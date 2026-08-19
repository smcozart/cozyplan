# CozyPlan

The source repo for the `cozyplan` and `discuss` skills: HTML-first engineering plans in
`specs/`, authored and tracked through the `plan_tool` CLI, plus a project state layer.

The skills themselves live in `skills/`; `plan_tool.py` and its hooks are bundled inside
`skills/cozyplan/scripts/`. `tests/` covers the CLI and both hooks — run it with `pytest tests`.

`plan_tool.py` is stdlib-only (`dependencies = []`), so `uv run` and a plain `python3` both
work. Prefer `uv` when it is installed; nothing here requires it.

## Project state

Start here, in this order. Each answers a different question.

| Read | To answer |
| --- | --- |
| `STATE.md` | Where the project left off, and what is verified working right now |
| `specs/_index.html` | Which plans exist and their status — open it in a browser |
| `docs/adr/` | Why the system is built this way |
| [GitHub issues](https://github.com/smcozart/cozyplan/issues) | What is queued, in flight, or blocked |
| `docs/journal.md` | The append-only history of who changed what and why |

**Reading a plan is indexed, not wholesale.** Plans in `specs/` are self-contained HTML
meant to be opened in a browser by humans. Agents read them through the CLI instead —
`plan_tool brief <plan>` for whole-plan state, `plan_tool phase <plan> --id phase-<n>` for
one phase, `plan_tool next <plan>` for the re-entry point. Reading a plan end to end spends
tens of thousands of tokens on state `brief` already renders.

**Generated files are never hand-edited:** `specs/_index.*`, `roles/_roles.json`, and
`.github/CODEOWNERS`. Rerun the command that builds them.

**Status markers** on plan tasks are `[]` idle, `[wip]` in progress, `[x]` done, `[f]`
abandoned with a recorded reason. Only `plan_tool status` writes them.

## Agent skills

### Issue tracker

Issues live as GitHub issues in `smcozart/cozyplan`, managed with the `gh` CLI.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, each label string equal to its name.
See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root.
See `docs/agents/domain.md`.
