# Expert Review: Recipe 7.1 - Appointment No-Show Prediction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter07.01-appointment-no-show-prediction.md`

---

## Overall Assessment

This is a strong opening recipe for Chapter 7. The problem framing is compelling and well-grounded in real operational pain. The technology section is genuinely educational, covering binary classification, feature engineering, and the feedback loop properties that make this problem tractable. The vendor-agnostic/AWS split is clean. The "Honest Take" section on fairness and overbooking is one of the best in the cookbook so far.

The recipe is architecturally sound for its stated scope (batch scoring for a mid-size practice). The issues found are primarily around security specificity (IAM permissions are too broad, PHI in DynamoDB needs tighter controls), one architectural gap around model monitoring that contradicts the recipe's own retraining guidance, and a few minor voice/completeness items.

No CRITICAL findings. The recipe passes.

---

## Security Expert Review

### What's Done Well

BAA requirement is explicitly stated with the correct rationale (appointment data contains patient names, DOB, contact info). Encryption at rest is specified for S3 (SSE-KMS), DynamoDB (default), and SageMaker training volumes. TLS in transit is noted. CloudTrail is required. The "never use real patient data in dev" warning is present. The VPC requirement for production is stated with VPC endpoints for S3 and DynamoDB.

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:Query`, `lambda:InvokeFunction`, `sns:Publish`) are listed as a flat set with no resource scoping or role separation. In practice, these permissions span at least four distinct IAM roles:

1. The Glue job execution role (needs S3 read/write on feature buckets, access to data sources)
2. The SageMaker execution role (needs S3 read/write on model/feature buckets, KMS decrypt)
3. The Lambda action engine role (needs DynamoDB read, SNS publish, but NOT SageMaker or Glue)
4. The EventBridge scheduler role (needs to invoke Lambda and start SageMaker transform jobs)

Presenting these as a single permission set implies a single role with all permissions, which violates least-privilege. A builder following this literally creates one role that can train models, score data, read all predictions, and send messages to patients.

**Suggested fix:** Split the IAM Permissions row into role-specific entries, or add a note: "These permissions are distributed across service-specific execution roles. The Lambda action engine role should NOT have SageMaker or Glue permissions. The Glue role should NOT have SNS publish. Scope each role to the minimum permissions for its function and restrict resource ARNs to the specific buckets, tables, and topics used."

### Issue S2: DynamoDB Table Contains PHI Without Access Controls Discussion (HIGH)

**Location:** Step 4 pseudocode (store_predictions), Prerequisites table

**The problem:** The `appointment-predictions` DynamoDB table stores `appointment_id`, `patient_id`, `scheduled_date`, `provider`, and `top_features` (which includes patient behavioral history like no-show rate). This is PHI: it links a patient identifier to health-related behavioral data and provider relationships. The recipe specifies "encryption at rest (default)" for DynamoDB but does not address:

- Item-level access control (who can query predictions for a specific patient?)
- The GSI on `scheduled_date` enables range queries that return all patients for a given day, which is a broader access pattern than needed for individual appointment lookup
- No TTL is specified; predictions for past appointments accumulate indefinitely with no retention policy
- The `features_used` field stores behavioral health data (no-show history) that could be considered sensitive beyond standard scheduling data

**Suggested fix:** Add guidance on: (1) DynamoDB TTL on the table to expire predictions after the appointment date plus a reasonable audit window (e.g., 90 days); (2) IAM condition keys or fine-grained access control to restrict who can perform the date-range GSI query vs. single-appointment lookup; (3) a note that `features_used` contains derived behavioral data and should be treated with the same access controls as the prediction itself.

### Issue S3: SNS/SES Reminder Messages Need PHI Handling Note (MEDIUM)

**Location:** Step 5 pseudocode (run_action_engine), Architecture Diagram

**The problem:** The action engine sends SMS via SNS and email via SES to patients. The `personalized_reminder` function implies message content that references the appointment (date, time, provider, possibly visit type). SMS messages are not encrypted end-to-end and may be stored on carrier systems. The recipe does not note that reminder message content should be minimized to avoid including PHI in an unencrypted channel.

**Suggested fix:** Add a brief note in Step 5 or in the Honest Take: "Reminder messages sent via SMS should contain minimal PHI. Include appointment date/time and a generic prompt ('You have an upcoming appointment') rather than provider name, visit type, or clinical details. SMS is not encrypted end-to-end and messages may persist on carrier infrastructure. For messages requiring clinical detail, use a secure patient portal notification that links to authenticated content."

### Issue S4: VPC Endpoint List Is Incomplete (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The VPC section states "SageMaker training and inference in VPC with VPC endpoints for S3 and DynamoDB." This omits several endpoints needed for the full pipeline:

- SageMaker API endpoint (`com.amazonaws.{region}.sagemaker.api`) for creating training/transform jobs from within VPC
- SageMaker Runtime endpoint (`com.amazonaws.{region}.sagemaker.runtime`) if real-time inference is added later
- SNS endpoint (`com.amazonaws.{region}.sns`) for the Lambda action engine to publish reminders
- SES endpoint (`com.amazonaws.{region}.email-smtp` or `com.amazonaws.{region}.ses`) for email reminders
- CloudWatch Logs endpoint (`com.amazonaws.{region}.logs`) for Lambda and Glue execution logging
- KMS endpoint (`com.amazonaws.{region}.kms`) for decrypting data in S3 and DynamoDB

Only listing S3 and DynamoDB endpoints gives a false sense of completeness.

**Suggested fix:** Expand the VPC row to list the full endpoint set, or add a note: "Additional VPC endpoints required for production: SageMaker API, SNS, CloudWatch Logs, and KMS. The S3 gateway endpoint and DynamoDB gateway endpoint handle data-path traffic; interface endpoints are needed for control-plane API calls from within the VPC."

---

## Architecture Expert Review

### What's Done Well

The four-stage pipeline decomposition (Feature Store, Model Training, Scoring Service, Action Engine) is clean and well-motivated. The separation of concerns principle ("the model predicts, the action engine decides") is correctly emphasized and will save builders from a common anti-pattern. The batch transform choice over real-time endpoints is well-justified for the nightly scoring use case. The cost estimates are reasonable. The "Where it struggles" section is honest and covers the right failure modes (cold start, sudden life events, seasonal shifts).

### Issue A1: No Model Monitoring or Drift Detection in Main Architecture (HIGH)

**Location:** Architecture Diagram, Code section, Prerequisites

**The problem:** The recipe's "Honest Take" section correctly states: "Monitor AUC weekly and trigger an alert if it drops below your baseline." The "Production-ready" tier in the implementation timeline mentions "model monitoring (AUC drift alerts)." But the main architecture diagram, the code walkthrough, and the prerequisites contain zero infrastructure for model monitoring.

There is no:
- Ground truth collection mechanism (how do you know which predictions were correct after the appointment date passes?)
- AUC computation on recent predictions vs. outcomes
- CloudWatch alarm on model performance degradation
- Trigger for automated retraining when drift is detected

The recipe tells you monitoring matters but provides no architecture for it. A builder following the main recipe gets a pipeline that trains once, scores nightly, and has no feedback loop. The model silently degrades.

**Suggested fix:** Add a Step 6 to the code walkthrough: "Ground truth and monitoring." A nightly Lambda (or Glue job) that runs after the appointment date, joins predictions with actual outcomes (show/no-show from the scheduling system), computes rolling AUC, and publishes to CloudWatch. Add a CloudWatch alarm that triggers retraining when AUC drops below a threshold (e.g., 0.72). Add this to the architecture diagram as a feedback loop from the scheduling system back to the training pipeline. This is the difference between a demo and a production system.

### Issue A2: scale_pos_weight Calculation Assumes Static Class Distribution (MEDIUM)

**Location:** Step 2 pseudocode, `scale_pos_weight: 5.5` with comment "if 15% no-show rate, weight = 85/15 ≈ 5.5"

**The problem:** The `scale_pos_weight` hyperparameter is hardcoded to 5.5 based on an assumed 15% no-show rate. But the recipe's own problem statement says no-show rates range from 5% to 30% depending on the practice. A practice with a 25% no-show rate using `scale_pos_weight: 5.5` will over-weight the positive class, producing a model biased toward predicting no-show. A practice with a 7% rate needs a weight closer to 13.

Additionally, class distribution shifts over time (the recipe acknowledges this in the retraining discussion). A fixed weight becomes stale.

**Suggested fix:** Change the hardcoded value to a computed one in the pseudocode: `scale_pos_weight = count(negative_class) / count(positive_class)` computed from the training data. Add a comment: "Compute from your actual training data distribution. The 5.5 example assumes a 15% no-show rate; your practice may differ significantly."

### Issue A3: No Idempotency on DynamoDB Writes (MEDIUM)

**Location:** Step 4 pseudocode (store_predictions)

**The problem:** The batch transform job writes predictions to DynamoDB with `appointment_id` as the primary key. If the nightly pipeline runs twice (EventBridge duplicate delivery, manual re-run, retry after partial failure), the second run overwrites the first run's predictions. This is actually fine for correctness (same model, same features, same predictions). But if a model was retrained between runs, or if features changed, the second write silently replaces predictions with different values and a different `model_version`.

More importantly, there's no conditional write. If the action engine has already read and acted on a prediction (sent a reminder), and the pipeline re-runs and writes a lower probability, the audit trail shows a prediction that doesn't match the action taken.

**Suggested fix:** Add a conditional write or versioning note: "Use a DynamoDB condition expression to prevent overwriting predictions that have already been acted upon: `attribute_not_exists(acted_at)`. Alternatively, append a `pipeline_run_id` to each write and keep the action engine's reference to the specific run it consumed. This preserves audit consistency between predictions and actions."

### Issue A4: Batch Transform Output Parsing Not Addressed (LOW)

**Location:** Step 3 pseudocode (score_upcoming_appointments)

**The problem:** SageMaker batch transform outputs one prediction per line in a `.out` file, but the output contains only the probability value (e.g., "0.73"), not the appointment ID. The pairing of predictions back to appointment IDs depends on the output file maintaining the same row order as the input file. The pseudocode says `read_predictions(transform_config.output_path)` and returns `{appointment_id, no_show_probability}` without explaining how the join happens.

A builder unfamiliar with batch transform may not realize that the output is positional (line N of output corresponds to line N of input) and attempt to parse appointment IDs from the output file, which won't work.

**Suggested fix:** Add a brief comment in Step 3: "Batch transform output is positional: line N of the output file contains the prediction for line N of the input file. Join predictions back to appointment IDs by index position. Alternatively, include appointment_id as a pass-through column in the input (using `AssembleWith` and `Accept` configurations) so the output contains both the ID and the prediction."

---

## Networking Expert Review

### What's Done Well

The recipe correctly places SageMaker training and inference in a VPC for production. The mention of VPC endpoints for S3 and DynamoDB is correct (both support gateway endpoints, which are free). The architecture is primarily batch-oriented, which reduces the networking complexity compared to real-time inference patterns.

### Issue N1: No Egress Discussion for Glue Jobs Accessing External Data (MEDIUM)

**Location:** Architecture Diagram, "Why These Services" section for Glue

**The problem:** The recipe states Glue jobs "pull from your data warehouse (Redshift, RDS, or wherever your scheduling system stores data)." If the scheduling system is on-premises or in a different VPC, the Glue job needs network connectivity to that source. The recipe places Glue "in VPC with access to data sources" but provides no guidance on:

- Whether the data source is in the same VPC, a peered VPC, or accessible via Direct Connect/VPN
- Security group rules for Glue ENIs to reach the data source
- Whether Glue needs a NAT gateway for any external API calls (e.g., geocoding for distance computation)

For the distance_miles feature, the recipe's pseudocode calls `compute_distance(patient.address, clinic.address)`. If this uses a geocoding API (Google Maps, HERE, etc.), the Glue job needs internet egress, which means NAT gateway or a VPC endpoint for the geocoding service. PHI (patient address) would transit to an external geocoding API, which has BAA implications.

**Suggested fix:** Add a note in the Glue section or prerequisites: "If computing distance features requires external geocoding APIs, route through a NAT gateway and ensure the geocoding provider is covered under your BAA (or pre-geocode addresses in a separate, de-identified pipeline). Alternatively, compute straight-line distance from stored lat/long coordinates that were geocoded at patient registration time, avoiding runtime external API calls from the PHI-containing pipeline."

### Issue N2: SageMaker Batch Transform Network Isolation Not Mentioned (LOW)

**Location:** Prerequisites, Step 3 pseudocode

**The problem:** SageMaker batch transform jobs can be configured with `NetworkIsolation: true`, which prevents the container from making any outbound network calls. For a model that only needs to read input from S3 and write output to S3 (which is the case here), network isolation is a defense-in-depth measure that prevents a compromised or misconfigured container from exfiltrating data.

**Suggested fix:** Add a brief note in the batch transform configuration: "Enable network isolation on the transform job (`EnableNetworkIsolation: true`). The XGBoost inference container does not need outbound network access; it reads input from S3 and writes predictions to S3 via SageMaker-managed channels. Network isolation prevents any unintended data egress from the scoring container."

---

## Voice Reviewer

### What's Done Well

The recipe nails CC's voice throughout. The opening hook ("Here's a number that should make any clinic operations manager wince") is strong. The parenthetical asides are natural ("not 'irresponsibility'"). The "Let's build it" transition is clean. The Honest Take section is genuinely self-deprecating and insightful. The fairness discussion is handled with appropriate nuance without being preachy. The 70/30 vendor split is well-maintained: the Technology section is entirely vendor-agnostic, and AWS only appears in the implementation half.

### Issue V1: One Instance of Documentation-Voice (LOW)

**Location:** "Why These Services" section, first sentence about SageMaker

**The problematic text:** "SageMaker provides the full ML lifecycle: notebook environments for exploration, managed training jobs for production model builds, and real-time or batch inference endpoints for serving predictions."

This reads like AWS marketing copy or a product overview page. Compare to the rest of the recipe's voice, which explains why a service fits the specific problem rather than listing its general capabilities.

**Suggested fix:** Rewrite to focus on why SageMaker fits this specific problem: "SageMaker handles the infrastructure you don't want to manage yourself: spinning up a training instance, running the XGBoost job, storing the model artifact, and tearing everything down when it's done. For this recipe, the batch transform mode is the key feature: score tomorrow's entire schedule in one job rather than standing up a persistent endpoint that sits idle 23 hours a day."

### Issue V2: No Em Dashes Found (PASS)

Zero em dashes in the recipe. Clean.

### Issue V3: Vendor Balance Is Correct (PASS)

The Technology section (approximately 60% of the recipe's prose) is entirely vendor-agnostic. AWS services appear only in "The AWS Implementation" section. A reader on GCP or Azure learns the full conceptual framework before seeing any AWS-specific content. The 70/30 target is met.

---

## Stage 2: Expert Discussion

**Overlap between Security (S2) and Architecture (A3):** Both identify the DynamoDB table as needing more careful treatment. S2 focuses on access controls and retention; A3 focuses on idempotency and audit consistency. These are complementary, not conflicting. Both should be addressed.

**Overlap between Security (S4) and Networking (N1):** The incomplete VPC endpoint list (S4) and the Glue egress discussion (N1) both relate to network security posture. S4 is about control-plane API access; N1 is about data-plane egress for feature computation. Both are valid and non-overlapping.

**Priority conflict:** Architecture (A1, model monitoring) vs. Security (S1, IAM least-privilege). Both are HIGH. A1 is more impactful for production viability (a model without monitoring silently degrades). S1 is more impactful for security posture (overly broad permissions are an audit finding). Both should be fixed, but A1 is the more likely production failure mode for a builder following this recipe.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

No CRITICAL findings. Three HIGH findings (below the 4-HIGH threshold for FAIL). The recipe is architecturally sound, clinically appropriate, well-written, and provides actionable guidance. The HIGH findings are gaps that would surface in a production deployment but do not represent fundamental design flaws.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Architecture Diagram, Code section | No model monitoring, drift detection, or ground truth collection in the main architecture. Recipe tells you to monitor but provides no infrastructure for it. | Add Step 6: ground truth collection Lambda, rolling AUC computation, CloudWatch alarm, retraining trigger. Add feedback loop to architecture diagram. |
| 2 | HIGH | Security | Prerequisites, IAM Permissions row | Permissions listed as flat set implying single role. Violates least-privilege. Lambda action engine would have SageMaker and Glue permissions. | Split into role-specific entries or add explicit note about role separation with resource-scoped ARNs. |
| 3 | HIGH | Security | Step 4 pseudocode, Prerequisites | DynamoDB table stores PHI (patient_id, behavioral data) with no TTL, no access control discussion, no retention policy. | Add TTL guidance (expire after appointment + 90 days), note on fine-grained access control, treat features_used as sensitive. |
| 4 | MEDIUM | Security | Step 5 pseudocode | SMS reminders may contain PHI (provider name, visit type) sent over unencrypted channel. No content minimization guidance. | Add note: minimize PHI in SMS content. Use generic prompts, link to secure portal for details. |
| 5 | MEDIUM | Security | Prerequisites, VPC row | VPC endpoint list only mentions S3 and DynamoDB. Missing SageMaker API, SNS, CloudWatch Logs, KMS endpoints. | Expand to full endpoint set or note that additional endpoints are required. |
| 6 | MEDIUM | Architecture | Step 2 pseudocode, scale_pos_weight | Hardcoded class weight assumes 15% no-show rate. Recipe acknowledges rates vary 5-30%. Static weight becomes stale. | Compute from training data: `count(negative) / count(positive)`. Note that the example value is illustrative. |
| 7 | MEDIUM | Architecture | Step 4 pseudocode | No idempotency on DynamoDB writes. Re-runs can overwrite predictions already acted upon, breaking audit trail. | Add conditional write (`attribute_not_exists(acted_at)`) or pipeline_run_id versioning. |
| 8 | MEDIUM | Networking | Glue section, distance_miles feature | Geocoding for distance computation may require external API egress with PHI (patient address). No BAA or network guidance. | Add note: pre-geocode at registration, or route through NAT with BAA-covered provider. Avoid runtime PHI egress to external APIs. |
| 9 | LOW | Architecture | Step 3 pseudocode | Batch transform output parsing (positional join) not explained. Builders may not know output is line-ordered. | Add comment explaining positional output and how to join back to appointment IDs. |
| 10 | LOW | Voice | "Why These Services", SageMaker paragraph | First sentence reads like AWS marketing copy rather than CC's engineer voice. | Rewrite to focus on why SageMaker fits this specific problem, not its general capabilities. |
| 11 | LOW | Networking | Step 3, Prerequisites | SageMaker batch transform network isolation not mentioned. Defense-in-depth measure for PHI-containing scoring jobs. | Add `EnableNetworkIsolation: true` recommendation with brief rationale. |

---

## Priority Actions Before Publication

1. **Fix A1 (HIGH):** Add model monitoring architecture. This is the gap most likely to cause production failure. A model without a feedback loop is a demo, not a system.

2. **Fix S1 (HIGH):** Split IAM permissions into role-specific guidance. This is an audit finding waiting to happen and misleads builders into creating overly permissive roles.

3. **Fix S2 (HIGH):** Add DynamoDB TTL and access control guidance. PHI retention without a policy is a compliance gap.

4. **Fix S3, S4, N1 (MEDIUM):** Address SMS PHI minimization, complete the VPC endpoint list, and add geocoding egress guidance. These are production-readiness items that prevent security surprises at deployment time.

5. **Fix A2, A3 (MEDIUM):** Make scale_pos_weight dynamic and add DynamoDB write idempotency. These prevent subtle correctness issues in production.

The LOW findings (A4, V1, N2) are polish items that improve quality but don't block a competent builder.

---

*Review complete. Recipe 7.1 is a strong first recipe for the Predictive Analytics chapter. The problem framing, technology explanation, and fairness discussion are excellent. The gaps are primarily in operational completeness (monitoring, IAM specificity, PHI retention) rather than fundamental design. A builder with AWS experience could deploy from this recipe with the HIGH items addressed.*
