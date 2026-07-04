---
role: {{ROLE_ID}}                        # stable id; matches plan `owner` + event-log `role` label
mission: {{ONE_LINE_MISSION}}
reports_to: {{REPORTS_TO}}                # role that reviews this role's PRs / receives escalations
github: {{GITHUB_IDENTITY}}              # @user or @org/team for CODEOWNERS; omit and this role's
                                         #   lines are emitted commented-out (never a bare @role slug)
owns:
  source_of_truth:                       # docs/plans THIS role authors and no one else edits
    - {{SOT_GLOB}}
  code:                                  # code globs this role owns
    - {{CODE_GLOB}}
  supporting:                            # docs it maintains but that are lower-stakes
    - {{SUPPORTING_GLOB}}
memory: roles/{{ROLE_ID}}/memory.md      # single-writer memory file
log: specs/*.log.ndjson                  # append-only events; `--role {{ROLE_ID}}` is a free-text attribution label
definition_of_done:                      # measurable, reviewable quality bar
  - id: {{DOD_ID}}
    check: "{{RUNNABLE_CHECK}}"          # optional runnable command (human & agent run the same)
    criteria: {{OBSERVABLE_CRITERIA}}
---

# Role: {{ROLE_DISPLAY_NAME}}

## Mission
{{2-3 sentences: what success for this role looks like at the project level}}

## Responsibilities
- {{explicit, enumerated — who is responsible for what}}

## Definition of Done
Narrative expansion of the frontmatter `definition_of_done`. Each item states the
observable/measurable signal a reviewer (human or architect-agent) checks.

## What you own / what you never touch
Owned globs (from frontmatter) in prose. Those globs compile into `.github/CODEOWNERS`,
so changes to another role's source of truth surface at PR-review time and in `git blame` —
that is where ownership is enforced, not at edit time. Shared/unowned files (README, root
configs) go through architect review before changing.

## Report-back protocol
How you deliver work to {{REPORTS_TO}}: open a PR against the branch they review (CODEOWNERS
routes it to them), with a clear summary, the plan `id`, and the commit SHAs. Blocking issues
and scope questions go to {{REPORTS_TO}} the same way — as a PR comment or an escalation.

## Session bootstrap
1. Read the planf3 `SKILL.md` (plugin-supplied — no `.claude/skills/` path).
2. Read this file ({{ROLE_ID}}).
3. Open `specs/_index.html` filtered to owner={{ROLE_ID}} and your active plan.
4. Read `roles/{{ROLE_ID}}/memory.md`.
5. Tail your plan's `specs/<plan>.log.ndjson` for recent status/events.
6. Pass `--role {{ROLE_ID}}` on `plan_tool` commands so your events are attributed in the log.

## Escalation
Stop and hand the decision to {{REPORTS_TO}} for: scope changes, cross-component
interface changes that affect other roles, or ambiguity in the plan.
