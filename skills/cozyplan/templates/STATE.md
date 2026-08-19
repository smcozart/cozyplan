# {{PROJECT_NAME}} — State

> **This file is the single source of truth (SOT) for this system's working state.**
> Snapshot semantics: sections below describe the system *now* and are overwritten on every sync — stale lines are removed, not accumulated.
> History is never lost: it lives in the append-only ledger at [docs/journal.md](docs/journal.md).
> New to this repo? Read this file top to bottom, then run the verify commands yourself.

| Sync | |
|---|---|
| Last synced | {{ISO_TIMESTAMP}} |
| Synced by | {{USER_NAME}} &lt;{{USER_EMAIL}}&gt;{{ · via AGENT_NAME · session SESSION_ID — include only when an agent did the work}} |
| Repo state | {{BRANCH}} @ {{SHORT_SHA}} |

## Current Working State

<!-- Verified claims only. Every line names its proof: the command/test that demonstrated it and when.
     Anything unverified belongs under Known Gaps / Risks or in an issue record — never here. -->

<!-- repeat -->
- {{CAPABILITY}} — verified by `{{PROOF_COMMAND}}` ({{ISO_DATE}})

## How to Run / Verify

```bash
{{SETUP_COMMANDS}}
{{VERIFY_COMMANDS}}
```

## In Development

| Item | Type | Status | Owner | Record / Plan |
|---|---|---|---|---|
<!-- repeat -->
| {{ITEM}} | {{feature / issue / plan-phase}} | {{STATUS}} | {{OWNER}} | {{RELATIVE_LINK}} |

## Registers

- **Plans** — [specs/_index.html](specs/_index.html)
- **Decisions (ADRs)** — [docs/adr/](docs/adr/)
  <!-- repeat: one line per ADR — keep this index current -->
  - {{ADR_ID}} — {{ADR_TITLE}} ({{ADR_STATUS}})
- **Work items** — the repo's issue tracker (see `docs/agents/issue-tracker.md`)
- **Components** — [SYSTEM.md](SYSTEM.md)
- **Ledger** — [docs/journal.md](docs/journal.md)

## Known Gaps / Risks

<!-- repeat -->
- {{GAP_OR_RISK}}
