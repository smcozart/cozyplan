# Handoff: design the enforcement layer

Self-contained. The evidence and decisions below originate in a sibling repository this one
cannot reach by relative path, so everything is restated rather than cited.

Not a post-mortem. The goal is the layer that decides **when** a check runs. cozyplan already
owns the checks and the mechanics; placement is what is missing.

## The finding the design answers to

Six defects were introduced and caught across 2026-08-23/24 in a project consuming cozyplan. Four
were studied:

| Defect | What caught it | Earliest it could have been caught |
|---|---|---|
| `=== ''` inside a `php -r '...'` shell string, killing the assertion step | CI, after push | Executing the block before pushing |
| `STATE.md` rendered citing an ADR whose file was never committed | CI, after push | `state check`, at pre-commit |
| A SHA from the wrong repository in the state log | `state check`, locally | Already correct |
| `composer.json` requiring `^8.3` while the lockfile needs 8.4.1 | Adversarial review | A test asserting the declared floor installs |

**Three of four were caught by checks that already existed, running too late.** The gap is
placement, not coverage — a stronger argument for hooks than any argument for more checks.

A fifth is categorically different. A commit deleted the only file in `tests/Unit`; git does not
track empty directories, so the directory left the repository while remaining on the machine that
made the commit. The suite kept passing there and aborted on every clone since, on every OS. No
local check could catch it, because **the defect *is* the difference between working tree and
repository**.

**So the design has two tiers, and the split is the load-bearing part:**

- **Local, at commit or push** — anything answerable from the working tree. Fast, fails before the
  mistake leaves the machine.
- **CI, on a clean machine** — anything where the working tree is the thing under suspicion.

Putting a check in the wrong tier is its own defect: a local check needing a clean machine gives
false confidence, a CI-only check that could have run locally burns a push cycle.

## Prerequisite: issue #9, and what it actually is

Verified against the sources, because the issue overstates it. "All four hooks invoke `python3`"
is not what ships:

- `.githooks/commit-msg` and `.githooks/pre-push` fall back to `RUN=python3` **only when
  `git config cozyplan.runner` is unset or empty**. `plan_tool hooks git-install` sets that key to
  `uv` (with `runnerarg=run`) or to `sys.executable`, an absolute interpreter path. So the bare
  `python3` fires on a clone that has `cozyplan.plantool` set but `cozyplan.runner` missing — a
  hand-wired or half-migrated clone. Narrow, real, silent.
- `hooks/hooks.json` — the plugin manifest — hardcodes `uv run "${CLAUDE_PLUGIN_ROOT}/…"` for both
  Claude Code hooks. Not `python3`, and **worse**: its own `description` field says *"Both fail
  open — if uv is missing, enforcement silently disappears."* One of those two is the `PreToolUse`
  guard, so a failure there sits in the path of every `Edit|MultiEdit|Write` call.
- `plan_tool hooks install` (the `.claude/settings.json` route) resolves through
  `_hook_runner_parts()` — `uv` if on PATH, else `sys.executable`. This path is already correct.
- `skills/cozyplan/scripts/adopt.sh` tries `python3` then `python`, never `py`. Windows commonly
  installs as `python` or the `py` launcher.

One class, three instances: **a runner named as a bare word the host may not resolve, failing open
and silently.** Fix the class. A layer that silently does not run on one of two machines is worse
than none, because it will be trusted. This is the one hard ordering constraint.

## What cozyplan owns, and what it does not

**Owns:** the hook *mechanism* — `.githooks/`, `hooks/hooks.json`, `skills/cozyplan/scripts/hooks/`,
and the `plan_tool hooks {install,git-install}` wiring. Runner resolution, fail-open/closed
semantics, the bypass, and `doctor`'s report of what is actually wired are all cozyplan's.

**Does not own:** which checks a consuming project runs. A particular test suite, a particular CI
job, a PHP-version assertion — those belong to that project. cozyplan ships no knowledge of them
and must not grow any.

There is currently **no mechanism for a consuming project to declare what to run**. Config today
is three git-config keys (`cozyplan.plantool`, `cozyplan.runner`, `cozyplan.runnerarg`) and no
project config file. Designing that declaration is part of this work: whatever its shape, cozyplan
invokes what the project declares and stays ignorant of its contents.

**Reuse before writing.** `plan_tool` already has `state check`, `doctor`, `validate`, `index`,
and `scan_drift`. The first pass moves existing checks earlier. If the answer is a new script, say
why an existing one could not be called.

## Principles this is designed against

- **A skill holds judgment; a script holds mechanics.** Mixing them means an agent re-derives
  mechanics it should just run and skims judgment it should apply. A hook decides *when* the
  script runs, which is the piece neither carries today.
- **A check observes the outcome, not the record of the outcome.** A hook confirming a script is
  *present* observes a record. A hook that *runs* it and blocks on failure observes an outcome.
  Six of nine findings from the first Windows run had this shape: a healthy `herd parked` row
  while the domain did not resolve, a `winget` success over an empty bin directory, a `STATE.md`
  recording a clean-clone proof while cloning had been broken for many commits. Every documented
  gate passed while the site was unreachable.

**Making anything gate is a change of posture, not a bug fix.** ADR-0004 here says hooks advise
and CI enforces; `reference/plan-tool.md` calls the guard and lint hooks *advisory* and says a
Bash/`sed` write bypasses them by design; `commit-msg` injects trailers and never rejects, because
rejection teaches `--no-verify` and costs both the trailer and the habit. Argue the change and
supersede ADR-0004 — do not quietly diverge from it.

## Settle empirically, do not assume

1. **Which hook events actually refuse?** `PreToolUse` reportedly blocks a tool call; `Stop`
   reportedly blocks completion. Establish what each can and cannot refuse by running it. The
   load-bearing unknown — nothing else can be designed on a guess.
2. **What does it cost per commit?** A pre-commit hook running a full suite is a different product
   from one running a three-second lint. Measure first.
3. **Fail open or fail closed, and where?** A hook that errors and blocks everything is worse than
   the defect; one that errors and passes silently is issue #9 again. Every hook needs a stated
   answer, not an inherited default.
4. **What is the deliberate bypass, and is it loud?** There will be an emergency. An unbypassable
   gate gets disabled permanently; a silent bypass gets used routinely.

## Ruled out — do not re-litigate without new evidence

- **A `loop.sh` for planning and execution.** cozyplan's `build-plan.md` workflow already is that
  loop, with a state layer, an append-only event log, and a real gate: `meta --field status --value
  built` refuses while any status marker is outside `{[x], [f]}`. A shell rewrite carries none of it.
- **Scripts alone as enforcement.** A script an agent may decline to call enforces nothing.
  Packaging changes distribution, never authority — which is why the hook, not the script, is the
  unit of work.

## Done means

An ADR, an issue, and a check that can fail. A design that produces only prose has not been done.
