---
id: ADR-0003
title: The system map records cross-boundary contracts only
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: skills/discuss/templates/system.md, skills/cozyplan/scripts/plan_tool.py
---

# ADR-0003: The system map records cross-boundary contracts only

## Context

`SYSTEM.md` stored nodes and explicitly forbade edges: "dependency edges, protocols, and
data flow are OUT of this file." That reasoning was sound about maintenance cost — nodes
change on add/remove/rename (weeks), while in-repo wiring changes on nearly every commit.

But it left "how does changing this function impact the rest of the system?" with no answer
at all, which is one of the four questions this baseline exists to make answerable from a
clone.

Two facts reframed the problem. First, "who calls this function inside the repo?" is
answered exactly, instantly, and never stalely by `find references` — writing it down is a
cache of a free lookup that rots immediately. Second, `plan_tool` already carried
`provides` and `consumes` as first-class append-only metadata, stamped into every plan
template, rendered by `brief`, and exported per-plan into `specs/_index.json` — a
machine-readable dependency graph that was always empty because `SKILL.md` never mentioned
the fields existed.

## Decision

We will record **only the contracts that cross a process, repo, or network boundary** —
a route, a queue topic, an event name, a shared table, a config key. Calls that stay inside
one component are the toolchain's job and are never written down.

Each edge records `From | To | Kind | Contract | Breaks if | Why`. `From` owns the
contract, `To` depends on it, so **the arrow points at the blast radius**: "what does
changing X break?" is the set of rows where `From = X`.

`Contract` is the **literal string that crosses**, never a prose description. This is what
makes an edge falsifiable: an edge whose `Contract` cannot be grepped in the source of both
sides is not an edge, and belongs in an ADR instead.

The plan-level `provides`/`consumes` fields are the same graph at planning time, and are
now documented as such. `plan_tool index` flags any contract consumed but provided by
nothing.

The map declares its trust boundary out loud: **it is a floor, not a ceiling.** It lists the
crossings the project knows about and never certifies that no others exist. Every impact
answer is "these edges, plus whatever the code shows."

We reject a coupling-strength column (unfalsifiable and drifts silently) and a
last-verified date (a claim nobody re-verifies, indistinguishable from a fresh one, and it
manufactures confidence). Freshness is computed, not asserted.

## Consequences

Easier: impact questions get a real answer at the altitude where blast radius actually
lives — the interface, not the function. The write rate matches a rate humans sustain,
because deployable interfaces change a few times a quarter on changes that already get a
plan and a review.

Harder: a **stale edge table is worse than no edge table**. With nodes only, an agent knows
it must read the code. With a table present, it reads the table and stops — so a missing
edge yields a confident "nothing depends on this" and ships a break. Missing-edge detection
therefore outranks dead-edge detection, even though it is the harder, heuristic half.

Follow-up work created: extend `templates/system.md` with the edge table and the trust
boundary; teach Build Plan to update edges alongside nodes; sharpen Orient's "never write
the walkthrough" rule so that narration stays live but **map repair** is permitted — the
read path is what pays for the write path.

## Alternatives Considered

- Function-level or call-graph edges — rejected: derivable by `find references`, changes
  every commit, and answers at the wrong altitude (renaming a private helper has no blast
  radius; changing a route's response body has a large one).
- Keep nodes-only and derive impact live from code on every question — rejected: never
  wrong, but it cannot see out-of-process consumers at all, which is precisely the case no
  tool can answer.
- Generate the whole graph from static analysis in CI — kept as an optional overlay, not
  the primary record: it needs one extractor per stack and still cannot see cross-process
  contracts.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
