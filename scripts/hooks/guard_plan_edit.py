#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse guard: managed-region integrity + role-ownership (mode-driven).

Reads the Claude Code hook payload from stdin. Two composed checks on
Edit/MultiEdit/Write:

  1. Managed region (specs/*.html only) — the INTEGRITY layer, always on for
     everyone regardless of roles. Allow Write to a new plan (Create authoring);
     deny Write over an existing plan; deny Edit/MultiEdit whose text touches a
     managed token (data-managed, data-meta=, class="status", amendments, or a
     bare status bracket), steering to plan_tool. Prose/diagram edits pass.

  2. Role ownership (any path) — driven by roles/_roles.json `mode`:
       off / no manifest / no roles dir : fail-open, no role logic.
       track                            : no denies (impact is logged post-write).
       protect                          : deny ONLY when the acting role (PLANF3_ROLE)
                                          is set, is not `architect`, and the target
                                          matches ANOTHER role's source_of_truth globs.
     Everything else — code paths, supporting, unowned, roleless sessions, the
     architect — is allowed. This is "coherence, not compliance": only integrity
     and cross-role source-of-truth writes are ever blocked.

The role matcher is plan_tool.glob_match — the SAME function roles-build uses for
disjointness — so build time and enforce time never disagree. If plan_tool cannot
be located the role layer fails open.

Fail-open: any unexpected error exits 0 so the hook never hard-blocks the agent.
"""

import importlib.util
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
    "  reference: uv run scripts/plan_tool.py ref --this <plan> --other <plan> --type back|forward|provides|consumes\n"
    "  amendment: uv run scripts/plan_tool.py amend <plan> --summary \"…\" --detail \"…\"\n"
    "Free-form prose (Purpose/Problem/Solution/Notes) and diagrams may be edited normally."
)


def is_plan_path(fp: str) -> bool:
    if not fp:
        return False
    p = Path(fp.replace("\\", "/"))
    return p.suffix.lower() == ".html" and "specs" in p.parts


def _load_glob_match(cwd: Path):
    """Return plan_tool.glob_match (the single shared matcher), or None if unlocatable."""
    candidates = []
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if pr:
        candidates.append(Path(pr) / "scripts" / "plan_tool.py")
    candidates.append(cwd / "scripts" / "plan_tool.py")
    candidates.append(Path(__file__).resolve().parent.parent / "plan_tool.py")
    for c in candidates:
        if not c.exists():
            continue
        try:
            sys.dont_write_bytecode = True
            spec = importlib.util.spec_from_file_location("_planf3_plan_tool_guard", c)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.glob_match
        except Exception:
            continue
    return None


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
        return None  # roleless session -> allow (logged post-write)
    cwd = Path(payload.get("cwd") or ".")
    roles_dir = cwd / "roles"
    manifest = roles_dir / "_roles.json"
    if not roles_dir.exists() or not manifest.exists():
        return None  # fail-open: roles not in use
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    mode = data.get("mode", "track")
    if mode != "protect":
        return None  # off / track -> no denies
    if acting == "architect":
        return None  # architect is never denied by the role layer
    glob_match = _load_glob_match(cwd)
    if glob_match is None:
        return None  # cannot enforce without the shared matcher -> fail-open
    roles = data.get("roles", {})
    rel = _rel_posix(fp, cwd)
    # Deny only on ANOTHER role's source-of-truth. Disjointness (build-time) means
    # this cannot also be the acting role's own SoT/code, so no self-conflict.
    for role, info in roles.items():
        if role == acting:
            continue
        for g in info.get("source_of_truth", []):
            if glob_match(rel, g):
                return role, g
    return None


def role_msg(owner: str, glob: str) -> str:
    acting = os.environ.get("PLANF3_ROLE")
    return (f"Role boundary: '{acting}' may not edit this path — it is the source of truth "
            f"owned by role '{owner}' (matches its glob '{glob}'). Do not edit another role's "
            f"source of truth. File a change request: "
            f"uv run scripts/plan_tool.py report <{owner}'s plan> --status request "
            f"--summary \"…\", or escalate to the architect.")


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

    # 2. Managed-region check — specs/*.html only (integrity layer, always on).
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
