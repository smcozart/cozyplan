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
    launcher = pt.hook_launcher()
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
    launcher = pt.hook_launcher()
    _write_settings(pt, settings, lambda s: (
        f'sh "{launcher.as_posix()}" "/nonexistent/{s}" {pt.HOOK_DEAD_EXIT[s]}'))
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "0/4 observed" in out
    assert "hook script not found" in out
    # These are FAILED, not "REFUSED, NO REASON": run-hook.sh writes a reason before
    # exiting, which is the fail-loud contract holding. The per-event dead code must
    # still reach the report — it is the difference between a blocked edit and an
    # erased prompt.
    assert "exited 2" in out   # guard_plan_edit / lint_plan
    assert "exited 1" in out   # steer_build / report_drift
    assert "REFUSED, NO REASON" not in out, "a loud failure must not read as a mute one"


def test_project_dir_placeholder_expands_to_the_project_not_the_fixture(pt, tmp_path, capsys):
    """A registration written against ${CLAUDE_PROJECT_DIR} must expand to the real
    project. selftest runs the hooks against a throwaway fixture repo, and expanding
    the placeholder to *that* points every hook at a directory with no scripts in it
    — reporting four dead hooks on a perfectly good install. Caught in the wild by
    the selftest itself, aimed at the wrong target."""
    rel = "vendored/scripts/hooks"
    dst = tmp_path / rel
    dst.mkdir(parents=True)
    src = pt.Path(pt.__file__).resolve().parent / "hooks"
    for f in list(pt.HOOK_MATCHERS) + ["run-hook.sh"]:
        (dst / f).write_bytes((src / f).read_bytes())
    # plan_tool must sit where the hooks expect a sibling copy, or lint_plan cannot
    # resolve the tool it validates with.
    (tmp_path / "vendored" / "scripts" / "plan_tool.py").write_bytes(
        pt.Path(pt.__file__).resolve().read_bytes())

    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: (
        f'sh "${{CLAUDE_PROJECT_DIR}}/{rel}/run-hook.sh" '
        f'"${{CLAUDE_PROJECT_DIR}}/{rel}/{s}" {pt.HOOK_DEAD_EXIT[s]}'))

    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "4/4 observed" in out, out


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


def test_resolver_script_ships_beside_the_hooks_it_launches(pt):
    """Not in the plugin's hooks/ directory. The skill directory travels as one unit
    through a plugin install, `npx skills add`, and a vendored copy; the plugin
    wrapper travels through only the first. Kept at the plugin root, the launcher
    was absent from two of the three shapes that ship the hooks needing it."""
    launcher = pt.hook_launcher()
    assert launcher.exists(), "run-hook.sh must ship beside the hook scripts"
    hooks_dir = pt.Path(pt.__file__).resolve().parent / "hooks"
    assert launcher.parent == hooks_dir, (
        f"launcher must live with the hooks it starts; found {launcher}")
    for script in pt.HOOK_MATCHERS:
        assert (hooks_dir / script).exists(), f"{script} is not beside the launcher"


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


# ── three failures, three diagnoses (reported by cozycode) ───────────────────
# cozycode's own pre-commit gate hit this while being written: `set -e` plus a
# loop whose last command is a false test exited 1 with no output — "a gate that
# looks like it ran and refused, with nothing to read". Calling that "silent",
# the same word used for an exit-0 no-op, hides the worse of the two.

def test_a_hook_that_refuses_without_a_reason_is_named_as_such(pt, tmp_path, capsys):
    """Non-zero exit, empty stderr. It blocked the action and explained nothing —
    and on PreToolUse the blocking message falls back to stderr, so the user is
    shown a refusal with an empty reason."""
    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: f"exit 1 # {s}")
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "REFUSED, NO REASON" in out
    assert "leaves nothing to read" in out
    assert "SILENT" not in out, "an exit-1 refusal must not be filed as a silent pass"


def test_a_hook_that_exits_zero_silently_is_named_differently(pt, tmp_path, capsys):
    """The other diagnosis: exit 0 and nothing said is what a hook that never ran
    also produces. Different cause, different remedy."""
    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: f"true # {s}")
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "SILENT" in out
    assert "what a hook that never ran also produces" in out
    assert "REFUSED, NO REASON" not in out


def test_a_hook_that_fails_loudly_reports_its_reason(pt, tmp_path, capsys):
    """Non-zero WITH stderr is the fail-loud contract working. It must be reported
    as a failure carrying its message, not lumped in with the mute ones."""
    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: f"echo 'no interpreter' >&2; exit 2 # {s}")
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "no interpreter" in out, "the reason it gave must reach the report"
    assert "REFUSED, NO REASON" not in out


# ── the placeholder must survive a real shell (the 127 bug) ──────────────────
# `shlex.quote` emits SINGLE quotes, which protect everything including a
# ${...} the shell must expand. sh received the literal
# "${CLAUDE_PROJECT_DIR}/..." as a filename and every hook exited 127 on every
# matched tool call. selftest could not see it: it substituted the placeholder
# itself before running the command, so it removed the fault before looking for
# it and reported 4/4 on a layer that could not start.

def _vendor_into(pt, repo, rel="vendored/scripts/hooks"):
    """Copy the hook scripts and a sibling plan_tool into `repo`, return the rel dir."""
    dst = repo / rel
    dst.mkdir(parents=True)
    src = pt.Path(pt.__file__).resolve().parent / "hooks"
    for f in list(pt.HOOK_MATCHERS) + ["run-hook.sh"]:
        (dst / f).write_bytes((src / f).read_bytes())
    (repo / rel).parent.joinpath("plan_tool.py").write_bytes(
        pt.Path(pt.__file__).resolve().read_bytes())
    return rel


def test_a_single_quoted_placeholder_is_reported_not_repaired(pt, tmp_path, capsys):
    """The regression. selftest must run the command AS WRITTEN, so a registration
    that cannot expand fails here exactly as it fails in a real session."""
    rel = _vendor_into(pt, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: (
        f"sh '${{CLAUDE_PROJECT_DIR}}/{rel}/run-hook.sh' "
        f"'${{CLAUDE_PROJECT_DIR}}/{rel}/{s}' {pt.HOOK_DEAD_EXIT[s]}"))
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "0/4 observed" in out, out
    assert "${CLAUDE_PROJECT_DIR}" in out, "the unexpanded literal must reach the report"
    # NOT the exit number: an unopenable script is 127 under bash-as-sh and 2 under
    # dash, which is /bin/sh on Ubuntu. CI caught that — the first version of this
    # test asserted "127" and was green on macOS and Windows, red on Linux. What
    # must hold everywhere is that the hook failed loudly and the report carries its
    # reason, which the two assertions above and this one cover.
    assert "FAILED" in out
    assert "exited " in out, out


def test_a_double_quoted_placeholder_expands_and_passes(pt, tmp_path, capsys):
    rel = _vendor_into(pt, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    _write_settings(pt, settings, lambda s: (
        f'sh "${{CLAUDE_PROJECT_DIR}}/{rel}/run-hook.sh" '
        f'"${{CLAUDE_PROJECT_DIR}}/{rel}/{s}" {pt.HOOK_DEAD_EXIT[s]}'))
    assert pt.main(["hooks", "selftest", "--root", str(tmp_path)]) == 0
    assert "4/4 observed" in capsys.readouterr().out


def test_shell_arg_expands_placeholders_and_holds_spaces(pt):
    """Both properties at once. Quoting existed to protect spaces; the placeholder
    needs expansion. A fix for either that breaks the other is not a fix."""
    q = pt.shell_arg("${CLAUDE_PROJECT_DIR}/a b/c.py")
    assert q.startswith('"') and q.endswith('"'), q
    assert "${CLAUDE_PROJECT_DIR}" in q, "the placeholder must stay expandable"
    # No placeholder -> single quotes are still correct and safest.
    assert pt.shell_arg("/plain/a b/c.py").startswith("'")


def test_registered_commands_never_single_quote_a_placeholder(pt, tmp_path):
    """Whatever `hooks install` writes must be expandable by a real shell."""
    import re
    settings = tmp_path / ".claude" / "settings.json"
    repo_root = pt.Path(pt.__file__).resolve().parents[3]
    pt.main(["hooks", "install", "--settings", str(settings), "--root", str(repo_root)])
    data = json.loads(settings.read_text(encoding="utf-8"))
    for _ev, blocks in data["hooks"].items():
        for b in blocks:
            for h in b["hooks"]:
                cmd = h["command"]
                assert not re.search(r"'\$\{", cmd), (
                    f"placeholder inside single quotes cannot expand: {cmd}")
