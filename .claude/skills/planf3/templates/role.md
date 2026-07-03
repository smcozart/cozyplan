---
role: {{ROLE_ID}}                        # stable id; matches plan `owner` + event-log `role`
mission: {{ONE_LINE_MISSION}}
reports_to: {{REPORTS_TO}}                # role that receives this role's report-backs
github: {{GITHUB_IDENTITY}}              # @user or @org/team for CODEOWNERS; omit and this role's
                                         #   lines are emitted commented-out (never a bare @role slug)
# --- architect role ONLY: project-wide knobs compiled into roles/_roles.json ---
# mode: track                            # off | track | protect  — guard enforcement level:
#                                        #   off = dormant; track = log impact, no denies;
#                                        #   protect = deny cross-role source-of-truth writes
# acceptance: manual                     # manual | auto — does a `built` plan need an accept step?
owns:
  source_of_truth:                       # docs/plans THIS role authors and no one else edits
    - {{SOT_GLOB}}
  code:                                  # code globs this role owns
    - {{CODE_GLOB}}
  supporting:                            # docs it maintains but that are lower-stakes
    - {{SUPPORTING_GLOB}}
memory: roles/{{ROLE_ID}}/memory.md      # single-writer memory file
log: specs/*.log.ndjson                  # append-only events filtered to role={{ROLE_ID}}
definition_of_done:                      # measurable, reviewable quality bar
  - id: {{DOD_ID}}
    check: "{{RUNNABLE_CHECK}}"          # optional runnable command (human & agent run the same)
    criteria: {{OBSERVABLE_CRITERIA}}
report_back:
  when: [phase-complete, plan-built, blocked]
  how: "uv run scripts/plan_tool.py report <plan> --role {{ROLE_ID}} --status <s> --summary <...> --commits <sha,...>"
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
Owned globs (from frontmatter) in prose, plus the explicit boundary: never edit another
role's source of truth. Shared/unowned files (README, root configs) require architect
sign-off before changing.

## Report-back protocol
When and how you report to {{REPORTS_TO}} (the `plan_tool report` command in the
frontmatter). A good report: status, one-line summary, commit SHAs.

## Session bootstrap
1. Read `.claude/skills/planf3/SKILL.md`.
2. Read this file ({{ROLE_ID}}).
3. `export PLANF3_ROLE={{ROLE_ID}}`.
4. Open `specs/_index.html` filtered to owner={{ROLE_ID}} and your active plan; `specs/_status.html --role {{ROLE_ID}}`.
5. Read `roles/{{ROLE_ID}}/memory.md`.
6. Tail your plan's `specs/<plan>.log.ndjson` for recent reports/status.

## Escalation
Stop and hand the decision to {{REPORTS_TO}} for: scope changes, cross-component
contract changes that affect other roles, or ambiguity in the plan.
