# Build Plan

Task status markers: `[]` idle · `[wip]` in progress · `[x]` complete · `[f]` failed.

1. Locate the Plan - From the `USER_PROMPT`, resolve the path to the target plan `.html` file; if no path is given, infer the most likely plan from `PLAN_OUTPUT_DIRECTORY` and confirm before building
2. Absorb Context - Read the full plan: all embedded images, the metadata header, and every back reference (depth 1) so you fully understand prior/related work before writing code
3. Execute Phases - For each phase in order, top to bottom:
   - Announce the phase you are starting
   - Set the phase and current task marker to `[wip]`: `PLAN_TOOL status PLAN_FILE --id <id> --state wip` (ids are `phase-<n>` and `<phase>.<task>`)
   - Implement the task's specific actions
   - Run that phase's Testing Strategy commands; loop on failure until they pass
   - Mark each task complete `PLAN_TOOL status PLAN_FILE --id <id> --state x`, or if it cannot be made to pass, `--state f --reason "<one line>"`, then move on
   - Do not start the next phase until the current phase's tasks and tests resolve
   - On phase completion, commit the phase's work with git (and optionally tag it, e.g. `git tag cozyplan/<id>/phase-<n>`). Commits and tags are your revert points — cozyplan records intent, git owns checkpoints and reverts
4. Final Validation - Run the global Validation Commands, mark each with `PLAN_TOOL status`, and confirm every box is `[x]` or `[f]`
5. Update the Component Map - If this build added, removed, renamed, or re-owned a component, update its one line in `SYSTEM.md` (nodes only: name · responsibility · owner · why-links — point the why-link at the very plan/ADR just built; the map's format and rules live in the sibling **`discuss`** skill's `templates/system.md`). Skip silently when the project has no `SYSTEM.md` or nothing structural changed
6. Update Metadata - Record the build in the metadata header: append `PLAN_TOOL meta PLAN_FILE --field agent --value <name>`, `--field session --value <id>`, and `--field commits --value <sha>` for the build commit(s) (each appends; `modified` is stamped automatically on every CLI write). When the plan is implemented and tests pass, set `PLAN_TOOL meta PLAN_FILE --field status --value built`
7. Report - Summarize what was built per phase, the final status of every task, and any `[f]` failures that need attention. Acceptance is not a cozyplan step: open a PR and let review + merge (git, CODEOWNERS, CI) be the acceptance gate
