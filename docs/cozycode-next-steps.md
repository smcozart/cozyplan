# cozycode: what is needed now

**For:** the agent session working in `/Volumes/dev/AI Dev/cozycode`.
**Written:** 2026-08-24 from the cozyplan session, at cozyplan `84ab997`.

cozyplan's two items are **done and pushed**. Everything below is cozycode's.
Background, if useful: `../software factory/cozyplan-src/docs/recommendedchanges.md`.

---

## Read this first: a defect cozyplan put in this repo

`83dbbc2` (a re-vendor run from the cozyplan session) regenerated
`.claude/skills/VENDORED.md` and **restored an absolute path** that `e9d78c5` had deliberately
removed — *"take an absolute path out of a tracked file"*. It violates this repo's ADR-0002 and
it is on `main` now.

It has been fixed upstream, so re-vendoring removes it rather than repeating it. Two things
changed in cozyplan:

- `VENDORED.md` now carries only fields that mean the same thing on every machine: `version`,
  `source commit`, `source remote`. No path.
- The local checkout path moved to this clone's **git config** as `cozyplan.source` — per-clone,
  untracked, correct exactly where it applies.

**The part worth keeping:** nothing in this repo caught either the original write or the
reinstatement. `PortabilityTest` scans only its own site (`git -C base_path() ls-files`), and this
repo's `pre-commit` runs only `state check`. **cozycode's own tracked files are checked by
nothing** — the ban is declared here and enforced only in the site repos. That is task 2.

---

## Task 1 — re-vendor

Currently **4 commits behind**. Picks up: the absolute-path fix, `plugin.json` 3.1.0 → **3.2.0**,
the `state check` index fix, `git hook tool` resolution, and the `vendored freshness` row.

```
cd "/Volumes/dev/AI Dev/cozycode"
git status --short                                    # must be clean
plan_tool doctor | grep -E "vendored freshness|ci runs selftest"
```

**Rehearse on a throwaway clone at the CURRENT HEAD first.** A rehearsal from an earlier HEAD is
stale evidence, not evidence — that has produced false results twice, once by missing a skill
added between rehearsal and run, once by running against a copy predating its own fix.

```
plan_tool init --root "/Volumes/dev/AI Dev/cozycode" --vendor
plan_tool hooks selftest                              # expect 4/4 observed
```

Then check, and treat any surprise as a stop:

- `grep -c "/Volumes" .claude/skills/VENDORED.md` → **0**
- `git config cozyplan.source` → set (this is where the path went; it is untracked, by design)
- `.claude/skills/VENDORED.md` shows `version | 3.2.0`
- `.githooks/pre-commit` untouched — 52 lines, zero diff
- zero changes to: `docs/`, `STATE.md`, `SYSTEM.md`, `CLAUDE.md`, `.github/`, `cozysites/`,
  `cozydesign/`, `.claude/skills/cozyreview`
- `settings.json` hooks semantically identical (parse and compare, do not eyeball — the CLI
  reorders keys and the raw diff looks alarming); `enabledPlugins` still has
  `cozyplan@cozyplan: false`
- `state check` → `OK`, and the gate still **refuses** a planted defect. Prove that by observing
  a refusal, not an exit code.

## Task 2 — decide whether ADR-0002 covers this repo

Your ADR-0002 bans absolute paths in tracked files. Three site repos enforce it. This one does
not check itself, which is how the defect above survived a review that was otherwise careful.

Your call, and this session should make it. Two shapes, both cheap and both consistent with
ADR-0012's rule that a check belongs where its question can be answered — this one is answerable
from the working tree, so it is the local tier:

- Add a scan of `git ls-files` for machine-specific absolute paths to this repo's `pre-commit`.
- Or accept the gap deliberately and record why. A recorded decision is a fine outcome; an
  unexamined gap is not.

Generated files are the awkward case either way: correct on the machine that generated them and
wrong everywhere else, which is exactly the class ADR-0002 exists for.

## Task 3 — amend ADR-0012

It records that a pre-commit `state check` is structurally blind to defect B — an ADR rendered
into Registers but never staged — because the file *is* on disk locally.

**That is no longer true.** `state check` now compares the register against the git index instead
of the directory that generates it (cozyplan#4). Verified in a sandbox at your HEAD: an ADR
rendered into Registers and never staged now stops the commit —

```
FAIL STATE.md: 1 problem(s)
  - Registers index lists ADR-0099, which exists in docs/adr/ but is not staged or
    committed — every clone renders a register citing a file it does not have.
    Run: git add docs/adr/0099-*.md
pre-commit: STATE.md does not agree with git.
```

The ADR's reasoning was correct when written and the gate was built for other reasons anyway.
The premise changed upstream, so it now reads as still-true when it is not. An amendment recording
what closed it is better than a silent edit — the blind spot being *found and honestly recorded*
is the part worth keeping.

## Task 4 — one line of CI

`doctor` reports:

```
[ warn ] ci runs selftest   no workflow runs `hooks selftest` ...
```

This repo's `state-check.yml` predates the selftest, and `init` leaves an existing workflow alone
by design, so it never gained the step. `hooks selftest` is the only check that proves the hook
layer actually runs; without it, nothing verifies that on a clean machine. Add:

```yaml
      - name: Hooks actually run
        run: python "${{ steps.pt.outputs.path }}" hooks selftest --shipped
```

Not exit-code theatre: it drives every hook with a payload it must react to and fails on silence.
The guard legitimately exits 0 on a non-plan path, a new file and a prose edit, so exit 0 is also
exactly what a hook that never ran produces.

---

## Push back on anything wrong here

A previous handoff from cozyplan carried a structural claim about this repo that did not survive
contact with your history — it named a repo created *during* that session as holding defects it
could not have held, and the conclusion drawn from it inverted. That was caught because this side
checked rather than accepted.

Same standard applies to this document.
