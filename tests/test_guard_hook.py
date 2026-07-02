"""guard_plan_edit.py (PreToolUse): managed-region + role-ownership enforcement.

Driven as a subprocess with a JSON payload on stdin (the Claude Code hook protocol).
"""

import json

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


# ── role-ownership checks (any path) ──────────────────────────────────────────
def _manifest(tmp_path):
    rd = tmp_path / "roles"
    rd.mkdir(exist_ok=True)
    (rd / "_roles.json").write_text(json.dumps({"roles": {
        "ux": {"owns": ["src/ui/**", "specs/ux-*.html"]},
        "engineer-api": {"owns": ["src/api/**"]},
    }}), encoding="utf-8")


def test_role_denies_other_lane(tmp_path):
    _manifest(tmp_path)
    fp = tmp_path / "src" / "api" / "handler.py"
    payload = _payload("Write", fp, tmp_path, content="x = 1")
    result = run_hook(GUARD_HOOK, payload, env={"PLANF3_ROLE": "ux"})
    assert _is_deny(result)
    assert "engineer-api" in hook_decision(result)["permissionDecisionReason"]


def test_role_allows_own_lane(tmp_path):
    _manifest(tmp_path)
    fp = tmp_path / "src" / "api" / "handler.py"
    payload = _payload("Write", fp, tmp_path, content="x = 1")
    result = run_hook(GUARD_HOOK, payload, env={"PLANF3_ROLE": "engineer-api"})
    assert hook_decision(result) is None


def test_role_unset_fails_open(tmp_path):
    _manifest(tmp_path)
    fp = tmp_path / "src" / "api" / "handler.py"
    payload = _payload("Write", fp, tmp_path, content="x = 1")
    result = run_hook(GUARD_HOOK, payload)  # no PLANF3_ROLE
    assert hook_decision(result) is None
