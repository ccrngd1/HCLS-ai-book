# Edit Status: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Editor:** TechEditor
**Task:** ch12-r07-edit
**Date:** 2026-06-04
**Status:** COMPLETE

---

## Changes Applied

### From Expert Review (reviews/chapter12.07-expert-review.md)

| Finding | Severity | Action |
|---------|----------|--------|
| H1 | HIGH | FIXED. Replaced `kinesisanalytics:*` wildcard with specific runtime and deployment role permissions. |
| H2 | HIGH | DEFERRED. TODO marker placed for TechWriter to add DLQ infrastructure and prose. |
| M1 | MEDIUM | FIXED. SNS encryption strengthened to "SSE-KMS (CMK), all subscribers must be BAA-covered endpoints." Added BAA subscriber note in service description. |
| M2 | MEDIUM | FIXED. Added note after Expected Results JSON clarifying pager de-identification pattern. |
| M3 | MEDIUM | PARTIALLY FIXED. Added inline comment in pseudocode Step 5 noting MAR PHI access requirements. Full Prerequisites row deferred to TechWriter. |
| M4 | MEDIUM | FIXED. Added paragraph after architecture diagram clarifying dynamic routing based on data source characteristics. |
| M5 | MEDIUM | FIXED. Added outlier clipping logic (4-sigma gate) before EMA baseline update in Step 2 pseudocode. |
| M6 | MEDIUM | DEFERRED. TODO marker placed for TechWriter to add ADT event listener description. |
| M7 | MEDIUM | DEFERRED. TODO marker placed for TechWriter to add SNS egress path controls for external endpoints. |
| M8 | MEDIUM | FIXED. First TODO resolved by softening the statistical claim and citing Churpek et al. without unverified percentages. Second TODO removed (GitHub repos are stable AWS-maintained). |
| L1 | LOW | FIXED. Added explicit no-egress restriction in VPC Prerequisites row. |
| L2 | LOW | Not addressed (cosmetic; multi-AZ is implicit in managed services). |
| L3 | LOW | No action required per expert recommendation. |

### From Code Review (reviews/chapter12.07-code-review.md)

The code review findings (W1, W2, N1-N4) apply to the Python companion file, not the main recipe. No changes needed in the main recipe for code review findings.

### Editorial Checklist

| Check | Result |
|-------|--------|
| Em dashes (U+2014) | 0 found. PASS. |
| En dashes (U+2013) | 0 found. PASS. |
| Bare code fences (no language tag) | 0 found. PASS. |
| Header hierarchy | H1 title only, H2 major sections, H3 subsections. PASS. |
| Documentation-voice | None detected. PASS. |
| Feature-list formatting | None detected. PASS. |
| Announcement statements | None detected. PASS. |
| Voice consistency | Engineer-explaining-over-lunch throughout. PASS. |
| RECIPE-GUIDE section order | All required sections present in correct order. PASS. |
| Vendor balance | ~60/40 (pseudocode placement per guide); within tolerance. PASS. |

---

## Remaining TODO Markers (3)

All deferred to TechWriter with finding IDs for follow-up tracking:

1. `H2` - Dead-letter queue for failed events (architecture + diagram change)
2. `M6` - ADT event handler for patient state lifecycle
3. `M7` - SNS egress path controls for external alert delivery
