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
    # Provenance, in fields that mean the same thing on every machine. This used to
    # assert `vendored from`, the vendoring machine's absolute path — provenance that
    # was true in one place and misleading everywhere else, in a tracked file. The
    # local path now lives in git config; see test_the_local_checkout_path_goes_to_git_config.
    assert "source commit" in text and "source remote" in text
    assert "vendored from" not in text, "the machine-specific path must not be tracked"


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


def test_scaffolds_system_md(pt, git_repo):
    """README routes 'how does this work' and 'what breaks if I change this' at
    SYSTEM.md, and nothing created it, so every repo shipped a dead link."""
    run(pt, git_repo, "--repo", "acme/widget")
    assert (git_repo / "SYSTEM.md").exists()
    text = read(git_repo / "SYSTEM.md")
    assert "## Components" in text and "## Edges" in text


def test_the_scaffolded_map_carries_no_fictional_components(pt, git_repo):
    """A fresh repo shipping a table of invented components is the confident-wrong-
    answer failure SYSTEM.md's own footer warns about: readers stop at the table."""
    run(pt, git_repo, "--repo", "acme/widget")
    text = read(git_repo / "SYSTEM.md")
    for example in ("Orders API", "Billing Worker", "Fulfillment", "Stripe"):
        assert example not in text, example
    assert "_none recorded yet_" in text


def test_an_existing_system_md_is_never_clobbered(pt, git_repo):
    (git_repo / "SYSTEM.md").write_text("# System\n\nour real map\n", encoding="utf-8")
    run(pt, git_repo, "--repo", "acme/widget")
    assert "our real map" in read(git_repo / "SYSTEM.md")


def test_strip_example_rows_keeps_headers_and_prose(pt):
    src = ("| A | B |\n| --- | --- |\n| x | y |\n| p | q |\n\nprose stays\n")
    out = pt.strip_example_rows(src)
    assert "| A | B |" in out and "prose stays" in out
    assert "| x | y |" not in out
    assert "_none recorded yet_" in out


# ── generated artifacts must be portable (cozycode ADR-0002) ─────────────────
# `init --vendor` wrote the absolute path of the vendoring machine into
# VENDORED.md, a TRACKED file. A consuming repo deleted it by hand as a violation
# of its own absolute-paths ban; the next re-vendor put it straight back, because
# that is what generated files do. Nothing caught either the first write or the
# reinstatement.

def test_vendored_marker_contains_no_absolute_path(pt, git_repo, tmp_path):
    """The marker is committed, so every field in it must be true on every machine."""
    assert pt.main(["init", "--root", str(git_repo), "--vendor"]) == 0
    marker = git_repo / ".claude" / "skills" / "VENDORED.md"
    body = marker.read_text(encoding="utf-8")
    for line in body.splitlines():
        assert not __import__("re").search(r"\|\s*(/|[A-Za-z]:\\)", line), (
            f"absolute path in a tracked, generated file: {line!r}")
    # The identity fields must survive — dropping the path must not drop provenance.
    assert "source commit" in body
    assert "source remote" in body


def test_the_local_checkout_path_goes_to_git_config(pt, git_repo):
    """Machine-specific location belongs in per-clone config, not a tracked file.
    doctor still needs it to compare against upstream, so it must land somewhere."""
    assert pt.main(["init", "--root", str(git_repo), "--vendor"]) == 0
    src = git(git_repo, "config", "cozyplan.source").stdout.strip()
    assert src, "cozyplan.source not recorded, so freshness can never be checked"
    assert pt.Path(src).exists()


def test_no_generated_artifact_carries_the_vendoring_machines_path(pt, git_repo):
    """Wider than VENDORED.md: nothing `init` writes may name the machine it ran on."""
    import re as _re
    assert pt.main(["init", "--root", str(git_repo), "--vendor"]) == 0
    here = str(pt.Path(pt.__file__).resolve().parents[3])
    ok, tracked = pt.git(git_repo, "ls-files")
    offenders = []
    for rel in (tracked.splitlines() if ok else []):
        f = git_repo / rel
        if not f.is_file() or f.suffix in (".png", ".jpg", ".webp"):
            continue
        try:
            if here in f.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(rel)
        except OSError:
            continue
    assert not offenders, f"tracked files naming the vendoring machine: {offenders}"


# ── a vendored copy may not be a vendor source (reported by cozycode) ────────
# The only guard compared the source against `root/skills`, which catches
# cozyplan's own layout and nothing else. A vendored copy lives at
# `.claude/skills/`, so two failures proceeded silently:
#   1. Vendored tool -> different root: provenance stamped from the CONSUMING
#      repo. version "unknown", source commit the consumer's own sha, source
#      remote the consumer's own remote. doctor then says upstream is "not
#      reachable" rather than that anything is wrong — the freshness row
#      disabled by the exact act it exists to guard against.
#   2. Vendored tool -> same root: rmtree clears the destination, which IS the
#      source, and the copy dies part-way. 21 files deleted before the crash.

def _fake_vendored_tool(pt, repo):
    """A plan_tool living at .claude/skills/cozyplan/scripts/, as a vendored one does."""
    dst = repo / ".claude" / "skills" / "cozyplan" / "scripts"
    (dst / "hooks").mkdir(parents=True)
    src = pt.Path(pt.__file__).resolve()
    (dst / "plan_tool.py").write_bytes(src.read_bytes())
    for f in list(pt.HOOK_MATCHERS) + ["run-hook.sh"]:
        (dst / "hooks" / f).write_bytes((src.parent / "hooks" / f).read_bytes())
    marker = repo / ".claude" / "skills" / "VENDORED.md"
    marker.write_text("| version | 3.2.0 |\n| source commit | abc1234 |\n"
                      "| source remote | https://example.com/cozyplan.git |\n", encoding="utf-8")
    return dst / "plan_tool.py", marker


def test_a_vendored_plan_tool_is_refused_as_a_vendor_source(pt, git_repo, tmp_path, monkeypatch):
    """Its git history is the consuming repo's, so provenance would name that repo
    as its own upstream — and doctor would then report only that it cannot look."""
    tool, marker = _fake_vendored_tool(pt, git_repo)
    before = marker.read_text(encoding="utf-8")
    monkeypatch.setattr(pt, "__file__", str(tool))

    target = tmp_path / "consumer"
    target.mkdir()
    git(target, "init")
    assert pt.main(["init", "--root", str(target), "--vendor"]) == 1
    # And nothing was written on the way to refusing.
    assert marker.read_text(encoding="utf-8") == before
    assert not (target / ".claude" / "skills").exists()


def test_the_refusal_names_the_remedy(pt, git_repo, tmp_path, monkeypatch, capsys):
    tool, _ = _fake_vendored_tool(pt, git_repo)
    monkeypatch.setattr(pt, "__file__", str(tool))
    target = tmp_path / "consumer"
    target.mkdir()
    git(target, "init")
    pt.main(["init", "--root", str(target), "--vendor"])
    err = capsys.readouterr().err
    assert "cozyplan.source" in err, "the refusal must name how to do it correctly"
    assert "--vendor" in err


def test_vendoring_into_the_tree_being_read_from_is_refused(pt, git_repo, monkeypatch):
    """Source and destination the same directory: the rmtree that clears the
    destination deletes the source. This must not reach the copy at all."""
    tool, marker = _fake_vendored_tool(pt, git_repo)
    before = marker.read_text(encoding="utf-8")
    monkeypatch.setattr(pt, "__file__", str(tool))
    assert pt.main(["init", "--root", str(git_repo), "--vendor"]) == 1
    # The scripts the copy would have destroyed are still there.
    assert (tool.parent / "hooks" / "run-hook.sh").exists()
    assert marker.read_text(encoding="utf-8") == before


def test_a_source_checkout_still_vendors_normally(pt, git_repo, tmp_path):
    """The guard must not block the only correct route."""
    target = tmp_path / "consumer"
    target.mkdir()
    git(target, "init")
    assert pt.main(["init", "--root", str(target), "--vendor"]) == 0
    assert (target / ".claude" / "skills" / "cozyplan" / "scripts" / "plan_tool.py").exists()
    body = (target / ".claude" / "skills" / "VENDORED.md").read_text(encoding="utf-8")
    assert "cozyplan" in body
