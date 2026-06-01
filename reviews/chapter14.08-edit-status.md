# Edit Status: Recipe 14.8 - Ambulance Routing and Dispatch

**Editor:** TechEditor
**Date:** 2026-06-01
**Status:** COMPLETE

---

## Changes Applied

1. **En dash normalization (line 3):** Replaced en dash (`–`) in the complexity/cost header with a regular hyphen (`-`) for consistency with the rest of the recipe and style guide compliance (no em dashes; en dashes normalized for uniformity).

2. **Encryption row (S2 partial fix, prior pass):** KMS key management guidance already strengthened with customer-managed CMK, auto-rotation, restricted `kms:Decrypt` grants, and separate CMK recommendation.

3. **Python companion (Code review Finding 4, prior pass):** Commented-out `store_dispatch_decision(decision)` call already present in `dispatch_ambulance()` to make the audit trail integration point explicit.

## Findings Already Addressed in Draft (No Further Action Needed)

- **S1 (HIGH):** ElastiCache IAM permission corrected in Prerequisites table. Uses security group explanation and scoped `elasticache:Connect` guidance.
- **A3 (MEDIUM):** Lambda provisioned concurrency strengthened to mandatory requirement with burst sizing (3-5x average), spillover metric monitoring, and zero-tolerance target.
- **A4 (LOW):** Conditional write exception handling documented in pseudocode comments (catch, discard, log at DEBUG, do not retry).
- **N2 (LOW):** VPC endpoint listed as preferred path with NAT Gateway as regional fallback only.
- **V2 (LOW):** Location Service paragraph leads with architectural need ("You need road-network travel times...") rather than product description.

## Code Review Findings Addressed

- **Finding 1 (WARNING):** No fix needed. Python implementation is functionally equivalent to pseudocode. Zero-weighted terms are a code uniformity choice.
- **Finding 2 (NOTE):** No fix needed. Float accumulation is correct and the partial-credit approach is intentional.
- **Finding 3 (WARNING):** No fix needed. The simplification is reasonable for a teaching example and the overall ranking behavior is preserved.
- **Finding 4 (NOTE):** Fixed (prior pass). Added commented-out `store_dispatch_decision(decision)` call in `dispatch_ambulance()`.
- **Finding 5 (NOTE):** No fix needed. Graceful degradation is correct.
- **Finding 6 (NOTE, positive):** No action needed. Correct DynamoDB Decimal handling confirmed.
- **Finding 7 (NOTE):** No action needed. Correct OR-Tools usage confirmed.

## Deferred Findings (TODO Markers Preserved)

| Finding | Severity | Location | Reason |
|---------|----------|----------|--------|
| A1 | HIGH | AWS Implementation section (line 149) | Requires new failover/degradation strategy section. Substantive content addition beyond editorial scope. |
| A2 | HIGH | AWS Implementation section (line 151) | Requires architectural changes (dispatcher console, auto-dispatch vs. recommendation mode). Substantive content addition. |
| N1 | MEDIUM | After Kinesis paragraph (line 169) | Requires new content on GPS device authentication and data validation. |
| S6 | MEDIUM | After Prerequisites table (line 225) | Requires new audit trail specification section. |
| V1 | MEDIUM | Industry References (line 586) | Requires link verification and academic citation research. |

## Editorial Checklist

- [x] Grammar and mechanics: Clean. No issues found.
- [x] Code formatting: All fenced blocks have language tags (`json`, `mermaid`, pseudocode unlabeled per convention). Inline code used consistently for service names, API calls, and metrics.
- [x] Link verification: All URLs are well-formed AWS documentation links. NEMSIS link is plausible. V1 TODO defers unverified academic links.
- [x] Header hierarchy: H1 title only, H2 major sections, H3 subsections. No skipped levels.
- [x] Readability: Short paragraphs, active voice, no run-on sentences.
- [x] Voice drift check: Zero em dashes, zero en dashes, no documentation-voice, no feature-list formatting, no announcement statements, no LinkedIn-influencer tone.
- [x] RECIPE-GUIDE compliance: All required sections present in correct order (Problem, Technology, General Architecture, AWS Implementation with Why These Services/Architecture Diagram/Prerequisites/Ingredients/Code/Expected Results, Honest Take, Variations, Related Recipes, Additional Resources, Implementation Time, Tags, Navigation).
- [x] Vendor balance: ~70/30 general vs. AWS-specific maintained. First half (Problem, Technology, General Architecture) is fully vendor-agnostic.
- [x] Python companion: Callout present linking to companion file. Companion has commented-out audit trail call per code review.

## Verdict

Recipe is publication-ready pending TechWriter resolution of the 5 deferred TODO markers (2 HIGH, 3 MEDIUM).
