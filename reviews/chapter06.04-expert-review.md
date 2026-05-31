# Expert Review: Recipe 6.4 -- Disease Severity Stratification

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 6.4 -- Disease Severity Stratification
**Date:** 2026-05-31
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 6.4 is a strong, well-structured treatment of disease severity stratification using unsupervised clustering. The Problem section is compelling and grounded in a real care management resource allocation scenario. The Technology section is one of the best in the chapter: it teaches feature engineering, normalization, algorithm selection, and validation from first principles without vendor lock-in. The clinical depth (diabetes-specific feature sets, equity audits, trajectory awareness) demonstrates genuine healthcare domain expertise.

**Verdict: PASS**

The recipe has no CRITICAL findings and 2 HIGH findings. Both are addressable with targeted additions. The architecture is sound for the stated scale, HIPAA considerations are well-handled in the Prerequisites table, and the domain treatment is clinically accurate. The equity audit discussion and explainability emphasis are particular strengths.

---

## Stage 1: Independent Expert Reviews

---

## Security Review

### 🟠 SEC-1: Missing Data Imputation Strategy Creates Clinical Safety Risk Without Adequate Warning

**Finding:** Step 2c imputes missing continuous values with the cohort median and missing binary values with 0 (assume condition absent). The recipe acknowledges "a patient without a recent HbA1c is not the same as a patient with a normal HbA1c" but then proceeds to impute with the median anyway. For binary complication flags, imputing 0 means "no diagnosis on file = no condition." This is clinically dangerous for patients with sparse data (new enrollees, patients who avoid care). A patient with no retinopathy screening is not the same as a patient with a negative retinopathy screening. The recipe mentions this in "Where it struggles" but does not flag it as a safety concern in the imputation step itself.

**Location:** Step 2 pseudocode, "Step 2c: Handle missing values" section; also "Where it struggles" paragraph.

**Fix:** Add a clinical safety warning directly in Step 2c: "WARNING: Imputing binary complication flags with 0 assumes absence of diagnosis means absence of disease. For patients with sparse data (fewer than 3 visits in 12 months, no specialist encounters), consider flagging them as 'insufficient data for stratification' rather than assigning them to a tier. A patient with no retinopathy screening who gets placed in Tier 0 (Well-Controlled) may be missed for outreach. Track the percentage of patients with imputed values per feature; if more than 20% of a feature is imputed, that feature's discriminating power is degraded."

---

### 🟠 SEC-2: DynamoDB Tier Assignments Contain Clinical Severity Labels Without Access Control Discussion

**Finding:** Step 6 writes records to DynamoDB containing `patient_id`, `disease_cohort`, `tier_label` (e.g., "Severe, Functional Decline"), `tier_numeric`, `key_drivers` (with specific clinical values like "complication_count: 4, er_visits_12mo: 5"). This is PHI: it reveals a patient's disease diagnosis, severity classification, and specific clinical indicators. The recipe's Prerequisites table mentions encryption at rest and BAA coverage, but there is no discussion of who can query this table, whether the patient_id is a direct identifier (MRN) or opaque key, or how to prevent unauthorized enumeration of all patients' severity classifications.

**Location:** Step 6 pseudocode; Prerequisites table, "IAM Permissions" row.

**Fix:** Add: "The severity-tiers DynamoDB table contains PHI (disease diagnosis, severity classification, clinical indicators). Restrict access: (1) Pipeline write role: `dynamodb:PutItem` only. (2) Care management read role: `dynamodb:GetItem` by patient_id only (no Scan). (3) Analytics role: query via Athena over the S3 Parquet copy, not DynamoDB directly. Use an opaque patient identifier as the partition key; maintain the MRN-to-opaque mapping in a separate identity service with tighter access controls. Disable DynamoDB Scan for all roles except break-glass admin."

---

### 🟡 SEC-3: Key Drivers Field Exposes Clinical Detail Beyond What's Needed for Tier Assignment

**Finding:** The `key_drivers` field in the output includes specific clinical values: `{"feature": "complication_count", "value": 4, "z_score": 2.1}`. While this is valuable for explainability, it means the operational lookup table contains granular clinical data beyond the tier label itself. A care manager querying "what tier is this patient in?" also receives detailed clinical indicators. This increases the sensitivity of the table and the blast radius of any access control failure.

**Location:** Step 6 pseudocode, `key_drivers` field; Expected Results sample JSON.

**Fix:** Add a design decision note: "Consider whether key_drivers should live in the operational DynamoDB table or only in the S3 analytics layer. If care managers need explainability at the point of care, include it. If the tier label alone is sufficient for workflow routing and detailed drivers are only needed for clinical review, store drivers only in S3 and reduce the DynamoDB table's sensitivity. This is a tradeoff between operational convenience and data minimization."

---

### 🟡 SEC-4: No Discussion of Tier Assignment Audit Trail for Clinical Governance

**Finding:** The recipe mentions CloudTrail in Prerequisites for API call logging, but does not discuss application-level audit trails for tier assignments. When a patient's tier changes between runs (e.g., from Tier 1 to Tier 3), that's a clinically significant event. Clinical governance boards may require: who ran the model, what version of the feature set was used, what the previous tier was, and why it changed. The `run_date` field provides temporal context but not a full audit trail.

**Location:** Prerequisites table, "CloudTrail" row; Step 6 pseudocode.

**Fix:** Add: "Maintain an append-only audit log of tier assignments. Each record should include: patient_id, previous_tier, new_tier, run_date, model_version (feature set hash), and the pipeline execution ID. Store in S3 (immutable, versioned bucket) for compliance. This supports clinical governance review when tier changes trigger care plan modifications."

---

### ✅ SEC-PRAISE: Strong PHI Awareness and Encryption Coverage

The Prerequisites table correctly requires BAA, SSE-KMS for all S3 buckets, DynamoDB encryption at rest, KMS-encrypted SageMaker training volumes, TLS for all API calls, and CloudTrail logging. The "Sample Data" row correctly states "Never use real PHI in development" and points to CMS Synthetic Public Use Files. The VPC requirement (no public internet access for compute touching PHI) is correctly specified.

---

## Architecture Review

### 🟡 ARCH-1: No Dead Letter Queue or Error Handling for the Pipeline

**Finding:** The architecture describes a linear pipeline: Glue ETL -> S3 -> SageMaker -> S3 -> DynamoDB. There is no discussion of what happens when a step fails. If the Glue job fails mid-way, does it leave partial data in S3? If SageMaker clustering fails (e.g., convergence issues), does the pipeline retry or alert? If the DynamoDB write fails for some patients, are those patients left without tier assignments? For a production system that drives care management decisions, silent failures mean patients don't get assigned to tiers and potentially miss interventions.

**Location:** Architecture Diagram; General Architecture Pattern section.

**Fix:** Add: "Production pipelines need failure handling at each stage. Use Step Functions to orchestrate the pipeline with per-step error handling: (1) Glue ETL failure: alert and halt (don't cluster on stale data). (2) SageMaker failure: retry once with increased instance size; if still failing, alert (likely a data quality issue). (3) DynamoDB write failure: use DynamoDB batch write with exponential backoff; log failed patient_ids for manual review. (4) Add a Dead Letter Queue (SQS) for patients that fail any step, so no patient silently falls through the cracks."

---

### 🟡 ARCH-2: Quarterly Refresh Cadence Stated but No Orchestration Architecture Shown

**Finding:** The recipe mentions quarterly re-stratification in multiple places (expires_at field set to run_date + 90 days, "Why This Isn't Production-Ready" section mentions scheduled pipeline). But the architecture diagram shows a one-shot pipeline with no scheduler, no trigger mechanism, and no monitoring for stale assignments. The "Why This Isn't Production-Ready" section acknowledges this gap but doesn't provide even a sketch of the solution.

**Location:** Architecture Diagram; "Why This Isn't Production-Ready" first bullet; Step 6 `expires_at` field.

**Fix:** Add a brief note in the architecture section: "For production, orchestrate with Step Functions triggered by EventBridge on a cron schedule (e.g., first Sunday of each quarter). The Step Functions workflow should: (1) verify source data freshness (abort if EHR extract is more than 7 days old), (2) run the full pipeline, (3) compare new assignments against previous run and emit tier-change events to an SNS topic, (4) update a CloudWatch metric for 'patients with expired tier assignments' so ops can alert if the pipeline fails silently."

---

### 🟡 ARCH-3: SageMaker K-Means Described as "Overkill" for 40K Patients but Still Recommended

**Finding:** The recipe states: "For a 40,000-patient cohort with 30 features, this is overkill (you could run it on a laptop), but for health systems with 500,000+ patients across multiple disease cohorts, managed infrastructure matters." This is honest, but the architecture then uses SageMaker anyway for the 40K case. A reader implementing for a 40K cohort might wonder why they need SageMaker at all. The recipe could more clearly delineate when SageMaker is justified vs. when a simpler compute option (Lambda with scikit-learn, or a Glue Python shell job) would suffice.

**Location:** "Why These Services" section, SageMaker paragraph.

**Fix:** Add: "For cohorts under 100K patients with fewer than 50 features, a SageMaker Processing Job with a scikit-learn container (ml.m5.large, ~$0.23/hour) is the simplest path: no model training infrastructure, just a Python script that reads from S3, runs sklearn.cluster.KMeans, and writes results back. For cohorts over 500K or when running multiple disease cohorts in parallel, SageMaker's built-in K-Means algorithm with distributed training provides horizontal scaling. The architecture diagram shows SageMaker for both paths; the difference is configuration, not topology."

---

### 🟡 ARCH-4: No Discussion of Feature Store or Feature Versioning

**Finding:** The recipe's feature engineering step (Step 2) constructs a feature matrix from multiple source systems. In production, these features are likely reused across multiple models (severity stratification, readmission risk, cost prediction). The recipe doesn't mention SageMaker Feature Store or any feature versioning strategy. When the clinical team decides to add a new feature or change a weight, there's no mechanism to track which version of the feature set produced which tier assignments.

**Location:** Step 2 pseudocode; "Why This Isn't Production-Ready" (model versioning bullet).

**Fix:** Add a brief note: "For production, consider SageMaker Feature Store to version and share the patient feature matrix across models. Each stratification run should record the feature set version (a hash of the FEATURE_SET configuration) alongside tier assignments. This enables: (1) reproducibility (re-run with the same features), (2) comparison (did adding trajectory features improve outcome correlation?), (3) audit (which feature set was active when patient X was assigned to Tier 3?)."

---

### ✅ ARCH-PRAISE: Excellent Validation Framework

The validation section (Step 5) is one of the strongest in the cookbook. It covers: internal metrics (silhouette score), outcome validation (hospitalization rates by tier), clinical face validity (show clinicians the assignments), stability testing (run on different time windows), and equity audits (check for racial/ethnic bias). The emphasis on "the algorithm should serve the workflow, not the other way around" when choosing K is exactly the right framing for healthcare implementations. The operational constraint discussion (your care team can only support N intervention programs) is practical and grounded.

---

## Networking Review

### 🟡 NET-1: VPC Endpoints Listed but No Guidance on Endpoint Policy Restrictions

**Finding:** The Prerequisites table states: "Production: SageMaker training jobs and Glue jobs in VPC with VPC endpoints for S3, DynamoDB, and CloudWatch Logs. No public internet access for compute touching PHI." This is correct, but the recipe doesn't mention VPC endpoint policies. Without endpoint policies, any principal in the VPC can access any S3 bucket or DynamoDB table through the endpoint. For a HIPAA workload, endpoint policies should restrict access to only the specific buckets and tables used by this pipeline.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Add: "Apply VPC endpoint policies to restrict access: S3 Gateway endpoint policy should allow access only to your data lake bucket (arn:aws:s3:::your-data-lake-bucket/*) and the SageMaker default bucket. DynamoDB Gateway endpoint policy should allow access only to the severity-tiers table. This prevents lateral movement: if another workload in the same VPC is compromised, it cannot use your VPC endpoints to access PHI in other buckets."

---

### 🔵 NET-2: No Mention of Cross-Account Data Access Patterns

**Finding:** Many health systems separate their data lake (analytics account) from their operational systems (production account). The recipe assumes all services are in a single account. If the EHR extract lands in a different account than where SageMaker runs, cross-account S3 access requires bucket policies, KMS key policies, and potentially VPC peering or Transit Gateway. This is a common enterprise pattern that the recipe doesn't address.

**Location:** Architecture Diagram (single-account assumption); Prerequisites.

**Fix:** Optional. Add a brief note in Prerequisites or Variations: "If your data lake and compute environments are in separate AWS accounts (common in healthcare enterprises), configure cross-account S3 access via bucket policies and KMS key grants. Ensure the SageMaker execution role in the compute account has permission to decrypt objects encrypted with the data lake account's KMS key."

---

### ✅ NET-PRAISE: Correct VPC Posture for HIPAA

The recipe correctly specifies: SageMaker and Glue in VPC, VPC endpoints for S3/DynamoDB/CloudWatch Logs, no public internet access for compute touching PHI. This is the standard HIPAA networking pattern and is correctly applied.

---

## Voice Review

### 🟡 VOICE-1: Em Dash Detected

**Finding:** Scanning for em dashes (—). Found none. Checking for en dashes (–): none found. Checking for double-hyphens used as dashes: none found. The recipe uses colons, semicolons, periods, and parentheses throughout. Clean.

**Correction:** False alarm. Withdrawing this finding. No em dashes present.

---

### 🔵 VOICE-2: "The Honest Take" Section Title Slightly Inconsistent with Other Chapter 6 Recipes

**Finding:** This recipe uses "The Honest Take" as the section header. Checking against the RECIPE-GUIDE.md, this is the correct title. Consistent with the guide. No issue.

**Correction:** Withdrawing. Consistent with guide.

---

### 🔵 VOICE-3: Vendor Balance Is Strong

**Finding:** The recipe's vendor-agnostic content (Problem + Technology + General Architecture Pattern + Honest Take + Variations) constitutes approximately 65-70% of the total prose. The AWS-specific section (Why These Services through Expected Results) is approximately 30-35%. This is within the 70/30 target. The Technology section is substantial (covers feature engineering, normalization, algorithm selection, choosing K, and validation) and contains zero AWS service names. Excellent balance.

**Location:** Overall recipe structure.

**Fix:** No change needed. Balance is on target.

---

### ✅ VOICE-PRAISE: Exceptional Engineer Voice and Clinical Authenticity

The Problem section's opening scenario (40,000 diabetes patients, 12 care managers, 960 slots) is immediately concrete and relatable. The "naive approach" critique (sorting by HbA1c alone misses the 7.2 with CKD and neuropathy) demonstrates genuine clinical understanding. The Technology section teaches without condescending: the feature engineering discussion is accessible to non-technical readers while remaining clinically precise. The Honest Take is authentic and specific: "the biggest predictor of whether a stratification system gets adopted is not accuracy. It's explainability" is a genuine production insight. The parenthetical style ("Not a risk score (that's prediction, Chapter 7). Not a single metric.") builds momentum effectively. No documentation-voice detected. No marketing language. The self-deprecating expertise ("The algorithm is the easy part. K-Means on 40,000 patients with 30 features takes seconds.") is exactly the cookbook's signature tone.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. The security, architecture, and networking findings are complementary and non-overlapping.

**Priority resolution:**
- SEC-1 (imputation creating clinical safety risk) is HIGH because imputing missing binary flags with 0 could cause genuinely sick patients with sparse data to be classified as low-severity and missed for outreach. This is a patient safety concern, not just a data quality issue.
- SEC-2 (DynamoDB access control for severity labels) is HIGH because the table contains disease diagnosis, severity classification, and clinical indicators for the entire cohort with no access control guidance. This is a high-value PHI asset.
- The MEDIUM findings are all "add a paragraph" improvements that strengthen the recipe without requiring structural changes.
- Voice review found zero em dashes and excellent adherence to the cookbook's style.

**Cross-cutting observation:** The recipe's equity audit discussion (checking whether tier assignments correlate with race/ethnicity after controlling for clinical factors) and the explainability emphasis (key_drivers field, decision tree variation) demonstrate mature thinking about healthcare AI deployment. These are strengths worth preserving through editing.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| SEC-1 | 🟠 HIGH | Security | Step 2c (missing value imputation) | Imputing binary flags with 0 creates clinical safety risk for patients with sparse data | Add clinical safety warning; recommend "insufficient data" flag for sparse patients |
| SEC-2 | 🟠 HIGH | Security | Step 6 (DynamoDB writes); Prerequisites IAM row | Severity labels + clinical indicators in DynamoDB without access control discussion | Add role decomposition, opaque identifiers, disable Scan |
| SEC-3 | 🟡 MEDIUM | Security | Step 6 (key_drivers field); Expected Results | Key drivers expose granular clinical detail in operational table | Add design decision note on data minimization tradeoff |
| SEC-4 | 🟡 MEDIUM | Security | Prerequisites CloudTrail row; Step 6 | No application-level audit trail for tier changes | Add append-only audit log recommendation |
| ARCH-1 | 🟡 MEDIUM | Architecture | Architecture Diagram; General Architecture Pattern | No error handling, DLQ, or failure recovery for pipeline steps | Add Step Functions orchestration with per-step error handling |
| ARCH-2 | 🟡 MEDIUM | Architecture | Architecture Diagram; "Why This Isn't Production-Ready" | Quarterly refresh mentioned but no orchestration architecture | Add EventBridge + Step Functions scheduling sketch |
| ARCH-3 | 🟡 MEDIUM | Architecture | Why These Services (SageMaker) | SageMaker described as overkill but still used; unclear when simpler options suffice | Clarify Processing Job vs built-in algorithm decision point |
| ARCH-4 | 🟡 MEDIUM | Architecture | Step 2; "Why This Isn't Production-Ready" | No feature versioning or Feature Store mention | Add Feature Store note for production reproducibility |
| NET-1 | 🟡 MEDIUM | Networking | Prerequisites, VPC row | VPC endpoints without endpoint policy restrictions | Add endpoint policy guidance to restrict to specific resources |
| NET-2 | 🔵 LOW | Networking | Architecture Diagram | Single-account assumption; no cross-account guidance | Optional: add brief cross-account note |

---

## Final Verdict: **PASS**

The recipe is technically sound, clinically accurate, and architecturally appropriate for its stated "Medium" complexity. The 2 HIGH findings are both addressable with brief additions (clinical safety warning for imputation, and access control discussion for the DynamoDB table) and do not represent fundamental architectural flaws. The 7 MEDIUM findings are all "add a paragraph" improvements. The voice is excellent with zero em dashes and strong adherence to the cookbook's engineer-explaining-something-cool style. The recipe is ready for the TechEditor stage after addressing the HIGH findings.

---

## Additional Notes

**Strengths worth highlighting:**
- The 40,000-patients / 12-care-managers / 960-slots opening immediately establishes the resource allocation constraint that makes stratification necessary
- The "naive approach" critique (HbA1c alone misses the 7.2 with CKD + neuropathy + 3 ER visits) is clinically precise and demonstrates why multi-dimensional clustering matters
- The feature engineering section is disease-specific and clinically validated (HbA1c, eGFR, complication burden, PHQ-9, utilization)
- The normalization discussion (why raw values can't be used directly, clinical weighting tradeoffs) is accessible and technically correct
- The "Choosing K" section correctly separates technical analysis from operational reality ("your care team can only support N programs")
- The validation framework (outcome correlation, clinical face validity, stability, equity audit) is comprehensive and production-oriented
- The equity audit discussion is important and well-placed: checking for racial/ethnic bias in tier assignments is a real concern in healthcare AI
- The Honest Take's insight about explainability being more important than accuracy for adoption is a genuine production lesson
- The key_drivers field design (top 3 features with z-scores) directly addresses the explainability requirement
- The Variations section (multi-disease composite, trajectory-aware, explainable boundaries) provides meaningful extension paths
- The cost estimate (~$5-10 per run for 40K patients) is realistic and well-decomposed

**Domain accuracy validation:**
- K-Means for severity stratification with K=3-5: Standard and appropriate approach
- Feature set for diabetes (HbA1c, eGFR, complication count, PHQ-9, utilization): Clinically sound and comprehensive
- Z-score normalization before clustering: Correct and necessary for mixed-scale features
- Silhouette score range 0.3-0.5 for clinical data: Realistic (clinical data rarely achieves >0.5 due to inherent overlap)
- Tier 3 hospitalization rate 4-8x Tier 0: Consistent with published literature on disease severity and utilization
- Quarterly refresh cadence: Appropriate for chronic disease management (monthly would be excessive, annually too slow)
- CMS Synthetic Public Use Files for development: Correct reference for synthetic chronic disease data
- eGFR < 60 as CKD threshold: Consistent with KDIGO guidelines (Stage 3+)
- PHQ-9 for depression screening: Standard validated instrument in primary care
- Median imputation for continuous features: Standard approach (though the clinical safety concern noted above applies)

**Clinical considerations validated:**
- The distinction between severity stratification (describing present state) and predictive analytics (forecasting future events) is correctly drawn and important for readers
- The multi-morbidity challenge (patient severe in one disease, mild in another) is correctly identified as a limitation
- The trajectory concept (rate of change matters more than absolute value for intervention timing) is clinically sound
- The care manager adoption insight (explainability > accuracy) is well-documented in health informatics literature
- The tier migration as program effectiveness metric is a sophisticated and correct framing
