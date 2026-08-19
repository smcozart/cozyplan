<!-- SYSTEM.md — the component MAP for this repo. Two tables:

     NODES — what exists, who owns it, where its "why" lives.
       Update ONLY when a component is added, removed, renamed, or re-owned.

     EDGES — the contracts that cross a process, repo, or network boundary.
       Calls INSIDE one component are not edges: `find references` answers those
       exactly and for free, and a hand-copied call graph rots on every commit.
       Cross-boundary contracts are the opposite case — no tool can see them, and
       they change a few times a quarter, on changes that already get a plan and
       a review. That narrow scope IS what keeps this table honest; widening it
       is what would kill it. (ADR-0003)

     TRUST BOUNDARY — this table is a FLOOR, not a ceiling. It lists the crossings
     the project knows about. It never certifies that no others exist. Every impact
     answer is "these edges, PLUS whatever the code shows."

     For the live running picture — how things actually wire today — run the
     discuss skill's Orient workflow, which synthesizes it from the source. -->

# System

## Components

One row per component: what it is *for*, who owns it, and the ADRs or plans that explain why it exists in this shape.

| Component | Responsibility (what it's FOR) | Owner | Why (ADRs / plans) |
| --- | --- | --- | --- |
| Orders API | Accepts and tracks customer orders | orders-team | `docs/adr/0001-event-sourced-orders.md` |
| Billing Worker | Turns dispatched shipments into invoices | billing-team | `docs/adr/0003-events-not-http.md` |

## Edges

One row per cross-boundary contract. **`From` owns the contract; `To` depends on it — the arrow points at the blast radius.**

To answer *"what does changing X break?"*: filter on `From = X` and read `Breaks if`. That is the out-of-process half. For the in-repo half, run `find references` on the symbol — this table does not duplicate what the toolchain already computes.

| From | To | Kind | Contract | Breaks if | Why |
| --- | --- | --- | --- | --- | --- |
| Orders API | Billing Worker | `event` | `OrderPlaced` | the `orderId` or `total` field is removed or retyped | `docs/adr/0003-events-not-http.md` |
| Orders API | Storefront | `http` | `GET /api/orders/{id}` | the 200 body loses a field, or the route path changes | — |
| Fulfillment | Orders API | `db` | `dbo.OrderStatus` | a column is dropped or its type changes | — |
| Billing Worker | `external:Stripe` | `http` | `POST /v1/payment_intents` | Stripe versions the endpoint | — |

**Field rules**

- **`From` / `To`** — must name a row in Components, or `external:<name>` for a third party.
- **`Kind`** — one of `http` · `queue` · `event` · `db` · `file` · `config`. It carries the deploy coupling: `http` means both sides ship together or the contract is versioned; `queue` and `event` mean the consumer tolerates lag.
- **`Contract`** — the **literal string** that crosses: the route, topic, event name, table, blob path, or env var. Never a prose description. This is what makes the row checkable — an edge whose `Contract` cannot be grepped in the source of both sides is not an edge; write it as an ADR instead.
- **`Breaks if`** — one clause naming the change to `From` that breaks `To`. This is the field no tool can derive, and the reason the table exists.
- **`Why`** — optional ADR or plan link.

There is deliberately **no coupling-strength column** and **no last-verified date**. Strength is unfalsifiable and drifts; `Kind` plus `Breaks if` carry the checkable part. A date is a claim nobody re-verifies, and a stale one is indistinguishable from a fresh one to a skimming reader — freshness comes from a check that is computed, not asserted.

## Who writes this

- **Interview** (`discuss`) — a decision that creates or changes a cross-boundary contract writes its edge on the spot, alongside the ADR.
- **Build Plan** (`cozyplan`) — a build that added, removed, or changed a component or a cross-boundary contract updates its row, with `Why` pointing at the plan just built.
- **Orient** (`discuss`) — reading the code is how rot gets found. A cross-boundary contract in the source with no row here, or a `Contract` string that no longer appears anywhere, gets repaired on sight.

Each edge is owned by the owner of its `From` component — the same person a review of that contract already routes to.

## Why a missing edge is worse than a wrong one

With nodes only, a reader asked "what breaks if I change this?" *knows* they must read the code, and does. With an edge table present, they read the table and **stop**. A missing edge therefore produces a confident *"nothing else depends on this"* — and a change ships that breaks a consumer the map never listed.

That is why the trust boundary above is stated in the file rather than assumed, and why detecting **missing** edges matters more than detecting dead ones. A dead edge wastes a lookup. A missing edge is a wrong answer delivered with confidence.
