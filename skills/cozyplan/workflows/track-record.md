# Track Record

Record a **decision** as an ADR, or file a **work item** on the issue tracker. If `STATE_FILE` is missing, run `workflows/init-state.md` first.

Per ADR-0001 cozyplan keeps no parallel tracker: features and bugs live as issues in the repo's tracker, and only decisions live as files here, because a decision has to outlive the tracker and stay readable in a clone with no network.

| Type | Where it lives | How |
|---|---|---|
| Decision (ADR) | `docs/adr/NNNN-<kebab-slug>.md` | `templates/adr.md`; status `proposed → accepted / rejected / superseded-by-ADR-NNNN / deprecated` |
| Feature · bug | The repo's issue tracker | Follow `docs/agents/issue-tracker.md`; label per `docs/agents/triage-labels.md` |

`docs/adr/` is the **same directory the sibling `discuss` skill records ADRs into** during interviews, using the same `templates/adr.md`. Before creating one, check for an existing ADR covering the decision, and take the next number across all existing files regardless of which skill wrote them.

## Record a decision

1. **Gate it.** An ADR is warranted only when the decision is hard to reverse **and** surprising without context **and** the result of a real trade-off. If any gate fails, skip it and say why.
2. **Assign the ID.** Highest existing number in `docs/adr/` + 1, zero-padded to four digits.
3. **Fill the template.** Copy `templates/adr.md` and replace every `{{PLACEHOLDER}}`. Identity from `git config user.name` / `user.email` — ask if unset. Fill terse: one or two sentences per section, and delete an optional section rather than padding it.
4. **Cross-link.** Link the ADR to its plan and to any ADR it supersedes, and add the reciprocal link on the other side.
5. **Carry it into history.** Name the ADR in the `ADR:` trailer of the commit that acts on it, so `git log --format='%(trailers:key=ADR,valueonly)' -- <path>` answers "what governs this code" later. The `commit-msg` hook adds it automatically for a staged ADR file.
6. **Ledger.** Append a state event and re-render: `PLAN_TOOL state add --kind gap|indev …` when the decision opens follow-up work, then `PLAN_TOOL state render`. The `STATE_FILE` ADR register is derived from `docs/adr/`, so it needs no hand edit.

**Completion criterion:** the ADR file exists with zero `{{}}` tokens, `PLAN_TOOL state check` exits 0, and the acting commit carries an `ADR:` trailer naming it.

## File a work item

1. **Check for a duplicate** on the tracker before opening anything.
2. **Open it** per `docs/agents/issue-tracker.md` — on GitHub, `gh issue create` with a label from `docs/agents/triage-labels.md`. Body names the plan id and any governing ADR.
3. **Link it back.** Record the issue number on the plan (`PLAN_TOOL meta <plan> --field issues --value <n>` where the field exists) and reference it as `Refs: #<n>` — or `Closes #<n>` — in the trailer of the commit that acts on it.
4. **Filing is one command either way.** `PLAN_TOOL issue file --title "…" --body "…" --label <label> --plan <id>` calls `gh` when it is installed and authenticated, and queues to `.scratch/` when it is not. Do not resurrect a file-based tracker, and do not branch on `gh` yourself. Replay a queue with `PLAN_TOOL issue replay` (add `--run` to file them; the default only lists, because filing is outward-facing and hard to undo).

**Completion criterion:** the issue exists on the tracker (or is queued in `.scratch/pending-gh.sh`), it names its plan, and the commit that acts on it carries a `Refs:` or `Closes:` trailer.

## Update a work item's status

Status lives on the tracker, not in a file — advance it there (`gh issue edit --add-label` / `gh issue close`). Only reflect it in `STATE_FILE` when the change alters the project's working state: append a `claim` event once a capability is verified with its proof, or a `gap` event when something is known broken, then re-render.

**Completion criterion:** the tracker and `STATE_FILE` agree, and `PLAN_TOOL state check` exits 0.
