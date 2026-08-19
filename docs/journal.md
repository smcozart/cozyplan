# Journal — Append-Only Ledger

<!-- RULES — this header is the single source of truth for the entry format.
     Newest entry goes at the BOTTOM. Never edit or delete an existing entry;
     corrections get a new entry that references the one they correct.

     Entry format:

## [{{ISO_TIMESTAMP}}] {{USER_NAME}} <{{USER_EMAIL}}>{{ · via AGENT_NAME · session SESSION_ID — include only when an agent did the work}}
- **What:** {{files / areas / records touched}}
- **Why:** {{the intent behind the change}}
- **State →** {{the resulting working state — what now works or is in flight, and its proof}}
- **Refs:** {{plan / ADR / feature / issue links}}
-->

## [2026-08-19T00:00:00-05:00] Sean Cozart <seancozart@outlook.com> · via Claude Opus 5 · session s-audit-03
- **What:** `plan_tool.py` (init, state migrate, render guard, hook runner), `.githooks/`, `skills/cozyplan/templates/`, `workflows/init-state.md`, `workflows/sync-state.md`, `docs/migrating-to-3.0.md`, `.claude-plugin/plugin.json`
- **Why:** Close items 4 and 8 of the baseline audit, cut 3.0.0, and settle the three open decisions. Ground (item 6) was deliberately deferred rather than built — the shape question had gone unanswered across two sessions, which read as an over-specified design rather than missing input.
- **State →** `plan_tool init` wires a repo in one idempotent command (203 tests pass, `doctor` reports 0 gaps). `state render` can no longer silently destroy a hand-authored `STATE.md`, and `state migrate` carries one into the log. A latent bug that disabled commit-msg trailer injection entirely on any path containing a space is fixed and pinned.
- **Refs:** ADR-0001, ADR-0004, ADR-0005, ADR-0006, ADR-0007
