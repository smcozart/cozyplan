"""`trailers` + `hooks git-install`: advisory trailer injection (ADR-0004, ADR-0007).

The hook adds only what it can demonstrate and never rejects, so these tests pin
both halves: that a provable trailer appears, and that an unprovable one does not.
"""

from __future__ import annotations

import os
import stat

from conftest import git, read


def infer(pt, repo, capsys):
    pt.main(["trailers", "--root", str(repo), "--print"])
    return [l for l in capsys.readouterr().out.strip().split("\n") if l]


def stage_adr(repo, num, name="a-decision"):
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    (adr / f"{num}-{name}.md").write_text(f"---\ntitle: T{num}\n---\n", encoding="utf-8")
    git(repo, "add", "-A")


def test_staged_adr_is_inferred(pt, git_repo, capsys):
    stage_adr(git_repo, "0007")
    assert infer(pt, git_repo, capsys) == ["ADR: 0007"]


def test_multiple_staged_adrs_are_sorted_and_joined(pt, git_repo, capsys):
    stage_adr(git_repo, "0009", "later")
    stage_adr(git_repo, "0002", "earlier")
    assert infer(pt, git_repo, capsys) == ["ADR: 0002,0009"]


def test_nothing_staged_infers_nothing(pt, git_repo, capsys):
    assert infer(pt, git_repo, capsys) == []


def test_branch_naming_a_real_plan_infers_it(pt, git_repo, specs, capsys):
    (git_repo / "specs").mkdir(exist_ok=True)
    (git_repo / "specs" / "streaming-ingest.html").write_text("<html></html>", encoding="utf-8")
    git(git_repo, "checkout", "-q", "-b", "feat/streaming-ingest")
    assert infer(pt, git_repo, capsys) == ["Plan: streaming-ingest"]


def test_branch_with_no_matching_plan_infers_nothing(pt, git_repo, capsys):
    """Never a guess: a branch name alone is not evidence a plan exists."""
    git(git_repo, "checkout", "-q", "-b", "feat/no-such-plan")
    assert infer(pt, git_repo, capsys) == []


def test_verified_is_never_inferred(pt, git_repo, capsys):
    """No hook can prove a test ran, so it must never claim one did."""
    stage_adr(git_repo, "0007")
    assert not any(t.startswith("Verified:") for t in infer(pt, git_repo, capsys))


def test_message_file_is_amended_in_place(pt, git_repo, tmp_path):
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nsome body text\n", encoding="utf-8")
    assert pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)]) == 0
    out = read(msg)
    assert "ADR: 0007" in out
    assert out.strip().split("\n")[-1] == "ADR: 0007", "trailer must be the last line"


def test_existing_trailer_is_not_duplicated(pt, git_repo, tmp_path):
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nADR: 0007\n", encoding="utf-8")
    pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)])
    assert read(msg).count("ADR: 0007") == 1


def test_injection_survives_a_co_authored_by_line(pt, git_repo, tmp_path):
    """The bug this session hit by hand: a trailer block split by a blank line
    means git parses only the last paragraph. interpret-trailers gets it right."""
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nbody\n\nCo-Authored-By: X <x@example.com>\n",
                   encoding="utf-8")
    pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)])
    got = git(git_repo, "interpret-trailers", "--parse", str(msg)).stdout
    assert "ADR: 0007" in got and "Co-Authored-By" in got


def test_missing_message_file_is_not_an_error(pt, git_repo):
    """Fail open: a hook that breaks a commit because a file moved is worse than
    a missing trailer (ADR-0004)."""
    stage_adr(git_repo, "0007")
    assert pt.main(["trailers", "--root", str(git_repo),
                    "--message-file", str(git_repo / "nope")]) == 0


def test_git_install_writes_executable_hooks_and_sets_hookspath(pt, git_repo, capsys):
    assert pt.main(["hooks", "git-install", "--root", str(git_repo)]) == 0
    hooks = git_repo / ".githooks"
    for name in ("commit-msg", "pre-push"):
        p = hooks / name
        assert p.exists(), name
        assert os.stat(p).st_mode & stat.S_IXUSR, f"{name} must be executable"
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert git(git_repo, "config", "cozyplan.plantool").stdout.strip().endswith("plan_tool.py")


def test_git_remove_unsets_everything(pt, git_repo):
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    assert pt.main(["hooks", "git-remove", "--root", str(git_repo)]) == 0
    assert not (git_repo / ".githooks" / "commit-msg").exists()
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ""


def test_installed_hook_injects_on_a_real_commit(pt, git_repo):
    """End to end: the hook git actually runs, on a commit actually made."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    stage_adr(git_repo, "0007")
    r = git(git_repo, "commit", "-m", "feat: add a decision")
    assert r.returncode == 0, r.stderr
    body = git(git_repo, "log", "-1", "--format=%B").stdout
    assert "ADR: 0007" in body, body
