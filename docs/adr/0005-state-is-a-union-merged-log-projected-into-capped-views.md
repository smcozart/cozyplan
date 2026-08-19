---
id: ADR-0005
title: State is a union-merged log projected into capped views
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0004-hooks-advise-ci-enforces-derivation-tolerates-gaps.md, .gitattributes
---

# ADR-0005: State is a union-merged log projected into capped views

## Context

`STATE.md` was declared the single source of truth for working state: one prose file,
overwritten section-by-section on every sync. That does not survive a fast-iterating team.

Five distinct failure mechanisms, not one:

1. **Write contention.** One file, overwritten by every agent and teammate. "Sections are
   overwritten" means the last writer silently wins.
2. **Semantic merge conflicts.** Prose in fixed sections cannot auto-merge; two agents each
   adding a verified claim produce a conflict git cannot resolve.
3. **Monotonic growth.** Current Working State, Known Gaps, In Development, and the System
   Map all grow with system age, until the front door is a file nobody reads.
4. **It contradicts the project's own thesis.** `brief` exists because "recall is index,
   not store" — yet `STATE.md` is read wholesale every session and grows without bound.
5. **Verification cost scales with claim count.** At a few hundred claims an honest sync
   becomes a build.

The decisive observation is that **this repo already solved the problem twice** and the
state layer did not inherit the solution. `.gitattributes` marks both
`specs/*.log.ndjson` and `roles/activity.log.ndjson` as `merge=union`: append-only event
logs whose concurrent writes combine instead of conflicting. The plan layer additionally
takes a per-plan `.lock` for read-modify-write. The state layer got a prose document.

## Decision

We will restructure the state layer into **three tiers, separated by mutability** — the
property that actually determines whether an artifact can rot.

**Tier 1 — Immutable sources.** Append-only, union-merged, never overwritten: git history
and its trailers, a new `docs/state.ndjson`, the existing `specs/*.log.ndjson` and
`roles/activity.log.ndjson`, `docs/adr/`, and GitHub issues. Every verified claim, gap, and
component change becomes an **event** rather than an edit.

**Tier 2 — Projections.** Generated, never hand-edited, and **capped**: `STATE.md`,
`specs/_index.*`, the `SYSTEM.md` edge table, `roles/_roles.json`, `.github/CODEOWNERS`.
`STATE.md` joins the family that already carries the rule "never hand-edit them; rerun the
command that builds them."

**Tier 3 — Authored and durable.** Human-first, deliberately not generated: ADRs,
`CONTEXT.md`, `STACK.md`, and plan prose.

**One id space joins the tiers.** Plans carry an immutable slug, ADRs `ADR-NNNN`, issues
`#N`, commits a sha, components a `SYSTEM.md` node name, contracts the literal string that
crosses. Commit trailers carry these ids into history, which is what makes git a
participant in the graph rather than a parallel record.

**We add `session` as a first-class id.** `agent` and `session` exist today as plan
metadata that nothing consumes. A session is the natural unit of one working block, so
`Session:` in trailers and on events makes "where did this leave off" a query over one
session rather than a document nobody writes at session end.

**Ordering is commit order.** Union merge concatenates without ordering, and wall-clock
timestamps collide and skew across machines, so a projection that reduces last-write-wins
needs a total order every writer already shares. Git's commit order is that order. Events
are ordered by the commit that introduced them, with an in-file sequence for ties.

**Entries are pointers, not content.** A projected line carries the ids needed to decide
whether to follow it — `plan:` `phase:` `adr:` `issue:` `session:` — never the detail
itself. Truncating a projection therefore costs immediacy, never reachability.

**Caps rank by importance, not recency alone.** Events carry a weight so a capped view
shows the most significant state rather than the most recent, with the remainder reachable
behind an explicit "show all". A cap that drops the least important is a summary; a cap
that drops the oldest is data loss with extra steps.

**`STATE.md` stays committed.** It is the offline, no-tooling read path, and a generated
file in git will conflict — so it is resolved by regeneration, never by hand.

## Consequences

Easier: concurrent agents stop clobbering each other. The snapshot is bounded by
construction regardless of project age. "What was true in March" becomes answerable — today
that history is destroyed by overwriting. Grounding cost stops scaling with project age.

Harder: the source of truth is no longer human-readable — an NDJSON log needs the renderer,
where a document degrades gracefully to plain reading. A wrong projection is harder to
diagnose than a wrong paragraph. Appending a structured event is more ceremony than editing
a line. We accept these because they are small-scale costs, and the failure modes they
replace are the ones that break at the scale this team actually operates at.

Follow-up work created: `state render` and the event schema; `merge=union` plus a
regenerate-on-conflict path for `STATE.md`; claim path sets so the sync trigger can fire on
intersection rather than commit count; migration of the existing `STATE.md` claim format,
which the current `state check` already accepts in both anchored and unanchored forms.

## Alternatives Considered

- Keep `STATE.md` authored and rely on discipline — rejected: the five mechanisms above are
  structural, and discipline does not fix a merge conflict.
- Decompose into per-component state files with no log — rejected as the primary design: it
  fixes contention but not history, and cross-cutting claims have no natural home. Retained
  as the organising discipline for Tier 2 views.
- Derive everything at read time and store nothing — rejected: it cannot go stale, but a
  fresh cloner with no tooling gets nothing, which defeats the requirement that the repo
  answer its own questions.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
