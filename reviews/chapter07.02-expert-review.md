# Expert Review: Recipe 7.2 - Propensity to Pay Scoring

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter07.02-propensity-to-pay-scoring.md`

---

## Overall Assessment

This is a well-crafted recipe that tackles a genuinely useful revenue cycle ML problem. The problem framing is compelling and grounded in real operational pain ($15-25M in annual bad debt for a mid-size hospital). The technology section is educational, covering the credit scoring analogy, calibration requirements, feature categories, and the outcome definition problem. The vendor-agnostic/AWS split is clean. The ethical dimension discussion (fairness, feedback loops, self-fulfilling prophecies) is thoughtful and appropriately prominent.

The architecture is sound for the stated scope (batch scoring, strategy-based routing). The recipe correctly emphasizes that calibration matters more than discrimination for this use case, which is a nuance many ML practitioners miss. The "Honest Take" section is one of the strongest in the cookbook: the insight that "the model is less important than the strategy engine" is genuinely valuable.

No CRITICAL findings. Two HIGH findings. The recipe passes.

---

## Security Expert Review

### What's Done Well

BAA requirement is explicitly stated with correct rationale (balance data contains patient names, account numbers, service dates). Encryption at rest is specified for S3 (SSE-KMS), DynamoDB (default), and SageMaker training volumes. TLS in transit is noted. CloudTrail is required with the excellent addition: "you need to demonstrate that scores are used for collection strategy optimization, not care access decisions." VPC requirements are stated with endpoints for S3 and DynamoDB. The "never use real patient financial data in dev" warning is present.

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:Query`, `lambda:InvokeFunction`) are presented as a flat set with no resource scoping or role separation. This pipeline has at least four distinct execution contexts:

1. Glue job role (needs S3 read/write on feature buckets, connectivity to billing system)
2. SageMaker execution role (needs S3 read/write on model/feature buckets, KMS decrypt)
3. Lambda strategy engine role (needs DynamoDB read, but NOT SageMaker or Glue permissions)
4. EventBridge scheduler role (needs to invoke Lambda and start SageMaker transform jobs)

Presenting these as a single permission set implies a single role. The Lambda strategy engine (which routes patients to collection queues) would have permissions to retrain models and modify feature data. This violates least-privilege and creates unnecessary blast radius.

**Suggested fix:** Split into role-specific entries or add a note: "These permissions are distributed across service-specific execution roles. The Lambda strategy engine role should NOT have SageMaker or Glue permissions. The Glue role should NOT have DynamoDB write access. Scope each role to minimum permissions with resource ARNs restricted to specific buckets, tables, and jobs."

### Issue S2: DynamoDB Predictions Table Lacks Retention and Access Control Guidance (HIGH)

**Location:** Step 3 pseudocode (score_open_balances), Prerequisites table

**The problem:** The `balance-predictions` DynamoDB table stores `balance_id`, `patient_id`, `propensity_score`, `top_features` (which includes payment history rates and engagement behavior), and `model_version`. This is PHI: it links patient identifiers to financial behavioral data and payment likelihood scores.

The recipe specifies "encryption at rest (default)" but does not address:

- **Retention policy:** No TTL is specified. Predictions for balances that have been resolved (paid, written off, sent to collections) accumulate indefinitely. Historical propensity scores are sensitive financial behavioral data.
- **Access control granularity:** The strategy engine needs to read all predictions. But who else can query this table? A GSI on propensity score range (mentioned in the "Why These Services" section) enables queries like "show me all patients with low propensity to pay," which is a sensitive population-level query that should be restricted.
- **The `top_features` field** stores derived behavioral data (payment rates, engagement patterns) that could be used for purposes beyond collection strategy (e.g., discriminatory treatment decisions). No guidance on restricting access to this field.

**Suggested fix:** Add guidance on: (1) DynamoDB TTL to expire predictions after balance resolution plus an audit window (e.g., 90 days post-resolution); (2) IAM policy separation between the strategy engine (which needs broad read access) and other consumers (which should be restricted); (3) a note that the propensity score range GSI should be restricted to authorized revenue cycle roles only, not exposed to clinical staff.

### Issue S3: No Discussion of Fair Credit Reporting Act (FCRA) Implications (MEDIUM)

**Location:** The Technology section, "The Credit Scoring Analogy" subsection

**The problem:** The recipe draws an explicit analogy to credit scoring and states "This is essentially credit scoring for healthcare." But it does not address whether propensity-to-pay scores might be considered "consumer reports" under the Fair Credit Reporting Act (FCRA). If a health system uses these scores to make adverse decisions (sending to collections, denying payment plans), FCRA may apply, requiring:

- Adverse action notices when a score leads to unfavorable treatment
- Dispute resolution processes
- Accuracy requirements for the underlying data

The recipe correctly notes that "ability to pay should never determine access to care" but does not address the regulatory framework around using predictive scores for financial decisions about consumers.

**Suggested fix:** Add a paragraph in the Technology section or Honest Take: "Consult legal counsel on whether your propensity scores constitute 'consumer reports' under FCRA. If scores are used to make adverse decisions (escalating to collections, denying payment plan eligibility), FCRA requirements may apply. This is an evolving legal area in healthcare; the safest approach is to use scores for prioritization (who to contact first) rather than exclusion (who to deny services to)."

### Issue S4: Calibration Model Stored Without Versioning or Integrity Check (MEDIUM)

**Location:** Step 2 pseudocode (train_propensity_model), calibration model save

**The problem:** The calibration model is saved to `s3://ml-data/models/propensity-to-pay/calibration/` without versioning or integrity verification. If this artifact is corrupted or tampered with, all subsequent predictions are miscalibrated. Since calibration directly affects financial decisions (which patients get payment plan offers vs. collections), a corrupted calibration model has direct financial impact.

**Suggested fix:** Add a note: "Enable S3 versioning on the models bucket. After saving the calibration model, compute and store a checksum. The scoring pipeline should verify the checksum before applying calibration. This prevents silent corruption from affecting financial routing decisions."

### Issue S5: VPC Endpoint List Is Incomplete (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The VPC section states "SageMaker training and inference in VPC with VPC endpoints for S3 and DynamoDB. Glue jobs in VPC with connectivity to source billing systems." This omits:

- SageMaker API endpoint (for creating training/transform jobs from within VPC)
- CloudWatch Logs endpoint (for Lambda and Glue execution logging)
- KMS endpoint (for decrypting data in S3 and DynamoDB)
- EventBridge endpoint (if the orchestration Lambda runs in VPC)

**Suggested fix:** Expand to: "Additional VPC endpoints required for production: SageMaker API, CloudWatch Logs, and KMS. The S3 gateway endpoint and DynamoDB gateway endpoint handle data-path traffic; interface endpoints are needed for control-plane API calls from within the VPC."

---

## Architecture Expert Review

### What's Done Well

The four-stage pipeline (Feature Store, Model Training, Scoring Service, Strategy Engine) is clean and well-motivated. The emphasis on calibration over discrimination is correct and well-explained. The strategy engine separation (model predicts, business rules decide) is the right pattern. The cost estimates are reasonable. The "Where it struggles" section covers the right failure modes (cold start, financial situation changes, small balances, disputed balances). The feedback loop warning in the Honest Take is excellent.

### Issue A1: No Ground Truth Collection or Model Monitoring Architecture (HIGH)

**Location:** Architecture Diagram, Code section

**The problem:** The recipe's Honest Take correctly warns about feedback loops and calibration drift. The "Production-ready" timeline mentions "monitoring, fairness checks, automated retraining." But the main architecture contains zero infrastructure for:

- Ground truth collection (how do you know which predictions were correct after balances resolve?)
- Calibration monitoring (is the model still well-calibrated after 3 months?)
- AUC/performance tracking over time
- Drift detection triggering retraining

The EventBridge section mentions "triggers retraining on a monthly schedule or when model monitoring detects drift" but no monitoring infrastructure exists in the architecture to detect drift. A builder following this recipe gets a pipeline that trains once, scores nightly, and has no feedback loop. The calibration (which the recipe correctly identifies as critical) silently degrades.

**Suggested fix:** Add a Step 5 to the code walkthrough: "Ground truth and calibration monitoring." A weekly process that joins predictions with actual outcomes (balance paid/not paid after the outcome window), computes rolling AUC and Expected Calibration Error (ECE), publishes to CloudWatch, and triggers retraining when ECE exceeds 0.05 or AUC drops below 0.75. Add this feedback loop to the architecture diagram. This is especially important for this recipe because calibration is emphasized as the critical requirement.

### Issue A2: Outcome Window Mismatch Between Training and Scoring (MEDIUM)

**Location:** Step 2 pseudocode, Step 3 pseudocode, "The Outcome Definition Problem" subsection

**The problem:** The Technology section has an excellent discussion of outcome window choices (30 days, 90 days, 365 days). Step 2 trains on "paid within 90 days." But Step 3 scores all open balances nightly regardless of their age. A balance that's 85 days old and scored with a 90-day model has only 5 days of remaining outcome window. A balance that's 5 days old has 85 days. The model's probability means different things for these two balances.

The strategy engine applies the same thresholds (0.75, 0.40) regardless of how much outcome window remains. A 0.6 score on a 5-day-old balance means something very different from a 0.6 score on an 85-day-old balance.

**Suggested fix:** Add a note in Step 3 or the strategy engine: "Consider the balance's remaining outcome window when interpreting scores. A balance at day 80 of a 90-day model has very little time left; a low score here is more definitive than a low score on a day-5 balance. Some implementations train multiple models for different time horizons (30-day, 60-day, 90-day) and apply the model whose window best matches the decision point. At minimum, the strategy engine should treat scores differently based on balance age."

### Issue A3: Strategy Engine Thresholds Are Static With No A/B Testing Framework (MEDIUM)

**Location:** Step 4 pseudocode (apply_collection_strategy)

**The problem:** The strategy engine uses fixed thresholds (0.75, 0.40) that are described as "business decisions, stored as configuration." This is correct. But the recipe provides no mechanism to validate whether these thresholds are optimal. How do you know that 0.75 is the right cutoff for "will pay without intervention"? How do you know that offering payment plans to the 0.40-0.75 band actually improves recovery vs. standard treatment?

The Honest Take correctly warns about feedback loops ("if you stop contacting low-propensity patients, you'll never know if they would have paid"). It suggests "a small random holdout group." But this holdout is not reflected in the strategy engine code or architecture.

**Suggested fix:** Add a randomization mechanism to the strategy engine pseudocode: "Reserve 5-10% of balances in each score band for random assignment to alternative strategies. This creates the counterfactual data needed to (a) validate that your thresholds are correct and (b) prevent the self-fulfilling prophecy the Honest Take warns about. Log the randomization flag alongside the routing decision for downstream analysis."

### Issue A4: No Error Handling for Missing Patient History (Cold Start) (MEDIUM)

**Location:** Step 1 pseudocode (compute_payment_features)

**The problem:** The feature engineering code computes `pay_rate_full` as `count(paid) / count(past_balances)`. For new patients with zero history, this is 0/0 (division by zero). The "Where it struggles" section acknowledges the cold start problem but the pseudocode doesn't handle it. A builder implementing this literally gets a runtime error on new patients.

**Suggested fix:** Add a guard in the pseudocode: "IF count(past_balances) == 0: use population-average defaults for history features and flag as cold_start = true. The strategy engine can route cold-start patients to a default strategy rather than relying on a prediction with no behavioral signal."

### Issue A5: DynamoDB GSI Design Not Specified (LOW)

**Location:** "Why These Services" section for DynamoDB

**The problem:** The recipe states "A GSI on propensity score range enables the batch queries the strategy engine needs." But DynamoDB GSIs require a partition key and optional sort key. You can't create a GSI on a continuous score range directly. The strategy engine would need a GSI with a partition key like `score_band` (categorical: "high", "medium", "low") or a date-based partition with score as sort key.

**Suggested fix:** Add a brief note: "Create a GSI with `score_date` as partition key and `propensity_score` as sort key. This enables queries like 'all balances scored today with propensity < 0.40.' Alternatively, add a categorical `score_band` attribute computed during write and use it as the GSI partition key."

---

## Networking Expert Review

### What's Done Well

The recipe correctly places SageMaker and Glue in VPC for production. VPC endpoints for S3 and DynamoDB are specified. The architecture is batch-oriented, reducing networking complexity. The Glue connectivity requirement to source billing systems is acknowledged.

### Issue N1: No Guidance on Glue Connectivity to Billing Systems (MEDIUM)

**Location:** Prerequisites, "VPC" row; "Why These Services" for Glue

**The problem:** The recipe states "Glue jobs in VPC with connectivity to source billing systems" but provides no guidance on how to achieve this connectivity. Billing systems in healthcare are typically:

- On-premises (connected via Direct Connect or VPN)
- In a separate VPC (requiring peering or Transit Gateway)
- Behind a firewall with strict ingress rules

The Glue job needs ENIs in a subnet that can reach the billing system. Security groups must allow the Glue ENIs to connect to the billing system's database port. If the billing system is on-premises, the Glue subnet needs a route to the on-premises network via a VPN or Direct Connect gateway.

This is a common deployment blocker for healthcare ML pipelines: the ML infrastructure is in AWS but the source data is behind a hospital firewall.

**Suggested fix:** Add a note in the VPC prerequisites or the Glue section: "Glue jobs require ENIs in a subnet with network connectivity to your billing system. If the billing system is on-premises, this typically requires Direct Connect or site-to-site VPN with appropriate route table entries. If in a separate VPC, use VPC peering or Transit Gateway. Security groups on the Glue ENIs must allow outbound traffic to the billing system's database port. This connectivity is often the longest lead-time item in the implementation."

### Issue N2: SageMaker Batch Transform Network Isolation Not Mentioned (LOW)

**Location:** Step 3 pseudocode, Prerequisites

**The problem:** SageMaker batch transform can be configured with `EnableNetworkIsolation: true`, preventing the inference container from making outbound network calls. For a model scoring financial PHI (patient payment histories, balance amounts), network isolation is a defense-in-depth measure against data exfiltration from a compromised container.

**Suggested fix:** Add to the batch transform configuration: "Enable network isolation (`EnableNetworkIsolation: true`). The XGBoost inference container reads input from S3 and writes predictions to S3 via SageMaker-managed channels; it does not need outbound network access. This prevents unintended data egress from the scoring container."

---

## Voice Reviewer

### What's Done Well

The recipe nails CC's voice throughout. The opening ("Revenue cycle teams in healthcare have a dirty secret") is a strong hook. The credit scoring analogy section is genuinely educational with the "easier because / harder because" structure. Parenthetical asides are natural and well-placed. The Honest Take is excellent: "The model is less important than the strategy engine" is the kind of counterintuitive insight that makes this cookbook valuable. The ethical dimension discussion is handled with appropriate weight without being preachy. The 70/30 vendor split is well-maintained.

### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the recipe. Clean.

### Issue V2: Vendor Balance Is Correct (PASS)

The Technology section (approximately 65% of the recipe's prose) is entirely vendor-agnostic. AWS services appear only in "The AWS Implementation" section. The credit scoring analogy, feature categories, calibration discussion, and outcome definition problem are all cloud-neutral. A reader on GCP or Azure learns the full conceptual framework. The 70/30 target is met.

### Issue V3: Minor Documentation-Voice in "Why These Services" (LOW)

**Location:** "Why These Services" section, DynamoDB paragraph

**The problematic text:** "DynamoDB's flexible query patterns and low-latency reads make it the right fit."

This is a mild case of product-description voice. The rest of the paragraph is fine (explains the specific query patterns needed), but this sentence reads like a feature bullet point rather than an engineer explaining a choice.

**Suggested fix:** Rewrite to: "DynamoDB works here because the access patterns are predictable: look up a single balance by ID, or query a range of scores for the strategy engine's batch routing. You don't need the relational flexibility of RDS, and the read latency matters when the strategy engine is processing thousands of routing decisions."

### Issue V4: One Sentence Slightly Too Long (LOW)

**Location:** The Problem section, paragraph 2

**The text:** "For a mid-size hospital doing $500M in net patient revenue, that's $15-25M per year in balances that were theoretically collectible but never collected."

This is fine stylistically but at 28 words it's at the upper end of CC's typical sentence length. Not a real issue, just noting it's borderline.

**Verdict:** No action needed. This is within acceptable range.

---

## Stage 2: Expert Discussion

**Overlap between Security (S2) and Architecture (A5):** Both touch on the DynamoDB table design. S2 focuses on access control for the score-range GSI; A5 focuses on the GSI's technical design. These are complementary: the GSI needs to be both technically correct (A5) and access-controlled (S2).

**Overlap between Architecture (A1) and the Honest Take:** The recipe's Honest Take warns about calibration drift and feedback loops but the architecture doesn't implement monitoring. A1 is the most impactful finding because the recipe explicitly identifies calibration as the critical requirement, then provides no infrastructure to maintain it.

**Priority resolution:** A1 (model monitoring) is the highest-priority fix because the recipe's own thesis (calibration matters more than discrimination) is undermined by the absence of calibration monitoring. S1 (IAM) and S2 (DynamoDB retention) are standard security hygiene that should be addressed but don't undermine the recipe's core argument.

**FCRA discussion (S3):** This is a genuinely important regulatory consideration that most propensity-to-pay implementations overlook. It's MEDIUM rather than HIGH because the recipe already includes strong ethical framing and the FCRA applicability is legally ambiguous (not settled law for internal scoring). But it should be mentioned.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

No CRITICAL findings. Two HIGH findings (below the 3-HIGH threshold for FAIL). The recipe is architecturally sound, ethically thoughtful, well-written, and provides actionable guidance. The HIGH findings are operational gaps (monitoring, IAM) that would surface in production but do not represent fundamental design flaws. The recipe's core contribution (calibration emphasis, strategy engine separation, ethical framing) is strong.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Architecture Diagram, Code section | No model monitoring, ground truth collection, or calibration tracking. Recipe identifies calibration as critical requirement but provides no infrastructure to maintain it over time. | Add Step 5: ground truth collection, rolling AUC and ECE computation, CloudWatch alarm, retraining trigger. Add feedback loop to architecture diagram. |
| 2 | HIGH | Security | Prerequisites, IAM Permissions row | Permissions listed as flat set implying single role. Lambda strategy engine would have SageMaker and Glue permissions. Violates least-privilege. | Split into role-specific entries or add explicit note about role separation with resource-scoped ARNs. |
| 3 | MEDIUM | Security | Step 3 pseudocode, Prerequisites | DynamoDB predictions table stores PHI with no TTL, no retention policy, no access control discussion for score-range GSI. | Add TTL (expire after balance resolution + 90 days), restrict GSI access to authorized revenue cycle roles, note sensitivity of top_features field. |
| 4 | MEDIUM | Security | Technology section, credit scoring analogy | No discussion of FCRA implications despite explicit credit scoring analogy. Scores used for adverse financial decisions may trigger regulatory requirements. | Add paragraph noting FCRA consultation need. Use scores for prioritization rather than exclusion to minimize regulatory risk. |
| 5 | MEDIUM | Security | Step 2 pseudocode, calibration model save | Calibration model stored without versioning or integrity verification. Corrupted calibration directly affects financial routing decisions. | Enable S3 versioning on models bucket. Store and verify checksum before applying calibration. |
| 6 | MEDIUM | Security | Prerequisites, VPC row | VPC endpoint list incomplete. Missing SageMaker API, CloudWatch Logs, KMS endpoints. | Expand to full endpoint set or note additional endpoints required. |
| 7 | MEDIUM | Architecture | Step 2 and Step 3, outcome window | 90-day model applied uniformly to balances of all ages. A score on a day-85 balance means something different from a score on a day-5 balance. Strategy engine doesn't account for remaining window. | Add note about interpreting scores relative to balance age. Consider multiple time-horizon models or age-adjusted thresholds. |
| 8 | MEDIUM | Architecture | Step 4 pseudocode | Strategy engine thresholds are static with no A/B testing or holdout mechanism. Recipe warns about feedback loops in Honest Take but doesn't implement the suggested holdout in the code. | Add 5-10% randomization to strategy engine for counterfactual measurement. Log randomization flag for analysis. |
| 9 | MEDIUM | Architecture | Step 1 pseudocode | No error handling for new patients with zero history (division by zero on pay_rate_full). Cold start acknowledged in "Where it struggles" but not handled in code. | Add guard: if no history, use population defaults and flag as cold_start. Route cold-start patients to default strategy. |
| 10 | MEDIUM | Networking | Prerequisites, VPC row; Glue section | No guidance on Glue connectivity to billing systems (on-premises, separate VPC). Common deployment blocker in healthcare. | Add note about Direct Connect/VPN requirements, security group rules for Glue ENIs, and that this is often the longest lead-time item. |
| 11 | LOW | Architecture | "Why These Services", DynamoDB | GSI on "propensity score range" not technically specified. DynamoDB GSIs need partition/sort key design. | Add note: use score_date as partition key, propensity_score as sort key, or categorical score_band attribute. |
| 12 | LOW | Voice | "Why These Services", DynamoDB paragraph | "DynamoDB's flexible query patterns and low-latency reads make it the right fit" reads like product-description voice. | Rewrite to explain the specific access patterns that make DynamoDB appropriate for this use case. |
| 13 | LOW | Networking | Step 3, Prerequisites | SageMaker batch transform network isolation not mentioned. Defense-in-depth for PHI-containing scoring jobs. | Add EnableNetworkIsolation: true recommendation with brief rationale. |

---

## Priority Actions Before Publication

1. **Fix A1 (HIGH):** Add calibration monitoring architecture. This is the most impactful gap because the recipe's central thesis (calibration > discrimination) is undermined without monitoring infrastructure. A calibrated model that drifts unchecked becomes an uncalibrated model.

2. **Fix S1 (HIGH):** Split IAM permissions into role-specific guidance. The strategy engine (which makes financial routing decisions about patients) should not have permissions to retrain models or modify feature data.

3. **Fix S2, S3 (MEDIUM security):** Add DynamoDB retention policy and FCRA discussion. These are compliance items that prevent regulatory surprises.

4. **Fix A2, A3, A4 (MEDIUM architecture):** Address outcome window interpretation, add holdout randomization, handle cold start. These prevent subtle correctness issues and implement the feedback loop the Honest Take recommends.

5. **Fix N1 (MEDIUM networking):** Add Glue connectivity guidance. This is the most common deployment blocker for healthcare ML pipelines.

The LOW findings (A5, V3, N2) are polish items that improve quality but don't block a competent builder.

---

*Review complete. Recipe 7.2 is a strong recipe with excellent problem framing, a genuinely educational technology section, and thoughtful ethical discussion. The calibration emphasis and strategy engine separation are the right architectural choices. The gaps are primarily in operational completeness (monitoring, IAM specificity, retention) and a few code-level edge cases (cold start, outcome window). The ethical framing is among the best in the cookbook. A builder with revenue cycle domain knowledge could deploy from this recipe with the HIGH items addressed.*
