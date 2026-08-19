# Sync State

Bring the state layer up to date with what just happened. Runs standalone ("sync state", "what's the current state?") or as the closing step of Create/Update/Build Plan. If the repo has no `STATE_FILE`, run `workflows/init-state.md` first.

1. **Gather the delta** - What changed since the newest event: files touched (`git status`, `git diff --stat`, recent commits), plan statuses (`PLAN_TOOL brief --all --specs specs` — one line per plan, never wholesale), decisions made, issues found or fixed. Run standalone with no fresh work, the delta is a reconciliation: `PLAN_TOOL state check` against the repo's reality, then fix what it reports.
2. **Verify before claiming** - Run the proof for every capability being recorded as a claim. A failure never becomes a claim: it becomes a gap, or a work item via `workflows/track-record.md`.
3. **Append events** - One `PLAN_TOOL state add` per change. `--kind claim` with `--proof`, `--sha`, and `--paths`; `--kind indev` with `--status` and `--owner`; `--kind gap` for what is known-broken or unverified. Supersede an entry by adding a new event with the same `--key`; retract one with `--clear`. Carry the ids: `--plan`, `--phase`, `--adr`, `--issue`, `--session`.
4. **Re-render** - `PLAN_TOOL state render`. The file is a projection of the log, so this is the only way it changes. Never edit it by hand; `render` refuses to overwrite a file it did not write, which is what protects a snapshot that predates this layer.
5. **Record what has no home yet** - Decisions become ADRs and work items go to the tracker, both via `workflows/track-record.md`.
6. **Append the ledger** - One entry in `docs/journal.md` in the format documented at its top (who, what, why, resulting state, refs). Append-only.
7. **Report** - Completion criterion: `PLAN_TOOL state check` exits 0, and every claim in `STATE_FILE` names the proof that demonstrated it.

**The log is append-only and union-merged**, so concurrent sessions combine instead of clobbering each other. Entries are pointer trails (`plan:` `adr:` `issue:` `session:` `path:`), never the detail itself.
