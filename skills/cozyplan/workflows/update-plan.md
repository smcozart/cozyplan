# Update Plan

1. Identify the Plan - From the `USER_PROMPT`, locate the target plan `.html` file to modify
2. Scope the Change - THINK HARD about exactly what the prompt asks to change, extend, or revise; keep the edit surgical and touch only the affected sections. **If the revision is structural** — new phases, a changed approach, altered architecture — *offer* the sibling **`discuss`** skill's Interview workflow before editing (never for status flips or wording changes); if taken, its resolved decisions arrive as locked inputs for the edit
3. Apply the Change - Edit the relevant free-form sections (Purpose, Problem, Solution, Notes, Questionables prose) in place, preserving existing structure. Do NOT hand-edit status markers, metadata, or amendments — those go through `PLAN_TOOL` (next steps). To flip a status marker use `PLAN_TOOL status PLAN_FILE --id <id> --state <state>`
4. Update Metadata - `PLAN_TOOL meta PLAN_FILE --field agent --value <name>` and `--field session --value <id>` (each appends; `modified` is stamped automatically on every CLI write). Never overwrite existing entries
5. Record Amendment - `PLAN_TOOL amend PLAN_FILE --summary "<what changed>" --detail "<what and why>"` (appends newest at the bottom). If the change supersedes the plan, also `PLAN_TOOL meta PLAN_FILE --field status --value superseded` and add the forward ref (see Update References)
6. Report - Summarize the change made and the amendment recorded
