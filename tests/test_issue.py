"""`issue file` / `issue replay`: the gh-less queue promised by ADR-0001.

The promise lived only in prose for a release, in three documents, and an agent
following markdown follows it approximately. `--queue` forces the queue path so
these tests do not depend on whether the machine running them has gh.
"""

from __future__ import annotations

import os
import stat

from conftest import EXEC_BIT_IS_MEANINGFUL, git, read


def file_issue(pt, repo, title, body="b", *extra):
    return pt.main(["issue", "file", "--root", str(repo), "--title", title,
                    "--body", body, "--queue", *extra])


def script(repo):
    return repo / ".scratch" / "pending-gh.sh"


def test_queues_a_body_file_and_a_one_line_command(pt, git_repo):
    assert file_issue(pt, git_repo, "ingest drops empty batches") == 0
    body = git_repo / ".scratch" / "pending-issues" / "ingest-drops-empty-batches.md"
    assert body.exists() and read(body).strip() == "b"
    cmds = [l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")]
    assert len(cmds) == 1
    assert "--body-file .scratch/pending-issues/ingest-drops-empty-batches.md" in cmds[0]


def test_a_multiline_body_stays_one_command_per_line(pt, git_repo):
    """Inlining the body put newlines inside the queued command, so the script
    stopped being listable and the body lived in two places."""
    file_issue(pt, git_repo, "multi", "para one\n\npara two\n\npara three")
    lines = read(script(git_repo)).splitlines()
    assert len([l for l in lines if l.startswith("gh ")]) == 1
    assert not any(l.startswith("para") for l in lines)


def test_duplicate_titles_do_not_overwrite_each_other(pt, git_repo):
    file_issue(pt, git_repo, "same title", "first")
    file_issue(pt, git_repo, "same title", "second")
    pending = git_repo / ".scratch" / "pending-issues"
    assert {p.name for p in pending.iterdir()} == {"same-title.md", "same-title-2.md"}
    assert read(pending / "same-title.md").strip() == "first"


def test_labels_and_plan_are_carried(pt, git_repo):
    file_issue(pt, git_repo, "with refs", "body", "--label", "type:bug,priority:high",
               "--plan", "streaming-ingest")
    cmd = [l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")][0]
    assert "--label type:bug" in cmd and "--label priority:high" in cmd
    assert "Plan: streaming-ingest" in read(
        git_repo / ".scratch" / "pending-issues" / "with-refs.md")


def test_the_queue_script_is_runnable(pt, git_repo):
    file_issue(pt, git_repo, "runnable")
    assert read(script(git_repo)).startswith("#!/bin/sh")
    if EXEC_BIT_IS_MEANINGFUL:
        assert os.stat(script(git_repo)).st_mode & stat.S_IXUSR


def test_replay_lists_without_filing_by_default(pt, git_repo, capsys):
    """Filing issues is outward-facing and hard to undo, so the default shows the
    queue rather than firing it."""
    file_issue(pt, git_repo, "one")
    file_issue(pt, git_repo, "two")
    assert pt.main(["issue", "replay", "--root", str(git_repo)]) == 0
    out = capsys.readouterr().out
    assert "2 queued" in out and "--run to file them" in out
    assert len([l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")]) == 2


def test_replay_on_an_empty_queue_is_quiet_and_succeeds(pt, git_repo, capsys):
    assert pt.main(["issue", "replay", "--root", str(git_repo)]) == 0
    assert "nothing queued" in capsys.readouterr().out


def test_replay_run_refuses_without_gh(pt, git_repo, monkeypatch, capsys):
    """Running the script with no gh would fail partway and leave the queue in an
    unknown state, so it must not start."""
    monkeypatch.setattr(pt, "gh_ready", lambda: False)
    file_issue(pt, git_repo, "queued")
    assert pt.main(["issue", "replay", "--root", str(git_repo), "--run"]) == 1
    assert "not installed or not authenticated" in capsys.readouterr().err
    assert len([l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")]) == 1


def test_file_requires_a_title(pt, git_repo, capsys):
    assert pt.main(["issue", "file", "--root", str(git_repo), "--body", "b"]) == 1
    assert "--title is required" in capsys.readouterr().err


def _fake_gh(tmp_path, monkeypatch):
    """A gh on PATH that fails only for a title containing FAIL, so a partial
    replay can be exercised without touching a real tracker."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text('#!/bin/sh\ncase "$*" in *FAIL*) exit 1;; esac\nexit 0\n', encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def test_replay_does_not_refile_what_already_succeeded(pt, git_repo, tmp_path, monkeypatch):
    """Running the whole script and leaving it untouched on failure meant the commands
    that already ran stayed queued, so the next --run duplicated them in the tracker."""
    _fake_gh(tmp_path, monkeypatch)
    file_issue(pt, git_repo, "first ok")
    file_issue(pt, git_repo, "second FAIL here")
    file_issue(pt, git_repo, "third ok")
    assert pt.main(["issue", "replay", "--root", str(git_repo), "--run"]) == 1
    left = [l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")]
    assert len(left) == 2, left
    assert "first ok" not in read(script(git_repo)), "a filed issue must leave the queue"
    assert "second FAIL here" in left[0]


def test_replay_clears_the_queue_when_every_command_succeeds(pt, git_repo, tmp_path, monkeypatch):
    _fake_gh(tmp_path, monkeypatch)
    file_issue(pt, git_repo, "one")
    file_issue(pt, git_repo, "two")
    assert pt.main(["issue", "replay", "--root", str(git_repo), "--run"]) == 0
    assert [l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")] == []


def test_a_second_replay_after_a_partial_failure_files_only_what_is_left(pt, git_repo,
                                                                        tmp_path, monkeypatch):
    """The property that matters: retrying must never duplicate."""
    _fake_gh(tmp_path, monkeypatch)
    file_issue(pt, git_repo, "alpha")
    file_issue(pt, git_repo, "beta FAIL")
    pt.main(["issue", "replay", "--root", str(git_repo), "--run"])
    # the operator fixes whatever was wrong; the failing title stops failing
    text = read(script(git_repo)).replace("beta FAIL", "beta fixed")
    script(git_repo).write_text(text, encoding="utf-8")
    assert pt.main(["issue", "replay", "--root", str(git_repo), "--run"]) == 0
    assert [l for l in read(script(git_repo)).splitlines() if l.startswith("gh ")] == []
