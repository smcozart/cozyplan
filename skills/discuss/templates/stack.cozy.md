<!-- STACK.md seed — the Cozy org's Microsoft stack. Copy to a repo root as STACK.md,
     then confirm/trim each entry with the owner and resolve every PROPOSED — confirm.
     A LIVING file: sessions update it as the system evolves. It describes the
     defaults; it does NOT enforce them. Every entry is `default + lane + escape
     hatch` — never a bare product name. -->

# Stack

The org's Microsoft-centered technology defaults, each with its lane and escape hatch.

## Hosting

- **Azure** — default hosting for everything; reach elsewhere only when a workload can't run on Azure.

## Business Logic

- **Azure Functions** — default for event-driven/API business logic; reach for Container Apps when a process is long-running.

## Frontend

- **Power Apps** — default for internal CRUD and workflow UIs; escape to React when the UI is customer-facing or the design must be controlled.
- **React** — the base for customer-facing frontends.

## Data

- **Dataverse** — default for data owned by Power Platform workloads; escape to transactional SQL when the workload needs it.

## Identity & Access

- **Microsoft Entra ID** — **PROPOSED — confirm** (not specified by the owner).

## CI/CD

- **GitHub Actions or Azure DevOps** — **PROPOSED — confirm** (not specified by the owner).

## Observability

- **Microsoft Fabric** — default for analytics and BI.

## Deviations

Choices that departed from a default above — one line each, stating what and why. A deviation that clears the three ADR gates (hard to reverse **and** surprising without context **and** the result of a real trade-off) gets an ADR in `docs/adr/`, linked from its line here.

- {Component} uses {choice} instead of the {section} default because {why}. — `docs/adr/NNNN-...`
