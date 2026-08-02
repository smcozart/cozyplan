# Build Plan

Task status markers: `[]` idle · `[wip]` in progress · `[x]` complete · `[f]` failed.

1. Locate the Plan - From the `USER_PROMPT`, resolve the path to the target plan `.html` file; if no path is given, infer the most likely plan from `PLAN_OUTPUT_DIRECTORY` and confirm before building
2. Absorb Context - Recall is **index, not store**. Read the plan's state cheaply, then pull detail only for the phase in hand — never read the plan file end to end:
   - `PLAN_TOOL brief PLAN_FILE` — the whole-plan index in a few hundred tokens: metadata, one line per phase/task with its status marker, open `[wip]`/`[f]` items with their reasons, and the recent events. Orient from this
   - `PLAN_TOOL phase PLAN_FILE --id phase-<n>` — the current phase in full: its tasks, their specific actions, and its Testing Strategy. `brief` carries no task instructions, so read the phase block before implementing that phase, and re-read it (one phase at a time) as you advance
   - Back references are fetched **on demand** — read one only when a decision actually in front of you depends on it, not upfront, and read it via its own `brief` first
   - Read an embedded image only if the current phase references one
   - The cost of a build session is O(current phase), not O(whole plan + every back ref + every image)
3. Resume - Assume nothing about how far a prior session got; a build is as likely to be a re-entry as a fresh start:
   - Run `PLAN_TOOL next PLAN_FILE` to get the re-entry point — it prints the first non-terminal id (the first marker that is not `[x]` or `[f]`), or `done`. Take that id mechanically; do not reason out the resume point yourself
   - `done` means every marker is terminal — skip to Final Validation and Report; rebuild nothing
   - Phases and tasks marked `[x]` are complete: skip them entirely. Do not re-read their block, do not re-run their tests
   - `[wip]` means **a prior session was interrupted mid-task**. It is not evidence the work is done, and not evidence it is absent. Re-verify that task's actual state against the codebase (files on disk, its tests, `git log`/`git status`), then either continue it or redo it from a known state
   - Any `[f]` marker halts the build. Surface it to the user with the reason `brief` recorded and get direction before building past it
4. Execute Phases - Start at the phase `next` resolved to and work forward in order, top to bottom:
   - Announce the phase you are starting
   - Read the phase block: `PLAN_TOOL phase PLAN_FILE --id phase-<n>`
   - Set the phase and current task marker to `[wip]`: `PLAN_TOOL status PLAN_FILE --id <id> --state wip` (ids are `phase-<n>` and `<phase>.<task>`)
   - Skip tasks already marked `[x]`; implement the rest of the task's specific actions
   - Run that phase's Testing Strategy commands; loop on failure until they pass
   - Mark each task complete `PLAN_TOOL status PLAN_FILE --id <id> --state x`, or if it cannot be made to pass, `--state f --reason "<one line>"`, then move on
   - Do not start the next phase until the current phase's tasks and tests resolve
   - On phase completion, commit the phase's work with git (and optionally tag it, e.g. `git tag cozyplan/<id>/phase-<n>`). Commits and tags are your revert points — cozyplan records intent, git owns checkpoints and reverts
   - If the build reveals work the plan does not cover, append a phase with `PLAN_TOOL addphase PLAN_FILE --tasks <N> --title "<name>"` and author its content — never hand-write phase/task HTML
5. Final Validation - Run the global Validation Commands, mark each with `PLAN_TOOL status`, and confirm every box is `[x]` or `[f]` (`PLAN_TOOL next PLAN_FILE` printing `done` is the check)
6. Update the Component Map - If this build added, removed, renamed, or re-owned a component, update its one line in `SYSTEM.md` (nodes only: name · responsibility · owner · why-links — point the why-link at the very plan/ADR just built; the map's format and rules live in the sibling **`discuss`** skill's `templates/system.md`). Skip silently when the project has no `SYSTEM.md` or nothing structural changed
7. Update Metadata - Record the build in the metadata header: append `PLAN_TOOL meta PLAN_FILE --field agent --value <name>`, `--field session --value <id>`, and `--field commits --value <sha>` for the build commit(s) (each appends; `modified` is stamped automatically on every CLI write). When the plan is implemented and tests pass, set `PLAN_TOOL meta PLAN_FILE --field status --value built` — this is **refused while any status marker is still un-terminal**, which is the intended gate: resolve the remaining markers to `[x]`/`[f]` rather than reaching for `--force` (use `--force` only when the user explicitly accepts an incomplete build)
8. Report - Summarize what was built per phase, the final status of every task, and any `[f]` failures that need attention. Acceptance is not a cozyplan step: open a PR and let review + merge (git, CODEOWNERS, CI) be the acceptance gate
