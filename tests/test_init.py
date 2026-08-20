"""`plan_tool init` — wire a repo for cozyplan (ADR-0004, ADR-0007).

init implements doctor's check list, so the contract these tests hold it to is:
a greenfield repo ends with zero gaps, and a brownfield repo loses nothing.
"""

from __future__ import annotations

from conftest import git, read


def run(pt, repo, *extra):
    return pt.main(["init", "--root", str(repo), *extra])


def gaps(pt, repo):
    return [(n, d) for _, st, n, d in pt.doctor_checks(repo, 20) if st == pt.GAP]


def test_greenfield_leaves_no_gaps(pt, git_repo, capsys):
    git(git_repo, "remote", "add", "origin", "https://github.com/acme/widget.git")
    assert run(pt, git_repo) == 0
    capsys.readouterr()
    assert gaps(pt, git_repo) == []
    for rel in ("docs/adr", "docs/state.ndjson", "docs/journal.md", "STATE.md",
                "CLAUDE.md", ".gitattributes", ".githooks/commit-msg",
                ".github/workflows/state-check.yml", "docs/agents/issue-tracker.md"):
        assert (git_repo / rel).exists(), rel


def test_the_issue_tracker_gets_the_real_repo_slug(pt, git_repo):
    git(git_repo, "remote", "add", "origin", "git@github.com:acme/widget.git")
    run(pt, git_repo)
    text = read(git_repo / "docs" / "agents" / "issue-tracker.md")
    assert "acme/widget" in text and "{{REPO_SLUG}}" not in text


def test_without_a_remote_the_tracker_is_handed_to_a_human(pt, git_repo, capsys):
    """A guessed slug would point every issue command at the wrong repo."""
    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "needs a human" in out and "issue-tracker.md" in out
    assert not (git_repo / "docs" / "agents" / "issue-tracker.md").exists()


def test_is_idempotent(pt, git_repo, capsys):
    git(git_repo, "remote", "add", "origin", "https://github.com/acme/widget.git")
    assert run(pt, git_repo) == 0
    first = read(git_repo / ".gitattributes")
    capsys.readouterr()
    assert run(pt, git_repo) == 0
    assert read(git_repo / ".gitattributes") == first
    assert read(git_repo / ".gitattributes").count("state.ndjson merge=union") == 1
    assert gaps(pt, git_repo) == []


def test_never_clobbers_an_existing_entry_point(pt, git_repo):
    (git_repo / "CLAUDE.md").write_text("# Mine\n\nhand written\n", encoding="utf-8")
    run(pt, git_repo)
    assert "hand written" in read(git_repo / "CLAUDE.md")


def test_appends_to_an_existing_gitattributes(pt, git_repo):
    (git_repo / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    run(pt, git_repo)
    text = read(git_repo / ".gitattributes")
    assert "* text=auto" in text and "state.ndjson merge=union" in text


def test_refuses_to_take_over_a_foreign_hook_manager(pt, git_repo, capsys):
    """Silently repointing core.hooksPath would disable the repo's real hooks."""
    (git_repo / ".husky").mkdir()
    git(git_repo, "config", "core.hooksPath", ".husky")
    run(pt, git_repo)
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ".husky"
    assert "another hook manager" in capsys.readouterr().out


def test_force_hooks_takes_over_deliberately(pt, git_repo):
    (git_repo / ".husky").mkdir()
    git(git_repo, "config", "core.hooksPath", ".husky")
    run(pt, git_repo, "--force-hooks")
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"


def test_a_hand_authored_state_file_is_routed_to_migrate_not_overwritten(pt, git_repo, capsys):
    (git_repo / "STATE.md").write_text(
        "# demo — State\n\n## Current Working State\n\n"
        "- ingest works — verified by `pytest` (2026-08-18, abc1234)\n", encoding="utf-8")
    run(pt, git_repo)
    assert "ingest works" in read(git_repo / "STATE.md")
    assert "state migrate" in capsys.readouterr().out


def test_leaves_an_existing_ci_workflow_alone(pt, git_repo):
    wf = git_repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: ci\njobs:\n  x:\n    steps:\n      - run: plan_tool state check\n",
                               encoding="utf-8")
    run(pt, git_repo)
    assert not (wf / "state-check.yml").exists(), "a workflow already runs state check"


def test_refuses_outside_a_git_repo(pt, tmp_path, capsys):
    assert pt.main(["init", "--root", str(tmp_path)]) == 1
    assert "not a git repository" in capsys.readouterr().err


def test_git_init_bootstraps_one(pt, tmp_path, capsys):
    assert pt.main(["init", "--root", str(tmp_path), "--git-init"]) == 0
    assert (tmp_path / ".git").is_dir()


def test_gitignores_the_issue_queue(pt, git_repo):
    """The queue holds intended issues, not repo content (ADR-0001)."""
    run(pt, git_repo)
    assert ".scratch/" in read(git_repo / ".gitignore")


def test_does_not_duplicate_the_gitignore_entry(pt, git_repo):
    run(pt, git_repo)
    run(pt, git_repo)
    assert read(git_repo / ".gitignore").count(".scratch/") == 1


def test_preserves_an_existing_gitignore(pt, git_repo):
    (git_repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    run(pt, git_repo)
    text = read(git_repo / ".gitignore")
    assert "node_modules/" in text and ".scratch/" in text


def _fake_skill_source(tmp_path):
    """A skills/ dir shaped like the real one, so --vendor has something to copy
    without this test depending on the repo it runs in."""
    src = tmp_path / "upstream" / "skills"
    for name in ("cozyplan", "discuss"):
        (src / name / "scripts").mkdir(parents=True)
        (src / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (src / name / "scripts" / "x.py").write_text("x = 1\n", encoding="utf-8")
    return src


def test_vendor_copies_both_skills_into_the_repo(pt, git_repo, tmp_path, monkeypatch):
    """A teammate cloning a vendored repo installs nothing: the skills and plan_tool
    travel with the repo, and the template resolver already looks in .claude/skills first."""
    src = _fake_skill_source(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(src / "cozyplan" / "scripts" / "plan_tool.py"))
    run(pt, git_repo, "--vendor", "--repo", "acme/widget")
    for name in ("cozyplan", "discuss"):
        assert (git_repo / ".claude" / "skills" / name / "SKILL.md").exists(), name
    assert "version" in read(git_repo / ".claude" / "skills" / "VENDORED.md")


def test_vendor_records_what_it_vendored(pt, git_repo, tmp_path, monkeypatch):
    """A consuming repo cannot see upstream, so the only honest drift signal is a
    recorded origin a human can compare against."""
    src = _fake_skill_source(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(src / "cozyplan" / "scripts" / "plan_tool.py"))
    run(pt, git_repo, "--vendor")
    text = read(git_repo / ".claude" / "skills" / "VENDORED.md")
    assert "source commit" in text and "vendored from" in text


def test_doctor_flags_a_hand_edited_vendored_skill(pt, git_repo, tmp_path, monkeypatch, capsys):
    src = _fake_skill_source(tmp_path)
    monkeypatch.setattr(pt, "__file__", str(src / "cozyplan" / "scripts" / "plan_tool.py"))
    run(pt, git_repo, "--vendor")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "vendor")
    capsys.readouterr()
    pt.main(["doctor", "--root", str(git_repo)])
    assert "committed in-repo" in capsys.readouterr().out
    (git_repo / ".claude" / "skills" / "cozyplan" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    pt.main(["doctor", "--root", str(git_repo)])
    assert "are modified" in capsys.readouterr().out


def test_repo_flag_breaks_the_init_doctor_loop(pt, git_repo, capsys):
    """Without an origin, doctor said 'run init' and init said 'needs a human'. --repo
    is the way out; a guessed slug would point every issue command at someone else."""
    assert run(pt, git_repo, "--repo", "acme/widget") == 0
    text = read(git_repo / "docs" / "agents" / "issue-tracker.md")
    assert "acme/widget" in text and "{{REPO_SLUG}}" not in text
    capsys.readouterr()
    assert gaps(pt, git_repo) == []


def test_vendoring_into_the_skill_source_itself_is_refused(pt, git_repo, capsys):
    """Running --vendor in cozyplan's own repo would copy skills/ into .claude/skills/."""
    (git_repo / "skills" / "cozyplan" / "scripts").mkdir(parents=True)
    import types
    pt_file = git_repo / "skills" / "cozyplan" / "scripts" / "plan_tool.py"
    pt_file.write_text("x\n", encoding="utf-8")
    import unittest.mock as _m
    with _m.patch.object(pt, "__file__", str(pt_file)):
        run(pt, git_repo, "--vendor")
    assert "vendoring it into" in capsys.readouterr().out
