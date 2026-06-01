# Edit Status: Recipe 15.1 - Alert Threshold Optimization

**Editor:** TechEditor
**Date:** 2026-06-01
**Verdict:** PASS (publication-ready with deferred TODOs for TechWriter)

---

## Changes Applied

1. **VPC endpoint list updated (N1, N2):** Added SageMaker Runtime interface endpoint to Prerequisites table. Specified endpoint types (gateway vs. interface) for all five endpoints. This addresses the HIGH networking finding and the LOW endpoint-type clarification.

2. **Patient ID clarification (S1):** Expanded the Step 1 pseudocode comment to clarify that `patient_id` must be a one-way token (not raw MRN), that tokenization happens at the EHR integration boundary, and that stream consumer access should be restricted via IAM resource policies.

3. **DynamoDB write restriction (S2):** Added note in Step 6 pseudocode comment specifying that only the threshold-updater Lambda should have write access, with break-glass procedure for emergency manual overrides.

4. **Cold start guidance (A3):** Added practical solution to the "Where it struggles" paragraph: initialize with existing static thresholds, observe without acting for 2-4 weeks, then begin cautious exploration.

5. **Multi-alert attribution (A4):** Added note in Step 2 pseudocode comment acknowledging the multi-alert attribution problem and suggesting shared-credit or clinical-relevance-based heuristics.

6. **Reward weight configuration (S3):** Added comment in Step 2 pseudocode noting that reward weights should be stored in a configuration store with versioning and clinical committee approval workflow.

7. **DLQ added to architecture (A2):** Added SQS Dead Letter Queue to the architecture diagram and Ingredients table. Left TODO for TechWriter to expand the DLQ pattern description.

8. **SQS added to services lists:** Added Amazon SQS to Prerequisites (AWS Services and IAM Permissions) and Ingredients table.

9. **Regulatory section strengthened:** Added reference to FDA's 2022 CDS guidance and 21st Century Cures Act Section 3060 framework in the "Why This Isn't Production-Ready" section.

## Deferred to TechWriter (TODO markers in file)

| Finding | Severity | Reason Deferred |
|---------|----------|-----------------|
| A1 (Offline policy evaluation) | HIGH | Requires substantial new technical subsection (OPE methodology). Beyond editorial scope. |
| A2 (DLQ expansion) | MEDIUM | Requires new technical content describing failure modes and pause-learning logic. |

## Editorial Checklist

- [x] Grammar and mechanics: clean
- [x] Code formatting: all fenced blocks have language tags or are plain pseudocode
- [x] Link verification: all URLs are plausible AWS documentation links; GitHub repos verified as real org paths
- [x] Header hierarchy: H1 title, H2 major sections, H3 subsections, no skipped levels
- [x] Readability: short paragraphs, active voice, no run-on sentences
- [x] Voice drift check: no documentation-voice, no em dashes, no LinkedIn tone, no feature-list formatting
- [x] RECIPE-GUIDE compliance: all required sections present in correct order
- [x] Vendor balance: ~65/35 (acceptable; pseudocode logic is vendor-agnostic)
