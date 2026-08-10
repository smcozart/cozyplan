---
name: cozyplan
description: Plans and tracks engineering work as living artifacts. Use when the user wants to plan/spec/design an implementation, build or execute an existing plan, revise a plan or its metadata/references, record a decision (ADR), feature, or issue, initialize state tracking in a repo, or sync/report the project's current working state.
argument-hint: "[user-prompt] [questionable]"
---

# CozyPlan

## Purpose

CozyPlan maintains a project's **living artifacts** across two layers, created, updated, and consumed by the trifecta (engineer, team, AI agents):

1. **Plans** — self-contained **HTML-first** implementation plans in `specs/`, openable in a browser, with embedded Excalidraw diagrams sharing a synced visual identity.
2. **State layer** — a markdown **snapshot + ledger**: a root `STATE.md` (the SOT snapshot of the system's verified working state, breaking down into ADR / feature / issue records) and an append-only `docs/journal.md` ledger of who changed what, why, and the resulting state.

The bar: anyone who clones the repo reads `STATE.md` and knows the exact working state, what is in development, who touched what and why, and how to verify every claim themselves.

## Variables

USER_PROMPT: $1
QUESTIONABLE: $2 - default false
PLAN_OUTPUT_DIRECTORY: `specs/`
PLAN_FILE: `PLAN_OUTPUT_DIRECTORY/<descriptive-kebab-name>.html`
IMAGES_OUTPUT_DIR: `PLAN_OUTPUT_DIRECTORY/<plan-name>/`
STATE_FILE: `STATE.md` (repo root)
DOCS_DIR: `docs/` — records in `docs/adr/`, `docs/features/`, `docs/issues/`; ledger at `docs/journal.md`
AI_DOCS: `AI_DOCS/`
APP_DOCS: `APP_DOCS/`
BROWSER: `chrome`

## Instructions

- IMPORTANT: If no `USER_PROMPT` is provided, stop and ask the user to provide it
- Think deeply (ultrathink) about the best approach; ground every workflow in the codebase, prior specs, and docs rather than assumption
- **Ledger discipline** — plan metadata lists, journal entries, Amendments sections, and record Status Histories are append-only: never overwrite or remove an existing entry. Only `STATE_FILE` snapshot sections are overwritten (by Sync State).
- **Verified-state discipline** — a claim enters `STATE_FILE`'s Current Working State only with its proof: the command or test that verified it, and when. Unverified claims go to Known Gaps / Risks or an issue record.
- State-layer workflows require `STATE_FILE`; when it is missing, run Init State first (or skip state steps when the user only wants a plan).

## Templates

All templates live in `templates/`. Copy the template, then replace every `{{PLACEHOLDER}}` with real content — no `{{}}` token may remain in a finished artifact. Blocks marked `<!-- repeat -->` are repeatable: duplicate them as many times as needed and delete the comment markers.

| Template | Produces |
| --- | --- |
| `templates/plan-template.html` | HTML implementation plan (`PLAN_FILE`) |
| `templates/STATE.md` | Root SOT snapshot (`STATE_FILE`) |
| `templates/journal.md` | Append-only ledger seed (`docs/journal.md`) — its header defines the entry format |
| `templates/adr.md` | Decision record (`docs/adr/ADR-NNNN-*.md`) |
| `templates/feature.md` | Feature record (`docs/features/FEAT-NNN-*.md`) |
| `templates/issue.md` | Issue record (`docs/issues/ISSUE-NNN-*.md`) |

## Workflow

Based on the `USER_PROMPT`, select the single best-matching workflow below and read its file for the step-by-step instructions before acting.

| Workflow | When to call it | File to read |
| --- | --- | --- |
| Create Plan | The prompt asks to plan, spec, or design new work and no existing plan is referenced | `workflows/create-plan.md` |
| Update Plan | The prompt asks to change, extend, or revise the content of an existing plan | `workflows/update-plan.md` |
| Update References | The prompt asks to refresh plan metadata or back/forward references (created, modified, commits, agent, session) | `workflows/update-references.md` |
| Build Plan | The prompt asks to implement, execute, or carry out the work described in an existing plan | `workflows/build-plan.md` |
| Init State | The prompt asks to set up state tracking / living artifacts in a repo | `workflows/init-state.md` |
| Track Record | The prompt asks to record a decision (ADR), register a feature, or open/update/close an issue | `workflows/track-record.md` |
| Sync State | The prompt asks to sync, refresh, reconcile, or report the project's current state | `workflows/sync-state.md` |

### Subworkflows

Called by other workflows rather than selected directly from the `USER_PROMPT`.

| Subworkflow | When it's called | File to read |
| --- | --- | --- |
| Diagram Generation | Invoked by Create/Update Plan to generate, fill, or regenerate the embedded Excalidraw diagrams in a plan | `workflows/diagram-generation.md` |
| Sync State | Also invoked as the closing step of Create, Update, and Build Plan | `workflows/sync-state.md` |
| Track Record | Also invoked by Build/Sync when decisions or failures surface without a record | `workflows/track-record.md` |
