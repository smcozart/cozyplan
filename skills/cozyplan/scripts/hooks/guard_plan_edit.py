#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse guard: managed-region COHERENCE for plan artifacts.

Reads the Claude Code hook payload from stdin. On Edit/MultiEdit/Write to a
plan (specs/*.html), it steers CLI-managed writes through plan_tool so the
machine-readable regions (status markers, metadata, amendments) stay
well-formed. Prose/diagram edits pass untouched.

  - Allow Write to a NEW plan (Create authoring); deny Write over an existing
    plan (route structured writes through plan_tool).
  - Deny Edit/MultiEdit whose text touches a managed token (data-managed,
    data-meta=, class="status", amendments, or a wrapped status marker).
  - Draft authoring window: while the plan's status is `draft` (the state
    `plan_tool new` stamps), STRUCTURAL authoring is allowed — duplicating /
    renumbering phase/task blocks with their anchors and markers — because the
    Create workflow requires it (and phase loop prose legitimately contains
    [x]/[f] literals a substring heuristic can't tell from markers). Metadata
    (data-meta=) and the amendments region stay CLI-only in every status; once
    the plan leaves draft, full strictness resumes.

WHAT THIS IS — and is NOT. This is a COHERENCE layer: it keeps a *cooperative*
agent routing structured writes through plan_tool, so plans stay well-formed and
diffable. It is deliberately NOT a tamper-proof boundary — a hook only sees
Edit/MultiEdit/Write, so a Bash/`sed`/redirect write (or any out-of-tool edit)
bypasses it by design. Real accountability and revert points are git's job
(branches, PRs, CODEOWNERS, tags). Do not rely on this to *prevent* a determined
writer; rely on it to keep an honest one consistent.

Fail-open: any unexpected error exits 0 so the hook never hard-blocks the agent.
"""

import json
import os
import re
import shlex
import shutil
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
# A bracket is only a status marker when it sits in its <code class="status">
# wrapper. Bare bracket forms are ordinary prose — `list[]` in a code sample,
# `Optional[x]` in a sentence, a markdown checkbox in Notes — and the guard
# leaves the free-form regions alone.
STATUS_BRACKET = re.compile(r'<code\b[^>]*class="status"[^>]*>\s*\[(?:|wip|x|f)\]')

# Tokens that stay CLI-only even while a plan is in draft: metadata and the
# amendments region. Structure (anchors, markers) is authorable during the
# Create workflow's draft window — marker values carry no meaning until Build,
# which requires the plan to have left draft.
DRAFT_HARD_TOKENS = (
    'data-managed=',
    'data-meta=',
    'data-amendments-list',
    'id="amendments"',
)

# plan_tool declares `dependencies = []`, so a plain interpreter runs it. Prefer
# uv when it is on PATH; otherwise name this interpreter, so the hint stays a
# command the agent can actually run rather than a block with no remedy.
_RUN = "uv run" if shutil.which("uv") else shlex.quote(sys.executable)

# The hint must point at a plan_tool that actually exists where the agent runs.
# plan_tool.py ships beside this hook (the skill directory moves as one unit),
# so the sibling copy is authoritative; fall back to the plugin root, then the
# legacy project-local scripts/ layout.
_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").rstrip("/\\")
_SIBLING = Path(__file__).resolve().parents[1] / "plan_tool.py"
if _SIBLING.exists():
    _TOOL = f'{_RUN} "{_SIBLING}"'
elif _PLUGIN_ROOT:
    _TOOL = f'{_RUN} "{_PLUGIN_ROOT}/skills/cozyplan/scripts/plan_tool.py"'
else:
    _TOOL = f"{_RUN} scripts/plan_tool.py"

CLI_HINT = (
    "This edit touches a CLI-managed region of the plan (status markers, metadata, "
    "or amendments). Use plan_tool instead:\n"
    f"  status:    {_TOOL} status <plan> --id <id> --state wip|x|f\n"
    f"  metadata:  {_TOOL} meta <plan> --field <field> --value <v>\n"
    f"  reference: {_TOOL} ref --this <plan> --other <plan> --type back|forward\n"
    f"  amendment: {_TOOL} amend <plan> --summary \"…\" --detail \"…\"\n"
    "Free-form prose (Purpose/Problem/Solution/Notes) and diagrams may be edited normally."
)


def is_plan_path(fp: str) -> bool:
    """True if fp names a plan (specs/*.html), robust to case-insensitive
    filesystems and trailing dots that resolve to the same file (Windows).

    Checks both the raw path and its resolved form, matches `specs` case-
    insensitively, and ignores trailing dots/spaces on the filename — so
    `SPECS/plan.html` and `specs/plan.html.` are treated as the plan they are.
    """
    if not fp:
        return False
    raw = Path(fp.replace("\\", "/"))
    candidates = [raw]
    try:
        candidates.append(raw.resolve())
    except (OSError, RuntimeError):
        pass
    for p in candidates:
        parts_lower = [seg.lower() for seg in p.parts]
        name = p.name.rstrip(". ")  # Windows ignores trailing dots/spaces
        if name.lower().endswith(".html") and "specs" in parts_lower:
            return True
    return False


def touches_managed(text: str) -> bool:
    if not text:
        return False
    if any(tok in text for tok in MANAGED_TOKENS):
        return True
    return bool(STATUS_BRACKET.search(text))


def plan_is_draft(fp: str) -> bool:
    try:
        text = Path(fp).read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.search(r'data-meta="status"[^>]*>\s*([A-Za-z-]+)', text)
    return bool(m) and m.group(1).lower() == "draft"


def draft_structural_ok(text: str) -> bool:
    """Draft-window authoring may add/renumber phase/task anchors and markers
    (phase loop prose legitimately contains [x]/[f] literals, so bracket forms
    cannot be distinguished from prose here); metadata and the amendments
    region stay CLI-only in every status."""
    if not text:
        return True
    return not any(tok in text for tok in DRAFT_HARD_TOKENS)


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

    # Managed-region coherence — specs/*.html only.
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
        # Draft authoring window: the Create workflow duplicates phase/task
        # blocks (anchors + idle [] markers) on the `new` scaffold via Edit.
        if plan_is_draft(fp) and all(draft_structural_ok(b) for b in blobs):
            return 0
        deny(CLI_HINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
