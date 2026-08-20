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

## [2026-08-19T18:36:55-05:00] Sean Cozart <seancozart@outlook.com> · via Claude Opus 5 · session s-audit-03
- **What:** `plan_tool.py` (init, state migrate, render guard, hook runner), `.githooks/`, `skills/cozyplan/templates/`, `workflows/init-state.md`, `workflows/sync-state.md`, `docs/migrating-to-3.0.md`, `.claude-plugin/plugin.json`
- **Why:** Close items 4 and 8 of the baseline audit, cut 3.0.0, and settle the three open decisions. Ground (item 6) was deliberately deferred rather than built — the shape question had gone unanswered across two sessions, which read as an over-specified design rather than missing input.
- **State →** `plan_tool init` wires a repo in one idempotent command (203 tests pass, `doctor` reports 0 gaps). `state render` can no longer silently destroy a hand-authored `STATE.md`, and `state migrate` carries one into the log. A latent bug that disabled commit-msg trailer injection entirely on any path containing a space is fixed and pinned.
- **Refs:** ADR-0001, ADR-0004, ADR-0005, ADR-0006, ADR-0007

## [2026-08-19T19:13:49-05:00] Sean Cozart <seancozart@outlook.com> · via Claude Opus 5 · session s-audit-03
- **What:** `plan_tool.py` (issue file/replay, path intersection in state check, roles removed), `tests/test_issue.py`, `track-record.md`, `README.md`, deleted `generate-roles.md` and `templates/role.md`
- **Why:** Close the last three feature gaps before 3.0: the gh-less queue that ADR-0001 promised but nothing implemented, claim path sets that were collected and never consumed, and roles/CODEOWNERS which answered a question nothing asks.
- **State →** 211 tests pass, `doctor` reports 0 gaps, `state check` is clean. `plan_tool` is 2,793 lines after removing roles and adding the queue. Remaining before release: install `gh`, open the PR so `state-check.yml` runs on a real runner for the first time, mark the check required, tag v3.0.0.
- **Refs:** ADR-0001, ADR-0004, ADR-0005, ADR-0006, ADR-0008
