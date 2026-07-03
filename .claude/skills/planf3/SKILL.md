---
name: planf3
description: Creates a concise engineering implementation plan based on user requirements and saves it to specs directory
argument-hint: "[user-prompt]"
---

# Plan F3

## Purpose

Create a detailed, **HTML-first** implementation plan based on the `USER_PROMPT` variable. The plan is authored as a single self-contained `.html` page so it can be opened in a browser, embed focused Excalidraw diagrams with a synced visual identity, and be created/updated/consumed by the agent trifecta (engineer, team, AI agents). Analyze the request, think through the implementation approach, follow the `## Instructions`, and work through the `## Workflow` to produce the plan from the `## Plan Template`.

## Variables

USER_PROMPT: $ARGUMENTS
QUESTIONABLE: default false — true when the `USER_PROMPT` explicitly asks to surface open questions, assumptions, or risks
PLAN_OUTPUT_DIRECTORY: `specs/`
PLAN_FILE: `PLAN_OUTPUT_DIRECTORY/<descriptive-kebab-name>.html`
IMAGES_OUTPUT_DIR: `PLAN_OUTPUT_DIRECTORY/<plan-name>/`
AI_DOCS: `AI_DOCS/`
APP_DOCS: `APP_DOCS/`
IDE: `code`
BROWSER: `chrome`
PLAN_TOOL: `uv run scripts/plan_tool.py` - the deterministic CLI that owns all structured writes to a plan (status, metadata, references, amendments) plus `validate` and `index`

## Instructions

- IMPORTANT: If no `USER_PROMPT` is provided, stop and ask the user to provide it
- Carefully analyze the user's requirements provided in the `USER_PROMPT` variable
- Think deeply (ultrathink) about the best approach to implement the requested functionality or solve the problem
- Explore the codebase to understand existing patterns, documentation, previous specs and architecture
- The plan is **HTML-first**: a single self-contained `.html` document. **Never hand-author the structure** — run `PLAN_TOOL new` to stamp the scaffold from `templates/plan.html` (the single source of truth for plan structure), then author only the **content** (see `## Plan Template`)
- The scaffold uses `{{PLACEHOLDER}}` variables in free-form content positions — replace EVERY `{{...}}` with real content. Leftover `{{}}` tokens are a validation *warning* while `status=draft` but a *failure* once the plan leaves draft, so none may remain in a non-draft plan
- Blocks marked with `<!-- repeat -->` are repeatable: duplicate them as many times as the plan needs (e.g. one block per phase, task, file, or Q&A entry) and delete the comment markers
- Keep the document self-contained: all CSS lives in the single `<style>` block; do not link external stylesheets or scripts
- Visuals are **Excalidraw diagrams**, not AI-generated raster art. Each diagram is a simple, straightforward box/arrow/flow drawing authored as an editable `.excalidraw` source file and rendered to a PNG (locally, no API key). Keep designs clean, minimal, and professional — easy to map out at a glance.
- Maintain a **synced visual identity** between the html styling and the diagrams. We want a professional, focused, minimal theme based on the original `USER_PROMPT` that created the plan. The CSS custom properties in `:root` define the palette/typography. Every diagram must use the same palette so the rendered PNGs sit naturally inside the page.
- For every diagram, focus on one or two primary ideas. Keep total words shown under ~10 — boxes, arrows, and short labels only. The goal is diagrams that aid the plan and convey the core information for the section they belong to.
- Build diagrams for professional software engineers to convey exactly what is going to be built. Be sure to center and space them properly.
- Embed diagrams via the `{{...IMAGE}}` slots. During Create, leave them as commented placeholders noting the intended subject; the Diagram Generation workflow fills them later
- The metadata header (`schema`, `id`, `owner`, `status`, `created`, `modified`, `commits`, `agent`, `session`, back/forward references) is **stamped by `PLAN_TOOL new`** and updatable across the plan's lifecycle. `schema`, `id`, and `created` are write-once; `status` is a single value; `modified`/`commits`/`agent`/`session`/back-refs/forward-refs are append-only comma-separated lists. `schema` is the artifact's structural-contract version (currently `1`) — leave it as the template sets it; `PLAN_TOOL` refuses to write a plan stamped newer than it understands. **Never hand-edit the metadata, status markers, or amendments — route every such write through `PLAN_TOOL` (see `## Managed Writes`).** These regions are marked `data-managed="cli"` in the template
- **Plan `status`** is a single value from a closed vocabulary: `draft` (authored, not started) → `active` (approved / being built) → `built` (implemented, tests pass); plus `superseded` (replaced — must carry a forward ref to its successor) and `archived` (kept for history). Set it with `PLAN_TOOL meta <plan> --field status --value <state>`. Create sets `draft` (or `active`); Build moves `active`→`built`
- **`id`** is a short immutable slug set once at Create (references and event logs point at it, so it survives renames). **`owner`** is the role that owns the plan (e.g. `architect`, `engineer-<component>`, `ux`); only the owner edits plan content
- If `QUESTIONABLE` is true, actively surface open questions/assumptions in the toggleable Q&A section rather than silently deciding
- Ensure the plan is detailed enough that another developer (or agent) could follow it to implement the solution
- Include code examples or pseudo-code where appropriate to clarify complex concepts
- Consider edge cases, error handling, and scalability concerns
- Save the complete plan to `PLAN_FILE` using a descriptive kebab-case filename

## Managed Writes

The plan HTML is a living artifact. Some regions are **CLI-managed** and must never be hand-edited — always go through `PLAN_TOOL` so writes stay deterministic and well-formed. A `PreToolUse` hook blocks raw edits to these regions and a `PostToolUse` hook lints the file after every write.

**Draft authoring window.** While a plan's `status` is `draft` (the state `new` stamps), the guard permits *structural* authoring via Edit — duplicating and renumbering phase/task blocks together with their `data-*` anchors and status markers — because the Create workflow requires it. Metadata (`data-meta=`) and the amendments region stay CLI-only in every status. Once the plan leaves `draft`, all managed tokens (anchors, markers, metadata, amendments) are CLI-only again.

| Write | Command |
| --- | --- |
| Scaffold a fresh plan (all `data-*` anchors + metadata stamped, `status=draft`) | `PLAN_TOOL new <kebab-name> --title "…" [--owner <role>] [--kind plan\|contract] [--specs specs]` |
| Flip a task/phase status marker | `PLAN_TOOL status <plan> --id <id> --state idle\|wip\|x\|f [--reason "…"]` (`--reason` required for `f`) |
| Append metadata (modified/commits/agent/session) or set id/owner/status/kind | `PLAN_TOOL meta <plan> --field <field> --value <v>` |
| Record build commit + agent + session at once (auto-captures + verifies HEAD) | `PLAN_TOOL build-meta <plan> [--commit <sha>] --agent <name> --session <id>` |
| Add a reference between two plans (typed) | `PLAN_TOOL ref --this <plan> --other <plan> --type back\|forward\|provides\|consumes` |
| Append an amendment | `PLAN_TOOL amend <plan> --summary "…" --detail "…"` |
| Cross-role report-back (incl. change-request lifecycle: `request` / `request-closed`) | `PLAN_TOOL report <plan> --role <r> --status <s> --summary "…" [--commits sha,…]` |
| Bind plan state to a verified commit + annotated git tag (clean tree only) | `PLAN_TOOL checkpoint <plan> [--label "…"]` |
| Architect: record acceptance + create a checkpoint tag | `PLAN_TOOL accept <plan> [--notes "…"]` |
| Acknowledge the current state of a seam a consumer depends on | `PLAN_TOOL ack <consumer-plan> --seam <seam-plan>` |
| Compact plain-text extract of a plan (or `--all` for a one-liner index) | `PLAN_TOOL brief <plan>` · `PLAN_TOOL brief --all --specs specs` |
| Lint a plan | `PLAN_TOOL validate <plan>` |
| Assign data-* anchors to an un-anchored/legacy plan | `PLAN_TOOL init-ids <plan>` |
| Rebuild the specs catalog | `PLAN_TOOL index` |
| Build the role manifest + CODEOWNERS from `roles/*.md` | `PLAN_TOOL roles build` |
| Regenerate the architect status dashboard | `PLAN_TOOL rollup [--role <r>]` |

Every mutating command also appends a one-line JSON event to `specs/<plan>.log.ndjson` (the append-only, merge-friendly multi-writer surface) and updates the human-readable HTML. Each read-modify-write op takes an exclusive `<plan>.lock` so concurrent writers to the same plan never lose data. **Free-form regions** — Purpose, Problem, Solution, Notes, Questionables prose, and diagrams — are edited normally. `roles/_roles.json`, `.github/CODEOWNERS`, `roles/activity.log.ndjson`, `specs/_index.*`, and `specs/_status.*` are **generated / append-only** aggregates — never hand-edit them; rerun the command that builds them.

**Attribution.** When acting as a role, set `PLANF3_ROLE` and pass the same value as `--role`; if the two disagree, `PLAN_TOOL` refuses the write (pass `--force-role` to override). This keeps the event log honest about who did what.

**Kinds & seams.** A plan's `kind` is `plan` (default) or `contract` — a **seam** describing the interface where two components meet. A consumer `--type consumes` a seam; the provider `--type provides` it (one command wires both sides via the `provides`/`consumes` metadata lists). When a seam changes, each consumer runs `PLAN_TOOL ack` to acknowledge the new state; `rollup` flags any consumer whose ack predates the seam's latest change. Legacy `--dir back|forward` still works.

**Checkpoints.** `checkpoint`/`accept` bind a plan to a **verified** git commit (HEAD sha + tree, refusing a dirty tree) and create an annotated tag `planf3/<plan-id>/<n>` — a real, git-native revert point `rollup` surfaces. `build-meta` auto-captures and verifies HEAD instead of trusting a hand-typed `--commit`.

### Roles (project-scoped ownership — OPT-IN)

Role mode is **optional and off by default**. It activates only when the user explicitly runs the `Generate Roles` workflow (or a `roles/` directory already exists in the project) — never enable it on your own initiative. Without it, planf3 is a pure planning tool: plans default `owner` to the value the user gives or leave the convention to them, and the guard's role checks stay dormant (fail-open). Role mode earns its keep on team projects with source control — it ties roles to source-control ownership rules and to each role's planning, executing, and logging docs. Users running a custom agentic approach can simply never turn it on.

When role mode is on, each owner is a **role** with one hand-authored source-of-truth file at `roles/<role>.md` (see `templates/role.md`). `PLAN_TOOL roles build` derives the enforcement manifest `roles/_roles.json` + `.github/CODEOWNERS` from those files, requiring each role's `source_of_truth` + `code` globs to be disjoint across roles (`supporting` globs may overlap — they drive logging/attribution only). CODEOWNERS uses each role's `github:` identity (`@user` / `@org/team`); a role without one has its lines emitted **commented-out** rather than as an unusable `@<role-slug>`. A plan names its role in the `owner` metadata field. The `Generate Roles` workflow scopes a project into roles.

**Coherence, not compliance.** Only two kinds of write are ever *blocked*: (1) hand-edits to a plan's CLI-managed regions (the integrity layer, always on), and (2) in `protect` mode, a role writing **another role's `source_of_truth`**. Everything else — code paths, supporting docs, unowned files, roleless sessions, the architect — is **allowed and logged, never blocked**. The system makes incoherence visible (drift, unacknowledged seams, open requests surface in `rollup`); it does not force anyone to obey a plan.

**Mode** (project-wide, from the architect role's frontmatter, compiled into `_roles.json`):
- `off` — role layer dormant; only the managed-region integrity guard runs.
- `track` (default) — no denies at all; impactful writes are logged to `roles/activity.log.ndjson` (the `PostToolUse` hook appends `{ts, path, tool, role, session, owner}` per impactful write; plan_tool-routed writes are recorded in the plan sidecar instead, so there's no double count). `rollup` reads this for **ownership drift** — a role's owned path written by someone else.
- `protect` — as `track`, plus the guard denies a role writing another role's `source_of_truth`. The architect is never denied.

**Acceptance** (project-wide): `manual` (default) means a `built` plan awaits an architect `accept` — `rollup` lists **pending acceptance**; `auto` treats `built` as accepted and omits that section.

**`PLANF3_ROLE`** — set this env var to the role you are acting as (e.g. `export PLANF3_ROLE=engineer-api`). The `PreToolUse` guard reads it plus `roles/_roles.json` (fail-open when unset, no manifest, or mode `off`). Pass the same value as `--role` on `PLAN_TOOL` calls so events are attributed (a mismatch is refused — see Attribution above).

**Seam contracts.** For a boundary between two components, author a `kind=contract` plan (a **seam**) owned by one role or the architect; consumers wire to it with `ref --type consumes` and re-`ack` it when it changes. This gives coherence teeth — a changed seam that a consumer hasn't acknowledged is impossible to miss in `rollup` — with zero compliance rigidity.

**Role session bootstrap** — when you assume role `R`, read in this order: (1) this `SKILL.md`; (2) `roles/<R>.md` (your mission, DoD, owned globs, report protocol); (3) set `PLANF3_ROLE=<R>`; (4) `specs/_index.html` filtered to `owner=<R>` and `specs/_status.html --role <R>`, opening only the full plan you will work on; (5) `roles/<R>/memory.md` (your durable notes); (6) tail the relevant `specs/<plan>.log.ndjson` for recent reports/status.

## Workflow

Based on the `USER_PROMPT`, select the single best-matching workflow below and read its file for the step-by-step instructions before acting.

| Workflow | When to call it | File to read |
| --- | --- | --- |
| Create Plan | The prompt asks to plan, spec, or design new work and no existing plan is referenced | `workflows/create-plan.md` |
| Update Plan | The prompt asks to change, extend, or revise the content of an existing plan | `workflows/update-plan.md` |
| Update References | The prompt asks to refresh plan metadata or back/forward references (created, modified, commits, agent, session) | `workflows/update-references.md` |
| Build Plan | The prompt asks to implement, execute, or carry out the work described in an existing plan | `workflows/build-plan.md` |
| Generate Roles | The prompt asks to scope a whole project/team into roles, define ownership, or set up who-owns-what (not a single plan) | `workflows/generate-roles.md` |

### Subworkflow

Called by other workflows rather than selected directly from the `USER_PROMPT`.

| Subworkflow | When it's called | File to read |
| --- | --- | --- |
| Diagram Generation | Invoked by other workflows (e.g. Create Plan) to generate, fill, or regenerate the embedded Excalidraw diagrams in a plan | `workflows/diagram-generation.md` |

## Plan Template

The plan's structure lives in **one single source of truth**: [`templates/plan.html`](templates/plan.html). Never hand-write the scaffold — run `PLAN_TOOL new` and it stamps a fresh plan from that template with every `data-*` anchor, prefilled metadata (`status=draft`), and one example phase/task/testing block:

```
PLAN_TOOL new <kebab-name> --title "<Plan Title>" [--owner <role>] [--specs specs]
```

`new` refuses to overwrite an existing plan and appends a `created` event to its `.log.ndjson`. Your job after `new` is to author **content**, never structure.

### Conventions (defined in `templates/plan.html`)

- **`{{PLACEHOLDER}}` tokens** are free-form content slots — replace EVERY one with real content. `new` fills the structural slots for you (title, `id`, `created`/`modified`, metadata, and the phase/task/check numbers in the example block); you fill the rest: purpose, problem, solution, file paths, phase names, task names, actions, testing approach, notes, and figure/image subjects.
- **`<!-- repeat -->` blocks** are duplicated as many times as the plan needs — one per phase, task, checklist item, global check, relevant file, or questionable — then the comment markers are deleted.
- **`data-*` anchors** are the contract `PLAN_TOOL` (status/meta/amend/validate) targets, so they must be well-formed:
  - `data-region` / `data-managed="cli"` mark the CLI-managed regions (metadata, amendments).
  - `data-meta="<field>"` tags each metadata value.
  - `data-phase="<n>"` numbers a phase; `data-status-for="phase-<n>"` is its status marker.
  - `data-task="<phase>.<task>"` numbers a task; `data-status-for="<phase>.<task>"` is its marker. Global checks use `g.<n>`.
  - When you **duplicate** a phase/task, increment the ids: phase 2 → `data-phase="2"` / `data-status-for="phase-2"`; its tasks → `data-task="2.1"` / `data-status-for="2.1"`, `2.2`, …; extra global checks → `g.2`, `g.3`. `new` stamps the first example as phase 1 (`phase-1`, tasks `1.1`/`1.2`, check `g.1`).
- **Status markers** all start as `[]` and are flipped only via `PLAN_TOOL status` (`[]` idle · `[wip]` · `[x]` · `[f]` terminal, needs a reason).

### Placeholder validation

`PLAN_TOOL validate` treats leftover `{{}}` tokens as a **warning while `status=draft`** — so a fresh `new` scaffold validates clean (exit 0) with a single placeholder warning — and as a **failure once `status` is anything other than `draft`**. Fill every `{{...}}` slot before moving a plan off `draft`.