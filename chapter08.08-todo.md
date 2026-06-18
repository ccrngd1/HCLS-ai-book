# Open TODOs — Recipe 8.8: Clinical Assertion Classification

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.08-architecture.md`

- **L11** — TODO (TechWriter): Expert review A1 (HIGH). Add SQS queue between EHR event and Lambda for retry/DLQ resilience. Failed notes are silently lost without this. At 2% transient failure rate and 200 notes/hour, ~2900 notes/month dropped. Add CloudWatch alarm on DLQ depth > 0.
- **L155** — TODO (TechWriter): Expert review A2 (HIGH). Add two-tier threshold guidance: 0.70 (exclude from downstream until reviewed) and 0.85 (include with low_confidence flag, queue for review). Estimate reviewer time at 20-30s per entity. At 200 entities/day that's ~1.5 hours of reviewer time. Address whether low-confidence entities are included in downstream with caveats or excluded until reviewed.
- **L245** — TODO (TechWriter): Expert review A3 (HIGH). Conflict resolution oversimplifies clinical reality. The section-priority heuristic fails on copy-forward notes, multi-day notes, and cases where both assertions are valid for different clinical questions. Recommend: (1) retain all mentions with individual assertions rather than resolving to a single winner; (2) let downstream consumers specify resolution strategy via a conflict_resolution_strategy parameter; (3) acknowledge the heuristic is a default, not ground truth. Update pseudocode comment from "Pick the highest-priority one" to note this is a default heuristic.
- **L298** — TODO (TechWriter): Expert review S1 (HIGH). Add DynamoDB TTL on a ttl_epoch attribute aligned with institutional records retention policy (typically 7-10 years). Document that context_snippet should live in a separate restricted-access audit table (finding S2, MEDIUM), and that the needs_review queue requires role-based access control and audit logging of reviewer actions (finding S3, MEDIUM).
- **L454** — TODO (TechWriter): Verify current URL for i2b2 2010 Assertion shared task description
- **L455** — TODO (TechWriter): Verify current URL for NegEx/ConText algorithm paper (Chapman et al.)
