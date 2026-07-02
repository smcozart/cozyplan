---
name: planf3
description: Creates a concise engineering implementation plan based on user requirements and saves it to specs directory
argument-hint: "[user-prompt] [questionable]"
---

# Plan F3

## Purpose

Create a detailed, **HTML-first** implementation plan based on the `USER_PROMPT` variable. The plan is authored as a single self-contained `.html` page so it can be opened in a browser, embed focused Excalidraw diagrams with a synced visual identity, and be created/updated/consumed by the agent trifecta (engineer, team, AI agents). Analyze the request, think through the implementation approach, follow the `## Instructions`, and work through the `## Workflow` to produce the plan from the `## Plan Template`.

## Variables

USER_PROMPT: $1
QUESTIONABLE: $2 - default false
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
- The plan is **HTML-first**: produce a single self-contained `.html` document from the `## Plan Template` below
- The template uses `{{PLACEHOLDER}}` variables — replace EVERY `{{...}}` with real content. Do not leave any `{{}}` token in the final file
- Blocks marked with `<!-- repeat -->` are repeatable: duplicate them as many times as the plan needs (e.g. one block per phase, task, file, or Q&A entry) and delete the comment markers
- Keep the document self-contained: all CSS lives in the single `<style>` block; do not link external stylesheets or scripts
- Visuals are **Excalidraw diagrams**, not AI-generated raster art. Each diagram is a simple, straightforward box/arrow/flow drawing authored as an editable `.excalidraw` source file and rendered to a PNG (locally, no API key). Keep designs clean, minimal, and professional — easy to map out at a glance.
- Maintain a **synced visual identity** between the html styling and the diagrams. We want a professional, focused, minimal theme based on the original `USER_PROMPT` that created the plan. The CSS custom properties in `:root` define the palette/typography. Every diagram must use the same palette so the rendered PNGs sit naturally inside the page.
- For every diagram, focus on one or two primary ideas. Keep total words shown under ~10 — boxes, arrows, and short labels only. The goal is diagrams that aid the plan and convey the core information for the section they belong to.
- Build diagrams for professional software engineers to convey exactly what is going to be built. Be sure to center and space them properly.
- Embed diagrams via the `{{...IMAGE}}` slots. During Create, leave them as commented placeholders noting the intended subject; the Diagram Generation workflow fills them later
- Populate the metadata header (`schema`, `id`, `owner`, `status`, `created`, `modified`, `commits`, `agent`, `session`, back/forward references) — these are updatable across the plan's lifecycle. `schema`, `id`, and `created` are write-once; `status` is a single value; `modified`/`commits`/`agent`/`session`/back-refs/forward-refs are append-only comma-separated lists. `schema` is the artifact's structural-contract version (currently `1`) — leave it as the template sets it; `PLAN_TOOL` refuses to write a plan stamped newer than it understands. **Never hand-edit the metadata, status markers, or amendments — route every such write through `PLAN_TOOL` (see `## Managed Writes`).** These regions are marked `data-managed="cli"` in the template
- **Plan `status`** is a single value from a closed vocabulary: `draft` (authored, not started) → `active` (approved / being built) → `built` (implemented, tests pass); plus `superseded` (replaced — must carry a forward ref to its successor) and `archived` (kept for history). Set it with `PLAN_TOOL meta <plan> --field status --value <state>`. Create sets `draft` (or `active`); Build moves `active`→`built`
- **`id`** is a short immutable slug set once at Create (references and event logs point at it, so it survives renames). **`owner`** is the role that owns the plan (e.g. `architect`, `engineer-<component>`, `ux`); only the owner edits plan content
- If `QUESTIONABLE` is true, actively surface open questions/assumptions in the toggleable Q&A section rather than silently deciding
- Ensure the plan is detailed enough that another developer (or agent) could follow it to implement the solution
- Include code examples or pseudo-code where appropriate to clarify complex concepts
- Consider edge cases, error handling, and scalability concerns
- Save the complete plan to `PLAN_FILE` using a descriptive kebab-case filename

## Managed Writes

The plan HTML is a living artifact. Some regions are **CLI-managed** and must never be hand-edited — always go through `PLAN_TOOL` so writes stay deterministic and well-formed. A `PreToolUse` hook blocks raw edits to these regions and a `PostToolUse` hook lints the file after every write.

| Write | Command |
| --- | --- |
| Flip a task/phase status marker | `PLAN_TOOL status <plan> --id <id> --state idle\|wip\|x\|f [--reason "…"]` (`--reason` required for `f`) |
| Append metadata (modified/commits/agent/session) or set id/owner/status | `PLAN_TOOL meta <plan> --field <field> --value <v>` |
| Record build commit + agent + session at once | `PLAN_TOOL build-meta <plan> --commit <sha> --agent <name> --session <id>` |
| Add a bidirectional reference between two plans | `PLAN_TOOL ref --this <plan> --other <plan> --dir back\|forward` |
| Append an amendment | `PLAN_TOOL amend <plan> --summary "…" --detail "…"` |
| Cross-role report-back | `PLAN_TOOL report <plan> --role <r> --status <s> --summary "…" [--commits sha,…]` |
| Lint a plan | `PLAN_TOOL validate <plan>` |
| Assign data-* anchors to an un-anchored/legacy plan | `PLAN_TOOL init-ids <plan>` |
| Rebuild the specs catalog | `PLAN_TOOL index` |
| Build the role manifest + CODEOWNERS from `roles/*.md` | `PLAN_TOOL roles build` |
| Regenerate the architect status dashboard | `PLAN_TOOL rollup [--role <r>]` |

Every mutating command also appends a one-line JSON event to `specs/<plan>.log.ndjson` (the append-only, merge-friendly multi-writer surface) and updates the human-readable HTML. **Free-form regions** — Purpose, Problem, Solution, Notes, Questionables prose, and diagrams — are edited normally. `roles/_roles.json`, `.github/CODEOWNERS`, `specs/_index.*`, and `specs/_status.*` are **generated** aggregates — never hand-edit them; rerun the command that builds them.

### Roles (project-scoped ownership — OPT-IN)

Role mode is **optional and off by default**. It activates only when the user explicitly runs the `Generate Roles` workflow (or a `roles/` directory already exists in the project) — never enable it on your own initiative. Without it, planf3 is a pure planning tool: plans default `owner` to the value the user gives or leave the convention to them, and the guard's role checks stay dormant (fail-open). Role mode earns its keep on team projects with source control — it ties roles to source-control ownership rules and to each role's planning, executing, and logging docs. Users running a custom agentic approach can simply never turn it on.

When role mode is on, each owner is a **role** with one hand-authored source-of-truth file at `roles/<role>.md` (see `templates/role.md`). `PLAN_TOOL roles build` derives the enforcement manifest `roles/_roles.json` + `.github/CODEOWNERS` from those files, requiring role ownership globs to be disjoint. A plan names its role in the `owner` metadata field. The `Generate Roles` workflow scopes a project into roles.

**`PLANF3_ROLE`** — set this env var to the role you are acting as (e.g. `export PLANF3_ROLE=engineer-api`). The `PreToolUse` guard reads it plus `roles/_roles.json` and denies writes to another role's owned paths (fail-open when unset or no manifest). Pass the same value as `--role` on `PLAN_TOOL` calls so events are attributed.

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

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Plan: {{PLAN_TITLE}}</title>
</head>
<body>
<main>

  <!-- ===== HEADER + UPDATABLE METADATA ===== -->
  <header>
    <h1>Plan: {{PLAN_TITLE}}</h1>
    <details class="meta" data-region="metadata" data-managed="cli">
      <summary>Metadata</summary>
      <dl>
        <dt>schema</dt>       <dd data-meta="schema">1</dd>
        <dt>id</dt>           <dd data-meta="id">{{PLAN_ID}}</dd>
        <dt>owner</dt>        <dd data-meta="owner">{{OWNER_ROLE}}</dd>
        <dt>status</dt>       <dd data-meta="status">draft</dd>
        <dt>created</dt>      <dd data-meta="created">{{CREATED_ISO}}</dd>
        <dt>modified</dt>     <dd data-meta="modified">{{MODIFIED_ISO_LIST}}</dd>
        <dt>commits</dt>      <dd data-meta="commits">{{COMMIT_SHA_LIST}}</dd>
        <dt>agent name</dt>   <dd data-meta="agent">{{AGENT_NAME_LIST}}</dd>
        <dt>session id</dt>   <dd data-meta="session">{{SESSION_ID_LIST}}</dd>
        <dt>back refs</dt>    <dd data-meta="back-refs">{{BACK_REFERENCES}}</dd>
        <dt>forward refs</dt> <dd data-meta="forward-refs">{{FORWARD_REFERENCES}}</dd>
      </dl>
    </details>
    <!-- Metadata, status markers, and amendments are CLI-managed (data-managed="cli").
         Never hand-edit them — use PLAN_TOOL (see ## Managed Writes). -->
  </header>

  <!-- Hero image — synced to the :root visual identity. Replace with <img> once generated. -->
  <figure>
    <!-- {{HERO_IMAGE: subject describing the plan at a glance}} -->
    <figcaption>{{HERO_IMAGE_CAPTION}}</figcaption>
  </figure>

  <!-- ===== PURPOSE / PROBLEM / SOLUTION ===== -->
  <section id="purpose">
    <h2>Purpose</h2>
    <p>{{PURPOSE}}</p>
  </section>

  <section id="problem">
    <h2>Problem</h2>
    <p>{{PROBLEM}}</p>
    <figure>
      <!-- {{PROBLEM_IMAGE: subject visualizing the problem this plan addresses}} -->
      <figcaption>{{PROBLEM_IMAGE_CAPTION}}</figcaption>
    </figure>
  </section>

  <section id="solution">
    <h2>Solution</h2>
    <p>{{SOLUTION}}</p>
    <figure>
      <!-- {{SOLUTION_IMAGE: subject visualizing the proposed solution}} -->
      <figcaption>{{SOLUTION_IMAGE_CAPTION}}</figcaption>
    </figure>
  </section>

  <!-- ===== RELEVANT FILES ===== -->
  <section id="files" class="files">
    <h2>Relevant Files</h2>

    <h3>Existing Files</h3>
    <ul>
      <!-- repeat -->
      <li><span class="tag existing">existing</span> <code>{{EXISTING_FILE_PATH}}</code> — {{WHY_RELEVANT}}</li>
    </ul>

    <h3>New Files</h3>
    <ul>
      <!-- repeat -->
      <li><span class="tag new">new</span> <code>{{NEW_FILE_PATH}}</code> — {{WHY_NEEDED}}</li>
    </ul>
  </section>

  <!-- ===== IMPLEMENTATION PHASES ===== -->
  <section id="phases">
    <h2>Implementation Phases</h2>
    <p><strong>IMPORTANT:</strong> Execute every phase and task step by step, in order, top to bottom.</p>
    <p>Status markers: <code>[]</code> idle · <code>[wip]</code> in progress · <code>[x]</code> complete · <code>[f]</code> failed (terminal — requires a one-line reason). All start as <code>[]</code>; the Build Plan workflow flips them via <code>PLAN_TOOL status</code> as it works. The <code>data-status-for</code> / <code>data-phase</code> / <code>data-task</code> ids are the anchors the CLI targets — assign them at Create (or run <code>PLAN_TOOL init-ids</code>), numbering tasks <code>&lt;phase&gt;.&lt;task&gt;</code> and phases <code>phase-&lt;n&gt;</code>.</p>

    <!-- repeat: one .phase block per phase. data-phase is sequential (1, 2, …) -->
    <div class="phase" data-phase="{{PHASE_NUMBER}}">
      <h3><code class="status" data-status-for="phase-{{PHASE_NUMBER}}">[]</code> Phase {{PHASE_NUMBER}}: {{PHASE_NAME}}</h3>
      <p>{{PHASE_DESCRIPTION}}</p>

      <!-- Optional focused image for this phase, synced to :root identity -->
      <figure>
        <!-- {{PHASE_IMAGE: subject describing this phase's architecture/flow}} -->
        <figcaption>{{PHASE_IMAGE_CAPTION}}</figcaption>
      </figure>

      <!-- repeat: one <h4> + checklist per task -->
      <h4>{{TASK_NUMBER}}. {{TASK_NAME}}</h4>
      <ul class="checklist">
        <!-- repeat: data-task is <phase>.<task>, e.g. 1.1, 1.2 -->
        <li data-task="{{PHASE_NUMBER}}.{{TASK_NUMBER}}"><code class="status" data-status-for="{{PHASE_NUMBER}}.{{TASK_NUMBER}}">[]</code> {{SPECIFIC_ACTION}}</li>
      </ul>

      <!-- Final task of every phase: Testing Strategy + validation loop -->
      <h4>{{LAST_TASK_NUMBER}}. Testing Strategy</h4>
      <p>{{TESTING_APPROACH: technology used to test/validate, including edge cases}}</p>
      <ul class="checklist">
        <!-- repeat -->
        <li data-task="{{PHASE_NUMBER}}.{{LAST_TASK_NUMBER}}"><code class="status" data-status-for="{{PHASE_NUMBER}}.{{LAST_TASK_NUMBER}}">[]</code> <code>{{VALIDATION_COMMAND}}</code> — {{WHAT_IT_PROVES}}</li>
      </ul>
      <div class="loop">
        🔁 <strong>Do not exit this phase until every box above is <code>[x]</code> or <code>[f]</code>.</strong>
        If a command fails, fix the cause and re-run; loop until it passes. <code>[f]</code> is terminal — only when a box genuinely cannot be made to pass, mark it <code>[f]</code> (with a one-line reason via <code>PLAN_TOOL status … --state f --reason "…"</code>) and move on.
      </div>
    </div>
  </section>

  <!-- ===== GLOBAL VALIDATION ===== -->
  <section id="validation">
    <h2>Validation Commands</h2>
    <p>Execute these commands to validate the entire plan is complete:</p>
    <ul class="checklist">
      <!-- repeat: data-task ids for global checks are g.1, g.2, … -->
      <li data-task="g.{{CHECK_NUMBER}}"><code class="status" data-status-for="g.{{CHECK_NUMBER}}">[]</code> <code>{{VALIDATION_COMMAND}}</code> — {{WHAT_IT_PROVES}}</li>
    </ul>
    <div class="loop">
      🔁 <strong>The plan is not complete until every box is <code>[x]</code> or <code>[f]</code> and every command passes. If a step genuinely cannot be completed, mark it <code>[f]</code> (terminal, with a one-line reason) and move on.</strong>
    </div>
  </section>

  <!-- ===== QUESTIONABLES (only include this section if QUESTIONABLE is true) ===== -->
  <section id="questionables">
    <h2>Questionables</h2>
    <!-- Optional image for this section, synced to :root identity -->
    <figure>
      <!-- {{QUESTIONABLES_IMAGE: subject visualizing the key open question/risk}} -->
      <figcaption>{{QUESTIONABLES_IMAGE_CAPTION}}</figcaption>
    </figure>
    <!-- repeat: one <details> per questionable decision / assumption / risk -->
    <details>
      <summary>{{QUESTIONABLE}}</summary>
      <p class="qa-answer">{{ASSUMPTION_OR_RATIONALE}}</p>
    </details>
  </section>

  <!-- ===== NOTES ===== -->
  <!-- Open canvas — the planning agent runs free here. There is no fixed shape:
       use whatever HTML best serves the plan (prose, lists, tables, code blocks,
       diagrams, callouts, decision logs, alternatives considered, open threads,
       links, anything). Embed as many image slots as the plan benefits from. -->
  <section id="notes">
    <h2>Notes</h2>
    {{NOTES: free-form. Capture anything that helps the trifecta understand, build,
      or extend this plan — context, dependencies (new libraries via `uv add`),
      tradeoffs, rejected approaches, risks, future work, references. Author rich,
      bespoke HTML as needed.}}
    <!-- repeat: add as many of these image slots as the notes warrant including the image block below -->
    <figure>
      <!-- {{NOTES_IMAGE: subject for a note worth visualizing}} -->
      <figcaption>{{NOTES_IMAGE_CAPTION}}</figcaption>
    </figure>
  </section>

  <!-- ===== AMENDMENTS ===== -->
  <!-- Running history of changes made AFTER the plan was first executed. Append-only.
       Populated by the Update Plan and Update References workflows — never edited during Create. -->
  <section id="amendments" data-region="amendments" data-managed="cli">
    <h2>Amendments</h2>
    <!-- CLI-managed: PLAN_TOOL amend/ref/report append <details> entries into the
         container below, newest at the bottom. Do not hand-edit. -->
    <div data-amendments-list>
    </div>
  </section>

</main>
</body>
</html>
```