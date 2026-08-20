---
id: ADR-0009
title: Role ownership maps are git's job, not cozyplan's
status: accepted
date: 2026-08-19
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0005-state-is-a-union-merged-log-projected-into-capped-views.md, docs/adr/0008-the-state-view-shows-everything-until-it-cannot.md
---

# ADR-0009: Role ownership maps are git's job, not cozyplan's

## Context

`plan_tool roles build` compiled `roles/*.md` into `roles/_roles.json` and
`.github/CODEOWNERS`, with a glob engine underneath it to detect overlapping ownership
globs. ADR-0005 listed both generated files as Tier 2 projections.

It was removed in the 3.0 work, and this ADR is written *after* that removal, which is
the process failure worth recording alongside the decision. The removal cited ADR-0008,
which says nothing about roles. A spec review caught the citation, and it was right to:
two documented Tier 2 artifacts disappeared with no decision authorising it and no line
in the migration note. The repo's own review layer caught its author skipping the repo's
own rule.

The evidence for removing it was strong and is unchanged:

- This repo, the reference implementation, has no `roles/` directory and no `CODEOWNERS`.
- `COZYPLAN_ROLE` was read nowhere in the codebase; it was only cleared in a test fixture.
- The glob engine's own comment named two consumers. One (`roles build`) was the feature
  itself; the other claimed "the guard imports `glob_match`", and the guard hook imports
  stdlib only and has never imported `plan_tool`. The comment was false before the
  removal, so the engine was dead code describing users it never had.
- `SKILL.md` already said review routing is git's job: "branches and PRs gate merges,
  CODEOWNERS routes review". The generator restated that claim as a feature.

## Decision

Cozyplan does not generate ownership maps. `roles build`, `roles/*.md`, `templates/role.md`,
the `generate-roles` workflow, and the glob engine are removed.

**`CODEOWNERS` stays a real thing; git owns it.** A team that wants review routing writes
`.github/CODEOWNERS` directly, in GitHub's own format, which is better documented than any
format we would invent and needs no regeneration step.

**The plan `owner` field stays.** It labels which role owns a plan, Build Plan reads it,
and it is unrelated to review routing.

This supersedes ADR-0005's Tier 2 list where it names `roles/_roles.json` and
`.github/CODEOWNERS`. The remaining Tier 2 projections are `STATE.md`, `specs/_index.*`,
and the `SYSTEM.md` edge table.

**A removed command is a breaking change and belongs in the release contract.** The
migration note now carries it. A feature can be deleted for good reasons and still owe
its users a line telling them it is gone.

## Consequences

Easier: ~175 lines and one workflow leave the tool, along with a glob engine whose
semantics comment was the only thing keeping it legible. One fewer generated file for
`state check` and `doctor` to reason about.

Harder: a team that wanted the ownership map now hand-maintains `CODEOWNERS`. We accept
that because GitHub already validates that file and nobody was using ours.

## Alternatives Considered

- Keep it and wait for a user — rejected: it shipped in 2.2.0 and this repo, its most
  exercised consumer, never once created a `roles/` directory.
- Keep the glob engine for future use — rejected: it is a hypothetical seam with zero
  adapters, and `_glob_witness` existed only to probe overlap for the feature being cut.
- Revert the removal and re-decide — rejected: the decision was sound; only the record
  was missing. Writing the record is the correct repair, and this ADR is it.

## Status History

- 2026-08-19 — proposed by Sean Cozart
- 2026-08-19 — accepted by Sean Cozart, recorded after the fact; see Context
