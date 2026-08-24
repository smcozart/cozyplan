# cozycode → cozyplan: what step 3 found

**Audience:** the agent session working in `cozyplan-src`.
**Subject:** the placement work for `cozycode#16` is done and pushed. This reports what the
handoff got right, the three places it was wrong about cozycode, and one defect in `plan_tool`
that changes a conclusion both repositories had drawn.

Everything below was verified by running it. Where something was demonstrated by a canary, the
canary is quoted.

---

## 1. The thing to fix in cozyplan: `state check`'s ADR register reads the filesystem

**Filed as `smcozart/cozyplan#4`.** This is the only item here that is cozyplan's to act on, and
it is the most consequential finding of the phase.

`plan_tool.py:2027-2028` enumerates ADRs with `adr_dir.glob("*.md")`. `render_state`
(~`:2207-2214`) builds the Registers list from the same glob. So the check validates a generated
list against the thing that generated it, and neither consults the index.

Demonstrated in cozycode, clean tree:

```
$ cat > docs/adr/0012-canary-uncommitted.md <<'X'
---
id: ADR-0012
title: Canary, uncommitted on purpose
status: accepted
date: 2026-08-24
---
X
$ plan_tool state render      # Registers now lists ADR-0012
$ plan_tool state check
OK STATE.md: consistent with git
$ git status --porcelain docs/adr/0012-canary-uncommitted.md
?? docs/adr/0012-canary-uncommitted.md
```

`OK ... consistent with git`, for a file git has never seen.

**Why this changes a conclusion, not just a line of code.** `cozycode/docs/next-session-enforcement.md`
lists defect B — `STATE.md` rendered citing ADR-0010 with no ADR file committed — as a *placement*
failure, catchable by `state check` at pre-commit. It is not. Locally the file **was** on disk,
untracked, which is exactly how it got rendered. A pre-commit `state check` would have been green
on the machine that introduced the defect, every time. It was caught in CI (run 32739779460)
because a clean clone genuinely did not have the file.

So B is defect E's shape — working tree versus repository — and it is already in the tier it
belongs in. A repository that moves `state check` to pre-commit on the strength of that reasoning
gets a gate structurally blind to the defect it was installed for. cozycode built that gate
anyway, for other reasons, and its ADR-0012 records the blind spot rather than hiding it.

Two details in the fix worth deciding rather than falling into, both in the issue:

- `render` and `check` should **not** share the enumeration. If render also switches to
  `git ls-files`, the defect becomes unrepresentable and user-written content is silently dropped.
  Rendering from disk and checking against the index is what makes the disagreement visible.
- Use `--cached` alone here, **not** `--cached --others --exclude-standard`. cozycode hit the
  mirror-image bug in its own `PortabilityTest` (it read only the index and could not see a file
  until it was committed) and fixed it with `--others`. This check wants the opposite: the
  question is "will a clone have this file", so an untracked file is precisely the failure. The
  two checks look alike and want opposite answers; that deserves a comment.

---

## 2. §1 of the handoff is wrong about the git hooks

The handoff states: *"The vendored copy is the single route: it travels with the repo, so a clone
on another machine needs no install."*

True for the **Claude hooks** — `settings.json` invokes `${CLAUDE_PROJECT_DIR}/.claude/skills/...`.
**False for the git hooks.** In cozycode:

```
$ git config cozyplan.plantool
/Volumes/dev/AI Dev/software factory/cozyplan-src/skills/cozyplan/scripts/plan_tool.py
$ git config cozyplan.runner
uv
```

The git hooks execute a `plan_tool` **outside the workspace**, from this very directory, via `uv`.
Byte-identical to the vendored copy today; nothing checks that. Consequences:

- It is an absolute machine-specific path in **local git config**, so `PortabilityTest` cannot see
  it on two counts: not a tracked file, and not in that repo.
- On any other machine `cozyplan.plantool` is unset, and both hooks open with
  `TOOL=$(git config ...) || exit 0` — a **silent no-op**, which is the failure mode ADR-0010 was
  written against, one level out from where cozyplan looked for it.
- `doctor`'s `git hooks` row passes regardless: it reads `core.hooksPath` and counts files. It
  never runs one. A record, and it is not labelled as one the way `hooks registered` is.

**Suggestion for cozyplan, not a demand:** `hooks git-install` could prefer a repo-relative
vendored path when one exists, and `doctor` could report *which* `plan_tool` the git hooks would
actually execute, flagging one outside the worktree. Two `plan_tool` binaries answering "is this
repo healthy" on one machine is the shape of a drift defect waiting to happen.

cozycode's new `.githooks/pre-commit` deliberately ignores `cozyplan.plantool` and resolves the
vendored copy from `git rev-parse --show-toplevel`.

---

## 3. §4's structural observation: mostly right, one claim wrong, conclusion inverted

The handoff flagged §4 as unverified and asked cozycode to check it. Correct call — it does not
survive.

**The table omits `cozysites` entirely.** It is a fifth repo with its own remote and no CI. The
real count is **three of five** repositories without CI, not two of three. Of those three,
`cozyapps` is an empty placeholder and `swimschool` is a deliberately disposable test bed with no
remote, so the only one that matters is `cozysites`.

**"Two of the four studied defects live in `swimschool`" is false.** `swimschool`'s first commit
is `8391e8b`, 2026-08-24 13:55:31 — it was created during the session that read this handoff. It
can hold none of A–E by inheritance. Traced:

| Defect | Actually lived in | Evidence |
|---|---|---|
| `php -r` shell string | **reference**, `.github/workflows/fresh-clone.yml` | introduced `0ff0b38`, fixed `878317e` |
| `composer.json ^8.3` | **reference**, `composer.json` | introduced `1cccda1`, fixed `0ff0b38` |

`swimschool` has no `.github/` directory at all.

**So the conclusion inverts.** §4 reasoned that for those repos "there is no CI tier to move a
check earlier *from* — local is the only tier that exists." But three of the four studied defects
lived in `reference`, which **has** `fresh-clone.yml`. The repo holding the evidence has both
tiers, and the two-tier design was buildable and testable there immediately.

**What the grep actually found is real and better.** `^8.3` genuinely is in `swimschool/composer.json`
— not inherited, **regenerated**, because `laravel new` emits it and nothing in the new-site
procedure raises it. That is a live instance of defect D that nothing in the system could see, and
it became the phase's headline result (§4 below).

**§4's last paragraph is correct and was acted on.** cozycode had no `pre-commit`, and `pre-push`
ended `|| true; exit 0`. That is now the central finding.

---

## 4. What cozycode built, and the one number that matters

**The finding that reframed the work: there was no local tier to move anything into.** Four of five
repositories had no git hooks at all. cozycode had two, and both ended `exit 0` unconditionally.
Nothing anywhere could refuse a commit, so "move existing checks earlier" had no destination.

**Cost, measured across the workspace before anything was chosen** (macOS, arm64, median of 3):

| check | ms |
|---|---|
| `hooks selftest` | 384 |
| `state check` | 595 |
| `doctor --strict` | 860 |
| `report_drift.py` (SessionStart) | 1448 |
| full Pest suite, reference (31 tests) | ~340 |
| full Pest suite, swimschool (45 tests) | ~375 |

Nothing in the workspace exceeds 1.6s. **A site's entire Pest suite is cheaper than one
`state check`**, so the pre-commit gate runs the whole suite rather than a subset. Cost was never
the constraint; authority was.

**Built:** `.githooks/pre-commit` in cozycode (runs `state check`, exits non-zero) and in both
sites (runs the full suite, exits non-zero). Proved to refuse: a phantom ADR in Registers → exit 1;
an em-dash in visible copy → exit 1; a PHP floor regression → exit 1; clean tree → exit 0.

**The check that can fail, born red on a defect nobody planted.** A `PortabilityTest` assertion
comparing `composer.json`'s declared PHP floor against every `require.php` in `composer.lock`. It
passed in `reference` (corrected by hand long before) and went **red the moment it was copied to
`swimschool`**: fourteen symfony packages demanding 8.4.1 against a manifest promising 8.3. That is
the phase's clearest lesson and it generalises past this workspace: **a fix that never becomes a
check applies to one repository once.**

**ADR-0012** records the rule the measurements support — *a check belongs in the tier where its
question can be answered* — and answers the open bypass question directly: `--no-verify` is
accepted, **unmitigated**. It costs under a second, so bypassing it is never justified by time;
where CI exists it re-runs the question; where CI does not, the answer is CI for those repos, not
a cleverer hook. Detecting bypasses would be apparatus guarding apparatus.

**This does not diverge from cozyplan's ADR-0004.** cozyplan's hooks still advise. ADR-0012
governs cozycode's placement of cozycode's own checks, and says one thing ADR-0004 does not reach:
for a repository with no CI, an advisory local tier is not a weaker gate, it is no gate.

---

## 5. Smaller observations, no action requested

- **`scan_drift`'s `DENYLIST` has never executed in cozycode.** It is reachable only via
  `cmd_index`, which is gated on `specs/*.html`, and cozycode has no `specs/`. The OpenRouter guard
  both repositories cite as a live protection has never run there.
- **Three of six `state-check.yml` steps are inert in cozycode** — `Test suite`, `Plans validate`
  and `Generated files are current` are gated on `hashFiles()` for `tests/` or `specs/`, neither of
  which exists. The workflow's real surface is: locate, `doctor --strict`, `state check`.
- **`doctor --strict` in CI is strictly weaker than the local SessionStart run.** On a runner,
  `identity`, `hooks registered`, `hooks observed`, `git hooks` and `vendored skills` all degrade
  to WARN by design, leaving only rows the local run already covers. The CI copy adds nothing.
- **`doctor`'s `ci workflow` row is a grep**, passing if any workflow file contains the string
  "state check". A syntactically broken or never-green workflow passes it. Consider labelling it a
  record the way `hooks registered` is.
- **`state check` never re-executes a proof.** It verifies claims are well-formed and cite real
  SHAs. cozycode currently carries 27 `proved N commits ago` notes and 7 `claim's own code changed`
  warnings, all non-fatal, with `--max-claim-age 50` and no `--max-drift`. Working as designed;
  worth knowing the ledger can drift a long way while green.
- **`hooks selftest` is wired into nothing.** Not in cozycode's CI, not in any hook. It is the
  best instrument in the toolkit and runs only when a human types it.
- **The plugin stays disabled in cozycode.** Verified after this work: `hooks selftest` reports
  **4/4 observed** with `cozyplan@cozyplan: false`. The vendored copy is sufficient, and
  re-enabling would restore the double-registration `c1dae1f` removed.

---

## 6. Boundary held

Nothing in `plan_tool.py` or the vendored skill tree was edited. `VENDORED.md` says re-vendor
rather than hand-patch, so the `state check` defect is filed upstream as cozyplan#4 and cozycode
carries it as a recorded gap in the meantime.

cozycode did not grow a mechanism for declaring which checks run in which tier. The handoff asked
that this be left alone until real use answers it, and one phase of real use is not enough.
