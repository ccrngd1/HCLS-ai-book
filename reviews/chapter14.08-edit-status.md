# Edit Status: Recipe 14.8 - Ambulance Routing and Dispatch

**Editor:** TechEditor
**Date:** 2026-06-01
**Status:** COMPLETE

---

## Changes Applied

1. **ElastiCache IAM (S1 fix):** Replaced wildcard `elasticache:*` with security-group-based access explanation and scoped `elasticache:Connect` guidance for IAM-based auth (Redis 7.0+).

2. **Lambda provisioned concurrency (A3 fix):** Strengthened from parenthetical mention to mandatory requirement with burst sizing (3-5x average), `ProvisionedConcurrencySpilloverInvocations` metric monitoring, and zero-tolerance target.

3. **GPS conditional write (A4 fix):** Added exception handling comments in pseudocode: catch `ConditionalCheckFailedException`, discard gracefully, log at DEBUG, do not retry.

4. **VPC endpoint preference (N2 fix):** Changed Location Service access from "VPC endpoint or NAT Gateway" to "VPC endpoint (preferred; keeps all traffic within the AWS network). Use NAT Gateway only if the Location Service VPC endpoint is not available in your region."

5. **Location Service voice (V2 fix):** Paragraph now leads with architectural need ("You need road-network travel times that account for current traffic conditions") rather than product description.

6. **KMS key management (S2 fix):** Encryption row specifies customer-managed CMK with automatic annual rotation, restricted `kms:Decrypt` grants to GPS processor Lambda execution role, and separate CMK for GPS stream.

## Editorial Checklist

- [x] Grammar and mechanics: Clean. No issues found.
- [x] Code formatting: All fenced blocks have language tags (`json`, `mermaid`). Pseudocode blocks unlabeled per convention. Inline code used consistently for service names, API calls, and metrics.
- [x] Link verification: All URLs are well-formed AWS documentation links. NEMSIS link verified. V1 TODO defers unverified academic links to TechWriter.
- [x] Header hierarchy: H1 title only, H2 major sections, H3 subsections. No skipped levels.
- [x] Readability: Short paragraphs, active voice, no run-on sentences.
- [x] Voice drift check: Zero em dashes, zero en dashes, no documentation-voice, no feature-list formatting, no announcement statements, no LinkedIn-influencer tone.
- [x] RECIPE-GUIDE compliance: All required sections present in correct order (Problem, Technology, General Architecture, AWS Implementation with Why These Services/Architecture Diagram/Prerequisites/Ingredients/Code/Expected Results, Honest Take, Variations, Related Recipes, Additional Resources, Implementation Time, Tags, Navigation).
- [x] Vendor balance: ~70/30 general vs. AWS-specific maintained. First half (Problem, Technology, General Architecture) is fully vendor-agnostic.

## Deferred Findings (TODO Markers in Recipe)

| Finding | Severity | Location (line) | Reason Deferred |
|---------|----------|-----------------|-----------------|
| A1 | HIGH | 149 | Requires new failover/degradation strategy section. Substantive content addition beyond editorial scope. |
| A2 | HIGH | 151 | Requires architectural changes (dispatcher console, auto-dispatch vs. recommendation mode). Substantive content addition. |
| N1 | MEDIUM | 169 | Requires new content on GPS device authentication and data validation. |
| S6 | MEDIUM | 225 | Requires new audit trail specification section. |
| V1 | MEDIUM | 586 | Requires link verification and academic citation research. |

## Code Review Findings Disposition

| Finding | Severity | Action |
|---------|----------|--------|
| 1 (normalize inconsistency) | WARNING | No fix needed. Functionally equivalent. |
| 2 (float accumulation) | NOTE | No fix needed. Correct behavior. |
| 3 (hospital scoring proxy) | WARNING | No fix needed. Reasonable simplification for teaching example. |
| 4 (store_dispatch_decision uncalled) | NOTE | Fixed in Python companion (commented-out call added). |
| 5 (solver infeasibility) | NOTE | No fix needed. Graceful degradation correct. |
| 6 (DynamoDB Decimal) | NOTE (positive) | No action. Correct pattern. |
| 7 (OR-Tools solver) | NOTE | No action. Correct usage. |

## Verdict

Recipe is publication-ready pending TechWriter resolution of the 5 deferred TODO markers (2 HIGH, 3 MEDIUM). All editorial fixes applied. All addressable review findings incorporated. Voice, formatting, and structure comply with STYLE-GUIDE.md and RECIPE-GUIDE.md.
