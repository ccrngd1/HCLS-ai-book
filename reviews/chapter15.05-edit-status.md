# Edit Status: Recipe 15.5 - Ventilator Weaning Protocols

**Editor:** TechEditor
**Date:** 2026-06-01
**Verdict:** PASS (publication-ready with deferred TODOs)

---

## Changes Applied

1. **IAM Permissions (S1, HIGH):** Replaced flat permission list with role-separated guidance per component (state constructor, inference, safety filter, training pipeline, logging) with resource ARN scoping. Addressed inline.

2. **Kinesis PHI retention (S4, LOW):** Added minimum retention guidance (24–48 hours) directly in the Encryption row of Prerequisites. Addressed inline.

3. **VPC endpoint enumeration (N1, MEDIUM):** Listed specific required VPC endpoints (S3 gateway, DynamoDB gateway, SageMaker Runtime, Kinesis, CloudWatch Logs, KMS interfaces) in the VPC row. Addressed inline.

4. **CloudTrail data-plane logging (S5, LOW):** Added DynamoDB Streams / CloudTrail data events guidance to the CloudTrail row. Addressed inline.

5. **Audit trail tamper protection (S2, MEDIUM):** Added prose paragraph before Step 4 pseudocode about S3 Object Lock compliance mode and immutable archive. Added `write_to_audit_archive` call in the pseudocode. Addressed inline.

6. **Episode boundary definition (A5, LOW):** Added clear episode start criteria (weaning readiness screening) in Step 5 prose. Addressed inline.

7. **Confounding paragraph tone (V3, LOW):** Softened one sentence from academic to conversational ("the core challenge of learning from observational data, and it shows up everywhere in offline RL"). Addressed inline.

8. **Minor formatting:** Normalized en dashes in "4-6 hours" to "4–6 hours" for consistency with other numeric ranges in the recipe.

## Deferred to TechWriter (TODO markers placed)

| Finding | Severity | Location | Reason for deferral |
|---------|----------|----------|---------------------|
| A1 | HIGH | After Architecture Diagram | DLQ/error handling for Kinesis-to-Lambda requires new architectural content (SQS DLQ, bisect-on-error, staleness alerting). Too substantive for editorial pass. |
| A2 | MEDIUM | The Honest Take section | Model rollback strategy (shadow traffic, production variants, rollback triggers) requires new technical content. |
| A4 | MEDIUM | The Honest Take section | Operational monitoring guidance (feature drift detection, override rate tracking) requires new technical content. |
| V2 | LOW | Additional Resources | Research paper citations need verification of DOI links. Editor cannot fabricate URLs per project rules. |

## Findings Not Applicable to Main Recipe

- S3 (de-identification for training data): Valid concern but more appropriate for a "Deployment Considerations" addendum or the Python companion's "Gap to Production" section. Not addressed.
- A3 (state construction latency): Valid architectural guidance but introducing latency budgets and caching strategy is new technical content. Not addressed; could be a future TODO.
- N2 (multi-AZ): Noted in the expert review as a production concern; recipe is correctly scoped as Research/Pilot. Not addressed.
- Code review findings (Issues 1–6): All pertain to the Python companion file, not this main recipe.

## Editorial Checklist

| Check | Status |
|-------|--------|
| Grammar and mechanics | ✅ Clean |
| Code formatting | ✅ All fenced blocks have language tags or are unlabeled pseudocode (appropriate) |
| Link verification | ✅ All AWS doc links are well-formed and plausible. PhysioNet links verified. |
| Header hierarchy | ✅ H1 title, H2 major sections, H3 subsections, no skipped levels |
| Readability | ✅ Short paragraphs, active voice, no run-on sentences |
| Voice drift | ✅ No doc-voice, no feature-list formatting, no announcements, zero em dashes, no LinkedIn tone |
| RECIPE-GUIDE compliance | ✅ All required sections present in correct order |
| Vendor balance | ✅ ~70/30 general vs AWS-specific maintained |
