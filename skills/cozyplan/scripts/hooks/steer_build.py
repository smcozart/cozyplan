#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""UserPromptSubmit: surface the active plan's re-entry point on every turn.

Reads the hook payload from stdin. In a repo with an active plan, injects the
plan id and the phase `plan_tool next` returns as additionalContext, so build
work routes through the Build Plan workflow without the human having to say so.

Deliberately does NOT classify the prompt. A regex deciding that "add the login
form" is build work but "what does this do" is not gets it wrong in both
directions, and a missed phase flip is the expensive error. Two lines on every
turn is the cheaper trade. Silent when no plan is active, so a repo between
plans pays nothing.

Fail-open on any unexpected error.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


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
    this hook, so a host without uv still gets steering instead of silence."""
    if shutil.which("uv"):
        return ["uv", "run", str(tool_script)]
    return [sys.executable, str(tool_script)]


def active_plans(root: Path) -> list[dict]:
    """Plans marked active in the generated index. Missing index -> not a
    cozyplan repo -> nothing to say."""
    index = root / "specs" / "_index.json"
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data.get("plans", []) if p.get("status") == "active"]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0  # valid JSON, wrong shape -> fail open like a parse error

    root = Path(payload.get("cwd") or ".")
    plans = active_plans(root)
    if not plans:
        return 0

    tool_script = resolve_tool(root)
    if tool_script is None:
        return 0  # fail-open: tool not present

    lines = []
    for p in plans:
        plan_path = root / "specs" / p.get("file", "")
        if not plan_path.exists():
            continue
        try:
            # stdin=DEVNULL, never inherited — see report_drift.py.
            r = subprocess.run(
                runner(tool_script) + ["next", str(plan_path)],
                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                cwd=str(root), timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return 0  # interpreter failed to launch -> fail-open
        if r.returncode != 0:
            continue
        where = r.stdout.strip()
        if where and where != "done":
            lines.append(f"- {p.get('id')} — re-entry at {where}")

    if not lines:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "cozyplan — plans in flight:\n" + "\n".join(lines)
                + "\n\nIf this turn implements any of that work, run the Build Plan "
                  "workflow (cozyplan skill) rather than editing directly. It resumes "
                  "at the phase above, flips markers through plan_tool, and syncs state "
                  "at the end. Never hand-edit managed regions of specs/*.html."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
