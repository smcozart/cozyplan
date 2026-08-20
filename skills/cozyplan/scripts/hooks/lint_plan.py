#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""PostToolUse: validate a plan after any write, feeding problems back to the agent.

Reads the hook payload from stdin. If the tool touched a specs/*.html file, run
`plan_tool validate` and surface any problems as additionalContext so the agent
self-corrects. Fail-open on any unexpected error.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HTML_IN_TEXT = re.compile(r'([^\s"\']*specs[\\/][^\s"\']*\.html)')


def resolve_tool(project_root: Path) -> Path | None:
    """Locate plan_tool.py: prefer the copy that ships beside this hook (the
    skill directory moves as one unit — plugin install, `npx skills add`, or
    plain clone all keep scripts/hooks/ next to scripts/plan_tool.py), then the
    plugin root, then the project's own scripts/ (legacy layout)."""
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


def plan_paths_from_payload(payload: dict) -> list[str]:
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    found: list[str] = []
    fp = ti.get("file_path", "")
    if fp and fp.replace("\\", "/").endswith(".html") and "specs" in Path(fp.replace("\\", "/")).parts:
        found.append(fp)
    if tool == "Bash":
        cmd = ti.get("command", "")
        found.extend(m.group(1) for m in HTML_IN_TEXT.finditer(cmd))
    # de-dup, keep existing files only
    out = []
    for p in dict.fromkeys(found):
        if Path(p).exists():
            out.append(p)
    return out


def runner(tool_script: Path) -> list[str]:
    """plan_tool declares `dependencies = []`, so a plain interpreter runs it.
    Prefer uv when it is on PATH; otherwise fall back to the interpreter running
    this hook, so a host without uv still gets validation instead of silence."""
    if shutil.which("uv"):
        return ["uv", "run", str(tool_script)]
    return [sys.executable, str(tool_script)]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    plans = plan_paths_from_payload(payload)
    if not plans:
        return 0

    root = Path(payload.get("cwd") or ".")  # project root (where the plan data lives)
    tool_script = resolve_tool(root)
    if tool_script is None:
        return 0  # fail-open: tool not present

    messages = []
    for plan in plans:
        try:
            r = subprocess.run(
                runner(tool_script) + ["validate", plan],
                capture_output=True, text=True, cwd=str(root), timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return 0  # interpreter failed to launch -> fail-open
        if r.returncode != 0:
            messages.append(f"plan_tool validate FAILED for {plan}:\n{r.stdout.strip()}")

    if messages:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(messages)
                + "\n\nFix via plan_tool (do not hand-edit managed regions).",
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
