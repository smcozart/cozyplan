#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse guard: role-ownership + CLI-managed-region enforcement.

Reads the Claude Code hook payload from stdin. Two composed checks on
Edit/MultiEdit/Write:

  1. Role ownership (any path). If PLANF3_ROLE is set and roles/_roles.json exists
     in the project cwd, deny writes to a path matching ANOTHER role's owned globs
     (deny-JSON names the owning role + escalation). Own-lane and unowned paths pass.
     Fail-open when PLANF3_ROLE is unset or the manifest is absent.
  2. Managed region (specs/*.html only). Allow Write to a new plan (Create
     authoring); deny Write over an existing plan; deny Edit/MultiEdit whose text
     touches a managed token (data-managed, data-meta=, class="status", amendments,
     or a bare status bracket), steering to plan_tool. Prose/diagram edits pass.

Fail-open: any unexpected error exits 0 so the hook never hard-blocks the agent.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

MANAGED_TOKENS = (
    'data-managed=',
    'data-meta=',
    'data-status-for=',
    'class="status"',
    'data-amendments-list',
    'id="amendments"',
)
STATUS_BRACKET = re.compile(r"\[(?:|wip|x|f)\]")

CLI_HINT = (
    "This edit touches a CLI-managed region of the plan (status markers, metadata, "
    "or amendments). Use plan_tool instead:\n"
    "  status:    uv run scripts/plan_tool.py status <plan> --id <id> --state wip|x|f\n"
    "  metadata:  uv run scripts/plan_tool.py meta <plan> --field <field> --value <v>\n"
    "  reference: uv run scripts/plan_tool.py ref --this <plan> --other <plan> --dir back|forward\n"
    "  amendment: uv run scripts/plan_tool.py amend <plan> --summary \"…\" --detail \"…\"\n"
    "Free-form prose (Purpose/Problem/Solution/Notes) and diagrams may be edited normally."
)


def is_plan_path(fp: str) -> bool:
    if not fp:
        return False
    p = Path(fp.replace("\\", "/"))
    return p.suffix.lower() == ".html" and "specs" in p.parts


def _glob_match(rel: str, glob: str) -> bool:
    # Normalize `**` to `*`; fnmatch's `*` already spans `/`, giving prefix ownership.
    g = glob.replace("\\", "/").replace("/**", "/*").replace("**", "*")
    return fnmatch.fnmatch(rel, g)


def _rel_posix(fp: str, cwd: Path) -> str:
    p = Path(fp.replace("\\", "/"))
    try:
        return p.resolve().relative_to(cwd.resolve()).as_posix()
    except (ValueError, OSError):
        return p.as_posix()


def role_denial(payload: dict, fp: str):
    """Return (owning_role, matched_glob) if the acting role may not touch fp, else None."""
    acting = os.environ.get("PLANF3_ROLE")
    if not acting:
        return None  # fail-open: roles not in use this session
    cwd = Path(payload.get("cwd") or ".")
    manifest = cwd / "roles" / "_roles.json"
    if not manifest.exists():
        return None  # fail-open: no manifest
    try:
        roles = json.loads(manifest.read_text(encoding="utf-8")).get("roles", {})
    except (json.JSONDecodeError, OSError):
        return None
    rel = _rel_posix(fp, cwd)
    if any(_glob_match(rel, g) for g in roles.get(acting, {}).get("owns", [])):
        return None  # in the acting role's own lane
    for role, info in roles.items():
        if role == acting:
            continue
        for g in info.get("owns", []):
            if _glob_match(rel, g):
                return role, g
    return None


def role_msg(owner: str, glob: str) -> str:
    acting = os.environ.get("PLANF3_ROLE")
    return (f"Role boundary: '{acting}' may not edit this path — it is owned by role "
            f"'{owner}' (matches its glob '{glob}'). Do not edit another role's lane. "
            f"Escalate to the architect, or ask '{owner}' to make the change.")


def touches_managed(text: str) -> bool:
    if not text:
        return False
    if any(tok in text for tok in MANAGED_TOKENS):
        return True
    return bool(STATUS_BRACKET.search(text))


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail-open

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    fp = ti.get("file_path", "")
    if tool not in ("Edit", "MultiEdit", "Write"):
        return 0

    # 1. Role ownership — applies to ANY path (src, docs, specs, roles, …).
    if fp:
        denial = role_denial(payload, fp)
        if denial:
            deny(role_msg(*denial))

    # 2. Managed-region check — specs/*.html only.
    if not is_plan_path(fp):
        return 0

    if tool == "Write":
        if Path(fp).exists():
            deny("Refusing full overwrite of an existing plan artifact. Edit free-form "
                 "sections in place, and route status/metadata/amendment writes through "
                 "plan_tool.\n" + CLI_HINT)
        return 0  # new file -> Create authoring, allow

    # Edit / MultiEdit: inspect the affected text.
    blobs = []
    if tool == "Edit":
        blobs = [ti.get("old_string", ""), ti.get("new_string", "")]
    else:  # MultiEdit
        for e in ti.get("edits", []) or []:
            blobs.append(e.get("old_string", ""))
            blobs.append(e.get("new_string", ""))

    if any(touches_managed(b) for b in blobs):
        deny(CLI_HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
