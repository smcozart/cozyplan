---
id: ADR-0002
title: The interview works the design tree in rounds, not one question at a time
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: skills/discuss/workflows/interview.md
---

# ADR-0002: The interview works the design tree in rounds, not one question at a time

## Context

`discuss` and the installed `grilling` skill prescribed contradictory interview
disciplines for the same job. `discuss/SKILL.md` required "**One question at a time.** A
batch of questions is bewildering and gets answered on autopilot." `grilling` required
"Work the tree in **rounds**… Ask the whole frontier in one round: number each question and
give your recommended answer."

Both skills were model-invoked with overlapping trigger words, so which discipline a
session got was effectively a coin flip — the user would experience the interview as
inconsistent.

One-question-at-a-time also makes the interview cost linear in the number of decisions:
twenty decisions is twenty human round-trips. There is a tell that this cost was already
being felt — `discuss` had to explicitly *forbid* skipping the interview. A step you must
forbid skipping is a step that is too expensive.

## Decision

We will fold `grilling`'s mechanics into `discuss` and retire the one-question-at-a-time
rule. The interview maps the work as a **design tree** and works it in **rounds**: the
**frontier** is every decision whose prerequisites are settled and which can be stated
precisely now; the whole frontier is asked in one numbered round, each question carrying a
recommended answer and a one-line reason; then the agent stops and waits.

One-question-at-a-time is preserved as the degenerate case — a frontier of size one — so
nothing is lost. `discuss`'s own round-size discipline survives as a diagnostic rather than
a prohibition: **a frontier past about seven means the tree was not cut at its
prerequisites**; find the upstream decision the rest hang off and ask that one alone.

Finding facts is the agent's job and never the user's; decisions are the user's and never
the agent's. A running exploration is an unsettled prerequisite, so the rest of the
frontier is asked while it runs.

The interview terminates on a recomputable state — **the frontier is empty** — followed by
the user's explicit confirmation, replacing the unfalsifiable "until nothing load-bearing
is unexamined".

We import rather than delegate: `discuss` carries its own copy so the baseline has no
runtime dependency on an external skill remaining installed. The source is credited.

## Consequences

Easier: a twenty-decision design costs roughly four rounds instead of twenty round-trips.
The termination condition becomes checkable. `discuss` gains the non-blocking sub-agent
rule, which is meaningless with a single question in flight.

Harder: rounds must be well-cut or they degrade into exactly the bewildering batch the old
rule feared — the ≤7 diagnostic and the sharpness test are what prevent that. We now carry
our own copy of mechanics that originate upstream, so improvements there will not
propagate to us.

Follow-up work created: rewrite `skills/discuss/workflows/interview.md`; strip the
mechanic from `discuss/SKILL.md`'s Purpose; sharpen the `description` so it stops competing
with `grilling` on the same trigger words. `cozyplan/workflows/create-plan.md` quotes the
depth rubric literally, so its phrasing must be preserved.

## Alternatives Considered

- Have `discuss` delegate to `grilling` — rejected: couples the team's planning baseline to
  an external skill we do not control.
- Keep both skills and sharpen only the descriptions — rejected: leaves two contradictory
  disciplines installed, so the interview stays inconsistent.
- Disable model invocation on `grilling` so `discuss` wins every call — rejected: `triage`,
  `wayfinder`, and `improve-codebase-architecture` all reach `grilling` by skill call, and
  a user-invoked skill cannot be reached by another skill.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
