---
name: cozyplan
description: Creates and maintains concise HTML-first engineering implementation plans in the specs directory — scaffold new plans, update or build existing ones, refresh references, and generate role/CODEOWNERS ownership maps. Use when the user wants to plan, spec, or design new work, or to update, implement, or build an existing plan.
argument-hint: "[user-prompt]"
---

# CozyPlan

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
PLAN_TOOL: the deterministic CLI that owns all structured writes to a plan (status, metadata, references, amendments) plus `validate` and `index`. It ships **inside this skill** at `scripts/plan_tool.py`. Resolve it once at session start, in order: (1) if the `CLAUDE_PLUGIN_ROOT` environment variable is set (plugin install — the normal case), use `uv run "${CLAUDE_PLUGIN_ROOT}/skills/cozyplan/scripts/plan_tool.py"` with the path **quoted** (plugin roots can contain spaces); (2) otherwise use the copy in this skill's own directory — `uv run "<skill-dir>/scripts/plan_tool.py"` where `<skill-dir>` is the directory containing this SKILL.md (bare-skill installs, e.g. `npx skills add` → `.claude/skills/cozyplan/` or `~/.claude/skills/cozyplan/`); (3) as a last resort fall back to `uv run scripts/plan_tool.py` (legacy project-local `scripts/`). Every `PLAN_TOOL …` invocation below means that resolved command

## Instructions

- IMPORTANT: If no `USER_PROMPT` is provided, stop and ask the user to provide it
- Carefully analyze the user's requirements provided in the `USER_PROMPT` variable
- Think deeply (ultrathink) about the best approach to implement the requested functionality or solve the problem
- Explore the codebase to understand existing patterns, documentation, previous specs and architecture
- The plan is **HTML-first**: a single self-contained `.html` document, scaffolded by `PLAN_TOOL new` — the authoring contract (structure vs content, placeholders, repeats) lives in `## Plan Template`
- The scaffold uses `{{PLACEHOLDER}}` variables in free-form content positions — replace EVERY `{{...}}` with real content. Leftover `{{}}` tokens are a validation *warning* while `status=draft` but a *failure* once the plan leaves draft, so none may remain in a non-draft plan
- Blocks marked with `<!-- repeat -->` are repeatable: duplicate them as many times as the plan needs (e.g. one block per phase, task, file, or Q&A entry) and delete the comment markers
- Keep the document self-contained: all CSS lives in the single `<style>` block; do not link external stylesheets or scripts
- Visuals are **Excalidraw diagrams**, not AI-generated raster art. Each diagram is a simple, straightforward box/arrow/flow drawing authored as an editable `.excalidraw` source file and rendered to a PNG (locally, no API key). Keep designs clean, minimal, and professional — easy to map out at a glance.
- Maintain a **synced visual identity** between the html styling and the diagrams. We want a professional, focused, minimal theme based on the original `USER_PROMPT` that created the plan. The CSS custom properties in `:root` define the palette/typography. Every diagram must use the same palette so the rendered PNGs sit naturally inside the page.
- For every diagram, focus on one or two primary ideas. Keep total words shown under ~10 — boxes, arrows, and short labels only. The goal is diagrams that aid the plan and convey the core information for the section they belong to.
- Build diagrams for professional software engineers to convey exactly what is going to be built. Be sure to center and space them properly.
- Embed diagrams via the `{{...IMAGE}}` slots. During Create, leave them as commented placeholders noting the intended subject; the Diagram Generation workflow fills them later
- The metadata header (`schema`, `id`, `owner`, `status`, `created`, `modified`, `commits`, `agent`, `session`, back/forward references) is **stamped by `PLAN_TOOL new`** and updatable across the plan's lifecycle. `schema`, `id`, and `created` are write-once; `status` is a single value; `modified`/`commits`/`agent`/`session`/back-refs/forward-refs are append-only comma-separated lists. `schema` is the artifact's structural-contract version (currently `1`) — leave it as the template sets it; `PLAN_TOOL` refuses to write a plan stamped newer than it understands. Metadata, status markers, and amendments are CLI-managed regions — see `## Managed Writes` for the routing rule
- **Plan `status`** is a single value from a closed vocabulary: `draft` (authored, not started) → `active` (approved / being built) → `built` (implemented, tests pass); plus `superseded` (replaced — must carry a forward ref to its successor) and `archived` (kept for history). Set it with `PLAN_TOOL meta <plan> --field status --value <state>`. Create sets `draft` (or `active`); Build moves `active`→`built`
- **`id`** is a short immutable slug set once at Create (references and event logs point at it, so it survives renames). **`owner`** is the role that owns the plan (e.g. `architect`, `engineer-<component>`, `ux`); only the owner edits plan content
- If `QUESTIONABLE` is true, actively surface open questions/assumptions in the toggleable Q&A section rather than silently deciding
- Ensure the plan is detailed enough that another developer (or agent) could follow it to implement the solution
- Include code examples or pseudo-code where appropriate to clarify complex concepts
- Consider edge cases, error handling, and scalability concerns
- Save the complete plan to `PLAN_FILE` using a descriptive kebab-case filename

## Scope — cozyplan is the plan layer, not the enforcement layer

cozyplan owns **plans/intent**: it makes a plan deterministic, browsable, and internally coherent. It does **not** reimplement enforcement, revert points, or accountability — **git does that**: branches + PRs gate merges, CODEOWNERS routes review, `git tag`/commits are your revert points, `git blame` answers "who changed this," and CI is your definition of done. Use cozyplan for the plan; use git for everything around it. (An earlier version grew a coordination/enforcement layer — protect-mode role denial, verified checkpoints, acceptance queues, seams, drift dashboards — that presented as guarantees it couldn't keep under real multi-agent use. It was removed; git already does those jobs, and does them for real.)

## Context Layer

Beside the plans, a project may carry four living context artifacts, **owned and defined by the sibling `discuss` skill** (see its Context artifacts table) — cozyplan *reads* them when planning but never manages them, and `PLAN_TOOL` has no role in any of them:

| Artifact | Location | Read it for |
| --- | --- | --- |
| `STACK.md` | repo root | The technology defaults a plan should conform to — or deviate from with a recorded reason |
| `CONTEXT.md` | repo root | The project's canonical vocabulary — use its terms in the plan |
| `SYSTEM.md` | repo root | Which components exist and who owns them (nodes only; the discuss skill's Orient workflow derives current wiring from code) |
| `docs/adr/` | `docs/adr/NNNN-title.md` | The "why" behind standing decisions — link the relevant ones inline in phase/task rationale |

When these files are present, read them during Create/Update so plans challenge and reflect the recorded context rather than re-deriving it.

## Managed Writes

The plan HTML is a living artifact. Some regions are **CLI-managed** and should go through `PLAN_TOOL` so writes stay deterministic and well-formed. A `PreToolUse` **coherence guard** steers raw edits of these regions back to `PLAN_TOOL`, and a `PostToolUse` hook validates the file after every write. (The guard is a coherence aid for a cooperative agent — it is **not** tamper-proof: a Bash/`sed`/out-of-tool write bypasses it by design. Correctness comes from `validate`, which every op runs, not from the hook.)

**Bare-skill installs** (e.g. `npx skills add` — no plugin, so the hooks above are not auto-registered): correctness still holds, because every `PLAN_TOOL` op self-validates — route managed writes through `PLAN_TOOL` yourself with extra care. To restore edit-time steering, you may offer (with the user's explicit approval — never silently, since hooks execute commands) to merge the two hook entries into the project's `.claude/settings.json`, pointing `PreToolUse → "uv run \"<skill-dir>/scripts/hooks/guard_plan_edit.py\""` (matcher `Edit|MultiEdit|Write`) and `PostToolUse → "uv run \"<skill-dir>/scripts/hooks/lint_plan.py\""` (matcher `Edit|MultiEdit|Write|Bash`).

**Draft authoring window.** While a plan's `status` is `draft` (the state `new` stamps), the guard permits *structural* authoring via Edit — duplicating and renumbering phase/task blocks together with their `data-*` anchors and status markers — because the Create workflow requires it. Metadata (`data-meta=`) and the amendments region stay CLI-only in every status. Once the plan leaves `draft`, all managed tokens (anchors, markers, metadata, amendments) are CLI-only again.

| Write | Command |
| --- | --- |
| Scaffold a fresh plan (all `data-*` anchors + metadata stamped, `status=draft`) | `PLAN_TOOL new <kebab-name> --title "…" [--owner <role>] [--specs specs]` |
| Flip a task/phase status marker | `PLAN_TOOL status <plan> --id <id> --state idle\|wip\|x\|f [--reason "…"]` (`--reason` required for `f`) |
| Set or append a metadata field (status/owner/modified/commits/agent/session/refs) | `PLAN_TOOL meta <plan> --field <field> --value <v>` |
| Add a back/forward reference between two plans | `PLAN_TOOL ref --this <plan> --other <plan> --type back\|forward` |
| Append an amendment | `PLAN_TOOL amend <plan> --summary "…" --detail "…"` |
| Compact plain-text extract of a plan (or `--all` for a one-liner index) | `PLAN_TOOL brief <plan>` · `PLAN_TOOL brief --all --specs specs` |
| Lint a plan | `PLAN_TOOL validate <plan>` |
| Assign data-* anchors to an un-anchored/legacy plan | `PLAN_TOOL init-ids <plan>` |
| Rebuild the specs catalog | `PLAN_TOOL index` |
| Build the role ownership map + CODEOWNERS from `roles/*.md` | `PLAN_TOOL roles build` |

A plan may only leave `draft` (to `active`/`built`/…) once every `{{}}` placeholder slot is filled — `meta --field status` refuses the transition otherwise. Every mutating command also appends a one-line JSON event to `specs/<plan>.log.ndjson` (the append-only, merge-friendly multi-writer surface) and updates the human-readable HTML. Each read-modify-write op takes an exclusive `<plan>.lock` so concurrent writers to the same plan never lose data. **Free-form regions** — Purpose, Problem, Solution, Notes, Questionables prose, and diagrams — are edited normally. `roles/_roles.json`, `.github/CODEOWNERS`, and `specs/_index.*` are **generated** aggregates — never hand-edit them; rerun the command that builds them.

To record which commit implemented a plan, append it with `PLAN_TOOL meta <plan> --field commits --value <sha>`, and tag revert points with plain `git tag`. `--role`/`--agent`/`--session` on any command are optional free-text labels on the event log.

### Roles (ownership map → CODEOWNERS — OPT-IN)

Roles are **optional and off by default** — they activate only when the user runs the `Generate Roles` workflow (or a `roles/` directory already exists); never enable them on your own initiative. Without them, cozyplan is a pure planning tool and `owner` is just a free label. They are a **pure ownership-map generator, not an enforcement engine**: `PLAN_TOOL roles build` compiles hand-authored `roles/*.md` into `roles/_roles.json` + `.github/CODEOWNERS`, and enforcement is git's job (PR review routing + branch protection + `git blame`). Full mechanics live in `workflows/generate-roles.md`; the assume-a-role read order lives in each role file's **Session bootstrap** section (from `templates/role.md`) — pass `--role <R>` on `PLAN_TOOL` calls to label your events.

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