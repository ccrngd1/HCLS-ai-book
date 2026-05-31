# Expert Review: Recipe 7.3 - Patient Churn / Disenrollment Prediction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter07.03-patient-churn-disenrollment-prediction.md`

---

## Overall Assessment

This is an excellent recipe. The problem framing is vivid and grounded in real health plan economics ($12,000-$15,000 per MA member, $25,000-$40,000 per commercial family). The technology section is genuinely educational: it covers the definition problem, feature engineering categories, model selection rationale, calibration importance, and the cold start problem, all without a single vendor name. The architecture is clean and appropriate for the stated scale. The Honest Take delivers real insights ("the model is the easy part," "calibration is non-negotiable but often skipped," "the intervention matters more than the model").

The recipe correctly identifies that churn prediction is primarily a feature engineering problem, not a modeling problem. The emphasis on calibration over raw accuracy is the right call for this use case. The ethical dimension (models encoding discrimination via zip code proxies) is handled with appropriate weight.

No CRITICAL findings. One HIGH finding. The recipe passes.

---

## Security Expert Review

### What's Done Well

BAA requirement is explicitly stated with correct rationale (member behavioral data, claims data, grievance records are PHI). Encryption is specified comprehensively: S3 SSE-KMS, DynamoDB encryption at rest, SageMaker KMS for training volumes and model artifacts, all transit over TLS. CloudTrail is required for HIPAA audit trail. VPC requirements are stated with endpoints for S3, DynamoDB, and CloudWatch Logs. The "Never use real member data in dev/test" warning is present with a link to CMS synthetic data. The DynamoDB TTL (scoring_date + 30 days) is a good practice for expiring stale scores.

### Issue S1: IAM Permissions Are Not Least-Privilege (HIGH)

**Location:** Prerequisites table, "IAM Permissions" row

**The problem:** The listed permissions (`sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `events:PutRule`) are presented as a flat set with no resource scoping or role separation. This pipeline has at least four distinct execution contexts:

1. Glue job role (needs S3 read/write on feature buckets, read access to source systems)
2. SageMaker execution role (needs S3 read/write on model/feature buckets, KMS decrypt)
3. Step Functions execution role (needs to invoke Glue, SageMaker, and write to DynamoDB)
4. EventBridge scheduler role (needs to start Step Functions executions)

Presenting these as a single permission set implies a single role. The Step Functions orchestrator would have permissions to create training jobs AND write to DynamoDB AND put EventBridge rules. A compromised orchestration step could modify the scoring schedule or retrain the model with poisoned data.

**Suggested fix:** Split into role-specific entries or add a note: "These permissions are distributed across service-specific execution roles. The Glue role should only have S3 access to feature buckets. The SageMaker role should not have DynamoDB write access. The Step Functions role needs invoke permissions for downstream services but not direct S3 data access. Scope each role with resource ARNs restricted to specific buckets, tables, and jobs."

### Issue S2: SHAP Values in DynamoDB May Expose Sensitive Behavioral Patterns (MEDIUM)

**Location:** Step 5 pseudocode (store_and_serve), Expected Results JSON

**The problem:** The `top_risk_factors` field stored in DynamoDB contains SHAP-derived explanations like "PCP left network 45 days ago," "Two unresolved grievances," "70% drop in utilization." This data is stored alongside `member_id` and served to "downstream systems (call center applications, care management platforms, member portals)."

The concern: these explanations expose sensitive behavioral and satisfaction data to any system with DynamoDB `GetItem` access. A call center agent seeing "Two unresolved grievances" is appropriate. A member portal displaying "70% drop in utilization" to the member themselves could be confusing or alarming. The recipe doesn't differentiate access levels for different consumers of this data.

Additionally, the `top_risk_factors` field creates a derived behavioral profile that persists even after the underlying events are resolved. A member whose grievances were resolved still has "grievances" listed as a risk factor until the next scoring run.

**Suggested fix:** Add guidance on consumer-specific access patterns: "Not all downstream systems should see the full risk factor detail. The call center application may need the full explanation for context. The member portal should not display churn risk factors to the member. Use IAM conditions or application-layer filtering to restrict which fields are returned based on the calling system's identity. Consider storing detailed explanations in a separate attribute that requires elevated permissions to read."

### Issue S3: EventBridge Event Detail Contains PHI (MEDIUM)

**Location:** Step 5 pseudocode, "publish high_risk to EventBridge with detail_type = 'MemberChurnRiskHigh'"

**The problem:** The pseudocode publishes high-risk member data to EventBridge. EventBridge events are logged, can be routed to multiple targets, and may be stored in event archives. If the event detail includes `member_id`, `churn_probability`, and `top_risk_factors`, this PHI is now flowing through EventBridge's control plane.

The recipe doesn't specify what's included in the event detail or whether EventBridge event archives are encrypted. EventBridge itself is a HIPAA-eligible service, but the event detail content and routing rules determine whether PHI is appropriately contained.

**Suggested fix:** Add a note: "The EventBridge event should contain only the member_id and risk_tier, not the full risk factor detail. Downstream intervention systems should look up the full detail from DynamoDB using the member_id. This minimizes PHI in the event bus and reduces the blast radius if an event rule is misconfigured to route to an unintended target. If event archives are enabled, ensure they use KMS encryption."

### Issue S4: No Mention of Model Explainability Audit Requirements (MEDIUM)

**Location:** The Technology section, "Calibration Matters More Than Accuracy" subsection; The Honest Take, ethical dimension

**The problem:** The recipe correctly discusses the ethical dimension (models encoding discrimination via zip code). In regulated healthcare contexts, there may be requirements to demonstrate that the model does not discriminate based on protected characteristics. CMS has issued guidance on algorithmic bias in Medicare Advantage. State insurance regulators are increasingly scrutinizing predictive models used in coverage decisions.

The recipe mentions monitoring predictions across demographic groups but doesn't address the audit trail needed to demonstrate compliance: model cards, fairness metrics, disparate impact analysis, or documentation of what features were excluded and why.

**Suggested fix:** Add to the Honest Take or a new subsection: "Document your model's fairness characteristics in a model card: which features are included, which were excluded and why, and how predictions distribute across demographic groups. CMS and state regulators are increasingly scrutinizing algorithmic decision-making in health plans. Having a documented fairness analysis before you're asked for one is significantly less painful than producing one under regulatory pressure."

### Issue S5: Sample Data Link Should Note Limitations (LOW)

**Location:** Prerequisites table, "Sample Data" row

**The problem:** The CMS synthetic Medicare claims link is appropriate for development. However, the recipe doesn't note that CMS synthetic data lacks several feature categories critical to this model: call center contacts, portal activity, grievance records, and network adequacy data. A developer using only CMS synthetic data would build a model missing the most predictive feature categories.

**Suggested fix:** Add: "CMS synthetic data covers claims and eligibility but not behavioral signals (call center, portal, grievances). For development, generate synthetic behavioral features with realistic distributions. The model's performance on synthetic data will underestimate production performance because the strongest predictors (satisfaction and engagement signals) won't be available."

---

## Architecture Expert Review

### What's Done Well

The four-stage pipeline (Feature Store Assembly, Model Training/Scoring, Risk Stratification, Intervention Routing) is clean and well-motivated. The emphasis on feature engineering as 60-70% of development time is accurate and sets correct expectations. The calibration discussion (isotonic regression, why raw XGBoost probabilities are poorly calibrated) is technically sound. The time-based train/validation split is correct (not random, which would leak temporal patterns). The DynamoDB TTL for stale scores is a good operational practice. The cost estimate ($50-100/month for 100K members) is reasonable for the stated architecture.

### Issue A1: No Model Monitoring or Retraining Trigger Architecture (MEDIUM)

**Location:** Architecture Diagram, General Architecture Pattern section

**The problem:** The recipe mentions "Retraining happens less frequently (quarterly or when performance degrades)" in the General Architecture section. But the architecture contains no infrastructure for detecting performance degradation. There is no:

- Ground truth collection (joining predictions with actual disenrollment outcomes)
- Calibration monitoring (is the model still well-calibrated after open enrollment shifts the population?)
- Feature drift detection (are the input distributions changing?)
- Automated retraining trigger

The recipe correctly identifies seasonality as a challenge ("A model trained on January-March data and deployed in October will underperform"). But without monitoring, you won't know when seasonal drift has degraded your model until retention outcomes are already poor.

This is MEDIUM rather than HIGH because the recipe does acknowledge the need for retraining and the feedback loop ("Track which interventions were attempted, which members were retained, and feed that outcome data back into the next training cycle"). The gap is in the implementation detail, not the conceptual understanding.

**Suggested fix:** Add a brief Step 6 or extend the General Architecture section: "Add a monthly ground truth join: compare predictions from 90 days ago against actual disenrollment outcomes. Compute rolling AUC-PR and Expected Calibration Error. Publish to CloudWatch. Trigger retraining when AUC-PR drops below 0.40 or ECE exceeds 0.10. This is especially important around open enrollment periods when population composition shifts."

### Issue A2: Intervention Routing Is Rule-Based But Rules Aren't Specified (MEDIUM)

**Location:** Step 4 pseudocode (score_membership), `recommend_intervention(top_drivers)` function call

**The problem:** The scoring step calls `recommend_intervention(top_drivers)` to route members to the appropriate intervention type. The Expected Results show `"intervention_type": "network_adequacy_outreach"`. But the `recommend_intervention` function is never defined. The General Architecture section says "The routing logic is often rule-based on top of the model's feature importance" but doesn't provide the rules.

This matters because the intervention routing is where the business value is realized. A reader implementing this recipe gets a scored population with no guidance on how to translate risk factors into specific interventions. The recipe's own Honest Take says "the intervention matters more than the model," but the intervention routing is the least-specified component.

**Suggested fix:** Add a brief pseudocode block for `recommend_intervention`:

```
FUNCTION recommend_intervention(top_drivers):
    IF "pcp_in_network" in top_drivers with value 0:
        RETURN "network_adequacy_outreach"
    IF "grievances" or "unresolved_grievances" in top_drivers:
        RETURN "member_services_escalation"
    IF "denied_claims" or "total_oop" in top_drivers:
        RETURN "benefits_counseling"
    IF "utilization_trend" or "portal_login_trend" in top_drivers:
        RETURN "engagement_outreach"
    RETURN "general_retention_call"
```

This doesn't need to be complex, but it should exist to make the recipe actionable end-to-end.

### Issue A3: Risk Tier Thresholds Are Hardcoded Without Capacity Calibration Guidance (MEDIUM)

**Location:** Step 4 pseudocode, `assign_tier` function

**The problem:** The `assign_tier` function uses fixed thresholds (0.60 for high, 0.35 for medium). The General Architecture section correctly notes that "tier boundaries are calibrated against your retention team's capacity: there's no point flagging 5,000 members as high-risk if your team can only handle 200 outreach calls per week." But the code uses fixed probability thresholds rather than capacity-based thresholds.

If your population is 100K members and 15% have probability > 0.60, that's 15,000 "high-risk" members. If your retention team can handle 200 calls per week, you need 75 weeks to reach them all. The thresholds should be set based on intervention capacity, not arbitrary probability cutoffs.

**Suggested fix:** Add a note after the `assign_tier` function: "These thresholds are illustrative. In production, set them based on your retention team's weekly capacity. If your team can handle 200 outreach calls per week and you score monthly, your 'high' tier should contain roughly 800 members (200 calls/week x 4 weeks). Work backward from capacity to find the probability threshold that produces the right volume. Recalibrate quarterly as team capacity and population size change."

### Issue A4: No Discussion of Label Leakage Risk in Specific Features (LOW)

**Location:** Step 1 pseudocode (assemble_member_features)

**The problem:** The feature `annual_wellness_completed` is computed as "1 if wellness visit in last 12 months, else 0." If the prediction window is 60-90 days before open enrollment (as recommended), and the label is "did they disenroll during open enrollment," there's a subtle leakage risk: members who are already planning to leave may skip their wellness visit precisely because they're leaving. The absence of a wellness visit is both a predictor and a consequence of the decision to leave.

This isn't true data leakage (the feature is computed before the label date), but it's a form of "label leakage" where the feature captures the outcome rather than predicting it. The model learns "people who skip wellness visits leave" but the causal direction may be reversed.

**Suggested fix:** Add a brief note in the feature engineering discussion: "Some features (like skipped wellness visits) may reflect the decision to leave rather than predict it. If a member has already decided to switch plans, they may stop engaging with your services. These features still have predictive value, but interventions targeting them (e.g., 'schedule your wellness visit') may not address the root cause. Prioritize features that capture fixable problems (network gaps, unresolved grievances) over features that capture disengagement symptoms."

### Issue A5: Batch Transform vs. SageMaker Pipelines (LOW)

**Location:** Architecture Diagram, "Why These Services" for SageMaker

**The problem:** The recipe uses SageMaker Batch Transform for weekly scoring. This is appropriate for the stated scale (100K members). However, the recipe doesn't mention SageMaker Pipelines as the orchestration layer for the ML workflow (training, evaluation, registration, deployment). Step Functions is used for the scoring pipeline orchestration, but the model training/retraining lifecycle isn't orchestrated.

This is LOW because the recipe's scope is primarily the scoring pipeline, and Step Functions is a reasonable orchestration choice. But for teams that will iterate on the model (which the recipe recommends), SageMaker Pipelines provides model registry, approval workflows, and lineage tracking that Step Functions doesn't.

**Suggested fix:** Add a brief note in Variations: "For teams iterating frequently on the model, consider SageMaker Pipelines for the training workflow. It provides model registry (versioning and approval gates), lineage tracking (which training data produced which model), and automated evaluation steps. Step Functions remains appropriate for the scoring pipeline orchestration."

---

## Networking Expert Review

### What's Done Well

The recipe correctly specifies VPC placement for SageMaker training and Glue jobs. VPC endpoints for S3, DynamoDB, and CloudWatch Logs are listed. "No public internet access for PHI processing" is explicitly stated. The architecture is batch-oriented, which simplifies networking (no real-time inference endpoints exposed to the internet).

### Issue N1: No Guidance on Source System Connectivity (MEDIUM)

**Location:** Prerequisites table, "VPC" row; Architecture Diagram, "Data Sources" box

**The problem:** The architecture shows six data sources (Claims, Eligibility, Call Center Logs, Portal Activity, Grievance Records, Network Directory) feeding into Glue. The VPC section says "Production: SageMaker training and Glue jobs in VPC with VPC endpoints for S3, DynamoDB, and CloudWatch Logs."

But how do Glue jobs reach these six source systems? In a typical health plan:
- Claims and eligibility are in a data warehouse (Redshift, on-premises Oracle/SQL Server)
- Call center logs are in a CRM (Salesforce, on-premises Genesys)
- Portal activity is in application databases or event streams
- Grievance records are in a case management system
- Network directory is in a provider data management system

Each source may be in a different network segment. The Glue jobs need ENIs with routes to each source. If sources are on-premises (common for legacy health plan systems), Direct Connect or VPN is required. If sources are in different VPCs, peering or Transit Gateway is needed.

**Suggested fix:** Add to the VPC prerequisites: "Glue jobs require network connectivity to each source system. For on-premises sources (common for claims warehouses and legacy CRM systems), this requires Direct Connect or site-to-site VPN with appropriate route table entries in the Glue subnet. For sources in separate VPCs, use VPC peering or Transit Gateway. Security groups on Glue ENIs must allow outbound traffic to each source system's port. Plan for this connectivity early; it's often the longest lead-time item in healthcare ML deployments."

### Issue N2: DynamoDB VPC Endpoint Type Not Specified (LOW)

**Location:** Prerequisites table, "VPC" row

**The problem:** The recipe lists "VPC endpoints for S3, DynamoDB, and CloudWatch Logs" but doesn't specify the endpoint type. S3 and DynamoDB use gateway endpoints (free, route-table-based). CloudWatch Logs uses an interface endpoint (costs money, ENI-based). This distinction matters for cost estimation and subnet configuration.

**Suggested fix:** Add: "S3 and DynamoDB use gateway VPC endpoints (no additional cost, configured via route tables). CloudWatch Logs requires an interface VPC endpoint (hourly charge plus data processing fees). Additional interface endpoints may be needed for SageMaker API and KMS if control-plane calls originate from within the VPC."

### Issue N3: No Mention of Cross-AZ Data Transfer for Glue (LOW)

**Location:** Architecture, Glue configuration

**The problem:** Glue jobs processing 100K members with hundreds of features per member will move non-trivial data volumes. If Glue workers span multiple AZs (default behavior for availability), cross-AZ data transfer charges apply. For a weekly job this is negligible, but it's worth noting for larger populations.

**Suggested fix:** Not required for this recipe's scale. The cost estimate already accounts for Glue DPU-hours. Cross-AZ transfer at this volume is cents per run. No action needed.

---

## Voice Reviewer

### What's Done Well

The recipe is one of the strongest in the cookbook for voice consistency. The opening scenario (open enrollment closes, membership reports come in, everyone scrambling) is vivid and specific. The "cruel part" paragraph builds emotional stakes effectively. The Technology section teaches without condescending: the definition problem, time horizon tradeoffs, and feature categories are explained with the "let me explain why" energy the style guide calls for. Parenthetical asides are natural ("ok, this is a gross oversimplification" energy without being that exact phrase). The Honest Take delivers genuine insights that a reader couldn't get from documentation.

Specific highlights:
- "The cruel part: retention interventions actually work." Perfect sentence. Sets up the prediction problem with emotional stakes.
- "This sounds simple. It's not. Let me explain why." Classic CC cadence.
- "The model is the easy part. Seriously." Direct, counterintuitive, true.
- "By the time someone submits a disenrollment form, it's too late. The decision was made weeks or months earlier." Clean insight, no filler.

### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the recipe. Clean.

### Issue V2: Vendor Balance Is Correct (PASS)

The Problem section, Technology section, and General Architecture Pattern section (approximately 70% of the recipe's prose) are entirely vendor-agnostic. AWS services appear only in "The AWS Implementation" section. The feature engineering discussion, model selection rationale, calibration explanation, and cold start problem are all cloud-neutral. A reader on GCP or Azure learns the full conceptual framework. The 70/30 target is met.

### Issue V3: One Instance of Mild Documentation-Voice (LOW)

**Location:** "Why These Services" section, EventBridge paragraph

**The problematic text:** "This is cleaner than cron jobs and gives you built-in retry logic and failure alerting."

The "cleaner than cron jobs" comparison is fine (engineer voice). But "gives you built-in retry logic and failure alerting" is slightly product-feature-list voice. The rest of the paragraph is good.

**Suggested fix:** Rewrite to: "This is cleaner than cron jobs. You get retry logic and failure alerting without building them yourself, which matters when a missed scoring run means your retention team is working with stale risk data for a week."

### Issue V4: "The Technology" Section Header Deviates from Style Guide (LOW)

**Location:** Section header after "The Problem"

**The text:** "The Technology: Predicting Who Will Leave"

The style guide specifies "The Technology" as the section name. Adding a subtitle is fine and other recipes do it, but noting for consistency tracking.

**Verdict:** No action needed. Subtitles on section headers are used elsewhere in the cookbook.

---

## Stage 2: Expert Discussion

**Security (S1) is the only HIGH finding.** The IAM permissions issue is a recurring pattern across recipes in this cookbook. It's important but well-understood: the fix is adding a note about role separation rather than restructuring the architecture.

**Architecture (A1) vs. the recipe's own guidance:** The recipe says "The feedback loop is critical. Track which interventions were attempted, which members were retained, and feed that outcome data back into the next training cycle." But the architecture doesn't implement this loop. A1 is the most impactful MEDIUM finding because the recipe identifies the need but doesn't deliver the implementation. However, the recipe does acknowledge this explicitly, which is why it's MEDIUM rather than HIGH.

**Architecture (A2) and the Honest Take:** The recipe says "the intervention matters more than the model" but the intervention routing function is undefined. This is a gap between the recipe's thesis and its implementation. The fix is straightforward (add a simple rule-based function) and would significantly improve actionability.

**Security (S2, S3) overlap:** Both concern PHI flowing to places it shouldn't. S2 is about SHAP explanations in DynamoDB being served to inappropriate consumers. S3 is about PHI in EventBridge events. Both are solved by the same principle: minimize PHI in transit and at rest, use member_id as a reference key, and let consumers look up only what they need.

**No conflicts between experts.** All findings are complementary.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

No CRITICAL findings. One HIGH finding (well below the 3-HIGH threshold for FAIL). The recipe is architecturally sound, clinically appropriate, well-written, and provides actionable guidance for the core prediction pipeline. The HIGH finding (IAM) is a standard security hygiene issue that doesn't undermine the recipe's core contribution. The MEDIUM findings are operational completeness gaps (monitoring, intervention routing, EventBridge PHI) that would surface in production but represent polish rather than fundamental design flaws.

The recipe's core strengths are substantial: the feature engineering taxonomy is comprehensive and well-explained, the calibration emphasis is correct and well-motivated, the ethical dimension is handled thoughtfully, and the Honest Take delivers genuine practitioner insights. This is one of the stronger recipes in Chapter 7.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites, IAM Permissions row | Permissions listed as flat set implying single role. Step Functions orchestrator would have permissions to create training jobs AND write to DynamoDB AND modify EventBridge rules. Violates least-privilege. | Split into role-specific entries or add explicit note about role separation with resource-scoped ARNs for each execution context. |
| 2 | MEDIUM | Architecture | Architecture Diagram, General Architecture | No model monitoring or retraining trigger despite recipe acknowledging feedback loop is "critical." No ground truth collection, calibration monitoring, or drift detection infrastructure. | Add Step 6: monthly ground truth join, rolling AUC-PR and ECE computation, CloudWatch alarm, retraining trigger. Especially important around open enrollment periods. |
| 3 | MEDIUM | Architecture | Step 4 pseudocode, `recommend_intervention` call | Intervention routing function is called but never defined. Recipe's own Honest Take says "the intervention matters more than the model" but the intervention logic is the least-specified component. | Add a brief pseudocode block for `recommend_intervention` mapping top risk factors to intervention types. |
| 4 | MEDIUM | Security | Step 5 pseudocode, DynamoDB writes | SHAP-derived `top_risk_factors` stored in DynamoDB and served to all downstream systems including member portals. No access differentiation between consumers. Behavioral explanations may be inappropriate for member-facing surfaces. | Add guidance on consumer-specific access patterns. Store detailed explanations in a separate attribute requiring elevated permissions. |
| 5 | MEDIUM | Security | Step 5 pseudocode, EventBridge publish | High-risk member data published to EventBridge without specifying what's in the event detail. PHI in event bus increases blast radius if rules are misconfigured. | Specify that events should contain only member_id and risk_tier. Downstream systems look up detail from DynamoDB. Ensure event archives use KMS encryption. |
| 6 | MEDIUM | Security | Technology section, Honest Take | No mention of model documentation requirements (model cards, fairness metrics, disparate impact analysis) despite discussing algorithmic bias. CMS and state regulators increasingly scrutinize predictive models in health plans. | Add note about documenting fairness characteristics in a model card. Having a documented fairness analysis before regulatory inquiry is significantly less painful. |
| 7 | MEDIUM | Architecture | Step 4 pseudocode, `assign_tier` function | Risk tier thresholds are hardcoded (0.60, 0.35) without capacity calibration guidance. Recipe correctly notes tiers should match retention team capacity but code uses fixed probability cutoffs. | Add note: set thresholds based on intervention capacity. Work backward from weekly call volume to find the probability threshold that produces the right tier size. |
| 8 | MEDIUM | Networking | Prerequisites, VPC row; Architecture Diagram | No guidance on Glue connectivity to six source systems. Health plan source systems are typically on-premises or in separate VPCs. Common deployment blocker. | Add note about Direct Connect/VPN requirements, security groups for Glue ENIs, and that source connectivity is often the longest lead-time item. |
| 9 | LOW | Security | Prerequisites, Sample Data row | CMS synthetic data lacks behavioral features (call center, portal, grievances) that are the strongest churn predictors. Developer using only CMS data builds incomplete model. | Add note that CMS data covers claims/eligibility only. Recommend generating synthetic behavioral features for development. |
| 10 | LOW | Architecture | Step 1 pseudocode, feature engineering | `annual_wellness_completed` may capture the decision to leave rather than predict it (reverse causality). Members planning to leave may skip wellness visits as a consequence, not a cause. | Add note distinguishing fixable-problem features (network gaps, grievances) from disengagement-symptom features (skipped visits, reduced logins). |
| 11 | LOW | Voice | "Why These Services", EventBridge paragraph | "gives you built-in retry logic and failure alerting" is slightly product-feature-list voice. | Rewrite to connect the capability to the business consequence of missing it. |
| 12 | LOW | Networking | Prerequisites, VPC row | VPC endpoint types not specified. S3/DynamoDB use gateway endpoints (free). CloudWatch Logs uses interface endpoint (costs money). Distinction matters for cost and subnet config. | Add brief note distinguishing gateway vs. interface endpoints. |

---

## Priority Actions Before Publication

1. **Fix S1 (HIGH):** Split IAM permissions into role-specific guidance. This is the only HIGH finding and a straightforward fix: add a sentence noting that permissions are distributed across service-specific roles with resource-scoped ARNs.

2. **Fix A2, A3 (MEDIUM architecture):** Define the `recommend_intervention` function and add capacity-based threshold guidance. These two fixes together make the recipe actionable end-to-end, which aligns with the recipe's own thesis that interventions matter more than the model.

3. **Fix S2, S3 (MEDIUM security):** Minimize PHI in DynamoDB consumer access and EventBridge events. Both follow the same principle: use member_id as a reference key, let consumers look up only what they need.

4. **Fix A1 (MEDIUM architecture):** Add monitoring architecture. The recipe acknowledges the feedback loop is critical but doesn't implement it. A brief Step 6 with ground truth collection and calibration monitoring closes this gap.

5. **Fix S4, N1 (MEDIUM):** Add model documentation guidance and source system connectivity notes. These are compliance and deployment readiness items.

The LOW findings (S5, A4, V3, N2) are polish items that improve quality but don't block a competent builder.

---

*Review complete. Recipe 7.3 is a strong recipe with excellent problem framing, comprehensive feature engineering guidance, and a genuinely educational technology section. The calibration emphasis, ethical dimension discussion, and Honest Take insights are among the best in Chapter 7. The single HIGH finding (IAM) is a standard security hygiene issue. The MEDIUM findings are primarily about operational completeness (monitoring, intervention routing specificity, PHI minimization in transit) rather than fundamental design flaws. A builder with health plan domain knowledge could deploy from this recipe with the HIGH item addressed.*
