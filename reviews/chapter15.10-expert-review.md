# Expert Review: Recipe 15.10 - Hospital Resource Allocation Under Uncertainty

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter15.10-hospital-resource-allocation-uncertainty.md`

---

## Overall Assessment

This is a strong capstone recipe for the RL chapter. The problem framing is excellent (the cascading constraint satisfaction narrative genuinely captures how hospital operations feel), the MDP formulation is clinically appropriate, the insistence on offline training and human-in-the-loop deployment is correct and unambiguous, and the "Honest Take" section is refreshingly realistic about the maturity of hospital RL in 2026. The CMDP formulation adds formal rigor. The simulator-first philosophy is the right recommendation.

However: there are gaps in the safety constraint architecture that could give a builder false confidence, the offline policy evaluation methodology has a significant technical flaw that would produce misleading results, the FDA regulatory discussion is entirely absent (this is a clinical decision support system), the IAM permissions are incomplete for the stated architecture, and the VPC section needs more specificity about PHI data flows.

Priority breakdown: 1 CRITICAL (missing FDA/regulatory discussion), 2 HIGH (OPE methodology flaw, safety constraint architecture gap), 4 MEDIUM, 3 LOW.

**Verdict: FAIL** (1 CRITICAL finding)

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

The prerequisites table correctly identifies BAA requirement with justification ("All operational data contains patient identifiers"), specifies SSE-KMS for S3, DynamoDB encryption at rest, Kinesis server-side encryption, and Lambda environment variable encryption. CloudTrail is mentioned for all API calls, and DynamoDB streams for state change audit. The decision logging in Step 5 (handle_human_decision) captures accepted/modified/rejected decisions with reasons, which supports post-hoc review. The explicit statement "you cannot do online RL in a live hospital" demonstrates correct safety thinking.

#### Issue S1: IAM Permissions List Is Incomplete for the Stated Architecture (MEDIUM)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** Listed permissions are `sagemaker:CreateTrainingJob`, `sagemaker:CreateModel`, `kinesis:GetRecords`, `dynamodb:PutItem/GetItem`, `lambda:InvokeFunction`, `s3:GetObject/PutObject`, `states:StartExecution`. Missing:

- `kms:Decrypt` and `kms:GenerateDataKey` (required for Lambda to read KMS-encrypted model artifacts from S3 and read/write encrypted DynamoDB items)
- `kinesis:DescribeStream`, `kinesis:GetShardIterator` (required for the State Aggregator Lambda to actually consume the Kinesis stream)
- `cloudwatch:PutMetricData` (for the monitoring described in the architecture)
- `logs:CreateLogGroup`, `logs:PutLogEvents` (Lambda and Step Functions logging)
- `sagemaker:DescribeTrainingJob` (for Step Functions to poll training job status)
- `apigateway:*` permissions are not mentioned but API Gateway is in the Ingredients table

Without `kms:Decrypt` on the Lambda execution role, the inference Lambda cannot read the trained model artifact from S3 when S3 SSE-KMS is the stated encryption.

**Suggested fix:** Expand IAM permissions to include KMS actions scoped to specific CMK ARN, Kinesis read actions, CloudWatch/Logs actions, and API Gateway management. Add a note that permissions should use resource-level ARN restrictions (not `*`).

#### Issue S2: No Discussion of Access Controls on Recommendation Logs (MEDIUM)

**Location:** Step 5 pseudocode, `LOG_RECOMMENDATION` and `LOG_DECISION` functions

**The problem:** The recipe logs every state vector (which contains patient census, acuity levels, and staffing data) and every recommendation. This is correct for audit purposes. But there's no discussion of:
- Who can access these logs (principle of least privilege for audit data)
- Whether the DynamoDB table containing state history should have fine-grained access control (IAM conditions on sort key patterns)
- Retention policies for recommendation logs (how long, when to archive to S3 Glacier)
- Whether state vectors should be pseudonymized (room numbers and unit assignments are indirect identifiers)

The state vector includes patient-level signals (acuity distribution, pending movements) that, combined with timestamps, could re-identify patients.

**Suggested fix:** Add a paragraph in the architecture section noting that recommendation logs contain indirect PHI, should be access-restricted to authorized operations staff and auditors, should have defined retention policies (e.g., 7 years per HIPAA), and should use DynamoDB item-level encryption with separate CMKs for audit data.

#### Issue S3: Lambda Model Loading Has No Integrity Verification (LOW)

**Location:** Step 5 pseudocode, `LOAD_MODEL(model_registry, stage="approved")`

**The problem:** The inference Lambda loads a model artifact from S3 via the model registry. There's no mention of verifying model artifact integrity (hash check) or provenance (was this model actually produced by an authorized training pipeline). In a clinical decision support context, a tampered model could produce systematically harmful recommendations.

**Suggested fix:** Add a brief note about signing model artifacts (S3 object metadata with SHA-256 hash from training pipeline) and verifying at load time. Mention that SageMaker Model Registry tracks model lineage, which partially addresses this.

---

### Architecture Expert Review

#### What's Done Well

The four-component architecture (data ingestion, simulation, training, decision support) is cleanly separated with clear data flow. Lambda for inference is well-justified at the stated 15-30 minute decision cadence. The choice of PPO with Lagrangian constraints is appropriate for the discrete action space with safety requirements. The domain randomization approach to handle sim-to-real gap is correct. The explicit framing as "decision support, not autonomous controller" is architecturally sound and prevents the most dangerous failure mode.

#### Issue A1: Hard Constraint Layer Architecture Is Underspecified (HIGH)

**Location:** "Safety Constraints in Hospital RL" section; Step 3 pseudocode, `GET_FEASIBLE_ACTIONS` function; Step 5 pseudocode, `CHECK_HARD_CONSTRAINTS` function

**The problem:** The recipe correctly identifies that hard constraints "must be enforced at action selection time, not just penalized in the reward." It mentions a "constraint checker that vetoes any action violating hard constraints." But the architecture does not specify:

1. Where the constraint checker lives in the inference path (is it a separate Lambda? A library in the inference Lambda? A rules engine?)
2. What happens when ALL top-k actions from the policy are infeasible (the recipe shows filtering top-3, but doesn't handle the case where all 3 violate constraints)
3. How constraint rules are maintained and updated (staffing ratios change with CMS regulation updates; isolation requirements change with new infection control policies)
4. Whether constraint checking is synchronous and blocking (it must be, but this should be explicit)
5. How the constraint checker handles conflicting hard constraints (e.g., minimum staffing ratio in unit A conflicts with minimum staffing ratio in unit B when total staff is insufficient)

The gap between the theoretical guarantee ("hard constraint layer is the safety guarantee") and the implementation detail (pseudocode shows `CHECK_HARD_CONSTRAINTS` as a black box) is concerning. A builder might implement the constraint checker as a simple range check and miss edge cases.

**Suggested fix:** Add a subsection describing the constraint checker architecture: (1) it runs inline in the inference Lambda before any recommendation is emitted, (2) it uses a rule engine with versioned rule definitions stored in DynamoDB, (3) if all top-k actions are infeasible, the system returns "no recommendation available, human judgment required" rather than relaxing constraints, (4) constraint rules are updated through a governed process with version history, (5) conflicting constraints trigger an alert to the capacity coordinator.

#### Issue A2: Offline Policy Evaluation Methodology Has a Significant Flaw (HIGH)

**Location:** Step 4 pseudocode, "Importance-weighted evaluation (off-policy)"

**The problem:** The importance sampling OPE implementation shown has a well-known failure mode that isn't discussed: when the learned policy assigns high probability to actions that the behavior policy rarely took, the importance weights explode (high variance). The pseudocode shows basic importance sampling without any variance reduction technique.

More specifically:
- The code computes `weight = policy_action_probs[actual_action] / behavior_policy_prob(actual_action)` but doesn't discuss where `behavior_policy_prob` comes from. Estimating the behavior policy (how charge nurses actually made decisions) from observational data is a hard problem in itself.
- There's no discussion of weight clipping or self-normalized importance sampling (SNIS), which are standard in practice.
- The bootstrap confidence interval at the end is not valid for importance-weighted estimators without correction for the weight variance.
- The `pass_threshold` check (`avg_improvement > MIN_IMPROVEMENT AND ci_lower > 0`) is reasonable in concept but the CI construction is unreliable given the issues above.

A builder following this pseudocode would get a policy evaluation with misleadingly narrow confidence intervals and potentially accept a policy that doesn't actually outperform the baseline.

**Suggested fix:** (1) Note that behavior policy estimation requires a separate modeling step (e.g., fit a behavior cloning model to historical decisions). (2) Recommend per-decision importance sampling (PDIS) or doubly-robust methods rather than basic IS. (3) Add weight clipping (`min(weight, C)` where C is typically 5-10). (4) Note that the CI should use the empirical Bernstein bound or similar variance-aware method rather than naive bootstrap. (5) Reference that high-stakes OPE (like clinical settings) should use multiple OPE estimators and check consistency.

#### Issue A3: Kinesis to Lambda State Aggregation Has No Error Handling Pattern (MEDIUM)

**Location:** Architecture diagram, `Lambda: State Aggregator` consuming from Kinesis

**The problem:** The architecture shows a Lambda consuming from Kinesis to build state vectors. But there's no discussion of:
- What happens when source systems send stale or out-of-order events (ADT systems are notorious for delayed messages)
- Whether the state aggregator uses tumbling windows or maintains running state (and if the latter, where state is persisted between Lambda invocations)
- How missing data is handled (if the staffing system is down, is the state vector incomplete? Does inference proceed with stale staffing data?)

For a decision support system that recommends nurse floating, acting on stale staffing data is actively harmful.

**Suggested fix:** Add a note that the state aggregator should (1) timestamp-order events with a grace period for late arrivals, (2) maintain current state in DynamoDB (not Lambda memory) for durability, (3) mark state vector fields with freshness timestamps, and (4) the inference Lambda should refuse to recommend if critical state fields are older than a threshold (e.g., staffing data > 15 minutes old).

#### Issue A4: Cost Estimate Range Is Too Wide to Be Useful (LOW)

**Location:** Header cost estimate "$3,000-$12,000/month" and Prerequisites table

**The problem:** A 4x range ($3K-$12K) doesn't help a reader budget. The breakdown in Prerequisites is better (training: $500-2K per run, inference: $50-200/month, storage: $100-500/month), but these don't add up to $3K-$12K/month unless you're retraining frequently. The simulation infrastructure cost (running many parallel simulator instances for training) isn't broken out separately.

**Suggested fix:** Add a line for simulation compute cost (CPU instances for parallel simulators during training) and clarify the assumed retraining frequency (weekly vs. monthly) that drives the range.

---

### Networking Expert Review

#### What's Done Well

The prerequisites table states "Training and inference in private subnets. VPC endpoints for S3, DynamoDB, SageMaker. No public internet access for PHI-containing workloads." This is the correct posture. The recipe correctly identifies that all operational data contains patient identifiers.

#### Issue N1: VPC Endpoint Coverage Is Incomplete for the Stated Services (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The recipe specifies VPC endpoints for S3, DynamoDB, and SageMaker. But the architecture also uses:
- Kinesis Data Streams (needs `com.amazonaws.{region}.kinesis-streams` interface endpoint)
- Step Functions (needs `com.amazonaws.{region}.states` interface endpoint)
- CloudWatch/Logs (needs `com.amazonaws.{region}.monitoring` and `com.amazonaws.{region}.logs` interface endpoints)
- API Gateway (needs `com.amazonaws.{region}.execute-api` interface endpoint for private APIs, or clarify that the API is internal only)

Without the Kinesis VPC endpoint, the State Aggregator Lambda in a private subnet cannot consume from the Kinesis stream without a NAT Gateway, which means PHI-containing events would traverse the NAT to reach the Kinesis endpoint. This works but adds cost and a potential monitoring blind spot.

**Suggested fix:** Expand VPC endpoint list to include Kinesis Streams, Step Functions, CloudWatch, CloudWatch Logs, and API Gateway (or specify private API). Add a note that NAT Gateway is acceptable as fallback but VPC endpoints are preferred for PHI workloads (lower latency, no data processing charge, traffic stays on AWS backbone).

#### Issue N2: No Discussion of Network Segmentation Between Training and Inference (LOW)

**Location:** Architecture section

**The problem:** Training (SageMaker) and inference (Lambda) have different security profiles. Training consumes large volumes of historical data and runs for hours. Inference accesses real-time state and produces recommendations consumed by clinical staff. These should arguably be in separate VPCs or at minimum separate subnets with distinct security group rules. The recipe doesn't discuss this separation.

**Suggested fix:** Brief note that training infrastructure (SageMaker training jobs) and inference infrastructure (Lambda, API Gateway) should use separate security groups with independent inbound/outbound rules. Training subnets allow SageMaker-to-S3 only; inference subnets allow Lambda-to-DynamoDB-to-S3 only.

---

### Voice Reviewer

#### What's Done Well

The tone is strong throughout. The opening scenario ("it's Tuesday afternoon, your ICU is at 94% capacity...") is visceral and exactly the kind of hook that makes readers nod along. The line "No static rulebook handles this well" lands perfectly. "This is where reinforcement learning gets interesting" is a natural transition. "The Honest Take" section is one of the best in the book: "The reward function is a political document" is memorable and insightful. The self-deprecating closer ("What I'd do differently if starting over: spend the first 6 months on the simulator") is classic CC voice.

Zero em dashes found. Good.

#### Issue V1: "Let me be unambiguous about this" Is Slightly Off-Voice (LOW)

**Location:** "Offline vs. Online Learning" section, paragraph starting "You cannot do online RL in a live hospital."

**The problem:** The phrase "Let me be unambiguous about this" is slightly formal/authoritative in a way that doesn't match CC's conversational register. CC would more naturally say something like "I need to be really clear here" or "This is not negotiable" or just let the bold formatting carry the emphasis without the meta-commentary.

**Suggested fix:** Replace "Let me be unambiguous about this." with "Full stop." or "I want to be really clear here." or simply remove the sentence and let the bold emphasis do the work.

#### Issue V2: One Instance of Documentation-Voice in Prerequisites (LOW)

**Location:** Prerequisites table, "Sample Data" row: "Synthetic hospital operational data for development. Real ADT feeds for calibration (requires data governance approval)."

**The problem:** "Requires data governance approval" is bureaucratic documentation-voice. The rest of the recipe avoids this register. It's minor since it's in a table, but noticeable when everything else sounds like an engineer talking.

**Suggested fix:** "Real ADT feeds for calibration (you'll need data governance sign-off, which takes longer than you think)" or simply "Real ADT feeds for calibration (data governance approval needed)."

---

## Stage 2: Expert Discussion

### Conflict Resolution

**Architecture vs. Security on constraint checker:** Both experts identified the constraint checker as underspecified. Architecture focuses on the system design (where does it live, what happens at edge cases). Security focuses on the integrity (who can update constraint rules, how are changes audited). These are complementary, not conflicting. Both should be addressed.

**Architecture OPE issue vs. overall recipe positioning:** The OPE methodology flaw (A2) is HIGH severity because a builder following this pseudocode would get misleading evaluation results. However, the recipe correctly identifies OPE as "necessary but insufficient" in the Honest Take and recommends pilot deployment. This mitigates but does not eliminate the issue: the pseudocode still teaches a flawed technique.

**Missing FDA discussion priority:** All experts agree this is CRITICAL. The recipe explicitly frames this as a "decision support system." In the US, clinical decision support software may be regulated under 21 CFR 820 depending on its characteristics. The 2022 FDA guidance on Clinical Decision Support identifies criteria for when CDS is or is not a medical device. A system that recommends nurse floating and bed assignments based on patient acuity likely meets the definition of a medical device if it's "intended for use by healthcare professionals" and provides "patient-specific recommendations." The complete absence of any regulatory discussion for a clinical system is a critical gap.

---

## Stage 3: Synthesized Findings

### CRITICAL

| # | Finding | Expert | Location | Fix |
|---|---------|--------|----------|-----|
| 1 | **No FDA/regulatory discussion for a clinical decision support system.** This system recommends patient-specific resource allocation decisions (bed assignments based on acuity, nurse floating based on patient needs). Under FDA's 2022 CDS guidance, software that provides "patient-specific recommendations" to "healthcare professionals" and is "not intended for a healthcare professional to independently review" may require 510(k) clearance or De Novo classification. The recipe does not mention FDA, does not discuss the CDS criteria that determine regulatory status, does not mention state medical device regulations, and does not reference the exemption criteria that might apply. Any builder without this context could invest 18 months and discover they need regulatory clearance. | All | Entire recipe (absent) | Add a "Regulatory Considerations" subsection in The Honest Take or as a standalone section. Discuss: (1) FDA's 2022 guidance on CDS, (2) the 4 criteria for CDS exemption (displays information, intended for HCP, allows independent review, doesn't replace clinical judgment), (3) this system likely qualifies for exemption if properly designed as decision support with human override BUT must be carefully architected to maintain the exemption, (4) note that if the system ever moves toward autonomous operation (removing human override), it would likely require FDA clearance, (5) state-level regulations vary. |

### HIGH

| # | Finding | Expert | Location | Fix |
|---|---------|--------|----------|-----|
| 2 | **Offline policy evaluation pseudocode teaches a flawed methodology.** Basic importance sampling without variance reduction, no behavior policy estimation discussion, and unreliable confidence intervals. A builder following this would accept or reject policies based on misleading evidence. | Architecture | Step 4 pseudocode | Add weight clipping, discuss behavior policy estimation, recommend PDIS or doubly-robust estimators, fix CI construction, note that multiple OPE methods should be compared for high-stakes domains. |
| 3 | **Hard constraint architecture is underspecified to the point of being dangerous.** The recipe claims "hard constraint layer is the safety guarantee" but doesn't specify what happens when all actions are infeasible, how rules are maintained, or how conflicts are resolved. A builder might implement a trivial range check and assume they have safety guarantees. | Architecture + Security | "Safety Constraints" section, Steps 3 and 5 | Add constraint checker architecture details: inline execution, rule versioning, "no recommendation" fallback for all-infeasible states, conflict resolution protocol, governed update process. |

### MEDIUM

| # | Finding | Expert | Location | Fix |
|---|---------|--------|----------|-----|
| 4 | IAM permissions list incomplete (missing KMS, Kinesis read, CloudWatch, Logs, API Gateway actions) | Security | Prerequisites table | Expand list with resource-scoped permissions |
| 5 | No access controls, retention policy, or pseudonymization discussion for recommendation logs containing indirect PHI | Security | Step 5 pseudocode | Add paragraph on log access controls and retention |
| 6 | VPC endpoint coverage incomplete (missing Kinesis, Step Functions, CloudWatch, API Gateway endpoints) | Networking | Prerequisites table, VPC row | Expand VPC endpoint list |
| 7 | Kinesis-to-Lambda state aggregation has no staleness detection or error handling for missing/delayed source data | Architecture | Architecture diagram | Add state freshness checks and graceful degradation |

### LOW

| # | Finding | Expert | Location | Fix |
|---|---------|--------|----------|-----|
| 8 | Model artifact integrity verification not discussed (hash check at load time) | Security | Step 5, LOAD_MODEL | Brief note on signing artifacts |
| 9 | Cost estimate range too wide (4x) without clear breakdown of what drives variation | Architecture | Header and Prerequisites | Clarify retraining frequency assumption, add simulation compute line item |
| 10 | "Let me be unambiguous about this" is slightly off-voice | Voice | Offline vs. Online Learning section | Replace with more conversational phrasing |

---

## Summary

The recipe is technically excellent in its RL formulation, clinically grounded in its problem statement, and appropriately cautious in its deployment recommendations. The CRITICAL finding (missing FDA/regulatory discussion) is the blocker: any recipe describing a clinical decision support system that makes patient-specific recommendations to healthcare professionals MUST discuss the regulatory landscape. This isn't a nice-to-have; it's a safety and legal requirement for the target audience (architects designing healthcare AI systems).

The two HIGH findings (OPE methodology and constraint architecture) are both cases where the recipe states the right principle but provides implementation guidance that could mislead. The OPE pseudocode would produce unreliable evaluation results. The constraint checker description provides theoretical guarantees without specifying the implementation that delivers them.

Fix the CRITICAL and both HIGHs, and this becomes one of the strongest recipes in the book.
