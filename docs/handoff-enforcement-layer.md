# Handoff: design the enforcement layer

> ## ⚠️ Superseded in part — read this first
>
> **This brief was acted on and completed.** The outcome is ADR-0010 and
> `docs/handoff-session-enforcement-layer.md`. It is kept as the record of what was believed at
> the time, so its reasoning stays legible. Three of its premises did not survive being tested.
>
> **1. "The `uv` failure is silent" is wrong** — and it is the load-bearing claim of the
> `Update 2026-08-24` section below. Shell-form hooks run under `sh -c`, so a missing `uv`
> produced `sh: uv: command not found`, exit 127, which Claude Code surfaces as
> `Failed with non-blocking status code:` on *every* matched tool call. It was loud, constant and
> non-blocking. Fixing the runner was never going to buy observability.
>
> The genuinely silent failure is different, and it is what ADR-0010 addresses: **a hook that
> exits 0 has its stderr discarded** — neither the user nor Claude sees it — and every hook
> returns 0 on every error path. So an internal failure is invisible *and identical to a hook
> that never ran*. The four probes described below are correct evidence for that, not for the
> `uv` claim they were attached to.
>
> **2. "Which hook events gate" is settled**, not open. `PreToolUse` blocks; `UserPromptSubmit`
> blocks by *erasing the user's prompt*, so it must never be used to; `PostToolUse` and
> `SessionStart` cannot block at all. Only `guard_plan_edit` can refuse anything — "test a hook by
> observing a refusal" applies to it and nothing else.
>
> **3. "Cost per commit" is measured**: `hooks selftest` 399ms, `state check` 604ms,
> `doctor --strict` 983ms. Cost was never the constraint. Authority was — four of five repos in
> that workspace had no git hooks at all.
>
> Still open from this brief: the deliberate bypass (`--no-verify` is accepted unmitigated, per
> cozycode's ADR-0012), and packaging in general.

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


### Update 2026-08-24: uv was installed, and what that proved

`uv 0.12.5` is now present on the macOS machine, so the `uv run` hooks execute there. Verified
by observing a refusal rather than an exit code: an `Edit` carrying `data-meta=` against a
`specs/*.html` path returns

```
decision: deny
reason:   This edit touches a CLI-managed region of the plan (status markers,
          metadata, or amendments). Use plan_tool instead:
```

through both routes — `uv run` and plain `python3` — with identical output.

**The instructive part is how long that took.** Three earlier attempts all returned silence and
exit 0, and every one of them reads as success:

| Probe | Result | Why |
|---|---|---|
| `Write` to `README.md` | silent, exit 0 | not a plan path |
| `Write` to `specs/x.html`, plain content | silent, exit 0 | touches no managed region |
| `Write` to `specs/x.html` that does not exist | silent, exit 0 | new-file authoring, deliberately allowed |
| `Edit` touching `data-meta=` on a plan path | **deny** | the only shape that fires |

Three consecutive false positives for "the hook works". A report after any of them would have
been wrong, and would have looked identical to a correct one.

**This is the design problem stated precisely.** `guard_plan_edit` fails open on unparseable
input, on a wrongly shaped payload, on a non-plan path, and on a new file. Each is correct
behaviour. Each is also **indistinguishable from the hook not running at all** — which is
exactly the state the machine was in an hour earlier, with `uv` absent.

So installing uv fixed one host and changed nothing about the class. The question the design has
to answer is not "is the runner present" but **"can a hook demonstrate that it ran?"** A hook
that only speaks when it refuses cannot: silence carries no information, and a reader must
already know the failure to interpret the report.

Concrete implications for this work:

- **A silent pass and an absent runner must not look the same.** Whatever mechanism is chosen —
  a heartbeat the hook emits, a recorded last-run, a self-test verb — the outcome has to be
  observable, not inferred from the absence of complaint.
- **`doctor` reads misleadingly today.** `all 4 registered` is a record about configuration, and
  `absent — plan_tool runs on plain python3, so this is fine` is true of plan_tool and false of
  the hooks, printed adjacently. Both lines are individually correct. Together they read healthy
  on a host where the hooks do not run.
- **Test a hook by observing a refusal it should make**, never by observing that it exited zero.
  Any test written the other way passes on a machine where the hook is absent entirely.

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
