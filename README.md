# CozyPlan — HTML-First Planning for Agentic Engineering

> **A [Mythos-class](https://www.anthropic.com/news/claude-fable-5-mythos-5) planning plugin: two skills that interrogate, write, build, and maintain every plan your agents run — and keep the "why" alive after everyone moves on.**
> Built for you, your team, and your AI agents.

<p align="center">
  <img src="images/meta-skill-v5-multiplier-grid.png" alt="One meta-skill multiplies into countless plans" width="850">
</p>

Most engineers hand planning to the model and hope. `/plan` goes into a black box, something comes out, and you review whatever you get. CozyPlan inverts that: you template your engineering once — the exact sections, the exact loops, the exact visual identity — and every plan the agent writes mirrors it, forever.

Then it does the harder thing. A plan is only worth as much as what survives after it ships, so CozyPlan carries a **state layer derived from git**: what works right now and how that was proven, why the system is shaped this way, what a change would break, and where the work left off. Not a document someone has to remember to update — a projection of history that is regenerated, checked in CI, and honest about its own gaps.

**Great planning is great engineering, and this is the skill that encodes yours.**

---

## Install

CozyPlan ships as a **Claude Code plugin**. Two commands — nothing to compile, no API key, no per-project setup:

```
/plugin marketplace add https://github.com/smcozart/cozyplan.git
/plugin install cozyplan@cozyplan
```

The plugin carries everything as one unit: **two skills** (`cozyplan`, the plan and state layer; `discuss`, the understanding loop), the deterministic `plan_tool.py` CLI, and the coherence hooks.

`plan_tool.py` is **stdlib-only Python 3.9+**. [`uv`](https://docs.astral.sh/uv/) is used when present and is not required — a plain `python3` runs everything, hooks included.

Diagrams are the one external dependency: the globally-installed `excalidraw-diagram` skill renders them locally, key-free. Without it a plan still writes; the `{{...IMAGE}}` slots stay as placeholders until you run the Diagram Generation subworkflow.

### Or: install as bare skills (npx)

Both skill directories are fully self-contained — the CLI and hook scripts ship inside `skills/cozyplan/scripts/`, so they travel with the skill:

```
npx skills add smcozart/cozyplan
```

Select `cozyplan` and `discuss` (recommended — it's the interview half). Two differences from the plugin install: the Claude Code hooks are **not** auto-registered, and updates come from `npx skills update`. Register them with:

```
python3 .claude/skills/cozyplan/scripts/plan_tool.py hooks install
```

`--global` registers user-wide; `hooks remove` undoes it. Idempotent, preserves your other settings, takes effect on the next restart. Skipping it is fine — every `plan_tool` operation self-validates; the hooks only add edit-time steering.

### Or: bootstrap with nothing installed

Cold start, on a machine with no cozyplan at all. Run these from inside the project you're adopting:

```bash
git clone --depth 1 https://github.com/smcozart/cozyplan.git /tmp/cozyplan
python3 /tmp/cozyplan/skills/cozyplan/scripts/plan_tool.py init --root . --vendor --repo <owner>/<name>
rm -rf /tmp/cozyplan
```

Then `git add -A && git commit`. `--vendor` copies both skills into `.claude/skills/`, which is the first place the tool looks for its own templates — so the project keeps working after the clone is deleted, and **anyone who clones your repo installs nothing at all**. The adoption wizard travels too, at `.claude/skills/cozyplan/scripts/adopt.sh`.

Vendoring pins a version per repo, which is the trade for zero-install teammates. `doctor` reports which version a repo carries and warns when someone hand-edits it; pulling a newer cozyplan means re-running the three lines and reviewing the diff.

### Wire a repo

```
python3 <plan_tool> init              # wire everything doctor checks for
python3 <plan_tool> doctor            # what is actually wired here
```

`init` is idempotent and additive — it creates only what is missing, never overwrites content, refuses to take over a `core.hooksPath` another hook manager owns, and prints the steps no command can take (branch protection, `gh` auth, the origin remote). On an existing repo it adopts rather than clobbers.

**Adopting cozyplan in a repo? Run the wizard.** `bash <plan_tool dir>/adopt.sh` walks the whole thing: prerequisites, `init --vendor`, commit, push, waiting for the first CI run, and marking the check required. It confirms before every write and before anything outward-facing, and it prints the click path when `gh` is missing or the branch already has a protection rule it would otherwise replace.

**`--vendor` makes a repo self-contained.** It copies the two skills into `.claude/skills/`, which is the first place the resolver looks, so a teammate cloning that repo installs nothing at all — the skills and `plan_tool.py` travel with the code. `doctor` then reports the vendored version and flags a hand-edited copy. `--repo owner/name` supplies the issue-tracker slug when the repo has no `origin` yet.

`doctor` is the one to run in any clone you did not wire yourself. `.git/hooks` is never cloned, so `hooks git-install` is a per-clone step — and `doctor` tells you when a clone has skipped it, rather than letting it fail silently.

**Upgrading from 2.x?** See [`docs/migrating-to-3.0.md`](docs/migrating-to-3.0.md) — `STATE.md` is generated now, and `state render` refuses to overwrite an authored one.

---

## The four questions

Everything here exists to make these answerable from a clone, by a human or an agent, months later:

| Question | Answered by |
| --- | --- |
| **How does this system work?** | `SYSTEM.md` components + `discuss`'s Orient workflow, synthesized live from the code |
| **Why was it built this way?** | `docs/adr/` — and the `ADR:` commit trailer, so `git log -- <path>` names the decisions governing any file |
| **What breaks if I change this?** | `SYSTEM.md`'s cross-boundary edge table + the `provides`/`consumes` graph across plans |
| **Where did this leave off?** | `STATE.md`, `plan_tool next`, and `git log` joined on `Plan:` / `Session:` trailers |

---

## How it works

**Plans are HTML-first.** One self-contained `.html` page per plan in `specs/` — browsable by a human, with embedded Excalidraw diagrams on a synced visual identity. `plan_tool new` scaffolds it with every `data-*` anchor stamped; you author content, never structure.

**Agents read plans indexed, not wholesale.** `plan_tool brief` renders whole-plan state in a few hundred tokens; `phase` pulls one phase; `next` returns the re-entry point. A build session costs O(current phase), not O(whole plan). Reading a plan end to end costs 4x to 7x what `brief` costs on the plans in this repo, and `next` is eight characters.

**Structured writes go through the CLI.** Status markers, metadata, and amendments are CLI-owned so they stay well-formed; prose and diagrams are edited normally. Every mutation appends to a union-merged event log and takes a lock, so concurrent writers never lose data.

**State is derived, not remembered.** `STATE.md` is *generated* from an append-only log by `plan_tool state render`. Entries are pointer trails (`plan:` `adr:` `issue:` `session:` `path:`) rather than content, so an entry carries the ids needed to decide whether to follow it, never the detail itself.

**Enforcement is layered honestly.** Local hooks *advise* — the `commit-msg` hook **injects** the trailers it can prove and never rejects, because rejection just teaches `--no-verify`. CI *enforces*. The derivation *tolerates gaps*: an untrailered commit is reported as unattributed work, never a corrupted answer.

---

## The workflows

| Workflow | Does |
| --- | --- |
| **Create Plan** | Interviews first (via `discuss`), then authors the plan, diagrams, and index entry |
| **Update Plan** | Surgical revision + amendment + reciprocal references |
| **Build Plan** | Resumes at `next`, works phase by phase, flips markers, records the implementing commit |
| **Init State** | Scaffolds the state layer in a repo |
| **Track Record** | Records a decision as an ADR, or files a work item on the issue tracker |
| **Sync State** | Reconciles the snapshot against git and the tracker |
| **Diagram Generation** | Renders and embeds the Excalidraw diagrams |

## The `discuss` skill

The understanding loop. It **interviews in rounds**: the *frontier* is every decision whose prerequisites are settled and that can be stated sharply now, and the whole frontier is asked in one numbered round with a recommended answer each. Twenty decisions cost about four rounds instead of twenty round-trips. It ends on a checkable condition — the frontier is empty — and waits for your confirmation.

What settles gets recorded as it lands: ADRs, a `CONTEXT.md` glossary, `STACK.md` deviations, and `SYSTEM.md` nodes and edges. Then it hands **locked inputs** to cozyplan's Create Plan, which does not relitigate them.

Its read side, **Orient**, narrates how the system runs today from the code and never stores the narration — a current-state description is stale the moment the next commit lands. It does repair the map when it finds a missing or dead edge.

## The state layer

```
docs/state.ndjson   append-only, union-merged event log     ← the source
STATE.md            generated, ordered by commit position   ← the view
docs/adr/           decisions, versioned, immutable         ← the why
git trailers        Plan: Phase: Refs: ADR: Verified:       ← the join
```

```bash
plan_tool init                  # wire a repo (idempotent, additive)
plan_tool state add --kind claim --what "ingest works" \
    --proof "pytest tests/ingest" --sha a1b2c3d --paths src/ingest --adr 0007
plan_tool state render          # rebuild STATE.md
plan_tool state migrate         # carry a hand-authored STATE.md into the log
plan_tool state check           # verify it against git
plan_tool doctor                # verify the wiring itself
plan_tool issue file --title "…"  # file it, or queue it when gh is away
```

`state check` is static — it never executes a proof command it read from a file. It verifies placeholders, sync-block shape, whether the recorded sha exists and is an ancestor of HEAD, drift, claim shape, and ADR-register drift in both directions. It also intersects each claim's `path:` set with what changed since that claim's anchor commit, so a claim whose own code moved gets reported while an unrelated spike stays silent.

**Ordering is commit order**, not wall clock: union merge concatenates without ordering, and same-second commits tie on timestamps. Rank comes from `git log --topo-order --reverse`.

## Keeping it honest

- `plan_tool validate` on every plan, run by every operation
- `plan_tool index` — dangling references, doc drift, and contracts consumed but provided by nothing
- `plan_tool state check` — the snapshot against git reality
- `plan_tool doctor` — the wiring, by *running* the hook interpreter rather than assuming it works
- `.github/workflows/state-check.yml` — all of the above on every PR

Marking that check **required** needs a human with repo admin. Nothing here claims otherwise.

## Folder structure

```
skills/cozyplan/
├── SKILL.md              the router
├── workflows/            one per branch, each with a checkable completion criterion
├── templates/            plan.html · journal.md · adr.md · state-check.yml
├── reference/            plan-tool.md — full CLI surface, metadata contract, install paths
└── scripts/              plan_tool.py + the four Claude Code hooks

skills/discuss/
├── SKILL.md
├── workflows/            interview · orient · seed-stack
└── templates/            system.md · stack.md

# In a project using CozyPlan:
specs/<plan>.html         the plan          specs/_index.html   generated catalog
specs/<plan>.log.ndjson   plan events       STATE.md            generated state view
docs/state.ndjson         state events      docs/adr/           decisions
docs/journal.md           narrative ledger  docs/agents/        issue tracker + label config
.githooks/                tracked git hooks
```

## Decisions

The architecture is recorded in `docs/adr/`, and the repo runs on its own baseline:

| ADR | Decision |
| --- | --- |
| 0001 | GitHub is the source of truth for work items; ADRs stay as files |
| 0002 | The interview works the design tree in rounds, not one question at a time |
| 0003 | The system map records cross-boundary contracts only |
| 0004 | Hooks advise, CI enforces, and derivation tolerates gaps |
| 0005 | State is a union-merged log projected into capped views |
| 0008 | The state view shows everything until it cannot |
| 0009 | Role ownership maps are git's job, not cozyplan's |
| 0006 | Grounding is a traversal with a declared stopping rule |
| 0007 | Git hooks are tracked and opted into per clone |

## Where it can still fail

- **Trailer coverage is earned, not given.** Backward grounding is only as complete as the trailers in history, and history predating the convention has none. `doctor` reports the fraction so a thin answer reads as thin.
- **A stale edge table is worse than none.** With nodes only, a reader knows to read the code. With a table present, they stop at it — so a *missing* edge is a confident wrong answer. The map declares itself a floor, not a ceiling.
- **Local hooks are advisory.** `--no-verify` bypasses them, `.git/hooks` is not cloned, and Claude Code hooks fire for one tool on one machine. CI is the only layer a contributor cannot route around.
- **Branch protection is invisible from a clone.** `doctor` says so rather than implying a gate exists.
- **`state render` truncates.** It refuses to overwrite a `STATE.md` without the generated marker, because the users at risk are exactly those who do not know the semantics changed. `state migrate` is the way across, and it names everything it could not carry.

---

## Origins & credits

CozyPlan is derived from **planf3** by [IndyDevDan](https://www.youtube.com/@indydevdan), released under the MIT license. The HTML-first plan philosophy, the original template and workflow set, and the deterministic-CLI approach all trace back to his work — CozyPlan carries that foundation forward under new maintenance.

- 📺 [Planf3 on YouTube](https://youtu.be/DzbqeO_diOQ) — IndyDevDan's full breakdown of the original codebase
- Learn tactical agentic coding patterns with [Tactical Agentic Coding](https://agenticengineer.com/tactical-agentic-coding?y=planf3)
- Follow the [IndyDevDan YouTube channel](https://www.youtube.com/@indydevdan) to improve your agentic coding advantage

> *"Stay Focused and Keep Building"* — IndyDevDan

The interview mechanics in `discuss` — the design tree, the frontier, rounds, and the numbered question format — are adapted from [Matt Pocock's `grilling` skill](https://github.com/mattpocock/skills), with the ADR candidate sweep and glossary discipline from his `domain-modeling`. See ADR-0002.

---

## License

MIT — see [`LICENSE`](LICENSE).
