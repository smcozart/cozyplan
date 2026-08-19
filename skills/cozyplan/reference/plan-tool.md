# plan_tool reference

The full CLI surface, the plan metadata contract, and the install paths. Reached from `SKILL.md`; only some branches need it. `PLAN_TOOL --help` is authoritative for flags — this file carries what `--help` cannot: which region a write belongs to, and why.

## Commands

| Write | Command |
| --- | --- |
| Scaffold a fresh plan (all `data-*` anchors + metadata stamped, `status=draft`) | `PLAN_TOOL new <kebab-name> --title "…" [--owner <role>] [--specs specs]` |
| Append a correctly-numbered phase block | `PLAN_TOOL addphase <plan> --tasks <N> [--title "…"]` |
| Flip a task/phase status marker | `PLAN_TOOL status <plan> --id <id> --state idle\|wip\|x\|f [--reason "…"]` (`--reason` required for `f`) |
| Set or append a metadata field | `PLAN_TOOL meta <plan> --field <field> --value <v>` |
| Add a back/forward reference between two plans | `PLAN_TOOL ref --this <plan> --other <plan> --type back\|forward` |
| Append an amendment | `PLAN_TOOL amend <plan> --summary "…" --detail "…"` |
| Assign `data-*` anchors to a legacy plan | `PLAN_TOOL init-ids <plan>` |
| Rebuild the specs catalog + dependency graph | `PLAN_TOOL index` |
| Build the role ownership map + CODEOWNERS | `PLAN_TOOL roles build` |

| Read | Command |
| --- | --- |
| Whole-plan index — metadata, every phase/task with its marker, open `[wip]`/`[f]` items + reasons, recent events | `PLAN_TOOL brief <plan>` · `--all --specs specs` for a one-liner per plan |
| One phase in full — its tasks, their actions, its Testing Strategy | `PLAN_TOOL phase <plan> --id phase-<n>` |
| The re-entry point — first non-terminal id, or `done` | `PLAN_TOOL next <plan>` |
| Lint a plan | `PLAN_TOOL validate <plan>` |
| What is actually wired in this clone | `PLAN_TOOL doctor [--strict]` |

| State layer | Command |
| --- | --- |
| Append an event | `PLAN_TOOL state add --kind claim\|indev\|gap --what "…" [--proof "…"] [--sha X] [--paths a,b] [--weight 1-5] [--adr N] [--issue N] [--plan P] [--clear]` |
| Rebuild `STATE_FILE` from the log | `PLAN_TOOL state render [--cap N] [--origin origin/main] [--project NAME] [--dry-run] [--force]` |
| Carry a hand-authored `STATE_FILE` into the log | `PLAN_TOOL state migrate [--dry-run]` |
| Inspect the projection | `PLAN_TOOL state show [--all]` |
| Check `STATE_FILE` against git | `PLAN_TOOL state check [--max-drift N]` |
| Add the trailers this commit can prove | `PLAN_TOOL trailers --message-file <f>` · `--print` |

| Install | Command |
| --- | --- |
| Wire a whole repo (idempotent; implements `doctor`'s check list) | `PLAN_TOOL init [--git-init] [--force-hooks] [--no-claude-hooks]` |
| Claude Code hooks (needs user approval — hooks execute commands) | `PLAN_TOOL hooks install [--global]` · `hooks remove` |
| Tracked git hooks + `core.hooksPath` | `PLAN_TOOL hooks git-install [--dir .githooks]` · `hooks git-remove` |

## Metadata contract

`PLAN_TOOL new` stamps the header; the fields stay updatable across the plan's lifecycle.

- **Write-once**: `schema`, `id`, `created`. `schema` is the artifact's structural-contract version (currently `1`) — leave it as the template sets it; `PLAN_TOOL` refuses to write a plan stamped newer than it understands.
- **Single value**: `status`, `owner`, `kind`.
- **Append-only lists**: `modified`, `commits`, `agent`, `session`, `back-refs`, `forward-refs`, `provides`, `consumes`.

**`status`** is a closed vocabulary: `draft` (authored, not started) → `active` (approved / being built) → `built` (implemented, tests pass); plus `superseded` (replaced — must carry a forward ref to its successor) and `archived` (kept for history).

**`id`** is a short immutable slug set once at Create. References, event logs, and commit trailers point at it, so it survives renames — which is why history keys on it rather than the filename.

**`owner`** is the role that owns the plan (`architect`, `engineer-<component>`, `ux`); only the owner edits plan content.

**`provides`/`consumes` are the plan's impact edges.** `provides` names the contracts this plan's work will own — a route, a queue topic, an event name, a shared table; `consumes` names the ones it depends on. Record the **literal string that crosses the boundary**, never a description, so the edge stays greppable in both sides' source. `PLAN_TOOL index` aggregates them across `specs/` into the dependency graph that answers "what breaks if this changes", and flags any contract consumed but provided by nothing. Calls that stay inside one component are not edges — `find references` answers those exactly and for free. (ADR-0003)

## Gates and guarantees

A plan may only leave `draft` once every `{{}}` slot is filled, and may only reach `built` once every status marker is terminal (`[x]`/`[f]`) — `meta --field status` refuses otherwise. `--force` overrides either refusal; it requires the user's explicit sign-off on the specific gap it skips.

Every mutating command appends a one-line JSON event to `specs/<plan>.log.ndjson` (append-only, union-merged, multi-writer) and updates the human-readable HTML. Each read-modify-write op takes an exclusive `<plan>.lock`, so concurrent writers to one plan never lose data.

Record the implementing commit with `meta --field commits --value <sha>`, and tag revert points with plain `git tag`. `--role`/`--agent`/`--session` are free-text labels on the event log.

## Regions

- **CLI-owned** — metadata (`data-meta=`), status markers, amendments. Route these through `PLAN_TOOL`.
- **Free-form** — Purpose, Problem, Solution, Notes, Open Questions prose, diagrams. Edit normally.
- **Generated** — `roles/_roles.json`, `.github/CODEOWNERS`, `specs/_index.*`, `STATE.md`. Change them by rerunning the command that builds them.

**Draft authoring window.** While `status` is `draft`, the guard permits *structural* authoring via Edit — duplicating and renumbering phase/task blocks with their `data-*` anchors and markers — because Create requires it. Metadata and amendments stay CLI-only in every status. Once the plan leaves `draft`, all managed tokens are CLI-only again.

## Install paths

The `PreToolUse` guard steers raw edits of CLI-owned regions back to `PLAN_TOOL`; the `PostToolUse` hook validates after every write. Both are **advisory**: a Bash/`sed`/out-of-tool write bypasses them by design. Correctness comes from `validate`, which every op runs — not from the hook. (ADR-0004)

**Bare-skill installs** (`npx skills add`, no plugin) do not auto-register those hooks. Correctness still holds because every op self-validates. To restore edit-time steering, offer `PLAN_TOOL hooks install` — with the user's explicit approval, never silently, since hooks execute commands. It is idempotent (re-running re-points stale paths rather than duplicating entries), preserves unrelated settings, and `hooks remove` undoes it. A Claude Code restart is needed before they fire.

**Git hooks** are separate and tracked: `hooks git-install` writes `.githooks/` and sets `core.hooksPath`. `.git/hooks` is not cloned, so each clone opts in once — `doctor` reports when one has not. (ADR-0007)

**`init` does all of the above at once**, plus the records, the event log, the union-merge attribute, the CI workflow, and a `CLAUDE.md` stub. It is additive: every write is create-if-absent or append-if-missing, so it is safe on a repo that is already partly wired. It refuses to take over a `core.hooksPath` another hook manager owns, and it never renders over a hand-authored `STATE_FILE`. Steps no command can take — branch protection, `gh` auth, the origin remote, git identity — are printed as **needs a human** rather than attempted. (ADR-0004)

**`state render` will not overwrite a `STATE_FILE` it did not write.** The generated file carries a marker; a file without one was authored by hand or by a pre-3.0 cozyplan, and rendering over it would destroy every claim and gap with no error. Run `state migrate` first — it carries what it can into the log, names everything it cannot (weights, path sets, the How to Run block), and keeps the original at `STATE.md.pre-migration`. (ADR-0005)

Run `PLAN_TOOL doctor` to see which of these are actually live in this clone rather than assuming.
