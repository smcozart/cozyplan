# cozycode: what is needed now

**For:** the agent session working in `/Volumes/dev/AI Dev/cozycode`.
**Rewritten:** 2026-08-24 at cozyplan `538e3d2`, against cozycode `ee50062`.

An earlier version of this file listed four tasks. **Three are done**, and so is the defect it
opened with. Verified against the repo rather than assumed — a stale to-do list reads as work
outstanding, which is the same failure this workspace keeps correcting.

**One task remains: re-vendor.** It carries one trap, and the trap is the reason this file was
rewritten rather than deleted.

---

## The one thing left, and the trap in it

cozycode is **1 commit behind** cozyplan. `doctor` says so unprompted:

```
[ warn ] vendored freshness  1 commit(s) behind ... (vendored at 4fdc4ac)
```

That one commit is `538e3d2`, and it matters because of what was hand-repaired here.

### Why it matters

`.claude/settings.json` was repaired by hand in `c0665ca` — single quotes to double quotes on the
four hook commands. The repair is correct and the hooks work now. But cozyplan *generates* that
file, and the vendored `plan_tool` here is `4fdc4ac`, which still builds those commands with
`shlex.quote()`. Single quotes stop the shell expanding `${CLAUDE_PROJECT_DIR}`, so `sh` gets a
literal string as a filename and every hook exits 127.

So the hand-repair is load-bearing. Any regeneration from this copy undoes it.

`538e3d2` fixes two things:

1. **The generator** writes double quotes for a path holding `${...}`, single quotes otherwise.
   Both properties hold together — the placeholder expands *and* spaces in the path survive.
2. **`hooks selftest`** no longer substitutes `${CLAUDE_PROJECT_DIR}` itself. It runs the
   registered command verbatim with the variable in the environment, the way the host does.

The second matters more. The old selftest repaired the fault before looking for it and reported
`4/4 observed` while all four hooks were dead. **Your selftest still cannot see this class of
fault.** That is what re-vendoring buys.

### ⚠️ The trap: the vendored plan_tool cannot fix itself

The vendored copy is the one carrying the bug. Run `init --vendor` **with it** and it will
faithfully rewrite single quotes and undo `c0665ca`.

This is a general property of vendoring, not a one-off: **the stale copy is the one nearest to
hand, and it is the one that must not be used to perform its own upgrade.** It is also why
`doctor`'s freshness row exists — to name the drift before you reach for the stale tool.

Use cozyplan's checkout. Its path is already in this clone's git config:

```sh
SRC="$(git config cozyplan.source)"   # /Volumes/dev/AI Dev/software factory/cozyplan-src
python3 "$SRC/skills/cozyplan/scripts/plan_tool.py" doctor --root "$(pwd)" | grep "vendored freshness"
```

Confirm it says *behind* before starting.

### Doing it

```sh
git status --short                    # must be clean
python3 "$SRC/skills/cozyplan/scripts/plan_tool.py" init --root "$(pwd)" --vendor
python3 .claude/skills/cozyplan/scripts/plan_tool.py hooks selftest
```

Rehearse on a throwaway clone at the **current** HEAD first. Not an earlier one — a rehearsal
from an earlier HEAD is stale evidence, and that has produced false results twice here: once by
missing a skill added between rehearsal and run, once by running against a copy predating the fix
being rehearsed.

### Checking it

```sh
grep -c "'\${" .claude/settings.json  # must be 0 — no single-quoted placeholder
```

- `hooks selftest` → **4/4 observed**, and this time from the fixed selftest, so 4/4 means
  something for this fault
- `.claude/skills/VENDORED.md` → source commit `538e3d2` or later
- `.githooks/pre-commit` untouched — zero diff
- zero changes to `docs/`, `STATE.md`, `SYSTEM.md`, `CLAUDE.md`, `.github/`, `cozysites/`,
  `cozydesign/`, `.claude/skills/cozyreview`
- `enabledPlugins` still has `cozyplan@cozyplan: false`
- `state check` → `OK`, and the gate still **refuses** a planted defect. Prove that by observing
  a refusal, not an exit code.

**The settings.json diff should show the hand-edit becoming what the generator now writes on its
own.** If single quotes come back, the wrong `plan_tool` ran — stop and say so.

---

## Already done — recorded so this file is not read as outstanding work

- **The absolute path in `VENDORED.md`.** cozyplan put it back in `83dbbc2` after `e9d78c5`
  removed it; fixed upstream, and this repo has re-vendored past it. `grep -c "/Volumes"` on that
  file is now 0. cozyplan now records identity in the tracked marker and the machine-specific path
  in git config as `cozyplan.source`.
- **ADR-0002 covering this repo's own tracked files.** `.githooks/pre-commit` now scans
  `git ls-files --cached --others --exclude-standard`. Worth noting it also avoids `case` inside
  `$( )` and comments why — a POSIX ambiguity found the hard way while writing that gate.
- **The ADR-0012 amendment.** Recorded, with the canary that demonstrated the blind spot and what
  closed it. Amending rather than silently editing was the right call: the blind spot being found
  and honestly recorded is the part worth keeping.
- **`ci runs selftest`.** `doctor` reports **ok** here now.

---

## Push back on anything wrong here

An earlier handoff from cozyplan carried a structural claim about this repo that did not survive
contact with its history — it named a repo created *during* that session as holding defects it
could not have held, and the conclusion drawn from it inverted. That was caught because this side
checked rather than accepted.

Two of the three real defects fixed in cozyplan this session came from this repo running the tool
rather than reading it. Same standard applies to this document.
