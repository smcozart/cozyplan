"""Tests for the two steering hooks — the layer that makes the tool notice its own
drift instead of waiting for a human to ask.

  steer_build.py   UserPromptSubmit — surfaces the active plan's re-entry point, so
                   build work routes through the workflow without being asked to.
  report_drift.py  SessionStart — runs doctor/state check and speaks only on gaps.

Both are stdin/stdout protocols, so they run as subprocesses (conftest.run_hook).
The property that matters most for both is SILENCE: a hook that talks on every turn
in every repo gets muted by the human, and then it is worth nothing when it matters.
"""
from __future__ import annotations

import json

from conftest import DRIFT_HOOK, STEER_HOOK, run_hook


def context(result) -> "str | None":
    """The additionalContext a hook injected, or None if it stayed silent."""
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def wire_plan(pt, tmp_path, specs, filled_plan, name="build-me", status="active"):
    """A plan at `status` with a generated index beside it — the shape both hooks read."""
    plan = filled_plan(name)
    assert pt.main(["meta", str(plan), "--field", "status", "--value", status]) == 0
    assert pt.main(["index", "--specs", str(specs), "--root", str(tmp_path)]) == 0
    return plan


# ── registration ─────────────────────────────────────────────────────────────

def test_install_registers_all_four_hooks(pt, tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart"}
    assert "steer_build.py" in hooks["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert "report_drift.py" in hooks["SessionStart"][0]["hooks"][0]["command"]


def test_session_and_prompt_events_carry_no_matcher(pt, tmp_path):
    """A matcher on a non-tool event is a filter Claude Code ignores — writing one
    reads as scoping that is silently doing nothing. Tool events still carry theirs."""
    settings = tmp_path / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert "matcher" not in hooks["UserPromptSubmit"][0]
    assert "matcher" not in hooks["SessionStart"][0]
    assert hooks["PreToolUse"][0]["matcher"] == "Edit|MultiEdit|Write"


def test_remove_strips_the_new_events_too(pt, tmp_path):
    settings = tmp_path / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    assert pt.main(["hooks", "remove", "--settings", str(settings)]) == 0
    assert "hooks" not in json.loads(settings.read_text(encoding="utf-8"))


# ── steer_build ──────────────────────────────────────────────────────────────

def test_steer_is_silent_outside_a_cozyplan_repo(tmp_path):
    assert context(run_hook(STEER_HOOK, {"cwd": str(tmp_path), "prompt": "hi"})) is None


def test_steer_surfaces_the_active_plans_reentry_point(pt, tmp_path, specs, filled_plan):
    wire_plan(pt, tmp_path, specs, filled_plan, "build-me")
    ctx = context(run_hook(STEER_HOOK, {"cwd": str(tmp_path), "prompt": "add the login form"}))
    assert ctx is not None
    assert "build-me" in ctx
    assert "phase-1" in ctx          # first non-terminal marker, what `next` returns
    assert "Build Plan" in ctx       # names the workflow, not just the state


def test_steer_ignores_plans_that_are_not_active(pt, tmp_path, specs, filled_plan):
    """A draft is being written, not built. Steering toward Build Plan on a draft
    would push the agent to implement a plan that is not finished."""
    wire_plan(pt, tmp_path, specs, filled_plan, "still-drafting", status="draft")
    assert context(run_hook(STEER_HOOK, {"cwd": str(tmp_path), "prompt": "go"})) is None


def test_steer_is_silent_when_the_plan_is_finished(pt, tmp_path, specs, filled_plan):
    """`next` returns "done" when every marker is terminal — nothing to re-enter."""
    plan = wire_plan(pt, tmp_path, specs, filled_plan, "all-done")
    ids = [sid for sid, _ in pt.iter_status_markers(pt.read(plan))]
    for sid in ids:
        assert pt.main(["status", str(plan), "--id", sid, "--state", "x"]) == 0
    assert context(run_hook(STEER_HOOK, {"cwd": str(tmp_path), "prompt": "go"})) is None


# ── report_drift ─────────────────────────────────────────────────────────────

def test_drift_is_silent_outside_a_cozyplan_repo(tmp_path):
    assert context(run_hook(DRIFT_HOOK, {"cwd": str(tmp_path)})) is None


def test_drift_reports_gaps_in_a_half_wired_repo(git_repo):
    """The case a human cannot see: a clone that arrived without its wiring. An event
    log with no STATE.md, no CI, and no union-merge attribute is exactly that."""
    (git_repo / "docs").mkdir(exist_ok=True)
    (git_repo / "docs" / "state.ndjson").write_text(
        json.dumps({"kind": "claim", "what": "x"}) + "\n", encoding="utf-8")
    ctx = context(run_hook(DRIFT_HOOK, {"cwd": str(git_repo)}))
    assert ctx is not None
    assert "doctor" in ctx
    assert "STATE.md" in ctx                  # the gap itself
    assert "Do not silently work around this" in ctx


# ── both: fail open ──────────────────────────────────────────────────────────

def test_hooks_fail_open_on_a_malformed_payload():
    """A hook that crashes on bad stdin takes the session with it. Exit 0, say nothing."""
    for hook in (STEER_HOOK, DRIFT_HOOK):
        r = run_hook(hook, "not-a-dict")
        assert r.returncode == 0, f"{hook.name} did not fail open"
        assert r.stdout.strip() == ""


def test_hooks_fail_open_when_cwd_is_missing():
    for hook in (STEER_HOOK, DRIFT_HOOK):
        r = run_hook(hook, {})
        assert r.returncode == 0, f"{hook.name} did not fail open"
