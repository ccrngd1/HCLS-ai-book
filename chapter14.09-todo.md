# Open TODOs — Recipe 14.9: Chemotherapy Scheduling

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter14.09-architecture.md`

- **L29** — TODO (TechWriter): Expert review A2 (HIGH). Add bidirectional arrow between Staff Dashboard and scheduling engine. Add paragraph describing human override mechanism: drag-and-drop reassignment, assignment locking, ad-hoc constraint addition, re-solve requests. Log all overrides with staff ID and reason. Track override frequency to identify missing model constraints. The recipe's Honest Take already advises "Allow overrides" but the architecture doesn't implement it.
- **L31** — TODO (TechWriter): Expert review A1 (HIGH). Add failover/degradation subsection. The optimization layer enhances existing scheduling; it does not replace it. Define: if batch optimizer fails by 6 AM, fall back to template-based schedule. If real-time adjuster times out (>5s), route to human scheduler queue. Staff dashboard must show current schedule regardless of optimizer availability. Alert if batch job fails or real-time latency exceeds 5s for 3+ consecutive events.
