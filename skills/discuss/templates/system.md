<!-- SYSTEM.md — the component MAP for this repo. It records what exists, who owns
     each component, and where its "why" lives. It deliberately does NOT describe how
     components wire together or behave today — that drifts on every commit and turns
     into a lie. For the current running picture, run the discuss skill's Orient
     workflow, which synthesizes it live from the code. Update this file ONLY when a
     component is added, removed, renamed, or re-owned.

     Store nodes, synthesize edges: dependency edges, protocols, and data flow are
     OUT of this file — they belong to the code and to Orient. -->

# System

The component map. One line per component: what it's *for*, who owns it, and the ADRs/plans that explain why it exists in this shape.

| Component | Responsibility (what it's FOR) | Owner | Why (ADRs / plans) |
| --- | --- | --- | --- |
| Orders API | Accepts and tracks customer orders | orders-team | `docs/adr/0001-event-sourced-orders.md` |
