# Init State

Wire the state layer into a repo. The mechanical half is one command; your job is the judgment half — what is actually true of this repo, and what is only assumed.

1. **Wire it** - Run `PLAN_TOOL init`. It creates the records and event log, the union-merge attribute, the CI workflow, the tracked `.githooks` plus `core.hooksPath`, the Claude Code hooks, a `CLAUDE.md` stub if the repo has no entry point, and a first rendered `STATE_FILE`. It is idempotent and never overwrites content, so it is safe on a repo that is already partly wired. Read its report: everything under **needs a human** is a step no command can take.
2. **Adopt an existing snapshot** - If the repo already has a hand-authored `STATE_FILE`, `init` refuses to render over it and says so. Run `PLAN_TOOL state migrate` to carry its claims, In Development rows, and gaps into `STATE_LOG`. It prints everything it could not carry (path sets, the How to Run block) and keeps the original at `STATE.md.pre-migration`. Salvage what it names, then delete the backup.
3. **Interrogate the repo** - Read the README, package manifests, entry points, and test suites; `git log --oneline -20`; scan plans with `PLAN_TOOL brief --all --specs specs` (never wholesale); read `STACK.md`, `CONTEXT.md`, `SYSTEM.md`, and `docs/adr/` when present. Draft the honest picture: what demonstrably works, what is mid-flight, what is unknown.
4. **Verify, then claim** - For every capability you intend to record as a claim, run its proof now. Record it with `PLAN_TOOL state add --kind claim --what "..." --proof "<the command you just ran>" --sha <HEAD> --paths <dirs it depends on>`. Anything you could not verify is `--kind gap`, never a claim. Work in flight is `--kind indev`.
5. **Backfill the registers** - Existing `docs/adr/` entries are picked up automatically by the renderer. Register `specs/` plans as `indev` (`draft`/`active`) or as claims (`built`, and only once you have run their validation).
6. **Render and check** - `PLAN_TOOL state render`, then `PLAN_TOOL state check`. Append the first entry to `docs/journal.md`.
7. **Report** - Completion criterion: `PLAN_TOOL doctor` reports zero gaps other than the ones it names as needing a human, `state check` exits 0, and every claim in `STATE_FILE` names the proof that demonstrated it.

**Never hand-edit `STATE_FILE`.** It is generated. Append an event and re-render — `state render` will refuse to overwrite a file it did not write.
