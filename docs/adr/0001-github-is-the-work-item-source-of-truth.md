---
id: ADR-0001
title: GitHub is the source of truth for work items; ADRs stay as files
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/agents/issue-tracker.md
---

# ADR-0001: GitHub is the source of truth for work items; ADRs stay as files

## Context

CozyPlan grew its own record layer — `docs/features/FEAT-NNN-*.md` and
`docs/issues/ISSUE-NNN-*.md` — with status frontmatter and append-only status histories.
Beside it, the installed engineering-skill suite already ships a pluggable issue-tracker
adapter (`docs/agents/issue-tracker.md`) that `to-tickets`, `triage`, `wayfinder`, and
`code-review` all read, with GitHub as its default backend.

That is two trackers for one job. Worse, cozyplan's records carried two status vocabularies
mapped to nothing (`open → in-progress → fixed / wontfix / duplicate` and
`proposed → planned → in-development → shipped / dropped`), and its `wontfix` collided by
name with a canonical triage role while meaning something narrower.

A file-based tracker also cannot do the thing a team actually needs from one: it has no
queue, no assignment, no notification, and no view a non-cloning stakeholder can open.

## Decision

We will treat **GitHub Issues as the source of truth for features and bugs**, reached
through the `gh` CLI via the conventions in `docs/agents/issue-tracker.md`. CozyPlan will
stop maintaining `docs/features/` and `docs/issues/`, and will cross-reference GitHub by
issue number instead.

We will keep **ADRs as versioned files in `docs/adr/`**. A decision's value is that it
survives — outliving the tracker, readable in a clone with no network, and diffable
alongside the code it explains. ADRs are the one record that must not live in a system we
could lose access to.

Every answer to "how does this work", "why this way", "what breaks", and "where did we
leave off" must remain answerable with **plain `git` alone**. GitHub carries the work
queue; git carries the durable record. `gh` is a convenience layer, never a dependency.

## Consequences

Easier: work items get a real queue, assignment, and a stakeholder-visible surface. One
tracker vocabulary instead of three. The triage label roles apply unchanged.

Harder: `gh` must be installed and authenticated to file or advance work items. Offline or
`gh`-less sessions queue intended issues to `.scratch/pending-issues/` plus a replayable
`.scratch/pending-gh.sh` rather than forking the source of truth.

Follow-up work created: delete `templates/feature.md` and `templates/issue.md`; reduce
Track Record to ADRs only; add an `issues` metadata field to `plan_tool` so a plan can
carry its GitHub issue numbers (the field set is closed, so `back-refs` is not a valid
home); adopt commit trailers so history joins to plans, phases, issues, and ADRs.

## Alternatives Considered

- Keep `docs/issues/` as the source of truth and mirror one-way to GitHub — rejected: the
  mirror drifts, and the repo copy has no queue, assignment, or notifications.
- Two-way sync between records and GitHub — rejected: most machinery, most drift risk, and
  it requires `gh` everywhere the team works.
- Keep both and let each surface own different work — rejected: three issue homes was the
  problem, not the solution.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
