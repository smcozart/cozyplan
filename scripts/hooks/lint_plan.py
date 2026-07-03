#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PostToolUse: activity logging + plan validation after writes.

Reads the hook payload from stdin. Two independent, fail-open jobs:

  1. Activity log (impact tracking). When a project uses roles (roles/ exists and
     mode != off), append one event per impactful direct write (Edit/MultiEdit/
     Write, or a non-plan_tool Bash redirect) to roles/activity.log.ndjson. This is
     the surface `plan_tool rollup` reads for "ownership drift" — writes to a role's
     owned paths by someone else. Writes routed through plan_tool are NOT logged
     here (plan_tool already records them in the plan's .log.ndjson sidecar), so
     there is no double counting. Generated aggregates and *.log.ndjson are skipped.

  2. Validation. If the tool touched a specs/*.html file, run `plan_tool validate`
     and feed any problems back as additionalContext so the agent self-corrects.

Fail-open on any unexpected error.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HTML_IN_TEXT = re.compile(r'([^\s"\']*specs[\\/][^\s"\']*\.html)')
# Bash write targets: redirections, tee, cp/mv destinations.
BASH_WRITE = re.compile(r'(?:>>?|\btee\b|\bcp\b|\bmv\b)\s+["\']?([^\s"\'|;&]+)')

AGGREGATE_NAMES = {"_index.json", "_index.html", "_status.json", "_status.html",
                   "_roles.json", "CODEOWNERS", "activity.log.ndjson"}


def resolve_tool(project_root: Path) -> Path | None:
    """Locate plan_tool.py: prefer the bundled plugin copy (CLAUDE_PLUGIN_ROOT),
    fall back to the project's own scripts/ so the same script runs project-local
    or plugin-bundled."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        p = Path(plugin_root) / "scripts" / "plan_tool.py"
        if p.exists():
            return p
    p = project_root / "scripts" / "plan_tool.py"
    return p if p.exists() else None


def _load_plan_tool(project_root: Path):
    tool = resolve_tool(project_root)
    if tool is None:
        return None
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("_planf3_plan_tool_lint", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _rel_posix(fp: str, cwd: Path) -> str:
    p = Path(fp.replace("\\", "/"))
    try:
        return p.resolve().relative_to(cwd.resolve()).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


def _skip_path(rel: str) -> bool:
    name = Path(rel).name
    return name in AGGREGATE_NAMES or name.startswith("_") or name.endswith(".log.ndjson")


def write_targets(payload: dict) -> list[str]:
    """Absolute-ish paths this tool call wrote, as raw strings (pre-normalization)."""
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    if tool in ("Edit", "MultiEdit", "Write"):
        fp = ti.get("file_path", "")
        return [fp] if fp else []
    if tool == "Bash":
        cmd = ti.get("command", "")
        # plan_tool writes are recorded in the plan sidecar; don't double-log them.
        if "plan_tool" in cmd:
            return []
        return [m.group(1) for m in BASH_WRITE.finditer(cmd)]
    return []


def log_activity(payload: dict) -> None:
    """Append impactful-write events to roles/activity.log.ndjson (fail-open)."""
    cwd = Path(payload.get("cwd") or ".")
    roles_dir = cwd / "roles"
    manifest = roles_dir / "_roles.json"
    if not roles_dir.exists() or not manifest.exists():
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if data.get("mode", "track") == "off":
        return
    roles = data.get("roles", {})

    mod = _load_plan_tool(cwd)
    if mod is None:
        return
    glob_match = mod.glob_match

    def owned_globs(info, tiers):
        out = []
        for t in tiers:
            out.extend(info.get(t, []))
        return out

    def owner_of(rel):
        for role, info in roles.items():
            for g in owned_globs(info, ("source_of_truth", "code")):
                if glob_match(rel, g):
                    return role
        return None

    def impactful(rel):
        if rel.startswith("specs/") or rel.startswith("roles/"):
            return True
        for info in roles.values():
            for g in owned_globs(info, ("source_of_truth", "code", "supporting")):
                if glob_match(rel, g):
                    return True
        return False

    tool = payload.get("tool_name", "")
    session = payload.get("session_id")
    acting = os.environ.get("PLANF3_ROLE")
    ts = datetime.now().astimezone().isoformat(timespec="seconds")

    events = []
    for fp in write_targets(payload):
        rel = _rel_posix(fp, cwd)
        if _skip_path(rel) or not impactful(rel):
            continue
        events.append({"ts": ts, "path": rel, "tool": tool,
                       "role": acting, "session": session, "owner": owner_of(rel)})
    if not events:
        return
    with open(roles_dir / "activity.log.ndjson", "a", encoding="utf-8", newline="\n") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    try:
        log_activity(payload)
    except Exception:
        pass  # logging must never block or crash the agent

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
                ["uv", "run", str(tool_script), "validate", plan],
                capture_output=True, text=True, cwd=str(root), timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return 0  # uv missing / failed to launch -> fail-open
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
