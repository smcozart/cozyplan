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
   - On phase completion, if the working tree is clean (all phase work committed), take a checkpoint: `PLAN_TOOL checkpoint PLAN_FILE --label "phase <n> complete"` — it binds the plan to the verified commit and creates a git tag as a revert point. Skip it if the tree is dirty (checkpoint refuses a dirty tree by design)
4. Final Validation - Run the global Validation Commands, mark each with `PLAN_TOOL status`, and confirm every box is `[x]` or `[f]`
5. Update Metadata - Record the build in the metadata header: `PLAN_TOOL build-meta PLAN_FILE --agent <name> --session <id>` (auto-captures and verifies HEAD, appends agent/session, stamps `modified`). When the plan is implemented and tests pass, set `PLAN_TOOL meta PLAN_FILE --field status --value built`
6. Report - Summarize what was built per phase, the final status of every task, and any `[f]` failures that need attention. Report back to the architect: `PLAN_TOOL report PLAN_FILE --role <r> --status done --summary "…"`. **Acceptance is the architect's step, not the builder's:** under `acceptance=manual` the plan stays "pending acceptance" in `rollup` until the architect runs `PLAN_TOOL accept PLAN_FILE` (which records acceptance and creates its own checkpoint tag)
