"""Tests for `plan_tool hooks selftest` — the check that proves the hook layer ran.

The failure this closes: guard_plan_edit fails open on an unreadable payload, a
non-plan path and a new file. All three are correct, all three exit 0 in silence,
and silence is exactly what a hook that never ran produces. Three consecutive
probes therefore "passed" on a machine where the layer was inert.

So every test here asserts on an OBSERVED REACTION, and the important half of the
file asserts that selftest FAILS when the layer is dead. A check that cannot fail
is the thing being deleted, not the thing being added (ADR-0010).
"""
from __future__ import annotations

import json

import pytest


def _write_settings(pt, settings_path, command_for):
    hooks = {}
    for script, (event, matcher) in pt.HOOK_MATCHERS.items():
        blk = {"hooks": [{"type": "command", "command": command_for(script)}]}
        if matcher:
            blk["matcher"] = matcher
        hooks.setdefault(event, []).append(blk)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")


# ── the layer works ──────────────────────────────────────────────────────────

def test_shipped_hooks_all_produce_their_reaction(pt, tmp_path, capsys):
    """Every hook, launched the way the manifest launches it, must react."""
    assert pt.main(["hooks", "selftest", "--shipped", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "4/4 observed" in out
    # The guard's reaction is a refusal, not an exit code. Assert the refusal.
    assert "DENIED the edit" in out
    for script in pt.HOOK_MATCHERS:
        assert script in out


def test_registered_hooks_are_run_as_registered(pt, tmp_path, capsys):
    """selftest must drive the command the host actually registered — not its own
    resolution of what that command ought to be. They differ exactly when the
    clone is misconfigured, which is the only case worth reporting."""
    settings = tmp_path / ".claude" / "settings.json"
    hook_dir = pt.Path(pt.__file__).resolve().parent / "hooks"
    launcher = pt.PLUGIN_HOOKS_JSON.parent / "run-hook.sh"
    _write_settings(pt, settings, lambda s: (
        f'sh "{launcher.as_posix()}" "{(hook_dir / s).as_posix()}" {pt.HOOK_DEAD_EXIT[s]}'))
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "4/4 observed" in out
    assert "settings.json" in out


# ── the layer is dead, and the check says so ─────────────────────────────────

def test_unregistered_is_a_failure_not_a_pass(pt, tmp_path, capsys):
    """An unregistered layer is silent in exactly the way a broken one is."""
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    assert "nothing is registered" in capsys.readouterr().out


def test_registered_but_inert_hooks_fail(pt, tmp_path, capsys):
    """The regression that motivated the command: four hooks registered, every one
    a no-op exiting 0. That is byte-identical to an absent runner, and used to
    print as `all 4 registered` with nothing to contradict it."""
    settings = tmp_path / ".claude" / "settings.json"
    # Names the script (so it is found as registered) and does nothing (so it is
    # inert) — registration and behaviour pulled apart, which is the whole point.
    _write_settings(pt, settings, lambda s: f"true # {s}")
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "0/4 observed" in out
    assert out.count("SILENT") == len(pt.HOOK_MATCHERS)


def test_missing_hook_script_fails_loudly_with_the_right_exit_code(pt, tmp_path, capsys):
    """A stale or half-copied install. run-hook.sh must say the hook did not run,
    and must use the per-event dead exit code — 2 where blocking is safe, 1 on
    UserPromptSubmit, where exit 2 erases the user's prompt instead of reporting."""
    settings = tmp_path / ".claude" / "settings.json"
    launcher = pt.PLUGIN_HOOKS_JSON.parent / "run-hook.sh"
    _write_settings(pt, settings, lambda s: (
        f'sh "{launcher.as_posix()}" "/nonexistent/{s}" {pt.HOOK_DEAD_EXIT[s]}'))
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "0/4 observed" in out
    assert "hook script not found" in out
    assert "exit 2" in out   # guard_plan_edit / lint_plan
    assert "exit 1" in out   # steer_build / report_drift


# ── the fail-loud contract itself ────────────────────────────────────────────

def test_userpromptsubmit_never_gets_the_blocking_exit_code(pt):
    """Exit 2 on UserPromptSubmit does not report anything — it erases the user's
    prompt. Any hook on that event must use a non-blocking dead code."""
    for script, (event, _matcher) in pt.HOOK_MATCHERS.items():
        if event == "UserPromptSubmit":
            assert pt.HOOK_DEAD_EXIT[script] != 2, (
                f"{script} runs on UserPromptSubmit, where exit 2 erases the prompt")


def test_manifest_dead_exit_codes_match_the_table(pt):
    """hooks.json carries the dead exit code as a literal argument, so it can drift
    from HOOK_DEAD_EXIT silently. It is the difference between a blocked edit and
    an erased prompt, so it is asserted rather than trusted."""
    manifest = json.loads(pt.PLUGIN_HOOKS_JSON.read_text(encoding="utf-8"))
    seen = {}
    for _event, blocks in manifest["hooks"].items():
        for blk in blocks:
            for h in blk.get("hooks", []):
                cmd = h.get("command", "")
                for script in pt.HOOK_MATCHERS:
                    if script in cmd:
                        seen[script] = int(cmd.rsplit(None, 1)[-1])
    assert seen == pt.HOOK_DEAD_EXIT, (
        "hooks.json dead exit codes disagree with HOOK_DEAD_EXIT")


def test_manifest_launches_every_hook_through_the_resolver(pt):
    """The bug this replaces: hooks.json hardcoded `uv run`, so on a host without
    uv no hook started at all. Nothing may name an interpreter directly."""
    manifest = json.loads(pt.PLUGIN_HOOKS_JSON.read_text(encoding="utf-8"))
    for _event, blocks in manifest["hooks"].items():
        for blk in blocks:
            for h in blk.get("hooks", []):
                cmd = h.get("command", "")
                assert "run-hook.sh" in cmd, f"not launched through the resolver: {cmd}"
                assert not cmd.startswith("uv "), f"hardcodes an interpreter: {cmd}"


def test_resolver_script_ships_with_the_plugin(pt):
    launcher = pt.PLUGIN_HOOKS_JSON.parent / "run-hook.sh"
    assert launcher.exists(), "hooks/run-hook.sh must ship beside hooks.json"


# ── doctor and selftest must never disagree ──────────────────────────────────

def test_doctor_reports_the_outcome_not_only_the_record(pt, git_repo, capsys):
    """Two rows, and they must be able to disagree: a registered-but-inert layer
    is ok on the record and a gap on the outcome."""
    settings = git_repo / ".claude" / "settings.json"
    # Names the script (so it is found as registered) and does nothing (so it is
    # inert) — registration and behaviour pulled apart, which is the whole point.
    _write_settings(pt, settings, lambda s: f"true # {s}")
    rows = pt.doctor_checks(git_repo, 5)
    named = {name: (status, detail) for _sec, status, name, detail in rows}
    assert "hooks registered" in named and "hooks observed" in named
    assert named["hooks observed"][0] == pt.GAP, "an inert layer must be a gap"


@pytest.mark.parametrize("shipped", [True, False])
def test_selftest_never_touches_the_callers_repo(pt, tmp_path, shipped, capsys):
    """The fixture is a throwaway. A selftest whose result depends on whether this
    project happens to have an active plan today reports the repo's contents
    rather than whether the hook layer runs."""
    before = sorted(p.name for p in tmp_path.iterdir())
    argv = ["hooks", "selftest", "--root", str(tmp_path)] + (["--shipped"] if shipped else [])
    pt.main(argv)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
