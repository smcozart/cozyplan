"""`state check`: STATE.md verified against git reality.

Per ADR-0004 the check is static — it never runs a proof command it read from a
file — and it tolerates gaps: an unanchored claim narrows the report to a warning
rather than failing the run.
"""

from __future__ import annotations

from conftest import git

SYNC = """# Demo — State

| Sync | |
|---|---|
| Last synced | {ts} |
| Synced by | Test <t@example.com> |
| Repo state | {branch} @ {sha} |

## Current Working State

{claims}

## Registers

- **Decisions (ADRs)** — [docs/adr/](docs/adr/)
{adrs}

## Known Gaps / Risks

- none
"""


def write_state(repo, sha, *, branch="main", claims=None, adrs=(), ts="2026-08-18T00:00:00Z"):
    """Compose a STATE.md in the tmp repo and return its path."""
    if claims is None:
        claims = [f"- ingest works — verified by `pytest tests` (2026-08-18, {sha})"]
    body = SYNC.format(
        ts=ts, branch=branch, sha=sha,
        claims="\n".join(claims),
        adrs="\n".join(f"  - ADR-{n} — thing (accepted)" for n in adrs),
    )
    p = repo / "STATE.md"
    p.write_text(body, encoding="utf-8")
    return p


def run(pt, repo, *extra):
    return pt.main(["state", "check", "--file", str(repo / "STATE.md"),
                    "--root", str(repo), "--adr-dir", str(repo / "docs" / "adr"),
                    "--journal", str(repo / "docs" / "journal.md"), *extra])


def head(repo):
    return git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def branch_of(repo):
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def test_passes_on_a_consistent_snapshot(pt, git_repo, capsys):
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo))
    assert run(pt, git_repo) == 0
    assert "OK STATE.md" in capsys.readouterr().out


def test_unfilled_placeholder_is_a_problem(pt, git_repo, capsys):
    p = write_state(git_repo, head(git_repo), branch=branch_of(git_repo))
    p.write_text(p.read_text(encoding="utf-8").replace("ingest works", "{{CAPABILITY}}"),
                 encoding="utf-8")
    assert run(pt, git_repo) == 1
    assert "unfilled {{}} placeholder" in capsys.readouterr().out


def test_repo_state_sha_must_exist(pt, git_repo, capsys):
    write_state(git_repo, "deadbee", branch=branch_of(git_repo))
    assert run(pt, git_repo) == 1
    assert "not a commit in this repo" in capsys.readouterr().out


def test_snapshot_from_an_unrelated_branch_is_a_problem(pt, git_repo, capsys):
    """A snapshot taken on a branch HEAD does not contain describes a state that
    never landed — worse than being merely behind."""
    base = head(git_repo)
    git(git_repo, "checkout", "-b", "sidetrack")
    (git_repo / "side.txt").write_text("x\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "side")
    side = head(git_repo)
    git(git_repo, "checkout", "-")
    assert side != base
    write_state(git_repo, side, branch=branch_of(git_repo))
    assert run(pt, git_repo) == 1
    assert "not an ancestor of HEAD" in capsys.readouterr().out


def test_claim_without_a_proof_is_a_problem(pt, git_repo, capsys):
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo),
                claims=["- ingest works"])
    assert run(pt, git_repo) == 1
    assert "does not name its proof" in capsys.readouterr().out


def test_unanchored_claim_warns_but_passes(pt, git_repo, capsys):
    """Date-only claims are the old format: reported, never fatal (ADR-0004)."""
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo),
                claims=["- ingest works — verified by `pytest tests` (2026-08-18)"])
    assert run(pt, git_repo) == 0
    out = capsys.readouterr().out
    assert "not commit-anchored" in out


def test_drift_is_reported_and_fails_only_past_max(pt, git_repo, capsys):
    sha = head(git_repo)
    write_state(git_repo, sha, branch=branch_of(git_repo))
    (git_repo / "later.txt").write_text("x\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "later")

    assert run(pt, git_repo) == 0
    assert "1 commit(s) behind HEAD" in capsys.readouterr().out

    assert run(pt, git_repo, "--max-drift", "0") == 1
    assert "max-drift 0" in capsys.readouterr().out


def test_adr_register_drift_both_directions(pt, git_repo, capsys):
    adr = git_repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-first.md").write_text("# one\n", encoding="utf-8")
    (adr / "0002-second.md").write_text("# two\n", encoding="utf-8")

    # on disk but unlisted
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0001"])
    assert run(pt, git_repo) == 1
    assert "ADR-0002 exists" in capsys.readouterr().out

    # listed but absent
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo),
                adrs=["0001", "0002", "0009"])
    assert run(pt, git_repo) == 1
    assert "lists ADR-0009" in capsys.readouterr().out

    # in agreement
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0001", "0002"])
    assert run(pt, git_repo) == 0


def test_missing_ledger_warns(pt, git_repo, capsys):
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo))
    assert run(pt, git_repo) == 0
    assert "no ledger" in capsys.readouterr().out


def test_ledger_missing_the_newest_sync_warns(pt, git_repo, capsys):
    journal = git_repo / "docs" / "journal.md"
    journal.parent.mkdir(parents=True)
    journal.write_text("# Journal\n\n- 2026-01-01T00:00:00Z — something\n", encoding="utf-8")
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo),
                ts="2026-08-18T00:00:00Z")
    assert run(pt, git_repo) == 0
    assert "may be unrecorded" in capsys.readouterr().out


def test_missing_state_file_is_an_error(pt, tmp_path):
    assert pt.main(["state", "check", "--file", str(tmp_path / "nope.md")]) == 1


def test_a_stale_claim_can_be_made_fatal(pt, git_repo, capsys):
    """A claim nobody re-proves is what this layer exists to prevent, so it must be
    able to fail rather than only appear as a note nobody reads."""
    sha = head(git_repo)
    write_state(git_repo, sha)
    for i in range(3):
        (git_repo / f"f{i}.txt").write_text("x\n", encoding="utf-8")
        git(git_repo, "add", "-A")
        git(git_repo, "commit", "-m", f"c{i}")
    assert run(pt, git_repo) == 0, "stale claims stay a note by default"
    capsys.readouterr()
    assert run(pt, git_repo, "--max-claim-age", "1") == 1
    assert "re-run its proof" in capsys.readouterr().out


def test_a_fresh_claim_passes_the_age_limit(pt, git_repo):
    write_state(git_repo, head(git_repo))
    assert run(pt, git_repo, "--max-claim-age", "0") == 0


def _claim_with_paths(sha, *paths):
    trail = "  ↳ " + " ".join(f"path:{p}" for p in paths)
    return [f"- ingest works — verified by `pytest tests` (2026-08-18, {sha})", trail]


def test_a_claim_whose_own_paths_changed_is_flagged(pt, git_repo, capsys):
    """Commit distance says a claim is old. Path intersection says it is probably
    wrong, which is the difference between a count and a signal."""
    sha = head(git_repo)
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "src/ingest"))
    (git_repo / "src").mkdir()
    (git_repo / "src" / "ingest").write_text("changed\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "touch ingest")
    assert run(pt, git_repo) == 0
    assert "claim's own code changed since it was proved" in capsys.readouterr().out


def test_a_commit_touching_nothing_the_claim_depends_on_stays_quiet(pt, git_repo, capsys):
    """A test run or a spike must produce no prompt, or the signal loses credibility."""
    sha = head(git_repo)
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "src/ingest"))
    (git_repo / "NOTES.md").write_text("a spike\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "unrelated")
    assert run(pt, git_repo) == 0
    assert "own code changed" not in capsys.readouterr().out


def test_a_claim_with_no_path_set_is_not_flagged(pt, git_repo, capsys):
    """Legacy and migrated claims carry no paths; they must not produce noise."""
    sha = head(git_repo)
    write_state(git_repo, sha)
    (git_repo / "anything.txt").write_text("x\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "c")
    assert run(pt, git_repo) == 0
    assert "own code changed" not in capsys.readouterr().out


def test_rev_count_reports_failure_instead_of_fabricating_zero(pt, git_repo):
    """`int(out or 0) if ok else 0` read a git failure as 'zero commits behind',
    which silently opened --max-drift and --max-claim-age. None is not zero."""
    assert pt.rev_count(git_repo, "HEAD..HEAD") == 0
    assert pt.rev_count(git_repo, "nope-not-a-ref..HEAD") is None
    assert pt.rev_count(pt.Path(git_repo) / "definitely-not-a-repo", "HEAD..HEAD") is None
