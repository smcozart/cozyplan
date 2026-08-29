"""`--root` is honoured by the path flags beside it, and a missing root is refused.

Every other test in this suite passes ABSOLUTE paths for `--log`, `--file` and
`--adr-dir`. That is why the suite has always been green on a defect that is five
days old in its own ledger: it worked around the bug rather than covering it.

The defect matters because `--root` is how a consuming repository reaches this
tool from somewhere else. A site records a claim into a workspace ledger that way.
When `--root` is accepted and not honoured, the read half reports an empty ledger
and the write half writes into the wrong one -- neither of them failing.
"""
from __future__ import annotations

import json

import pytest


def _cwd_elsewhere(repo, monkeypatch):
    """Run from a directory that is not the root, which is the whole point."""
    elsewhere = repo / "not-the-root"
    elsewhere.mkdir(exist_ok=True)
    monkeypatch.chdir(elsewhere)
    return elsewhere


def test_state_add_writes_under_root_not_cwd(pt, git_repo, monkeypatch):
    elsewhere = _cwd_elsewhere(git_repo, monkeypatch)
    assert pt.main(["state", "add", "--root", str(git_repo),
                    "--kind", "claim", "--what", "a claim", "--proof", "a proof"]) == 0
    assert (git_repo / "docs" / "state.ndjson").exists(), "wrote nothing under --root"
    assert not (elsewhere / "docs").exists(), "wrote relative to the working directory"


def test_state_show_reads_the_root_ledger(pt, git_repo, monkeypatch, capsys):
    (git_repo / "docs").mkdir(parents=True, exist_ok=True)
    (git_repo / "docs" / "state.ndjson").write_text(
        json.dumps({"kind": "claim", "key": "findable", "what": "findable",
                    "ts": "2026-08-29T00:00:00-05:00", "date": "2026-08-29",
                    "proof": "p", "sha": "abc1234", "by": "T"}) + "\n",
        encoding="utf-8")
    _cwd_elsewhere(git_repo, monkeypatch)
    pt.main(["state", "show", "--root", str(git_repo)])
    assert "findable" in capsys.readouterr().out, "read a ledger relative to cwd, not --root"


def test_state_add_refuses_a_root_that_does_not_exist(pt, tmp_path, capsys):
    """The false positive this exists to stop: a stale --root used to create a
    whole new ledger at the dead path and report success, so the claim landed
    where nobody reads and the real ledger got nothing."""
    ghost = tmp_path / "ghost-workspace"
    rc = pt.main(["state", "add", "--root", str(ghost),
                  "--log", str(ghost / "docs" / "state.ndjson"),
                  "--kind", "claim", "--what", "phantom", "--proof", "phantom"])
    assert rc != 0, "reported success against a root that does not exist"
    assert not ghost.exists(), "fabricated a ledger at a path that did not exist"


def test_index_resolves_specs_under_root(pt, git_repo, monkeypatch):
    (git_repo / "specs").mkdir(parents=True, exist_ok=True)
    _cwd_elsewhere(git_repo, monkeypatch)
    assert pt.main(["index", "--root", str(git_repo)]) == 0, "looked for specs/ beside cwd"
    assert (git_repo / "specs" / "_index.json").exists()
