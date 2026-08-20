"""`state render`'s overwrite guard and `state migrate` (ADR-0005).

render truncates its output file. Before the guard, a repo with a hand-authored
STATE.md and no event log rendered a complete, well-formed, entirely empty
snapshot and exited 0 — and `state check` then passed on it, so nothing
downstream caught the loss either.
"""

from __future__ import annotations

import json

from conftest import git, read

# A genuine pre-3.0 snapshot: authored by hand, no generated marker, carrying
# content in sections the new format has no home for.
LEGACY = """# demo — State

> Single source of truth for working state.

| Sync | |
|---|---|
| Last synced | 2026-08-18 |
| Synced by | A Person <a@example.com> · via Claude |
| Repo state | main @ abc1234 |

## Current Working State

- ingest works — verified by `pytest tests/ingest` (2026-08-18, abc1234)
- the CLI validates plans — verified by `plan_tool validate` (2026-08-17)

## How to Run / Verify

```bash
pytest tests
```

## In Development

| Item | Type | Status | Owner | Record / Plan |
|---|---|---|---|---|
| the state layer | plan-phase | in-development | architect | docs/adr/0005-state.md |

## Known Gaps / Risks

- the CI check is not marked required
"""


def _common(repo):
    return ["--root", str(repo), "--log", str(repo / "docs" / "state.ndjson"),
            "--file", str(repo / "STATE.md")]


def render(pt, repo, *extra):
    return pt.main(["state", "render", *_common(repo),
                    "--adr-dir", str(repo / "docs" / "adr"),
                    "--journal", str(repo / "docs" / "journal.md"), *extra])


def migrate(pt, repo, *extra):
    return pt.main(["state", "migrate", *_common(repo), *extra])


def events(repo):
    log = repo / "docs" / "state.ndjson"
    return [json.loads(l) for l in read(log).splitlines() if l.strip()] if log.exists() else []


def test_render_refuses_to_overwrite_a_hand_authored_state_file(pt, git_repo, capsys):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert render(pt, git_repo) == 1
    assert "ingest works" in read(git_repo / "STATE.md"), "the file must be untouched"
    err = capsys.readouterr().err
    assert "not generated" in err and "state migrate" in err


def test_force_overwrites_deliberately(pt, git_repo):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert render(pt, git_repo, "--force") == 0
    assert "ingest works" not in read(git_repo / "STATE.md")


def test_render_still_overwrites_its_own_output(pt, git_repo):
    """The guard must not break the normal path: generated output carries the marker,
    so re-rendering stays a no-question overwrite."""
    assert render(pt, git_repo) == 0
    assert render(pt, git_repo) == 0


def test_dry_run_prints_without_writing(pt, git_repo, capsys):
    assert render(pt, git_repo) == 0
    before = read(git_repo / "STATE.md")
    (git_repo / "STATE.md").write_text(before + "\nsentinel\n", encoding="utf-8")
    assert render(pt, git_repo, "--dry-run") == 0
    assert "sentinel" in read(git_repo / "STATE.md")
    assert "# " in capsys.readouterr().out


def test_migrate_carries_claims_indev_and_gaps(pt, git_repo):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert migrate(pt, git_repo) == 0
    kinds = [e["kind"] for e in events(git_repo)]
    assert kinds.count("claim") == 2 and kinds.count("indev") == 1 and kinds.count("gap") == 1
    claim = [e for e in events(git_repo) if e["kind"] == "claim"][0]
    assert claim["what"] == "ingest works"
    assert claim["proof"] == "pytest tests/ingest"
    assert claim["sha"] == "abc1234"
    assert claim["date"] == "2026-08-18", "the claim keeps its own date, not today's"


def test_migrate_never_invents_a_sha_for_an_unanchored_claim(pt, git_repo):
    """Back-filling HEAD would assert a proof ran at a commit where it never ran, and
    check_state would then compute a staleness distance from a fiction."""
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    migrate(pt, git_repo)
    unanchored = [e for e in events(git_repo) if e.get("what") == "the CLI validates plans"][0]
    assert "sha" not in unanchored


def test_migrate_names_everything_it_could_not_carry(pt, git_repo, capsys):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    migrate(pt, git_repo)
    out = capsys.readouterr().out
    assert "not carried over" in out
    # `weight` used to be on this list. Deleting the feature deleted the migration
    # problem with it, which is the point of deleting it.
    for expected in ("How to Run", "Synced by", "paths", "Type column"):
        assert expected in out, expected


def test_migrate_maps_an_adr_link_to_a_ref(pt, git_repo):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    migrate(pt, git_repo)
    indev = [e for e in events(git_repo) if e["kind"] == "indev"][0]
    assert indev["refs"]["adr"] == ["0005"]
    assert indev["status"] == "in-development" and indev["owner"] == "architect"


def test_migrate_is_a_noop_on_an_already_generated_file(pt, git_repo, capsys):
    assert render(pt, git_repo) == 0
    assert migrate(pt, git_repo) == 0
    assert "already generated" in capsys.readouterr().out
    assert events(git_repo) == []


def test_migrate_then_render_round_trips(pt, git_repo):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert migrate(pt, git_repo) == 0
    assert render(pt, git_repo) == 0, "the guard must pass once content is in the log"
    rendered = read(git_repo / "STATE.md")
    assert "ingest works" in rendered
    assert "the CI check is not marked required" in rendered


def test_migrate_sets_the_original_aside(pt, git_repo):
    """Leaving it in place would deadlock the user: migrate says 'now render', and
    render's guard refuses because the file still carries no marker."""
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert migrate(pt, git_repo) == 0
    assert not (git_repo / "STATE.md").exists()
    assert "How to Run" in read(git_repo / "STATE.md.pre-migration")


def test_migrate_refuses_to_run_twice_over_its_own_backup(pt, git_repo, capsys):
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert migrate(pt, git_repo) == 0
    (git_repo / "STATE.md").write_text(LEGACY, encoding="utf-8")
    assert migrate(pt, git_repo) == 1
    assert "already run" in capsys.readouterr().err
