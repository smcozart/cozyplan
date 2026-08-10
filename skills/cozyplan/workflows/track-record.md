# Track Record

Create or update a record in `DOCS_DIR`: a decision (ADR), a feature, or an issue. If `STATE_FILE` is missing, run `workflows/init-state.md` first.

| Type | Directory | Template | Filename | Status values |
|---|---|---|---|---|
| Decision | `docs/adr/` | `templates/adr.md` | `NNNN-<kebab-slug>.md` | proposed → accepted / rejected / superseded-by-ADR-NNNN / deprecated |
| Feature | `docs/features/` | `templates/feature.md` | `FEAT-NNN-<kebab-slug>.md` | proposed → planned → in-development → shipped / dropped |
| Issue | `docs/issues/` | `templates/issue.md` | `ISSUE-NNN-<kebab-slug>.md` | open → in-progress → fixed / wontfix / duplicate |

Decisions use the `docs/adr/NNNN-title.md` naming the Context Layer reads — the **same directory the sibling `discuss` skill records ADRs into** during interviews. Before creating one, check the directory for an existing ADR covering the decision (don't duplicate what discuss already recorded), and take the next number across all existing files regardless of which skill wrote them.

## Create

1. Classify - Decide decision / feature / issue from the `USER_PROMPT`; if genuinely ambiguous, ask.
2. Assign ID - Next number = highest existing ID in that directory + 1, zero-padded.
3. Fill Template - Copy the template and replace every `{{PLACEHOLDER}}`. Identity from `git config user.name` / `user.email`.
4. Cross-Link - Link the record to its plan and related records, and add the reciprocal link on the other side so links stay bidirectional (same rule as `workflows/update-references.md`).
5. Register - Add or refresh the record's row in `STATE_FILE`: In Development for active features/issues, the ADR index under Registers for decisions.
6. Ledger - Append a journal entry (who, what, why, refs).
7. Report - Completion criterion: record file exists with zero `{{}}` tokens, `STATE_FILE` references it, journal entry appended.

## Update Status

1. Locate the record from the `USER_PROMPT`.
2. Set frontmatter `status` to the new value and append a matching line to the record's Status History. For issues moving to `fixed`, fill the Resolution section.
3. Refresh the record's row in `STATE_FILE` (remove it from In Development when work concludes; shipped features with verified proof belong in Current Working State).
4. Append a journal entry.
5. Report - Completion criterion: frontmatter, Status History, `STATE_FILE`, and journal all agree on the new status.
