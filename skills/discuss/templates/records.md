# Recording what settles

Reached from `workflows/interview.md` step 5, and from anywhere else a decision needs
writing down. Each record's location and gates live in `SKILL.md`'s Context artifacts
table; this file carries only what that table does not.

Write each record **the moment it lands**, never batched at the end — a record reconstructed from memory is worth nothing. The four artifacts, their locations, and their rules live in `SKILL.md`'s Context artifacts table; below is only what that table does not carry.

## ADRs

Sweep first, then gate. A decision is a **candidate** when it is any of:

- **architectural shape** — "the write model is event-sourced, the read model is projected into Postgres"
- **an integration pattern between components** — "Ordering and Billing talk over events, not synchronous HTTP"
- **a technology choice carrying lock-in** — database, bus, auth provider, deployment target; the ones that take a quarter to swap, not every library
- **a boundary or scope decision** — the explicit no's are as valuable as the yes's
- **a deliberate deviation from the obvious path** — "manual SQL instead of an ORM, because X." These stop the next engineer from "fixing" something that was on purpose
- **a constraint invisible in the code** — "no AWS, for compliance"; "under 200ms, per the partner contract"
- **a rejected alternative whose rejection was subtle** — otherwise someone proposes it again in six months

The list is the sweep; the three gates in `SKILL.md`'s artifact table are the filter. A candidate that clears all three gets an ADR at `docs/adr/NNNN-kebab-title.md`, where `NNNN` is one past the highest number already there (create the directory lazily on the first one).

Use the sibling `cozyplan` skill's `templates/adr.md`. Its frontmatter is what cozyplan's Track Record and Sync State workflows read, so an ADR written in any other shape is invisible to them. Fill it **terse**: one or two sentences per section. Delete an optional section that has nothing to say rather than padding it — the value is recording *that* a decision was made and *why*, not filling out headings.

## Glossary — a domain term

When a term resolves, add it to `CONTEXT.md` (create it lazily on the first term):

```md
# {Context Name}

{One or two sentences: what this context is and why it exists.}

## Language

**Order**:
{One or two sentences — what it IS, not what it does.}
_Avoid_: Purchase, transaction
```

Be opinionated: when several words mean the same thing, pick the best and list the rest under `_Avoid_`. Keep definitions tight. Include **only** terms specific to this domain — general programming concepts don't belong. `CONTEXT.md` is a glossary and **nothing else**: no implementation detail, no spec, no scratch pad.

## Stack deviation — a choice off the lane

When a decision departs from a `STACK.md` default, add one line to that file's **Deviations** section stating what and why. If it clears the three gates, write the ADR and link it from the line.

## System map — a component or a contract

When a component is **added, removed, renamed, or re-owned**, update its row in `SYSTEM.md`'s node table. When a decision creates or changes a contract that **crosses a process, repo, or network boundary** — a route, a queue topic, an event name, a shared table — add or update its row in the edge table, with the literal `Contract` string the code will use. Calls that stay inside one component are not edges; `SYSTEM.md`'s own header carries the rule.
