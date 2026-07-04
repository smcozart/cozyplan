# Orient

Read the understanding *out*: walk a reader through how the system runs today. This is the read side of the loop — synthesized live, never stored.

## 1. Read the map and records

- `SYSTEM.md` — the component roster: what exists, who owns each, and the why-links.
- `CONTEXT.md` — the vocabulary you'll narrate in.
- `STACK.md` — the technology lanes the components sit on.
- `docs/adr/` — scan the titles.

## 2. Open the whys in scope

For the components the reader cares about, open the ADRs and plans their `SYSTEM.md` lines link to. This is where the "why it's shaped this way" lives.

## 3. Read the actual code

Open the **source** of the in-scope components and derive how they wire and behave *today* — the calls they make, the data they pass, the order things happen in. The map names the nodes; the code is the only truthful source of the edges between them.

## 4. Walk the reader through it live

Narrate the picture out loud, in the project's own vocabulary: the components from the map, the connections from the code, the whys from the ADRs. Answer follow-ups by going back to the code, not to a stored description.

## Hard rule: never write the walkthrough to a file

A current-state description is a lie the moment the next commit lands — every wiring change silently invalidates it, and no one updates prose they didn't know went stale. So Orient produces a live narration and nothing durable. The map stores **nodes** (`SYSTEM.md`, updated only on add/remove/rename/re-own); the code is the source of **edges**. If you catch yourself wanting to save the walkthrough, that's the signal that the map or an ADR is missing a node or a why — record *that* instead.
