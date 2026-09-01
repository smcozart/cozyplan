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
    # Staged deliberately. This test is about the register drifting from the ADRs
    # the repository actually carries; it used to leave both files untracked and
    # still expect them to count, which is the defect cozyplan#4 fixed rather than
    # a behaviour worth preserving. Untracked ADRs have their own test below.
    git(git_repo, "add", str(adr / "0001-first.md"), str(adr / "0002-second.md"))

    # tracked but unlisted
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0001"])
    assert run(pt, git_repo) == 1
    assert "ADR-0002 is tracked" in capsys.readouterr().out

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
    # The claim's path has to actually be carried by git: a path this repo neither
    # tracks nor ignores is a different report now, and it would fire here.
    (git_repo / "src").mkdir()
    (git_repo / "src" / "ingest").write_text("v1\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "ingest")
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


# ── the ADR register against the index, not the disk (cozyplan#4) ────────────
# render_state builds Registers from `adr_dir.glob("*.md")`. Checking the register
# against that same glob compares a generated list to its own generator, so after a
# render the two agree by construction and the check cannot fail. It reported
# `OK STATE.md: consistent with git` for an ADR git had never seen. Found by cozycode.

def _adr(repo, num, *, track):
    """Write an ADR file; stage it only when `track`."""
    d = repo / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{num}-thing.md"
    f.write_text(f"---\nid: ADR-{num}\ntitle: thing\n---\n", encoding="utf-8")
    if track:
        git(repo, "add", str(f))
    return f


def test_registers_citing_an_untracked_adr_fails(pt, git_repo, capsys):
    """The canary: on disk, in Registers, never staged. Every clone renders a
    register citing a file it does not have."""
    _adr(git_repo, "0099", track=False)
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0099"])
    assert run(pt, git_repo) == 1
    out = capsys.readouterr().out
    assert "ADR-0099" in out
    assert "not staged or committed" in out
    assert "git add" in out, "the message must name the fix, not only the failure"


def test_a_staged_adr_passes(pt, git_repo, capsys):
    """Staged is not committed, but the commit will carry it — so a clone gets it.
    This is why the check uses `--cached` and never `--cached --others`."""
    _adr(git_repo, "0099", track=True)
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0099"])
    assert run(pt, git_repo) == 0, capsys.readouterr().out


def test_a_tracked_adr_missing_from_registers_still_fails(pt, git_repo, capsys):
    """The original direction of the check must survive the fix."""
    _adr(git_repo, "0099", track=True)
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=[])
    assert run(pt, git_repo) == 1
    assert "missing from the Registers index" in capsys.readouterr().out


def test_registers_citing_an_adr_with_no_file_at_all_still_fails(pt, git_repo, capsys):
    """Distinct message from the untracked case — the remedy is different."""
    (git_repo / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    write_state(git_repo, head(git_repo), branch=branch_of(git_repo), adrs=["0099"])
    assert run(pt, git_repo) == 1
    assert "has no file in" in capsys.readouterr().out


def _age_out(repo, n=3):
    """Push HEAD n commits past the claim so --max-claim-age 1 fires."""
    for i in range(n):
        (repo / f"unrelated{i}.md").write_text("x\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", f"unrelated {i}")


def _ignore(repo, pattern):
    """Make `pattern` gitignored here, the way a sibling repository is (ADR-0019)."""
    (repo / ".gitignore").write_text(pattern + "\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "ignore a sibling")


def test_an_aged_claim_whose_subject_this_repo_cannot_see_says_so(pt, git_repo, capsys):
    """ADR-0018 rule 5. `git diff` returns nothing for an untracked path, and nothing
    is what an untouched path returns too. Found live in cozycode: 18 of 35 aged
    claims pointed into a gitignored sibling repo and every one read clean."""
    sha = head(git_repo)
    _ignore(git_repo, "cozysites/")
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "cozysites/sites/reference"))
    _age_out(git_repo)
    assert run(pt, git_repo, "--max-claim-age", "1") != 0
    out = capsys.readouterr().out
    assert "unverifiable here, not verified" in out
    assert "own code changed" not in out


def test_an_ignored_subject_is_unverifiable_and_a_missing_one_is_gone(pt, git_repo, capsys):
    """The middle state, named honestly. Both paths are untracked and `ls-files` cannot
    tell them apart; `check-ignore` can, and they are opposite reports — one is the
    checker unable to look (ADR-0019, permanent, not fatal), the other is a file that
    was renamed or deleted out from under the claim (a defect, and fatal)."""
    sha = head(git_repo)
    _ignore(git_repo, "cozysites/")
    write_state(git_repo, sha, claims=[
        f"- ingest works — verified by `pytest tests` (2026-08-18, {sha})",
        "  ↳ path:cozysites/sites/reference",
        f"- export works — verified by `pytest tests` (2026-08-18, {sha})",
        "  ↳ path:docs/adr/0011-renamed-away.md",
    ])
    assert run(pt, git_repo) == 1
    out = capsys.readouterr().out
    assert "neither tracks nor ignores" in out
    assert "0011-renamed-away.md" in out
    assert "cozysites/sites/reference" not in out.split("FAIL")[1]


def test_a_gone_path_is_fatal_at_any_age_and_needs_no_limit(pt, git_repo, capsys):
    """A claim whose path no longer exists is wrong on the day it is written. The old
    notice only spoke past --max-claim-age, which is the under-warning ADR-0010 exists
    to prevent, and this shape was silent entirely."""
    sha = head(git_repo)
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "src/vanished.py"))
    assert run(pt, git_repo) == 1
    assert "cannot be re-run" in capsys.readouterr().out


def test_a_gone_path_is_reported_even_beside_a_tracked_one(pt, git_repo, capsys):
    """A claim with one live path and one dead one used to fall through to the diff and
    report clean, because the untracked branch only fired when NO path was tracked."""
    sha = head(git_repo)
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "README.md", "src/vanished.py"))
    assert run(pt, git_repo) == 1
    assert "src/vanished.py" in capsys.readouterr().out


def test_an_ignored_subject_never_fails_the_run_but_leaves_a_trace(pt, git_repo, capsys):
    """Not fatal: every solution and deliverable would be permanently red for a
    structural fact no commit here can change. Not silent either — ADR-0010 forbids the
    apparatus leaving the same trace as a verified claim, and one census line is that
    trace without 42 identical ones."""
    sha = head(git_repo)
    _ignore(git_repo, "cozysites/")
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "cozysites/sites/reference"))
    assert run(pt, git_repo) == 0
    out = capsys.readouterr().out
    assert "1 claim(s) name a subject git ignores here" in out
    assert "unverifiable in this repository" in out


def test_an_aged_claim_with_no_path_is_called_unverified_not_clean(pt, git_repo, capsys):
    sha = head(git_repo)
    write_state(git_repo, sha)
    _age_out(git_repo)
    assert run(pt, git_repo, "--max-claim-age", "1") != 0
    assert "unverified here, not clean" in capsys.readouterr().out


def test_a_healthy_ledger_gains_no_new_noise(pt, git_repo, capsys):
    """The per-claim notices are gated on the age limit already firing, because a
    path-less claim producing noise on a healthy ledger is a decision this suite
    already made. The unverifiable census is a count, not a line per claim."""
    sha = head(git_repo)
    write_state(git_repo, sha)
    _age_out(git_repo)
    assert run(pt, git_repo) == 0
    out = capsys.readouterr().out
    assert "unverified here, not clean" not in out
    assert "unverifiable" not in out


def test_a_tracked_subject_still_reports_a_real_change(pt, git_repo, capsys):
    """The unreachable branch must not swallow the signal it sits in front of."""
    sha = head(git_repo)
    write_state(git_repo, sha, claims=_claim_with_paths(sha, "src/ingest"))
    (git_repo / "src").mkdir()
    (git_repo / "src" / "ingest").write_text("changed\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "touch ingest")
    _age_out(git_repo)
    assert run(pt, git_repo, "--max-claim-age", "1") != 0
    out = capsys.readouterr().out
    assert "claim's own code changed since it was proved" in out
    assert "subject is not tracked" not in out


def test_state_add_refuses_a_proof_that_cannot_be_rendered(pt, git_repo, capsys):
    """render writes the proof inside backticks and STATE_CLAIM_RE reads it back
    with [^`]+, so a backtick produces a line `state check` rejects as "claim does
    not name its proof" -- true of the line, false of the claim.

    Refused rather than stripped: the log is append-only, so a silently altered
    proof is wrong forever.
    """
    assert pt.main(["state", "add", "--root", str(git_repo), "--kind", "claim",
                    "--what", "a claim",
                    "--proof", "ran `pytest tests` => 12 passed"]) != 0
    assert "backtick" in capsys.readouterr().err
    assert not (git_repo / "docs" / "state.ndjson").exists(), "wrote an unparseable entry"


def test_state_add_refuses_a_newline_in_a_field(pt, git_repo, capsys):
    assert pt.main(["state", "add", "--root", str(git_repo), "--kind", "claim",
                    "--what", "a claim", "--proof", "line one\nline two"]) != 0
    assert "newline" in capsys.readouterr().err


def test_state_add_still_accepts_an_ordinary_proof(pt, git_repo):
    """The guard must not narrow what a real proof may say."""
    assert pt.main(["state", "add", "--root", str(git_repo), "--kind", "claim",
                    "--what", "a claim",
                    "--proof", "pytest tests => 12 passed; curl -o /dev/null => 200"]) == 0
    assert (git_repo / "docs" / "state.ndjson").exists()


def _many_claims(repo, n, sha):
    return [f"- claim {i} — verified by `pytest tests` (2026-08-18, {sha})"
            for i in range(n)]


def test_history_is_read_once_not_once_per_claim(pt, git_repo):
    """The check cost 18 ms per claim, all of it git subprocess spawn, so a growing
    ledger eventually made a pre-commit hook unusable: 400 claims took 7 s and
    10,000 would have taken three minutes.

    This asserts the shape rather than a wall-clock number, which would be flaky on
    a loaded runner: git is invoked a bounded number of times no matter how many
    claims there are. 60 claims against 20 is a 3x difference in work and must not
    be a 3x difference in git calls.
    """
    calls = []
    real = pt.git

    def counting(root, *argv):
        calls.append(argv[0])
        return real(root, *argv)

    sha = head(git_repo)
    counts = {}
    for n in (20, 60):
        write_state(git_repo, sha, claims=_many_claims(git_repo, n, sha))
        calls.clear()
        pt.git = counting
        try:
            run(pt, git_repo)
        finally:
            pt.git = real
        counts[n] = len(calls)
    assert counts[60] <= counts[20] + 2, (
        f"git calls grew with claim count: {counts} — the history is being read "
        f"per claim again")


def test_a_sha_that_is_not_an_ancestor_is_named_as_such(pt, git_repo, capsys):
    """Resolving age from one rev-list makes "unknown object" and "real commit on
    another branch" the same lookup miss. They are different reports and stayed so.
    """
    sha = head(git_repo)
    # Never hardcode "main". A runner whose init.defaultBranch is something else
    # makes the checkout fail, the test stay on the side branch, and the assertion
    # pass for the wrong reason -- which is how this first reached CI.
    base = branch_of(git_repo)
    git(git_repo, "checkout", "-q", "-b", "sidebranch")
    (git_repo / "side.txt").write_text("x\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "on the side")
    side = head(git_repo)
    git(git_repo, "checkout", "-q", base)
    assert branch_of(git_repo) == base, "could not return to the base branch"
    write_state(git_repo, sha, claims=[
        f"- a claim — verified by `pytest tests` (2026-08-18, {side})"])
    assert run(pt, git_repo) != 0
    assert "not an ancestor of HEAD" in capsys.readouterr().out


def test_an_unknown_sha_is_still_reported_as_unknown(pt, git_repo, capsys):
    sha = head(git_repo)
    write_state(git_repo, sha, claims=[
        "- a claim — verified by `pytest tests` (2026-08-18, deadbee)"])
    assert run(pt, git_repo) != 0
    assert "not a commit in this repo" in capsys.readouterr().out


def test_a_log_ahead_of_the_render_is_named_rather_than_passed(pt, git_repo, capsys):
    """`state add` writes the log; `state render` writes STATE.md; every other check
    here reads only STATE.md. So a log and its render can disagree while this command
    prints OK -- observed 2026-09-01 with 123 passed in one file and 114 in the other.
    That is ADR-0010 inside the checking tool: it observed the record of the outcome.
    """
    sha = head(git_repo)
    write_state(git_repo, sha)
    log = git_repo / "docs" / "state.ndjson"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        '{"kind": "claim", "key": "k", "what": "a claim the render never saw", '
        f'"proof": "pytest tests", "sha": "{sha}", "date": "2026-09-01", '
        '"ts": "2026-09-01T00:00:00Z"}\n', encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "log ahead of render")

    run(pt, git_repo)
    out = capsys.readouterr().out
    assert "is stale against the log" in out
    assert "a claim the render never saw" in out, "the warn must name what is missing"


def test_a_log_the_render_already_carries_is_not_reported_stale(pt, git_repo, capsys):
    """The other half of the canary. A warn that cannot go green is noise, and this
    repository already has one signal nobody clears.
    """
    sha = head(git_repo)
    write_state(git_repo, sha, claims=["- carried through — verified by `pytest tests` "
                                       f"(2026-09-01, {sha})"])
    log = git_repo / "docs" / "state.ndjson"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        '{"kind": "claim", "key": "k", "what": "carried through", '
        f'"proof": "pytest tests", "sha": "{sha}", "date": "2026-09-01", '
        '"ts": "2026-09-01T00:00:00Z"}\n', encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", "log matches render")

    run(pt, git_repo)
    assert "is stale against the log" not in capsys.readouterr().out


def test_clear_is_addressed_by_key_and_does_not_need_what(pt, git_repo, capsys):
    """A retraction is addressed by --key. --what exists only to derive a key when none
    is given, so requiring both made the common case fail for an unrelated reason --
    observed 2026-09-01, where three rejected clears were followed by a real `state
    render` whose success was the last line printed, so a batch that retracted nothing
    read as having worked.
    """
    sha = head(git_repo)
    write_state(git_repo, sha)
    assert pt.main(["state", "add", "--root", str(git_repo), "--kind", "gap",
                    "--what", "a gap to retract", "--sha", sha]) == 0
    capsys.readouterr()

    assert pt.main(["state", "add", "--root", str(git_repo), "--clear",
                    "--key", "a gap to retract"]) == 0
    assert "(cleared)" in capsys.readouterr().out


def test_clear_with_neither_key_nor_what_is_refused(pt, git_repo, capsys):
    assert pt.main(["state", "add", "--root", str(git_repo), "--clear"]) != 0
    assert "--clear needs --key" in capsys.readouterr().err


def test_clear_of_an_unknown_key_still_refuses(pt, git_repo, capsys):
    """The ADR-0010 guard below it must survive: appending a clear no earlier event
    matches printed "(cleared)" and looked exactly like a successful one.
    """
    assert pt.main(["state", "add", "--root", str(git_repo), "--clear",
                    "--key", "nothing-has-this-key"]) != 0
    assert "nothing to clear" in capsys.readouterr().err
