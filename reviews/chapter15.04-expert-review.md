# Expert Review: Recipe 15.4 - Sepsis Treatment Optimization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter15.04-sepsis-treatment-optimization.md`

---

## Overall Assessment

**Verdict: PASS**

This is a strong, well-researched recipe that tackles one of the most studied and most difficult RL applications in healthcare with appropriate intellectual honesty. The RL formulation follows established literature (Komorowski et al., 2018), the safety constraint layer is clinically reasonable, the offline evaluation methodology is correctly framed with appropriate caveats, and the "Honest Take" is genuinely honest about the gap between research promise and clinical deployment. The regulatory discussion (FDA, IRB) is present and appropriately cautious.

Priority breakdown: 0 critical issues, 3 high issues, 5 medium issues, 4 low issues.

---

## Security Expert Review

### What's Done Well

- BAA requirement explicitly stated in Prerequisites
- SSE-KMS encryption specified for S3 trajectory data and model artifacts
- DynamoDB encryption at rest mentioned
- TLS for all API calls specified
- VPC with VPC endpoints for production (S3, DynamoDB, CloudWatch Logs)
- CloudTrail enabled for all SageMaker, S3, and Glue API calls
- IRB approval requirement stated
- Audit logging of every recommendation in Step 6 (`log_to_audit_trail`)
- The recipe correctly identifies this as research requiring IRB, not routine operations

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:GetItem`, `states:StartExecution`) are listed as a flat set without resource-scoping or role separation. In a system processing PHI (patient physiological data from EHR), a single role with all these permissions violates least-privilege. The Glue ETL job that extracts patient data from the EHR should not have `sagemaker:CreateEndpoint` permission. The inference endpoint should not have `glue:StartJobRun`. A compromised training job with `s3:PutObject` on all buckets could overwrite audit logs.

**Suggested fix:** Replace the flat permission list with role-separated guidance: "Separate IAM roles per pipeline stage: (1) Glue ETL role: `glue:StartJobRun`, `s3:GetObject` on EHR source, `s3:PutObject` on trajectory bucket only. (2) SageMaker training role: `s3:GetObject` on trajectory bucket, `s3:PutObject` on model artifact bucket. (3) Inference endpoint role: `s3:GetObject` on model bucket, `dynamodb:GetItem` on policy table, `logs:PutLogEvents` for audit. (4) Step Functions orchestration role: `states:StartExecution` plus pass-role for each stage role." Add resource ARN constraints to all permissions.

### Issue S2: Audit Trail for Recommendations Lacks Tamper Protection (MEDIUM)

**Location:** Code, Step 6 (Clinical decision support interface), `log_to_audit_trail` call

**The problem:** The recipe logs every recommendation for "audit and outcome tracking" but does not specify where or how. If recommendations are logged to a standard S3 bucket or DynamoDB table, they can be modified or deleted by anyone with write access. For a clinical decision support system that may face regulatory scrutiny or malpractice litigation, the audit trail must be tamper-evident. If a recommendation contributed to a bad outcome, the integrity of the log is critical.

**Suggested fix:** Add after the `log_to_audit_trail` call: "Audit logs should be written to an S3 bucket with Object Lock (compliance mode) or to CloudWatch Logs with a resource policy preventing deletion. For regulatory defensibility, consider a separate audit account with cross-account write-only access from the production account."

### Issue S3: No Mention of De-identification for Model Training (MEDIUM)

**Location:** Code, Step 1 (Cohort extraction), general

**The problem:** The recipe extracts patient data including demographics, vital signs, lab values, and outcomes from the EHR for model training. While it mentions IRB approval, it does not discuss whether the training data should be de-identified (Safe Harbor or Expert Determination under HIPAA) or whether a Limited Data Set with a Data Use Agreement is sufficient. For a research use case, this distinction matters. If the model is trained on identified data, the model artifact itself could potentially memorize patient-specific patterns, creating a PHI leakage risk in the model weights.

**Suggested fix:** Add a note in Step 1 or Prerequisites: "Training data should be de-identified per HIPAA Safe Harbor (remove 18 identifiers) or used under a Limited Data Set agreement with IRB-approved DUA. Patient IDs in trajectory data should be replaced with study-specific pseudonymous identifiers. Note: the model artifact trained on de-identified data is not itself PHI, but the trajectory dataset is."

### Issue S4: KMS Key Policy Not Discussed (LOW)

**Location:** Prerequisites, Encryption row

**The problem:** The recipe specifies "SSE-KMS for all trajectory data and model artifacts" and "KMS-encrypted training volumes and endpoints" but does not mention key policy design. For PHI data, the KMS key policy should restrict decrypt access to specific roles (the training role, the inference role) and deny access to administrative roles that don't need to read patient data. This prevents a SageMaker admin from accessing trajectory data without going through the approved pipeline.

**Suggested fix:** Add one line: "KMS key policy should restrict `kms:Decrypt` to the specific IAM roles that need data access (training role, inference role). Deny decrypt to administrative roles that manage infrastructure but should not access PHI."

---

## Architecture Expert Review

### What's Done Well

- The offline RL approach (CQL) is the correct choice for healthcare: conservative, well-studied, addresses distribution shift
- Separation of training (batch, GPU) from inference (real-time, endpoint) is architecturally sound
- Step Functions for pipeline orchestration with multi-step dependencies is appropriate
- The safety constraint layer as a hard override on the policy output is the right pattern (defense in depth)
- The 4-hour time window discretization is clinically standard and well-justified
- The recipe correctly identifies that evaluation is harder than training
- Multiple OPE methods (WIS + FQE + agreement rate) with confidence intervals is the right approach
- The "advisory only" framing with clinician override is both clinically appropriate and architecturally simpler than autonomous systems
- Cost estimates are reasonable for the described workload

### Issue A1: Safety Constraint Layer Has No Monitoring or Alerting (HIGH)

**Location:** Code, Step 4 (Safety constraint layer)

**The problem:** The safety constraints are applied silently. If the learned policy is frequently recommending actions that get vetoed by the safety layer, that's a signal that either (a) the policy has degraded, (b) the patient population has shifted outside the training distribution, or (c) the safety constraints are too restrictive. The recipe has no mechanism to detect this. A policy that triggers safety constraints on 80% of recommendations is effectively useless, but without monitoring, nobody would know.

**Suggested fix:** Add after the safety constraint function: "Monitor the constraint trigger rate per constraint type. If any single constraint fires on more than 20% of recommendations over a 24-hour window, alert the clinical informatics team. A high trigger rate indicates either policy degradation (retrain needed) or out-of-distribution patients (model boundary reached). Log which constraints fired for every recommendation as part of the audit trail. Publish constraint trigger rates to CloudWatch as custom metrics with alarms."

### Issue A2: No Distribution Shift Detection for Inference (HIGH)

**Location:** Architecture, CloudWatch section; Code, Step 6

**The problem:** The recipe mentions CloudWatch for "prediction distribution drift" monitoring but provides no specifics. This is the most critical operational concern for a deployed RL policy. If the patient population changes (new sepsis variant, different demographics, new standard-of-care drugs not in training data), the policy will make recommendations based on states it has never seen. The Q-values will be unreliable. The recipe needs a concrete mechanism for detecting when the inference-time state distribution diverges from the training distribution.

**Suggested fix:** Add a subsection or note: "Implement distribution shift detection: (1) During training, compute the mean and covariance of the state feature vectors. (2) At inference time, compute the Mahalanobis distance of each incoming patient state from the training distribution. (3) If the distance exceeds a threshold (e.g., 95th percentile of training distances), flag the recommendation as 'low confidence, out of distribution' and suppress it from the clinical display. (4) Track the percentage of OOD states over time in CloudWatch. A rising OOD rate signals the need for model retraining."

### Issue A3: DynamoDB for Policy Serving Is Under-specified (MEDIUM)

**Location:** "Why These Services" section, DynamoDB paragraph

**The problem:** The recipe says "For discrete state spaces, DynamoDB provides single-digit-millisecond lookups" but the state space described uses continuous features with neural network function approximators (CQL with a neural Q-network). The recipe then also mentions "SageMaker endpoints handle inference" for neural network policies. It's unclear which path is actually recommended. If the state space is discretized (750 states via k-means, as mentioned in the Technology section), DynamoDB makes sense. If it's continuous (as the code implies with normalized feature vectors), DynamoDB doesn't apply. The recipe presents both without resolving which architecture the code actually implements.

**Suggested fix:** Clarify in "Why These Services": "The code in this recipe uses a continuous state representation with a neural Q-network, served via a SageMaker endpoint. DynamoDB is listed as an alternative for implementations that discretize the state space (e.g., k-means clustering into 750 states as described in the Technology section). Choose one approach: continuous states + SageMaker endpoint (more expressive, higher inference cost) or discrete states + DynamoDB lookup (simpler, cheaper, but loses information in discretization)."

### Issue A4: No Model Versioning or Rollback Strategy (MEDIUM)

**Location:** Architecture, S3 Model Registry mention

**The problem:** The recipe mentions "S3 Model Registry" in the architecture diagram but provides no detail on model versioning, A/B testing between policy versions, or rollback procedures. For a clinical system, deploying a new policy version that performs worse than the previous one is a patient safety concern. There should be a mechanism to compare new vs. old policy performance and roll back if the new policy shows degradation.

**Suggested fix:** Add a note: "Use SageMaker Model Registry (not just S3) to version policies with approval workflows. Before promoting a new policy to production, run OPE comparison against the currently deployed policy on the same held-out test set. Implement a canary deployment pattern: serve the new policy to a small percentage of recommendations initially, monitor safety constraint trigger rates and clinician override rates, and roll back automatically if either metric degrades beyond a threshold."

### Issue A5: Reward Function Sensitivity Not Addressed Architecturally (MEDIUM)

**Location:** Code, Step 1 (reward computation); "The Honest Take"

**The problem:** The "Honest Take" correctly states "the reward function matters more than the algorithm" and to "spend 80% of your time on state representation and reward engineering." But the architecture has no mechanism for experimenting with multiple reward functions and comparing the resulting policies. The Step Functions pipeline trains a single policy with a single reward. In practice, teams will want to train policies with different reward formulations (terminal-only vs. intermediate SOFA vs. composite) and compare them via OPE. The architecture should support this experimentation loop.

**Suggested fix:** Add to the architecture or "Variations" section: "In practice, parameterize the reward function and train multiple policies in parallel (one per reward formulation). Use SageMaker Experiments to track which reward function produced which policy, and compare all policies via the same OPE pipeline. The reward function that produces the policy with the highest OPE estimate AND the highest clinician agreement rate is likely the best candidate for clinical review."

---

## Networking Expert Review

### What's Done Well

- VPC deployment specified for production with no public internet access for training jobs
- VPC endpoints listed for S3, DynamoDB, and CloudWatch Logs
- TLS for all API calls specified
- The architecture keeps PHI within the VPC boundary (EHR data never leaves the private subnet)

### Issue N1: Missing VPC Endpoints for SageMaker and KMS (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The prerequisites specify "VPC endpoints for S3, DynamoDB, CloudWatch Logs" but omit SageMaker API and Runtime endpoints (`com.amazonaws.{region}.sagemaker.api`, `com.amazonaws.{region}.sagemaker.runtime`) and KMS (`com.amazonaws.{region}.kms`). SageMaker training jobs in a private subnet need the SageMaker API endpoint to report status. The inference endpoint needs the SageMaker Runtime endpoint for invocations from within the VPC. KMS is needed for SSE-KMS operations on S3. Without these, the architecture requires a NAT Gateway (which introduces an egress point for PHI) or simply fails.

**Suggested fix:** Expand the VPC endpoint list: "VPC endpoints for S3 (gateway), DynamoDB (gateway), CloudWatch Logs (interface), KMS (interface), SageMaker API (interface), and SageMaker Runtime (interface). Note: interface endpoints incur per-AZ-hour charges (~$7.20/month per endpoint per AZ)."

### Issue N2: EHR Data Source Connectivity Not Addressed (LOW)

**Location:** Architecture diagram, "EHR Data Source" node

**The problem:** The architecture shows "EHR Data Source (FHIR / HL7 / Database)" connecting to AWS Glue, but does not discuss how the EHR system connects to the VPC. In most healthcare enterprises, the EHR (Epic, Cerner) is on-premises or in a separate network. The connection typically requires AWS Direct Connect or Site-to-Site VPN with specific security controls (encryption, access logging, firewall rules). This is a significant infrastructure prerequisite that the recipe glosses over.

**Suggested fix:** Add a note in Prerequisites or the architecture section: "EHR connectivity assumes either (a) Direct Connect with a private VIF to the VPC, (b) Site-to-Site VPN, or (c) an EHR-provided FHIR API accessible over the internet with mutual TLS. For on-premises EHR databases, AWS Database Migration Service (DMS) or a custom ETL via Direct Connect is typical. The connectivity pattern is institution-specific and often the longest lead-time item in the project."

### Issue N3: Clinical System to SageMaker Endpoint Path Not Secured (LOW)

**Location:** Architecture diagram, "Clinical System (EHR / CDSS)" to "SageMaker Endpoint" connection

**The problem:** The architecture shows the clinical system (EHR/CDSS) calling the SageMaker endpoint directly. In practice, this should go through an API Gateway or Application Load Balancer with authentication (IAM SigV4, Cognito, or mutual TLS). A raw SageMaker endpoint invocation requires IAM credentials in the calling system, which means the EHR/CDSS needs AWS SDK integration. Most clinical systems call REST APIs. The recipe should clarify the integration pattern.

**Suggested fix:** Add a note: "In production, place an API Gateway (REST) or Application Load Balancer in front of the SageMaker endpoint. The clinical system calls a standard HTTPS REST API with authentication (API key, OAuth2, or mutual TLS). The API Gateway invokes the SageMaker endpoint via IAM role. This decouples the clinical system from AWS-specific SDK requirements."

---

## Voice Reviewer

### What's Done Well

- The opening problem statement is passionate and makes the reader feel the urgency ("Sepsis kills more people in hospitals than heart attacks")
- The conversational asides work well: "(ok, this is a gross oversimplification, but stay with me)" energy throughout
- The "Honest Take" is genuinely honest and self-aware ("sepsis RL is one of the most published topics in healthcare AI, and it is still not deployed in routine clinical practice anywhere")
- The 70/30 vendor balance is well-maintained: the entire Technology section (substantial) is vendor-agnostic
- No documentation-voice detected. Reads like an engineer who has actually worked on this problem
- The "Why This Is Hard (Beyond the Obvious)" subsection is excellent teaching
- The reward function insight ("spend 80% of your time on state representation and reward engineering") is the kind of hard-won wisdom that makes this cookbook valuable

### Issue V1: Em Dash Check

**Result:** Zero em dashes found. Clean.

### Issue V2: One Instance of Slightly Academic Register (LOW)

**Location:** "The Technology" section, "The mathematical goal" paragraph

**Quote:** "The mathematical goal: find the policy π that maximizes the expected sum of discounted future rewards. In notation: π* = argmax E[Σ γ^t * r_t], where γ is a discount factor that weights near-term rewards more heavily than distant ones."

This reads slightly more like a textbook than an engineer at a whiteboard. The notation is fine (it's accurate and useful), but the framing "The mathematical goal" and "In notation" is a bit formal. Compare to the rest of the recipe which uses phrases like "Here's the thing that makes this problem so maddening" and "How do you know if your learned policy is actually better than what clinicians did?"

**Suggested fix:** Optional. Could rephrase to: "What we're optimizing: find the policy π that maximizes expected cumulative reward. The math: π* = argmax E[Σ γ^t * r_t], where γ discounts future rewards (we care about long-term survival but prefer getting there sooner)." Minor polish, not blocking.

### Issue V3: "TODO" Left in Additional Resources (LOW)

**Location:** Additional Resources, Research References section

**Quote:** "TODO: Verify current URL for MIMIC-IV dataset access (PhysioNet)"

A TODO should not appear in a published recipe. Either include the verified URL or remove the line.

**Suggested fix:** Replace with the verified PhysioNet URL: `https://physionet.org/content/mimiciv/` or remove the line entirely if verification is not possible before publication.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

The Architecture (A1, A2) and Security (S1) reviewers converge on operational safety: the recipe describes a system that could be deployed but lacks the monitoring and guardrails needed to detect when it's failing silently. A1 (no monitoring of safety constraint triggers) and A2 (no distribution shift detection) are two facets of the same gap: the system has no way to know when it's operating outside its competence boundary. S1 (flat IAM permissions) compounds this because a single compromised role could affect the entire pipeline.

The Architecture (A3) and Networking (N1) reviewers both identify under-specification in the serving layer: it's unclear whether the recipe recommends DynamoDB or SageMaker endpoints, and the VPC endpoints needed for SageMaker are missing.

### Priority Resolution

- A1 and A2 are the highest-priority findings because they affect patient safety in a deployed system. A policy that silently degrades or operates on out-of-distribution patients without detection is dangerous. These are addressable with monitoring additions, not architectural redesign.
- S1 (IAM least-privilege) is HIGH because PHI is involved and the flat permission model is a compliance gap that auditors will flag.
- The remaining issues are important for production readiness but do not affect the recipe's educational value or clinical correctness.

### Clinical Accuracy Assessment

The RL formulation is clinically appropriate:
- Sepsis-3 criteria for cohort selection is current standard
- 4-hour time windows are standard in the literature
- The 5x5 action discretization (fluids x vasopressors) follows Komorowski et al.
- Safety constraints are clinically reasonable (MAP < 55 requiring vasopressors, fluid overload limits, rising lactate contraindication)
- The reward formulation options (terminal survival, intermediate SOFA) are well-established
- CQL as the algorithm choice is appropriate for the distribution shift concern
- The off-policy evaluation methodology (WIS + FQE + agreement rate) is the current best practice
- The "not production-ready" framing and regulatory pathway discussion are honest and accurate

One minor clinical note: Constraint 1 uses MAP < 55 as the threshold for requiring vasopressors. The Surviving Sepsis Campaign 2021 guidelines target MAP >= 65. A threshold of 55 is very permissive (allowing the policy to recommend no vasopressors for MAPs between 55-64). This is defensible as a "hard floor" (below which organ damage is near-certain) rather than a "target" (which is the clinician's job), but the distinction could be made explicit.

---

## Stage 3: Synthesized Verdict

**VERDICT: PASS**

No CRITICAL findings. 3 HIGH findings (all addressable with additions/clarifications, not redesign). The recipe is clinically sound, the RL formulation is appropriate, the safety constraints are reasonable, the evaluation methodology is correctly framed with appropriate uncertainty acknowledgment, and the regulatory discussion is honest. The writing quality is high and maintains the cookbook's voice throughout.

---

## Prioritized Fix List

### HIGH

| ID | Issue | Expert | Location |
|----|-------|--------|----------|
| A1 | Safety constraint layer has no monitoring or alerting. High trigger rates indicate policy degradation or OOD patients but go undetected. | Architecture | Step 4, safety constraints |
| A2 | No distribution shift detection for inference. No mechanism to detect when patient states diverge from training distribution. | Architecture | CloudWatch section / Step 6 |
| S1 | IAM permissions are flat, not role-separated or resource-scoped. Single role with all permissions violates least-privilege for PHI-processing system. | Security | Prerequisites, IAM row |

### MEDIUM

| ID | Issue | Expert | Location |
|----|-------|--------|----------|
| S2 | Audit trail for recommendations lacks tamper protection (Object Lock, compliance mode). | Security | Step 6, log_to_audit_trail |
| S3 | No mention of de-identification requirements for training data. PHI leakage risk in model weights not addressed. | Security | Step 1 / Prerequisites |
| A3 | DynamoDB vs. SageMaker endpoint ambiguity. Recipe describes both without resolving which the code implements. | Architecture | "Why These Services" |
| A4 | No model versioning, A/B testing, or rollback strategy for policy updates. | Architecture | Architecture, S3 Model Registry |
| N1 | Missing VPC endpoints for SageMaker API, SageMaker Runtime, and KMS. Will break in private subnet without NAT. | Networking | Prerequisites, VPC row |

### LOW

| ID | Issue | Expert | Location |
|----|-------|--------|----------|
| S4 | KMS key policy not discussed. No guidance on restricting decrypt to specific roles. | Security | Prerequisites, Encryption |
| N2 | EHR connectivity pattern (Direct Connect, VPN, FHIR API) not addressed. Major infrastructure prerequisite glossed over. | Networking | Architecture diagram |
| N3 | Clinical system to SageMaker endpoint lacks API Gateway or ALB intermediary for standard REST integration. | Networking | Architecture diagram |
| V2 | One instance of slightly academic register ("The mathematical goal: find the policy π..."). | Voice | Technology section |
| V3 | "TODO: Verify current URL for MIMIC-IV dataset access" left in published recipe. | Voice | Additional Resources |

---

## What This Recipe Does Well

Worth preserving in final edits:

- The problem statement makes sepsis mortality visceral and connects it to the sequential decision-making challenge without being melodramatic
- The Technology section is one of the best explanations of offline RL for a practitioner audience I've seen. The progression from "what is RL" to "why offline" to "why this is hard" is well-sequenced and each concept builds on the previous
- The "Why This Is Hard (Beyond the Obvious)" subsection correctly identifies confounding, partial observability, non-stationarity, and evaluation as the real challenges (not the algorithm)
- The safety constraint layer is well-designed: clinically motivated, clearly explained, with a fallback mechanism when all actions are constrained out
- The off-policy evaluation section is honest about limitations ("confidence intervals wide enough to drive a truck through") while still providing actionable methodology
- The "Honest Take" is genuinely valuable: "start with the data pipeline and evaluation infrastructure, not the RL algorithm" is advice that will save readers months of wasted effort
- The reward function insight ("spend 80% of your time on state representation and reward engineering, and 20% on the RL algorithm itself") is the kind of hard-won wisdom that justifies the cookbook format
- The clinician agreement rate discussion (50-70%) is nuanced: "Encouraging because it means the policy isn't recommending wildly different things... Concerning because the 30-50% disagreement is where the value supposedly lives"
- The implementation timeline is realistic and correctly identifies the regulatory pathway as the dominant time factor (2-4 years)
- The "Why This Isn't Production-Ready" section is appropriately cautious without being defeatist

---

*Review completed 2026-06-01. Four expert perspectives: security, architecture, networking, voice.*
