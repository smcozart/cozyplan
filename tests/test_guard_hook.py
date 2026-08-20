"""guard_plan_edit.py (PreToolUse): managed-region coherence for plan artifacts.

Driven as a subprocess with a JSON payload on stdin (the Claude Code hook protocol).
"""

import json
from pathlib import Path

import pytest

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


def _marker(task="1.1", state=""):
    return f'<code class="status" data-status-for="{task}">[{state}]</code>'


# ── managed-region checks (specs/*.html) ──────────────────────────────────────
def test_deny_edit_touching_status_marker(tmp_path):
    fp = _specs_html(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string=_marker(), new_string=_marker(state="wip"))
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


# ── path normalization (case / trailing-dot bypasses closed) ──────────────────
# On a case-insensitive filesystem SPECS/plan.html and specs/plan.html are the same
# file; a trailing dot (plan.html.) resolves to plan.html on Windows. The guard must
# treat all of these as the plan they are, not wave them through.
def _fs_is_case_insensitive(tmp_path) -> bool:
    probe = tmp_path / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    try:
        return (tmp_path / "caseprobe").exists()
    finally:
        probe.unlink()


def test_capitalized_specs_segment_still_guarded(tmp_path):
    """The bypass this closes only exists where the filesystem is case-insensitive.

    On macOS and Windows, SPECS/plan.html IS specs/plan.html, so a Write to it would
    overwrite the plan and must be denied. On Linux it is a genuinely different path
    that does not exist, so allowing it is correct: that is creating a new plan, not
    overwriting one. This test asserted the macOS outcome on every platform and only
    failed once CI ran it on a Linux runner for the first time."""
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip("case-sensitive filesystem: SPECS/plan.html is not the plan")
    d = tmp_path / "specs"
    d.mkdir(exist_ok=True)
    (d / "plan.html").write_text("existing", encoding="utf-8")
    payload = _payload("Write", tmp_path / "SPECS" / "plan.html", tmp_path,
                       content="PWNED")
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_capitalized_specs_segment_is_still_recognised_as_a_plan(tmp_path):
    """Platform-independent half: whatever the filesystem, an Edit through an
    upper-case SPECS segment must still reach the managed-region check."""
    d = tmp_path / "specs"
    d.mkdir(exist_ok=True)
    (d / "plan.html").write_text("existing", encoding="utf-8")
    payload = _payload("Edit", tmp_path / "SPECS" / "plan.html", tmp_path,
                       old_string=_marker(), new_string=_marker(state="wip"))
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_capitalized_html_edit_still_guarded(tmp_path):
    fp = _specs_html(tmp_path)
    payload = _payload("Edit", str(fp).replace("specs", "SPECS"), tmp_path,
                       old_string=_marker(), new_string=_marker(state="wip"))
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_non_specs_dir_not_guarded(tmp_path):
    # A .html outside any specs/ dir is not a plan — prose/docs edits pass.
    fp = tmp_path / "docs" / "notes.html"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("<html>notes</html>", encoding="utf-8")
    payload = _payload("Edit", fp, tmp_path,
                       old_string=_marker(), new_string=_marker(state="wip"))
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


# ── free-form regions stay editable (bracket forms that are not markers) ──────
# Purpose/Problem/Solution/Notes are prose. A bracket only counts as a status
# marker inside its <code class="status"> wrapper — code samples, type hints and
# markdown checkboxes must pass through a non-draft plan untouched.
def _nondraft(tmp_path):
    return _draft_plan(tmp_path, status="active")


def test_allow_code_sample_with_empty_subscript(tmp_path):
    fp = _nondraft(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<pre><code>rows = list()</code></pre>",
                       new_string="<pre><code>rows: list[] = []</code></pre>")
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


def test_allow_prose_type_hint(tmp_path):
    fp = _nondraft(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<p>Returns the row.</p>",
                       new_string="<p>Returns <code>Optional[x]</code> when absent.</p>")
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


def test_allow_markdown_checkbox_in_notes(tmp_path):
    fp = _nondraft(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<li>- [] chase the flake</li>",
                       new_string="<li>- [x] chase the flake</li>")
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


def test_allow_multiedit_of_prose_brackets(tmp_path):
    fp = _nondraft(tmp_path)
    payload = _payload("MultiEdit", fp, tmp_path, edits=[
        {"old_string": "<p>a</p>", "new_string": "<p>a <code>dict[x]</code></p>"},
        {"old_string": "<p>b</p>", "new_string": "<p>b <code>tuple[]</code></p>"},
    ])
    assert hook_decision(run_hook(GUARD_HOOK, payload)) is None


# ── genuine markers are still blocked ─────────────────────────────────────────
def test_nondraft_denies_wrapped_marker_in_new_string(tmp_path):
    fp = _nondraft(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string="<li data-task=\"1.1\">a</li>",
                       new_string=f'<li data-task="1.1">{_marker(state="x")} a</li>')
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_nondraft_denies_wrapped_marker_in_old_string(tmp_path):
    # Only old_string carries the marker — the guard inspects both sides.
    fp = _nondraft(tmp_path)
    payload = _payload("Edit", fp, tmp_path,
                       old_string=f'<li data-task="1.1">{_marker(state="x")} a</li>',
                       new_string="<li data-task=\"1.1\">a</li>")
    assert _is_deny(run_hook(GUARD_HOOK, payload))


def test_nondraft_denies_multiedit_with_one_marker(tmp_path):
    # A single managed edit poisons the batch, even alongside legitimate prose.
    fp = _nondraft(tmp_path)
    payload = _payload("MultiEdit", fp, tmp_path, edits=[
        {"old_string": "<p>a</p>", "new_string": "<p>a <code>list[]</code></p>"},
        {"old_string": _marker(), "new_string": _marker(state="f")},
    ])
    assert _is_deny(run_hook(GUARD_HOOK, payload))
