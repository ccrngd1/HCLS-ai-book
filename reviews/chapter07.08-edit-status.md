# Edit Status: Recipe 7.8 - Disease Progression Modeling

**Editor:** TechEditor
**Date:** 2026-05-31
**Verdict:** COMPLETE (with deferred findings for TechWriter)

---

## Changes Applied

### Main Recipe (`chapter07.08-disease-progression-modeling.md`)

1. **A-1 (HIGH) - Treatment confounding gap:** Added explicit callout paragraph before Step 3 pseudocode stating the implementation uses observational prediction only and pointing to the Counterfactual Treatment Simulation variation. Added inline comment in Step 3 pseudocode noting treatment features are confounded.

2. **A-2 (HIGH) - Feature engineering cutoff:** Added `cutoff_date` parameter to `engineer_progression_features` pseudocode. Added CRITICAL comment about temporal leakage. Updated all feature computations to reference `cutoff_date`. Updated Step 3 to show features computed using `patient.index_date` as the cutoff.

3. **S-2 (MEDIUM) - SHAP in DynamoDB:** Added access control note in Step 5 prose before the pseudocode block.

4. **S-3 (MEDIUM) - Model artifacts as PHI-adjacent:** Added guidance to the Encryption row in Prerequisites.

5. **N-1 (MEDIUM) - VPC endpoints:** Expanded VPC row in Prerequisites to list all required endpoints (S3, DynamoDB, HealthLake, SageMaker API, SageMaker Runtime, CloudWatch Logs, KMS, STS) and noted Glue VPC connection requirement.

6. **S-4 (LOW) - CloudTrail specificity:** Expanded CloudTrail row to clarify it captures API metadata only, and recommend application-level audit logging for patient_id tracking.

7. **N-2 (LOW) - Cross-region cost:** Added same-region deployment note to VPC row.

8. **A-6 (LOW) - Retraining trigger:** Added comment in monitoring pseudocode noting the alarm can trigger Step Functions but should include manual approval.

9. **A-3 (MEDIUM) - Cache invalidation:** Added event-driven refresh note in Step 5 pseudocode and data_freshness warning guidance.

10. **S-1 (HIGH) - FHIR query scoping:** Added inline comment in Step 1 pseudocode about scoping queries to relevant LOINC codes and condition categories. Deferred full LOINC code filter implementation to TechWriter (requires domain-specific code additions).

### Python Companion (`chapter07.08-python-example.md`)

1. **WARNING 1 (cutoff variable):** Moved `cutoff` definition to top of `engineer_progression_features()` function body, before the biomarker loop.

2. **WARNING 2 (confidence intervals):** Expanded comment to explicitly state intervals are illustrative placeholders with no statistical basis, and recommend `predict_survival_function` with alpha parameter or bootstrap resampling.

3. **WARNING 3 (concordance_index sign):** Expanded comment to explain the full reasoning for negation.

4. **NOTE 1 (monitoring omitted):** Added note in Step 5 section header that monitoring logic is omitted.

5. **NOTE 2 (missing biomarkers in synthetic data):** Added comment in generator explaining only eGFR, creatinine, and HbA1c are simulated.

---

## Deferred Findings (TODO markers placed)

| Finding | Severity | Location | Reason |
|---------|----------|----------|--------|
| S-1 | HIGH | Step 1 pseudocode | Requires adding specific LOINC code filters and privacy officer consultation note. Inline comment added; full implementation deferred. |
| A-5 | MEDIUM | Technology section | Requires new paragraph on eGFR race coefficient (2021 CKD-EPI) and NKF/ASN Task Force reference. New clinical content. |
| A-4 | MEDIUM | After Step 3 | Requires citing Tangri et al. KFRE benchmarks and contextualizing recipe's performance claims. New clinical content. |

---

## Editorial Checklist Results

- ✅ Grammar and mechanics: Clean
- ✅ Code formatting: All fenced blocks have language tags; inline code for service names
- ✅ Link verification: Pre-existing TODOs for unverified links preserved; no new fabricated URLs
- ✅ Header hierarchy: H1 title, H2 major sections, H3 subsections, no skipped levels
- ✅ Readability: Short paragraphs, active voice, no run-on sentences
- ✅ Voice: No documentation-voice, no em dashes, no LinkedIn-influencer tone, no announcement statements
- ✅ RECIPE-GUIDE compliance: All required sections present in correct order
- ✅ Vendor balance: ~70/30 general vs AWS-specific maintained
