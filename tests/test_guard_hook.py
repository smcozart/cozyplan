"""guard_plan_edit.py (PreToolUse): managed-region + role-ownership enforcement.

Driven as a subprocess with a JSON payload on stdin (the Claude Code hook protocol).
"""

import json
from pathlib import Path

from conftest import GUARD_HOOK, run_hook, hook_decision


def _specs_html(tmp_path, name="plan.html"):
    d = tmp_path / "specs"
    d.mkdir(exist_ok=True)
    return d / name


def _payload(tool, file_path, cwd, **ti):
    ti["file_path"] = str(file_path)
    return {"tool_name": tool, "tool_input": ti, "cwd": str(cwd)}


def _is_deny(result):
    d = hook_decision(result)
    return bool(d) and d.get("permissionDecision") == "deny"


# ── managed-region checks (specs/*.html) ──────────────────────────────────────
def test_deny_edit_touching_status_marker(tmp_path):
    fp = _specs_html(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<code>[]</code>", new_string="<code>[wip]</code>")
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_deny_write_over_existing_plan(tmp_path):
    fp = _specs_html(tmp_path)
    fp.write_text("<html>existing plan</html>", encoding="utf-8")
    payload = _payload("Write", fp, tmp_path, content="<html>new</html>")
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_allow_prose_edit(tmp_path):
    fp = _specs_html(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<p>old purpose text</p>",
                       new_string="<p>new purpose text</p>")
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None  # silent -> allow


def test_allow_new_file_write(tmp_path):
    fp = _specs_html(tmp_path, "brand-new.html")  # does not exist
    payload = _payload("Write", fp, tmp_path, content="<html>fresh scaffold</html>")
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


# ── draft authoring window (Create workflow on a `new` scaffold) ──────────────
def _draft_plan(tmp_path, status="draft"):
    fp = _specs_html(tmp_path, "draft.html")
    fp.write_text(
        '<html><body><main>\n'
        '<dl><dt>status</dt> <dd data-meta="status">' + status + '</dd></dl>\n'
        '<div class="phase" data-phase="1">\n'
        '<h3><code class="status" data-status-for="phase-1">[]</code> Phase 1: X</h3>\n'
        '<li data-task="1.1"><code class="status" data-status-for="1.1">[]</code> a</li>\n'
        '</div>\n'
        '<section id="amendments" data-region="amendments" data-managed="cli">\n'
        '<div data-amendments-list></div></section>\n'
        '</main></body></html>', encoding="utf-8")
    return fp


_STRUCTURAL_OLD = '<li data-task="1.1"><code class="status" data-status-for="1.1">[]</code> a</li>'
_STRUCTURAL_NEW = (_STRUCTURAL_OLD +
                   '\n<li data-task="1.2"><code class="status" data-status-for="1.2">[]</code> b</li>')


def test_draft_allows_structural_authoring(tmp_path):
    fp = _draft_plan(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string=_STRUCTURAL_OLD, new_string=_STRUCTURAL_NEW)
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


def test_nondraft_denies_structural_authoring(tmp_path):
    fp = _draft_plan(tmp_path, status="active")
    payload = _payload("Edit", fp, tmp_path,
                       old_string=_STRUCTURAL_OLD, new_string=_STRUCTURAL_NEW)
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_draft_allows_marker_text(tmp_path):
    # Marker values are meaningless until Build (which requires leaving draft),
    # and phase loop prose contains literal [x]/[f] — so draft edits may carry
    # bracket forms. Post-draft, test_deny_edit_touching_status_marker applies.
    fp = _draft_plan(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string='data-status-for="1.1">[]',
                       new_string='data-status-for="1.1">[x]')
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


def test_nondraft_denies_marker_flip(tmp_path):
    fp = _draft_plan(tmp_path, status="built")
    payload = _payload("Edit", fp, tmp_path,
                       old_string='data-status-for="1.1">[]',
                       new_string='data-status-for="1.1">[x]')
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_draft_denies_metadata_edit(tmp_path):
    fp = _draft_plan(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string='<dd data-meta="status">draft</dd>',
                       new_string='<dd data-meta="status">active</dd>')
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_draft_denies_amendments_edit(tmp_path):
    fp = _draft_plan(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string='<div data-amendments-list></div>',
                       new_string='<div data-amendments-list><details>x</details></div>')
    assert _is_deny(run_hook(GUARD_HOOK, payload))


# ── role-ownership checks (any path, mode-driven) ─────────────────────────────
def _manifest(tmp_path, mode="protect"):
    rd = tmp_path / "roles"
    rd.mkdir(exist_ok=True)
    (rd / "_roles.json").write_text(json.dumps({
        "mode": mode, "acceptance": "manual",
        "roles": {
            "ux": {"source_of_truth": ["specs/ux-*.html"], "code": ["src/ui/**"],
                   "supporting": []},
            "engineer-api": {"source_of_truth": ["specs/api-*.html"], "code": ["src/api/**"],
                             "supporting": []},
        }}), encoding="utf-8")


def _write(tmp_path, rel):
    fp = tmp_path / Path(rel)
    return _payload("Write", fp, tmp_path, content="x = 1")


def test_protect_denies_other_role_sot(tmp_path):
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/api-foo.html"),
                      env={"PLANF3_ROLE": "ux"})
    assert _is_deny(result)
    assert "engineer-api" in hook_decision(result)["permissionDecisionReason"]


def test_protect_allows_own_sot(tmp_path):
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/ux-foo.html"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None


def test_protect_allows_other_role_code(tmp_path):
    # Deny scope is source_of_truth ONLY — another role's CODE is allowed (+ logged).
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "src/api/handler.py"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None


def test_protect_allows_unowned_path(tmp_path):
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "README.md"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None


def test_protect_architect_bypasses_role_layer(tmp_path):
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/api-foo.html"),
                      env={"PLANF3_ROLE": "architect"})
    assert hook_decision(result) is None


def test_track_never_denies(tmp_path):
    _manifest(tmp_path, mode="track")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/api-foo.html"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None


def test_off_never_denies(tmp_path):
    _manifest(tmp_path, mode="off")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/api-foo.html"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None


def test_role_unset_fails_open(tmp_path):
    _manifest(tmp_path, mode="protect")
    result = run_hook(GUARD_HOOK, _write(tmp_path, "specs/api-foo.html"))  # no PLANF3_ROLE
    assert hook_decision(result) is None


def test_no_manifest_fails_open(tmp_path):
    (tmp_path / "src" / "api").mkdir(parents=True)
    result = run_hook(GUARD_HOOK, _write(tmp_path, "src/api/handler.py"),
                      env={"PLANF3_ROLE": "ux"})
    assert hook_decision(result) is None
