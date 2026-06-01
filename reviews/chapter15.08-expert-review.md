# Expert Review: Recipe 15.8 - Chemotherapy Dose Optimization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter15.08-chemotherapy-dose-optimization.md`

---

## Overall Assessment

**Verdict: PASS**

This is an exceptionally well-written recipe that tackles one of the most clinically complex RL applications in the cookbook. The RL formulation is clinically appropriate (offline CQL for sequential dosing decisions, multi-objective reward with explicit tradeoff weights, hard safety constraints as a non-negotiable override layer). The recipe is honest about its research-stage status, correctly identifies the regulatory pathway challenges, and frames the system as decision support rather than autonomous dosing. The architecture is sound for the stated purpose (retrospective research and eventual clinical decision support). The safety constraint layer is clinically appropriate and correctly positioned as a hard override rather than a soft penalty. The vendor balance is excellent (the first ~70% is entirely vendor-agnostic RL and clinical domain teaching). No CRITICAL findings. Two HIGH findings related to security gaps. The recipe passes with required fixes.

Priority breakdown: 0 critical issues, 2 high issues, 4 medium issues, 3 low issues.

---

## Security Expert Review

### What's Done Well

- BAA requirement explicitly stated in Prerequisites table
- Encryption specified: S3 SSE-KMS, DynamoDB encryption at rest, SageMaker KMS for training volumes and endpoints, all transit over TLS
- CloudTrail enabled with explicit rationale ("log all API calls for HIPAA audit trail")
- VPC requirement stated: all services in VPC with VPC endpoints, SageMaker in private subnets, no public internet for PHI-processing components
- IAM permissions listed with specific actions (not wildcards)
- The `store_recommendation` call in Step 6 demonstrates audit trail awareness
- The recipe correctly identifies treatment records as PHI requiring BAA coverage

### Issue S1: IAM Permissions Not Scoped to Resource ARNs (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:GetItem`, `states:StartExecution`) are a flat list without resource ARN constraints. This system processes complete chemotherapy treatment trajectories (PHI including lab values, tumor measurements, dosing records, genetic markers). A compromised credential with unscoped `s3:PutObject` could overwrite model artifacts or training data across any bucket in the account. A compromised credential with unscoped `dynamodb:GetItem` could read any patient's state vector from any table.

**Suggested fix:** Replace the flat list with resource-scoped guidance:
```
IAM Permissions:
- sagemaker:CreateTrainingJob, CreateEndpoint on arn:aws:sagemaker:REGION:ACCOUNT:*  (scoped by tag-based conditions)
- s3:GetObject, PutObject on arn:aws:s3:::chemo-rl-trajectories/* and arn:aws:s3:::chemo-rl-models/*
- glue:StartJobRun on arn:aws:glue:REGION:ACCOUNT:job/chemo-trajectory-etl*
- dynamodb:PutItem, GetItem on arn:aws:dynamodb:REGION:ACCOUNT:table/chemo-patient-state
- states:StartExecution on arn:aws:states:REGION:ACCOUNT:stateMachine:chemo-rl-pipeline
Separate roles for: training pipeline, inference endpoint, ETL, clinician dashboard.
```

### Issue S2: No Access Control on Recommendation Audit Trail (HIGH)

**Location:** Step 6 pseudocode, `store_recommendation(patient_state.patient_id, recommendation)`

**The problem:** The `store_recommendation` function is called but there's no specification of immutability or access control for the audit store. For a system recommending chemotherapy doses (a life-or-death clinical decision), the audit trail must be tamper-evident. If a recommendation is later questioned (patient harmed, malpractice claim, regulatory inquiry), the institution must prove the recommendation was recorded accurately at the time it was made and has not been modified since. The DynamoDB "Decision Audit Trail" in the architecture diagram has no immutability specification.

**Suggested fix:** Add to the architecture description or Step 6 commentary:
```
// Audit trail requirements for clinical decision support:
// 1. Append-only: no updates or deletes permitted on recommendation records
// 2. Tamper-evident: use S3 Object Lock (compliance mode) for archival copies
// 3. Retention: minimum 7 years (malpractice statute of limitations varies by state)
// 4. Access: read-only for clinicians and compliance; write-only for the recommendation engine
// DynamoDB stores operational copies; S3 with Object Lock stores the compliance archive.
```

### Issue S3: Genetic Marker Data Requires Additional Access Controls (MEDIUM)

**Location:** State space definition, "Genetic markers (if available: DPYD, UGT1A1, etc.)"

**The problem:** Genetic information (pharmacogenomic markers) is subject to additional protections beyond standard PHI under GINA (Genetic Information Nondiscrimination Act) and various state genetic privacy laws. The recipe includes genetic markers in the state vector without noting that this data may require segregated storage, additional access controls, or specific consent documentation beyond standard HIPAA authorization. Some states (e.g., California, New York) have genetic privacy laws stricter than HIPAA.

**Suggested fix:** Add a note in the state space definition or Prerequisites: "Genetic markers (DPYD, UGT1A1) are subject to GINA and state genetic privacy laws beyond HIPAA. Segregate genetic data storage with additional access controls. Verify patient consent specifically covers use of genetic data in algorithmic decision support. Some institutions require separate IRB approval for genetic data use in ML systems."

### Issue S4: No Input Validation on State Vector Before Policy Inference (MEDIUM)

**Location:** Step 6, `generate_recommendation(patient_state, policy, safety_rules)`

**The problem:** The function accepts `patient_state` and passes it directly to `policy.recommend()`. There's no validation that the state vector values are within physiologically plausible ranges. An EHR integration error could pass ANC = -500 or bilirubin = 999, and the policy would produce a recommendation based on garbage input. The safety constraints check some thresholds but only after the policy has already made its recommendation. A corrupted state vector could produce a confident but dangerous recommendation that happens to pass all safety checks (e.g., if ANC is erroneously reported as 5000 when it's actually 200).

**Suggested fix:** Add input validation before policy inference:
```
FUNCTION validate_state(patient_state):
    // Reject physiologically impossible values before policy inference.
    // These catch EHR integration errors, not clinical edge cases.
    ASSERT 0 <= patient_state.anc <= 50000, "ANC out of physiological range"
    ASSERT 0 <= patient_state.platelets <= 1000000, "Platelets out of range"
    ASSERT 0 < patient_state.creatinine <= 30, "Creatinine out of range"
    ASSERT 0 < patient_state.bilirubin <= 50, "Bilirubin out of range"
    ASSERT patient_state.cycle_number >= 1, "Invalid cycle number"
    // If any validation fails: do not generate recommendation, alert clinician
```

---

## Architecture Expert Review

### What's Done Well

- CQL (Conservative Q-Learning) is the correct algorithmic choice: penalizes out-of-distribution actions, produces conservative policies that stay close to historical practice, appropriate for safety-critical domains
- The offline RL framing is correct: no online exploration on patients, learn from historical trajectories only
- The safety constraint layer is correctly positioned as a hard override (not a soft reward penalty), which is the right pattern for clinical safety
- The reward function design is explicitly framed as a clinical value judgment (not a learned parameter), with configurable weights. This is architecturally sound and clinically appropriate.
- The off-policy evaluation section correctly uses multiple estimators (IS + FQE) and checks for agreement. This is methodologically sound.
- The "Why This Isn't Production-Ready" section is honest and accurate about regulatory, validation, and liability gaps
- The architecture diagram correctly shows the feedback loop from outcomes back to training data
- Step Functions for pipeline orchestration is appropriate for the multi-stage training workflow
- The decision to use DynamoDB for real-time state vectors and S3 for batch training data is architecturally sound (right tool for each access pattern)
- The recipe correctly identifies data quality (not algorithms) as the primary bottleneck

### Issue A1: No Model Drift Detection or Retraining Trigger (MEDIUM)

**Location:** Architecture diagram and "Expected Results" section

**The problem:** The architecture shows a training pipeline and an inference endpoint but no mechanism to detect when the deployed policy becomes stale. Clinical practice evolves: new supportive care drugs (e.g., new G-CSF formulations), updated toxicity grading criteria, changes in imaging protocols, or shifts in patient demographics could all cause the training data distribution to diverge from the current patient population. The recipe mentions CloudWatch for "model drift, recommendation acceptance rates, outcome metrics" in the Ingredients table but provides no detail on what drift looks like or what triggers retraining.

**Suggested fix:** Add a subsection or expand the CloudWatch description: "Monitor for drift signals: (1) recommendation acceptance rate dropping below 60% (clinicians disagreeing more often suggests the policy is out of step with current practice), (2) patient state distributions shifting outside training data bounds (new patient populations the policy hasn't seen), (3) outcome metrics degrading over time (the policy's recommendations correlating with worse outcomes than historical baseline). Any of these triggers a retraining cycle via Step Functions."

### Issue A2: CQL Training Pseudocode Oversimplifies the Action Space (MEDIUM)

**Location:** Step 3, `train_offline_rl_policy`, the CQL penalty computation

**The problem:** The pseudocode shows `random_actions = sample_random_actions(batch_size=len(batch))` for the CQL penalty. But the action space is defined earlier as a structured tuple: `{dose_fraction: [0.25, 0.5, 0.75, 1.0, hold], delay_days: [0, 7, 14], gcsf_given: [true, false]}`. This is a discrete combinatorial space (5 x 3 x 2 = 30 actions). Sampling "random actions" from this space is straightforward, but the pseudocode doesn't clarify whether it's sampling uniformly from the 30 valid combinations or from a continuous space. For a pedagogical recipe, this matters because readers implementing CQL need to know whether to treat this as discrete-action CQL (simpler, enumerate all actions) or continuous-action CQL (harder, requires sampling).

**Suggested fix:** Add a comment in the CQL training loop:
```
// The action space is discrete (30 combinations of dose x timing x G-CSF).
// For discrete CQL: enumerate all 30 actions, compute Q-values for each,
// and the CQL penalty pushes down the max Q across all actions relative
// to the Q of the action actually taken. No random sampling needed.
// The random_actions formulation shown here is the continuous-action variant
// included for generality. For this specific problem, discrete CQL is simpler.
```

### Issue A3: No Discussion of Confounding Adjustment (LOW)

**Location:** "Why This Is Hard" section mentions confounding, but the training pipeline doesn't address it

**The problem:** The recipe correctly identifies confounding as a challenge ("Sicker patients got lower doses... If you naively learn from this data, you'll conclude that lower doses cause worse outcomes"). However, the training pipeline (Step 3) does not include any confounding adjustment. CQL addresses distribution shift (overconfidence about untested actions) but does not address confounding (systematic bias in which patients received which treatments). The recipe should note whether CQL's conservatism partially mitigates confounding or whether additional techniques (propensity weighting, instrumental variables, or explicit causal modeling) are needed.

**Suggested fix:** Add a note after Step 3 or in the Honest Take: "CQL's conservatism helps with confounding indirectly: by staying close to historical behavior, it avoids extrapolating into regions where confounding is worst (actions that were never taken for specific patient types). But it doesn't eliminate confounding. For stronger causal claims, consider propensity-weighted trajectories or doubly-robust estimators in the evaluation step. This is an active research area."

---

## Networking Expert Review

### What's Done Well

- VPC requirement explicitly stated: "all services in VPC with VPC endpoints"
- Private subnets specified for SageMaker training and endpoints
- "No public internet access for PHI-processing components" is the correct stance
- TLS specified for all transit
- The architecture keeps PHI within the AWS network boundary (no external API calls in the inference path)

### Issue N1: VPC Endpoints Not Enumerated by Type (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The recipe states "all services in VPC with VPC endpoints" but doesn't specify which endpoint types are needed. The recipe uses S3, DynamoDB, SageMaker, Glue, Step Functions, CloudWatch, and KMS. Some of these use gateway endpoints (free), others use interface endpoints (cost per AZ per hour). This is a common implementation stumbling block: teams budget for the architecture but miss the ~$50-100/month in interface endpoint costs, or worse, deploy without endpoints and have PHI traverse the public internet.

**Suggested fix:** Add to the VPC row or as a note:
```
VPC Endpoints needed:
- S3: Gateway endpoint (free)
- DynamoDB: Gateway endpoint (free)
- SageMaker Runtime: Interface endpoint (~$7.50/month/AZ)
- SageMaker API: Interface endpoint (~$7.50/month/AZ)
- Glue: Interface endpoint (~$7.50/month/AZ)
- Step Functions: Interface endpoint (~$7.50/month/AZ)
- CloudWatch: Interface endpoint (~$7.50/month/AZ)
- KMS: Interface endpoint (~$7.50/month/AZ)
Budget ~$45-90/month for interface endpoints (2-3 AZs).
```

### Issue N2: Glue ETL Network Path Not Specified (LOW)

**Location:** Architecture diagram, Glue ETL step

**The problem:** AWS Glue jobs can run in the default AWS-managed network or in a customer VPC. For ETL processing EHR data (PHI), Glue jobs must run in the customer VPC with appropriate security group rules. The recipe doesn't specify this. A Glue job running in the default network would have the EHR data traversing outside the customer's VPC boundary.

**Suggested fix:** Add to Prerequisites or the "Why These Services" section for Glue: "Configure Glue jobs with VPC connection to run within your VPC. Glue needs a NAT gateway or VPC endpoints for S3 access when running in VPC mode. Security group: allow outbound to S3 gateway endpoint only."

---

## Voice Reviewer

### What's Done Well

- The Problem section is outstanding: passionate, specific, makes the reader feel the clinical tension ("Patient A metabolizes oxaliplatin twice as fast as Patient B")
- The engineer-explaining-something-cool tone is consistent throughout ("This is a sequential decision problem under uncertainty with delayed, noisy rewards. That's exactly what reinforcement learning was designed for.")
- Self-deprecating honesty in the Honest Take ("the RL algorithms are not the bottleneck... You'll spend 80% of your time on data engineering and 20% on the actual RL")
- Parenthetical asides used effectively ("(ok, this is a gross oversimplification, but stay with me)" energy throughout)
- The 70/30 vendor balance is excellent: the entire Technology section, MDP formulation, offline RL explanation, and general architecture are completely vendor-agnostic. AWS appears only in the implementation section.
- The "Why This Isn't Production-Ready" section is refreshingly honest for a cookbook recipe
- Clinical domain knowledge is woven naturally into the narrative rather than presented as dry reference material
- The reward function explanation is pedagogically excellent: "Two equally valid reward functions with different toxicity-efficacy tradeoff weights will produce meaningfully different policies. This isn't a bug; it's a feature."

### Issue V1: Em Dash Check (PASS)

**Location:** Full file scan

**Result:** No em dashes found. The file uses colons, semicolons, periods, commas, and parentheses for clause separation throughout. Clean pass.

### Issue V2: Vendor Balance Check (PASS)

**Location:** Full recipe structure

**Result:** The Problem section (~800 words) is entirely clinical/domain. The Technology section (~2500 words) is entirely vendor-agnostic RL concepts. The General Architecture Pattern is vendor-agnostic. AWS services appear only starting at "The AWS Implementation" section. Estimated split: ~72% vendor-agnostic, ~28% AWS-specific. Within the target range.

### Issue V3: One Instance of Slightly Formal Register (LOW)

**Location:** "The State of the Field" subsection, final paragraph

**The problem:** "Current approaches to validation include: importance-weighted evaluation (estimating policy value from historical data), simulation with pharmacokinetic/pharmacodynamic (PK/PD) models, and expert review of recommended actions." This sentence reads slightly more like a survey paper than an engineer explaining something. The rest of the section maintains the conversational register well.

**Suggested fix:** Minor. Consider: "So how do you validate a policy you can't test on patients? Three approaches, none perfect: importance-weighted evaluation (estimate what would have happened using historical data), simulation with PK/PD models (build a fake patient and test on them), and expert review (show oncologists the recommendations and ask 'would you do this?')."

---

## Stage 2: Expert Discussion

### Cross-Expert Agreements

1. **Security + Architecture:** The audit trail immutability gap (S2) is the most significant security finding. For a system recommending chemotherapy doses, the legal and regulatory exposure of a mutable audit trail is substantial. Architecture agrees this is a design-level concern, not just a security annotation.

2. **Security + Networking:** The VPC endpoint enumeration (N1) and Glue network path (N2) are both about ensuring PHI doesn't traverse the public internet. Security's IAM scoping concern (S1) compounds with networking: if credentials are compromised AND the network path allows egress, the blast radius is maximized. Defense in depth requires both to be addressed.

3. **Architecture + Voice:** The CQL action space clarification (A2) is both a technical accuracy issue and a pedagogical one. The recipe's voice is "engineer explaining something cool," and an engineer would clarify whether they're doing discrete or continuous CQL. The current pseudocode is ambiguous in a way that could mislead implementers.

4. **All Experts:** The recipe's honest framing as research-stage (not production-ready) appropriately sets expectations. The "Why This Isn't Production-Ready" section and the Honest Take both correctly identify the gaps. This means some findings (like model drift detection) are less urgent than they would be for a recipe claiming production readiness.

### Priority Resolution

- The two HIGH findings (IAM scoping, audit trail immutability) are both security concerns that apply even to a research system processing real patient data. Research doesn't exempt you from HIPAA.
- The MEDIUM findings are improvements that strengthen the recipe's pedagogical value and production-readiness guidance.
- No conflicts between expert recommendations.
- The recipe's research-stage framing means some architectural concerns (drift detection, retraining triggers) are appropriately noted as future work rather than current gaps.

---

## Stage 3: Synthesized Findings

### Verdict: **PASS**

No CRITICAL findings. Two HIGH findings (both security-related, both fixable with annotation changes). The recipe is clinically accurate, architecturally sound, pedagogically excellent, and appropriately honest about its limitations. The RL formulation is correct for the domain. The safety constraint layer is well-designed. The voice is strong and consistent.

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites table, IAM Permissions row | Flat permission list without resource ARN constraints. System processes chemotherapy trajectories (PHI) including labs, tumor measurements, genetic markers. Unscoped credentials have account-wide blast radius. | Scope each permission to specific resource ARNs. Specify separate roles for training pipeline, inference endpoint, ETL, and clinician dashboard. |
| 2 | HIGH | Security | Step 6, `store_recommendation` call | Audit trail for chemotherapy dose recommendations has no immutability specification. Mutable audit records are indefensible in malpractice or regulatory proceedings. | Specify append-only storage with S3 Object Lock (compliance mode) for archival. Define retention period (minimum 7 years). Separate write-only (recommendation engine) from read-only (compliance/clinician) access. |
| 3 | MEDIUM | Security | State space definition, genetic markers | Pharmacogenomic data (DPYD, UGT1A1) subject to GINA and state genetic privacy laws beyond HIPAA. No mention of additional access controls or consent requirements for genetic data in ML systems. | Add note about GINA compliance, segregated storage for genetic markers, and specific consent requirements for algorithmic use of genetic data. |
| 4 | MEDIUM | Security | Step 6, `generate_recommendation` | No input validation on patient state vector before policy inference. EHR integration errors could pass physiologically impossible values, producing confident but dangerous recommendations that pass safety checks. | Add state validation function checking physiological plausibility ranges before policy inference. Reject and alert on impossible values. |
| 5 | MEDIUM | Architecture | Architecture diagram / CloudWatch description | No model drift detection or retraining trigger mechanism specified. Clinical practice evolution could make the deployed policy stale without any alerting. | Add drift monitoring signals: recommendation acceptance rate, state distribution shift, outcome metric degradation. Define retraining triggers. |
| 6 | MEDIUM | Networking | Prerequisites table, VPC row | VPC endpoints stated as required but not enumerated by type (gateway vs. interface). Common implementation stumbling block; teams miss interface endpoint costs or deploy without them. | Enumerate all needed endpoints with types and approximate monthly costs. |
| 7 | LOW | Architecture | Step 3, CQL training pseudocode | `random_actions` sampling is ambiguous for a discrete action space (30 combinations). Readers implementing CQL won't know whether to use discrete enumeration or continuous sampling. | Add comment clarifying that discrete CQL (enumerate all 30 actions) is simpler and more appropriate for this specific problem. |
| 8 | LOW | Networking | Architecture diagram, Glue ETL | Glue job network configuration not specified. Default Glue runs outside customer VPC; EHR data (PHI) would traverse outside VPC boundary. | Specify Glue VPC connection requirement and security group configuration. |
| 9 | LOW | Voice | "The State of the Field" subsection, final paragraph | One sentence reads slightly like a survey paper rather than engineer-explaining-something-cool register. | Rephrase to match conversational tone used elsewhere in the recipe. |

---

## Clinical Accuracy Assessment

The recipe demonstrates strong clinical accuracy across multiple dimensions:

**RL Formulation:**
- **State space** is clinically comprehensive and correctly prioritized: CBC (ANC, platelets, hemoglobin), liver function (AST, ALT, bilirubin), renal function (creatinine, GFR), tumor measurements, CTCAE toxicity grades, cycle number, cumulative dose, timing, demographics, performance status, and pharmacogenomic markers. These are exactly the variables an oncologist considers at each cycle.
- **Action space** (dose fraction at discrete levels + cycle timing + G-CSF) correctly represents the actual decision space. The discrete levels (100%, 75%, 50%, 25%, hold) match standard dose modification protocols.
- **Reward function** correctly implements the efficacy-toxicity tradeoff with appropriate asymmetry: discontinuation penalty (25.0) > severe toxicity penalty (15.0) > tumor response weight (10.0) > moderate toxicity penalty (3.0) > dose intensity bonus (1.0). This ordering reflects clinical priorities: keeping the patient on treatment is paramount, avoiding life-threatening toxicity is next, tumor response is the goal but not at any cost.
- **Decision interval** (per-cycle, typically every 2-3 weeks) correctly matches the clinical decision cadence.

**Safety Constraints:**
- ANC < 1000: hold treatment. Correct (standard of care for myelosuppressive chemotherapy).
- Platelets < 75,000: max 50% dose. Correct (bleeding risk threshold).
- Elevated bilirubin (>1.5x ULN): max 75% dose. Correct (hepatic clearance impairment affects drug metabolism).
- Never exceed 100% protocol dose. Correct and critical (dose escalation above protocol is never appropriate outside a clinical trial).
- Cumulative dose limits. Correct (e.g., anthracycline lifetime dose limits for cardiotoxicity).
- ECOG >= 3: hold treatment. Correct (patients with limited self-care ability have poor risk-benefit for aggressive chemotherapy).

**One clinical nuance worth noting:** The platelet threshold of 75,000 for dose reduction is reasonable but some protocols use 100,000 as the threshold for full-dose administration. The recipe's threshold is conservative (allows 50% dose between 75K-100K) which is safe but slightly more aggressive than some institutional protocols. This is within the range of clinical practice variation and not an error.

**Offline RL Methodology:**
- CQL is appropriate: penalizes overconfidence about untested actions, produces conservative policies
- The importance-weighted evaluation with clipping (0.01 to 100.0) is methodologically sound; extreme weights are the primary failure mode of IS estimators
- Using multiple OPE methods (IS + FQE) and checking agreement is best practice
- The recipe correctly notes that OPE is necessary but not sufficient for clinical validation

**Regulatory Assessment:**
- Correctly identifies FDA SaMD pathway as likely required
- Correctly references the 2021 FDA AI/ML action plan
- Correctly identifies the gap in regulatory frameworks for adaptive/learning systems
- Correctly notes that prospective validation (clinical trial) is required before deployment
- Correctly raises liability questions without pretending they're resolved
- The "Research/Clinical Validation" phase designation in the header is appropriate and honest

**Data Requirements:**
- "500-1000 complete treatment trajectories per regimen" is a reasonable minimum for offline RL with a moderate state/action space. This aligns with published research in the field.
- The recipe correctly identifies that rare tumor types and unusual pharmacogenomics will have insufficient training data.

**Overall clinical assessment:** The recipe is clinically sound, appropriately conservative in its safety constraints, honest about limitations, and correctly positioned as research-stage. No clinical inaccuracies that would mislead readers or create safety risks.

---

## Additional Notes

This is one of the strongest recipes in Chapter 15. The Problem section is genuinely compelling (the reader feels the clinical tension). The Technology section teaches offline RL from first principles without assuming prior knowledge. The safety constraint layer is the right architectural pattern for clinical AI (hard rules override learned policies). The Honest Take is refreshingly direct about the gap between algorithmic capability and clinical deployment. The recipe correctly identifies that this is a 2-4 year journey, not a weekend project, and that the bottleneck is data quality and clinical validation, not algorithms.

The two HIGH findings are both security annotations that can be fixed without restructuring the recipe. The MEDIUM findings improve pedagogical clarity and production-readiness guidance. This recipe should pass after addressing the HIGH findings.
