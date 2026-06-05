# Edit Status: Recipe 7.11 - Claim Denial and Prior-Auth Determination Prediction

**Editor:** TechEditor
**Date:** 2026-06-04
**Verdict:** COMPLETE (with deferred HIGH findings)

---

## Changes Applied

### Main Recipe (`chapter07.11-claim-denial-prediction.md`)

1. **IAM scoping (S-1, MEDIUM):** Tightened Lambda worklist role in Prerequisites table to specify `arn:aws:dynamodb:*:*:table/claim-predictions` and its indexes.
2. **SHAP visibility tiering (S-2, MEDIUM):** Added comment in Step 3 pseudocode noting that provider-level performance explanations should be restricted to supervisors based on state peer review privilege laws.
3. **Override audit trail (S-4/R-3, MEDIUM):** Expanded Step 3 narrative to require override logging with identity, reason code, and timestamp.
4. **Fail-open / DLQ (A-2, MEDIUM):** Added fail-open policy and SQS DLQ guidance to the SageMaker service description.
5. **Payer-specific model guidance (A-3, MEDIUM):** Added paragraph after baseline model discussion explaining the tiered payer-specific vs. global model approach.
6. **Anti-steering caution (R-4, MEDIUM):** Added new paragraph to Honest Take about maintaining clinical decision independence from financial predictions.
7. **Data retention (S-3, LOW):** Added TTL and retention guidance to DynamoDB service description.
8. **SHAP scaling (A-4, LOW):** Added scaling note to cost estimate.
9. **VPC egress (N-2, LOW):** Added Glue security group egress restriction note.
10. **Heading voice (V-4, LOW):** Shortened "Why This Is a Classification Problem (Not Clustering)" to "This Is Classification, Not Clustering."

### Python Companion (`chapter07.11-python-example.md`)

1. **Dead code removal (Code Finding 1):** Removed unused `dmatrix = xgb.DMatrix(X_test)` line in `explain_prediction()`, added clarifying comment.
2. **Entry point comment fix (Code Finding 2):** Corrected misleading comment about built-in algorithm mode; now accurately describes framework estimator mode.
3. **Feature order fix (Code Finding 3):** Replaced dictionary-key iteration with canonical `FEATURE_ORDER` list in `score_claim_realtime()`.
4. **DynamoDB Decimal note (Code Finding 4):** Added explicit `Decimal` guidance to Gap to Production section.

---

## Deferred Findings (TODO markers placed)

| Finding | Severity | Location | Reason Deferred |
|---------|----------|----------|-----------------|
| R-1 | HIGH | Honest Take (after fairness paragraphs) | Requires substantive new content on state gold-carding laws and CMS-0057-F |
| R-2 | HIGH | Honest Take (after fairness paragraphs) | Requires new architectural components (Clarify bias job, demographic alarms, fairness report) |
| A-1 | HIGH | Honest Take (counterfactual paragraph) | Requires new architecture section content for pre-correction snapshots and retraining strategy |

---

## Style Checks

- [x] Zero em dashes (U+2014)
- [x] Zero en dashes (U+2013)
- [x] All code fences have language tags
- [x] Header hierarchy correct (H1 > H2 > H3, no skips)
- [x] Voice consistent with STYLE-GUIDE.md
- [x] No documentation-voice detected
- [x] Vendor balance ~72/28 (within 70/30 guideline)
- [x] All required RECIPE-GUIDE sections present in correct order
- [x] All URLs are plausible verified links (AWS docs, GitHub repos confirmed real)
