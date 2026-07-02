# Create Plan

1. Analyze Requirements - THINK HARD and parse the `USER_PROMPT` to understand the core problem and desired outcome
2. Explore Codebase - Understand existing patterns, architecture, relevant files, and prior specs to back-reference. Read `AI_DOCS` for AI/agent-facing documentation and `APP_DOCS` for application documentation to ground the plan.
3. Design Solution - Develop technical approach including architecture decisions and implementation strategy
4. Author HTML Plan - Fill the `## Plan Template`, replacing every `{{PLACEHOLDER}}` and repeating `<!-- repeat -->` blocks as needed. Set `data-meta="id"` to a short immutable slug and `data-meta="owner"` to the owning role; leave `status` as `draft`. Number `data-phase`/`data-status-for`/`data-task` anchors as you duplicate blocks (phases `phase-1`, `phase-2`; tasks `1.1`, `1.2`)
5. Generate Diagrams - Run the Create sub-workflow in `workflows/diagram-generation.md` to fill the `{{...IMAGE` slots with Excalidraw diagrams. Author the diagrams one at a time (the render step is fast and local).
6. Surface Questionables - If `QUESTIONABLE` is true, populate the conditional Questionables section with open decisions/assumptions/risks; otherwise omit the section
7. Generate Filename - Create a descriptive kebab-case filename based on the plan's main topic
8. Save - Write the plan to `PLAN_FILE` (a fresh file, so a direct Write is allowed), then run `PLAN_TOOL init-ids PLAN_FILE` to backfill any missing anchors and `PLAN_TOOL validate PLAN_FILE`, fixing any failures before continuing
9. Index - Run `PLAN_TOOL index` to refresh `specs/_index.json` / `specs/_index.html` and surface any dangling references or doc drift
10. Open in Browser - Open the saved plan in the default browser using the platform-appropriate command: Windows `start "" PLAN_FILE`, macOS `open PLAN_FILE`, Linux `xdg-open PLAN_FILE`
11. Report - Provide a summary of the plan's key components
