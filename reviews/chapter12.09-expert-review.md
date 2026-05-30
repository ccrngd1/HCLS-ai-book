# Expert Review: Recipe 12.9 -- Epidemic Forecasting

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 12.09 -- Epidemic Forecasting
**Date:** 2026-05-29
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 12.9 is an exceptional piece of technical writing. The treatment of epidemic forecasting is thorough, technically accurate, and reflects genuine production experience. The multi-source data fusion discussion, the behavioral feedback section, the calibration framework, and the honest take are all outstanding. The architecture is sound, the AWS service selection is well-justified, and the pseudocode is clear and educational. The recipe correctly identifies the ensemble approach as the production standard and references the right institutional frameworks (CDC FluSight, COVID-19 Forecast Hub, CFA, Delphi group).

**Verdict: PASS**

The recipe has no CRITICAL findings and only 2 HIGH findings. The issues identified are addressable with targeted edits and do not undermine the recipe's core value. The architecture is production-viable, the security posture is well-considered, and the healthcare domain treatment is accurate.

---

## Stage 1: Independent Expert Reviews

---

## Security Review

### 🟠 SEC-1: IAM Permissions List Includes Overly Broad Actions Without Resource Scoping

**Finding:** The Prerequisites table lists IAM permissions as a flat list (`kinesis:PutRecord`, `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateTrainingJob`, etc.) and states "Each pipeline component runs under a least-privilege role scoped to its data class." However, the listed permissions are presented as a single aggregate list without showing the per-role decomposition. A reader implementing this could reasonably interpret this as a single role needing all these permissions. The `sagemaker:InvokeEndpoint` permission combined with `s3:GetObject` on PHI buckets in a single role would violate least-privilege.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Add a brief note or sub-table showing the role decomposition: (1) Ingestion role: Kinesis + S3 raw bucket only; (2) Harmonization role: S3 raw read + S3 harmonized write + Glue; (3) Forecasting role: S3 harmonized/nowcast read + SageMaker + S3 forecast write; (4) Publishing role: S3 forecast read + DynamoDB write + Aurora write; (5) Dashboard role: DynamoDB read + Aurora read + QuickSight. Even a one-sentence clarification like "See the role decomposition in the walkthrough" with per-step role annotations would suffice.

---

### 🟡 SEC-2: Case-Line-List Data Handling Needs Stronger Minimum-Necessary Guidance

**Finding:** The recipe correctly identifies that "most production systems handle some line-list data for nowcasting accuracy and case investigation linkage" and that BAA coverage is standard. However, the pseudocode and architecture do not explicitly show where the line-list data is de-identified or aggregated before flowing into the forecasting layer. The nowcasting step receives "harmonized_signals" but it is unclear whether individual-level records have been aggregated to counts by this point or whether the nowcasting model operates on individual records.

**Location:** Step 2 pseudocode (`nowcast_current_state`), and the "Why This Isn't Production-Ready" section on surveillance data governance.

**Fix:** Add a comment in the harmonization pseudocode (Step 1) explicitly noting: "Output is aggregated counts per geography per time unit. Individual-level case records are consumed during harmonization but not persisted in the harmonized layer. If individual-level data is needed downstream (e.g., for delay-distribution estimation), it flows through a separate restricted-access path with additional access controls." This makes the minimum-necessary principle explicit in the architecture.

---

### 🟡 SEC-3: Scenario-Evaluation Lambda API Lacks Authentication Discussion

**Finding:** The recipe describes a "Lambda-fronted API" for scenario evaluation requests from public health staff. No mention is made of authentication, authorization, or rate limiting on this API. Scenario requests could potentially be used to probe the model's behavior or to generate forecasts that, if leaked, could cause public confusion or market impact (for healthcare-adjacent financial instruments).

**Location:** "AWS Lambda for the scenario-evaluation API" in the Why These Services section.

**Fix:** Add a brief note: "The scenario API is internal-only, fronted by API Gateway with IAM or Cognito authentication, restricted to authorized public health analysts. Rate limiting prevents abuse. Scenario outputs are marked as internal-draft until reviewed and approved for publication."

---

### ✅ SEC-PRAISE: Excellent PHI Handling Framework

The recipe's treatment of encryption (per-data-class CMKs), CloudTrail with data events on PHI-bearing resources, Object Lock on audit logs, VPC endpoint isolation, and the explicit BAA discussion is thorough and correct. The distinction between aggregate count data (generally not PHI) and individual-level line-list data (PHI) is correctly drawn. The "Never use real individual-level case-line-list data in dev" callout in Sample Data is exactly right.

---

## Architecture Review

### 🟠 ARCH-1: No Dead Letter Queue or Error Handling in the Step Functions Pipeline

**Finding:** The Step Functions orchestration is described as handling the daily forecast cycle with "explicit retry semantics" but no mention is made of Dead Letter Queues, error states, or partial-failure handling. In a pipeline with parallel fan-out across multiple model families (Distributed Map), individual model failures are expected (a Bayesian sampler may fail to converge, a container may OOM). The recipe does not describe what happens when one model in the ensemble fails: does the pipeline halt, does it proceed with fewer models, does it alert and continue?

**Location:** "AWS Step Functions for the daily forecast pipeline" in Why These Services, and Step 4 pseudocode where `minimum_models_required` is checked.

**Fix:** The pseudocode in Step 4 does handle this partially (the `minimum_models_required` check and the `filter_eligible` function). Add a brief architectural note in the Step Functions description: "Individual model failures in the Distributed Map are caught and logged; the pipeline continues with remaining models as long as the minimum ensemble size is met. Failed model runs trigger CloudWatch alarms and are retried on the next cycle. A DLQ on the Step Functions state machine captures pipeline-level failures for investigation." This makes the fault-tolerance explicit.

---

### 🟡 ARCH-2: Aurora PostgreSQL as Analytic Registry May Be Undersized for Multi-Year Forecast History

**Finding:** The recipe uses Aurora PostgreSQL for the "full forecast artifacts (per-model trajectories, ensemble distributions, scenario comparisons, and calibration metrics)." For a multi-pathogen, multi-geography system running daily with 5+ models producing full posterior samples, the data volume grows quickly. A single state with 100 counties, 8 forecast horizons, 23 quantiles, 5 models, daily runs, across 3 pathogens generates ~100M rows per year in the forecast registry. Aurora PostgreSQL can handle this but the recipe does not discuss partitioning strategy, retention policy, or when to consider moving historical forecasts to S3/Athena.

**Location:** "Amazon Aurora PostgreSQL for the analytic forecast registry" in Why These Services.

**Fix:** Add a sentence: "Partition the forecast registry by run_date and pathogen. Implement a retention policy that moves forecast artifacts older than 12-24 months to S3 Parquet (queryable via Athena) to keep Aurora performant for recent-history analyst queries and calibration evaluation."

---

### 🟡 ARCH-3: DynamoDB Partition Key Design May Create Hot Partitions

**Finding:** The DynamoDB forecast-serving table uses `partition_key = summary.geography` and `sort_key = summary.target + "#" + summary.horizon`. During an active outbreak response, a single high-profile geography (e.g., the state itself, or a major metro county) will receive disproportionate read traffic from dashboards, APIs, and hospital operations integrations. This creates a hot partition.

**Location:** Step 5 pseudocode, DynamoDB write pattern.

**Fix:** Add a note: "For high-traffic geographies, consider a composite partition key that includes a shard suffix (e.g., geography#shard_N with N in 0-3) and scatter-gather reads, or use DynamoDB DAX as a read cache for the dashboard layer." Alternatively, note that DynamoDB's adaptive capacity handles moderate hot-partition scenarios automatically, but that DAX is recommended for dashboard-scale read patterns.

---

### ✅ ARCH-PRAISE: Excellent Separation of Concerns

The pipeline's separation into harmonization, nowcasting, per-model forecasting, ensemble combination, and validation/publishing is textbook correct. The use of S3 as the intermediate artifact store between stages enables reproducibility and replay. The Distributed Map pattern for parallel model execution is the right choice. The calibration-as-first-class-operational-metric framing is exactly how production forecasting systems should work.

---

## Networking Review

### 🟡 NET-1: VPC Endpoint List Is Incomplete

**Finding:** The Prerequisites VPC section states "SageMaker training, inference, and processing in private subnets with VPC endpoints for S3, DynamoDB, KMS, Step Functions, CloudWatch Logs, Glue, and SageMaker API/Runtime." This is a good list but omits several services that would need VPC endpoints in a fully private deployment: SNS (for calibration drift alarms), EventBridge, Lambda (if invoked from within VPC), and ECR (for pulling SageMaker custom containers).

**Location:** Prerequisites table, "VPC" row.

**Fix:** Expand the VPC endpoint list to include: "S3, DynamoDB, KMS, Step Functions, CloudWatch Logs, Glue, SageMaker API/Runtime, ECR (for custom container pulls), SNS, and EventBridge. Lambda functions that access VPC resources require VPC configuration with appropriate security groups."

---

### ✅ NET-PRAISE: Correct Public-Facing Surface Isolation

The architecture correctly isolates the public-facing dashboard as the only externally addressable surface (S3 + CloudFront static site), with all processing infrastructure in private subnets. This is the right pattern for public health systems where the data pipeline must be isolated from internet-facing attack surface.

---

## Voice Review

### 🟡 VOICE-1: Em Dash Usage Detected

**Finding:** The recipe contains em dashes in several locations, violating the style guide's absolute prohibition.

**Locations:**
- "The Problem" paragraph 1: "three dashboards on three monitors trying to decide whether something is happening" -- this is fine (no em dash here), but checking further...
- "The Technology" section: "SIR, SEIR, SEIRS, and friends, the family of models that describes..." -- no em dash.
- After thorough review: The recipe uses double-hyphens in a few TODO comments but no actual em dash characters (U+2014) appear in the prose. The recipe uses commas, colons, semicolons, and parentheses throughout as alternatives.

**Correction:** On closer inspection, no em dashes (the character "—") are present in the recipe text. The style guide prohibition is satisfied. Withdrawing this finding.

---

### 🔵 VOICE-2: Minor Doc-Voice Creep in Prerequisites Table Headers

**Finding:** The Prerequisites table uses slightly formal headers ("Requirement / Details") which is standard for the recipe format. However, a few entries use passive constructions: "Every service touching individual-level data must be on the HIPAA eligible services list" and "Customer-managed CMKs per data class are the standard." These are borderline but acceptable given the tabular context.

**Location:** Prerequisites table, BAA and Encryption rows.

**Fix:** Optional. These are within acceptable range for tabular reference content. No change required.

---

### ✅ VOICE-PRAISE: Outstanding Voice Consistency

The recipe is one of the strongest voice performances in the cookbook. The Problem section is genuinely compelling and makes the reader feel the decision pressure. The Technology section teaches without condescension. The Honest Take is authentic, specific, and self-deprecating in exactly the right way ("I spent six weeks getting the harmonization right, two weeks getting the nowcasting working, and one week on the actual forecasting math"). The behavioral feedback discussion ("Epidemics are not weather") is a perfect example of the cookbook's voice: complex concept, accessible explanation, genuine insight. The 70/30 vendor balance is well-maintained with the Technology section being entirely vendor-agnostic and the AWS section clearly delineated.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. The security, architecture, and networking findings are complementary rather than conflicting.

**Priority resolution:**
- SEC-1 (IAM role decomposition) and ARCH-1 (DLQ/error handling) are the two HIGH findings. Both are addressable with brief additions rather than structural rewrites.
- The MEDIUM findings (SEC-2, SEC-3, ARCH-2, ARCH-3, NET-1) are all "add a sentence or two" fixes that improve completeness without changing the recipe's structure.
- Voice review found no issues. The recipe is exemplary in this dimension.

**Cross-cutting observation:** The recipe's "Why This Isn't Production-Ready" section already addresses many of the gaps that would otherwise be findings (data governance, reporting delay modeling, multi-strain, hospital integration, public communication, federation, equity auditing, reproducibility, regulatory framing, idempotency). This section is unusually thorough and preempts several potential criticisms. The expert panel notes this as a strength.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| SEC-1 | 🟠 HIGH | Security | Prerequisites, IAM Permissions | Flat permission list without per-role decomposition could be misread as single-role | Add brief role decomposition note or sub-table showing 5 distinct roles |
| ARCH-1 | 🟠 HIGH | Architecture | Why These Services (Step Functions) | No DLQ or partial-failure handling described for model fan-out | Add note on individual model failure handling, minimum ensemble threshold, and DLQ |
| SEC-2 | 🟡 MEDIUM | Security | Step 1-2 pseudocode | Unclear where line-list data is aggregated vs. passed through | Add comment in harmonization showing aggregation boundary |
| SEC-3 | 🟡 MEDIUM | Security | Why These Services (Lambda) | Scenario API has no auth/authz discussion | Add note on API Gateway + IAM/Cognito auth, rate limiting, internal-only access |
| ARCH-2 | 🟡 MEDIUM | Architecture | Why These Services (Aurora) | No partitioning or retention strategy for growing forecast registry | Add sentence on partition-by-date and S3/Athena offload for historical data |
| ARCH-3 | 🟡 MEDIUM | Architecture | Step 5 pseudocode (DynamoDB) | Hot partition risk for high-traffic geographies | Add note on DAX caching or shard-suffix pattern |
| NET-1 | 🟡 MEDIUM | Networking | Prerequisites, VPC | VPC endpoint list missing ECR, SNS, EventBridge | Expand list to include all required endpoints |

---

## Final Verdict: **PASS**

The recipe is technically excellent, architecturally sound, and demonstrates deep domain expertise in both epidemic forecasting and production public health systems. The 2 HIGH findings are addressable with brief additions (a role decomposition note and a fault-tolerance note) and do not represent architectural flaws. The 5 MEDIUM findings are all "add a sentence" improvements. The voice is outstanding. The healthcare domain treatment is accurate and reflects real-world implementation experience. The recipe is ready for the TechEditor stage after addressing the HIGH findings.

---

## Additional Notes

**Strengths worth highlighting:**
- The behavioral feedback section ("Epidemics are not weather") is one of the best explanations of this concept in any technical resource
- The calibration discussion is technically precise and operationally grounded
- The "Why This Isn't Production-Ready" section is unusually thorough and honest
- The multi-source data fusion treatment correctly identifies wastewater as increasingly the primary nowcast input
- The scenario forecasting framing (conditional projections, not predictions) is the correct epistemological stance
- The references section is comprehensive and all cited resources are real, verifiable, and relevant
- The cross-references to other recipes (3.10, 12.3, 12.5, 12.8) are accurate and well-motivated
- The cost estimate range ($1,200-$5,000/month) is realistic for state-level respiratory virus forecasting

**Domain accuracy validation:**
- SEIR compartmental model description: Correct
- Weighted Interval Score and Vincentized quantile combination: Correctly described
- CDC FluSight and COVID-19 Forecast Hub references: Accurate institutional descriptions
- Wastewater surveillance lead time (4-10 days): Consistent with published literature
- POLYMOD contact matrix reference: Correct and appropriate
- Reporting delay and nowcasting framing: Technically accurate
- Ensemble superiority over individual models: Empirically supported by forecast hub evaluations
- Behavioral feedback and counterfactual problem: Correctly framed
