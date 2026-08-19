# CozyPlan — State

> **This file is the single source of truth (SOT) for this system's working state.**
> Snapshot semantics: sections below describe the system *now* and are overwritten on every sync — stale lines are removed, not accumulated.
> History is never lost: it lives in the append-only ledger at [docs/journal.md](docs/journal.md).
> New to this repo? Read this file top to bottom, then run the verify commands yourself.

| Sync | |
|---|---|
| Last synced | 2026-08-19T00:18:11Z |
| Synced by | Sean Cozart <seancozart@outlook.com> · via Claude Opus 5 |
| Repo state | baseline-audit @ 2b40eed |

## Current Working State

- plan_tool CLI and both hooks pass their suite — verified by `pytest tests` (2026-08-18, 2b40eed)
- Plan validation runs without uv installed — verified by `python3 skills/cozyplan/scripts/plan_tool.py validate` (2026-08-18, 2b40eed)
- The provides/consumes graph flags unprovided contracts — verified by `plan_tool index` (2026-08-18, 2b40eed)

## How to Run / Verify

```bash
python3 -m pytest tests
python3 skills/cozyplan/scripts/plan_tool.py state check
```

## In Development

| Item | Type | Status | Owner | Record / Plan |
|---|---|---|---|---|
| state check + CI gate | plan-phase | in-development | architect | docs/adr/0004-hooks-advise-ci-enforces-derivation-tolerates-gaps.md |

## Registers

- **Plans** — [specs/_index.html](specs/_index.html)
- **Decisions (ADRs)** — [docs/adr/](docs/adr/)
  - ADR-0001 — GitHub is the work-item source of truth (accepted)
  - ADR-0002 — The interview works the design tree in rounds (accepted)
  - ADR-0003 — The system map records cross-boundary contracts only (accepted)
  - ADR-0004 — Hooks advise, CI enforces, and derivation tolerates gaps (accepted)
  - ADR-0005 — State is a union-merged log projected into capped views (accepted)
  - ADR-0006 — Grounding is a traversal with a declared stopping rule (accepted)
- **Work items** — [GitHub issues](https://github.com/smcozart/cozyplan/issues)
- **Ledger** — [docs/journal.md](docs/journal.md)

## Known Gaps / Risks

- No CI workflow yet, so `state check` is advisory only (ADR-0004)
- STATE.md is still authored, not generated — the union-merged log and `state render` from ADR-0005 are not built
- `ground` (ADR-0006) is decided but unimplemented; backward grounding needs trailer coverage that does not exist yet
