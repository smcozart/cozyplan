"""`state add` / `render` / `show`: the append-only log and its projection.

ADR-0005: the log is Tier 1 (append-only, union-merged), STATE.md is Tier 2
(generated), and ordering is commit order — not file order, which union merge
does not preserve, and not wall clock, which skews.
"""

from __future__ import annotations

import json

from conftest import git, read


def add(pt, repo, **kw):
    argv = ["state", "add", "--root", str(repo), "--log", str(repo / "docs" / "state.ndjson")]
    for k, v in kw.items():
        flag = "--" + k.replace("_", "-")
        if v is True:
            argv.append(flag)
        else:
            argv += [flag, str(v)]
    return pt.main(argv)


def render(pt, repo, *extra):
    return pt.main(["state", "render", "--root", str(repo),
                    "--log", str(repo / "docs" / "state.ndjson"),
                    "--file", str(repo / "STATE.md"),
                    "--adr-dir", str(repo / "docs" / "adr"),
                    "--journal", str(repo / "docs" / "journal.md"), *extra])


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", msg)


def test_add_appends_one_json_event(pt, git_repo):
    assert add(pt, git_repo, kind="claim", key="k", what="it works", proof="pytest") == 0
    lines = read(git_repo / "docs" / "state.ndjson").strip().split("\n")
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["kind"] == "claim" and ev["key"] == "k" and ev["proof"] == "pytest"
    # the proof date is derived from the event's own timestamp, never a second field
    assert ev["date"] == ev["ts"][:10]


def test_render_is_idempotent(pt, git_repo):
    """Re-rendering unchanged inputs must be byte-identical, or the generated-files
    CI step would fail on every run."""
    add(pt, git_repo, kind="claim", key="k", what="it works", proof="pytest")
    assert render(pt, git_repo) == 0
    once = read(git_repo / "STATE.md")
    assert render(pt, git_repo) == 0
    assert read(git_repo / "STATE.md") == once


def test_last_write_wins_per_key(pt, git_repo):
    add(pt, git_repo, kind="claim", key="k", what="old wording", proof="pytest")
    add(pt, git_repo, kind="claim", key="k", what="new wording", proof="pytest")
    render(pt, git_repo)
    out = read(git_repo / "STATE.md")
    assert "new wording" in out and "old wording" not in out


def test_clear_retracts_but_keeps_history(pt, git_repo):
    add(pt, git_repo, kind="gap", key="g", what="a risk")
    add(pt, git_repo, kind="gap", key="g", what="a risk", clear=True)
    render(pt, git_repo)
    assert "a risk" not in read(git_repo / "STATE.md")
    # the log is append-only: the retraction is a new line, nothing is rewritten
    assert len(read(git_repo / "docs" / "state.ndjson").strip().split("\n")) == 2


def test_commit_order_beats_file_order(pt, git_repo):
    """The load-bearing guarantee. Union merge concatenates without ordering, so a
    later event can end up physically ABOVE an earlier one. The projection must
    follow the commit that introduced each line, not its position in the file."""
    log = git_repo / "docs" / "state.ndjson"
    add(pt, git_repo, kind="claim", key="k", what="first", proof="p")
    commit(git_repo, "first event")
    first_line = read(log).strip()

    # Simulate the post-merge layout: the newer event lands above the older one.
    add(pt, git_repo, kind="claim", key="k", what="second", proof="p")
    second_line = [l for l in read(log).strip().split("\n") if "second" in l][0]
    log.write_text(second_line + "\n" + first_line + "\n", encoding="utf-8")
    commit(git_repo, "second event, written above the first")

    assert read(log).splitlines()[0].find("second") > 0, "file order really is second-first"
    render(pt, git_repo)
    out = read(git_repo / "STATE.md")
    assert "second" in out and "first" not in out


def test_uncommitted_events_sort_last(pt, git_repo):
    add(pt, git_repo, kind="claim", key="k", what="committed", proof="p")
    commit(git_repo, "committed event")
    add(pt, git_repo, kind="claim", key="k", what="uncommitted", proof="p")
    render(pt, git_repo)
    assert "uncommitted" in read(git_repo / "STATE.md")



def test_refs_render_as_a_pointer_trail(pt, git_repo):
    add(pt, git_repo, kind="claim", key="k", what="it works", proof="pytest",
        adr="0007,0009", issue="42", plan="streaming-ingest", phase="2.3",
        paths="src/ingest")
    render(pt, git_repo)
    out = read(git_repo / "STATE.md")
    for token in ("adr:0007", "adr:0009", "issue:#42", "plan:streaming-ingest",
                  "phase:2.3", "path:src/ingest"):
        assert token in out


def test_malformed_lines_are_skipped_not_fatal(pt, git_repo):
    """Union merge can land junk. A log that will not fully parse must still
    render what it can (ADR-0004 gap tolerance)."""
    add(pt, git_repo, kind="claim", key="k", what="survivor", proof="p")
    log = git_repo / "docs" / "state.ndjson"
    log.write_text("{not json at all\n" + read(log) + '{"kind":"bogus"}\n', encoding="utf-8")
    assert render(pt, git_repo) == 0
    assert "survivor" in read(git_repo / "STATE.md")


def test_adr_register_is_derived_so_it_cannot_drift(pt, git_repo):
    adr = git_repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-a-thing.md").write_text("---\ntitle: A thing\n---\n", encoding="utf-8")
    (adr / "0002-another.md").write_text("---\ntitle: Another\n---\n", encoding="utf-8")
    add(pt, git_repo, kind="claim", key="k", what="it works", proof="p")
    render(pt, git_repo)
    out = read(git_repo / "STATE.md")
    assert "ADR-0001 — A thing" in out and "ADR-0002 — Another" in out


def test_rendered_state_passes_state_check(pt, git_repo, capsys):
    """The generated file must satisfy the checker that guards hand-written ones."""
    add(pt, git_repo, kind="claim", key="k", what="it works", proof="pytest",
        sha=git(git_repo, "rev-parse", "--short", "HEAD").stdout.strip())
    render(pt, git_repo)
    capsys.readouterr()
    code = pt.main(["state", "check", "--root", str(git_repo),
                    "--file", str(git_repo / "STATE.md"),
                    "--adr-dir", str(git_repo / "docs" / "adr"),
                    "--journal", str(git_repo / "docs" / "journal.md")])
    assert code == 0, capsys.readouterr().out




# ── `state add --clear` must observe that it cleared something ───────────────
# Keys are derived by truncating --what, so they are easy to get subtly wrong.
# A clear for a key nothing matches is a no-op that printed "(cleared)" and read
# exactly like a successful one — a command reporting an outcome it never
# observed, which is ADR-0010's whole subject. It happened three times in one
# session, and each time the gap silently stayed open in STATE.md.

def _add(pt, repo, **kw):
    argv = ["state", "add", "--root", str(repo), "--log", str(repo / "docs" / "state.ndjson")]
    for k, v in kw.items():
        argv += [f"--{k.replace('_', '-')}"] + ([] if v is True else [str(v)])
    return pt.main(argv)


def test_clearing_an_unknown_key_fails(pt, git_repo, capsys):
    assert _add(pt, git_repo, kind="gap", what="a real gap") == 0
    capsys.readouterr()
    assert _add(pt, git_repo, kind="gap", clear=True, key="no-such-key", what="x") == 1
    assert "nothing to clear" in capsys.readouterr().err


def test_a_near_miss_key_suggests_the_real_one(pt, git_repo, capsys):
    """The actual failure mode: a key off by a character or two at the truncation."""
    long_what = "Version skew is undetectable because a snapshot cannot know it is old"
    assert _add(pt, git_repo, kind="gap", what=long_what) == 0
    real = [e for e in pt.read_state_log(git_repo, git_repo / "docs" / "state.ndjson")
            if e.get("key")][0]["key"]
    capsys.readouterr()
    assert _add(pt, git_repo, kind="gap", clear=True, key=real[:-1], what="x") == 1
    err = capsys.readouterr().err
    assert "did you mean" in err
    assert real in err, err


def test_clearing_a_known_key_still_works(pt, git_repo, capsys):
    assert _add(pt, git_repo, kind="gap", what="a real gap") == 0
    key = [e for e in pt.read_state_log(git_repo, git_repo / "docs" / "state.ndjson")
           if e.get("key")][0]["key"]
    capsys.readouterr()
    assert _add(pt, git_repo, kind="gap", clear=True, key=key, what="closed") == 0
    assert "(cleared)" in capsys.readouterr().out


def test_one_bad_clear_cannot_validate_the_next(pt, git_repo, capsys):
    """A previous mistyped clear is itself in the log. Counting clears as keys would
    let one typo authorise the next, which is how the first version still passed."""
    assert _add(pt, git_repo, kind="gap", what="a real gap") == 0
    capsys.readouterr()
    assert _add(pt, git_repo, kind="gap", clear=True, key="typo-key", what="x") == 1
    capsys.readouterr()
    assert _add(pt, git_repo, kind="gap", clear=True, key="typo-key", what="x") == 1, (
        "the failed clear must not have made its own key legitimate")
