# Edit Status: Recipe 14.8 - Ambulance Routing and Dispatch

**Editor:** TechEditor
**Date:** 2026-06-01
**Status:** COMPLETE

---

## Changes Applied

1. **Encryption row (S2 partial fix):** Added "and authorized administrative principals" and "Use a separate CMK for the GPS stream to enable independent access control" to strengthen the KMS key management guidance per expert review S2.

2. **Blank line fix:** Added missing blank line between the V1 TODO marker and the `### Related Concepts` heading for proper Markdown rendering.

3. **Python companion (Code review Finding 4):** Added commented-out `store_dispatch_decision(decision)` call in `dispatch_ambulance()` to make the audit trail integration point explicit for readers.

## Findings Already Addressed in Draft (No Further Action Needed)

- **S1 (HIGH):** ElastiCache IAM permission already corrected in Prerequisites table. Uses security group explanation and scoped `elasticache:Connect` guidance.
- **A3 (MEDIUM):** Lambda provisioned concurrency already strengthened to mandatory requirement with burst sizing and spillover metric guidance.
- **A4 (LOW):** Conditional write exception handling already documented in pseudocode comments.
- **N2 (LOW):** VPC endpoint already listed as preferred path with NAT Gateway as regional fallback only.
- **V2 (LOW):** Location Service paragraph already leads with architectural need rather than product description.

## Code Review Findings Addressed

- **Finding 1 (WARNING):** No fix needed. Python implementation is functionally equivalent to pseudocode. Zero-weighted terms are a code uniformity choice.
- **Finding 2 (NOTE):** No fix needed. Float accumulation is correct and the partial-credit approach is intentional.
- **Finding 3 (WARNING):** No fix needed. The simplification is reasonable for a teaching example and the overall ranking behavior is preserved.
- **Finding 4 (NOTE):** Fixed. Added commented-out `store_dispatch_decision(decision)` call in `dispatch_ambulance()`.
- **Finding 5 (NOTE):** No fix needed. Graceful degradation is correct. Expanded error messaging is a nice-to-have but not required for a teaching example.
- **Finding 6 (NOTE, positive):** No action needed. Correct DynamoDB Decimal handling confirmed.
- **Finding 7 (NOTE):** No action needed. Correct OR-Tools usage confirmed.

## Deferred Findings (TODO Markers Preserved)

| Finding | Severity | Location | Reason |
|---------|----------|----------|--------|
| A1 | HIGH | AWS Implementation section | Requires new section (failover/degradation strategy). Substantive content addition beyond editorial scope. |
| A2 | HIGH | AWS Implementation section | Requires architectural changes (dispatcher console, auto-dispatch vs. recommendation mode). Substantive content addition. |
| N1 | MEDIUM | After Kinesis paragraph | Requires new content on GPS device authentication and data validation. |
| S6 | MEDIUM | After Prerequisites table | Requires new audit trail specification section. |
| V1 | MEDIUM | Industry References | Requires link verification and academic citation research. |

## Editorial Checklist

- [x] Grammar and mechanics: Clean. No issues found.
- [x] Code formatting: All fenced blocks have language tags. Inline code used consistently for service names and API calls.
- [x] Link verification: All URLs are well-formed AWS documentation links. NEMSIS link is plausible. V1 TODO defers unverified academic links.
- [x] Header hierarchy: H1 title only, H2 major sections, H3 subsections, H4 for walkthrough. No skipped levels.
- [x] Readability: Short paragraphs, active voice, no run-on sentences.
- [x] Voice drift check: No em dashes, no documentation-voice, no feature-list formatting, no announcement statements, no LinkedIn-influencer tone.
- [x] RECIPE-GUIDE compliance: All required sections present in correct order. Python companion callout present.
- [x] Vendor balance: ~70/30 general vs. AWS-specific maintained. First half (Problem, Technology, General Architecture) is fully vendor-agnostic.

## Verdict

Recipe is publication-ready pending TechWriter resolution of the 5 deferred TODO markers (2 HIGH, 3 MEDIUM).
