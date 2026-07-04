# Generate Roles

Scope a project (not a single plan) into **roles** — the owners of its plans, code, and
docs. Roles are project-scoped: generated once at kickoff and revised as the architecture
evolves. Each role is one hand-authored source-of-truth file at `roles/<role>.md`; the
**ownership map** (`roles/_roles.json`) and `.github/CODEOWNERS` are generated from those
files. planf3 only *compiles* the map — ownership is enforced by git + PR review +
CODEOWNERS, not at edit time, and `git blame` answers "who changed my file." Author role
files from `templates/role.md`.

**Role mode is opt-in.** Run this workflow only when the user explicitly asks for roles
(or asks to scope a team). If the user's prompt is ambiguous about wanting roles, ask
before creating any `roles/` artifacts — some users deliberately run planf3 role-free
with their own agentic approach, and that is a fully supported mode.

1. **Derive candidate roles from the plan/project structure.**
   - **Architect** is always created — owns vision/strategy plans (`specs/vision-*.html`, `specs/roadmap-*.html`), the role source files (`roles/**`), and `docs/architecture/**`. It does NOT own generated aggregates (`roles/_roles.json`, `.github/CODEOWNERS`, `specs/_index.*`).
   - **Engineer roles map to independently-ownable components** — a body of code with its own source-of-truth doc, its own test suite, and phases that can proceed without serializing against another component. If two phases share files and must serialize, they are ONE role. Default to fewer roles; split only when parallel ownership is real.
   - **UX role** when there is a user-facing surface, bug intake, or feature-request funnel (owns `docs/ux/**`, files bugs/features as plans).
   - Add QA / data / infra roles only by the same "owns a component with its own SoT + tests" test.
2. **Map ownership globs.** For each role propose `source_of_truth`, `code`, and `supporting` globs. Source-of-truth and code globs MUST be disjoint across roles (overlap is what causes merge pain — `roles build` rejects overlap). `supporting` globs may overlap. Shared files (README, root configs) stay unowned and architect-gated.
3. **Confirm with the user (interview step).** Use AskUserQuestion to present the proposed role set and ownership map; let the user add / merge / split / rename roles and correct globs. Also confirm the **`github` identity per role** — the `@user` / `@org/team` each role's CODEOWNERS lines map to. A role without one has its CODEOWNERS lines commented out (and `roles build` warns). This is the "who is responsible for what" sign-off before any building starts.
4. **Write role files.** For each role, author `roles/<role>.md` from `templates/role.md`, filling mission, responsibilities, a concrete Definition of Done, and the `github` identity. Create an empty `roles/<role>/memory.md` for each.
5. **Build the ownership map + CODEOWNERS.** Run `PLAN_TOOL roles build`. It generates `roles/_roles.json` (the ownership map — role → owned globs, no enforcement fields) and `.github/CODEOWNERS`, and fails if any source-of-truth/code globs overlap across roles — fix the globs and rerun until it passes.
6. **Author the team map.** Using the `excalidraw-diagram` skill (same tooling as plan diagrams — see `workflows/diagram-generation.md`), draw the role structure: one box per role and `reports_to` arrows. Keep it minimal (boxes, arrows, short labels; match the plan palette). Save as `roles/team-map.excalidraw` and render to `roles/team-map.png` as a shared reference for the team. If the excalidraw skill is unavailable, skip. Re-author whenever roles are added, split, or re-wired.
7. **Assign owners to plans.** For each existing/new plan, set `PLAN_TOOL meta <plan> --field owner --value <role>`.
8. **Report.** Summarize the role set and ownership map back to the user, and note that each agent/human assuming a role should follow the role file's Session bootstrap. Ownership is enforced downstream by git + PR review + CODEOWNERS — the `--role` label on `plan_tool` events is just a free-text attribution tag in the event log, not an enforced identity.

Revising later: add a component = add `roles/<role>.md` + `PLAN_TOOL roles build`. Split a role = author the new file, narrow the old role's globs, rebuild. Ownership is a field + glob, not a directory move, so adding roles never breaks existing plan references.
