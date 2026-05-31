# Expert Review: Recipe 7.5 - 30-Day Readmission Risk

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Review date:** 2026-05-31
**Complexity rating:** Appropriate (Medium / Growth phase)
**Overall assessment:** PASS

---

## Executive Summary

Recipe 7.5 is a strong, well-structured recipe that covers one of the most important and well-studied predictive analytics problems in healthcare. The clinical framing is accurate, the technology explanation is thorough and appropriately nuanced, and the architecture is sound for the stated scale. The "Honest Take" section is excellent and reflects genuine operational experience with readmission prediction deployments.

The recipe correctly identifies the key challenges (base rate imbalance, information availability at scoring time, social determinant gaps, calibration drift) and provides actionable guidance for each. The feature categories are clinically appropriate and the model approach recommendations (gradient boosted trees as the practical sweet spot) align with published literature and real-world deployments.

No CRITICAL findings. Three HIGH findings related to security controls, architectural completeness, and a missing fairness implementation detail. These are addressable without restructuring the recipe.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### S1 - HIGH: IAM Permissions List Lacks Resource-Level Scoping

**Location:** Prerequisites table, "IAM Permissions" row

**Issue:** The IAM permissions are listed as bare actions (`sagemaker:InvokeEndpoint`, `healthlake:SearchWithGet`, `dynamodb:PutItem`, etc.) without resource ARN scoping. In a healthcare environment, a Lambda with `dynamodb:PutItem` on `*` can write to any DynamoDB table in the account, not just the risk score table. Similarly, `sagemaker:InvokeEndpoint` on `*` allows invoking any endpoint, including endpoints in other projects that may have different access controls.

**Why it matters:** HIPAA's minimum necessary standard requires that each component access only the specific resources it needs. An overly broad IAM policy is a compliance finding in most healthcare security audits and creates lateral movement risk if a Lambda is compromised.

**Suggested fix:** Add a note after the permissions list: "All permissions should be scoped to specific resource ARNs. Example: `sagemaker:InvokeEndpoint` should target `arn:aws:sagemaker:{region}:{account}:endpoint/readmission-risk-*`, not `*`. The scoring Lambda, training pipeline, and monitoring functions should use separate IAM roles with distinct permission boundaries." This doesn't need to be a full IAM policy example (the pseudocode is already simplified), but the principle of resource-level scoping should be stated explicitly.

---

#### S2 - HIGH: SNS Alert Message Contains PHI-Adjacent Data Without Access Controls

**Location:** Step 4 pseudocode, `SNS_PUBLISH` call; also Python companion Step 7

**Issue:** The SNS notification for high-risk patients includes the patient_id, primary_diagnosis, facility_id, and (in the Python companion) the risk drivers with specific clinical values (e.g., "admissions_past_6mo=3", "albumin_last=2.8"). SNS messages are delivered to all subscribers of the topic. If the topic has email subscribers, this data traverses email (which is not encrypted end-to-end). If the topic has HTTP/HTTPS subscribers, the endpoint must be validated as HIPAA-compliant.

The recipe mentions SNS is HIPAA-eligible (correct), but doesn't address that the message content itself contains individually identifiable health information (patient ID + clinical indicators = PHI under HIPAA). The BAA covers the service, but the organization is still responsible for ensuring the delivery endpoints are appropriate for PHI.

**Suggested fix:** Add a note in the SNS section: "SNS messages containing patient identifiers and clinical indicators constitute PHI. Restrict topic subscriptions to HIPAA-compliant endpoints only (Lambda functions, SQS queues within your VPC, or HTTPS endpoints covered under your BAA). Do not use email or SMS subscriptions for high-risk alerts containing patient-level data. If email notification is required, send a minimal alert ('1 new high-risk discharge requires review') with a link to the secure care management dashboard rather than embedding clinical details in the message body."

---

#### S3 - MEDIUM: CloudTrail Guidance Lacks Specificity for PHI Access Auditing

**Location:** Prerequisites table, "CloudTrail" row

**Issue:** The CloudTrail entry says "Enabled for all API calls. Critical for HIPAA audit trail: who accessed which patient's risk score, when, and from where." This is directionally correct but CloudTrail alone doesn't answer "who accessed patient X's risk score." CloudTrail logs the DynamoDB `GetItem` API call with the IAM principal, but the item key (patient_id) is not logged in CloudTrail data events by default for DynamoDB. You'd see "role/scoring-lambda called GetItem on table readmission-risk-scores" but not which patient was queried.

**Suggested fix:** Add: "Enable CloudTrail data events for the DynamoDB risk score table. Note that DynamoDB data events log the table name and API action but not the item key. For patient-level access auditing, implement application-level audit logging: each system that reads a risk score should log the patient_id, requesting user/system identity, and timestamp to a dedicated audit log (CloudWatch Logs or a separate DynamoDB audit table). This is required to answer HIPAA audit questions like 'who viewed patient X's readmission risk score?'"

---

#### S4 - MEDIUM: No Mention of Data Retention Policy for Risk Scores

**Location:** Step 4 pseudocode, DynamoDB TTL setting

**Issue:** The recipe sets a DynamoDB TTL of 45 days (discharge_date + 45 days). This is operationally sensible (scores expire after the measurement window closes). However, there's no discussion of whether this meets or conflicts with organizational data retention requirements. Many healthcare organizations have minimum retention periods for clinical decision support outputs (often 6-7 years for Medicare patients, matching the False Claims Act statute of limitations). If the risk score influenced a clinical decision (e.g., enrolling a patient in a care transition program), it may need to be retained as part of the medical record.

**Suggested fix:** Add a note in the DynamoDB section or "Honest Take": "The 45-day TTL keeps the operational table lean, but your compliance team may require longer retention of risk scores that influenced clinical decisions. Consider archiving expired scores to S3 (with appropriate lifecycle policies) before TTL deletion. If your organization treats ML-generated risk scores as part of the clinical record, retention requirements may extend to 6-10 years depending on state law and payer contracts."

---

#### S5 - LOW: Sample Data Section Could Mention De-identification Requirements

**Location:** Prerequisites table, "Sample Data" row

**Issue:** The recipe correctly says "Never use real PHI in development" and points to MIMIC-III/IV and CMS Synthetic files. This is good. However, it doesn't mention that when you eventually validate the model on real patient data (which you must do before production deployment), that validation dataset needs to be handled under full HIPAA controls even in a development/staging environment.

**Suggested fix:** Add one sentence: "Model validation on real patient data requires a HIPAA-compliant environment with appropriate access controls, even in pre-production. Use a dedicated validation environment with the same security controls as production."

---

### Architecture Expert Review

#### A1 - HIGH: No Discussion of Model Versioning and Rollback Strategy

**Location:** Model Scoring section and Step 5 (Outcome Tracking)

**Issue:** The recipe mentions "model_version" in the output and "monthly retraining" in the lifecycle section, but doesn't address what happens when a newly retrained model performs worse than the previous version. The architecture diagram shows a direct arrow from "SageMaker Training" to the scoring endpoint. In practice, you need a model registry, a shadow scoring period (score with both old and new models, compare), and a rollback mechanism.

This is architecturally important because a bad model deployment in a readmission prediction system has direct patient impact: if the new model under-predicts risk, high-risk patients don't get interventions. If it over-predicts, you overwhelm your care transition team with false positives and they start ignoring alerts (alert fatigue).

**Suggested fix:** Add a paragraph in the "Model Lifecycle" section of the architecture: "Before promoting a retrained model to the production endpoint, run shadow scoring for 1-2 weeks: score each discharge with both the current and candidate models, compare predictions, and validate that the candidate's calibration and discrimination meet minimum thresholds (AUC >= current model AUC - 0.02, calibration slope between 0.85 and 1.15). SageMaker Model Registry tracks model versions and approval status. Use SageMaker endpoint production variants to run A/B testing or canary deployments. Always maintain the ability to roll back to the previous model version within minutes."

---

#### A2 - MEDIUM: Feature Store Architecture Is Underspecified

**Location:** Architecture diagram, "S3 Feature Store (Parquet)" box

**Issue:** The architecture shows an "S3 Feature Store (Parquet)" for historical features, but the interaction between real-time feature assembly (from HealthLake) and pre-computed historical features (from S3/Glue) is not well-defined. At scoring time, the Step Functions workflow needs to: (1) query HealthLake for current encounter data, and (2) look up pre-computed historical features for this patient. The second lookup implies either a DynamoDB table keyed by patient_id with pre-computed features, or a real-time query against the Parquet files in S3 (which would be slow).

The recipe's pseudocode in Step 2 queries HealthLake for historical encounters (prior_encounters, prior_ed_visits), which suggests computing historical features in real time rather than using pre-computed values. This is fine for low volume but becomes a latency concern at scale (querying 12 months of encounter history per patient at scoring time).

**Suggested fix:** Clarify the feature assembly strategy: "For production deployments with >100 discharges/day, pre-compute historical utilization features (admissions_past_6mo, ed_visits_past_6mo, prior_30day_readmission) in a nightly Glue job and store them in DynamoDB keyed by patient_id. The scoring workflow then queries HealthLake only for current-encounter features (which are small and fast) and looks up pre-computed historical features from DynamoDB (single-digit millisecond latency). This hybrid approach keeps scoring latency under 500ms even for patients with extensive utilization history."

---

#### A3 - MEDIUM: Missing Dead Letter Queue for Failed Scoring Events

**Location:** Architecture diagram, Event Processing section

**Issue:** The architecture shows EventBridge triggering Step Functions, but doesn't address what happens when the Step Functions execution fails (HealthLake timeout, SageMaker endpoint unavailable, DynamoDB throttling). The recipe mentions "Step Functions coordinates this sequence and provides visibility into failures" and "retries with backoff," but doesn't specify a dead letter queue or alerting mechanism for permanently failed scoring attempts.

A patient whose scoring fails silently is worse than a patient who scores as low-risk, because at least the low-risk patient was evaluated. A failed scoring means nobody knows the patient's risk level.

**Suggested fix:** Add to the architecture: "Configure an SQS dead letter queue for the EventBridge rule. Discharge events that fail to trigger Step Functions (or whose Step Functions execution fails after maximum retries) land in the DLQ. A CloudWatch alarm on DLQ depth > 0 alerts the operations team. A separate Lambda processes DLQ messages daily, attempting to re-score patients whose initial scoring failed. Any patient not scored within 24 hours of discharge should be flagged for manual review by the care transition team."

---

#### A4 - MEDIUM: Cost Estimate Doesn't Account for HealthLake Query Volume

**Location:** Prerequisites table, "Cost Estimate" row

**Issue:** The cost estimate mentions HealthLake at "$0.60/GB stored + $0.09 per 1000 read operations." But the feature assembly step (Step 2) makes 5-7 FHIR search queries per patient (Encounter, Condition, MedicationRequest, Observation, Procedure, plus historical lookups). At 100 discharges/day, that's 500-700 HealthLake read operations per day just for scoring. The cost is negligible ($0.063/day), but the latency impact of 5-7 sequential FHIR queries is not addressed. Each HealthLake search can take 100-500ms depending on result set size, meaning feature assembly alone could take 1-3 seconds.

**Suggested fix:** Add a latency note: "Feature assembly from HealthLake involves 5-7 FHIR search queries per patient. Parallelize independent queries (Condition, MedicationRequest, and Observation searches can run concurrently) to reduce assembly latency from 2-3 seconds (sequential) to under 1 second (parallel). The cost impact is negligible at typical discharge volumes, but latency is the real constraint for meeting the <2 hour scoring SLA."

---

#### A5 - LOW: The "TODO" in Additional Resources Should Be Resolved

**Location:** Additional Resources, Industry References section

**Issue:** There's a `TODO: Verify current URL for Yale/CMS readmission measure methodology documentation` at the end of the Industry References section. This should be resolved before publication.

**Suggested fix:** Either find and verify the URL (the Yale/CORE readmission measures methodology is published at https://qualitynet.cms.gov/ under the Hospital Inpatient Quality Reporting program), or remove the TODO and add a general reference: "CMS Quality Measures documentation at qualitynet.cms.gov includes the detailed risk-adjustment methodology for each HRRP condition."

---

### Networking Expert Review

#### N1 - MEDIUM: VPC Endpoint List Is Incomplete

**Location:** Prerequisites table, "VPC" row

**Issue:** The VPC section says "SageMaker endpoints, Glue jobs, and Lambda functions in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, and CloudWatch Logs. HealthLake accessed via VPC endpoint." This is a good start but misses several endpoints needed by the full architecture:

- `com.amazonaws.{region}.states` (Step Functions, needed for Lambda to report back to the workflow)
- `com.amazonaws.{region}.sns` (for publishing high-risk alerts from within VPC)
- `com.amazonaws.{region}.events` (EventBridge, if the event processing Lambda is in VPC)

Without these, traffic to Step Functions, SNS, and EventBridge would traverse the public internet or NAT gateway, which adds latency and (for NAT) cost.

**Suggested fix:** Expand the VPC endpoint list to include all services accessed from within the VPC: "VPC endpoints required: S3 (gateway), DynamoDB (gateway), SageMaker Runtime (interface), HealthLake (interface), CloudWatch Logs (interface), Step Functions/states (interface), SNS (interface). If EventBridge rules trigger Lambda functions within the VPC, also add the EventBridge interface endpoint."

---

#### N2 - LOW: No Mention of HealthLake VPC Endpoint Availability

**Location:** Prerequisites table, "VPC" row

**Issue:** The recipe states "HealthLake accessed via VPC endpoint." Amazon HealthLake does support VPC endpoints (interface type), but this is a relatively newer capability. The recipe should confirm this is available in the target region, as HealthLake itself has limited regional availability compared to services like S3 or DynamoDB.

**Suggested fix:** Add a brief note: "Verify HealthLake and its VPC endpoint are available in your target region. HealthLake has more limited regional availability than other services in this architecture. If HealthLake is not available in your primary region, consider a cross-region architecture with appropriate data residency controls, or use a FHIR server on EC2/ECS as an alternative."

---

### Voice Reviewer

#### V1 - LOW: Minor Doc-Voice Creep in One Sentence

**Location:** "Why These Services" section, first paragraph about SageMaker

**Issue:** "SageMaker provides managed real-time endpoints with auto-scaling, plus the training infrastructure for periodic model retraining." This reads slightly like documentation voice (feature listing). The rest of the "Why These Services" section is well-written and conversational.

**Suggested fix:** Minor. Could be rephrased to: "SageMaker gives you managed real-time endpoints that auto-scale, plus the training infrastructure for periodic retraining." But this is nitpicking; the sentence is functional and clear.

---

#### V2 - PASS: No Em Dashes Found

The recipe uses no em dashes throughout. Commas, colons, semicolons, parentheses, and periods are used appropriately as alternatives.

---

#### V3 - PASS: Vendor Balance Is Appropriate

The recipe maintains the 70/30 split well. The Problem, Technology, and General Architecture Pattern sections are entirely vendor-agnostic. AWS services appear only in "The AWS Implementation" section and below. A reader on GCP or Azure would learn substantial value from the first half of the recipe.

---

#### V4 - PASS: Tone Is Consistent

The voice throughout matches the style guide: engineer explaining something they've built, with appropriate self-deprecating honesty ("The model is the easy part"), practical wisdom ("Clinician buy-in requires transparency"), and genuine enthusiasm for the problem space. The "Honest Take" section is particularly strong.

---

## Stage 2: Expert Discussion

**Security vs. Architecture overlap:** The SNS PHI concern (S2) and the DLQ concern (A3) interact. If a failed scoring event lands in a DLQ and the DLQ message contains patient identifiers, the DLQ itself becomes a PHI store that needs encryption and access controls. Resolution: the DLQ should contain only the discharge event metadata (patient_id, encounter_id, discharge_date) needed to retry scoring, not clinical data. This is consistent with the minimum necessary principle.

**Architecture vs. Networking overlap:** The feature assembly latency concern (A4) is partly a networking issue. If HealthLake queries traverse a VPC endpoint, the endpoint adds minimal latency (<1ms). But if the Lambda is in a different AZ than the HealthLake VPC endpoint ENI, cross-AZ latency adds 1-2ms per query. With 5-7 queries, this is negligible. No conflict here.

**Priority resolution:** S2 (SNS PHI in messages) is the highest-priority fix because it's a compliance risk that could surface in a HIPAA audit. A1 (model versioning) is the highest-priority architecture fix because deploying a bad model has direct patient safety implications.

---

## Stage 3: Synthesized Findings

### Verdict: PASS

The recipe is well-written, clinically accurate, architecturally sound, and provides actionable guidance. The three HIGH findings are important for production readiness but don't represent fundamental flaws in the approach. They're the kind of details that distinguish a "good enough for a cookbook recipe" from "ready to deploy Monday morning," and the recipe's own "Gap to Production" framing acknowledges this distance.

### Prioritized Findings

| # | Severity | Expert | Location | Issue | Fix |
|---|----------|--------|----------|-------|-----|
| S1 | HIGH | Security | Prerequisites, IAM Permissions | IAM permissions lack resource-level scoping guidance | Add note about scoping to specific ARNs; separate roles for scoring vs. training |
| S2 | HIGH | Security | Step 4 pseudocode, SNS publish | SNS alert messages contain PHI without delivery endpoint controls | Add guidance on restricting subscriptions to HIPAA-compliant endpoints; minimize message content |
| A1 | HIGH | Architecture | Model Lifecycle section | No model versioning, shadow scoring, or rollback strategy | Add paragraph on shadow scoring, Model Registry, and rollback mechanism |
| S3 | MEDIUM | Security | Prerequisites, CloudTrail | CloudTrail alone doesn't provide patient-level access auditing | Add application-level audit logging requirement |
| S4 | MEDIUM | Security | Step 4, DynamoDB TTL | No discussion of retention requirements for clinical decision support outputs | Add note about archiving scores and compliance retention periods |
| A2 | MEDIUM | Architecture | Architecture diagram, Feature Store | Feature store interaction pattern underspecified for production latency | Clarify hybrid approach: pre-computed historical features in DynamoDB + real-time current encounter from HealthLake |
| A3 | MEDIUM | Architecture | Event Processing section | No dead letter queue for failed scoring events | Add DLQ, CloudWatch alarm, and manual review fallback for unscored patients |
| A4 | MEDIUM | Architecture | Prerequisites, Cost Estimate | HealthLake query latency not addressed | Add note about parallelizing FHIR queries for feature assembly |
| N1 | MEDIUM | Networking | Prerequisites, VPC | VPC endpoint list incomplete (missing states, SNS) | Expand list to include all services accessed from VPC |
| A5 | LOW | Architecture | Additional Resources | Unresolved TODO for Yale/CMS URL | Resolve or remove the TODO before publication |
| S5 | LOW | Security | Prerequisites, Sample Data | No mention of validation environment PHI controls | Add one sentence about HIPAA-compliant validation environments |
| N2 | LOW | Networking | Prerequisites, VPC | HealthLake regional availability not noted | Add brief note about regional availability check |
| V1 | LOW | Voice | Why These Services, SageMaker paragraph | Minor doc-voice in one sentence | Optional rephrase; not blocking |

### What's Done Well

- **Clinical accuracy.** The HRRP penalty structure, base rate discussion, feature categories, and model performance expectations all align with published literature and real-world experience.
- **Calibration emphasis.** Calling out calibration as "the most underrated requirement" is exactly right and often missed in ML cookbooks.
- **Fairness framing.** The ethical framing ("are you using the score to help or penalize?") is thoughtful and appropriate for the audience.
- **Honest Take section.** Genuinely useful operational wisdom. "The model is the easy part" and "the intervention matters more than the prediction" are the two most important lessons for anyone building this system.
- **Feature importance for clinical adoption.** The recipe correctly identifies that clinician buy-in requires explainability, not just accuracy.
- **Appropriate scope.** The recipe doesn't over-promise on model performance (C-statistic 0.68-0.75 is honest) and correctly frames the limitations.

---

*Review complete. The recipe is publication-ready after addressing the HIGH findings. MEDIUM and LOW findings are improvements that strengthen the recipe but don't block publication.*
