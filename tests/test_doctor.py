"""`doctor`: what is actually wired in this clone (ADR-0004).

The failure being guarded against is silent misconfiguration, so these tests
assert that an unwired clone SAYS it is unwired — a doctor that reports OK on a
broken clone is worse than no doctor at all.
"""

from __future__ import annotations

import json

from conftest import git


def run(pt, repo, *extra):
    return pt.main(["doctor", "--root", str(repo), *extra])


def test_bare_repo_reports_gaps_not_ok(pt, git_repo, capsys):
    assert run(pt, git_repo) == 0          # diagnostic by default, never a gate
    out = capsys.readouterr().out
    assert "gap" in out
    for expected in ("issue tracker", "agent doc", "STATE.md", "union merge", "ci workflow"):
        assert expected in out


def test_strict_exits_nonzero_on_gaps(pt, git_repo, capsys):
    assert run(pt, git_repo, "--strict") == 1
    assert "gaps are wiring that is absent" in capsys.readouterr().out


def test_non_git_directory_stops_early(pt, tmp_path, capsys):
    assert run(pt, tmp_path) == 0
    out = capsys.readouterr().out
    assert "not a git repository" in out
    # nothing below git can be meaningfully checked, so it must not pretend to
    assert "union merge" not in out


def test_missing_git_identity_warns_but_never_fails_strict(pt, git_repo, capsys):
    """Attribution config, not wiring: a CI runner has no identity, and failing
    --strict there would be a false positive."""
    git(git_repo, "config", "--unset", "user.name")
    git(git_repo, "config", "--unset", "user.email")
    (git_repo / ".gitattributes").write_text("docs/state.ndjson merge=union\n", encoding="utf-8")
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "user.name/user.email unset" in out
    assert "[ warn ] identity" in out


def test_identity_present_reads_ok(pt, git_repo, capsys):
    run(pt, git_repo)
    assert "Test <t@example.com>" in capsys.readouterr().out


def test_union_merge_attribute_is_detected(pt, git_repo, capsys):
    run(pt, git_repo)
    assert "missing from .gitattributes" in capsys.readouterr().out

    (git_repo / ".gitattributes").write_text("docs/state.ndjson merge=union\n", encoding="utf-8")
    run(pt, git_repo)
    assert "state log is union-merged" in capsys.readouterr().out


def test_hook_interpreter_is_executed_not_assumed(pt, git_repo, capsys):
    """The uv bug shipped because registration was checked and execution was not.
    doctor runs the path the hooks run: `--help` passed happily while the commit-msg
    hook was dead, because the break was in the runner rather than in the tool."""
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "hook interpreter" in out
    assert "runs the trailer path" in out


def test_claude_hooks_registration_is_detected(pt, git_repo, capsys):
    run(pt, git_repo)
    assert "not registered" in capsys.readouterr().out

    settings = git_repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)

    # Half-wired reads as unwired. A settings.json carrying the two tool hooks but
    # neither steering hook used to report "registered", which is the same lie as a
    # registered-but-unrunnable hook — the human stops looking at exactly the point
    # the layer is incomplete.
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{"command": "uv run guard_plan_edit.py"}]}],
        "PostToolUse": [{"hooks": [{"command": "uv run lint_plan.py"}]}]}}), encoding="utf-8")
    run(pt, git_repo)
    assert "not registered" in capsys.readouterr().out

    # All of them, whatever HOOK_MATCHERS currently holds.
    settings.write_text(json.dumps({"hooks": {"All": [
        {"hooks": [{"command": f"uv run {s}"}]} for s in pt.HOOK_MATCHERS]}}), encoding="utf-8")
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert f"all {len(pt.HOOK_MATCHERS)} listed" in out

    # Registration must never present itself as proof. These four commands name
    # scripts that do not exist at those paths, so the layer is registered and
    # entirely inert — the exact state that used to print as a healthy row.
    # doctor has to carry both facts, and the outcome row is the one that objects.
    assert "a record only" in out, "registration must be labelled as a record"
    assert "hooks observed" in out, "doctor must report an observed outcome too"
    reg_line = next(l for l in out.splitlines() if "hooks registered" in l)
    obs_line = next(l for l in out.splitlines() if "hooks observed" in l)
    assert "ok" in reg_line and "gap" in obs_line, (
        "a registered-but-inert layer must show ok on the record and a gap on the "
        f"outcome; got:\n{reg_line}\n{obs_line}")


def test_ci_workflow_must_actually_run_state_check(pt, git_repo, capsys):
    wf = git_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    # a workflow that exists but does not run the check is not the enforcing layer
    (wf / "other.yml").write_text("name: lint\njobs: {}\n", encoding="utf-8")
    run(pt, git_repo)
    assert "no workflow runs `state check`" in capsys.readouterr().out

    (wf / "state-check.yml").write_text("name: state check\njobs: {}\n", encoding="utf-8")
    run(pt, git_repo)
    assert "state-check.yml" in capsys.readouterr().out


def test_required_check_is_never_claimed(pt, git_repo, capsys):
    """Branch protection is invisible from a clone, so doctor must not imply a gate."""
    run(pt, git_repo)
    assert "not verifiable from a clone" in capsys.readouterr().out


def test_trailer_coverage_is_reported(pt, git_repo, capsys):
    for i in range(2):
        (git_repo / f"f{i}.txt").write_text("x\n", encoding="utf-8")
        git(git_repo, "add", "-A")
        git(git_repo, "commit", "-m", f"plain {i}")
    (git_repo / "g.txt").write_text("x\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "trailered\n\nADR: 0001")
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "trailer coverage" in out
    assert "1/4" in out, out       # seed commit + 2 plain + 1 trailered


def test_state_log_event_count_is_reported(pt, git_repo, capsys):
    pt.main(["state", "add", "--root", str(git_repo),
             "--log", str(git_repo / "docs" / "state.ndjson"),
             "--kind", "claim", "--what", "it works", "--proof", "pytest"])
    capsys.readouterr()
    run(pt, git_repo)
    assert "1 event(s)" in capsys.readouterr().out


def test_reports_when_prose_names_a_command_the_parser_lacks(pt, git_repo, tmp_path, capsys):
    """Docs drifting from the CLI sent readers to run commands that do not exist, for a
    whole release. It is a grep, so it should never have been a manual check."""
    skill = tmp_path / "skill"
    (skill / "workflows").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# S\n", encoding="utf-8")
    (skill / "workflows" / "w.md").write_text(
        "Run `PLAN_TOOL brief <plan>` then `PLAN_TOOL ground --review`.\n", encoding="utf-8")
    drift = pt.doc_command_drift(skill)
    assert ("w.md", "ground") in drift
    assert not any(v == "brief" for _, v in drift), "brief is a real command"


def test_prose_naming_only_real_commands_is_clean(pt, tmp_path):
    skill = tmp_path / "skill"
    (skill / "workflows").mkdir(parents=True)
    (skill / "SKILL.md").write_text("Use `PLAN_TOOL doctor` and `PLAN_TOOL state add`.\n",
                                    encoding="utf-8")
    assert pt.doc_command_drift(skill) == []


def test_the_command_list_is_read_off_the_parser(pt):
    """Hardcoding it would let the very drift this checks for happen here."""
    names = pt.subcommand_names()
    assert {"init", "doctor", "state", "brief", "validate"} <= names
    assert "ground" not in names


def test_the_header_command_list_must_match_the_parser(pt, monkeypatch):
    """The prose check reads SKILL.md, workflows/, and reference/, never this script —
    so the file's own Commands: block was the one place drift could hide from it, and did."""
    assert pt.header_command_drift() == []
    trimmed = pt.__doc__.replace("  issue      file a work item, queueing it when gh is away (ADR-0001)\n", "")
    monkeypatch.setattr(pt, "__doc__", trimmed + "")
    # __doc__ is read inside the function, so patching the module attribute is enough
    assert ("undocumented", "issue") in pt.header_command_drift()


def test_a_header_naming_a_command_that_does_not_exist_is_drift(pt, monkeypatch):
    monkeypatch.setattr(pt, "__doc__",
                        pt.__doc__.replace("  doctor     report what is actually wired in this clone (ADR-0004)",
                                           "  doctor     report what is actually wired in this clone (ADR-0004)\n"
                                           "  ground     traverse the id space"))
    assert ("stale", "ground") in pt.header_command_drift()


def test_plugin_manifest_counts_as_registration(pt, git_repo, capsys, monkeypatch):
    """A plugin install registers hooks via the bundled manifest and never writes
    .claude/settings.json, so doctor reported 'not registered' to every plugin
    user permanently — a check that can never go green teaches you to ignore it."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(pt.PLUGIN_HOOKS_JSON.parents[1]))
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "not registered" not in out
    assert "plugin manifest" in out


def test_a_source_checkout_is_not_mistaken_for_a_plugin_install(pt, git_repo, capsys, monkeypatch):
    """hooks/hooks.json sitting beside plan_tool.py proves nothing — a source
    checkout has one too. Only the host setting CLAUDE_PLUGIN_ROOT does."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    run(pt, git_repo)
    assert "not registered" in capsys.readouterr().out


# ── the CI rows: a record labelled as one, and the selftest gap (cozycode) ────

def test_ci_workflow_row_is_labelled_a_record(pt, git_repo, capsys):
    """It greps a YAML file for a string. A syntactically broken workflow, or one
    that has never gone green, passes it identically to one guarding every push —
    so it must not read as proof, the way `hooks registered` no longer does."""
    wf = git_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "state-check.yml").write_text("name: x\njobs: {}\n# state check\n", encoding="utf-8")
    run(pt, git_repo)
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "ci workflow" in l)
    assert "a record only" in line, line


def test_a_workflow_without_the_selftest_is_reported(pt, git_repo, capsys):
    """`init` leaves an existing workflow alone by design, so a repo wired before
    the selftest existed never gains the step and nothing said so. cozycode had it
    in neither CI nor any hook."""
    wf = git_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "state-check.yml").write_text("name: x\njobs: {}\n# state check\n", encoding="utf-8")
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "ci runs selftest" in out
    assert "no workflow runs `hooks selftest`" in out
    assert "--shipped" in out, "the row must name the step to add, not only the absence"


def test_a_workflow_with_the_selftest_passes(pt, git_repo, capsys):
    wf = git_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "state-check.yml").write_text(
        "name: x\njobs: {}\n# state check\n# hooks selftest --shipped\n", encoding="utf-8")
    run(pt, git_repo)
    line = next(l for l in capsys.readouterr().out.splitlines() if "ci runs selftest" in l)
    assert "ok" in line, line


def test_the_installed_template_carries_the_selftest_step(pt):
    """The template `init` writes into a consuming repo. Without this the gap was
    worse than reported: not only did existing repos never gain the step, a brand
    new one did not get it either."""
    tpl = pt.resolve_template("state-check.yml")
    assert tpl is not None, "state-check.yml template not found"
    body = tpl.read_text(encoding="utf-8")
    assert "hooks selftest" in body, "the shipped CI template must run the selftest"
    assert "--shipped" in body
