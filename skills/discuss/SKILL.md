---
name: discuss
description: Stress-test a design by interviewing in rounds until every open decision is settled, recording what settles as ADRs, glossary terms, stack defaults, and system-map edges, then handing the locked decisions to a plan; also explains how an existing system runs today. Use when a design needs grilling before it is built, when a plan would otherwise rest on unsettled decisions, or when someone needs orienting in a running system.
---

# Discuss

## Purpose

Discuss runs the **understanding loop**: write understanding *in* by interviewing the user relentlessly and recording what crystallizes, then read it *out* on demand by orienting a reader in how the system runs today. The interview is the write side — it works the design tree in rounds until the frontier is empty, surfacing weak assumptions before they land in a plan. The records are the residue — decisions as ADRs, vocabulary as a glossary, stack defaults and deviations in place — so the "why" survives instead of evaporating into chat history. Orient is the read side — it never stores a description, it synthesizes the current picture live from the map, the code, and the records.

## Session start

Read the standing context before interviewing or orienting, in this order:

1. `STACK.md` (repo root) — technology defaults and their lanes
2. `CONTEXT.md` (repo root) — the glossary
3. `docs/adr/` — scan the ADR titles; open the ones in scope
4. `specs/_index.html` — the plan catalog, if the repo uses cozyplan
5. (brownfield) the relevant **code** — the source of truth for how components actually wire and behave

Missing files are normal on a fresh repo; create them lazily when the first thing worth writing appears. Never block on them.

## Workflow

Select the single best-matching workflow and read its file before acting.

| Workflow | When to call it | File to read |
| --- | --- | --- |
| Interview | The default — stress-test, grill, or discuss a design or idea before it's built | `workflows/interview.md` |
| Seed Stack | No `STACK.md` exists yet / the repo's environment has not been recorded | `workflows/seed-stack.md` |
| Orient | Understand how the system runs today / onboard onto an existing component | `workflows/orient.md` |

## Context artifacts

Four living records hold the understanding the loop writes. Each has one job; keep them from bleeding into one another.

| Artifact | Location | Holds | Rule |
| --- | --- | --- | --- |
| `STACK.md` | repo root | Technology defaults, each as *default + when-to-use lane + escape hatch*, plus a Deviations section | Describes defaults, does not enforce them; a deviation that clears the three gates gets an ADR |
| `CONTEXT.md` | repo root | The glossary — canonical domain terms and their meanings | Glossary **only**; zero implementation detail, no spec, no scratch pad |
| `docs/adr/` | `docs/adr/NNNN-kebab-title.md` | One decision per file, recorded only when all three gates pass, in the shape of the sibling `cozyplan` skill's `templates/adr.md` | Hard to reverse **and** surprising without context **and** the result of a real trade-off |
| `SYSTEM.md` | repo root | The component map — nodes (what exists, who owns it, where its why lives) plus the cross-boundary edges between them | Nodes change on add/remove/rename/re-own; edges record only contracts crossing a process, repo, or network boundary, each with a greppable `Contract` string. In-repo calls are the code's job (ADR-0003) |

## Scope

Discuss interviews, records, and hands off — nothing more. It does not enforce, gate, deny edits, run modes, or revert; **git owns those** (branches/PRs, CODEOWNERS, tags, blame, CI). If a decision seems to need enforcement, the answer is a git-layer convention, not machinery here.

## Exit

An interview ends when the user has confirmed the shared understanding — not before. It then summarizes the resolved decisions as **locked inputs** and handing them to the cozyplan skill: greenfield work → its Create Plan workflow, a brownfield structural revision → its Update Plan workflow. The plan links the ADRs inline in its phase and task rationale.
