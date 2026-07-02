# Create Plan

1. Analyze Requirements - THINK HARD and parse the `USER_PROMPT` to understand the core problem and desired outcome
2. Explore Codebase - Understand existing patterns, architecture, relevant files, and prior specs to back-reference. Read `AI_DOCS` for AI/agent-facing documentation and `APP_DOCS` for application documentation to ground the plan.
3. Design Solution - Develop technical approach including architecture decisions and implementation strategy
4. Name the Plan - Choose a descriptive kebab-case slug for the plan's main topic. It becomes the filename (`specs/<kebab-name>.html`) and the immutable `id`.
5. Scaffold - Run `PLAN_TOOL new <kebab-name> --title "<Plan Title>" [--owner <role>]` to stamp a fresh `specs/<kebab-name>.html` from `templates/plan.html`: it fills every `data-*` anchor and the metadata (`id`, `created`, `modified`, `status=draft`, `schema`) and lays down one example phase (`phase-1`, tasks `1.1`/`1.2`) plus one global check (`g.1`) for you to duplicate. `new` refuses to overwrite an existing plan and logs a `created` event — no `init-ids` needed.
6. Author Content - Edit the scaffold **in place** (it already exists, so author with Edit, not a full-file Write). Replace every `{{...}}` content slot (purpose, problem, solution, file paths, phase names, task names, actions, testing approach, notes, figure subjects) with real content, and duplicate the example phase/task/checklist blocks as the plan needs — keep the `data-*` anchor pattern and increment ids (phases `data-phase="2"` / `data-status-for="phase-2"`; tasks `data-task="2.1"` / `data-status-for="2.1"`; extra global checks `g.2`, …). Never hand-edit the metadata, status markers, or amendments — those are CLI-managed (see `## Managed Writes`).
7. Generate Diagrams - Run the Create sub-workflow in `workflows/diagram-generation.md` to fill the `{{...IMAGE` slots with Excalidraw diagrams. Author the diagrams one at a time (the render step is fast and local).
8. Surface Questionables - If `QUESTIONABLE` is true, populate the conditional Questionables section with open decisions/assumptions/risks; otherwise delete the section
9. Validate - Run `PLAN_TOOL validate PLAN_FILE` and fix any failures. While the plan is `draft`, unfilled `{{}}` slots report a placeholder *warning* (not a failure) — but replace every slot before the plan leaves `draft`.
10. Index - Run `PLAN_TOOL index` to refresh `specs/_index.json` / `specs/_index.html` and surface any dangling references or doc drift
11. Open in Browser - Open the saved plan in the default browser using the platform-appropriate command: Windows `start "" PLAN_FILE`, macOS `open PLAN_FILE`, Linux `xdg-open PLAN_FILE`
12. Report - Provide a summary of the plan's key components
