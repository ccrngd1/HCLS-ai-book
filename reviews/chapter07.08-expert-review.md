# Expert Review: Recipe 7.8 -- Disease Progression Modeling

**Reviewer:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Document:** `chapter07.08-disease-progression-modeling.md`
**Review Date:** 2026-05-31
**Focus Areas:** Clinical accuracy, survival modeling correctness, treatment confounding, PHI in longitudinal data, uncertainty quantification, causal inference claims

---

## Overall Assessment

Recipe 7.8 is an ambitious and largely successful treatment of one of the hardest problems in healthcare ML. The "Why This Is Fundamentally Hard" section is excellent: it correctly identifies censoring, treatment confounding, irregular observation intervals, and competing risks as the core challenges. The modeling approach taxonomy (joint longitudinal-survival, HMMs, RNNs, Gaussian processes, survival extensions) is accurate and well-organized. The "Honest Take" section is genuinely honest and will save implementers months of wasted effort.

The recipe's primary weakness is in the gap between the sophistication of the conceptual discussion and the simplicity of the implementation pseudocode. The Technology section discusses causal inference, marginal structural models, and G-computation. The Code section trains a standard survival model on observational features with no treatment confounding adjustment. This disconnect will mislead readers into thinking the pseudocode addresses the problems the Technology section warned about.

Several security and architecture findings require attention, but the recipe's clinical framing and honest limitations make it a strong foundation.

---

## Verdict: PASS (conditional on addressing HIGH findings)

---

## Stage 1: Independent Expert Reviews

### Security Expert

#### FINDING S-1: Longitudinal Data Assembly Has No Access Control Scoping (Severity: HIGH)

**Location:** Step 1 pseudocode, `assemble_patient_timeline` function

**Issue:** The function queries all labs, medications, conditions, and procedures for a patient over the lookback period with no mention of access control scoping. In a production FHIR system, not all users or services should have access to all patient data. A disease progression model for CKD does not need psychiatric diagnoses, substance abuse records, or reproductive health data. Under 42 CFR Part 2 (substance abuse records) and state-specific mental health privacy laws, querying "all conditions where patient = patient_id" may return records the consuming system is not authorized to access.

**Risk:** A broad FHIR query that returns all patient data violates the Minimum Necessary standard (45 CFR 164.502(b)) and may violate 42 CFR Part 2 if substance abuse records are included in the condition list. The model training pipeline would then contain data it should never have accessed.

**Suggested Fix:** Add a FHIR query filter for relevant condition categories (renal, cardiovascular, endocrine, metabolic) and relevant lab codes (LOINC codes for eGFR, creatinine, HbA1c, albumin, etc.). Add a note in the Prerequisites section: "FHIR queries must be scoped to clinically relevant data categories. Consult your privacy officer regarding 42 CFR Part 2 and state-specific consent requirements before assembling longitudinal datasets." Include example LOINC code filters in the pseudocode.

---

#### FINDING S-2: SHAP Values May Expose Protected Health Information (Severity: MEDIUM)

**Location:** Step 4 pseudocode, `predict_progression` function, explanations section

**Issue:** The prediction output includes `risk_factors` and `protective_factors` derived from SHAP values. These are surfaced to the clinical interface. Example output: "HbA1c poorly controlled (8.9%, target <7.0%)". If this prediction is cached in DynamoDB with a 30-day TTL and the DynamoDB table is accessible to systems beyond the direct care team (analytics, population health, quality reporting), the SHAP explanations effectively broadcast specific clinical details to a wider audience than the source EHR record.

**Risk:** SHAP explanations that include specific lab values, medication names, and diagnosis details create a secondary PHI store in DynamoDB that may have broader access than the source clinical system. Access controls on the prediction cache must match or exceed the access controls on the source data.

**Suggested Fix:** Add a note in Step 5 that the DynamoDB prediction cache must have row-level access control (or table-level access restricted to the clinical application). Consider offering a "redacted explanations" mode where SHAP outputs use category labels ("declining kidney function biomarker") rather than specific values ("eGFR declining at 5.2 points/year") for contexts where the consumer doesn't need clinical specifics.

---

#### FINDING S-3: Model Artifacts Contain Learned Patient Patterns (Severity: MEDIUM)

**Location:** Prerequisites table, Encryption row

**Issue:** The recipe correctly specifies KMS encryption for training data and model artifacts. However, it does not address the model governance concern that trained model artifacts encode patterns learned from PHI. A survival model trained on 50,000 patient trajectories contains statistical representations of those patients' disease courses. While individual patients cannot typically be reconstructed from model weights, membership inference attacks can determine whether a specific patient was in the training set. The recipe does not mention model access controls or model artifact handling as a PHI-adjacent concern.

**Risk:** Model artifacts shared across environments (dev/staging/prod) or with external collaborators without appropriate controls may constitute a PHI disclosure vector under emerging interpretations of HIPAA's de-identification standard.

**Suggested Fix:** Add a bullet in Prerequisites noting that model artifacts should be treated as PHI-adjacent: stored in PHI-designated S3 buckets, access-logged via CloudTrail, and not shared outside the BAA boundary without privacy review. Reference the SageMaker Model Registry's IAM-based access control as the mechanism for restricting who can deploy or download model artifacts.

---

#### FINDING S-4: CloudTrail Logging for Inference Calls Needs Specificity (Severity: LOW)

**Location:** Prerequisites table, CloudTrail row

**Issue:** The recipe states "Model inference calls logged for audit trail (who requested predictions for which patients)." SageMaker `InvokeEndpoint` calls are logged in CloudTrail, but the request body (which contains the patient features) is not captured in CloudTrail by default. To achieve "who requested predictions for which patients," you need application-level logging that records the patient_id alongside the IAM principal, not just the CloudTrail API event.

**Suggested Fix:** Clarify that CloudTrail captures the API call metadata (who, when, which endpoint) but not the patient identifier. Add a recommendation for application-level audit logging: the clinical application should log (patient_id, requesting_user, timestamp, prediction_version) to a separate audit table or CloudWatch Logs stream before invoking the endpoint.

---

### Architecture Expert

#### FINDING A-1: Treatment Confounding Discussed But Not Implemented (Severity: HIGH)

**Location:** Technology section ("Handling Treatment Effects") vs. Step 3 pseudocode

**Issue:** The Technology section devotes an entire subsection to treatment confounding, correctly identifying it as "where most naive implementations fail." It discusses marginal structural models, G-computation, causal forests, and the pragmatic approach of "conditioning on treatment as a feature." The Step 3 pseudocode then trains a standard survival model on features that include `ace_arb_duration_months` and `diabetes_med_count` as simple numeric features. This is the "conditioning on treatment as a feature" approach, which the Technology section itself describes as "less rigorous."

The problem: the recipe never explicitly states that the pseudocode implements the simplest (least rigorous) approach. A reader who absorbed the Technology section's discussion of causal inference will expect the implementation to address confounding. Instead, the implementation silently uses the approach the Technology section warned is insufficient.

**Risk:** Readers will build the pseudocode implementation, observe that patients on ACE inhibitors appear to progress more slowly, and interpret this as the model correctly capturing disease trajectory. In reality, it's capturing treatment effect confounded with disease severity (sicker patients get more aggressive treatment, creating Simpson's paradox scenarios). The model may systematically underestimate progression risk for untreated patients and overestimate it for aggressively treated patients.

**Suggested Fix:** Add an explicit callout between the Technology section and the Code section: "The implementation below uses the pragmatic approach: conditioning on current treatment as a feature. This means predictions are implicitly 'given current treatment continues.' The model does not answer counterfactual questions ('what if we stop the ACE inhibitor?'). For causal progression modeling, see the Counterfactual Treatment Simulation variation." Add a comment in Step 3 pseudocode: "// NOTE: This is observational prediction, not causal. Treatment features are confounded with disease severity."

---

#### FINDING A-2: Temporal Validation Split Is Correct But Incomplete (Severity: HIGH)

**Location:** Step 3 pseudocode, train/validation split

**Issue:** The recipe correctly insists on temporal splitting ("NEVER split randomly. Random splits leak future information.") and splits by index date. However, it does not address a subtler form of temporal leakage: feature computation using future data. The `engineer_progression_features` function computes slopes and variability using "all values" for a biomarker. If the training pipeline computes features at time T using data up to time T, but the outcome is measured at time T+horizon, this is correct. But if the feature engineering step inadvertently uses data from after the index date (e.g., computing eGFR slope using all available labs including those after the prediction point), the model sees the future.

The pseudocode does not explicitly enforce a "feature computation cutoff" that aligns with the prediction point. The `engineer_progression_features` function takes a `timeline` object with no temporal boundary parameter.

**Risk:** Temporal leakage in feature engineering is the most common source of inflated validation metrics in longitudinal modeling. A model that appears to have a C-index of 0.78 may actually perform at 0.68 in production because it was trained with features computed using data that wouldn't be available at prediction time.

**Suggested Fix:** Add a `cutoff_date` parameter to `engineer_progression_features`. All feature computations must use only data before `cutoff_date`. Add a comment: "// CRITICAL: Only use data available at the time of prediction. Using future labs in feature computation is the #1 source of inflated metrics in progression modeling." In Step 3, explicitly show that the cutoff_date for each training example is the index date (the point from which the prediction horizon is measured).

---

#### FINDING A-3: DynamoDB Prediction Cache TTL Strategy Is Underspecified (Severity: MEDIUM)

**Location:** Step 5 pseudocode, DynamoDB write

**Issue:** The prediction cache uses a 30-day TTL. The recipe states "predictions expire; new data means new predictions." But the trigger for generating a new prediction is not defined. If a patient has new labs today, does the old prediction get invalidated immediately, or does it persist until TTL expiry? A clinician viewing the patient's record 29 days after a prediction was generated, when 3 new lab results have arrived since, would see a stale prediction that doesn't incorporate the most recent data.

**Risk:** Stale predictions that don't reflect recent clinical changes could mislead clinicians. A patient whose eGFR dropped sharply last week would still show the month-old prediction suggesting slow decline.

**Suggested Fix:** Add an event-driven invalidation mechanism: when new lab results arrive (via EventBridge from HealthLake or the EHR integration), trigger a re-prediction for that patient. The DynamoDB record should include a `data_freshness` field (already present in the output schema) and the clinical interface should display a warning when `data_freshness` is more than 14 days old. The 30-day TTL becomes a cleanup mechanism, not the primary freshness control.

---

#### FINDING A-4: C-index Benchmarks Need Context (Severity: MEDIUM)

**Location:** Expected Results, Performance benchmarks table

**Issue:** The recipe states "A C-index above 0.70 is reasonable for multi-year disease progression. Above 0.75 is good. Above 0.80 is excellent (and you should double-check for leakage)." The performance benchmarks table then shows "C-index (12-month horizon): 0.72-0.78" and "C-index (36-month horizon): 0.65-0.72." These ranges are reasonable for CKD progression specifically, but the recipe doesn't cite any published benchmarks to support these claims. Without citations, a reader has no way to validate whether their model's performance is in line with the state of the art or whether the recipe's claims are aspirational.

**Risk:** Readers may accept a C-index of 0.72 as "good enough" without understanding whether published CKD progression models achieve higher discrimination. Conversely, they may reject a model with C-index 0.68 as inadequate when it's actually competitive with published results for their specific population.

**Suggested Fix:** Add a note referencing published CKD progression models (e.g., the Kidney Failure Risk Equation by Tangri et al., which achieves C-statistics of 0.84-0.90 for 2-year and 5-year kidney failure prediction). Clarify that the recipe's benchmarks assume a general-purpose model predicting stage progression (a broader outcome than kidney failure specifically), which is inherently harder to discriminate than a binary endpoint. This gives readers calibration for their own results.

---

#### FINDING A-5: No Discussion of Model Fairness Across Subgroups (Severity: MEDIUM)

**Location:** "Where it struggles" section and throughout

**Issue:** The recipe mentions "subgroups underrepresented in training data (rare diseases, pediatric populations, specific ethnic groups with different progression patterns)" as a limitation. However, it does not address the well-documented issue that eGFR itself is calculated differently by race (the 2021 CKD-EPI equation removed the race coefficient, but many health systems still use the older race-adjusted formula). A model trained on race-adjusted eGFR values will have systematically different baseline features for Black patients versus non-Black patients, potentially encoding a biased trajectory baseline.

**Risk:** A disease progression model that doesn't account for the eGFR race coefficient controversy may produce systematically different predictions for Black patients, not because of biological differences in progression rate, but because of measurement artifact in the input feature. This is a health equity concern with regulatory implications.

**Suggested Fix:** Add a paragraph in the Technology section or "The Honest Take" addressing the eGFR race coefficient issue. Recommend that implementations verify which eGFR formula was used in their training data and consider recomputing eGFR using the 2021 CKD-EPI equation (race-free) for consistency. Add model fairness evaluation (C-index stratified by race, sex, age group) to the monitoring section. Reference the NKF/ASN Task Force recommendation on removing race from eGFR estimation.

---

#### FINDING A-6: Retraining Trigger Is Alarm-Based But No Automated Retraining Pipeline (Severity: LOW)

**Location:** Step 5, `monitor_model_performance` function

**Issue:** The monitoring function triggers an alarm when calibration error exceeds 0.10 or C-index drops below 0.65. The alarm text says "Retraining recommended." But the recipe's architecture (Step Functions + EventBridge) is described as handling "data refresh, feature computation, model retraining, validation, deployment." The monitoring alarm doesn't connect to the retraining pipeline. It's a manual alert that requires human intervention to initiate retraining.

**Suggested Fix:** Add a note that the CloudWatch alarm can trigger a Step Functions execution for automated retraining, but recommend human-in-the-loop approval before deploying a retrained model (via a manual approval step in the Step Functions workflow). Automated retraining without validation review is risky for clinical models.

---

### Networking Expert

#### FINDING N-1: HealthLake VPC Endpoint Access Pattern Not Specified (Severity: MEDIUM)

**Location:** Prerequisites table, VPC row; Architecture diagram

**Issue:** The Prerequisites state "HealthLake accessed via VPC endpoint." Amazon HealthLake supports VPC endpoints (Interface type, `com.amazonaws.REGION.healthlake`). However, the recipe does not specify whether the Glue ETL jobs and SageMaker training jobs access HealthLake from within the VPC or via the public endpoint. Glue jobs can run in a VPC, but this requires explicit VPC configuration. SageMaker training jobs in VPC mode cannot access the internet, so they need VPC endpoints for every service they call.

**Risk:** If Glue ETL jobs are not configured to run in the VPC, they access HealthLake via the public endpoint, meaning PHI traverses the public internet (encrypted via TLS, but outside the VPC boundary). This may not satisfy security teams that require all PHI data flows to remain within the VPC.

**Suggested Fix:** Specify that Glue jobs must be configured with VPC connections (Glue Connection with VPC/subnet/security group) to access HealthLake via the VPC endpoint. List the required VPC endpoints for the full pipeline: S3 (Gateway), DynamoDB (Gateway), HealthLake (Interface), SageMaker API (Interface), SageMaker Runtime (Interface), CloudWatch Logs (Interface), KMS (Interface), STS (Interface). Note that SageMaker training in VPC mode requires all these endpoints to be present.

---

#### FINDING N-2: No Data Transfer Cost Estimate for Large Cohort Training (Severity: LOW)

**Location:** Prerequisites, Cost Estimate

**Issue:** Training on a 50,000-patient cohort with 5+ years of longitudinal data per patient could produce a training dataset of 5-20 GB. If HealthLake and SageMaker are in the same region and VPC, data transfer is free. But the recipe doesn't mention this constraint. If a reader has HealthLake in one region and runs SageMaker training in another (perhaps for GPU availability), cross-region data transfer at $0.02/GB adds up for repeated training runs.

**Suggested Fix:** Add a one-line note in Prerequisites: "All services should be deployed in the same AWS region to avoid cross-region data transfer charges on training data."

---

### Voice Reviewer

#### FINDING V-1: Em Dash Present (Severity: MEDIUM)

**Location:** Multiple locations throughout the recipe

**Issue:** The recipe contains em dashes. Specific instances:

- "The Problem" section: "how fast is this going to get worse?" paragraph contains no em dashes (good), but checking further...
- Technology section: "Not population averages. Individual trajectories." (good, uses period)
- After thorough review: The recipe appears clean of em dashes. The long dashes in the document are actually part of the horizontal rule markers (`---`) which are valid markdown section separators, not em dashes in prose.

**Result:** No em dash violations found. PASS on this criterion.

---

#### FINDING V-2: Vendor Balance Is Well-Maintained (Severity: LOW)

**Location:** Overall structure

**Issue:** The recipe follows the 70/30 split well. The Problem, Technology, and General Architecture Pattern sections are entirely vendor-agnostic. AWS services appear only in "The AWS Implementation" section. The Technology section discusses modeling approaches without mentioning SageMaker. The General Architecture Pattern uses generic terms ("clinical data store," "model training," "prediction cache"). This is correct.

One minor note: the "Why These Services" section could be slightly more concise. It spends 2-3 sentences per service explaining the choice, which is appropriate per the RECIPE-GUIDE but pushes the AWS section slightly longer than necessary.

**Result:** Vendor balance is acceptable. No action required.

---

#### FINDING V-3: Voice Is Consistent and Appropriate (Severity: LOW)

**Location:** Throughout

**Issue:** The recipe maintains the "engineer explaining something cool" voice throughout. The opening scenario (nephrologist with a CKD patient) is engaging and specific. Phrases like "the combination is what makes it genuinely complex" and "Here's the fundamental paradox" match the expected tone. The "Honest Take" section uses first person ("I've learned," "I cannot stress this enough") appropriately.

One minor observation: the sentence "This is non-negotiable for clinical use" in the Uncertainty Quantification subsection has a slightly more authoritative/prescriptive tone than the rest of the recipe. It's not doc-voice, but it's closer to a mandate than the typical conversational register.

**Result:** Voice is consistent. No action required.

---

## Stage 2: Expert Discussion

**Conflict: A-1 (Treatment Confounding) vs. Pragmatism**

The Architecture expert flags that the implementation doesn't match the sophistication of the Technology discussion. The Voice reviewer notes that the recipe's tone is honest and educational. Resolution: the recipe should be explicit about the gap rather than closing it. Adding causal inference to the pseudocode would make the recipe inaccessible. Instead, clearly label the implementation as "observational prediction" and point readers to the Variations section for causal approaches. This maintains the educational value of the Technology section while being honest about what the pseudocode actually does.

**Conflict: S-1 (Broad FHIR Queries) vs. A-2 (Feature Completeness)**

The Security expert wants narrowly scoped FHIR queries. The Architecture expert wants complete longitudinal data for accurate features. Resolution: scope queries by LOINC code and condition category rather than by "all data." The feature engineering step already specifies which biomarkers it uses (eGFR, HbA1c, creatinine, albumin, hemoglobin, potassium). The FHIR query should retrieve only those specific lab codes plus the medication and condition categories relevant to CKD progression. This satisfies both Minimum Necessary and feature completeness.

**Overlap: A-5 (Fairness) and Clinical Accuracy**

The eGFR race coefficient issue is both a fairness concern and a clinical accuracy concern. A model trained on race-adjusted eGFR will produce predictions that are technically accurate for the formula used but clinically misleading if the health system transitions to the race-free formula. This should be addressed in both the Technology section (as a data quality issue) and the Honest Take (as a fairness issue).

---

## Stage 3: Synthesized Findings

| ID | Lens | Severity | Title |
|----|------|----------|-------|
| A-1 | Architecture | HIGH | Treatment confounding discussed but not addressed in implementation; no explicit labeling of approach |
| A-2 | Architecture | HIGH | Temporal validation correct but feature engineering lacks cutoff_date enforcement |
| S-1 | Security | HIGH | Longitudinal data assembly queries all patient data without Minimum Necessary scoping |
| A-5 | Architecture | MEDIUM | No discussion of eGFR race coefficient and model fairness across subgroups |
| A-4 | Architecture | MEDIUM | C-index benchmarks lack published reference citations |
| S-2 | Security | MEDIUM | SHAP explanations in DynamoDB cache create secondary PHI store with potentially broader access |
| S-3 | Security | MEDIUM | Model artifacts not addressed as PHI-adjacent; no access control guidance |
| N-1 | Networking | MEDIUM | HealthLake VPC endpoint access pattern unspecified for Glue and SageMaker |
| A-3 | Architecture | MEDIUM | DynamoDB prediction cache has no event-driven invalidation; stale predictions possible |
| V-1 | Voice | -- | No em dash violations found |
| S-4 | Security | LOW | CloudTrail doesn't capture patient_id in inference calls; application-level audit needed |
| A-6 | Architecture | LOW | Monitoring alarm doesn't connect to automated retraining pipeline |
| N-2 | Networking | LOW | No cross-region data transfer cost warning for training data |
| V-2 | Voice | LOW | Vendor balance acceptable; AWS section slightly verbose but within bounds |

---

## Priority Fix List (Recommended Order)

1. **A-1 (Treatment Confounding Gap):** Add explicit callout that the pseudocode implements observational prediction only. Add a comment in Step 3 noting that treatment features are confounded. This is a one-paragraph addition plus one code comment, but it prevents the most dangerous misinterpretation of the recipe.

2. **A-2 (Feature Engineering Cutoff):** Add `cutoff_date` parameter to `engineer_progression_features`. Add a CRITICAL comment about temporal leakage. This prevents the most common implementation error in longitudinal modeling.

3. **S-1 (FHIR Query Scoping):** Add LOINC code filters and condition category filters to the `assemble_patient_timeline` pseudocode. Add a Minimum Necessary note in Prerequisites. This addresses a HIPAA compliance gap.

4. **A-5 (eGFR Race Coefficient / Fairness):** Add a paragraph addressing the 2021 CKD-EPI race-free equation and recommend stratified model evaluation. This is clinically important and timely.

5. **A-4 (Benchmark Citations):** Add a reference to the Kidney Failure Risk Equation (Tangri et al.) and clarify how the recipe's benchmarks relate to published results. One paragraph addition.

6. **S-2 (SHAP in DynamoDB):** Add access control guidance for the prediction cache table. Note that SHAP explanations containing specific clinical values require the same access controls as the source EHR data.

7. **N-1 (VPC Endpoints):** Expand the VPC row in Prerequisites to list all required endpoints for the full pipeline (HealthLake, SageMaker API, SageMaker Runtime, S3, DynamoDB, KMS, STS, CloudWatch Logs).

8. **A-3 (Cache Invalidation):** Add event-driven prediction refresh when new labs arrive. The 30-day TTL should be a cleanup mechanism, not the freshness control.

---

## What the Recipe Gets Right

The Technology section is outstanding. The taxonomy of modeling approaches (joint longitudinal-survival, HMMs, RNNs, Gaussian processes, survival extensions) is accurate, well-organized, and gives readers genuine understanding of the landscape. The discussion of why disease progression is fundamentally hard (long horizons, treatment confounding, irregular observations, competing risks, censoring) is the best explanation of these challenges I've seen in a practitioner-oriented document.

The "Honest Take" section earns significant trust. "The data problem is bigger than the model problem" and "Calibration matters more than discrimination" are insights that would save a team months of misdirected effort. The observation that "the uncertainty bounds are the product, not the point estimate" is clinically correct and important.

The sample output JSON is well-designed. Including both `risk_factors` and `protective_factors` gives clinicians a balanced view. The confidence intervals widening with prediction horizon (46-54 at 6 months, 28-49 at 36 months) demonstrates honest uncertainty quantification.

The decision to use CKD as the running example is excellent. It's concrete, clinically important, and has clear biomarkers (eGFR) that make the trajectory concept intuitive for non-specialist readers.

The Variations section correctly identifies counterfactual treatment simulation as the highest-value extension and honestly labels it as "significantly harder to validate." This manages expectations appropriately.

---

*Review prepared by the Technical Expert Panel. All findings include suggested fixes. No em dashes were used in the preparation of this document.*
