# Expert Review: Recipe 7.4 - ED Visit Prediction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter07.04-ed-visit-prediction.md` (MISSING)
**Python companion:** `chapter07.04-python-example.md` (reviewed)

---

## Overall Assessment

The main recipe file (`chapter07.04-ed-visit-prediction.md`) does not exist. The Python companion exists and is well-written, but the recipe pipeline requires the main recipe to be drafted before expert review can be meaningfully completed. The Python companion references the main recipe at its footer: "See [Recipe 7.4](chapter07.04-ed-visit-prediction) for the full architectural walkthrough, pseudocode, and honest take on where ED prediction gets complicated."

Without the main recipe, the expert panel cannot evaluate:
- The Problem section (clinical framing, emotional stakes)
- The Technology section (vendor-agnostic teaching of ED prediction concepts)
- The General Architecture Pattern (cloud-neutral pipeline design)
- The AWS-specific implementation (service selection rationale, architecture diagram)
- Prerequisites table (IAM, BAA, encryption, VPC, cost estimate)
- Pseudocode walkthrough (the primary teaching artifact)
- Expected Results and performance benchmarks
- The Honest Take (production lessons)
- Variations and Extensions
- Additional Resources (verified links)

The review below evaluates the Python companion for issues that would carry into the main recipe, and flags the missing file as a blocking issue.

---

## Verdict: **FAIL**

**Reason:** CRITICAL finding (C1). The main recipe file does not exist. The Python companion cannot stand alone; it is explicitly framed as a supplement to the main recipe. No architectural guidance, prerequisites, pseudocode, or vendor-agnostic teaching content exists for this recipe.

---

## Security Expert Review

*Reviewed against the Python companion only. Main recipe security posture (IAM table, BAA, VPC, encryption) cannot be evaluated.*

### What's Done Well (Python Companion)

- S3 upload uses `ServerSideEncryption="aws:kms"` for PHI-adjacent training data.
- DynamoDB `Decimal(str(...))` pattern correctly avoids float precision issues.
- DynamoDB TTL auto-expires stale predictions after the prediction window.
- IAM permissions in the Setup section are specific (not `*` wildcards): `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:Query`.
- The "Gap Between This and Production" section explicitly calls out IAM least-privilege, VPC + VPC endpoints, and KMS CMKs.
- Synthetic data generation avoids any real PHI.

### Issue S1: IAM Permissions Not Resource-Scoped (MEDIUM)

**Location:** Python companion, Setup section

**The problem:** The Setup section lists IAM permissions (`s3:GetObject`, `s3:PutObject` on "your data bucket", `sagemaker:CreateTrainingJob`, etc.) but doesn't specify resource ARNs. The phrasing "on your data bucket" is directionally correct but a reader may interpret this as bucket-level `s3:*` rather than prefix-scoped access. The SageMaker permissions are listed without endpoint ARN scoping.

More importantly, all permissions are listed for a single "IAM role or user," implying a single execution identity for the entire pipeline. The training job, scoring job, and DynamoDB writer should be separate roles.

**Suggested fix:** This belongs in the main recipe's Prerequisites table (which doesn't exist). When the main recipe is written, split permissions into: (1) SageMaker execution role (S3 read/write on model bucket, KMS decrypt), (2) Scoring Lambda/job role (SageMaker InvokeEndpoint on specific endpoint ARN, DynamoDB PutItem/BatchWriteItem on specific table ARN), (3) Data upload role (S3 PutObject on training prefix only).

### Issue S2: DynamoDB Table Has No Encryption Specification (MEDIUM)

**Location:** Python companion, Step 5 (store_risk_scores)

**The problem:** The DynamoDB table `ed-risk-scores` stores `patient_id`, `risk_score`, `risk_tier`, and `top_factors`. This is PHI (patient identifiers linked to health predictions). The code uses `dynamodb.Table(RISK_SCORES_TABLE)` without any mention of encryption configuration. DynamoDB encrypts at rest by default (AWS-owned key), but HIPAA best practice requires customer-managed KMS keys for PHI tables to maintain key rotation control and audit trail.

The "Gap to Production" section mentions "VPC and network isolation" and "IAM least-privilege" but does not mention DynamoDB encryption with CMK.

**Suggested fix:** Add to the Gap to Production section: "DynamoDB encrypts at rest by default with an AWS-owned key. For PHI tables, use a customer-managed KMS key (CMK) to maintain control over key rotation, access policies, and CloudTrail audit of key usage. Specify this when creating the table, not after."

### Issue S3: Risk Scores Served Without Consumer Access Differentiation (MEDIUM)

**Location:** Python companion, Step 5 comments

**The problem:** The comments state two consumers: "Care management platform: queries by risk_tier (via GSI) to build daily outreach worklists" and "EHR integration: queries by patient_id to show risk badges at the point of care." Both consumers access the same table with the same data, including `top_factors` (e.g., "ed_visits_last_12m, has_chf, lives_alone").

The `top_factors` field exposes behavioral and social determinant data. An EHR risk badge showing "lives_alone" as a contributing factor could be inappropriate in certain clinical contexts or if visible to the patient in a portal. No guidance on restricting which fields different consumers can access.

**Suggested fix:** Add a note: "In production, consider separating the detailed `top_factors` into a separate DynamoDB attribute or table that requires elevated IAM permissions. The EHR badge may only need `risk_tier` (HIGH/MEDIUM/LOW), while care managers need the full explanation. Use IAM conditions or application-layer filtering to restrict field access by consumer identity."

---

## Architecture Expert Review

*Evaluated based on the Python companion's pipeline design. The main recipe's architecture diagram, General Architecture Pattern, and service selection rationale cannot be reviewed.*

### What's Done Well (Python Companion)

- Pipeline follows a clear pedagogical progression: Config, Data, Training, Evaluation, Scoring, Storage, S3 upload.
- Gradient boosted trees are well-justified for this problem (tabular data, <50 features, interaction effects, explainability needs).
- Risk tier thresholds are externalized as constants with operational context (nurse capacity, outreach cadence).
- The evaluation function focuses on clinically relevant metrics (precision at threshold, tier distribution) rather than just AUC.
- The "Gap Between This and Production" section is comprehensive: temporal validation, calibration, fairness, SHAP, drift detection, retraining, consent, error handling.
- DynamoDB TTL correctly auto-expires stale predictions.
- Filtering LOW risk patients before DynamoDB write is operationally sound.

### Issue A1: Per-Patient Explanation Method Is Actively Misleading (HIGH)

**Location:** Python companion, Step 4, `score_patients()`, contribution calculation

```python
contributions = patient_features * feature_importances
top_indices = np.argsort(contributions)[-3:][::-1]
```

**The problem:** This multiplies raw feature values by global feature importances. Feature scale dominates the result. A patient with `age=75` (importance 0.05) gets contribution 3.75, while `ed_visits_last_12m=4` (importance 0.30) gets contribution 1.2. The code reports "age" as the top factor when the model actually relies on ED visit history for that prediction.

This output feeds a care manager worklist with "top contributing factors." Care managers would see misleading explanations and potentially make incorrect outreach decisions (e.g., focusing on age-related interventions when the actual driver is recent ED utilization patterns).

The comment acknowledges this is a simplification and points to SHAP, but the code produces actively wrong per-patient attributions that would mislead clinical users. For a teaching example, this teaches a pattern that produces incorrect results.

**Suggested fix:** Either:
1. Normalize features before multiplying: `patient_normalized = (X.iloc[idx] - X.min()) / (X.max() - X.min() + 1e-8)` then multiply by importances.
2. Or replace with a simpler heuristic: report the top global feature importances for features where the patient has above-median values.
3. Add a prominent warning: "WARNING: This approach produces incorrect per-patient attributions due to feature scale differences. Do not show these explanations to clinicians. Use SHAP values for any patient-facing or clinician-facing explanations."

### Issue A2: No Temporal Validation in Training Step (MEDIUM)

**Location:** Python companion, Step 2, `train_ed_prediction_model()`

```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
```

**The problem:** The code uses a random train/test split. The "Gap to Production" section correctly identifies this as a problem ("Random splits leak future information and produce optimistic AUC estimates"). But the teaching code demonstrates the wrong pattern. A reader copying this code gets inflated performance metrics and a false sense of model quality.

For ED prediction specifically, temporal patterns matter: flu season, holiday periods, and seasonal behavioral changes all affect ED utilization. A random split mixes future and past data, making the model appear better than it will perform when deployed forward in time.

**Suggested fix:** The code already has a comment noting temporal validation is needed. Strengthen it: "IMPORTANT: This random split is for demonstration only. In production, you MUST use a temporal split (e.g., train on months 1-9, test on months 10-12). Random splits produce optimistically biased AUC estimates for time-dependent outcomes like ED visits. A model that shows AUC 0.82 on a random split may drop to 0.72 on a temporal split."

### Issue A3: No Model Calibration Step (MEDIUM)

**Location:** Python companion, Step 3, `evaluate_model()`; Gap to Production section

**The problem:** The evaluation step computes AUC-ROC, average precision, and precision at threshold. It does not assess calibration (whether a predicted probability of 0.70 corresponds to a 70% actual event rate). The Gap to Production section correctly identifies calibration as critical ("Calibration matters because care managers make resource allocation decisions based on these numbers").

For ED prediction, calibration is especially important because the risk tiers are probability-based (HIGH >= 0.70, MEDIUM >= 0.40). If the model is poorly calibrated (e.g., patients scored at 0.70 actually have a 45% event rate), the tier assignments are meaningless and care management resources are misallocated.

Gradient boosted trees are known to produce poorly calibrated probabilities out of the box. The Gap to Production section mentions Platt scaling and isotonic regression but the code doesn't demonstrate either.

**Suggested fix:** Add a brief calibration check to the evaluation function, even if simplified:

```python
# Quick calibration check: bin predictions and compare to actual rates
from sklearn.calibration import calibration_curve
fraction_of_positives, mean_predicted_value = calibration_curve(y_test, y_prob, n_bins=5)
# Log the calibration gap
for actual, predicted in zip(fraction_of_positives, mean_predicted_value):
    logger.info("Predicted: %.2f, Actual: %.2f (gap: %.2f)", predicted, actual, abs(predicted - actual))
```

### Issue A4: Synthetic Data Generation Creates Circular Validation (LOW)

**Location:** Python companion, Step 1, `generate_synthetic_patients()`

**The problem:** The synthetic data generates outcomes using a logistic model with known feature weights, then trains a gradient boosted tree to recover those weights. This guarantees good performance metrics because the model is learning a pattern that was explicitly encoded. The comment correctly notes "This is NOT how you'd build a real model (that's circular)."

This is LOW because the comment is clear and the purpose is pedagogical. But a reader who runs this code and sees AUC 0.85+ may develop unrealistic expectations for real-world ED prediction performance (literature typically shows AUC 0.70-0.78).

**Suggested fix:** Add expected real-world performance context: "Note: This synthetic data produces artificially high AUC because the outcome was generated from the same features the model uses. Real-world ED prediction models typically achieve AUC 0.70-0.78 due to unmeasured confounders, data quality issues, and temporal drift. Don't use synthetic-data performance as a benchmark for production readiness."

---

## Networking Expert Review

*The main recipe's VPC configuration, Prerequisites table, and architecture diagram cannot be reviewed. Evaluating only what's stated in the Python companion.*

### What's Done Well

- The Gap to Production section explicitly states: "Patient data (even derived risk scores) is PHI. The scoring job runs in a private subnet with VPC endpoints for SageMaker, DynamoDB, and S3. No internet egress."
- CloudTrail logging is mentioned for audit trail.

### Issue N1: No VPC Endpoint Guidance in Code Comments (LOW)

**Location:** Python companion, Step 5 (DynamoDB), Step 6 (S3)

**The problem:** The boto3 clients are created with default configuration (`boto3.resource("dynamodb")`, `boto3.client("s3")`). In a VPC with no internet egress, these calls route through VPC endpoints automatically if configured. But the code doesn't mention that VPC endpoints must exist for these calls to succeed in a private subnet. A developer deploying this in a locked-down VPC would get timeout errors with no guidance on why.

**Suggested fix:** Add a comment near the boto3 client creation: "In a VPC with no internet egress (required for PHI workloads), ensure gateway VPC endpoints exist for S3 and DynamoDB, and interface VPC endpoints for SageMaker Runtime. Without these, boto3 calls will timeout."

---

## Voice Reviewer

*The main recipe's Problem section, Technology section, and Honest Take cannot be reviewed for voice. Evaluating the Python companion's tone.*

### What's Done Well

- The opening callout is appropriately self-deprecating: "It is not production-ready. The feature engineering is minimal, the synthetic data is unrealistically clean, and the model evaluation skips half the things you'd need for a real deployment. Think of it as a sketch that shows the shape of the solution. A starting point, not a destination."
- Comments explain clinical "why" throughout (why gradient boosting over logistic regression, why precision matters for care managers, why prior ED visits are the strongest signal).
- The Gap to Production section reads like an engineer listing what they'd actually need to fix, not a documentation checklist.
- Parenthetical asides are natural and informative.
- The tone is consistently "engineer explaining something cool" rather than documentation-voice.

### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the Python companion. Clean.

### Issue V2: Vendor Balance Cannot Be Assessed (NOTE)

The Python companion is inherently AWS-specific (boto3, SageMaker, DynamoDB). The 70/30 vendor balance is assessed on the main recipe, which doesn't exist. The Python companion's Config section and model training steps are vendor-agnostic (scikit-learn), which is appropriate for the companion format.

### Issue V3: One Instance of Mild Documentation-Voice (LOW)

**Location:** Step 6, docstring

**The text:** "SageMaker's built-in XGBoost algorithm expects CSV with the target column first and no header row. We format accordingly."

"We format accordingly" is slightly formal/documentation-voice. The rest of the file uses more natural phrasing.

**Suggested fix:** Rewrite to: "SageMaker's built-in XGBoost algorithm expects CSV with the target column first and no header row. So that's what we give it."

---

## Stage 2: Expert Discussion

**The dominant issue is C1 (missing main recipe).** Without the main recipe, this review is fundamentally incomplete. The Python companion is a supplement, not the primary teaching artifact. The main recipe contains the vendor-agnostic technology explanation, the architecture diagram, the prerequisites table (where IAM, BAA, VPC, and encryption are specified), the pseudocode walkthrough, and the Honest Take. These are the sections where most CRITICAL and HIGH findings typically surface.

**Architecture A1 (misleading explanations) is the most impactful technical finding.** The per-patient explanation method produces actively wrong results that would mislead clinical users. This is HIGH rather than CRITICAL because the Python companion explicitly frames itself as "not production-ready" and the comment points to SHAP. But the code still teaches a harmful pattern.

**Security findings (S1, S2, S3) are all MEDIUM** because they represent gaps in guidance rather than active vulnerabilities. The Python companion correctly identifies most of these in its Gap to Production section but doesn't implement the fixes.

**No conflicts between experts.** All findings are complementary.

---

## Stage 3: Synthesized Feedback

### Verdict: **FAIL**

**Reason:** One CRITICAL finding. The main recipe file does not exist. The expert review cannot be completed without the primary teaching artifact.

The Python companion is well-written and would likely support a PASS verdict for the main recipe once it exists. The code is clean, the comments are excellent, the Gap to Production section is comprehensive, and the clinical context is appropriate throughout. The HIGH finding (A1, misleading per-patient explanations) needs to be fixed but is not blocking given the companion's explicit "not production-ready" framing.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | CRITICAL | All | Repository | Main recipe file `chapter07.04-ed-visit-prediction.md` does not exist. The Python companion references it but it has not been written. No architecture, prerequisites, pseudocode, technology teaching, or Honest Take content exists for this recipe. | Write the main recipe following RECIPE-GUIDE.md structure. The Python companion is ready and waiting for it. |
| 2 | HIGH | Architecture | Python companion, Step 4, `score_patients()` | Per-patient explanation method (`feature_value * global_importance`) is dominated by feature scale and produces actively wrong attributions. Care managers would see misleading "top factors" on their worklists. | Normalize features before multiplying, or replace with above-median heuristic, or add prominent WARNING that this method produces incorrect results and must not be shown to clinicians. |
| 3 | MEDIUM | Security | Python companion, Setup section | IAM permissions listed as flat set for single identity. No role separation between training, scoring, and storage contexts. No resource ARN scoping. | Address in main recipe Prerequisites table: split into role-specific entries with resource-scoped ARNs. |
| 4 | MEDIUM | Security | Python companion, Step 5 | DynamoDB table stores PHI (patient_id + risk predictions) with no mention of customer-managed KMS key. Default AWS-owned encryption doesn't provide key rotation control or granular audit. | Add to Gap to Production: specify CMK for PHI tables. Address in main recipe Prerequisites table. |
| 5 | MEDIUM | Security | Python companion, Step 5 comments | Two consumers (care management, EHR) access same table with same data including `top_factors`. No access differentiation. Social determinant data ("lives_alone") may be inappropriate for all consumer contexts. | Add guidance on consumer-specific field access. Separate detailed explanations into attribute requiring elevated permissions. |
| 6 | MEDIUM | Architecture | Python companion, Step 2 | Random train/test split demonstrated despite Gap to Production correctly identifying temporal validation as required. Teaching code shows the wrong pattern. | Strengthen the comment to WARNING level. Add expected performance degradation when switching from random to temporal split. |
| 7 | MEDIUM | Architecture | Python companion, Step 3 | No calibration assessment despite probability-based tier thresholds (0.70, 0.40). GBTs produce poorly calibrated probabilities. Gap to Production mentions calibration but code doesn't demonstrate it. | Add brief calibration check (calibration_curve from sklearn) to evaluation function. |
| 8 | LOW | Architecture | Python companion, Step 1 | Synthetic data guarantees artificially high AUC due to circular generation. No real-world performance context provided. Reader may develop unrealistic expectations. | Add note: real-world ED prediction AUC is typically 0.70-0.78. Synthetic performance is not a production benchmark. |
| 9 | LOW | Networking | Python companion, Steps 5-6 | No mention that VPC endpoints must exist for boto3 calls to succeed in private subnets. Developer in locked-down VPC gets unexplained timeouts. | Add comment near boto3 client creation about VPC endpoint requirements. |
| 10 | LOW | Voice | Python companion, Step 6 docstring | "We format accordingly" is mildly documentation-voice. | Rewrite to more natural phrasing. |

---

## Priority Actions

1. **Write the main recipe (CRITICAL).** This blocks all further progress. The Python companion is ready. The main recipe needs: Problem section (why ED prediction matters, the human cost of avoidable ED visits), Technology section (vendor-agnostic teaching of predictive modeling for ED utilization, feature engineering challenges, the avoidable-vs-unavoidable distinction), General Architecture, AWS implementation, Prerequisites, Pseudocode, Expected Results, Honest Take, Variations, Resources.

2. **Fix A1 (HIGH) in Python companion.** The per-patient explanation method needs either normalization or a prominent warning. This is the only technical finding that could actively mislead clinical users.

3. **Address S1-S3 and A2-A3 (MEDIUM) in main recipe.** Most of these findings belong in the main recipe's Prerequisites table and architecture sections. The Python companion's Gap to Production section already identifies most of these gaps; the main recipe needs to address them structurally.

4. **Re-review after main recipe is written.** This expert review is incomplete. Once the main recipe exists, a full review of architecture, security posture, networking, and voice can be conducted against the complete recipe pair.

---

*Review complete. Recipe 7.4 cannot pass in its current state because the main recipe file does not exist. The Python companion is well-crafted and demonstrates strong clinical awareness, appropriate model selection, and comprehensive gap-to-production coverage. Once the main recipe is written, the recipe pair has strong potential to pass with the HIGH finding (A1) addressed. The code review (chapter07.04-code-review.md) also noted the missing main recipe as a consistency-check blocker.*
