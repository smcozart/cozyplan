---
name: cozyplan
description: HTML-first implementation plans in specs/, plus a project state layer derived from git. Use when the user wants to plan new work, build or update an existing plan, wire a repo for planning, record a decision, or sync and report the project's working state.
argument-hint: "[user-prompt]"
---

# CozyPlan

Plans are **HTML-first**: one self-contained `.html` page per plan in `specs/`, browsable by a human and read through the CLI by an agent. Beside them sits a **state layer** — what works right now, why it was built this way, and where the work left off — derived from git rather than remembered.

## Variables

```
USER_PROMPT           the request that triggered this skill: $ARGUMENTS when invoked as
                      /cozyplan <request>, otherwise the user's request in the conversation
PLAN_OUTPUT_DIRECTORY specs/
PLAN_FILE             specs/<descriptive-kebab-name>.html
IMAGES_OUTPUT_DIR     specs/<plan-name>/
DOCS_DIR              docs/            records and ledger
STATE_FILE            STATE.md         the generated current view
STATE_LOG             docs/state.ndjson  the append-only event log behind it
JOURNAL               docs/journal.md
```

`PLAN_TOOL` is the deterministic CLI that owns structured writes, cheap reads, validation, and the state layer. It ships inside this skill at `scripts/plan_tool.py` and is stdlib-only, so `uv run` and a plain `python3` both work. Resolve it once per session, in order: (1) `uv run "${CLAUDE_PLUGIN_ROOT}/skills/cozyplan/scripts/plan_tool.py"` when `CLAUDE_PLUGIN_ROOT` is set — quote it, plugin roots contain spaces; (2) the copy in this skill's own directory, for bare-skill installs; (3) `scripts/plan_tool.py` for the legacy project-local layout. Every `PLAN_TOOL …` below means that resolved command.

## Scope

cozyplan owns **plans and intent**. **Git owns enforcement**: branches and PRs gate merges, CODEOWNERS routes review, tags and commits are revert points, `git blame` answers who changed what, and CI is the definition of done. The state layer records what git cannot — *why*, and *what is verified* — and never claims a guarantee it cannot keep (ADR-0004).

## Reading a plan

**Indexed, not wholesale.** Orient with `PLAN_TOOL brief <plan>`, pull one phase at a time with `PLAN_TOOL phase <plan> --id phase-<n>`, and get the re-entry point from `PLAN_TOOL next <plan>`. Follow a back reference only when the decision in front of you depends on it. Reading a plan end to end costs several times what `brief` costs, and `next` is one line.

## Context and state

Four **context artifacts** are owned and defined by the sibling `discuss` skill — cozyplan reads them when planning and never manages them: `STACK.md` (technology defaults and lanes), `CONTEXT.md` (the glossary — use its terms), `SYSTEM.md` (components, owners, and the cross-boundary contracts between them — filter its edge table on `From = <component>` for blast radius), and `docs/adr/` (the why behind standing decisions — link the relevant ones inline in phase and task rationale).

The **state layer** is cozyplan's, and it is derived rather than authored:

- `STATE_FILE` is **generated** by `PLAN_TOOL state render` from `STATE_LOG`, ordered by commit position. Never hand-edit it — append an event and re-render. Each entry is a pointer trail (`plan:` `phase:` `adr:` `issue:` `session:` `path:`), not the detail itself. `render` refuses to overwrite a `STATE_FILE` it did not write; a hand-authored one is carried over with `PLAN_TOOL state migrate` first.
- `STATE_LOG` is append-only and union-merged, so concurrent sessions combine instead of clobbering. The projection is last-write-wins per key, ordered by the commit that introduced each line (ADR-0005).
- **Decisions** live in `docs/adr/`. **Work items live on the repo's issue tracker**, not in files — see `docs/agents/issue-tracker.md`; cozyplan cross-references them by number in commit trailers (ADR-0001).
- A claim enters `STATE_FILE` only with its proof: the command that demonstrated it, when, and the commit it was true at. Unverified claims are gaps, not claims.

**Commit trailers** carry the ids into history — `Plan:`, `Phase:`, `Refs:`, `ADR:`, `Verified:`, `Session:` — which is what makes `git log` answer "what governs this code" and "where did this leave off". The `commit-msg` hook adds the ones it can prove.

## Writes

Metadata, status markers, and amendments are **CLI-owned**: route them through `PLAN_TOOL` so they stay well-formed. Purpose, Problem, Solution, Notes, Open Questions prose, and diagrams are free-form — edit normally. `specs/_index.*` and `STATE_FILE` are **generated** — change them by rerunning the command that builds them.

Full CLI surface, the metadata contract, the gates, and the install paths: [`reference/plan-tool.md`](reference/plan-tool.md).

`PLAN_TOOL init` wires a repo in one idempotent command and prints the steps that need a human. `PLAN_TOOL doctor` shows what is actually wired in this clone rather than assuming it.

## Workflow

Select the single best-matching workflow and read its file before acting.

| Workflow | When to call it | File |
| --- | --- | --- |
| Create Plan | Plan, spec, or design new work, with no existing plan referenced | `workflows/create-plan.md` |
| Update Plan | Change, extend, or revise an existing plan — including refreshing its references | `workflows/update-plan.md` |
| Build Plan | Implement, execute, or carry out the work an existing plan describes | `workflows/build-plan.md` |
| Init State | Set up the state layer in a repo, or adopt an existing one | `workflows/init-state.md` |
| Track Record | Record a decision as an ADR, or file a work item on the tracker | `workflows/track-record.md` |
| Sync State | Sync, refresh, reconcile, or report the project's current state. Also the closing step of Create, Update, and Build | `workflows/sync-state.md` |
| Diagram Generation | Generate, fill, or regenerate a plan's embedded diagrams. Also called by Create | `workflows/diagram-generation.md` |

`QUESTIONABLE` defaults on: surface open questions, assumptions, and risks in the plan's **Open Questions** section rather than deciding them silently. A plan that decided something on a guess says so there.
