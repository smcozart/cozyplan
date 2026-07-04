# Seed Stack

First-run creation of `STACK.md` — the repo's technology defaults. Take the first path that fits:

1. **Org seed.** If an org seed file is provided or available (the plugin's `templates/stack.cozy.md`, or a file the user points at), copy it to the repo root as `STACK.md`. Then walk the entries with the user, confirming or trimming each and resolving anything the seed marked **PROPOSED — confirm**.
2. **Generic scaffold.** Otherwise, instantiate `templates/stack.md` at the repo root — the section skeleton and the entry format are already there to fill in.
3. **Interview.** Otherwise, or to fill a scaffold's gaps, interview the user section by section — Hosting, Business Logic, Frontend, Data, Identity & Access, CI/CD, Observability — and write each entry from the answers.

## The entry format is the point

Every entry MUST be **default + when-to-use lane + escape hatch** — never a bare product name. One line, one worked shape:

> **Azure Functions** — default for event-driven/API business logic; reach for Container Apps when a process is long-running.

State in that one line *why* the default is the default and *when* to leave it. A bare inventory ("Business Logic: Azure Functions") reads as law to a later reader and suppresses exactly the trade-offs the interview exists to surface; a lane with an escape hatch turns every future deviation into a recordable decision instead of a silent violation.

`STACK.md` is a **living file**: later sessions update it as the system evolves. It describes defaults; it does not enforce them.
