<!-- STACK.md — this repo's technology defaults. A LIVING file: sessions update it
     as the system evolves. It describes the defaults; it does NOT enforce them.
     Every entry is `default + when-to-use lane + escape hatch` — never a bare
     product name. A bare inventory reads as law and suppresses the trade-offs the
     discuss interview exists to surface. -->

# Stack

The technology defaults for this repo, each with the lane it's the default for and the escape hatch out of it.

## Hosting

- **{Product}** — default for {what}; reach for {alternative} when {condition}.

## Business Logic

- **Azure Functions** — default for event-driven/API business logic; reach for Container Apps when a process is long-running.

## Frontend

-

## Data

-

## Identity & Access

-

## CI/CD

-

## Observability

-

## Deviations

Choices that departed from a default above — one line each, stating what and why. A deviation that clears the three ADR gates (hard to reverse **and** surprising without context **and** the result of a real trade-off) gets an ADR in `docs/adr/`, linked from its line here.

- {Component} uses {choice} instead of the {section} default because {why}. — `docs/adr/NNNN-...`
