# Handoff: the enforcement layer session

**For:** a fresh cozyplan session picking this up.
**Written:** 2026-08-24, at cozyplan `757a387` — clean, pushed, CI green on all three platforms,
300 tests. Nothing is in flight and nothing is at risk.

Read `STATE.md` and `docs/adr/0010-*` first; this file is the narrative those two cannot carry.

---

## What this session was

A consuming project (cozycode) reported six defects, and asked for an **enforcement layer** —
something deciding *when* checks run. The brief was `docs/handoff-enforcement-layer.md`, and the
agreed plan was four steps, referenced by number throughout:

1. **Push and watch CI** — done.
2. **Repair the second install path** — done.
3. **Move the checks earlier** — done, *in cozycode*, by that session. It built a `pre-commit`
   that can refuse, and recorded ADR-0012: *a check belongs in the tier where its question can be
   answered*.
4. **Let a project declare its own checks** — **deliberately not started.** cozycode's reasoning,
   which I agree with: one phase of real use is not enough to reveal the shape.

Step 4 is the only step outstanding, and it should stay outstanding until real use argues for it.

---

## The one idea this session actually produced

Every defect fixed here was the same shape, and it is worth stating once because it keeps
recurring:

> **A record presented as an outcome.**

- `state check` compared the ADR register against the glob that *generates* the register.
- `doctor` printed `all 4 registered` — a fact about a config file — as if it meant "they ran".
- `hooks git-install` recorded whichever `plan_tool` happened to invoke it.
- `doctor`'s `ci workflow` row grepped YAML for a string.
- A vendored copy could not know it was stale.
- `state add --clear` printed `(cleared)` without clearing anything.
- **`hooks selftest` substituted the placeholder it was meant to observe.**
- **`init --vendor` had a guard that existed only in my prose.**

The last two are the sharpest: a check that edits or repairs its own subject cannot observe it.
Both were inside the tooling built to prevent exactly this. ADR-0010 records the rule; the two
"apparatus" cases are its second and third instance.

## Working standards adopted, and where they came from

These were earned, not chosen. Keep them.

- **Never accept exit 0 as evidence a check ran.** Four probes at `guard_plan_edit` all "passed"
  on an inert layer. Silence from a healthy hook and from an absent one are identical.
- **Mutation-test every new guard.** Reintroduce the bug; if the test does not go red, it is a
  record, not a check. Done for every fix here.
- **Prove an improved check against the old one, on the same input.** cozycode set this bar:
  `4fdc4ac` says `4/4 observed`, `0c0f2ad` says `0/4` on identical broken input. A claim that a
  check improved is worth little without the old check's answer beside it.
- **Rehearse destructive operations on a throwaway clone at the target's CURRENT head.** A
  rehearsal from an earlier HEAD is stale evidence. That caught real problems twice.
- **Quote what a command printed, or say nothing.** Four numbers I asserted about cozycode were
  wrong because nobody ran anything against cozycode. Generated prose asserting facts about a
  repo it cannot see is the same class as a stale to-do list.
- **Assert behaviour, not platform.** A test asserting exit `127` was green on macOS and Windows,
  red on Linux — `dash` uses 2. CI caught it.

---

## The repo boundary, which matters

**cozyplan owns the mechanism**: `plan_tool`, the four hooks, `run-hook.sh`, `hooks.json`,
`hooks {install,git-install,selftest}`, `doctor`, runner resolution, fail-open/fail-loud.

**cozyplan does not own, and must not grow knowledge of**, which checks a consuming project runs
or in which tier. There is deliberately no declaration mechanism — that is step 4.

I drifted across that line once, analysing cozycode's repo structure from outside it, and the
conclusion I drew was wrong in a way its own history disproved. Handing step 3 back was the
correction. **Two of the three most consequential defects fixed here were found by cozycode
running the tool rather than reading it.** The split is working; keep it.

---

## State of both repos

| | HEAD | Notes |
|---|---|---|
| cozyplan | `757a387` | clean, pushed, CI green ×3, 300 tests |
| cozycode | `db8d438` | clean, pushed, **3 commits behind** — not urgent |

cozycode being behind is normal and now self-announcing:

```
[ warn ] vendored freshness  3 commit(s) behind ... — re-vendor with `plan_tool init --root ... --vendor`
```

**The trap, if a re-vendor comes up:** the vendored `plan_tool` must never be the vendor *source*.
`init --vendor` now refuses that, but the reason is worth knowing — a vendored copy's git history
is the *consuming* repo's, so provenance would name that repo as its own upstream. Use
`git config cozyplan.source`.

---

## Open, all deliberate

Twelve gaps are recorded in `STATE.md`; these are the ones a new session should know:

- **Step 4** — projects declaring their own checks. Not started, on purpose.
- **Passive run ledger** — answers "did a hook fire during real work", as opposed to "can it".
  Needs a per-machine vs committed storage decision.
- **Three friction items from cozycode**, small and cheap: the ledger wants a byte-exact
  hand-copied timestamp; `state sync` does not exist though `STATE.md` says "Last synced";
  `pre-push` always reports "N commits behind HEAD" on a push carrying a render.
- **`enforce_admins` is off** — an admin can push past a failing `state-check`. Sean's call,
  unchanged all session.
- **Node 20 deprecation** in `actions/checkout@v4` and `setup-python@v5` — pre-existing, will
  become a hard failure eventually.

## Documents worth reading, in order

1. `docs/adr/0010-fail-open-on-the-subject-fail-loud-on-the-apparatus.md` — the decision.
2. `docs/handoff-from-cozycode-step-3.md` — what cozycode found running it, including the
   corrections to this repo's beliefs.
3. `docs/cozycode-next-steps.md` — a record now, not a task list. It went stale twice.
4. `docs/handoff-enforcement-layer.md` — the original brief. Note its `uv`-is-silent premise was
   wrong; ADR-0010 records why.

## If cozycode reports something

Take it seriously and verify it independently — it has been right every time, and once its
suggested *shape* did not cover its own repro, which was worth catching. File mechanism bugs at
`smcozart/cozyplan`. Do not fix cozycode's own checks from here.
