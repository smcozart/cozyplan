"""`state add` / `render` / `show`: the append-only log and its capped projection.

ADR-0005: the log is Tier 1 (append-only, union-merged), STATE.md is Tier 2
(generated, capped, ranked by importance), and ordering is commit order — not
file order, which union merge does not preserve, and not wall clock, which skews.
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


def test_weight_ranks_and_cap_reports_the_remainder(pt, git_repo):
    for i, w in enumerate([1, 5, 3]):
        add(pt, git_repo, kind="gap", key=f"g{i}", what=f"gap-w{w}", weight=w)
    render(pt, git_repo, "--cap", "1")
    out = read(git_repo / "STATE.md")
    assert "gap-w5" in out, "the heaviest survives the cap"
    assert "gap-w1" not in out
    assert "2 more" in out, "a cap must say what it dropped"


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


def test_show_respects_cap_and_all(pt, git_repo, capsys):
    for i in range(3):
        add(pt, git_repo, kind="gap", key=f"g{i}", what=f"gap-{i}")
    pt.main(["state", "show", "--root", str(git_repo),
             "--log", str(git_repo / "docs" / "state.ndjson"), "--cap", "1"])
    assert "2 more" in capsys.readouterr().out
    pt.main(["state", "show", "--root", str(git_repo),
             "--log", str(git_repo / "docs" / "state.ndjson"), "--all"])
    out = capsys.readouterr().out
    assert "gap-0" in out and "gap-1" in out and "gap-2" in out
