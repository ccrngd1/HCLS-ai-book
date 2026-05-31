# Expert Review: Recipe 7.6 - Rising Risk Identification

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Review date:** 2026-05-31
**Complexity rating:** Appropriate (Medium-Complex / Growth phase)
**Overall assessment:** PASS

---

## Executive Summary

Recipe 7.6 is an excellent, deeply educational recipe that tackles one of the most impactful problems in population health management. The clinical framing is accurate and compelling, the mathematical treatment of "rising risk" definitions is thorough and appropriately nuanced, and the architecture is well-suited for the batch-oriented nature of the workload. The "Honest Take" section is outstanding, particularly the insight about regression to the mean as a confounder and the practical advice to work backward from intervention capacity.

The recipe correctly identifies the fundamental challenges (irregular observation intervals, informative missingness, confounding events, score versioning) and provides actionable guidance for each. The feature engineering section is clinically sound, and the multi-window trajectory approach reflects real-world best practices in population health analytics.

No CRITICAL findings. Two HIGH findings related to missing access controls on the patient risk state store and incomplete model bias/fairness discussion for a population-level scoring system. These are addressable without restructuring.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### S1 - HIGH: DynamoDB Patient Risk State Table Lacks Access Control Discussion

**Location:** Step 5 pseudocode, "write to database table 'patient-risk-state'"; Architecture Diagram, DynamoDB box; Ingredients table

**Issue:** The DynamoDB table stores patient_id, risk_tier, severity, current_score, trajectory_slope, signals, and flagged_date. This is PHI (patient identifier combined with health-related risk information). The recipe mentions encryption at rest in the Prerequisites table ("DynamoDB: encryption at rest (default)") but does not discuss:

1. Fine-grained access control: who can read this table? The "Care Management Platform API Integration" arrow in the diagram implies external system access, but there's no discussion of how to restrict which care managers can see which patients (e.g., by attributed panel, by program, by geography).
2. Item-level access patterns: DynamoDB doesn't natively support row-level security. If multiple care management programs share this table, a BH care manager could query any patient's risk state, not just BH-flagged patients.
3. API Gateway or AppSync layer: the diagram shows a direct arrow from DynamoDB to "Care Management Platform." In practice, you need an API layer that enforces authorization (which user can see which patient's data) before returning risk state.

**Why it matters:** HIPAA's minimum necessary standard requires that care managers access only the patients in their panel. A direct DynamoDB read without an authorization layer violates this principle and would be flagged in a compliance audit.

**Suggested fix:** Add a paragraph after the DynamoDB description in "Why These Services": "Access to the patient risk state table should be mediated through an API layer (API Gateway + Lambda, or AppSync) that enforces panel-level authorization. Care managers should only retrieve risk state for patients attributed to their program. Implement this as a Lambda authorizer that validates the requesting user's panel assignment against the patient's attributed care team before returning data. Direct DynamoDB access should be restricted to the scoring pipeline's IAM role and the API layer's execution role only."

---

#### S2 - MEDIUM: EventBridge Alert Events Contain PHI Without Subscriber Controls

**Location:** Step 5 pseudocode, "emit event" block; SNS Care Manager Notifications in architecture diagram

**Issue:** The emitted event includes patient_id, severity, program, signals, slope_6mo, and a human-readable message containing the patient's risk score, percentile, and trajectory details. This event flows to EventBridge and then to SNS for care manager notifications. The recipe doesn't discuss:

1. Who can subscribe to the SNS topic (email subscribers would receive PHI in plaintext email)
2. Whether the EventBridge event bus should be encrypted (it is by default with AWS-managed keys, but CMK encryption is recommended for PHI)
3. Whether the message content should be minimized (send a notification with patient_id and a link to the secure dashboard, rather than embedding clinical trajectory details in the message body)

**Suggested fix:** Add after the EventBridge/SNS description: "SNS notifications containing patient identifiers and risk trajectory data constitute PHI. Restrict topic subscriptions to HIPAA-compliant endpoints (SQS queues, Lambda functions, or HTTPS endpoints under your BAA). Avoid email or SMS subscriptions that embed clinical details. For care manager notifications, send a minimal alert ('3 new rising-risk patients require review in your panel') with a link to the secure care management dashboard rather than embedding trajectory details in the notification body."

---

#### S3 - MEDIUM: IAM Permissions Listed Without Least-Privilege Guidance

**Location:** Prerequisites table, "IAM Permissions" row

**Issue:** The permissions list includes `sagemaker:CreateTransformJob`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:GetItem`, `events:PutEvents`, `sns:Publish`. These are listed as bare actions without resource scoping or role separation guidance. The pipeline has distinct phases (feature assembly, scoring, trajectory computation, detection/routing) that should use separate IAM roles with minimal permissions for each phase.

**Suggested fix:** Add a note: "Each pipeline phase should use a dedicated IAM role scoped to specific resources. The Glue feature assembly role needs S3 read on source buckets and write on the feature store bucket only. The SageMaker batch transform role needs S3 read on features and write on score history only. The Lambda detection function needs DynamoDB write on the risk state table and events:PutEvents on the specific event bus. Never use a single role with all permissions for the entire pipeline."

---

#### S4 - LOW: No Mention of Score History Retention and Right-to-Deletion

**Location:** Step 2 pseudocode, "Append (not overwrite) to the longitudinal score history in S3"

**Issue:** The recipe correctly emphasizes appending scores and never overwriting. However, it doesn't address data retention policies or patient right-to-deletion requests. Under some state privacy laws (and potentially under HIPAA's amendment provisions), patients may request deletion of their data. A longitudinal score history in S3 Parquet files (partitioned by date) makes individual patient deletion operationally complex (you'd need to rewrite entire Parquet partitions to remove one patient's records).

**Suggested fix:** Add a brief note in the "Why Isn't This Production-Ready" section or as a footnote: "Patient data deletion requests require rewriting Parquet partitions to remove individual records. Consider maintaining a deletion registry and filtering deleted patients at query time rather than physically removing records from historical partitions. Implement S3 Lifecycle policies to automatically transition older score history to Glacier after the active analysis window (e.g., 24 months in Standard, then Glacier for long-term retention)."

---

#### S5 - LOW: CloudTrail Entry Could Be More Specific About Data Events

**Location:** Prerequisites table, "CloudTrail" row

**Issue:** "Enabled: log all SageMaker, Glue, and DynamoDB API calls for HIPAA audit trail." This is correct at a high level, but CloudTrail management events (enabled by default) don't capture DynamoDB item-level access. Data events for DynamoDB and S3 must be explicitly enabled and incur additional cost. The recipe should clarify this distinction.

**Suggested fix:** Append: "Enable CloudTrail data events for the DynamoDB risk state table and S3 score history bucket. Management events alone don't capture item-level reads/writes needed for patient-level audit trails."

---

### Architecture Expert Review

#### A1 - HIGH: No Discussion of Model Fairness or Bias in Population-Level Scoring

**Location:** The Technology section (all subsections); Detection thresholds in Step 4

**Issue:** The recipe scores an entire managed population and flags patients for intervention based on trajectory thresholds. This is a population health equity concern that the recipe doesn't address:

1. **Differential data density:** Patients with more frequent visits generate more data points, producing more reliable trajectory estimates. Patients who are underserved (rural, uninsured, minority populations) tend to have sparser visit histories, meaning they're more likely to fall into the "INSUFFICIENT_HISTORY" bucket and never get evaluated. The recipe acknowledges this technically ("patients with fewer than 3 scoring cycles cannot be evaluated") but doesn't frame it as an equity issue.

2. **Threshold equity:** The detection thresholds are applied uniformly across the population. But if the underlying risk model has known disparities (e.g., systematically under-predicting risk for Black patients, as documented in the Obermeyer et al. 2019 Science paper on algorithmic bias in healthcare), then the trajectory analysis inherits and potentially amplifies those disparities. A patient whose risk is under-predicted will show a flatter trajectory even if they're genuinely deteriorating.

3. **Intervention allocation fairness:** The prioritization step (sort by severity and slope) doesn't consider whether the resulting intervention list is equitable across demographic groups. If your model systematically produces steeper slopes for certain populations (due to data density or model bias), those populations will be over-represented in the intervention queue while others are under-served.

**Why it matters:** CMS and state regulators are increasingly scrutinizing algorithmic tools used in coverage and care management decisions for disparate impact. A rising risk system that systematically under-identifies deterioration in underserved populations could create regulatory and legal exposure.

**Suggested fix:** Add a subsection in "The Technology" section (after "Regression to the mean") titled "Equity and Bias Considerations": "Rising risk detection inherits any biases present in the underlying risk model. If the base model systematically under-predicts risk for certain demographic groups (a well-documented phenomenon; see Obermeyer et al., Science 2019), trajectory analysis will show artificially flat slopes for those groups, causing them to be under-flagged. Mitigation strategies include: (1) auditing flag rates by demographic group and investigating disparities, (2) using group-specific thresholds calibrated to equalize flag rates across populations with similar true deterioration rates, (3) separately flagging patients with sparse data for proactive outreach regardless of trajectory, and (4) including the 'insufficient history' population in equity reporting rather than silently excluding them."

---

#### A2 - MEDIUM: Lambda for Detection and Prioritization May Hit Timeout at Scale

**Location:** Architecture diagram, "Lambda: Rising Risk Detection & Prioritization" box; Performance benchmarks table ("Detection + routing (Lambda): 2-5 minutes")

**Issue:** The recipe shows a Lambda function handling rising risk detection and prioritization for the full population's trajectory results. The performance benchmark says "2-5 minutes." AWS Lambda has a maximum timeout of 15 minutes, so this is within limits. However, the detection logic iterates over all patients with computed trajectories (461K in the sample output), applies threshold rules, collects signals, and sorts results. For 461K patients, this is feasible in Lambda if the trajectory results are loaded from S3 as a single file, but:

1. Loading a 461K-row dataset into Lambda memory requires careful memory allocation (likely needs 1-2 GB depending on the number of trajectory fields)
2. If the trajectory results are stored as multiple Parquet files (partitioned), the Lambda needs to read and merge them
3. The 2-5 minute estimate seems optimistic for a Lambda cold start + S3 read + 461K row iteration + DynamoDB writes for 3,891 flagged patients + EventBridge puts for 847 newly flagged patients

This isn't wrong, but it's a potential scaling concern that should be acknowledged.

**Suggested fix:** Add a note: "For populations exceeding 500K, consider splitting the detection step: use a Glue job (or Glue Python Shell) for the threshold application and signal collection (which is a data transformation), and use Lambda only for the routing and notification step (which handles only the flagged subset, typically <1% of the population). This avoids Lambda memory and timeout constraints for the bulk filtering operation."

---

#### A3 - MEDIUM: No Monitoring or Alerting for Pipeline Failures

**Location:** Architecture diagram (no monitoring components shown); Prerequisites table

**Issue:** The pipeline is a multi-step batch process (Glue -> SageMaker -> Glue -> Lambda) orchestrated by EventBridge. The recipe doesn't discuss what happens when a step fails:

1. What if the Glue feature assembly job fails (bad source data, schema change)?
2. What if SageMaker batch transform fails (model endpoint deleted, instance unavailable)?
3. What if the trajectory computation Glue job fails (OOM on a large population)?
4. What if the Lambda detection function fails (DynamoDB throttling)?

A monthly scoring pipeline that fails silently means an entire month's worth of rising-risk patients go unidentified. This is a patient safety concern.

**Suggested fix:** Add to the architecture section: "Implement Step Functions or an equivalent orchestrator to coordinate the pipeline steps with error handling. Each step should emit success/failure metrics to CloudWatch. Configure CloudWatch Alarms for: (1) pipeline not completing within expected window (e.g., 4 hours), (2) any step failure, (3) anomalous output (flagged count deviating >50% from prior cycle, which suggests a data or model issue). Alert the operations team via PagerDuty/SNS if the pipeline fails to complete, as a missed scoring cycle means rising-risk patients go unidentified for an additional month."

---

#### A4 - MEDIUM: Score Versioning Problem Acknowledged But Solution Underspecified

**Location:** "Why This Isn't Production-Ready" section, first paragraph on score versioning

**Issue:** The recipe correctly identifies that model retraining invalidates historical score comparisons. It mentions two solutions: (a) re-score full history with new model, or (b) maintain version-specific percentile baselines. But it doesn't recommend one over the other or discuss the practical implications:

- Option (a) requires storing all historical feature matrices (not just scores), which could be terabytes for a large population over multiple years
- Option (b) means your trajectory computation must be version-aware, only comparing scores produced by the same model version

The recipe's pseudocode in Step 2 stores `model_version` with each score (good), but the trajectory computation in Step 3 doesn't filter by model_version when computing slopes. This means a model version change would produce a spurious spike or drop in the trajectory, potentially triggering false flags.

**Suggested fix:** Add to Step 3 pseudocode a comment: "// IMPORTANT: Only compute slopes using scores from the same model version. // If model_version changed during the history window, either: // (a) re-score historical periods with the current model, or // (b) compute slope only from scores produced by the current model version, // accepting a shorter effective history window after each model update." Also add a brief recommendation in the "Why This Isn't Production-Ready" section: "For most organizations, option (b) is more practical: after a model retrain, accept a reduced trajectory window until enough new-version scores accumulate. Design your minimum data point threshold (currently 3) to account for this reset."

---

#### A5 - LOW: Cost Estimate Could Include Data Transfer Costs

**Location:** Prerequisites table, "Cost Estimate" row

**Issue:** The cost estimate covers Glue DPU-hours, SageMaker batch transform, S3 storage, and DynamoDB writes. It doesn't mention data transfer costs for pulling source data (EHR extracts, claims feeds) into S3, or cross-AZ data transfer within the VPC. For most organizations, the source data ingestion cost (especially if pulling from on-premises systems via Direct Connect or VPN) is a significant portion of the total pipeline cost.

**Suggested fix:** Add a note: "Cost estimate excludes data ingestion from source systems (EHR, claims). If source data is on-premises, factor in Direct Connect or VPN data transfer costs. For a 500K-member population with 18-24 months of history, initial data load may be 50-200 GB; incremental monthly loads are typically 5-20 GB."

---

### Networking Expert Review

#### N1 - MEDIUM: VPC Endpoint List Is Incomplete for the Full Architecture

**Location:** Prerequisites table, "VPC" row

**Issue:** The VPC section states: "Production: Glue jobs and SageMaker in VPC with VPC endpoints for S3, DynamoDB, and CloudWatch Logs." The architecture also uses Lambda (for detection/routing), EventBridge (for event emission), and SNS (for notifications). If the Lambda function runs in the VPC (which it should, since it accesses DynamoDB with PHI), it also needs VPC endpoints for:

- `com.amazonaws.{region}.events` (EventBridge, for PutEvents calls)
- `com.amazonaws.{region}.sns` (for Publish calls)
- `com.amazonaws.{region}.lambda` (if Step Functions invokes Lambda within VPC)
- `com.amazonaws.{region}.sagemaker.runtime` (if any component calls SageMaker from within VPC)

Without these, the Lambda would need a NAT Gateway for internet-routed API calls, adding cost and a potential single point of failure.

**Suggested fix:** Expand the VPC prerequisites: "VPC endpoints required: S3 (gateway), DynamoDB (gateway), CloudWatch Logs (interface), EventBridge (interface), SNS (interface), SageMaker API (interface, for batch transform job submission). If Lambda detection function runs in VPC, ensure all AWS service calls from Lambda have corresponding VPC endpoints to avoid NAT Gateway dependency."

---

#### N2 - LOW: No Discussion of Source Data Ingestion Network Path

**Location:** Architecture diagram (starts at "EventBridge Scheduler" but doesn't show data ingestion)

**Issue:** The architecture diagram begins with the EventBridge trigger and assumes features are already available. But the Glue feature assembly job needs to read from source systems (EHR extracts, claims feeds, ADT feeds). The network path for this ingestion is not discussed. In most healthcare organizations, these source systems are on-premises or in a separate VPC, requiring:

- AWS Direct Connect or Site-to-Site VPN for on-premises sources
- VPC peering or Transit Gateway for cross-VPC sources
- Appropriate security group rules to allow Glue ENIs to reach source databases

**Suggested fix:** Add a brief note in Prerequisites or the architecture section: "Source data ingestion (EHR, claims, ADT) is assumed to be pre-staged in S3 via a separate ETL pipeline. If source systems are on-premises, use Direct Connect or Site-to-Site VPN with Glue connections configured for the appropriate VPC and subnet. If sources are in a separate VPC, use VPC peering or Transit Gateway with security groups allowing Glue job ENIs to reach source endpoints."

---

#### N3 - LOW: QuickSight Access to S3 Score History Should Use VPC Connection

**Location:** Architecture diagram, "QuickSight: Population Dashboards" connected to "S3: Score History"

**Issue:** QuickSight accessing S3 directly is fine from a functionality standpoint (QuickSight uses IAM roles for S3 access). However, if the S3 bucket policy restricts access to specific VPC endpoints (a common security pattern for PHI buckets), QuickSight needs to be configured with a VPC connection to access the data through the VPC endpoint rather than over the public S3 endpoint.

**Suggested fix:** Add: "If S3 bucket policies restrict access to VPC endpoints (recommended for PHI), configure QuickSight with a VPC connection to access score history data through the S3 gateway endpoint."

---

### Voice Reviewer

#### V1 - PASS: No Em Dashes Found

Thorough scan of the full recipe confirms zero em dashes. The recipe uses colons, semicolons, parentheses, commas, and periods appropriately throughout.

---

#### V2 - PASS: Vendor Balance Is Excellent

The recipe maintains a strong 70/30 split. The Problem, Technology (all subsections including mathematical definitions, longitudinal modeling challenges, feature engineering, model architecture options, and intervention timing), and General Architecture Pattern sections are entirely vendor-agnostic. AWS services appear only starting at "The AWS Implementation." A reader on any cloud would gain substantial value from the first ~60% of the recipe.

---

#### V3 - PASS: Tone Is Consistent and Engaging

The voice throughout matches the style guide perfectly. The opening hook ("Every health system has a list of high-risk patients... The problem is not identifying who is already high-risk. The problem is identifying who is *becoming* high-risk.") is compelling. The mathematical definitions section maintains accessibility while being rigorous. The "Honest Take" is genuinely insightful and reflects real operational experience. Phrases like "this is where it gets interesting" and "the ROI math is compelling, but only if..." demonstrate the engineer-explaining-something-cool energy the style guide calls for.

---

#### V4 - LOW: One Sentence Slightly Approaches Doc-Voice

**Location:** "Why These Services" section, QuickSight paragraph

**Issue:** "QuickSight connects directly to the S3-based score history for population analytics without requiring a separate data warehouse." This reads slightly like a feature description from a product page. The rest of the "Why These Services" section is conversational and well-motivated.

**Suggested fix:** Minor. Could be: "QuickSight can query the S3 score history directly, so you don't need to stand up a separate data warehouse just for leadership dashboards." But this is cosmetic; the current phrasing is clear and functional.

---

## Stage 2: Expert Discussion

**Security vs. Architecture overlap on fairness:** The security concern about access controls (S1) and the architecture concern about fairness (A1) interact. If the system systematically under-identifies rising risk in underserved populations (A1), and the access control layer restricts visibility to attributed panels (S1), then the equity gap becomes invisible to individual care managers. Only population-level reporting would reveal the disparity. Resolution: the fairness monitoring recommended in A1 should be accessible to quality/equity leadership, not just individual care managers. This doesn't conflict with S1's panel-level access controls; it's a separate reporting layer.

**Architecture vs. Security on score versioning:** The score versioning concern (A4) has a security dimension. If you re-score historical data with a new model (option a), you're processing PHI through a new model version that may not have completed the same validation/approval process as the original. Some organizations require model governance approval before any model touches PHI. Resolution: model governance should approve the retrained model before it's used for either prospective scoring or historical re-scoring. This is a process concern, not an architectural one.

**Networking vs. Architecture on pipeline orchestration:** The missing monitoring concern (A3) and the VPC endpoint concern (N1) interact. If you add Step Functions as an orchestrator (as A3 suggests), you need an additional VPC endpoint for `com.amazonaws.{region}.states`. Resolution: include Step Functions endpoint in the expanded VPC endpoint list.

**Priority resolution:** A1 (fairness/bias) is the highest-priority finding because it represents a systemic equity concern that could affect patient outcomes and regulatory standing. S1 (DynamoDB access controls) is the highest-priority security finding because it's a concrete HIPAA minimum-necessary violation in the current architecture.

---

## Stage 3: Synthesized Findings

### Verdict: PASS

The recipe is exceptionally well-written, clinically accurate, and architecturally sound for its stated purpose. The mathematical treatment of trajectory definitions is a standout strength that elevates this beyond a typical cookbook recipe into genuinely educational content. The two HIGH findings (access control gap and missing fairness discussion) are important additions for production readiness and responsible deployment, but don't represent fundamental flaws in the approach. The recipe's own "Why This Isn't Production-Ready" section demonstrates appropriate self-awareness about limitations, though it should be extended to cover the equity dimension.

### Prioritized Findings

| # | Severity | Expert | Location | Issue | Fix |
|---|----------|--------|----------|-------|-----|
| S1 | HIGH | Security | Step 5, DynamoDB risk state; Architecture diagram | DynamoDB patient risk state accessible without authorization layer; no panel-level access control | Add API layer with panel-level authorization; restrict direct DynamoDB access to pipeline roles only |
| A1 | HIGH | Architecture | Technology section; Step 4 thresholds | No discussion of model fairness, differential data density, or equity in population-level scoring | Add "Equity and Bias Considerations" subsection addressing data density disparities, inherited model bias, and intervention allocation fairness |
| S2 | MEDIUM | Security | Step 5, EventBridge/SNS events | Alert events contain PHI without subscriber endpoint controls | Add guidance on restricting SNS subscriptions; minimize message content to IDs + dashboard links |
| S3 | MEDIUM | Security | Prerequisites, IAM Permissions | Permissions listed without resource scoping or role separation | Add note about per-phase IAM roles scoped to specific resource ARNs |
| A2 | MEDIUM | Architecture | Architecture diagram, Lambda box | Lambda detection function may hit memory/timeout limits at >500K population | Recommend Glue for bulk filtering, Lambda only for routing the flagged subset |
| A3 | MEDIUM | Architecture | Architecture diagram (no monitoring) | No pipeline failure monitoring or alerting; silent failure means missed scoring cycles | Add Step Functions orchestration, CloudWatch Alarms, and operational alerting for pipeline failures |
| A4 | MEDIUM | Architecture | Step 3 pseudocode; "Why This Isn't Production-Ready" | Trajectory computation doesn't filter by model_version; version changes produce spurious flags | Add model_version filter to trajectory computation; recommend version-aware slope calculation |
| N1 | MEDIUM | Networking | Prerequisites, VPC | VPC endpoint list incomplete (missing EventBridge, SNS, SageMaker endpoints) | Expand list to include all services accessed from VPC-resident components |
| S4 | LOW | Security | Step 2, S3 score history | No discussion of data retention policy or right-to-deletion for longitudinal score history | Add note about deletion registry, Parquet rewrite complexity, and S3 Lifecycle policies |
| S5 | LOW | Security | Prerequisites, CloudTrail | CloudTrail guidance doesn't distinguish management vs. data events | Clarify that DynamoDB and S3 data events must be explicitly enabled for patient-level auditing |
| A5 | LOW | Architecture | Prerequisites, Cost Estimate | Cost estimate excludes source data ingestion and transfer costs | Add note about Direct Connect/VPN costs for on-premises source data |
| N2 | LOW | Networking | Architecture diagram, data ingestion | Source data ingestion network path not discussed | Add note about Direct Connect/VPN/VPC peering for source system connectivity |
| N3 | LOW | Networking | Architecture diagram, QuickSight | QuickSight S3 access may need VPC connection if bucket policy restricts to VPC endpoints | Add note about QuickSight VPC connection for restricted S3 buckets |
| V4 | LOW | Voice | Why These Services, QuickSight paragraph | One sentence slightly approaches documentation voice | Optional rephrase; not blocking |

### What's Done Well

- **Mathematical rigor with accessibility.** The "Defining Rising Risk Mathematically" section presents five distinct definitions with clear tradeoffs, making the concept accessible to non-technical readers while giving engineers the precision they need. This is the best section in the recipe.
- **Longitudinal modeling challenges.** The discussion of irregular observation intervals, informative missingness, confounding events, and regression to the mean is clinically accurate and reflects genuine operational experience. These are exactly the challenges that trip up teams building this for the first time.
- **Feature engineering specificity.** The trajectory features (score deltas, utilization acceleration, clinical marker trends, care engagement changes, new diagnosis velocity) are clinically appropriate and well-motivated. The multi-window approach is the right design choice.
- **Detection threshold transparency.** Exposing the thresholds as named constants with explanatory comments, and requiring 2+ converging signals to reduce false positives, demonstrates production-grade thinking.
- **Honest Take section.** The regression-to-the-mean discussion and the "work backward from intervention capacity" advice are genuinely valuable operational insights that most cookbook-style content misses entirely.
- **Intervention timing framing.** Treating intervention timing as an optimization problem (lead time, trajectory confidence, capacity constraints) elevates this beyond simple threshold-based alerting.
- **Appropriate scope.** The recipe doesn't over-promise. The 30-50% false positive rate acknowledgment and the "6-12 month blind spot for new enrollees" are honest and useful for expectation-setting.

---

*Review complete. The recipe is publication-ready after addressing the HIGH findings. MEDIUM findings strengthen production readiness. LOW findings are polish items that don't block publication.*
