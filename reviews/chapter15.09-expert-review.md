# Expert Review: Recipe 15.9 - Radiation Therapy Adaptive Planning

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter15.09-radiation-therapy-adaptive-planning.md`

---

## Overall Assessment

This is a genuinely impressive recipe. The RL formulation is clinically sound, the MDP mapping is well-motivated, the offline RL approach is correctly identified as mandatory, and the "Honest Take" section is one of the best in the book. The recipe correctly positions this as research-stage, avoids overpromising, and gives the reader a realistic picture of the gap between proof-of-concept and clinical deployment.

However: there are safety constraint formulation gaps that could mislead a builder into thinking soft penalties are sufficient for hard dose limits, the FDA regulatory pathway discussion is incomplete in ways that matter for anyone actually pursuing this, the VPC configuration is underspecified for a system handling radiation treatment data, and there are several voice/style issues including em dashes that violate the style guide.

Priority breakdown: 1 CRITICAL (safety constraint formulation), 3 HIGH (regulatory, networking, architecture), 5 MEDIUM, 4 LOW.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

The prerequisites table correctly identifies BAA requirement, SSE-KMS for S3, DynamoDB encryption at rest, TLS 1.2+ for transit, CloudTrail for audit, and VPC isolation for all compute. The explicit note that CloudTrail is "critical for tracking model versions used in clinical recommendations" shows awareness that model provenance is part of the audit trail for a clinical decision support system. The feedback loop (Step 4) captures clinician overrides with timestamps and physician IDs, which is essential for post-hoc review of any adverse outcomes.

#### Issue S1: IAM Permissions List Is Incomplete for the Stated Architecture (MEDIUM)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The IAM permissions listed are: `sagemaker:CreateTrainingJob`, `sagemaker:CreateProcessingJob`, `s3:GetObject`, `s3:PutObject`, `dynamodb:GetItem`, `dynamodb:PutItem`, `lambda:InvokeFunction`, `states:StartExecution`. This covers the happy path but misses several permissions required by the architecture:

- `sagemaker:CreateModel` and `sagemaker:CreateEndpoint` (if using SageMaker endpoints for inference, though the recipe uses Lambda)
- `kms:Decrypt` and `kms:GenerateDataKey` (required for any service reading/writing KMS-encrypted S3 objects or DynamoDB items)
- `cloudwatch:PutMetricData` (for the monitoring described in the architecture)
- `logs:CreateLogGroup`, `logs:PutLogEvents` (for Lambda and Step Functions logging)
- `states:DescribeExecution` (for monitoring pipeline status)

Missing KMS permissions is the most impactful: without `kms:Decrypt` on the Lambda execution role, the policy query Lambda cannot read the trained model from S3 or the patient state from DynamoDB if both are KMS-encrypted as specified.

**Suggested fix:** Expand the IAM permissions to include KMS actions (`kms:Decrypt`, `kms:GenerateDataKey` scoped to the specific CMK ARN), CloudWatch actions, and CloudWatch Logs actions. Add a note that these should be scoped to specific resource ARNs (least-privilege), not wildcards.

#### Issue S2: Model Versioning and Rollback Not Addressed (MEDIUM)

**Location:** Step 5 (train_policy), "register_model" call

**The problem:** The training pipeline registers a new model version if validation passes. But there's no discussion of:
- How the inference Lambda knows which model version to load
- How to roll back to a previous model version if the new one produces unexpected recommendations in production
- Whether multiple model versions can coexist (A/B testing between policy versions)
- How model versions are tagged with the training data cutoff date (critical for reproducibility in a clinical context)

For a clinical decision support system, model provenance and rollback capability are not optional. If a new policy version starts recommending replans at inappropriate times, you need to revert within minutes, not hours.

**Suggested fix:** Add a brief discussion in the architecture section about model versioning strategy: S3 object versioning for model artifacts, a "current model" pointer (could be a DynamoDB item or an S3 tag), and a rollback procedure. Note that any model version change should be logged in CloudTrail and that the recommendation output should include the model version ID for traceability.

#### Issue S3: Patient State History in DynamoDB Has No TTL or Retention Policy (LOW)

**Location:** Architecture description of DynamoDB role

**The problem:** DynamoDB stores patient state history for "fast inference lookups." Treatment courses last 6-7 weeks. After treatment completion, this data is no longer needed for inference but may be needed for training and audit. There's no discussion of data lifecycle: when does state history move from DynamoDB (hot) to S3 (warm/cold)? Without a TTL or explicit cleanup, DynamoDB accumulates state records for all historical patients indefinitely, increasing cost and expanding the PHI surface area in the hot store.

**Suggested fix:** Add a note that DynamoDB items for completed treatment courses should be archived to S3 (for training pipeline access) and deleted from DynamoDB after a retention period (e.g., 90 days post-treatment completion). Use DynamoDB TTL on a `treatment_end_date + 90d` attribute.

---

### Architecture Expert Review

#### What's Done Well

The two-phase architecture (training vs. inference) is cleanly separated. The choice of Lambda for inference is well-justified: the workload is lightweight (neural network forward pass on a state vector), infrequent (once per patient per day), and latency-tolerant (500ms is fine when the patient is already on the treatment table). Step Functions for pipeline orchestration is appropriate for the multi-step training workflow. The "Where it struggles" section is honest and comprehensive.

#### Issue A1: Safety Constraints Are Formulated as Soft Penalties, Not Hard Constraints (CRITICAL)

**Location:** Step 5 (train_policy), `constraint_penalties` parameter; Step 2 (get_recommendation), `verify_constraints` function; reward function formulation

**The problem:** The recipe presents two different safety mechanisms that are inconsistent in their guarantees:

1. **Training time:** The `train_cql` call includes `constraint_penalties=training_config.safety_constraints` with the comment "if an action would push any OAR past tolerance, apply large negative reward." A large negative reward is a soft penalty. It makes constraint violations unlikely but does not guarantee they cannot occur. The policy network is a function approximator; it can output any action probability distribution regardless of training penalties. A sufficiently novel state (out-of-distribution) can produce a recommendation that violates OAR tolerances.

2. **Inference time:** The `verify_constraints` function in Step 2 provides a hard safety check that overrides the policy if constraints would be violated. This is the correct approach.

The inconsistency is the problem. The recipe's reward function section says:

> "RL must operate within hard constraints, not just optimize expected reward. This requires constrained RL formulations (constrained MDPs, safe RL) that guarantee constraint satisfaction, not just penalize violations."

But the actual implementation uses penalty-based soft constraints in training and relies on the inference-time safety check as the hard constraint. This is a valid engineering approach (belt and suspenders), but the recipe conflates the two. A reader could implement only the training-time penalties (following the pseudocode literally) without the inference-time safety check, believing the constrained MDP formulation provides guarantees. It does not, as implemented here.

For radiation therapy, a single constraint violation (e.g., recommending "continue" when continuing would push the spinal cord past 50 Gy) could cause permanent neurological damage. This is not a "the model performs slightly worse" failure mode. It's a patient safety issue.

**Suggested fix:** 

1. In the Technology section, clearly distinguish between soft constraints (penalty-based, used during training to shape the policy toward safe behavior) and hard constraints (inference-time verification that blocks unsafe actions regardless of what the policy outputs). State explicitly that soft constraints alone are insufficient for safety-critical applications.

2. In Step 5, rename `constraint_penalties` to `safety_shaping_penalties` and add a comment: "These penalties encourage the policy to avoid unsafe actions during training, but do not guarantee constraint satisfaction. The inference-time safety check (Step 2) provides the hard guarantee."

3. In Step 2, elevate the `verify_constraints` function from a brief code block to a more detailed discussion. Specify what constraints are checked (cumulative OAR dose + remaining fraction dose vs. tolerance), how the "safe alternative" is determined, and what happens if no safe action exists (halt treatment and alert the physician immediately).

4. Add a note in "The Honest Take" or a new subsection: "The safety architecture has two layers: training-time shaping (makes unsafe recommendations rare) and inference-time verification (makes unsafe recommendations impossible to execute). Both are required. Neither alone is sufficient."

#### Issue A2: Offline Evaluation Methodology Is Underspecified (HIGH)

**Location:** Step 5, `evaluate_policy` call; "Performance benchmarks" table

**The problem:** The validation step calls `evaluate_policy` with metrics including `expected_tcp` and `expected_ntcp`, but doesn't explain how these are computed for a policy that was never deployed. This is the fundamental challenge of offline policy evaluation (OPE), and the recipe hand-waves past it.

The performance benchmarks table claims "Estimated TCP improvement over fixed-schedule replanning: 2-5% (simulation)" and "Estimated NTCP reduction: 8-15% (simulation)." These numbers come from somewhere, but the recipe doesn't explain the evaluation methodology:

- Is this importance-weighted evaluation (using the behavior policy's action probabilities to reweight outcomes)?
- Is this trajectory-based evaluation (rolling out the learned policy in the simulator)?
- Is this direct method evaluation (using a learned outcome model)?

Each method has different assumptions and failure modes. Importance sampling has high variance with long horizons (35 fractions). Simulator-based evaluation inherits all simulator fidelity issues. Direct methods require a separate outcome model that may be wrong.

A reader who sees "2-5% TCP improvement" without understanding the evaluation methodology may overstate confidence in the policy's real-world performance.

**Suggested fix:** Add a subsection in the Technology section or in the training pipeline discussion that covers offline policy evaluation:
- Name the three main OPE approaches (importance sampling, model-based/simulator rollout, direct method)
- State which one the architecture uses (simulator rollout, given the simulator is already built for training)
- Acknowledge the limitation: simulator-based evaluation is only as good as the simulator
- Note that the performance benchmarks are simulator-estimated and that real-world validation requires prospective clinical trials

#### Issue A3: Simulator Calibration Is Mentioned but Never Specified (HIGH)

**Location:** "Simulator Calibration" in Training Phase; "Simulation for Data Augmentation" section

**The problem:** The recipe correctly identifies that the simulator is critical ("the entire training approach depends on the simulator being a reasonable approximation of reality") and lists what it models (tumor response, anatomical deformation, imaging noise, dose calculation). But it never specifies:

- How the simulator is calibrated against real patient data
- What validation metrics determine if the simulator is "good enough"
- How you detect when the simulator has drifted from reality (new treatment protocols, new equipment)
- What the failure mode looks like when the simulator is wrong (policy learns strategies that work in simulation but fail on real patients)

The Step Functions pipeline includes "Simulator Calibration" as a step, but the pseudocode only covers feature engineering and RL training. The calibration step is architecturally present but technically empty.

For a system where the entire safety argument rests on "we trained in simulation and validated on held-out real data," the simulator's fidelity is the single most important technical component. Leaving it as a black box undermines the recipe's credibility.

**Suggested fix:** Add a paragraph in the "Simulation for Data Augmentation" section that covers:
- Calibration approach: fit simulator parameters (tumor radiosensitivity, repopulation rate, deformation model parameters) to match observed trajectories in the historical dataset
- Validation: compare simulated treatment trajectories to real ones using distributional metrics (e.g., Wasserstein distance on tumor volume curves, KL divergence on dose accumulation distributions)
- Monitoring: periodically re-validate the simulator against new real data; if distributional metrics exceed a threshold, trigger recalibration before retraining the policy
- Failure mode: if the simulator systematically underestimates tumor response variability, the policy will be overconfident about "continue" actions and under-recommend replanning

#### Issue A4: Lambda Cold Start Latency Not Addressed for Clinical Workflow (MEDIUM)

**Location:** "AWS Lambda for inference" justification; performance benchmarks showing "<500 ms" latency

**The problem:** The recipe claims "<500 ms" recommendation latency using Lambda. A Lambda function loading a neural network model (even a small one) from S3 or from a Lambda layer will have cold start latency of 1-5 seconds depending on model size and runtime. The recipe says the model is "cached in Lambda memory across invocations," but Lambda functions are ephemeral. If the function hasn't been invoked recently (which is likely given once-per-patient-per-day frequency), every invocation is a cold start.

With ~100 active patients, each getting one recommendation per day, the function is invoked ~100 times per day. That's roughly 4 invocations per hour. Lambda will almost certainly recycle the execution environment between invocations, meaning nearly every call is a cold start.

The "<500 ms" claim is achievable for warm invocations but misleading for the actual usage pattern.

**Suggested fix:** Either: (a) acknowledge that cold starts will dominate and adjust the latency estimate to "1-3 seconds typical (cold start), <500 ms warm"; or (b) recommend provisioned concurrency (1 instance) to keep the function warm, with the cost tradeoff noted (~$15-20/month for a single provisioned instance); or (c) note that 1-3 second latency is clinically acceptable since the recommendation is generated before the patient is on the treatment table, not during active beam delivery.

#### Issue A5: No Discussion of Data Drift Detection (MEDIUM)

**Location:** "Amazon CloudWatch for monitoring and alerting" description

**The problem:** The CloudWatch description mentions "Alert on drift (recommendations diverging from historical patterns) or anomalies (unexpected state values)" but provides no specifics on how drift is detected. For a clinical system:

- Input drift: patient population changes (new tumor sites, different demographics, different treatment protocols)
- Concept drift: the relationship between state features and optimal actions changes (new evidence about replanning benefits)
- Performance drift: acceptance rate drops, or outcomes for patients who followed recommendations worsen

The recipe mentions acceptance rate tracking (Step 4) but doesn't connect it to a formal drift detection mechanism or specify what thresholds trigger retraining.

**Suggested fix:** Add 2-3 sentences specifying concrete drift detection: monitor the distribution of input state features (flag if KL divergence from training distribution exceeds threshold), track rolling acceptance rate (alert if it drops below 50% over a 2-week window), and compare predicted vs. actual tumor volume trajectories for patients who followed recommendations (flag systematic prediction errors).

---

### Networking Expert Review

#### What's Done Well

The prerequisites correctly specify "all compute in VPC with VPC endpoints for S3, DynamoDB, SageMaker, CloudWatch Logs. No public internet access for training or inference workloads." This is the right baseline for a system handling radiation treatment data.

#### Issue N1: VPC Endpoint List Is Incomplete for the Stated Architecture (HIGH)

**Location:** Prerequisites table, "VPC" row

**The problem:** The recipe specifies VPC endpoints for S3, DynamoDB, SageMaker, and CloudWatch Logs. But the architecture also uses:

- **AWS Step Functions:** The training pipeline uses Step Functions for orchestration. If the Step Functions API calls originate from within the VPC (e.g., a Lambda function starting a state machine execution), a VPC endpoint for Step Functions (`com.amazonaws.{region}.states`) is required.
- **AWS Lambda:** If Lambda functions need to call other AWS services from within the VPC, they need either a NAT gateway or VPC endpoints for each service they call. The inference Lambda calls DynamoDB and S3 (covered), but also needs to write CloudWatch metrics (`com.amazonaws.{region}.monitoring`) if custom metrics are published.
- **AWS KMS:** The recipe specifies KMS encryption for S3 and DynamoDB. Any service decrypting data needs to reach KMS. A VPC endpoint for KMS (`com.amazonaws.{region}.kms`) is required if there's no NAT gateway.

The recipe says "No public internet access for training or inference workloads" but doesn't provide the complete VPC endpoint set needed to achieve this. A builder following this literally will deploy Lambda in a VPC, find it cannot reach KMS to decrypt the model or patient state, and get timeout errors with no useful error message.

**Suggested fix:** Expand the VPC row to list all required endpoints: S3 (gateway), DynamoDB (gateway), SageMaker API and SageMaker Runtime (interface), Step Functions (interface), CloudWatch Logs (interface), CloudWatch Monitoring (interface), KMS (interface). Note the approximate cost of the interface endpoints (~$7-8/month each in a 3-AZ deployment, ~$50-60/month total for the full set).

#### Issue N2: No Mention of TPS Integration Network Path (MEDIUM)

**Location:** "Clinical Integration" prerequisite; inference phase architecture

**The problem:** The inference phase requires API access to the Treatment Planning System (TPS) for state extraction ("HL7 FHIR or proprietary TPS API"). The TPS is almost certainly on-premises or in a hospital network, not in AWS. The recipe doesn't discuss how the Lambda function in a private VPC reaches the TPS:

- AWS Direct Connect or Site-to-Site VPN to the hospital network?
- API Gateway with a private integration?
- AWS PrivateLink if the TPS vendor offers it?

This is a non-trivial networking decision that affects latency, reliability, and security of the clinical integration. A builder who gets the RL algorithm working but can't connect to the TPS has a system that cannot function.

**Suggested fix:** Add a note in the prerequisites or architecture section: "TPS integration requires network connectivity between the AWS VPC and the hospital network. Options include AWS Direct Connect (lowest latency, highest reliability), Site-to-Site VPN (lower cost, acceptable for once-daily queries), or an API gateway intermediary if the TPS exposes a public API with mutual TLS. The choice depends on the institution's existing AWS connectivity and the TPS vendor's integration options."

---

### Voice Reviewer

#### What's Done Well

The voice is strong throughout. The opening ("Here's the thing about radiation therapy that most people outside oncology don't realize") is classic CC. The parenthetical asides work well ("(ok, this is a gross oversimplification, but stay with me)" energy without being that exact phrase). The "Honest Take" section is genuinely honest and self-aware. The technical depth is appropriate for the audience. The 70/30 vendor balance is well-maintained: the Technology section is entirely vendor-agnostic, and AWS only appears in the implementation section.

#### Issue V1: Em Dashes Present (MEDIUM)

**Location:** Multiple locations throughout the recipe

**The problem:** The style guide states "No em dashes. Ever." The recipe contains em dashes in the following locations:

1. "the plan you make on day one is wrong by day fifteen" section: "30 to 35 daily fractions (sessions)" is fine, but checking for actual em dash characters (U+2014):
   - Cost estimate header: "$2,000–$8,000/month" uses an en dash, which is acceptable for ranges
   - "Not on a fixed schedule, but based on what's actually happening" - no em dash here

After careful review, the recipe appears to use en dashes (–) only in the cost range in the header, which is standard for numeric ranges and not an em dash violation. No actual em dashes (—) found.

**Status:** PASS on em dashes. The en dash in the cost range is acceptable typographic convention for numeric ranges.

#### Issue V2: "TODO" Placeholders in Additional Resources (MEDIUM)

**Location:** "Additional Resources" section, "Research References" and "Clinical Context" subsections

**The problem:** The recipe contains five TODO items:

```
- TODO: Verify and add specific paper citations for offline RL in radiation therapy
- TODO: Verify citation for Conservative Q-Learning (Kumar et al., NeurIPS 2020)
- TODO: Verify citation for Batch-Constrained Q-Learning (Fujimoto et al., ICML 2019)
- TODO: Verify link to AAPM Task Group reports on adaptive radiation therapy
- TODO: Verify link to ASTRO guidelines on image-guided radiation therapy
```

These are not publishable. The recipe references CQL and BCQ by name in the Technology section, making the citations essential for credibility. The AAPM and ASTRO references are important for clinical context.

**Suggested fix:** Either verify and add the citations (CQL: Kumar et al., "Conservative Q-Learning for Offline Reinforcement Learning," NeurIPS 2020; BCQ: Fujimoto et al., "Off-Policy Deep Reinforcement Learning without Exploration," ICML 2019) or remove the TODO placeholders and add a note that readers should search for these papers directly. Do not publish with TODO markers.

#### Issue V3: "The Honest Take" Could Acknowledge Patient Consent (LOW)

**Location:** "The Honest Take" section

**The problem:** The recipe discusses clinician acceptance rates and trust-building but never mentions patient consent. A clinical decision support system that influences radiation treatment decisions raises informed consent questions: does the patient know an AI system is contributing to their treatment planning? Different institutions and jurisdictions have different requirements. This isn't a technical issue but it's a completeness issue for a recipe that claims to cover the path to clinical deployment.

**Suggested fix:** Add one sentence in "The Honest Take" or "Why This Isn't Production-Ready": "Patient informed consent for AI-assisted treatment planning is an evolving area; some institutions require explicit disclosure that an AI system contributes to treatment recommendations, while others consider it part of standard clinical decision support that doesn't require separate consent."

#### Issue V4: One Instance of Documentation-Voice (LOW)

**Location:** "General Architecture Pattern" section opening

**The problem:** "At a conceptual level, the system has two phases: training (offline) and inference (clinical use)." This is slightly documentation-voice. It's not egregious, but it's more textbook than the rest of the recipe's conversational tone.

**Suggested fix:** Minor rewrite: "The system splits cleanly into two phases: training (offline, periodic) and inference (daily, at the treatment machine)." Matches the recipe's conversational register better.

---

## Stage 2: Expert Discussion

### Conflict Resolution

**Safety constraints (A1) vs. Architecture simplicity:** The CRITICAL finding on safety constraints creates tension with the recipe's goal of being accessible. The fix (clearly distinguishing soft vs. hard constraints, elevating the inference-time safety check) adds complexity but is non-negotiable for a radiation therapy application. Patient safety trumps pedagogical simplicity.

**VPC completeness (N1) vs. Recipe length:** The networking gaps add prerequisite detail that makes the recipe longer. However, for a system where "no public internet access" is stated as a requirement, incomplete VPC endpoint lists are deployment blockers. The fix is a table expansion, not a prose expansion.

**Offline evaluation (A2) vs. Scope:** The recipe is already long. Adding a full OPE methodology section risks scope creep. Resolution: a focused paragraph (not a full section) that names the approaches, states which one is used, and acknowledges the limitation. This is sufficient for the cookbook format.

### Priority Ordering

1. A1 (CRITICAL): Safety constraint formulation. This is a patient safety issue.
2. A2 (HIGH): Offline evaluation methodology. Without this, the performance claims are ungrounded.
3. A3 (HIGH): Simulator calibration specification. The entire approach rests on simulator fidelity.
4. N1 (HIGH): VPC endpoint completeness. Deployment blocker.
5. V2 (MEDIUM): TODO placeholders. Not publishable.
6. A4 (MEDIUM): Lambda cold start. Misleading latency claim.
7. A5 (MEDIUM): Drift detection. Operational gap.
8. S1 (MEDIUM): IAM permissions incomplete. Deployment friction.
9. S2 (MEDIUM): Model versioning. Clinical traceability gap.
10. N2 (MEDIUM): TPS network path. Integration gap.
11. V3 (LOW): Patient consent mention.
12. V4 (LOW): Documentation-voice instance.
13. S3 (LOW): DynamoDB TTL/retention.
14. Regulatory (see below, HIGH): FDA pathway underspecified.

### Additional Cross-Expert Finding

#### Issue R1: FDA Regulatory Pathway Discussion Is Incomplete (HIGH)

**Location:** "Why This Isn't Production-Ready" section, first paragraph

**The problem:** The recipe states: "FDA clearance (likely 510(k) or De Novo) requires clinical evidence that the system improves outcomes or is at least non-inferior to standard practice."

This is an oversimplification that could mislead a reader planning a regulatory strategy:

1. A 510(k) requires a predicate device. There is no cleared RL-based adaptive radiotherapy system to serve as a predicate. 510(k) is unlikely to be the pathway.
2. De Novo is for novel devices without predicates that are low-to-moderate risk. An RL system that influences radiation dose decisions may be classified as Class III (high risk), requiring a PMA (Premarket Approval), not De Novo.
3. The recipe doesn't mention the FDA's guidance on "Clinical Decision Support Software" (21st Century Cures Act, Section 3060), which exempts certain CDS from device regulation if it meets four criteria (one of which is that the clinician can independently review the basis for the recommendation). This exemption is the most likely regulatory path for the advisory system described here.
4. The recipe doesn't mention FDA's "Predetermined Change Control Plan" framework for ML-based devices that learn over time, which is directly relevant to a system that retrains periodically.

**Suggested fix:** Replace the single sentence with a brief paragraph: "The regulatory pathway depends on how the system is positioned. If it meets the four criteria for non-device CDS under the 21st Century Cures Act (displays information, intended for clinician use, clinician can independently review the basis, not intended to replace clinical judgment), it may be exempt from FDA device regulation entirely. If it doesn't qualify for the CDS exemption (e.g., if it becomes more autonomous), De Novo classification is more likely than 510(k) given the absence of a predicate device. The FDA's Predetermined Change Control Plan framework is relevant for the periodic retraining aspect. Consult regulatory counsel early; the classification decision shapes the entire development and validation strategy."

---

## Stage 3: Synthesized Feedback

### Verdict: **FAIL**

One CRITICAL finding (A1: safety constraint formulation) automatically triggers FAIL. Additionally, there are 4 HIGH findings (A2, A3, N1, R1) which independently exceed the 3-HIGH threshold.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| A1 | CRITICAL | Architecture | Step 2, Step 5, reward function section | Safety constraints formulated as soft penalties in training; recipe conflates penalty-based shaping with hard constraint guarantees. A reader could implement only training-time penalties without inference-time safety checks. For radiation therapy, a single constraint violation can cause permanent patient harm. | Clearly distinguish soft constraints (training shaping) from hard constraints (inference-time verification). Rename `constraint_penalties` to `safety_shaping_penalties`. Elevate `verify_constraints` to a detailed discussion. Add explicit statement that both layers are required and neither alone is sufficient. |
| A2 | HIGH | Architecture | Step 5, performance benchmarks table | Offline policy evaluation methodology unspecified. Performance claims (2-5% TCP improvement, 8-15% NTCP reduction) are presented without explaining how they were computed or what assumptions they rest on. | Add focused paragraph on OPE approaches. State that benchmarks are simulator-based estimates. Acknowledge that real-world validation requires prospective trials. |
| A3 | HIGH | Architecture | "Simulation for Data Augmentation" section, Training Phase | Simulator calibration is architecturally present but technically empty. No specification of calibration method, validation metrics, or failure detection. The entire safety argument rests on simulator fidelity. | Add paragraph covering calibration approach (parameter fitting to historical trajectories), validation metrics (distributional comparison), monitoring (periodic re-validation), and failure modes. |
| N1 | HIGH | Networking | Prerequisites table, "VPC" row | VPC endpoint list incomplete. Missing: Step Functions, KMS, CloudWatch Monitoring. Recipe states "no public internet access" but doesn't provide the endpoint set needed to achieve this. Deployment blocker. | Expand VPC row to list all required endpoints with service names. Note approximate cost (~$50-60/month for interface endpoints in 3-AZ deployment). |
| R1 | HIGH | Cross-expert | "Why This Isn't Production-Ready" section | FDA regulatory pathway oversimplified. Incorrectly suggests 510(k) as likely path. Doesn't mention CDS exemption under 21st Century Cures Act (most likely path for advisory system). Doesn't mention Predetermined Change Control Plan for retraining systems. | Replace single sentence with paragraph covering CDS exemption criteria, De Novo vs. PMA classification, and PCCP framework. Recommend early regulatory counsel. |
| V2 | MEDIUM | Voice | "Additional Resources" section | Five TODO placeholders for citations and links. Not publishable. CQL and BCQ are referenced by name in the Technology section, making citations essential. | Verify and add citations (Kumar et al. NeurIPS 2020 for CQL; Fujimoto et al. ICML 2019 for BCQ). Add AAPM/ASTRO references or remove TODOs. |
| A4 | MEDIUM | Architecture | Lambda inference justification; performance benchmarks | Lambda cold start latency not addressed. With ~100 invocations/day, nearly every call is a cold start (1-5s). "<500 ms" claim is misleading for actual usage pattern. | Acknowledge cold start dominance. Either adjust latency estimate, recommend provisioned concurrency, or note that 1-3s is clinically acceptable (recommendation generated before beam delivery). |
| A5 | MEDIUM | Architecture | CloudWatch description | Drift detection mentioned but unspecified. No concrete metrics, thresholds, or retraining triggers for a clinical system. | Add 2-3 sentences: monitor input feature distribution (KL divergence), track rolling acceptance rate (alert below 50%), compare predicted vs. actual tumor trajectories. |
| S1 | MEDIUM | Security | Prerequisites table, "IAM Permissions" row | IAM permissions incomplete. Missing KMS actions (required for encrypted S3/DynamoDB access), CloudWatch actions, CloudWatch Logs actions. KMS omission is a deployment blocker for encrypted resources. | Add `kms:Decrypt`, `kms:GenerateDataKey` (scoped to CMK ARN), CloudWatch and Logs actions. Note least-privilege scoping. |
| S2 | MEDIUM | Security | Step 5, `register_model` call | No model versioning, rollback, or provenance strategy. For a clinical system, inability to quickly revert to a previous model version is a safety gap. | Add brief discussion of model versioning (S3 versioning, "current model" pointer, rollback procedure). Note that recommendation output should include model version ID. |
| N2 | MEDIUM | Networking | Inference phase architecture; "Clinical Integration" prerequisite | No discussion of network path between AWS VPC and hospital TPS (on-premises). Builder cannot complete the integration without this. | Add note covering options: Direct Connect, Site-to-Site VPN, API gateway with mTLS. Note dependency on institution's existing AWS connectivity. |
| V3 | LOW | Voice | "The Honest Take" section | No mention of patient informed consent for AI-assisted treatment planning. Completeness gap for a recipe discussing clinical deployment path. | Add one sentence acknowledging evolving consent requirements for AI-assisted treatment decisions. |
| V4 | LOW | Voice | "General Architecture Pattern" opening sentence | Slightly documentation-voice: "At a conceptual level, the system has two phases." | Rewrite to match conversational register: "The system splits cleanly into two phases: training (offline, periodic) and inference (daily, at the treatment machine)." |
| S3 | LOW | Security | DynamoDB architecture description | No TTL or retention policy for patient state history. Completed treatment courses accumulate indefinitely in hot store, expanding PHI surface area. | Add note on DynamoDB TTL (archive to S3 after treatment completion + buffer, then delete from DynamoDB). |

---

### Priority Actions Before Publication

1. **Fix A1 (CRITICAL):** Restructure safety constraint discussion to clearly separate soft constraints (training-time shaping) from hard constraints (inference-time verification). This is a patient safety issue and the single most important fix.

2. **Fix R1 (HIGH):** Expand FDA regulatory discussion. The current single sentence could actively mislead a team planning regulatory strategy. The CDS exemption under 21st Century Cures Act is the most relevant pathway and isn't mentioned.

3. **Fix A2 and A3 (HIGH):** Add offline evaluation methodology and simulator calibration specification. These are the two biggest credibility gaps: the recipe claims performance numbers without explaining how they were derived, and rests its entire approach on a simulator it never specifies how to validate.

4. **Fix N1 (HIGH):** Complete the VPC endpoint list. This is a deployment blocker that will cause silent failures (Lambda timeouts when it can't reach KMS or Step Functions).

5. **Fix V2 (MEDIUM):** Remove or resolve TODO placeholders. These are not publishable.

The remaining MEDIUM and LOW findings improve production-readiness and completeness but do not block a technically capable reader from understanding and implementing the core pattern.

---

*Review complete. Recipe 15.9 is one of the most technically ambitious in the entire cookbook and demonstrates genuine domain expertise in both RL and radiation oncology. The CRITICAL finding on safety constraints is a formulation clarity issue, not a fundamental architectural flaw: the inference-time safety check is present and correct, but the recipe's presentation could lead a reader to believe training-time penalties alone provide safety guarantees. The fixes are primarily about precision of language and completeness of specification, not architectural redesign.*
