---
id: ISSUE-{{NNN}}
title: {{ISSUE_TITLE}}
status: open
severity: {{critical / major / minor}}
created: {{ISO_DATE}}
reporter: {{USER_NAME}} <{{USER_EMAIL}}>
refs: {{PLAN_OR_RECORD_LINKS}}
---

# ISSUE-{{NNN}}: {{ISSUE_TITLE}}

## Observed

{{WHAT_HAPPENS: symptom, error output, where}}

## Expected

{{WHAT_SHOULD_HAPPEN}}

## Reproduction

```bash
{{REPRO_STEPS_OR_COMMANDS}}
```

## Resolution

{{LEAVE_AS_PENDING_UNTIL_FIXED: root cause and fix, filled when status moves to fixed}}

## Status History

<!-- append-only: never edit or remove a line; status changes add a line AND update frontmatter `status` -->
- {{ISO_DATE}} — opened by {{USER_NAME}}
