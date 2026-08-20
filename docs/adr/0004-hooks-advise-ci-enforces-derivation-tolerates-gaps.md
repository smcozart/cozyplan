---
id: ADR-0004
title: Hooks advise, CI enforces, and derivation tolerates gaps
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0001-github-is-the-work-item-source-of-truth.md, hooks/hooks.json
---

# ADR-0004: Hooks advise, CI enforces, and derivation tolerates gaps

## Context

The state layer is moving from hand-maintained documents to records **derived from git**:
commit trailers (`Plan:`, `Phase:`, `Refs:`, `ADR:`, `Verified:`) become the join key, and
`STATE.md` becomes a render rather than a document someone remembers to update. That only
works if the trailers are actually written, which raises the question of how to make them
appear.

The obvious answer is hooks. Three layers exist and they differ enormously in what they
guarantee:

- **Claude Code hooks** (`.claude/settings.json`) fire for the agent, in Claude Code, on
  one machine. A human, a Bash `sed`, or any other tool bypasses them. `plan_tool hooks
  install` writes only these.
- **Git hooks** fire for anyone committing in that clone regardless of tool, but
  `.git/hooks/` is **not versioned and not cloned**, so shipping them with the repo does
  not install them. `--no-verify` bypasses them anyway.
- **CI checks** run on every pull request and cannot be bypassed by a developer.

This project has already been burned by treating an advisory layer as a guarantee. The
shipped `hooks/hooks.json` describes its own failure mode in its own description — *"Both
fail open — if uv is missing, enforcement silently disappears"* — and that is exactly what
happened: on a machine without `uv`, plan validation was silently off. The failure was
documented and shipped, and nobody connected the note to the consequence.

The `## Scope` section records the same lesson from an earlier iteration: a
coordination/enforcement layer was removed because it "presented as guarantees it couldn't
keep under real multi-agent use."

## Decision

We will layer the three mechanisms by what each can actually promise, and we will not let
any of them become load-bearing for correctness.

**Hooks advise.** Local hooks exist for fast feedback, not for guarantees. The `commit-msg`
hook **injects** trailers it can infer (from the branch name or the active plan) rather
than rejecting commits that lack them: rejection trains people to type `--no-verify` and
costs us both the trailer and the habit, while injection is invisible and captures most of
the data for free.

**CI enforces.** `plan_tool state check` runs as a required status check on every pull
request. This is the only layer whose result a developer cannot route around, so it is the
only place a real gate belongs.

**Derivation tolerates gaps.** A commit with no trailers is not an error. It is reported as
**unattributed work**, which is itself a signal about where process is leaking. Every
render must produce a correct, narrower answer from partial data rather than a wrong one.
If the hook layer silently dies again — and one day it will — the reports get thinner, not
false.

**Wiring is observable.** Because the failure mode we are guarding against is *silent*
misconfiguration, `plan_tool doctor` reports what is actually wired in this clone:
`core.hooksPath`, registered Claude hooks, the CI workflow, `gh` availability. The cure for
silent enforcement failure is not more enforcement; it is a command that answers "is this
clone actually wired?"

**Git hooks are versioned.** They live in a tracked `.githooks/` directory activated by
`git config core.hooksPath .githooks`, so the hook *content* clones even though the
activation is one command per clone — which `doctor` then detects and reports.

**Human-only steps are named, never faked.** Enabling branch protection and marking a
status check required needs repository admin in the GitHub UI. No skill can do it, and
claiming otherwise would manufacture exactly the guarantee this ADR exists to prevent.
Those steps are handed to the `wizard` skill and printed for a human.

## Consequences

Easier: the system degrades honestly. A missing hook, an absent `uv`, a teammate who
committed from a different tool — each narrows the derived picture without corrupting it.
Trailer capture gets most of its value from injection, at no cost to the committer.

Harder: real enforcement now depends on CI being configured, which requires a human with
admin rights and is therefore outside the skill's control. Until that is done, the layering
provides feedback but no gate — and `doctor` must say so plainly rather than implying
protection that is not there.

Follow-up work created: build `plan_tool state check` first, since a hook is only as useful
as the check it runs; then the CI workflow; then `.githooks/` plus `core.hooksPath`; then
`doctor`; then the `wizard` handoff for branch protection.

## Alternatives Considered

- Reject commits missing trailers in `commit-msg` — rejected: teaches `--no-verify`, and
  the bypass costs both the data and the habit.
- Rely on Claude Code hooks alone — rejected: they cover one tool on one machine, and this
  repo has already demonstrated they can die silently.
- Require trailers for the derivation to work at all — rejected: makes an advisory layer
  load-bearing, which is the precise mistake `## Scope` records having already made once.
- Commit the hooks into `.git/hooks/` during init — rejected: not versioned, so it does not
  survive a clone and cannot be updated with the repo.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
