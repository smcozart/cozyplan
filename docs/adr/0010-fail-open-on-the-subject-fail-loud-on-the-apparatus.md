---
id: ADR-0010
title: Fail open on the subject, fail loud on the apparatus
status: accepted
date: 2026-08-24
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0004-hooks-advise-ci-enforces-derivation-tolerates-gaps.md, docs/handoff-enforcement-layer.md, hooks/hooks.json, skills/cozyplan/scripts/hooks/run-hook.sh
---

# ADR-0010: Fail open on the subject, fail loud on the apparatus

## Context

A consuming project introduced and caught six defects across 2026-08-23/24. Three of the four
studied were caught by checks that **already existed, running too late** — in CI after a push,
when the working tree could have answered. That is a placement problem, and it is the subject of
separate work. This ADR answers the question that blocks it.

While verifying the hook layer, four probes were fired at `guard_plan_edit` on a machine whose
hook layer was believed broken:

| Probe | Result |
|---|---|
| `Write` to `README.md` | silent, exit 0 — not a plan path |
| `Write` to `specs/x.html`, plain content | silent, exit 0 — touches no managed region |
| `Write` to a `specs/x.html` that does not exist | silent, exit 0 — new-file authoring, allowed |
| `Edit` touching `data-meta=` on a plan path | **deny** — the only shape that fires |

Three consecutive false positives for "the hook works". Every one of those silences is **correct
behaviour**, and every one is **indistinguishable from the hook not running at all**.

That is the whole finding. `guard_plan_edit` fails open on an unparseable payload, on a wrongly
shaped payload, on a non-plan path, and on a new file. Each is right. Each leaves behind exit 0
and no output — which is byte-identical to what an absent interpreter leaves behind. A reader has
to already know the failure to read the result as anything other than health.

`doctor` reproduced the same error one level up. It printed `all 4 registered` — a fact about a
config file, which says nothing about whether any hook ran — adjacent to `uv absent — plan_tool
runs on plain python3, so this is fine`, which is true of `plan_tool` and false of the hooks.
Both lines were individually correct. Together they read as a clean bill of health on a host
where the layer could not start.

Two things found while settling this empirically are worth recording, because they contradict
what the repository previously believed:

- **The `uv` failure was never silent.** Shell-form hooks run under `sh -c`, so a missing `uv`
  produces `sh: uv: command not found` and exit 127, which Claude Code surfaces as
  `Failed with non-blocking status code:` on *every* matched tool call. `hooks/hooks.json`'s own
  description, the README, and the issue all called it silent. It was loud, constant, and
  non-blocking. Fixing the runner was therefore never going to buy observability.
- **Only one of the four hooks can refuse anything.** `PreToolUse` blocks the tool call;
  `UserPromptSubmit` blocks by *erasing the user's prompt*; `PostToolUse` and `SessionStart`
  cannot block at all. So "test a hook by observing a refusal" is available to `guard_plan_edit`
  and to nothing else, and the other three must be observed by the context they emit.

## Decision

**Fail open on the subject. Fail loud on the apparatus.**

Not finding a reason to object is a finding, and hooks keep making it silently. Not being able to
look is not a finding, and must never again leave the same trace behind.

- **Subject failures stay open and silent.** An unreadable payload, a wrongly shaped payload, a
  non-plan path, a new file, a prose edit — the hook exits 0 and says nothing. Unchanged.
- **Apparatus failures are loud.** No interpreter resolves, the hook script is missing, the
  subprocess will not launch — the hook says so on stderr and exits non-zero. Where the event can
  block, it blocks: `guard_plan_edit` exits 2, so a plan write is refused rather than proceeding
  unchecked. `UserPromptSubmit` never uses exit 2, because exit 2 there erases the user's prompt
  instead of reporting anything.
- **The interpreter is resolved at call time, never named in the manifest.** `hooks/hooks.json`
  is static and cannot ask the host what it has, which is why it hardcoded `uv run`. Every hook
  now launches through `run-hook.sh`, which probes `python3`, `python`, `py`, then falls
  back to `uv`. Candidates are probed for `>=3.9` rather than merely found on `PATH`, because
  `command -v python3` succeeds against the Windows Store alias stub, which is not an interpreter.
- **A hook must be able to demonstrate that it ran.** `plan_tool hooks selftest` drives every hook
  with a payload it must react to — through the command the host actually registered — and fails
  when any of them stays silent. Registration is a record; a refusal is an outcome.
- **`doctor` reports both, and they are allowed to disagree.** `hooks registered` is labelled a
  record. `hooks observed` runs the selftest. A registered-but-inert layer is `ok` on the first
  and a `gap` on the second, which is the state that previously printed as healthy.

**This does not supersede ADR-0004.** ADR-0004 governs what hooks do with *findings*: they advise,
they inject rather than reject, and CI remains the only real gate. That still holds — the guard
still refuses only what it refused before, and no new check gained the power to block work. This
ADR governs what the layer does about *its own absence*, which ADR-0004 never addressed. The two
compose: an advisory layer is allowed to be quiet about your code, and is not allowed to be quiet
about itself.

Reserving the gap for **registered-and-inert** rather than **unregistered** is deliberate. A CI
runner registers nothing, correctly; failing `--strict` there on every run is how a team learns to
delete the flag. The dangerous state is the one that claims wiring it does not have.

## Consequences

Easier: the four-probe episode cannot recur. One command answers "is this layer alive here", it
runs on a fresh clone before any work exists, and CI runs it on Linux, macOS and Windows — so a
teammate's broken wiring is caught on a clean machine rather than trusted on theirs. The hook layer
also got *faster*: resolving `python3` costs 24ms against `uv run`'s 62ms on the same host, and the
hooks declare `dependencies = []`, so `uv` bought latency and nothing else.

Harder: `guard_plan_edit` can now block plan writes for a reason that has nothing to do with the
plan. A host with no Python at all refuses edits to `specs/*.html` until it is fixed. That is the
intended trade — the alternative is writing unguarded plans while believing they are guarded — but
it is a real cost, and it is why the message names the fix rather than only the failure.

Also harder: the dead exit code now lives in two places, `HOOK_DEAD_EXIT` and the literal trailing
argument in `hooks/hooks.json`. Drift between them is the difference between a blocked edit and an
erased prompt, so a test asserts they match rather than trusting them to.

## Alternatives Considered

- **Make the hooks gate, superseding ADR-0004** — rejected: gating a layer you cannot tell is
  running is worse than not gating. On a team of N machines, N−1 can be inert while every report
  reads healthy; turning on blocking gates there teaches `--no-verify` on the machines that work
  and enforces nothing on the ones that do not. Observability is the precondition, not the sequel.
- **Fix the runner and stop there** — rejected: the runner failure was already loud. It is a real
  portability bug and it is fixed here, but it was never the silent one.
- **A passive run ledger (record each invocation, report last-run)** — deferred, not rejected. It
  answers "did it fire during real work", which is a different and later question than "can it fire
  at all". It also needs a storage decision (per-machine or committed) that this pass does not.
- **Keep `doctor`'s single `claude hooks` row and make it stricter** — rejected: one row cannot
  hold both a record and an outcome, and collapsing them is what produced the misleading report.
- **Have the hook scripts self-report liveness on every call** — rejected: `PostToolUse` and
  `SessionStart` stderr on exit 0 is discarded and never reaches Claude or the user, so the
  report would be written where nobody reads it.

## Status History

- 2026-08-24 — proposed by Sean Cozart
- 2026-08-24 — accepted; earned by four probes that all read as success on an inert layer
- 2026-08-24 — extended to the second registration path. `hooks install` resolved the
  interpreter at *install* time and wrote `uv run <absolute path>` into
  `.claude/settings.json`, which is a committed file — the same class this ADR closes,
  surviving on the route the ADR did not name. Both paths now share one command builder.
  `run-hook.sh` moved from the plugin root to `skills/cozyplan/scripts/hooks/`, beside the
  hooks it launches, because the skill directory travels through all three distribution
  shapes and the plugin wrapper travels through one.
- 2026-08-28 — extended to the **third** registration path, the git hooks. `commit-msg` and
  `pre-push` both ended in `|| true`, so a recorded runner that had left the host produced no
  trailer, no output and exit 0 — byte-identical to a healthy commit with nothing to prove. The
  decision needed no change; the path had simply never been audited against it. Two clauses are
  worth writing down because this path differs from the other two.

  **Loud here cannot mean non-zero.** A git hook that exits non-zero rejects the commit or the
  push, which is exactly what ADR-0004 forbids and what teaches `--no-verify`. So the apparatus
  reports on **stderr and still exits 0**. That is not a weaker reading of this ADR: the
  requirement is that the two failures leave different traces, and on this path stderr is the
  trace, because git hook stderr reaches the terminal. It is the same reasoning that *rejected*
  self-reporting for `PostToolUse`, where stderr on exit 0 is discarded — the test was always
  whether anyone reads the stream, not which stream it is.

  **A recorded runner is a fact with a shelf life.** `git-install` writes what resolved on the
  day it was wired; uv gets uninstalled and interpreters move. The record is now preferred,
  verified with `command -v`, and re-resolved by the same probe `run-hook.sh` uses when it no
  longer answers — and the re-resolution is itself reported, because a stale record is a
  half-wired clone that still reads as configured. Four tests pin it, each confirmed red against
  the old templates first; the pre-push one exists because `state check` exits non-zero on a real
  finding too, so the exit code alone cannot separate a finding from a crash.
