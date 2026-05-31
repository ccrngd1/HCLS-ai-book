# Edit Status: Recipe 7.9 - Mortality Risk Scoring (ICU)

**Editor:** TechEditor
**Date:** 2026-05-31
**Files Modified:** `chapter07.09-mortality-risk-scoring-icu.md`, `chapter07.09-python-example.md`

---

## Summary of Changes

### Main Recipe (`chapter07.09-mortality-risk-scoring-icu.md`)

**Expert Review Findings Addressed:**

1. **A-1 (HIGH) - Lambda timeout for complex patients:** Added guidance in the Lambda "Why These Services" paragraph about pre-aggregation for long-stay patients, maximum memory allocation, and timeout fallback. Left a TODO marker for TechWriter to consider a dedicated callout box.

2. **S-1 (MEDIUM) - Dual SageMaker endpoint calls:** Consolidated Step 3 pseudocode into a single endpoint call with `custom_attributes = "explain=true"`. Added comment about reducing attack surface.

3. **S-2 (MEDIUM) - IAM permissions lack resource ARN scoping:** Expanded Prerequisites IAM row with example resource ARN patterns and scoping guidance.

4. **S-3 (MEDIUM) - Patient-level authorization:** Added API Gateway row to Prerequisites specifying care-relationship verification requirement.

5. **N-1 (MEDIUM) - VPC endpoint list incomplete:** Expanded VPC row to include STS, KMS, and S3 Gateway endpoints with note about STS being required for Lambda role assumption.

6. **N-3 (MEDIUM) - API Gateway exposure:** Added dedicated API Gateway row specifying Private API or mutual TLS, VPN/Direct Connect access.

7. **A-2 (MEDIUM) - 4-hour rescoring limitation:** Added event-triggered rescoring mention in EventBridge "Why These Services" paragraph with forward reference to Variations. Updated "Where it struggles" bullet to note mitigation.

8. **A-3 (MEDIUM) - Separate calibration Lambda:** Added note after "Why These Services" explaining production consolidation pattern.

9. **A-4 (MEDIUM) - No DLQ:** Added SQS DLQ to architecture diagram, Ingredients table, and Prerequisites (new Error Handling row). Added freshness indicator guidance.

10. **A-5 (LOW) - Wilson interval approximation:** Added comment in Step 4 pseudocode noting alternatives (Bayesian calibration, conformal prediction).

11. **S-4 (LOW) - BAA verification:** Added HIPAA Eligible Services list verification note to BAA row.

12. **N-2 (LOW) - Security group rules:** Added security group specification to VPC row.

**Voice/Style:** Zero em dashes confirmed. No voice drift detected. Vendor balance maintained.

### Python Companion (`chapter07.09-python-example.md`)

**Code Review Findings Addressed:**

1. **ERROR 1 - SOFA renal uses liver function:** Added `SOFA_RENAL_THRESHOLDS` constant and `compute_sofa_renal()` function with correct creatinine thresholds. Updated `engineer_features()` to call the correct function.

2. **WARNING 1 - DynamoDB float rejection in nested structures:** Added `_convert_floats_to_decimal()` helper function. Updated `build_prediction_record()` to convert `top_contributors` recursively. Updated the store function comment to reflect the fix.

3. **WARNING 2 - Deprecated `use_label_encoder=False`:** Removed the parameter from `XGBClassifier` constructor (removed in XGBoost 2.0+).

4. **WARNING 3 - SHAP API comment ambiguity:** Clarified the comment explaining `shap_values[0]` indexing behavior for single-row input.

5. **WARNING 4 - Feature schema mismatch:** Added clarifying comment that the loop over-generates features and FEATURE_SCHEMA acts as a filter. Removed duplicate `map_min_6h`/`map_max_6h` computation.

6. **NOTE 1 - Calibration merged with training:** Added comment clarifying that production calibration is a separate step (main recipe Step 4) and this demo combines them for simplicity.

7. **NOTE 2 - Wilson vs Wald interval:** Corrected comment from "Wilson score interval" to "Wald interval approximation" with note about Wilson being preferred for extreme probabilities.

8. **SageMaker deployment gap:** Added note about single-call pattern for predictions + SHAP.

---

## Deferred Items

| Finding | Marker Location | Reason |
|---------|----------------|--------|
| A-1 (HIGH) | Lambda "Why These Services" paragraph | TODO left for TechWriter to consider a dedicated callout box with pre-aggregation pipeline pattern details |

---

## Checklist

- [x] Grammar and mechanics
- [x] Code formatting (language tags on fenced blocks, inline code for service names)
- [x] Link verification (all URLs plausible and well-formed)
- [x] Header hierarchy (H1 title, H2 major sections, H3 subsections, no skipped levels)
- [x] Readability (short paragraphs, active voice)
- [x] Voice drift check (zero em dashes, no documentation-voice, no feature-lists, no announcements)
- [x] RECIPE-GUIDE compliance (all required sections present in correct order)
- [x] Vendor balance (~70/30 general vs AWS-specific maintained)
