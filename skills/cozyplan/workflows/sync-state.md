# Sync State

Bring the snapshot (`STATE_FILE`) and ledger (`docs/journal.md`) up to date with what just happened. Runs standalone ("sync state", "what's the current state?") or as the closing step of Create/Update/Build Plan. If `STATE_FILE` is missing, run `workflows/init-state.md` first.

1. Resolve Identity - `git config user.name` / `git config user.email` for the human (ask if unset); agent name + session id when an agent did the work.
2. Gather the Delta - What changed since the newest journal entry: files touched (`git status`, `git diff --stat`, recent commits), plan statuses (`PLAN_TOOL brief --all --specs specs` — one line per plan; never read plan files wholesale), decisions made, issues found or fixed, features begun or shipped. When run standalone with no fresh work, the delta is a reconciliation: diff `STATE_FILE`'s claims against the repo's reality and fix drift.
3. Verify Before Claiming - Run the proof for every capability being promoted into Current Working State. A failure never enters the snapshot: it becomes an issue record (via `workflows/track-record.md`) or a Known Gaps line.
4. Update the Snapshot - Overwrite the affected `STATE_FILE` sections: the Sync header block (timestamp, identity, branch @ commit), Current Working State, How to Run / Verify, In Development, System Map, Registers, Known Gaps. Snapshot sections describe *now* — remove stale lines rather than accumulating them.
5. Update Records - For every feature/issue record this work touched, update frontmatter `status` and append a Status History line. For decisions made or issues discovered that have no record yet, run `workflows/track-record.md`.
6. Append the Ledger - Append one journal entry in the format documented at the top of `docs/journal.md` (who, what, why, resulting state, refs). Append-only.
7. Report - Completion criterion: the journal's newest entry and `STATE_FILE`'s "Last synced" timestamp match, and every Current Working State line names its proof.
