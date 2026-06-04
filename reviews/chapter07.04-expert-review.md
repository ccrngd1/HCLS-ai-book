# Expert Review: Recipe 7.4 - ED Visit Prediction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter07.04-ed-visit-prediction.md`

---

## Overall Assessment

This is one of the strongest recipes in the predictive analytics chapter. The problem framing is exceptional: the opening paragraph about the diabetic patient at 2 AM, the COPD patient who missed pulmonary rehab, and the asthmatic kid whose family didn't have a nebulizer immediately grounds the reader in the human cost. The technology section is genuinely educational, covering the prediction problem formulation, what makes ED prediction harder than other risk models, feature engineering families ordered by predictive importance, model architecture choices, calibration, and the general pipeline. All without a single vendor name until the AWS section.

The architecture is well-suited to the batch-scoring use case. The emphasis that "the model is 20% of the work" and the operational integration is the other 80% is the kind of insight that saves organizations from building technically excellent systems that produce no outcomes. The calibration discussion is clinically sound. The fairness and bias discussion in "Why This Isn't Production-Ready" addresses a critical issue that many cookbooks skip.

The recipe correctly identifies the fundamental ceiling on accuracy (partially preventable outcomes trained on all outcomes), the multi-dimensionality problem (clinical vs. behavioral vs. social drivers), and the operational challenge (predictions without intervention pathways are useless).

**Verdict: PASS**

No CRITICAL findings. Two HIGH findings. Four MEDIUM findings. Three LOW findings.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA requirement is explicitly stated with correct rationale ("patient claims and clinical data are PHI")
- Encryption is comprehensive: S3 SSE-KMS for all buckets, DynamoDB encryption at rest, SageMaker KMS for training volumes/model artifacts/batch transform output, Glue security configuration with KMS, all traffic over TLS
- VPC requirements specify private subnets with VPC endpoints for S3, DynamoDB, SageMaker API, and CloudWatch Logs
- "No internet egress for PHI-processing components" is explicitly stated
- VPC Flow Logs are required
- CloudTrail enabled for full HIPAA audit trail across SageMaker, Glue, S3, and DynamoDB
- DynamoDB PITR enabled for audit and incident response
- "Never use real patient data in non-production environments" is present
- CMS Synthetic Medicare Claims (SynPUF) is correctly cited for development data

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTransformJob`, `sagemaker:CreateTrainingJob`, `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `states:StartExecution`, `athena:StartQueryExecution`) are presented as a flat list with no resource scoping or role separation.

This pipeline has at least five distinct execution contexts:

1. Glue ETL role (needs S3 read on source buckets, S3 write on feature store bucket)
2. SageMaker execution role (needs S3 read on feature store, S3 write on model artifacts and scoring output, KMS decrypt/encrypt)
3. Step Functions execution role (needs to invoke Glue, SageMaker Batch Transform, Lambda)
4. Lambda role for post-processing (needs DynamoDB PutItem, S3 read on scoring output)
5. Lambda role for API score lookup (needs DynamoDB GetItem only)

Presenting these as a single permission set implies a single role with combined privileges. A compromised Lambda function for API lookups would also have permissions to start training jobs and write to DynamoDB. This violates least-privilege and increases the blast radius of a credential compromise.

**Suggested fix:** Replace the flat permission list with a note: "These permissions are distributed across service-specific IAM roles. Each role is scoped to its minimum required actions and resource ARNs. The Glue role accesses only source and feature store buckets. The SageMaker role has no DynamoDB access. The API Lambda role has DynamoDB GetItem only on the risk scores table. See the Python companion for role separation patterns."

### Issue S2: SHAP Values and Risk Drivers Stored Without Access Tiering (MEDIUM)

**Location:** Step 5 pseudocode, `top_drivers` field in DynamoDB; Expected Results JSON

**The problem:** The `top_drivers` field in DynamoDB contains explanations like "Medication adherence dropped to 42% for metformin" and "No PCP visit in 7 months." This is stored alongside `patient_id` and served via API Gateway + Lambda to "care management workflow tools."

The recipe states the API serves "care management systems" but doesn't differentiate access levels. A care manager seeing medication adherence detail is appropriate. A patient-facing portal or a less-privileged downstream system should not see the full behavioral profile. The recipe also doesn't mention access controls on the API Gateway itself (IAM authorization, API keys, or Cognito).

**Suggested fix:** Add a sentence after the DynamoDB/API description: "Scope API Gateway access with IAM authorization or Cognito user pools. Not all consumers need the full risk driver detail. Care managers need the complete explanation; patient-facing systems should see only the risk tier and recommended action. Use IAM conditions or separate API endpoints to restrict field-level access based on the caller's identity."

### Issue S3: Outreach Lists Published Without Specifying Encryption for Care Management Queue (MEDIUM)

**Location:** Step 5 pseudocode, `PUBLISH care_manager_list TO care_management_queue`

**The problem:** The pseudocode publishes patient lists (containing patient_id, risk_score, risk_tier, top_drivers, recommended_action) to a "care_management_queue" and "patient_engagement_system." These are PHI payloads leaving the secure data lake perimeter. The recipe doesn't specify what this queue is (SQS, SNS, EventBridge, direct API call) or what encryption/access controls apply to it.

**Suggested fix:** Add: "The outreach delivery mechanism (SQS, SNS, or direct API integration) must use encryption at rest (SSE-KMS for SQS) and enforce IAM policies restricting which principals can receive messages. If using SNS, disable HTTP subscriptions; use only HTTPS or SQS targets within the same VPC. The outreach list contains PHI and must be treated with the same security posture as the source data."

### Issue S4: Model Artifact Integrity Not Addressed (LOW)

**Location:** Step 3 pseudocode, `LOAD_MODEL(model_artifact)`

**The problem:** The pipeline loads a model artifact during batch scoring. There's no mention of verifying model artifact integrity (hash validation, signed model artifacts, or model registry version pinning). If the S3 bucket containing model artifacts were compromised, a tampered model could produce biased scores that route patients to incorrect interventions.

**Suggested fix:** Add a brief note in the Step 3 explanation: "In production, validate the model artifact checksum against the model registry before scoring. SageMaker Model Registry provides versioning and approval workflows that prevent unapproved models from entering the scoring pipeline."

---

## Architecture Expert Review

### What's Done Well

- Batch scoring is correctly chosen over real-time for this use case (weekly features, 30-90 day prediction window, no need for sub-second latency)
- Step Functions for orchestration is the right pattern for a multi-step pipeline with dependencies
- DynamoDB for operational score lookups is appropriate (low-latency reads, TTL via `expires_at`)
- The capacity-based stratification approach (set thresholds to match care management bandwidth) is operationally sound and avoids the common anti-pattern of generating unactionable lists
- SageMaker Batch Transform is correctly chosen over persistent endpoints (cost-effective for weekly batch runs)
- The architecture clearly separates data aggregation, feature engineering, scoring, and delivery

### Issue A1: No Dead Letter Queue or Error Handling in Pipeline (HIGH)

**Location:** Architecture diagram and Step Functions description

**The problem:** The recipe describes Step Functions as providing "built-in retry logic and failure notifications" but doesn't show or discuss what happens when individual steps fail. Specific gaps:

1. If the Glue ETL job fails mid-run, are partial features written to S3? Can the next scoring cycle pick up stale features from a previous run and produce scores based on outdated data?
2. If SageMaker Batch Transform fails for a subset of patients (malformed input rows), are partial results written? Does the pipeline proceed with incomplete scoring?
3. If DynamoDB writes fail (throttling, capacity), are failed patient scores lost? Is there a DLQ for retry?
4. If the outreach list delivery fails, does the pipeline still report success? Do care managers get Monday's list?

In healthcare, silent partial failures are dangerous. A pipeline that scores 90% of patients and silently drops 10% (potentially the highest-risk ones if they have unusual data patterns) is worse than a pipeline that fails loudly and delays the entire list.

**Suggested fix:** Add a paragraph after the architecture diagram or in the Step Functions description: "Each pipeline step should validate output completeness before proceeding. The Glue job should verify output row counts match input patient counts. The Batch Transform step should check for scoring failures and route failed patients to a DLQ for manual review rather than dropping them silently. The DynamoDB write step should use BatchWriteItem with retry logic and alert on unprocessed items. The pipeline should fail loudly (SNS alert to on-call) if any step produces fewer than 95% of expected outputs."

### Issue A2: No Data Versioning or Lineage Tracking (MEDIUM)

**Location:** The Technology section, "The General Architecture Pattern"; AWS Implementation

**The problem:** The recipe mentions "you can always trace a risk score back to the specific features that produced it" but doesn't describe how. There's no mention of:
- Partitioning the feature store by scoring date (S3 prefix = `features/scoring_date=2026-06-01/`)
- Storing which model version produced each score (mentioned in DynamoDB output but not in the pipeline design)
- Retaining historical feature snapshots for model retraining and audit

If a clinician asks "why was this patient flagged high-risk last month?" you need to retrieve the specific feature values and model version from that scoring cycle. The recipe implies this is possible ("full lineage") but doesn't show how it's implemented.

**Suggested fix:** Add a brief note to the Data Aggregation step or the S3 data lake description: "Partition the feature store by scoring_date in S3 (e.g., `s3://features/scoring_date=2026-06-01/`). Retain historical feature snapshots for at least 12 months to support audit queries, model retraining on historical features, and incident investigation. Each DynamoDB record already includes model_version; pair this with the date-partitioned feature store for full score lineage."

### Issue A3: Cost Estimate May Be Low for Production Scale (LOW)

**Location:** Prerequisites table, "Cost Estimate" row; header cost ("~$0.03 per patient per scoring cycle")

**The problem:** The estimate of "$10-40 for a 100K member population" seems reasonable for compute costs alone but omits:
- S3 storage for 24 months of historical data across 5 source systems
- DynamoDB read capacity for API lookups (depends on query volume from care management tools)
- CloudWatch custom metrics and alarms
- Step Functions state transitions
- Data transfer if source systems are in different accounts or regions

The $0.03 per patient per cycle figure is plausible for the Glue + SageMaker compute portion but the total operational cost including storage, monitoring, and API serving is likely 2-3x higher.

**Suggested fix:** Add a qualifier: "Compute cost per scoring cycle is $10-40 for 100K patients. Total operational cost including S3 storage (24-month lookback across 5 sources), DynamoDB provisioned capacity for API serving, CloudWatch monitoring, and Step Functions orchestration is typically $100-300/month at this scale."

### Issue A4: Scoring Frequency vs. Intervention Timing (LOW)

**Location:** The Technology section, "The Prediction Problem" subsection

**The problem:** The recipe says "Most production systems settle on 30 or 60 days, scoring patients weekly or biweekly" and later mentions the Variations section's real-time scoring at care transitions. However, there's a gap: the recipe doesn't address what happens between scoring cycles when a patient has a high-signal event (hospitalization, ED visit, medication discontinuation).

The Variations section covers this but frames it as an extension. In practice, for ED prediction specifically, the between-cycle gap is critical because ED visits often cluster (one visit predicts another within days, not weeks). A patient who had an ED visit Tuesday morning won't be rescored until the next weekly batch run, potentially missing a critical intervention window.

**Suggested fix:** This is adequately covered in Variations and is labeled as an extension, so it's a minor note. Consider adding a single sentence in the main architecture: "Note that weekly scoring creates a blind spot for rapid-onset risk. The Variations section describes event-triggered rescoring for critical transitions."

---

## Networking Expert Review

### What's Done Well

- VPC endpoints specified for S3, DynamoDB, SageMaker API, and CloudWatch Logs
- "No internet egress for PHI-processing components" is explicitly stated
- VPC Flow Logs are required
- All traffic over TLS is specified
- Private subnets for SageMaker and Glue

### Issue N1: VPC Endpoint for Glue Not Explicitly Listed (MEDIUM)

**Location:** Prerequisites table, "VPC" row

**The problem:** The VPC row says "SageMaker and Glue in private subnets with VPC endpoints for S3, DynamoDB, SageMaker API, CloudWatch Logs." Glue jobs in a private subnet need the Glue VPC endpoint (`com.amazonaws.region.glue`) to communicate with the Glue service API for job status updates and data catalog access. Without it, Glue jobs in a private subnet with no internet egress will fail to start or report status.

The listed endpoints are S3, DynamoDB, SageMaker API, and CloudWatch Logs. Missing: Glue, STS (needed for IAM role assumption), and KMS (needed for envelope encryption operations).

**Suggested fix:** Expand the VPC endpoint list: "VPC endpoints for S3 (gateway), DynamoDB (gateway), SageMaker API, SageMaker Runtime, Glue, STS, KMS, and CloudWatch Logs (all interface endpoints)."

### Issue N2: No Mention of Cross-Account Data Access Pattern (LOW)

**Location:** Architecture diagram, Data Sources section

**The problem:** The architecture shows five data sources (Claims, EHR Encounters, Pharmacy Fills, Lab Results, SDOH Indicators) all in "S3 / Data Lake." In many healthcare organizations, these sources live in separate AWS accounts (a claims data warehouse account, an EHR integration account, a pharmacy benefits account). The recipe doesn't address cross-account S3 access patterns, which require bucket policies, cross-account IAM roles, or AWS RAM.

**Suggested fix:** Add a brief note: "If source data resides in separate AWS accounts (common in large health systems), use cross-account IAM roles with external IDs for the Glue job to assume. Alternatively, replicate source data into the analytics account using S3 Replication with KMS re-encryption. Avoid bucket policies that grant broad cross-account access."

### Issue N3: API Gateway Endpoint Type Not Specified (LOW)

**Location:** Architecture diagram, "API Gateway + Lambda / Score Lookup API"

**The problem:** The recipe doesn't specify whether this is a Regional, Edge-optimized, or Private API Gateway endpoint. For a healthcare internal system serving care management tools, this should almost certainly be a Private API Gateway (accessible only within the VPC or via VPC endpoint from peered networks). A Regional or Edge-optimized endpoint would expose the risk score API to the public internet (even with authentication).

**Suggested fix:** Add: "Deploy API Gateway as a Private endpoint accessible only within the VPC. Care management systems in peered VPCs or connected via Direct Connect access the API through an interface VPC endpoint for API Gateway. This ensures risk score data never traverses the public internet."

---

## Voice Reviewer

### What's Done Well

- The Problem section is outstanding. It nails the engineer-explaining-something-cool voice with real clinical scenarios. The opening about the 2 AM diabetic, the COPD patient, and the asthmatic kid is vivid and builds empathy without being maudlin.
- The parenthetical asides are well-calibrated: "(ok, this is a gross oversimplification, but stay with me)" energy without actually using that phrase
- The Technology section is fully vendor-agnostic. No AWS service names appear until "The AWS Implementation" section.
- The Honest Take delivers genuinely useful hard-won insights, particularly "the model is 20% of the work" and the social determinants paragraph
- Self-deprecating expertise shows throughout: acknowledging the accuracy ceiling, the "preventable" question that never goes away
- The recipe maintains momentum through accumulation of short-to-medium sentences

### Issue V1: No Em Dashes Found

Confirmed: zero em dashes in the recipe. Uses colons, semicolons, periods, commas, and parentheses appropriately throughout.

### Issue V2: Vendor Balance Assessment

The recipe is approximately 72% vendor-agnostic (Problem, Technology, General Architecture, Honest Take, Variations) and 28% AWS-specific (Why These Services, Architecture Diagram, Prerequisites, Ingredients, Code walkthrough). This is within the 70/30 target.

### Issue V3: Minor Doc-Voice Creep in Prerequisites Table (LOW)

**Location:** Prerequisites table headers and AWS Implementation section opener

**The problem:** The phrase "Why These Services" as a section header is slightly more formal/documentary than the rest of the voice. The rest of the recipe uses "Here's what I've learned" and "Skip this step and you'll..." energy. The "Why These Services" header reads more like a formal architecture document.

This is very minor. The content under that header maintains the correct voice. The header itself is specified in the RECIPE-GUIDE.md structure, so it may be intentional.

**Suggested fix:** No change required. The header follows the recipe template. The content beneath it maintains voice.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

**Security (S1) and Architecture (A1) overlap:** Both experts flag pipeline failure modes. Security is concerned about permissions scope in failure scenarios (a compromised step with overly broad permissions). Architecture is concerned about silent partial failures producing incomplete scoring. These are complementary concerns that reinforce each other. Both are HIGH severity independently.

**Security (S2) and Networking (N3) overlap:** S2 flags that risk driver data is served without access tiering. N3 flags that the API endpoint type isn't specified (could be public). Together these create a scenario where detailed patient behavioral profiles are served through a potentially public API with no field-level access control. The combination is worse than either alone, but neither individually rises to CRITICAL because the recipe does specify authentication in the architecture (API Gateway + Lambda) and encryption (TLS).

**Resolution:** The two HIGH findings stand independently. Neither rises to CRITICAL because the recipe does address BAA, encryption, VPC isolation, and audit logging. The gaps are about depth (role separation, failure handling) rather than fundamental security omissions.

### Priority Order

1. S1 (IAM least-privilege) and A1 (error handling/DLQ) are the most impactful fixes: they address operational safety and security posture simultaneously.
2. S2 + N3 (access tiering + private API) are the next priority: they close a potential PHI exposure path.
3. The remaining MEDIUM and LOW findings are improvements that strengthen the recipe without addressing fundamental gaps.

---

## Stage 3: Synthesized Findings

### Verdict: **PASS**

The recipe is architecturally sound, clinically accurate, well-voiced, and comprehensive. The two HIGH findings address depth issues (least-privilege role separation and pipeline error handling) rather than fundamental security omissions or architectural flaws. The recipe correctly handles BAA, encryption, VPC isolation, CloudTrail auditing, and the critical operational challenge of turning predictions into interventions. The clinical framing is accurate (AUROC ranges, feature importance hierarchy, calibration requirements, fairness concerns). The Honest Take provides genuine value.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding |
|---|----------|--------|----------|---------|
| 1 | HIGH | Security | Prerequisites, IAM Permissions row | IAM permissions presented as flat list without role separation or resource scoping. Split into service-specific roles with minimum-privilege resource ARNs. |
| 2 | HIGH | Architecture | Architecture diagram / Step Functions | No error handling, DLQ, or output validation between pipeline steps. Silent partial failures could produce incomplete scoring, dropping high-risk patients. Add row count validation and alerting on partial failures. |
| 3 | MEDIUM | Security | Step 5 pseudocode, DynamoDB schema | SHAP-derived risk drivers (detailed behavioral data) stored without access tiering. Different API consumers need different field visibility. Add IAM-based field-level access or separate endpoints. |
| 4 | MEDIUM | Security | Step 5 pseudocode, outreach list delivery | Outreach list published to unspecified "care_management_queue" without encryption or access control guidance. Specify SQS SSE-KMS and IAM constraints. |
| 5 | MEDIUM | Networking | Prerequisites, VPC row | VPC endpoint list incomplete. Missing Glue, STS, and KMS endpoints required for private-subnet operation without internet egress. |
| 6 | MEDIUM | Architecture | Technology section, Data Lake description | No data versioning or lineage tracking mechanism described despite claiming "full lineage." Add date-partitioned feature store and historical snapshot retention guidance. |
| 7 | LOW | Security | Step 3 pseudocode, LOAD_MODEL | No model artifact integrity verification. Add checksum validation against model registry before scoring. |
| 8 | LOW | Architecture | Prerequisites, Cost Estimate | Cost estimate covers compute only. Total operational cost (storage, monitoring, API serving) is likely 2-3x higher. Add qualifier. |
| 9 | LOW | Networking | Architecture diagram, API Gateway | API Gateway endpoint type not specified. Should be Private for healthcare internal use. PHI should not traverse public internet. |
| 10 | LOW | Networking | Architecture diagram, Data Sources | No cross-account data access pattern for multi-account health systems. Add brief guidance on cross-account IAM roles or S3 Replication. |
| 11 | LOW | Voice | Prerequisites table header | Very minor: "Why These Services" header is slightly more formal than the recipe voice, but follows the RECIPE-GUIDE template. No change required. |

---

### Summary

Strong recipe. The clinical framing, technology teaching, and operational honesty are all excellent. The two HIGH findings are common patterns in cookbook-style content (IAM oversimplification and missing error handling guidance) and are straightforward to address without restructuring. The MEDIUM findings add defense-in-depth guidance appropriate for a HIPAA-regulated environment. No fundamental architectural, clinical, or security issues.
