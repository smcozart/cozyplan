# Init State

Scaffold the state layer in a repo: the `STATE_FILE` snapshot plus the `DOCS_DIR` records and ledger. Idempotent — adopt what already exists, never clobber it.

1. Detect - Check for `STATE_FILE`, `docs/adr/`, `docs/features/`, `docs/issues/`, and `docs/journal.md`. If all exist and are populated, report that the state layer is already initialized and stop. If partial, create only what is missing.
2. Interrogate the Repo - Read the README, package manifests, entry points, test suites, and `git log --oneline -20`; scan existing plans with `PLAN_TOOL brief --all --specs specs` (never wholesale); read the context artifacts (`STACK.md`, `CONTEXT.md`, `SYSTEM.md`, existing `docs/adr/`) when present. Draft the honest picture: what demonstrably works, what is mid-flight, what is unknown.
3. Verify - For each capability you intend to list under Current Working State, run its proof (build, test, or launch command) now. Anything that cannot be verified goes under Known Gaps / Risks — never into Current Working State.
4. Resolve Identity - `git config user.name` / `git config user.email`; if unset, ask the user. When an agent is doing the work, also capture agent name and session id.
5. Scaffold - Copy `templates/STATE.md` to `STATE_FILE` and `templates/journal.md` to `docs/journal.md`; create the three record directories. Fill every `{{PLACEHOLDER}}`.
6. Backfill Registers - Register existing `specs/` plans under In Development (`draft`/`active` plans) or Current Working State (`built` plans whose validation you verified). Existing `docs/adr/` entries (however they were authored) go in the ADR register as-is. If the repo carries pre-existing decision or issue notes elsewhere, offer to convert them into records via `workflows/track-record.md` — offer, don't force.
7. First Ledger Entry - Append the initialization entry to the journal: who initialized, why, and the state as found.
8. Report - Completion criterion: `STATE_FILE` exists with zero `{{}}` tokens, every Current Working State line names its proof, and the journal holds its first entry.
