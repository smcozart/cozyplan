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

## [2026-08-24T14:24:49-05:00] Sean Cozart <seancozart@outlook.com> · via Claude Opus 5 · session s-enforce-01
- **What:** `hooks/run-hook.sh` (new), `hooks/hooks.json`, `plan_tool.py` (hooks selftest, plugin detection, doctor rows, hook runtime row), `docs/adr/0010-*`, `tests/test_hooks_selftest.py` (new), `tests/test_doctor.py`, `.github/workflows/state-check.yml`, `README.md`, `skills/cozyplan/reference/plan-tool.md`
- **Why:** Four probes at `guard_plan_edit` all read as success on a layer believed inert — three silences that are correct behaviour and also identical to a hook that never ran. Registration was being reported as if it were execution. Pass 1 of the enforcement work: make the layer able to demonstrate it runs, which is the precondition for the placement work in cozycode#16 and for any later gating.
- **State →** 261 tests pass. `hooks selftest` proves all four hooks react, and fails on each of the four dead states (unregistered, registered-but-inert, missing script, no interpreter). `doctor` splits `hooks registered` from `hooks observed`. CI runs the selftest on Linux, macOS and Windows. Corrected three beliefs the repo held: the uv failure was loud not silent (exit 127 on every matched call), only `PreToolUse` of the four hooks can refuse anything, and `doctor` had been telling every plugin user `not registered` because it read `CLAUDE_PLUGIN_ROOT`, which is never set in a terminal. Hooks also got faster — 24ms/call against `uv run`'s 62ms. Commit 39993cd.
- **Refs:** ADR-0010, ADR-0004, cozyplan#3, cozycode#9, cozycode#16
