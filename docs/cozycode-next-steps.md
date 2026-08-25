# cozycode: nothing outstanding

**For:** the agent session working in `/Volumes/dev/AI Dev/cozycode`.
**Rewritten:** 2026-08-24 at cozyplan `8ff1913`, after cozycode `db8d438`.

The re-vendor is done. Everything this file previously listed is complete, and nothing here needs
doing. It is kept as a record rather than a task list, because a stale to-do list reads as work
outstanding — which this file has now been twice.

---

## Done

- **Re-vendored** — `ee50062..db8d438`. `doctor` 22 ok / 2 warn / 0 gap, freshness current,
  `hooks selftest` 4/4 observed.
- **The absolute path** in `VENDORED.md` — gone; provenance is now portable and the machine path
  lives in `git config cozyplan.source`.
- **ADR-0002 covering cozycode's own tracked files** — `.githooks/pre-commit` scans
  `git ls-files --cached --others --exclude-standard`.
- **The ADR-0012 amendment** — recorded, with the canary and what closed it.
- **`ci runs selftest`** — `doctor` reports ok.

## What cozycode proved, which is the part worth keeping

The `538e3d2` selftest fix was verified against the old one on identical input — same repo, one
planted single-quote `settings.json`:

| plan_tool | verdict |
|---|---|
| `4fdc4ac` | `4/4 observed` — blind |
| `0c0f2ad` | `0/4 observed`, naming `exited 127` on all four |

Both answers are in cozycode's ledger as the proof. **A claim that a check improved is worth
little without the old check's answer beside it** — that is a better standard than the one this
repo had been using, and it is now the standard here too.

---

## One thing available whenever you next re-vendor

Not urgent, and nothing is at risk waiting.

`8ff1913` closes the bug cozycode found and did not fix: **`init --vendor` now refuses to run from
a vendored `plan_tool`**, before anything is written or removed.

The prose guard in the last handoff — *"the vendored copy must not perform its own upgrade"* — was
enforced by nothing. `_vendored_freshness` had one call site, `doctor`, and `cmd_init` never
consulted it. Two failures got through:

1. **Vendored tool, different root** (cozycode's repro): provenance stamped from the consuming
   repo, so `doctor` then reported upstream *unreachable* rather than wrong. The freshness row
   disabled by the act it guards against.
2. **Vendored tool, same root** (found here while reproducing the first, and worse): source and
   destination are one directory, so the `rmtree` clearing the destination deletes the source.
   21 files removed before `FileNotFoundError`.

One correction to the suggested shape, offered as a detail rather than a disagreement: refusing
"when `plan_tool` resolves inside `--root`" catches the destructive case but **not the repro that
found it** — there the source was cozycode and the root a clone, so nothing was inside anything.
The load-bearing signal is that the running tool is *itself* vendored, whatever the target. Both
conditions ship; the second is narrowed to source-inside-*destination*, because a source merely
inside the target is harmless and the broad form failed four existing tests.

---

## Four errors in the last handoff, all mine

Recorded because the class matters more than the instances: **generated text asserting numbers
about a repo nobody verified them against.** The same class as a stale to-do list.

1. *"Confirm it says `1 commit(s) behind`"* — `doctor` said **2**. A reader following the gate
   literally stops before starting.
2. *"`.githooks/pre-commit` — 52 lines"* — it is **96**. Zero diff was the real claim, and it held.
3. *"The settings.json diff should show the hand-edit becoming what the generator writes"* — the
   diff is **empty**, because the generator's output is byte-identical to the hand repair. That is
   the strongest possible confirmation, and the checklist framed it as failure.
4. The `init --root` line was truncated, missing the path and `--vendor`.

The fix is not to write more carefully. It is to quote what a command actually printed, or to say
nothing — which is the same rule this repo applies to its own checks.

## Friction cozycode reported, now recorded as gaps here

Not acted on; recorded so they are not rediscovered.

- **The ledger wants a byte-exact hand-copied timestamp.** `state check` warns until
  `docs/journal.md` carries the exact string. One typo is a permanent warn.
- **`state sync` does not exist** — but `STATE.md`'s own header says `Last synced`. It is
  `state add` + `state render`.
- **`pre-push` always says `snapshot is N commit(s) behind HEAD`** on a push carrying a render,
  because a render cannot record the sha of the commit carrying it. Structural, and it trains
  people to ignore the line.
