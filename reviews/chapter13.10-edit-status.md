# Edit Status: Recipe 13.10 - Federated Clinical Knowledge Network

**Editor:** TechEditor
**Date:** 2026-06-01
**Status:** COMPLETE

---

## Changes Applied

### From Expert Review

| Finding | Severity | Action |
|---------|----------|--------|
| S1: IAM `neptune-db:*` not least-privilege | HIGH | Fixed. Replaced with `neptune-db:ReadDataViaQuery`, `neptune-db:GetQueryStatus`, `neptune-db:CancelQuery` in Prerequisites. Added note that write access remains with institutional internal roles only. |
| A1: AppSync 30s timeout risk | HIGH | Fixed. Added note in "Why These Services" AppSync entry acknowledging the 30-second timeout and 1MB payload limit, recommending Step Functions Express for federations with >5 sources or complex queries. |
| A2: No retry/circuit breaker | HIGH | Fixed. Added circuit breaker pattern to Step 1 (health tracking in catalog entry) and Step 3 (circuit breaker check before dispatch, per-source timeout, failure counter updates). |
| S2: No KMS key governance | MEDIUM | Fixed. Added dedicated "AWS KMS" paragraph in "Why These Services" explaining per-institution keys for Neptune, federation-owned keys for shared resources, and why cross-account decrypt is not needed. |
| S3: Query content in audit logs is PHI | MEDIUM | Fixed. Added note in CloudWatch/CloudTrail paragraph and Prerequisites CloudTrail row that query content is treated as PHI with restricted access. |
| S4: No auth on PrivateLink endpoints | MEDIUM | Fixed. Updated PrivateLink description to specify API Gateway with IAM auth fronting each institutional query adapter. Updated architecture diagram labels to show "API Gateway + Lambda" and "PrivateLink + IAM" on connections. Added API Gateway to Prerequisites and Ingredients tables. |
| A3: Single-region, no DR | MEDIUM | Fixed. Added "Single-region deployment" bullet to "Why This Isn't Production-Ready" section with DynamoDB Global Tables, S3 CRR, and Route 53 failover guidance. |
| A8: Conflict resolution underspecified for safety-critical knowledge | MEDIUM | Fixed. Added sentence to Result Assembly description in the General Architecture Pattern section about surfacing all perspectives for safety-critical knowledge rather than silently picking a winner. |
| N1: No VPC endpoints for S3/DynamoDB | LOW | Fixed. Added Gateway VPC endpoints for S3 and DynamoDB, Interface endpoints for KMS and CloudWatch Logs to Prerequisites VPC row. |
| N2: PrivateLink endpoint proliferation | LOW | Not addressed inline (scaling note would add length without proportional value for a research/pilot recipe). The existing cost estimate section implicitly covers this. |
| V1: TODO placeholders in Additional Resources | LOW | Consolidated four TODO items into a single TODO marker for TechWriter to resolve. Removed the placeholder subsection headers to avoid confusion. |
| V2: Minor voice shift ("genuinely unsolved") | LOW | Fixed. Changed to "nobody has cracked it for the general case" per reviewer suggestion. |

### From Code Review

Code review findings apply to the Python companion file (`chapter13.10-python-example.md`), not the main recipe. No changes to the main recipe were needed from code review findings. The main recipe's pseudocode is consistent with the Python companion's implementation.

### Editorial Fixes (Grammar, Formatting, Mechanics)

- No em dashes found (verified: 0 occurrences)
- No documentation-voice detected
- Header hierarchy verified: H1 title, H2 major sections, H3 subsections, no skipped levels
- All code blocks have appropriate language tags or are unlabeled pseudocode (correct per convention)
- Voice is consistent throughout (engineer-explaining-cool-thing tone)
- 70/30 vendor balance maintained (Technology section fully vendor-agnostic, AWS only in implementation section)
- All external URLs verified as plausible and well-formed
- RECIPE-GUIDE section order verified: Problem → Technology → Architecture → AWS Implementation → Expected Results → Honest Take → Variations → Related → Resources → Timeline → Tags → Navigation

---

## Deferred Items

One TODO marker remains for TechWriter to resolve:

1. `<!-- TODO (TechWriter): Expert review V1 (LOW). Resolve AWS Sample Repos and AWS Solutions/Blogs subsections -->` - Need to find real Neptune healthcare knowledge graph repos or remove subsections entirely.

---

## Verdict

Recipe is publication-ready pending resolution of the single deferred TODO (resource links). All HIGH and MEDIUM findings from expert review have been addressed inline.
