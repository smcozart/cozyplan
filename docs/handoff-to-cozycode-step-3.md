# Handoff to cozycode: the enforcement mechanism is ready, placement is yours

**Audience:** the agent session working in `/Volumes/dev/AI Dev/cozycode`.
**Subject:** what cozyplan now provides, what was settled empirically, and what cozycode must
decide. This closes the prerequisite named in `cozycode#16` and `cozycode#9`.

Read this alongside `cozycode/docs/next-session-enforcement.md`, which is the brief for the work
itself. **Where the two disagree, prefer this file for anything about the hook mechanism, and
prefer cozycode's own ADRs for anything about cozycode's structure.**

Everything below was verified by running it, not by reading code. Where something is unproven,
it says so.

---

## 1. The blocking prerequisite is resolved

`cozycode#16` is blocked by `cozycode#9` ("hooks invoke `python3`, which Windows may not
resolve"). That is fixed, and cozycode is already running the fix.

**What changed in cozyplan** (ADR-0010, *Fail open on the subject, fail loud on the apparatus*):

- Every hook launches through `skills/cozyplan/scripts/hooks/run-hook.sh`, which resolves an
  interpreter **at call time** — `python3`, `python`, `py`, then `uv` — and *probes* each for
  `>=3.9` rather than trusting `command -v`, because `command -v python3` succeeds against the
  Windows Store alias stub, which is not an interpreter.
- A hook that **cannot run at all** now says so on stderr and exits non-zero. The `PreToolUse`
  guard exits 2, so a plan write is refused rather than proceeding unchecked. `UserPromptSubmit`
  never uses exit 2, because exit 2 there erases the user's prompt instead of reporting anything.
- Subject failures are unchanged: an unreadable payload, a non-plan path, a new file, a prose
  edit — the hook still exits 0 in silence. **That is correct, and it is the trap** (see §3).

**What changed in cozycode** (commits `cd067a8`, `c1dae1f`, both pushed):

- The vendored copy was upgraded. Its registration was a bare `python3` — the original wording of
  `cozycode#9`, before it was retitled to blame the plugin manifest. Both routes carried the
  defect in different forms; the one cozycode actually used was the one first reported.
- The plugin (`cozyplan@cozyplan`) is now **disabled** in cozycode. Both routes had been
  registering the same four hooks. The vendored copy is the single route: it travels with the
  repo, so a clone on another machine needs no install.
- `.claude/skills/VENDORED.md` records `source commit: a87b570` — the first time it has held a
  real commit rather than `unknown`. Version skew is now visible.

Nothing outside `.claude/` was touched. CI was green before and after, step for step.

---

## 2. The command that answers "is the layer alive here"

```
plan_tool hooks selftest          # expect: 4/4 observed
```

It drives every hook with a payload it **must** react to, through the command the host actually
registered, and fails when any of them stays silent. `--shipped` tests the scripts before any
registration exists (what CI uses).

`plan_tool doctor` now reports two rows that are allowed to disagree:

```
[ ok ] hooks registered   a record only — all 4 listed in .claude/settings.json
[ ok ] hooks observed     4/4 produced the reaction they owe
```

A registered-but-inert layer is `ok` on the first and a `gap` on the second. Unregistered is a
`warn`, not a gap, because a CI runner registers nothing and failing `--strict` there on every
run is how a team learns to delete the flag.

**Per clone, one manual step** — `.git/hooks` is never cloned (ADR-0007):

```
plan_tool hooks git-install
plan_tool hooks selftest
```

---

## 3. Settled empirically — do not re-derive these

`next-session-enforcement.md` lists five open questions. Three are answered, with evidence.

### Which hook events can actually refuse (its "load-bearing unknown")

| Event | Can block? | Effect |
|---|---|---|
| `PreToolUse` | **yes** | blocks the tool call |
| `UserPromptSubmit` | yes | **blocks by erasing the user's prompt** — never use |
| `PostToolUse` | **no** | tool already ran; stderr shown to Claude |
| `SessionStart` | **no** | stderr shown to user only |

Consequence: of the four hooks, **only `guard_plan_edit` can refuse anything.** "Test a hook by
observing a refusal" applies to it alone; the other three are observed by the context they emit.

### Cost per commit — measured in cozycode, on this machine

| Check | Cost |
|---|---|
| `hooks selftest` | 399 ms |
| `state check` | 604 ms |
| `doctor --strict` | 983 ms |

A pre-commit running `state check` costs ~0.6s; all three ~2s. **Cost is not an obstacle to a
local gate.** This is the "three-second lint", not the "full suite".

### Fail open versus closed

Answered by ADR-0010 and stated above. Open on the subject, loud on the apparatus.

### Still genuinely open

- **Question 4, the deliberate bypass.** `--no-verify` skips git hooks silently and leaves no
  trace. If anything becomes a gate, this needs an answer before it ships, not after.
- **Question 5, packaging.** Settled *for cozycode* (vendored, plugin disabled, verified 4/4).
  Not settled in general.

### One correction worth carrying

The claim that the `uv` failure was **silent** appears in `hooks/hooks.json`'s own description,
cozyplan's README, and `cozycode#9`. It was wrong. Shell-form hooks run under `sh -c`, so a
missing `uv` produced `sh: uv: command not found`, exit 127, surfaced on *every* matched tool
call. It was loud, constant, and non-blocking.

**The genuinely silent failure is different, and it is the one to design against:** a hook that
exits 0 writes its stderr to the debug log only — Claude never sees it, and neither do you. Every
cozyplan hook returns 0 on every error path. So an internal failure is invisible, and identical
to a hook that never ran. Four probes against `guard_plan_edit` on a machine believed broken all
"passed" that way. Three of the four were correct fail-open behaviour and indistinguishable from
death.

**Therefore: never accept exit 0 as evidence a check ran.** That is ADR-0010's whole content, and
it is the same rule as cozycode's own ADR-0010 (*checks observe outcomes, not records*), applied
one level out.

---

## 4. An observation about cozycode's structure — verify before trusting it

This came from outside cozycode, without its history. **Treat it as a question, not a finding.**

`git check-ignore` and `git ls-files` report:

| Repo | tracked by cozycode | own remote | own CI |
|---|---|---|---|
| `cozycode` | — | yes | `state-check.yml` |
| `cozydesign` | 28 files | — | via cozycode CI |
| `cozysites/sites/reference` | **0** (gitignored, own repo) | yes | `fresh-clone.yml` |
| `cozysites/sites/swimschool` | **0** | **none** | **none** |
| `cozyapps` | **0** | yes | **none** |

If that is right, it has a consequence for the two-tier design: cozycode's CI cannot see the
children at all, and two of three have no CI of their own. For those, there is no "CI tier" to
move a check *earlier from* — local is the only tier that exists.

Two of the four studied defects (`php -r` shell string, `composer.json ^8.3`) live in
`swimschool`. The `tests/Unit` case lives in `reference`, which does have `fresh-clone.yml` — so
that one looks correctly placed already.

**cozycode owns this question.** The structure is deliberate (ADR-0001), and the reasons for it
are not visible from here. If the table is wrong, the conclusion drawn from it is wrong too.

Also observed: cozycode has **no `pre-commit` hook**. `.githooks/pre-push` runs `state check`,
greps for `behind HEAD|FAIL`, and ends `|| true; exit 0` — it reports and never blocks. That is
ADR-0004 working as designed, but it means the `STATE.md`-citing-an-uncommitted-ADR defect would
have been *printed* at pre-push and pushed anyway.

---

## 5. The boundary

**cozyplan owns:** the hook mechanism — `run-hook.sh`, the four hook scripts, `hooks.json`,
`plan_tool hooks {install,git-install,selftest}`, `doctor`, runner resolution, and the
fail-open/fail-loud contract. Bugs in any of that are cozyplan's to fix; file them at
`smcozart/cozyplan`.

**cozyplan does not own, and must not grow knowledge of:** which checks cozycode runs, in which
tier, for which repo. There is deliberately **no mechanism for a project to declare its checks** —
designing that is the last step, and only once the tier question is answered by real use.

**A note on posture.** Making anything *gate* is a change of stance, not a bug fix. cozyplan's
ADR-0004 holds that hooks advise and CI enforces, and ADR-0010 deliberately did **not** supersede
it — it only stopped the layer being silent about its own absence. If cozycode wants a blocking
`pre-commit`, that is cozycode's ADR to write, with question 4 (the bypass) answered. Argue it;
do not diverge from ADR-0004 quietly.

---

## 6. Done means

Unchanged from `cozycode#16`: an ADR, an issue, and **a check that can fail**. A design that
produces only prose has not been done.

For "a check that can fail", the standard `hooks selftest` had to meet is a useful bar: it was
verified against all four dead states — unregistered, registered-but-inert, missing script, and
no interpreter — and its key assertion was mutation-tested by reintroducing the bug to confirm it
goes red. A check nobody has watched fail is a record, not an outcome.
