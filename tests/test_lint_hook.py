"""lint_plan.py (PostToolUse): validate on plan writes, surface problems as context.

Driven as a subprocess. The hook itself shells out to `uv run plan_tool validate`,
so CLAUDE_PLUGIN_ROOT points it at the repo copy of plan_tool.py.
"""

import json

from conftest import LINT_HOOK, REPO, run_hook


def _payload(plan_path, cwd):
    return {"tool_name": "Edit", "tool_input": {"file_path": str(plan_path)},
            "cwd": str(cwd)}


def test_lint_surfaces_problem_on_broken_plan(pt, new_plan, specs, tmp_path):
    plan = new_plan("lint-bad")
    # non-draft with leftover {{}} tokens -> validate fails
    assert pt.main(["meta", str(plan), "--field", "status", "--value", "active"]) == 0
    result = run_hook(LINT_HOOK, _payload(plan, tmp_path),
                      env={"CLAUDE_PLUGIN_ROOT": str(REPO)})
    assert result.stdout.strip(), "expected additionalContext output"
    ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "FAILED" in ctx
    assert "lint-bad" in ctx


def test_lint_silent_on_clean_plan(pt, new_plan, specs, tmp_path):
    plan = new_plan("lint-good")  # fresh draft scaffold validates clean
    result = run_hook(LINT_HOOK, _payload(plan, tmp_path),
                      env={"CLAUDE_PLUGIN_ROOT": str(REPO)})
    assert result.stdout.strip() == ""


def test_lint_ignores_non_plan_path(tmp_path):
    fp = tmp_path / "notes.txt"
    fp.write_text("hello", encoding="utf-8")
    result = run_hook(LINT_HOOK, _payload(fp, tmp_path),
                      env={"CLAUDE_PLUGIN_ROOT": str(REPO)})
    assert result.stdout.strip() == ""
