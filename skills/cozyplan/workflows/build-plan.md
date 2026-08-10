# Build Plan

Task status markers: `[]` idle · `[wip]` in progress · `[x]` complete · `[f]` failed.

1. Locate the Plan - From the `USER_PROMPT`, resolve the path to the target plan `.html` file; if no path is given, infer the most likely plan from `PLAN_OUTPUT_DIRECTORY` and confirm before building
2. Absorb Context - Read the full plan: all embedded images, the metadata header, and every back reference (depth 1). Read `STATE_FILE` if present so you know the verified working state you are building on.
3. Execute Phases - For each phase in order, top to bottom:
   - Announce the phase you are starting
   - Set the phase and current task marker to `[wip]` in the plan file
   - Implement the task's specific actions
   - Run that phase's Testing Strategy commands; loop on failure until they pass
   - Mark each task `[x]` when complete or `[f]` if it cannot be made to pass, then move on
   - Do not start the next phase until the current phase's tasks and tests resolve
4. Final Validation - Run the global Validation Commands and confirm every box passes
5. Update Plan Metadata - Append the current ISO timestamp to `modified`, append agent name / session id, and append the relevant commit SHA(s) to the metadata header
6. Sync State - If `STATE_FILE` exists, run `workflows/sync-state.md`: promote the validated results into Current Working State (the passing Validation Commands are the proof), update In Development and any touched feature/issue records, and append the ledger entry. `[f]` failures become issue records via `workflows/track-record.md`.
7. Report - Summarize what was built per phase, the final status of every task, and any `[f]` failures that need attention
