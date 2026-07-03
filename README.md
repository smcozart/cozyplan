# Planf3 — Plans For Fable Five

> **A [Mythos-class](https://www.anthropic.com/news/claude-fable-5-mythos-5) planning meta-skill: one skill that writes, builds, and maintains every plan your agents run.**
> Built for the agent trifecta: you, your team, and your AI agents.

📺 Watch this video to get the full breakdown of this codebase: **[Planf3 on YouTube](https://youtu.be/DzbqeO_diOQ)**

<p align="center">
  <img src="images/meta-skill-v5-multiplier-grid.png" alt="One meta-skill multiplies into countless plans" width="850">
</p>

Most engineers hand planning to the model and hope. `/plan` goes into a black box, something comes out, and you review whatever you get. Planf3 inverts that: you template your engineering once (the exact sections, the exact loops, the exact visual identity), and every plan the agent writes mirrors it, forever.

The big unlock is the new Mythos-class models (Fable 5 and what follows). They raise the intelligence ceiling far enough to absorb a token-rich, HTML-first plan and hit the *exact* outcomes you specify, which is the next level of planning ability we've been waiting for. Planf3 was built to pull that capability out of them: it deliberately spends tokens, images, and structure to extract the best plan these models can produce. Every property in the skill exists to capture that ceiling, and the payoff compounds with each more-capable model. **Great planning is great engineering, and this is the skill that encodes yours.**

---

## Install

Planf3 is a Claude Code Agent Skill (it runs in Pi, Codex, opencode, or any harness that reads `.claude/skills/`). There's nothing to compile and no API key to wire; "installing" is putting the skill where your agent can find it, dropping in the deterministic `plan_tool.py` CLI, and (optionally) activating the two hooks that keep plans consistent.

### Agentic Install

Open this repo in your agentic coding tool and prompt:

```
Read .claude/skills/planf3/SKILL.md and install this skill for me:
copy it to ~/.claude/skills/planf3 so /planf3 works in every project,
and tell me how to wire scripts/plan_tool.py plus the two hooks in
.claude/settings.json.sample.
```

The skill moves as a unit — `SKILL.md`, the four `workflows/` + one subworkflow, and the `scripts/` CLI. Its one external dependency is the [`excalidraw-diagram`](#the-workflows) skill used to render diagrams (see below); without it the plan still writes and the `{{...IMAGE}}` slots stay as placeholders.

### Manual Install

**Prereqs:** [`claude`](https://docs.claude.com/en/docs/claude-code) (or [`pi`](https://pi.dev/) / Codex / opencode), [`uv`](https://docs.astral.sh/uv/) (runs `plan_tool.py` and the diagram renderer), and the globally-installed `excalidraw-diagram` skill (invoked by the [Diagram Generation subworkflow](.claude/skills/planf3/workflows/diagram-generation.md)) for local, key-free diagram rendering. No API keys — diagrams are rendered locally.

planf3 has **two parts that must both be present** in the project you plan in:
the **skill** (the workflow prose, model-invoked) and the **`scripts/` CLI +
hooks** (`plan_tool.py` and `scripts/hooks/`, invoked as `uv run
scripts/plan_tool.py` and resolved by the hooks from the project root). Copying
only the skill is the most common install mistake — the skill will trigger but
every `plan_tool` call and both hooks fail with file-not-found.

```bash
# 1. Put the SKILL where your agent finds it — project-local (already here under
#    .claude/skills/planf3) or global for every project:
cp -r .claude/skills/planf3 ~/.claude/skills/planf3        # /planf3 everywhere

# 2. Put the CLI + hooks at your PROJECT ROOT (required — the skill and hooks
#    both invoke uv run scripts/plan_tool.py relative to the project):
cp -r scripts /path/to/your-project/scripts
cp .gitattributes /path/to/your-project/.gitattributes     # merge=union for *.log.ndjson

# 3. (Optional) Activate the consistency hooks — merge the sample into live settings:
#    copy .claude/settings.json.sample into .claude/settings.json (or merge the
#    "hooks" block). They run commands, so they're intentionally NOT auto-enabled.

# 4. Run it
#    /planf3 "<what you want planned>"
```

> The scripts are **path-agnostic** — every command takes explicit paths — so one
> copy of `scripts/` at the project root serves every plan in that project's
> `specs/`. (This copy-in-two-places friction is exactly what the planned
> skill→plugin migration removes: `/plugin install` ships the skill, CLI, and
> hooks together.)

To surface open decisions in a toggleable Q&A section instead of silently
deciding, ask for it in the prompt (e.g. "…and flag the open questions").

---

## Why this exists

<p align="center">
  <img src="images/02_outsourced_planning.png" alt="Handing the plan to a black box means handing off the result" width="750">
</p>

There are two hard constraints in agentic engineering: **planning** and **reviewing**. Most engineers spend their effort on the second one: babysitting output, catching drift, re-prompting. That's backwards. A vague `/plan` forces the model to guess what you want; you pay for the guess on every review pass that follows. The upfront plan is the cheapest place to buy correctness.

<p align="center">
  <img src="images/03_templated_engineering.png" alt="One template stamps the same structured shape every time" width="750">
</p>

Planf3 is a **meta-skill**, a skill that produces other artifacts. You write the plan *format* once, and the agent reproduces it across hundreds of executions: same sections, same checklists, same validation loops, same look. That consistency is you teaching the agent *how you engineer*. **More upfront investment in the plan means less reviewing later, and the gap widens with every more-capable model.**

---

## How it works

Planf3 takes a prompt and emits a single self-contained `.html` plan into `specs/`. HTML-first is a deliberate trade: it costs more tokens than markdown, and it buys a plan that opens in a browser, embeds synced diagrams, and reads cleanly for all three audiences. Of the trade-off trifecta (performance, speed, cost) this skill spends speed and cost to maximize performance.

The skill's API is one line:

```
/planf3 "<user prompt>" [questionable]
```

| Input | Meaning |
|---|---|
| `USER_PROMPT` | What to plan, build, update, or illustrate — this also selects the workflow |
| `QUESTIONABLE` | `true` surfaces assumptions in a toggleable Q&A section; defaults to `false` |

On a create run the agent reads the prompt, explores the codebase (plus `AI_DOCS/` and `APP_DOCS/` if present), authors the HTML plan from the template, generates one Excalidraw diagram per section (authored one at a time, rendered locally), validates and indexes the plan via `plan_tool.py`, and opens the result in your default browser.

---

## The plan template

<p align="center">
  <img src="images/04_plan_anatomy.png" alt="The plan template — metadata, purpose, phases with checklists, validation loop, notes" width="780">
</p>

The heart of the skill is the **Plan Template** in [`SKILL.md`](.claude/skills/planf3/SKILL.md): the structure the agent mirrors every time. `{{PLACEHOLDER}}` tokens get replaced with real content; `<!-- repeat -->` blocks duplicate per phase, task, or file. Every plan carries:

| Section | What it gives the trifecta |
|---|---|
| **Updatable metadata** | write-once `id` and `created`; single-value `owner` (role) and `status`; append-only lists of `modified`, `commits`, `agent`, `session`, and back/forward references — the plan is a living artifact |
| **Purpose / Problem / Solution** | The why, the pain, the approach — each with a focused diagram |
| **Relevant Files** | Existing files (tagged) vs new files, so the builder knows the blast radius |
| **Implementation Phases** | Phased work, each phase carrying per-task checklists and a Testing Strategy |
| **Validation loop** | A closed loop — *do not exit until every box is `[x]` or `[f]` and every command passes* |
| **Notes** | Open canvas where the planning agent runs free — matrices, tradeoffs, rejected approaches |
| **Amendments** | Append-only history of changes made *after* the plan was first built |

Status markers (`[]` idle · `[wip]` in progress · `[x]` complete · `[f]` failed) live right in the checklist, so the build agent tracks its own progress inside the plan itself. `[f]` is terminal — it means a box genuinely can't be made to pass, and it carries a one-line reason. The metadata, status markers, and amendments are **CLI-managed regions** (marked `data-managed="cli"`): they are written through `plan_tool.py`, never hand-edited. See [Keeping plans consistent](#keeping-plans-consistent).

---

## The workflows

<p align="center">
  <img src="images/05_five_workflows.png" alt="Planf3 routes one prompt to one of five dedicated workflows plus a diagram subworkflow" width="780">
</p>

Planf3 is one skill, but the prompt routes to one of **five dedicated workflows**, backed by **one subworkflow** for diagrams. This keeps the plan a living artifact across the whole lifecycle of the codebase, not a write-once document.

| Workflow | Trigger | File |
|---|---|---|
| **Create Plan** | Plan/spec/design new work, no existing plan referenced | [`create-plan.md`](.claude/skills/planf3/workflows/create-plan.md) |
| **Update Plan** | Change, extend, or revise an existing plan (surgical edit + amendment) | [`update-plan.md`](.claude/skills/planf3/workflows/update-plan.md) |
| **Update References** | Refresh metadata or wire bidirectional back/forward references | [`update-references.md`](.claude/skills/planf3/workflows/update-references.md) |
| **Build Plan** | Implement the work in an existing plan, updating status markers as it goes | [`build-plan.md`](.claude/skills/planf3/workflows/build-plan.md) |
| **Generate Roles** | Scope a whole project/team into roles and set up who-owns-what (not a single plan) | [`generate-roles.md`](.claude/skills/planf3/workflows/generate-roles.md) |

| Subworkflow | Called by | File |
|---|---|---|
| **Diagram Generation** | Other workflows (e.g. Create Plan) — authors and renders the embedded Excalidraw diagrams locally via the `excalidraw-diagram` skill (no API key) | [`diagram-generation.md`](.claude/skills/planf3/workflows/diagram-generation.md) |

The **Build Plan** workflow is the payoff: a fresh agent reads the full plan (every image, every back reference at depth 1), then executes phases top to bottom, looping on each phase's tests until they pass, marking `[x]` or `[f]` (via `plan_tool.py`) as it goes.

---

## Keeping plans consistent

A plan is a living artifact many agents (and, soon, many roles) touch over time. To keep those touches deterministic and merge-friendly, every *structured* write goes through one CLI instead of free-form edits.

**`scripts/plan_tool.py`** — a stdlib-only CLI (run with `uv run`) that owns all managed writes. It targets machine-readable `data-*` anchors baked into the template, so it always writes well-formed HTML:

| Command | What it does |
|---|---|
| `new` | Scaffold a fresh plan from `templates/plan.html` — stamps every `data-*` anchor + metadata (`status=draft`); `--kind plan\|contract`; refuses to overwrite |
| `status` | Flip a task/phase marker (`idle`/`wip`/`x`/`f`; `f` requires `--reason`) |
| `meta` | Set or append a metadata field (`id`/`owner`/`status`/`kind`, or the append-only lists) |
| `build-meta` | Append agent + session, auto-capture + verify HEAD, and stamp `modified` in one call |
| `ref` | Add a typed reference between two plans — `--type back\|forward\|provides\|consumes` (dedupes, updates both sides) |
| `amend` | Append an amendment entry |
| `report` | Append a cross-role report-back event (incl. `request` / `request-closed` change-request lifecycle) |
| `checkpoint` | Bind plan state to a verified commit + annotated git tag (`planf3/<id>/<n>`); refuses a dirty tree |
| `accept` | Architect: record acceptance + create a checkpoint tag |
| `ack` | Acknowledge the current state of a seam a consumer plan depends on |
| `brief` | Compact plain-text extract of a plan (or `--all` for a one-liner index) |
| `validate` | Lint a plan (leftover `{{}}` tokens, markers, metadata, images, refs) |
| `index` | Scan `specs/` → `_index.json` + `_index.html`, flag dangling refs and doc drift |
| `init-ids` | Backfill `data-*` anchors on a legacy/un-anchored plan (also stamps the schema) |
| `roles build` | Generate `roles/_roles.json` + `.github/CODEOWNERS` from `roles/*.md` |
| `rollup` | Scan event logs + `_index.json` → `specs/_status.html` (the architect view) |

Every mutating command also appends a one-line JSON event to **`specs/<plan>.log.ndjson`** — an append-only, `merge=union` sidecar (see `.gitattributes`) so concurrent writes from different agents/roles combine cleanly instead of colliding — and holds an exclusive `<plan>.lock` for its read-modify-write so two agents touching the same plan never lose an update.

**Lifecycle.** Each plan carries a single-value `status`: `draft` → `active` → `built`, plus `superseded` (replaced — carries a forward ref to its successor) and `archived` (kept for history). The generated `specs/_index.html` catalog lets `specs/` stay navigable as plans accumulate.

**Schema stamp.** Every plan carries a write-once `schema` version (currently `1`) recording its structural contract. `plan_tool.py` refuses to write a plan stamped newer than it understands (so an older tool never corrupts a newer artifact) and `init-ids` stamps the schema on older/legacy plans to migrate them forward.

**Hooks (opt-in).** `.claude/settings.json.sample` carries two hooks — merge it into `.claude/settings.json` to activate:

- a **PreToolUse** guard that steers raw `Edit`/`Write` of CLI-managed regions to `plan_tool.py` (and blocks overwriting an existing plan),
- a **PostToolUse** lint that runs `plan_tool validate` after any write to `specs/*.html` and feeds failures back to the agent.

Both **fail open** — an unexpected error never hard-blocks the agent. They execute commands, which is why they're shipped as a sample rather than enabled automatically.

---

## Roles (opt-in)

Role mode is **optional and off by default** — planf3 is a complete planning tool without it, and users running their own custom agentic approach can simply never turn it on. It shines on team projects with source control, where roles tie directly to source-control ownership rules and to each role's planning, executing, and logging docs.

Roles are **new** and project-scoped: on a multi-owner project you opt in by running the **Generate Roles** workflow once at kickoff to scope the project into roles — the owners of its plans, code, and docs — and revise them as the architecture evolves. It's the answer to the merge pain of several people (and agents) pushing to their own scattered `CLAUDE.md`/markdown files with no shared process. Nothing role-related activates until that workflow creates `roles/` (enforcement is fail-open without it).

Each role is **one hand-authored file** at `roles/<role>.md` (from [`templates/role.md`](.claude/skills/planf3/templates/role.md)) that serves three readers at once: a human onboarding doc, an agent operating brief, and the parsed source the enforcement machinery reads. A role file carries explicit **responsibilities**, a concrete **Definition of Done** (with runnable checks a human and an agent run the same way), and **disjoint ownership globs** — `source_of_truth` and `code` globs may not overlap across roles (`plan_tool roles build` rejects overlap, since overlap is what causes the merge pain in the first place).

Ownership is enforced **twice from that one source**:

- **Agents** — the PreToolUse guard reads the generated `roles/_roles.json` plus your `PLANF3_ROLE` env var. Its behaviour is set by a project-wide **mode** (on the architect role): `off` (dormant), `track` (log impact, no denies — the default), or `protect` (also deny a role writing another role's *source of truth*). Fail-open when unset.
- **Humans** — `plan_tool roles build` also generates `.github/CODEOWNERS` from each role's `github:` identity for review-time ownership (a role without one is emitted commented-out rather than as an unusable `@role` slug).

The guiding line is **coherence, not compliance**: only two writes are ever *blocked* — hand-edits to CLI-managed regions, and (in `protect`) cross-role source-of-truth writes. Everything else is **allowed and logged**. The system's job is to make incoherence *visible*, not to force plan-obedience. So `plan_tool rollup` surfaces **ownership drift** (a role's path written by someone else, from an append-only `roles/activity.log.ndjson`), **pending acceptance** (built plans awaiting an architect `accept`, under `acceptance=manual`), **open change requests**, and **unacknowledged seam changes**.

**Seams & checkpoints.** A `kind=contract` plan is a **seam** — the interface where two components meet. Consumers wire to it with `ref --type consumes` and re-`ack` it when it changes; a consumer that hasn't acknowledged the latest change lights up in the rollup. And `checkpoint`/`accept` bind a plan to a **verified** git commit (HEAD + tree, refusing a dirty tree) and tag it `planf3/<id>/<n>` — a real, git-native revert point, not a self-reported SHA.

A plan names its role in the `owner` metadata field. Roles **report back** to the role they report to (usually the architect) via `plan_tool report`, which appends an event to the plan's `.log.ndjson`; the architect regenerates a status dashboard with `plan_tool rollup` → `specs/_status.html`. As with `_index.*` and `CODEOWNERS`, these aggregates are **generated, never hand-edited**.

When an agent or human assumes role `R`, the role file's **Session bootstrap** sets the read order: `SKILL.md` → `roles/<R>.md` → export `PLANF3_ROLE=R` → the `owner=R`-filtered `specs/_index.html` and `specs/_status.html` → `roles/<R>/memory.md` → the relevant plan's `.log.ndjson`. Adding or splitting a role is a file plus a `roles build` — ownership is a field and a glob, not a directory move, so it never breaks existing plan references.

---

## Priorities

<p align="center">
  <img src="images/06_priorities.png" alt="Performance over speed over cost — spend tokens to win" width="750">
</p>

> *`Performance > Speed >= Cost`*

This is the design axis of the whole skill, and it's why planf3 looks "expensive." HTML over markdown, embedded images, rich updatable metadata, generated diagrams: none of that is the cheap choice. It's the choice that gives the best plan. When you run state-of-the-art models, **make the sacrifices you need to get state-of-the-art results.** Cost, here, is just tokens.

---

## Who it's for

<p align="center">
  <img src="images/07_trifecta.png" alt="One plan, three readers — you, your team, and your AI agents" width="750">
</p>

Every choice in planf3 serves the **agent trifecta**: the engineer (you), the engineering team, and the AI agents. Most planning systems over-index on one: pure agent JSON nobody can read, or a human doc no agent can act on. The HTML-first format, the embedded diagrams, the checklists, and the metadata header exist so a single plan satisfies all three at once.

---

## Folder structure

```
planf3/
├── README.md                       # this file
├── RAW.md                          # the raw think-out-loud spec that started the build
├── legacy_v1_meta_plan.md          # the V1 markdown spec planf3 evolved from
├── .env.sample                     # no keys required — placeholder for your own vars
├── .gitattributes                  # merge=union on specs/*.log.ndjson (clean concurrent appends)
│
├── .claude/
│   ├── settings.json.sample        # opt-in PreToolUse guard + PostToolUse lint hooks
│   └── skills/planf3/              # the meta-skill itself
│       ├── SKILL.md                # API, instructions, and plan-template conventions
│       ├── templates/
│       │   ├── plan.html           # the HTML plan template — single source of truth (stamped by plan_tool new)
│       │   └── role.md             # source template for a project's role files
│       └── workflows/              # five workflows + one subworkflow
│           ├── create-plan.md
│           ├── update-plan.md
│           ├── update-references.md
│           ├── build-plan.md
│           ├── generate-roles.md   # scope a project into roles / who-owns-what
│           └── diagram-generation.md   # subworkflow — local Excalidraw diagrams
│
├── scripts/
│   ├── plan_tool.py                # deterministic CLI for all managed plan writes + validate/index/roles/rollup
│   └── hooks/
│       ├── guard_plan_edit.py      # PreToolUse — steers raw edits of managed regions to plan_tool
│       └── lint_plan.py            # PostToolUse — validates specs/*.html after any write
│
├── prompts/
│   └── pi-iroh-coms.md             # the demo prompt
│
├── specs/                          # where plans land
│   ├── _index.json                 # generated catalog (machine-readable)
│   ├── _index.html                 # generated catalog (browsable)
│   ├── _status.html                # generated architect rollup (plan_tool rollup)
│   ├── pi-iroh-coms-net.html       # a REAL planf3 plan — open it in a browser
│   ├── pi-iroh-coms-net/           # its synced, generated section diagrams
│   └── <plan>.log.ndjson           # per-plan append-only event log (created on first managed write)
│
└── images/                         # README diagrams

# In a project that uses roles, planf3 also maintains:
#   roles/
#   ├── <role>.md                   # hand-authored role source of truth (from templates/role.md)
#   ├── <role>/memory.md            # that role's single-writer durable notes
#   └── _roles.json                 # GENERATED enforcement manifest (plan_tool roles build)
#   .github/CODEOWNERS              # GENERATED from roles/*.md for review-time ownership
```

---

## See it in action

<p align="center">
  <img src="specs/pi-iroh-coms-net/solution.png" alt="A real planf3-generated plan: serverless P2P agent mesh on iroh" width="780">
</p>

[`specs/pi-iroh-coms-net.html`](specs/pi-iroh-coms-net.html) is a real, unedited planf3 output. The prompt in [`prompts/pi-iroh-coms.md`](prompts/pi-iroh-coms.md) asked the agent to re-implement an HTTP agent-communication extension as a serverless peer-to-peer mesh on [iroh](https://iroh.computer). One `/planf3` run produced:

- a full HTML plan with metadata, four phases, per-phase checklists, and validation loops
- eight synced diagrams (hero, problem, solution, one per phase, notes)
- a freeform Notes section where the agent authored its own feature-parity matrix

Open the `.html` in a browser to see exactly what the skill delivers.

```bash
start "" specs\pi-iroh-coms-net.html    # Windows
open specs/pi-iroh-coms-net.html        # macOS
xdg-open specs/pi-iroh-coms-net.html    # Linux
```

---

## Where it can still fail

Honest edges to know before you ship plans with this:

- **It's tuned for top-tier models.** Planf3 deliberately spends tokens and time. On smaller models the HTML, metadata, and image steps can overwhelm the budget; it runs, but the payoff curve is steepest on Mythos-class models.
- **Diagrams need the `excalidraw-diagram` skill.** It's planf3's one external dependency (rendered locally, no API key). Without it the plan still writes; the `{{...IMAGE}}` slots just stay as placeholders until you run the Diagram Generation subworkflow with the skill installed.
- **The agent will sometimes over-reach.** These models take one instruction and run with the whole context, so expect occasional extra edits beyond what you asked. Be surgical in your prompts; review the diff.
- **Stray context bleeds in.** If other specs sit in `specs/`, a create run may reference them. Keep the output directory clean, or point back references deliberately.
- **`AI_DOCS/` and `APP_DOCS/` are optional.** The skill reads them if they exist; it won't create them. Add them when you want the plan grounded in your own documentation.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Master Agentic Coding

Prepare for the future of software engineering.

Learn tactical agentic coding patterns with [Tactical Agentic Coding](https://agenticengineer.com/tactical-agentic-coding?y=planf3).

Follow the [IndyDevDan YouTube channel](https://www.youtube.com/@indydevdan) to improve your agentic coding advantage.

---

Stay Focused and Keep Building

- IndyDevDan
