#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""SessionStart: report cozyplan's own health, so drift surfaces before work starts.

Reads the hook payload from stdin. Runs the two checks that already know whether
this repo is wired and whether its snapshot still matches git — `doctor --strict`
and `state check` — and injects their output as additionalContext only when one
of them fails. A healthy repo produces nothing.

Once per session, not per turn: this catches "this clone arrived broken" (hooks
never installed, CI absent, thin trailer coverage), which is the case a human
cannot see and would otherwise carry for weeks. Drift introduced *during* a
session is already caught by lint_plan on every write and by CI on push.

Fail-open on any unexpected error: a health check that blocks a session is worse
than one that stays quiet.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT = 60


def resolve_tool(project_root: Path) -> Path | None:
    """Locate plan_tool.py: prefer the copy that ships beside this hook (the
    skill directory moves as one unit), then the plugin root, then the project's
    own scripts/ (legacy layout)."""
    sibling = Path(__file__).resolve().parents[1] / "plan_tool.py"
    if sibling.exists():
        return sibling
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        for rel in ("skills/cozyplan/scripts/plan_tool.py", "scripts/plan_tool.py"):
            p = Path(plugin_root) / rel
            if p.exists():
                return p
    p = project_root / "scripts" / "plan_tool.py"
    return p if p.exists() else None


def runner(tool_script: Path) -> list[str]:
    """plan_tool declares `dependencies = []`, so a plain interpreter runs it.
    Prefer uv when it is on PATH; otherwise fall back to the interpreter running
    this hook, so a host without uv still gets a report instead of silence."""
    if shutil.which("uv"):
        return ["uv", "run", str(tool_script)]
    return [sys.executable, str(tool_script)]


def run(cmd: list[str], root: Path) -> "tuple[int, str] | None":
    try:
        # stdin=DEVNULL, never inherited: this hook's own stdin is the payload stream
        # and is already consumed, and handing a live console handle to a child lets it
        # invalidate the one every later subprocess inherits.
        r = subprocess.run(cmd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, cwd=str(root), timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None  # interpreter failed to launch -> fail-open
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0  # valid JSON, wrong shape -> fail open like a parse error

    root = Path(payload.get("cwd") or ".")
    # Not a cozyplan repo -> nothing to report. The event log is the one artifact
    # every wired repo has and no other tool creates.
    if not (root / "docs" / "state.ndjson").exists():
        return 0

    tool_script = resolve_tool(root)
    if tool_script is None:
        return 0  # fail-open: tool not present

    base = runner(tool_script)
    problems = []

    doc = run(base + ["doctor", "--strict", "--root", str(root)], root)
    if doc is None:
        return 0
    if doc[0] != 0:
        problems.append("plan_tool doctor --strict reports gaps:\n" + doc[1].strip())

    chk = run(base + ["state", "check", "--root", str(root)], root)
    if chk is not None and chk[0] != 0:
        problems.append("plan_tool state check FAILED:\n" + chk[1].strip())

    if not problems:
        return 0  # healthy -> say nothing

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "cozyplan health — this repo's planning layer is not fully wired "
                "or its state has drifted:\n\n" + "\n\n".join(problems)
                + "\n\nTell the user what is broken and what fixes it before doing "
                  "plan or build work. Gaps are absent wiring, not preferences: "
                  "`plan_tool init` closes most of them, `hooks git-install` is a "
                  "per-clone step, and a stale snapshot is repaired with "
                  "`plan_tool state render`. Do not silently work around this."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
