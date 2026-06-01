# Expert Review: Recipe 15.7 - Chronic Disease Treatment Personalization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter15.07-chronic-disease-treatment-personalization.md` (MISSING; review based on `chapter15.07-python-example.md`)

---

## Overall Assessment

**Verdict: FAIL**

The main recipe file does not exist. The Python companion is present and contains a complete, clinically sound RL pipeline for type 2 diabetes treatment personalization. The RL formulation is appropriate (BCQ for offline learning, quarterly decision intervals, multi-objective reward, hard safety constraints). The clinical domain knowledge is accurate and well-sourced (ADA Standards of Care, appropriate treatment escalation pathways, correct contraindication logic). However, the absence of the main recipe is a CRITICAL structural issue: the cookbook's pipeline requires the main recipe to exist before the Python companion, and readers navigating from the sidebar or adjacent recipes will hit a dead link. Beyond this structural failure, the Python companion itself has security gaps, an architectural concern around the missing main recipe's architecture diagram, and a misleading OPE claim.

Priority breakdown: 1 critical issue, 2 high issues, 4 medium issues, 3 low issues.

---

## Security Expert Review

### What's Done Well

- BAA requirement explicitly stated in Setup section ("You'll need a signed BAA because longitudinal treatment data is PHI regardless of de-identification status")
- IAM permissions listed with specific actions (not wildcards)
- Retry configuration with adaptive mode (prevents credential exposure on repeated failures)
- Logging configured with explicit warning: "Never log patient identifiers or PHI values"
- DynamoDB used for patient state (encryption at rest by default)
- S3 bucket naming suggests separation of training data from operational data
- The "Gap to Production" section explicitly calls out: IAM least-privilege, VPC + VPC endpoints, KMS CMKs, structured JSON logging with correlation IDs

### Issue S1: No Encryption Specification for Patient State Table (MEDIUM)

**Location:** Config and Constants section, `DYNAMODB_TABLE = "patient-diabetes-state"`

**The problem:** The DynamoDB table stores longitudinal patient diabetes state (HbA1c history, treatment levels, comorbidities, adherence data). This is PHI. While DynamoDB encrypts at rest by default with AWS-owned keys, the recipe does not specify customer-managed KMS keys (CMKs). For a system storing multi-year treatment histories, customer-managed keys provide key rotation control, cross-account access control, and the ability to revoke access by disabling the key. The "Gap to Production" section mentions KMS CMKs but the code and configuration do not demonstrate or specify them.

**Suggested fix:** Add to the Config section:
```python
# KMS key for DynamoDB encryption. Use a customer-managed key (CMK)
# for patient state tables. AWS-owned keys don't give you rotation
# control or the ability to revoke access by disabling the key.
# KMS_KEY_ARN = "arn:aws:kms:us-east-1:ACCOUNT:key/YOUR-KEY-ID"
```

### Issue S2: IAM Permissions Not Scoped to Resources (HIGH)

**Location:** Setup section, IAM permission list

**The problem:** The listed permissions (`sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `s3:GetObject`, `s3:PutObject`, `cloudwatch:PutMetricData`) are a flat list without resource ARN constraints. A role with `dynamodb:PutItem` on all tables could write to any DynamoDB table in the account. A role with `s3:PutObject` on all buckets could overwrite model artifacts or training data. For a system processing multi-year patient treatment histories (PHI), the blast radius of a compromised credential must be minimized.

**Suggested fix:** Replace the flat list with resource-scoped guidance:
```
IAM role needs:
- sagemaker:InvokeEndpoint on arn:aws:sagemaker:REGION:ACCOUNT:endpoint/chronic-dm-rl-policy-v1
- dynamodb:GetItem, PutItem, Query on arn:aws:dynamodb:REGION:ACCOUNT:table/patient-diabetes-state
- s3:GetObject, PutObject on arn:aws:s3:::chronic-dm-rl-training/episodes/*
- cloudwatch:PutMetricData (no resource scoping available for this action)
Separate roles for training pipeline vs. inference vs. state management.
```

### Issue S3: No Audit Trail for Treatment Recommendations (MEDIUM)

**Location:** Step 7 (`generate_treatment_recommendation`), the function returns a recommendation dict but does not persist it

**The problem:** The `generate_treatment_recommendation` function returns a recommendation to the caller but does not log it to an immutable audit store. For a clinical decision support system recommending diabetes treatment changes, every recommendation (including the safety constraints that activated, the clinician's final decision, and the patient outcome at the next visit) must be logged with tamper-evidence. The "Gap to Production" section mentions "every recommendation, every clinician decision, every override reason" but the code demonstrates no audit pattern.

**Suggested fix:** Add after the recommendation is constructed:
```python
# In production: write recommendation to an append-only audit store.
# Use S3 with Object Lock (compliance mode) or CloudWatch Logs with
# a resource policy preventing deletion. The operational store (DynamoDB)
# serves real-time reads; the immutable archive serves compliance.
```

### Issue S4: Patient State Update Has No Optimistic Locking (LOW)

**Location:** Step 7, where `patient_data` is updated with new visit data and presumably written back to DynamoDB

**The problem:** If two concurrent requests update the same patient's state (unlikely in quarterly visits but possible in a multi-provider scenario), the last write wins without detection. DynamoDB conditional writes with version attributes prevent lost updates.

**Suggested fix:** Note in the code: "In production, use a version attribute with ConditionExpression to prevent concurrent write conflicts on patient state."

---

## Architecture Expert Review

### What's Done Well

- BCQ (Batch-Constrained Q-Learning) is the correct algorithmic choice for chronic disease: conservative, stays close to observed clinician behavior, prevents recommending untested treatment combinations
- Quarterly decision interval correctly matches HbA1c measurement cadence (3-month average)
- Safety constraint layer is correctly implemented as hard rule-based overrides (not learned), providing defense-in-depth
- The treatment action space is clinically appropriate and ordered by escalation level
- The reward function is multi-objective (glycemic control, hypoglycemia avoidance, treatment burden, adherence appropriateness), which correctly reflects clinical priorities
- The "Gap to Production" section is exceptionally thorough and honest (3-5 years from prototype to clinical use)
- Discount factor of 0.95 is appropriate for quarterly decisions over multi-year horizons
- Episode construction correctly handles the temporal structure (reward for today's decision observed 3 months later)

### Issue A1: Main Recipe File Missing (CRITICAL)

**Location:** Expected at `chapter15.07-chronic-disease-treatment-personalization.md`

**The problem:** The main recipe file does not exist. The Python companion exists and references it. The sidebar links to it. The previous recipe (15.06) links to it in navigation. The code review explicitly notes its absence. Per the RECIPE-GUIDE.md, the main recipe provides: the Problem statement, the vendor-agnostic Technology explanation, the General Architecture Pattern, the AWS-specific implementation with architecture diagram, Prerequisites table, Ingredients table, pseudocode walkthrough, Expected Results, Honest Take, Variations, and Related Recipes. Without the main recipe, readers have no vendor-agnostic conceptual foundation, no architecture diagram, no prerequisites table, no cost estimates, and no pseudocode that the Python companion is supposed to implement. The Python companion is orphaned.

**Suggested fix:** The main recipe must be written before this recipe can pass review. The Python companion cannot stand alone per the cookbook's structure.

### Issue A2: Tabular Q-Learning Won't Scale to the State Space (MEDIUM)

**Location:** Step 5 (`train_bcq_policy`), `_state_to_index` function

**The problem:** The implementation discretizes the 16-dimensional state into 8^3 = 512 bins using only 3 features (hba1c_current, current_treatment_level, medication_adherence). This is acknowledged as a simplification ("production would use neural networks"), but the pedagogical concern is that readers may not appreciate how severe the information loss is. The other 13 state features (age, BMI, eGFR, cardiovascular risk, heart failure, comorbidity count, diabetes duration, etc.) are computed and normalized but then completely ignored by the policy. A patient with eGFR 25 (severe kidney disease) and a patient with eGFR 90 (normal) get the same Q-value lookup if their HbA1c, treatment level, and adherence match. The safety constraints catch the contraindication, but the policy itself is blind to it.

**Suggested fix:** Add a comment in `_state_to_index` acknowledging this limitation explicitly: "WARNING: This 3-feature discretization discards 13 state features entirely. The policy cannot learn patient-specific treatment responses based on renal function, cardiovascular risk, age, or comorbidities. In production, use a neural network Q-function that takes the full 16-dimensional state vector as input. The safety constraint layer partially compensates for this limitation but cannot learn nuanced preferences."

### Issue A3: No Discussion of Model Versioning or Retraining Cadence (LOW)

**Location:** Gap to Production section

**The problem:** The Gap to Production section discusses retraining when "treatment guidelines change" but does not specify how model versions are tracked, how a new policy is validated against the previous one, or what triggers retraining. For a chronic disease system where outcomes take months to observe, the retraining cadence and validation pipeline are architecturally significant.

**Suggested fix:** Add to Gap to Production: "Retraining cadence: quarterly or when new drug classes enter the formulary. Each retrained policy must pass OPE against the previous production policy on a held-out validation cohort before promotion. Maintain model lineage: which training data, which hyperparameters, which OPE results led to each deployed version."

---

## Networking Expert Review

### What's Done Well

- The Gap to Production section explicitly calls out "VPC with VPC endpoints for all AWS services handling PHI"
- No egress to external services in the inference path (all AWS-internal)
- SageMaker endpoint invocation stays within the AWS network

### Issue N1: No VPC Endpoint Specification (MEDIUM)

**Location:** Gap to Production section, "VPC with VPC endpoints for all AWS services handling PHI"

**The problem:** The statement is correct but insufficiently specific. The recipe uses DynamoDB, SageMaker Runtime, S3, and CloudWatch. Each needs a VPC endpoint to avoid PHI traversing the public internet. The recipe should enumerate which endpoint types (gateway vs. interface) are needed for each service, since this is a common implementation stumbling block.

**Suggested fix:** Expand the VPC guidance: "VPC endpoints needed: S3 (gateway endpoint, free), DynamoDB (gateway endpoint, free), SageMaker Runtime (interface endpoint), CloudWatch (interface endpoint). Gateway endpoints have no hourly cost; interface endpoints cost ~$7.50/month per AZ. Deploy the SageMaker endpoint in VPC mode to keep inference traffic off the public internet."

### Issue N2: SageMaker Endpoint Not Specified as VPC-Mode (LOW)

**Location:** Config section, `SAGEMAKER_ENDPOINT = "chronic-dm-rl-policy-v1"`

**The problem:** The endpoint is named but there's no indication it should be deployed in VPC mode. A SageMaker endpoint not in VPC mode means inference requests (containing patient state vectors derived from PHI) traverse the public AWS network rather than staying within the VPC.

**Suggested fix:** Add a comment: "# Deploy this endpoint in VPC mode (VpcConfig in CreateEndpointConfig) # to keep inference traffic within your VPC. Required for PHI workloads."

---

## Voice Reviewer

### What's Done Well

- The Python companion's prose is excellent: engineer-explaining-something-cool tone throughout
- Comments are generous, accessible, and explain clinical reasoning ("HbA1c takes 3 months to reflect a treatment change. Switching sooner means you never saw the effect of the current regimen.")
- Self-deprecating honesty in the Gap to Production ("This example is maybe 3% of a production system")
- The opening callout is appropriately cautious without being defensive
- Clinical domain knowledge is woven naturally into code comments rather than presented as dry reference material
- The 70/30 vendor balance is maintained: the RL concepts, reward design, and clinical logic are vendor-agnostic; AWS appears only in the infrastructure layer

### Issue V1: Em Dash Check (PASS)

**Location:** Full file scan

**Result:** No em dashes found. The file uses colons, semicolons, periods, and parentheses for clause separation. Clean pass.

### Issue V2: Cannot Assess Main Recipe Voice (N/A)

**Location:** `chapter15.07-chronic-disease-treatment-personalization.md` (missing)

**The problem:** The main recipe file does not exist, so voice consistency for the Problem statement, Technology section, and Honest Take cannot be assessed. The Python companion's voice is strong, but the main recipe is where voice matters most (it serves the mixed audience including executives and non-technical readers).

### Issue V3: Minor Doc-Voice in One Comment (LOW)

**Location:** Step 5, `train_bcq_policy` docstring, final sentence

**The problem:** "For chronic disease, start conservative. Clinicians have decades of experience encoded in their treatment patterns." The second sentence is good. But "start conservative" is slightly prescriptive/doc-voice. The rest of the file uses a more conversational register.

**Suggested fix:** Minor. Consider: "For chronic disease, lean conservative. Clinicians have decades of experience encoded in their treatment patterns, and the BCQ threshold is how you express respect for that experience in code."

---

## Stage 2: Expert Discussion

### Cross-Expert Agreements

1. **Architecture + All Experts:** The missing main recipe (A1) is the dominant issue. Without it, Security cannot assess the Prerequisites table or architecture diagram for IAM/encryption/VPC completeness. Networking cannot assess VPC endpoint specifications. Voice cannot assess the Problem/Technology sections. Architecture cannot assess the general architecture pattern or cost estimates. The Python companion is orphaned content.

2. **Security + Architecture:** The IAM scoping issue (S2) and the audit trail gap (S3) are both present in the Python companion but would normally be addressed in the main recipe's Prerequisites table and architecture diagram. Their presence here reflects the missing main recipe rather than a Python companion deficiency.

3. **Architecture + Voice:** The tabular Q-learning limitation (A2) is well-acknowledged in prose ("production would use neural networks") but the code's `_state_to_index` function silently discards 13 features without a warning comment at the point of use. This is a pedagogical gap: a reader following the code might not realize the policy is blind to most of the state they carefully constructed.

### Priority Resolution

- The CRITICAL issue (missing main recipe) is unambiguous. The cookbook's structure requires it. The Python companion references it. Navigation links point to it. It must exist.
- The two HIGH issues (IAM scoping, OPE mislabeling from code review) are legitimate security and accuracy concerns in the Python companion itself.
- The MEDIUM issues are improvements that strengthen the existing content.
- No conflicts between expert recommendations.

### Note on Code Review Findings

The code review (chapter15.07-code-review.md) identified four issues including a WARNING about the OPE function's docstring claiming "weighted importance sampling" when the implementation only computes concordance metrics. This is incorporated as a HIGH finding below because it misleads readers about a safety-critical validation methodology.

---

## Stage 3: Synthesized Findings

### Verdict: **FAIL**

One CRITICAL finding (missing main recipe file) automatically fails the review. The Python companion is technically strong, clinically accurate, and well-written, but it cannot stand alone per the cookbook's structure.

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | CRITICAL | Architecture | Repository root | Main recipe file `chapter15.07-chronic-disease-treatment-personalization.md` does not exist. Python companion is orphaned. Sidebar, navigation, and code review all reference a non-existent file. | Write the main recipe following RECIPE-GUIDE.md structure: Problem, Technology (vendor-agnostic RL for chronic disease), General Architecture, AWS implementation, Prerequisites, pseudocode, Expected Results, Honest Take. |
| 2 | HIGH | Security | Setup section, IAM permissions | Flat permission list without resource ARN constraints. Multi-year patient treatment histories (PHI) require least-privilege with resource scoping. | Scope each permission to specific resource ARNs. Separate roles for inference vs. training vs. state management. |
| 3 | HIGH | Architecture / Code Review | Step 6, `evaluate_policy_offline` docstring | Docstring claims "weighted importance sampling" but implementation only computes agreement rate and average treatment levels. Misleads readers about a safety-critical validation methodology. | Change docstring to "Evaluate learned policy using concordance metrics against clinician decisions." Add comment noting IS/DR estimators omitted for simplicity. |
| 4 | MEDIUM | Security | Config section, DynamoDB table | No encryption specification (CMK) for patient state table storing multi-year PHI. Default AWS-owned keys lack rotation control and revocation capability. | Add comment specifying customer-managed KMS key requirement for the patient state table. |
| 5 | MEDIUM | Security | Step 7, `generate_treatment_recommendation` | No audit trail pattern for treatment recommendations. Clinical decision support outputs must be logged immutably for regulatory and legal defensibility. | Add comment demonstrating audit write to S3 Object Lock or append-only log. |
| 6 | MEDIUM | Architecture | Step 5, `_state_to_index` | Tabular discretization silently discards 13 of 16 state features. Readers may not realize the policy is blind to renal function, cardiovascular risk, age, etc. | Add explicit WARNING comment at the discretization point noting the information loss and its clinical implications. |
| 7 | MEDIUM | Networking | Gap to Production, VPC section | VPC endpoint guidance is a single sentence without specifying which endpoints (gateway vs. interface) are needed for each service. | Enumerate: S3 (gateway), DynamoDB (gateway), SageMaker Runtime (interface), CloudWatch (interface). Note cost differences. |
| 8 | LOW | Security | Step 7, patient state update | No optimistic locking on DynamoDB writes. Concurrent updates could cause lost writes (unlikely for quarterly visits but possible in multi-provider scenarios). | Add comment noting version attribute + ConditionExpression for production. |
| 9 | LOW | Networking | Config section, SageMaker endpoint | Endpoint not specified as VPC-mode. Inference requests containing PHI-derived state vectors would traverse public AWS network. | Add comment specifying VpcConfig requirement in CreateEndpointConfig. |
| 10 | LOW | Voice | Step 5, `train_bcq_policy` docstring | Minor doc-voice ("start conservative") in otherwise conversational prose. | Rephrase to match the file's conversational register. |

---

## Clinical Accuracy Assessment

Despite the missing main recipe, the Python companion demonstrates strong clinical accuracy for type 2 diabetes management:

**RL Formulation:**
- **State space** is clinically comprehensive: HbA1c (current + trend), hypoglycemia burden, current treatment level and duration, patient factors (age, BMI, eGFR, CV risk, heart failure), adherence metrics, and comorbidity burden. These are the variables an endocrinologist considers at a quarterly visit.
- **Action space** (8 treatment levels from lifestyle-only through intensive insulin) correctly represents the ADA treatment escalation pathway. The ordering is clinically appropriate.
- **Reward function** correctly implements multi-objective optimization: glycemic control is primary, but hypoglycemia avoidance, treatment burden minimization, and adherence-appropriateness are all weighted. The asymmetric penalties (severe hypo penalty of -20 vs. at-target reward of +10) correctly reflect that hypoglycemia is more dangerous than mild hyperglycemia.
- **Decision interval** of 3 months correctly matches HbA1c measurement cadence.

**Safety Constraints:**
- Maximum escalation/de-escalation speed: clinically appropriate (prevents wild treatment swings)
- Minimum duration before change: correct (HbA1c needs 3 months to reflect treatment effect)
- Adherence gating: excellent clinical insight (escalating when the patient isn't taking current meds is the wrong intervention)
- Renal contraindications: correct (metformin contraindicated below eGFR 30, SGLT2 less effective below eGFR 45, per ADA/KDIGO guidelines)
- Insulin avoidance in elderly with hypo history: appropriate (aligns with ADA recommendation for relaxed targets in frail elderly)
- No escalation at target: correct (prevents unnecessary treatment complexity)

**Individualized Targets:**
- Standard 7.0% for most adults: correct per ADA Standards of Care
- Relaxed to 7.5-8.0% for elderly, high comorbidity, severe hypo history: correct per ADA individualization guidance
- The logic is simplified but directionally accurate

**One clinical nuance:** The SGLT2 constraint (action 2 or 5 with eGFR < 45) switches to GLP-1 or DPP-4 alternatives. This is mostly correct, but current guidelines (2024 ADA/KDIGO) actually recommend SGLT2 inhibitors for kidney protection even at eGFR 20-45 in patients with CKD, despite reduced glycemic efficacy. The constraint is conservative (safe) but slightly outdated. This is LOW severity since the safety constraint prevents harm (it doesn't recommend SGLT2 where it might not work for glucose control) even if it misses a kidney-protective benefit.

**Offline RL Methodology:**
- BCQ is appropriate for this setting: small discrete action space, desire to stay close to clinician behavior, consequences of untested actions unfold over months
- The bcq_threshold parameter correctly controls conservatism
- The discount factor of 0.95 is reasonable for quarterly decisions (implies ~5-year effective horizon)

**Regulatory Assessment:**
- The Gap to Production section correctly identifies FDA SaMD classification as likely Class II
- Correctly notes the CDS exemption analysis as relevant
- Correctly identifies the need for predetermined change control plans
- The 3-5 year timeline from prototype to clinical use is realistic and honest

---

## Additional Notes

The Python companion is one of the strongest in Chapter 15 from a clinical accuracy and pedagogical quality standpoint. The code comments explain clinical reasoning at every decision point, the safety constraint layer is comprehensive and correctly motivated, and the Gap to Production section is exceptionally honest about the distance to real deployment. The CRITICAL failure is purely structural (missing main recipe), not a quality issue with the existing content. Once the main recipe is written, this recipe should pass review with the remaining HIGH and MEDIUM fixes applied to the Python companion.
