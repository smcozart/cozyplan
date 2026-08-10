# Create Plan

1. Analyze Requirements - THINK HARD and parse the `USER_PROMPT` to understand the core problem and desired outcome
2. Explore Codebase - Understand existing patterns, architecture, relevant files, and prior specs to back-reference. Read `AI_DOCS` for AI/agent-facing documentation and `APP_DOCS` for application documentation. Read `STATE_FILE` if present so the plan builds on the recorded working state rather than guessing at it.
3. Design Solution - Develop technical approach including architecture decisions and implementation strategy. Decisions worth remembering past this plan get an ADR via `workflows/track-record.md`.
4. Author HTML Plan - Copy `templates/plan-template.html` and fill it:
   - Keep the document self-contained: all CSS lives in a single `<style>` block; no external stylesheets or scripts. The `:root` custom properties define the palette/typography — a professional, focused, minimal identity derived from the `USER_PROMPT`; diagrams reuse the same palette (see `workflows/diagram-generation.md`).
   - Leave the `{{...IMAGE}}` slots as commented placeholders naming the intended subject; step 5 fills them.
   - The plan must be executable by another developer or agent without the author present: every task names concrete files and actions, complex parts carry code or pseudo-code, and edge cases and error handling are addressed in the tasks — not left implied.
5. Generate Diagrams - Run the Create sub-workflow in `workflows/diagram-generation.md` to fill the `{{...IMAGE}}` slots. Author the diagrams one at a time (the render step is fast and local).
6. Surface Questionables - If `QUESTIONABLE` is true, populate the Questionables section with open decisions/assumptions/risks rather than silently deciding; otherwise delete the section.
7. Save - Write the plan to `PLAN_FILE` using a descriptive kebab-case filename based on the plan's main topic.
8. Register - If `STATE_FILE` exists, run `workflows/sync-state.md` to register the plan under In Development and append the ledger entry. If it doesn't, mention that Init State is available and move on.
9. Open in Browser - Open `PLAN_FILE` in `BROWSER` (platform-appropriate: `start` on Windows, `open -a` on macOS, `xdg-open` on Linux).
10. Report - Summarize the plan's key components.
