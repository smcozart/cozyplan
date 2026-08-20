# Interview

Interview the user in rounds until every decision the design hangs on is settled, recording what crystallizes as it happens. This is the write side of the understanding loop.

## 1. Map the design tree

Name the design on the table and map it as a **design tree**: every decision branches into the decisions that hang off it. The tree's depth is the stakes' depth:

- **Short pass** — a small feature or a contained change: the goal, stack fit against the `STACK.md` lanes, the edge cases. Usually one round. Do not manufacture ceremony where the decision is obvious.
- **Full interview** — a new system or an architectural change. Every branch of the tree gets visited before you stop.

A new-plan session gets the interview **by default**. Skipping it requires the requester to say so explicitly — do not skip on your own read of the stakes. A brownfield structural revision gets an *offer*; trivial edits (wording, a status flip) get nothing.

## 2. Work the frontier in rounds

The **frontier** is every decision that is both:

- **unblocked** — its prerequisites are settled, so you can ask it without guessing at an answer you have not heard yet; and
- **sharp** — you can state the question precisely *now*. Whether you can *answer* it is not the test.

Ask the whole frontier in one round. Then stop and wait.

Each round's answers reshape the tree: settled decisions push the frontier outward and unblock the questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a *later* round, not this one.

A frontier past about seven questions means the tree was not cut at its prerequisites. Find the upstream decision the rest hang off and ask that one alone.

### Round format

Number every question and give your recommended answer:

```
❓ **Q1** — **<question title>**: <the question, including any choices>

➡️ <your recommended answer> — <the one-line reason>
```

The number is the user's handle: it lets them answer "1 yes, 2 your call, 3 no because…" in a single pass. The recommendation makes a round cheap to answer — they react to a proposal instead of staring at a blank — and the reason is what makes it safe, because it gives them something to attack. Where you have no real basis to prefer, say so and name the axis the choice turns on rather than manufacturing a preference: a recommendation with nothing behind it anchors without informing.

Close each round with the questions you can see coming but cannot yet state sharply — one line each — so the user sees where the interview is heading and can redirect it before you walk down the wrong branch.

When a question does not land, re-pitch it: plain language, short sentences, the `CONTEXT.md` vocabulary. A round that is not understood is not answered, it is guessed at.

## 3. Facts are yours, decisions are theirs

Finding **facts** is your job, never the user's. When a frontier question needs a fact from the environment — the code, the filesystem, a config, a CLI, a running service — go get it and report what you found. Dispatch a sub-agent for anything that takes real digging. Offloading a knowable fact to the user is a failure of the interview.

Do not block on it. A running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent's report; ask the rest of the frontier now.

The **decisions** are the user's. Put each one to them and wait. An interview that answers its own questions — treating a recommendation as though it were an answer — has broken the only rule that matters here.

When a question is one the user is not positioned to answer, it is neither settled nor yours to settle. Park it: name it as an open input, name who or what can answer it, and carry on with the rest of the frontier.

## 4. What to press on

- **Stack fit.** Hold each choice against the `STACK.md` lanes and name the mismatch out loud: "this is customer-facing — why Power Apps, when the lane says React?" A default unchallenged is a default unowned.
- **Fuzzy language.** Propose a precise canonical term: "you're saying 'account' — the Customer or the User? Those are different things." When a term conflicts with an existing `CONTEXT.md` entry, call it out immediately.
- **The code's dissent.** When the user states how something works, check whether the code agrees, and surface the contradiction: "your code cancels whole Orders, but you just said partial cancellation is possible — which is right?"
- **Concrete scenarios.** Invent edge cases that force precision about where one concept ends and the next begins.

## 5. Record as it crystallizes

Write each record **the moment it lands**, batching nothing until the end — a record reconstructed from memory is worth nothing. Which artifact takes it, and the gates it must clear, are in `SKILL.md`'s Context artifacts table.

When a decision, term, deviation, or component change lands, read [`../templates/records.md`](../templates/records.md) for the shape it must take: the ADR candidate sweep, the glossary entry format, the stack Deviations line, and the `SYSTEM.md` node and edge rows.

## 6. Done

The interview is done when the frontier is empty: you recompute it and nothing comes back. Every branch of the design tree visited, every parked question named as parked, nothing left silently assumed.

Then put the shared understanding to the user and wait. **Do not act on the design and do not open the handoff until they confirm it.** On confirmation, hand off as `SKILL.md`'s Exit describes.

---

*Interview mechanics — the design tree, the frontier, rounds, the numbered question format, and the facts-versus-decisions boundary — are adapted from [Matt Pocock's `grilling` skill](https://github.com/mattpocock/skills); the ADR candidate sweep and glossary discipline from his `domain-modeling`. See ADR-0002.*
