# Interview

Relentlessly interview the user about the design until you reach shared understanding, walking down each branch of the decision tree and recording what crystallizes as it happens. This is the write side of the understanding loop.

## 1. Identify and scale

Name the design or idea on the table. Then scale the depth of the interview to the stakes:

- **Short pass** — a small feature or a contained change. A handful of questions: the goal, stack fit against the `STACK.md` lanes, the edge cases. Do not manufacture ceremony where the decision is obvious.
- **Full interview** — a new system or an architectural change. Walk *every* branch of the decision tree, resolving dependencies between decisions one at a time until nothing load-bearing is unexamined.

A new-plan session gets the interview **by default**. Skipping it requires the requester to say so explicitly — do not skip on your own read of the stakes. A brownfield structural revision gets an *offer*; trivial edits (wording, a status flip) get nothing.

## 2. Interview discipline

- **One question at a time.** Wait for the answer before the next. A batch of questions is bewildering and gets answered on autopilot — the opposite of thinking.
- **Recommend an answer.** Every question carries your recommended answer and a brief reason, so the user is reacting to a proposal, not staring at a blank.
- **Resolve prerequisites first.** When one decision depends on another, ask the upstream one first and say why ("this depends on whether X — so first: X?").
- **Never ask what the code can answer.** If exploring the codebase resolves the question, go read it and report what you found instead of asking. Offloading a knowable fact to the user is a failure of the interview.
- **Challenge stack fit explicitly.** Hold each choice against the `STACK.md` lanes and name the mismatch out loud: "this is customer-facing — why Power Apps, when the lane says React?" A default unchallenged is a default unowned.
- **Sharpen fuzzy language.** When a term is vague or overloaded, propose a precise canonical one: "you're saying 'account' — the Customer or the User? Those are different things." When a term conflicts with an existing `CONTEXT.md` entry, call it out immediately.
- **Stress-test with scenarios.** Invent concrete edge-case scenarios that force the user to be precise about the boundaries between concepts.

## 3. Capture rules

Apply these **inline, the moment something crystallizes** — never batched at the end. The record is worthless if it's reconstructed from memory after the fact.

### ADR — a decision, when all three gates pass

Write an ADR only when the decision is **hard to reverse** *and* **surprising without context** (a future reader will wonder "why on earth this way?") *and* **the result of a real trade-off** (genuine alternatives existed and you picked one for specific reasons). If any gate fails, skip it — an easy-to-reverse decision you'll just reverse, an unsurprising one nobody questions, a forced move has nothing to record.

Write to `docs/adr/NNNN-kebab-title.md`, where `NNNN` is one past the highest number already in `docs/adr/` (create the directory lazily on the first ADR). Format:

```md
# {Short title of the decision}

{1–3 sentences: the context, what you decided, and why.}
```

That's the whole thing — an ADR can be a single paragraph. The value is recording *that* a decision was made and *why*, not filling out sections. Add `Status:` frontmatter (`proposed | accepted | superseded by ADR-NNNN`), a **Considered Options** line, or a **Consequences** line only when it earns its place — most ADRs need none.

### Glossary — a domain term

When a term resolves, add it to `CONTEXT.md` (create it lazily on the first term). Format:

```md
# {Context Name}

{One or two sentences: what this context is and why it exists.}

## Language

**Order**:
{One or two sentences — what it IS, not what it does.}
_Avoid_: Purchase, transaction

**Invoice**:
A request for payment sent to a customer after delivery.
_Avoid_: Bill, payment request
```

Be opinionated: when several words mean the same thing, pick the best and list the rest under `_Avoid_`. Keep definitions tight. Include **only** terms specific to this domain — general programming concepts don't belong. `CONTEXT.md` is a glossary and **nothing else**: no implementation detail, no spec, no scratch pad.

### Stack deviation — a choice off the lane

When a decision departs from a `STACK.md` default, record it in that file's **Deviations** section, one line stating what and why. If the deviation clears the three ADR gates, write the ADR and link it from the Deviations line.

### System map — a component change

When a component is **added, removed, renamed, or re-owned**, update its one line in `SYSTEM.md`. Nothing else touches that file — it is a map of nodes, not a description of how they wire (that drifts every commit; the Orient workflow synthesizes it live).

## 4. Exit

Close by summarizing the resolved decisions as **locked inputs** — the interview is done deciding; the plan does not relitigate them. Hand off to the cozyplan skill: greenfield → its Create Plan workflow, a brownfield structural revision → its Update Plan workflow. The plan links the ADRs inline in its phase and task rationale, exactly as a plan authored from a locked design session does.
