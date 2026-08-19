---
id: ADR-0007
title: Git hooks are tracked and opted into per clone
status: accepted
date: 2026-08-18
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0004-hooks-advise-ci-enforces-derivation-tolerates-gaps.md
---

# ADR-0007: Git hooks are tracked and opted into per clone

## Context

ADR-0004 established that hooks advise while CI enforces, but left the
distribution problem open: `.git/hooks/` is not versioned and not cloned, so
shipping hooks alongside the skill does not install them anywhere.

## Decision

Hooks live in a **tracked `.githooks/` directory** and each clone opts in with
`plan_tool hooks git-install`, which sets `core.hooksPath` and records the
interpreter and plan_tool path in git config. The hook *content* therefore
clones and updates with the repo; only the activation is per clone, and `doctor`
reports when a clone has not done it.

`commit-msg` **injects** trailers it can demonstrate — ADRs from the staged
files, a plan whose id matches a branch segment — and never rejects. Rejection
teaches `--no-verify`, which costs both the trailer and the habit.

Trailer grammar is delegated to `git interpret-trailers` rather than hand-rolled.
The first hand-rolled attempt in this session silently dropped every trailer
behind a `Co-Authored-By` line, because a blank line had split the block.

## Consequences

Easier: coverage rises without anyone remembering, and the hooks update with the
repo like any other tracked file.

Harder: activation is still a manual step per clone, so `doctor` has to carry it.
Inference is deliberately narrow — it will never add `Verified:`, which no hook
can prove.

## Alternatives Considered

- Write into `.git/hooks/` at init — rejected: not versioned, does not survive a
  clone, cannot be updated with the repo.
- Reject commits missing trailers — rejected: teaches `--no-verify` (ADR-0004).
- A dependency such as Husky — rejected: adds a package manager to a stdlib-only
  Python tool.

## Status History

- 2026-08-18 — proposed by Sean Cozart
- 2026-08-18 — accepted by Sean Cozart
