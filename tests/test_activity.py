"""PostToolUse activity logging: impactful direct writes land in
roles/activity.log.ndjson; plan_tool-routed and off-mode writes do not."""

import json

from conftest import LINT_HOOK, REPO, run_hook


def _roles(tmp_path, mode="track"):
    rd = tmp_path / "roles"
    rd.mkdir()
    (rd / "_roles.json").write_text(json.dumps({
        "mode": mode, "acceptance": "manual",
        "roles": {"engineer-api": {"source_of_truth": ["specs/api-*.html"],
                                   "code": ["src/api/**"], "supporting": [],
                                   "owns": ["src/api/**"]}}}), encoding="utf-8")
    return rd


def _edit(tmp_path, rel):
    return {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / rel)},
            "cwd": str(tmp_path), "session_id": "sess-1"}


def _events(rd):
    log = rd / "activity.log.ndjson"
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_activity_logs_impactful_edit(tmp_path):
    rd = _roles(tmp_path)
    (tmp_path / "specs").mkdir()
    run_hook(LINT_HOOK, _edit(tmp_path, "specs/api-foo.html"),
             env={"CLAUDE_PLUGIN_ROOT": str(REPO), "PLANF3_ROLE": "ux"})
    evs = _events(rd)
    assert len(evs) == 1
    assert evs[0]["path"] == "specs/api-foo.html"
    assert evs[0]["role"] == "ux"
    assert evs[0]["owner"] == "engineer-api"  # api-* is engineer-api's SoT
    assert evs[0]["session"] == "sess-1"


def test_activity_skips_generated_aggregates(tmp_path):
    rd = _roles(tmp_path)
    (tmp_path / "specs").mkdir()
    run_hook(LINT_HOOK, _edit(tmp_path, "specs/_index.json"),
             env={"CLAUDE_PLUGIN_ROOT": str(REPO), "PLANF3_ROLE": "ux"})
    assert _events(rd) == []


def test_activity_skips_plan_tool_bash(tmp_path):
    rd = _roles(tmp_path)
    payload = {"tool_name": "Bash",
               "tool_input": {"command": "uv run scripts/plan_tool.py status "
                                         "specs/api-foo.html --id 1.1 --state wip"},
               "cwd": str(tmp_path), "session_id": "s"}
    run_hook(LINT_HOOK, payload, env={"CLAUDE_PLUGIN_ROOT": str(REPO), "PLANF3_ROLE": "ux"})
    assert _events(rd) == []  # plan_tool logs to the sidecar; no double count


def test_activity_off_mode_logs_nothing(tmp_path):
    rd = _roles(tmp_path, mode="off")
    (tmp_path / "specs").mkdir()
    run_hook(LINT_HOOK, _edit(tmp_path, "specs/api-foo.html"),
             env={"CLAUDE_PLUGIN_ROOT": str(REPO), "PLANF3_ROLE": "ux"})
    assert _events(rd) == []


def test_activity_no_roles_dir_logs_nothing(tmp_path):
    # no roles/ at all -> role layer dormant, no activity file created
    (tmp_path / "specs").mkdir()
    run_hook(LINT_HOOK, _edit(tmp_path, "specs/api-foo.html"),
             env={"CLAUDE_PLUGIN_ROOT": str(REPO), "PLANF3_ROLE": "ux"})
    assert not (tmp_path / "roles" / "activity.log.ndjson").exists()
