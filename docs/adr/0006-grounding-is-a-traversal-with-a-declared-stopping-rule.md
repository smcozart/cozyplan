---
id: ADR-0006
title: Grounding is a traversal with a declared stopping rule
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0005-state-is-a-union-merged-log-projected-into-capped-views.md
---

# ADR-0006: Grounding is a traversal with a declared stopping rule

## Context

The repo had exactly one way to orient a reader: open `STATE.md` and read top to bottom.
That serves nobody well, because the people arriving want different things.

A new developer adding a feature needs vocabulary, stack lanes, and the contracts they must
not break — and needs almost no history. A returning developer fixing a bug needs the
opposite: what changed while they were away, and which decisions govern the code they are
about to touch, so they do not "fix" something that was deliberate. An architect reviewing
the system needs breadth — every component, every crossing, every gap — and none of the
task detail. An agent resuming a plan needs strictly less than all of them: the re-entry
point and one phase.

"Read this file top to bottom" also has no stopping rule. A reader stops when bored, which
is the premature-completion failure the project's own writing rubric names.

Two structural gaps sat underneath this. First, **backward grounding did not exist**: there
was no way to go from a file to the decisions that govern it. Second, any fixed list of
reader types is a closed vocabulary over an open space of intents, so it will always miss
cases.

## Decision

We will treat grounding as a **traversal of the id space from ADR-0005**, parameterised by
four things: the **entry node**, the **direction**, the **stopping rule**, and the
**budget**.

**The algorithm is primitive; the modes are presets.**

1. **Resolve** — turn the stated intent into entry ids. The id space is small and typed, so
   free text resolves against it: an existing path or directory to a component, `ADR-NNNN`
   to a decision, `#N` to an issue, a slug to a plan, a term to a `CONTEXT.md` entry, a
   literal contract string to a `provides`/`consumes` edge, a hex string to a commit.
   Resolution deliberately spans **code and docs together** — a component is both a
   directory and a `SYSTEM.md` row, and either may be what the reader meant.
2. **Expand** — walk typed edges from the resolved nodes. Backward: path → commits →
   trailers → plan / ADR / issue. Forward: plan → phases → components → contracts.
   Sideways: component → the edges where it is `From`, which is its blast radius.
3. **Rank** — by relevance to the intent, then by the event weight from ADR-0005.
4. **Stop** — on the mode's declared rule, or on budget.

**Four presets, each with a checkable bound:**

| Mode | Entry | Direction | Grounded when |
| --- | --- | --- | --- |
| `--build <issue\|plan>` | intent | forward | the files to touch and the contracts not to break are both named |
| `--change <path>` | code | backward | every ADR governing the path is named, and its blast radius is enumerated |
| `--review` | none | breadth | every component, every cross-boundary contract, and every open gap is enumerated |
| `--resume <plan>` | plan | minimal | `next` returns an id and that phase alone is loaded |

**Any intent outside the presets runs the same algorithm** with resolution from free text.
There is no "unsupported intent": an unrecognised question resolves what it can and expands
from there. **When nothing resolves at all, grounding falls back to the situation** —
current branch, uncommitted changes, position relative to the remote, plans sitting at
`[wip]`, and the most recent session — which is always answerable and never returns empty.

**Re-grounding fires on signals, never on a schedule.** At session start, position against
the remote. Before editing a path, run the backward traversal on it. Before claiming
something done, intersect the changed paths with the path sets claims depend on. A schedule
gets ignored; a signal that stays quiet when nothing relevant changed keeps its credibility
— a test run or a spike touches nothing any claim depends on, and must produce no prompt.

**Thin answers must read as thin.** Backward grounding is only as complete as trailer
coverage, which will be partial for a long time and absent from history predating the
convention. Every backward result therefore reports the fraction of touching commits that
carried trailers. A confident empty answer — "nothing governs this code" — is the one
failure mode that would actively cause the harm this decision exists to prevent.

## Consequences

Easier: each arrival gets a read path sized to its purpose, and grounding cost becomes
O(mode) rather than O(project age) — `--resume` stays cheap forever. `STATE.md` is demoted
from "the front door" to one projection among several, which is what lets it stay capped.
The architect's review becomes a computed report — claims whose code moved since their
proof, contracts consumed but never provided, plans stalled at `[wip]` — rather than a
document someone maintained.

Harder: the traversal needs the id space to be populated, so it inherits every gap in
trailer coverage, `provides`/`consumes` fill-in, and `SYSTEM.md` accuracy. Resolution of
free text is heuristic and will sometimes pick the wrong entry node; it must show what it
resolved so a reader can correct it rather than silently grounding on the wrong thing.

Follow-up work created: implement resolution over the id space; implement the four presets
over the shared algorithm; add the trailer-coverage fraction to backward results; wire the
session-start remote check and the path-intersection trigger.

## Alternatives Considered

- A fixed set of reader personas with hand-written read paths — rejected: a closed
  vocabulary over an open space, and it makes every new intent a change request.
- One front door read top to bottom — rejected: it is the current design, it has no
  stopping rule, and it grows without bound.
- Always ground maximally and let the reader skim — rejected: it spends the reader's
  attention and an agent's context on material the task does not need, which is the cost
  `brief` was created to avoid.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
