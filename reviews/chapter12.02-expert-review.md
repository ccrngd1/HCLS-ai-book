# Expert Review: Recipe 12.2 - Supply Inventory Forecasting

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-25
**Recipe file:** `chapter12.02-supply-inventory-forecasting.md`

---

## Overall Assessment

**Verdict: PASS**

This is the second recipe in Chapter 12 (Time Series Analysis / Forecasting) and the chapter's second simple-tier recipe. It correctly inherits the forecasting machinery from 12.1 (Appointment Volume Forecasting) and adds the recipe-distinct primitives that justify a separate recipe rather than a footnote on 12.1: SKU-segmentation by demand pattern, intermittent-demand methods (Croston, SBA, TSB), the procedure-driven two-stage forecast (cases times per-case usage), the safety-stock-and-reorder-point translation, and the materials-management-and-ERP integration target. The opening Tuesday-afternoon vignette (the missing surgical staple cartridge with the two-hour vendor cutoff and the 35% expedite fee, simultaneously with the eighteen months of pandemic-era respiratory masks approaching expiration in central supply) earns its position and frames the operational stakes at exactly the right "this is what hospital materials management actually looks like" register.

The Technology section is the clearest articulation in the chapter so far of why "demand forecasting" in a hospital is not one problem but a portfolio of problems with different shapes. The five-bucket SKU taxonomy (high-volume smooth, medium-volume seasonal, low-volume intermittent, procedure-driven, pandemic-and-crisis) is operationally accurate and ties cleanly to the segmentation routing in the architecture. The three method families (classical ETS/ARIMA/SARIMA; Croston/SBA/TSB for intermittent; modern Prophet/DeepAR/N-BEATS) are correctly named and correctly bounded. The reorder-point and safety-stock derivation (`reorder_point = mean_demand * lead_time + z * sqrt(lead_time) * sigma`) is the standard textbook formula. The ADI-and-CV-squared four-corner classification (Syntetos et al.) is the standard quantitative segmentation. The seven-bullet "Why This Is Harder Than It Looks" enumeration (SKU explosion, substitution and equivalent items, vendor and contract changes, lead-time variability, recall and discontinuation, lumpy procedure demand, expiration dating, pandemic and disaster demand) is the recipe's strongest single architectural framing and ties each operational concern to a specific architectural primitive in the AWS implementation.

The five-stage architecture (consumption history -> feature engineering and SKU segmentation -> per-segment model training -> forecast and reorder-point calculation -> materials management / ERP integration) is the right shape. The Step Functions Map state for parallel per-segment training is the correct pattern for a multi-thousand-SKU portfolio. The Amazon Forecast deprecation note with the `transition-your-amazon-forecast-usage-to-amazon-sagemaker-canvas` link is current as of mid-2024 and correctly hedged with a TODO-verify (N1). The DeepAR-as-built-in-SageMaker-algorithm framing is technically accurate. The DynamoDB write pattern (partition key `facility_id#sku_id`, sort key `generated_at`, plus optional `CURRENT` record per `(facility, sku)`) is the right access-pattern shape for low-latency operational consumers.

The Honest Take is publication-ready. The four observations earn the recipe's voice: model-selection-gets-too-much-attention-relative-to-segmentation-and-master-data-plumbing; value-is-in-the-reorder-point-updates-not-the-forecast-itself; intermittent-demand-is-genuinely-harder-than-the-smooth-case; concept-drift-is-silent-and-constant. The closing observation that "the prediction interval, not the point estimate, is the operational primitive" is the recipe's clearest articulation of why probabilistic forecasting earns its keep over point forecasts in a safety-stock context.

That said, two correctness gaps at HIGH severity need attention before publication. First, the encryption posture in the Prerequisites table specifies "SSE-KMS" without naming customer-managed keys per data class, and the architectural treatment of KMS keys across the consumption-history bucket, the model-artifacts bucket, the forecasts bucket, the DynamoDB serving table, the SageMaker training output, and the CloudWatch logs is generic rather than per-class. Second, the per-segment Map state in Step Functions is the architectural fan-out point for training jobs that may run for tens of minutes each, but neither the diagram nor the pseudocode specifies retry policy, dead-letter routing, or partial-failure semantics for a Map iteration that fails mid-fan-out. The chapter-pattern from 12.1 has not yet established a baseline since 12.1's expert review has not been written; 12.2 is therefore the first recipe in the chapter to surface these patterns and the chapter editor should plan to consolidate.

Five MEDIUM findings cluster on architectural specificity (cold-start handling for new SKUs is correctly elevated in production-gaps but not architecturally specified; the forecast-quality gate in Step 3 names rejection but not rollback, alerting, or human-review routing; the reorder-point Lambda for 5,000-plus SKUs may approach the 15-minute Lambda timeout if implemented naively; DynamoDB write idempotency and conditional-write semantics are not specified; the VPC-endpoint enumeration in the Prerequisites table mentions S3, CloudWatch Logs, and KMS without distinguishing gateway endpoints from interface endpoints or naming the SageMaker-API and SageMaker-Runtime endpoints).

Four LOW findings: the BAA framing in the Prerequisites table is correct but more hedged than the chapter pattern warrants; the four inline TODO-verify markers (N1, N2, N3, V1, A1, N4) should be tracked through to publication; the architecture diagram's "Errors" box mentions CloudWatch and SNS but does not show the per-stage retry-and-DLQ wiring; the cost-estimate range ($100-$400/month) does not decompose by SKU count, which is the dominant cost driver per the recipe's own framing.

Voice is excellent. **Em dash count: 0** (verified by U+2014 codepoint scan). En dash count: 11 (used appropriately in numeric ranges and date ranges; en dashes are not forbidden by STYLE-GUIDE.md). The 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout.

Priority breakdown: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW. **Verdict: PASS** because there are 0 CRITICAL findings and HIGH count (2) is below the > 3 = FAIL threshold.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review (OWASP, CIS, NIST SP 800-66 for HIPAA)

#### What's Done Well

- BAA called out explicitly: "AWS BAA signed if consumption data is linked to specific patients or procedures (it usually is at the case level, even when aggregated to daily SKU counts; PHI considerations are conservative)." The conservative posture is correct: case-level linkage is the realistic operational posture, and the BAA hedge appropriately acknowledges that pure aggregate-SKU-count data may not require BAA coverage in some narrow scenarios.
- Encryption at rest specified for S3 (SSE-KMS), DynamoDB (encryption at rest enabled by default), SageMaker training and inference (encrypted EBS volumes, KMS-encrypted output), and CloudWatch log groups (configure KMS encryption explicitly). The explicit elevation of CloudWatch log-group KMS configuration is the right call out.
- VPC enforcement framed correctly for production: "SageMaker training and inference jobs in VPC with VPC endpoints for S3, CloudWatch Logs, and KMS. Required for HIPAA workloads."
- CloudTrail enabled with the correct enumeration: "log all SageMaker, S3, DynamoDB, and Glue API calls for HIPAA audit trail."
- Synthetic-data discipline in the Sample Data row: "Never use real consumption data linked to patient identifiers in dev." The M5 Forecasting Competition reference is appropriately hedged (retail, not healthcare) with the suggested generative shape (case volume * per-case usage + smooth consumables + intermittent specialty items + noise) for healthcare-realistic synthetic data.
- IAM permissions list includes the right action set (`sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `states:StartExecution`, `dynamodb:BatchWriteItem`, `kms:Decrypt`).
- Pandemic-and-disaster-demand regime-break handling correctly elevated as a security-and-correctness concern in addition to a forecasting concern: "Including the surge period in training data trains your model to over-buy. Excluding it without explicit handling means you have a gap in the data."

#### Finding S1: Customer-Managed KMS Keys Per Data Class Not Specified

- **Severity:** HIGH
- **Expert:** Security (key custody, blast-radius containment, regulatory)
- **Location:** Prerequisites Encryption row: "S3: SSE-KMS; DynamoDB: encryption at rest enabled (default); SageMaker training and inference: encrypted EBS volumes, KMS-encrypted output; CloudWatch log groups: configure KMS encryption explicitly."
- **Problem:** The encryption row says SSE-KMS for S3 but does not specify customer-managed keys versus AWS-managed keys, and does not differentiate keys per data class. A single AWS-managed key for the consumption-history bucket, the model-artifacts bucket, the forecasts bucket, the DynamoDB serving table, the SageMaker training output, and the CloudWatch logs creates a blast-radius problem: a single compromised IAM principal that has `kms:Decrypt` on the shared key gets every data class. The chapter pattern (and the chapter 5 / 11 reviews to the extent they apply here) consistently elevates customer-managed keys per data class. For this recipe specifically, the data classes are: (a) consumption-history with per-case linkage (PHI by association), (b) SKU master data (operational, low sensitivity), (c) model artifacts (no PHI but high integrity-and-availability concern; a tampered model produces wrong reorder points), (d) forecasts and reorder points (operational, no direct PHI but downstream-sensitive), (e) DynamoDB serving table (operational), (f) CloudWatch logs (may contain payload fragments).
- **Fix:** Update the Encryption row to specify customer-managed keys (CMKs) per data class:
  > "All buckets, tables, and log groups: SSE-KMS with customer-managed KMS keys. Separate CMKs per data class for blast-radius containment: a CMK for the consumption-history-and-SKU-master bucket (PHI-by-association posture), a CMK for the model-artifacts bucket, a CMK for the forecasts bucket and the DynamoDB serving table, a CMK for the SageMaker training output, a CMK for CloudWatch log groups. Key policies grant decrypt only to the IAM principals that have a need-to-know for each data class. Bedrock and SageMaker model-invocation logging (where enabled) routes to a destination encrypted to the same standard."

  Add to the IAM permissions row: "Per-Lambda least-privilege execution roles. The reorder-point Lambda has `kms:Decrypt` on only the forecasts-and-DynamoDB CMK. The training-job role has `kms:Decrypt` on the consumption-history CMK and `kms:Encrypt` on the model-artifacts CMK. The Glue ETL role has `kms:Decrypt` on the consumption-history CMK and `kms:Encrypt` on the same CMK for the cleaned output. Cross-class permissions are not granted at the IAM-policy level."

#### Finding S2: CloudTrail Data Events Not Specified

- **Severity:** MEDIUM
- **Expert:** Security (audit trail, forensic reconstruction)
- **Location:** Prerequisites CloudTrail row: "Enabled: log all SageMaker, S3, DynamoDB, and Glue API calls for HIPAA audit trail."
- **Problem:** "Log all SageMaker, S3, DynamoDB, and Glue API calls" reads as management-event coverage but does not specify CloudTrail data events on the S3 buckets, the DynamoDB tables, or the KMS keys. CloudTrail data events are required to reconstruct who-read-what-when on PHI-bearing buckets and tables; management-events alone log the bucket and table creation but not the GetObject and GetItem calls.
- **Fix:** Update the CloudTrail row: "Enabled at the account level. Data events enabled on the consumption-history S3 bucket, the SKU-master S3 bucket, the model-artifacts S3 bucket, the forecasts S3 bucket, the DynamoDB serving table, and the customer-managed KMS keys. Management events for SageMaker, Glue, Step Functions, EventBridge, and Lambda. CloudTrail logs in a dedicated S3 bucket with Object Lock in compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days."

#### Finding S3: BAA Framing Hedged Beyond What the Chapter Pattern Warrants

- **Severity:** LOW
- **Expert:** Security (regulatory)
- **Location:** Prerequisites BAA row: "AWS BAA signed if consumption data is linked to specific patients or procedures (it usually is at the case level, even when aggregated to daily SKU counts; PHI considerations are conservative)."
- **Problem:** The hedge ("if consumption data is linked to specific patients or procedures") is technically correct but operationally rare; aggregate-SKU-count data without any case-level or patient-level linkage is unusual in production hospital materials-management systems. The recipe's later prose in the architecture acknowledges this. Cookbook hygiene from chapter 11 is to default to BAA-required and hedge in the negative case, not the reverse.
- **Fix:** Reframe to the affirmative default: "AWS BAA signed. Hospital consumption data typically carries case-level linkage even when aggregated to daily SKU counts, and PHI-by-association applies; default to BAA coverage. Pure aggregate-SKU-count data with no case-level, patient-level, or procedure-level linkage may fall outside BAA scope, but production systems rarely operate at that level of disconnection."

---

### Architecture Expert Review

#### What's Done Well

- The five-stage architecture (consumption history -> feature engineering and SKU segmentation -> per-segment model training -> forecast and reorder-point calculation -> materials management / ERP integration) is the correct shape for a multi-thousand-SKU forecasting problem.
- The Step Functions Map state for parallel per-segment training is the architecturally-correct fan-out pattern. The walkthrough's Step 3 correctly notes the wall-clock-time benefit ("keeps wall-clock time manageable even on a multi-thousand-SKU portfolio").
- The SKU segmentation as a routing primitive (smooth -> Prophet; intermittent -> SBA; erratic -> Croston; lumpy -> hierarchical at category level; procedure-driven -> two-stage case-forecast-times-usage; deepar_pool -> optional shared model) is the right architectural shape and correctly avoids the "one-size-fits-all" anti-pattern.
- The forecast-quality gate in Step 3 ("Reject the new model if it materially regresses against the current production model for this segment ... error > current_production_model[segment].error * 1.20") is the correct shape for a quality-gate primitive. The 20% regression threshold is a reasonable default for a Simple/MVP recipe.
- The DynamoDB access pattern is correctly factored: partition key `facility_id#sku_id` for efficient single-SKU queries, sort key `generated_at` for time-series of forecasts, optional `CURRENT` sort-key value for single-GetItem latest-forecast retrieval.
- The procedure-driven branch correctly notes the architectural dependency: "It's to forecast case volume by procedure type and apply a usage-per-case multiplier. This is more stable and easier to explain to operations." The cross-recipe link to 12.1 (case forecasts) and 7.1 (no-show adjusted case forecasts) is the right architectural decomposition.
- The "Why This Isn't Production-Ready" section correctly surfaces six structural production gaps (SKU master data quality, cold-start handling for new SKUs, demand regime breaks, forecast monitoring and drift detection, service-level differentiation by clinical importance, idempotency and audit trail). Each is operationally accurate and would be a HIGH or MEDIUM finding if not surfaced; the recipe correctly elevates them as known scope-cuts.
- The variations section (hierarchical forecasting with MinT reconciliation; probabilistic ordering with newsvendor logic for short-shelf-life items; multi-facility pooling and substitution; OR-schedule-as-input for procedure-driven SKUs) is well-scoped and frames each extension at the right grain.

#### Finding A1: Step Functions Map State Lacks Retry, DLQ, and Partial-Failure Semantics

- **Severity:** HIGH
- **Expert:** Architecture (orchestration, error handling, distributed systems)
- **Location:** Architecture Diagram Mermaid block: `D -->|Per-Segment Jobs| F[SageMaker Training Jobs]`. Step 3 pseudocode `train_segment_model` returns `model, error, sigma` or alerts on quality-gate failure but does not specify Map-state error handling. The "Step Functions for orchestration" paragraph in "Why These Services" mentions "explicit retry logic, parallel execution via the Map state for per-segment training, and visibility into each step" but the diagram and pseudocode do not specify retry counts, backoff, DLQ routing, or per-iteration failure-tolerance.
- **Problem:** A Step Functions Map state with N segments fans out N parallel SageMaker training jobs. Without explicit retry policy and error-handling, the failure modes are: (a) a SageMaker training job fails on a transient infrastructure issue and the Map iteration fails, propagating the failure to the parent state and aborting the entire pipeline (catastrophic for a 5,000-SKU run where 1 of 5 segments failed); (b) a SageMaker training job runs longer than the Map state's per-iteration timeout and gets cancelled mid-run; (c) a SageMaker training job produces a model that fails the quality gate in Step 3, but the rejection logic ("REJECT this model; alert the ML engineer") does not specify whether the rejection blocks the pipeline or allows it to continue with the prior production model; (d) a partial failure where 4 of 5 segments train successfully and 1 fails leaves the pipeline in an ambiguous state where the forecasts-and-reorder-points step in Step 4 could be invoked with a stale model for the failed segment without explicit signaling. The recipe's prose claims "explicit retry logic" but the architecture text and pseudocode do not specify it.
- **Fix:** Add explicit retry, error-catch, and partial-failure semantics to the Map state. Specifically:
  1. **Per-iteration retry policy.** Each Map iteration retries on `States.TaskFailed` and `SageMaker.SageMakerException` up to 3 times with exponential backoff (initial 60s, multiplier 2.0, max 600s).
  2. **Catch-and-route on persistent failure.** After retries are exhausted, the iteration catches into a fail-soft state that emits a CloudWatch metric (`segment_training_failed`), logs the failure to a CloudWatch Logs group with the segment label and the SageMaker job name, and routes the segment-failure record to an SQS DLQ for the ML engineer to inspect.
  3. **Map-state tolerated-failure-percentage.** Configure `ToleratedFailurePercentage` (or `ToleratedFailureCount`) so that a small number of segment failures does not abort the pipeline. The pipeline continues with the failed segments using their prior production models, and the downstream Step 4 reorder-point Lambda is signaled which segments are stale.
  4. **Quality-gate rejection routing.** When `train_segment_model` rejects a model on the quality-gate threshold, the rejection emits a CloudWatch metric, routes the segment to use the prior production model, and emits an SNS notification to the ML engineer for review. The rejection does not abort the pipeline.
  5. **Pipeline-level partial-failure indicator.** The Step Functions state machine's terminal output includes a `partial_failure: true/false` flag and a list of `failed_segments`. The downstream Step 4 reorder-point Lambda reads this flag and stamps the DynamoDB records with `model_freshness: "current"` or `"stale"` so operational consumers can distinguish.

  Add this to the architecture diagram explicitly: a DLQ box (SQS) wired from the Map state's catch path, an SNS topic for the ML engineer alerts, and a CloudWatch alarm on the `segment_training_failed` metric.

#### Finding A2: Reorder-Point Lambda Scalability Not Specified for Multi-Thousand-SKU Portfolios

- **Severity:** MEDIUM
- **Expert:** Architecture (compute boundaries, scalability)
- **Location:** Architecture Diagram: `I -->|Lambda<br/>Reorder Calc| J[DynamoDB<br/>sku-forecasts]`. Step 4 pseudocode `generate_sku_forecasts_and_reorder_points(models, skus, sku_metadata)` and Step 5 pseudocode `load_forecasts_to_dynamodb(forecast_records, table_name)`.
- **Problem:** A 5,000-SKU facility produces 5,000 forecast records that must be loaded into DynamoDB via 200 BatchWriteItem calls (25 items per call), plus 5,000 model.predict invocations (or equivalent inference calls), plus 5,000 reorder-point calculations. A naive single-Lambda implementation runs into the 15-minute Lambda timeout boundary at the high end of the 30-90 minute pipeline runtime range cited in Expected Results, and the network round-trips to DynamoDB compound. The architecture does not specify the chunking strategy: per-segment Lambda fan-out (each segment's reorder calculation runs in its own Lambda invocation), per-facility Lambda fan-out (each facility's reorder calculation runs in its own Lambda invocation), or a longer-running compute (Step Functions parallel state with per-segment Lambda; or a SageMaker Processing Job for the reorder calculation; or a Glue Python Shell job).
- **Fix:** Specify the chunking strategy explicitly. Recommended: a Step Functions parallel state with one Lambda invocation per segment, where each Lambda invocation handles 100-500 SKUs per segment with explicit pagination, BatchWriteItem chunking with retry on `UnprocessedItems`, and per-Lambda timeout headroom (10-minute Lambda invocations with 15-minute timeout). Add to the diagram: "Reorder Calc" decomposed into per-segment Lambda invocations under a parallel state.

#### Finding A3: Cold-Start Handling for New SKUs Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (operational discipline)
- **Location:** "Why This Isn't Production-Ready" section, "Cold-start handling for new SKUs" paragraph: "A new SKU enters the catalog with no history. Per-SKU models have nothing to fit. Production options include: (1) borrow demand from the predecessor SKU using the master data successor map; (2) borrow from a similar SKU using item-category clustering; (3) carry a configured starting reorder point until enough history accumulates (usually three months). Pick one and implement it; do not let the pipeline silently emit zeros."
- **Problem:** The cold-start handling is correctly elevated as a production gap but is not architecturally specified. The downstream consequence is sharp: a pipeline that silently emits zero forecasts for new SKUs produces zero reorder points and triggers immediate stockouts on the items the materials manager just added to the catalog. The recipe correctly diagnoses the failure mode in prose; the architecture should specify the lookup-and-fallback discipline at the architectural level so a TechWriter or implementer does not skip it.
- **Fix:** Add a "Cold-Start-Handling for New SKUs" architectural primitive to the General Architecture Pattern with named ownership: the segmentation step (Step 2) detects new SKUs (count of historical observations below a threshold, e.g., 30 days), routes them to a `cold_start` segment with explicit lookup discipline (predecessor-from-master-data first, similar-SKU-from-category-clustering second, configured-default third), stamps the DynamoDB record with `cold_start_strategy: "predecessor" | "similar" | "default"` and `cold_start_until_date`, and emits a CloudWatch metric `sku_in_cold_start` per facility per segment so the ML engineer can monitor the cold-start volume.

#### Finding A4: Forecast Monitoring and Drift Detection Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (operational discipline, model lifecycle)
- **Location:** "Why This Isn't Production-Ready" section, "Forecast monitoring and drift detection" paragraph: "Track per-SKU forecast error against actuals on a rolling basis. Alert when error exceeds tolerance for two consecutive cycles for high-value SKUs."
- **Problem:** Forecast monitoring is correctly elevated as a production concern but is not architecturally specified. The recipe's quality-gate in Step 3 ("REJECT this model if error > current_production_model.error * 1.20") is a release-gate, not a runtime drift detector. A model that passed the release gate but degrades over four weeks of actuals will not be caught by the release gate; it will only be caught by a runtime drift detector that compares each cycle's forecast against the next cycle's actuals.
- **Fix:** Add a "Drift Detection" architectural primitive: a separate Lambda (or Step Functions step) that runs after each cycle's actuals are available, joins the prior cycle's forecasts against the current cycle's consumption, computes per-SKU and per-segment forecast error, writes the metrics to CloudWatch with dimensions `(facility, segment, sku_value_tier)`, and alerts on two-consecutive-cycle threshold breaches for high-value SKUs. The drift-detection Lambda is invoked from EventBridge on a separate schedule from the forecast pipeline (typically a few days after the forecast is consumed).

#### Finding A5: DynamoDB Write Idempotency and Conditional-Write Semantics Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (idempotency, rerun safety)
- **Location:** Step 5 pseudocode `load_forecasts_to_dynamodb(forecast_records, table_name)`: "Each item is keyed by (facility_id + '#' + sku_id, generated_at) so the latest forecast supersedes prior versions ... upsert 'CURRENT' record per (facility_id, sku_id) pointing to latest forecast."
- **Problem:** The recipe's Why-This-Isn't-Production-Ready section correctly elevates "Idempotency, audit trail, and rerun safety" as a production concern. The pseudocode in Step 5 says "BatchWriteItem ... if batch had unprocessed items: retry unprocessed items with exponential backoff" but does not specify (a) the idempotency key for the BatchWriteItem retry (since BatchWriteItem is not transactional, a partial-success-then-retry can produce duplicates with different `generated_at` timestamps if the timestamp is computed inside the Lambda); (b) the conditional-write semantics on the `CURRENT` record (a stale upsert that overwrites a newer `CURRENT` is a regression; a `ConditionExpression` on `attribute_not_exists(generated_at) OR generated_at < :new_generated_at` prevents this); (c) the at-least-once delivery contract from EventBridge that the pipeline trigger relies on (a pipeline that runs twice on the same week's data should produce idempotent writes, not double writes).
- **Fix:** Specify the idempotency contract in Step 5:
  - The `generated_at` timestamp is computed once at the pipeline-start step and propagated through the Step Functions state, not recomputed per Lambda invocation. Reruns of the same pipeline with the same `pipeline_run_id` produce the same `generated_at`.
  - The `CURRENT` upsert uses a conditional write: `ConditionExpression: attribute_not_exists(generated_at) OR generated_at < :new_generated_at`.
  - The pipeline trigger from EventBridge uses a `pipeline_run_id` derived from the schedule's invocation ID so that at-least-once trigger delivery produces idempotent pipeline runs.
  - The BatchWriteItem retry on `UnprocessedItems` is bounded (e.g., 5 retries with exponential backoff) and surfaces a metric on the count of unprocessed items.

---

### Networking Expert Review

#### What's Done Well

- VPC enforcement framed correctly: "Production: SageMaker training and inference jobs in VPC with VPC endpoints for S3, CloudWatch Logs, and KMS. Required for HIPAA workloads."
- The recipe correctly identifies that the materials-management-and-ERP integration is "rarely a one-shot DynamoDB write; it's typically a flat-file extract or an API call into the ERP that runs on its own cadence and reconciles." This frames the integration networking surface honestly.

#### Finding N1: VPC Endpoint Enumeration Incomplete and Endpoint-Type Not Distinguished

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites VPC row: "SageMaker training and inference jobs in VPC with VPC endpoints for S3, CloudWatch Logs, and KMS."
- **Problem:** The list omits VPC endpoints for SageMaker (API and Runtime), DynamoDB, Step Functions, EventBridge, Glue, Lambda, and Secrets Manager (where used for the ERP integration credentials). It also does not distinguish gateway endpoints (S3 and DynamoDB; free) from interface endpoints (everything else; per-AZ-per-endpoint pricing). A reader copying the list creates only the three named endpoints and discovers at deploy time that SageMaker training jobs cannot pull container images, that the reorder-point Lambda cannot reach DynamoDB without a NAT or a gateway endpoint, and that Step Functions cannot start training jobs without a SageMaker API endpoint.
- **Fix:** Update the VPC row to enumerate the full set with endpoint type:
  > "Production: All compute (SageMaker training, SageMaker inference, Lambda, Glue) deployed inside a VPC with no internet egress for PHI-bearing paths. Gateway endpoints for S3 and DynamoDB (free, no per-AZ cost). Interface endpoints (per-AZ-per-endpoint cost) for SageMaker (API), SageMaker (Runtime), Step Functions, EventBridge, Glue, Lambda, KMS, CloudWatch Logs, CloudWatch Monitoring, and Secrets Manager (if used for the ERP integration credentials). Required for HIPAA workloads."

#### Finding N2: TLS Minimum Version and ERP Integration Egress Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row and the "Materials Management / ERP Integration" paragraph in "Why These Services."
- **Problem:** The recipe does not specify TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary, and does not specify the egress path for the ERP integration (whether through a VPC NAT gateway, a private connection to an on-premises ERP, a partner-VPC peering connection, or a PrivateLink endpoint to the ERP vendor's hosted offering).
- **Fix:** Add a sentence to the VPC row: "TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary." Add a sentence to the ERP-integration paragraph: "The ERP-integration egress path depends on the deployment posture: an on-premises ERP via a Direct Connect link or VPN with the ERP-integration Lambda in the VPC; a hosted ERP via a PrivateLink endpoint where the vendor offers one; a public-internet API call only when the alternatives are not available, in which case egress traffic is routed through a NAT gateway with logging and the API call uses TLS 1.2-or-higher with mutual-TLS or signed-JWT authentication."

---

### Voice Reviewer (STYLE-GUIDE.md, RECIPE-GUIDE.md)

**Em dash count: 0** (verified by U+2014 codepoint scan).
**En dash count: 11** (used appropriately in numeric ranges like "$100-$400 per month" and "30-60% reduction"; en dashes are not forbidden by STYLE-GUIDE.md, only em dashes).
**TODO-verify markers: 6** (N1, V1, N2, N3, A1, N4). All are appropriately scoped to verifiable factual claims (Amazon Forecast deprecation status, AWS pricing, accuracy and operational benchmarks, external-link liveness, pre-publication audit). These are author hedges, not blocking issues.

**Voice consistency:** The Tuesday-afternoon vignette earns its position at exactly the right "this is what hospital materials management actually looks like in production" register. The "Hospital supply chain spend is typically the second-largest expense category after labor, and a meaningful fraction of it is wasted on either too much inventory or too little" framing is the recipe's clearest operational stake-setting. The Honest Take's four observations land cleanly in CC's voice: "the model selection question gets way more attention than it deserves"; "the value isn't in the forecast itself, it's in the reorder point updates"; "intermittent demand is genuinely harder than the smooth case"; "the prediction interval, not the point estimate, is the operational primitive."

**Vendor-balance (70/30):** Maintained. The Problem and Technology sections are 100% vendor-agnostic. The General Architecture Pattern is vendor-agnostic. AWS service names appear first in "The AWS Implementation" section as expected. The 30% AWS-specific content covers the implementation in appropriate depth without becoming a service-name-soup.

**Healthcare-domain accuracy:** High. Croston's method and the Syntetos-Boylan Approximation (SBA) are correctly described. Teunter-Syntetos-Babai (TSB) for obsolescence is correctly named. The four-corner ADI/CV-squared classification is the standard textbook segmentation (Syntetos et al.). Prophet, ETS, ARIMA, SARIMA, and DeepAR are correctly framed for their respective use cases. The reorder-point and safety-stock formula is the standard textbook form. The 1.65-for-95%-and-2.33-for-99% z-scores are correct for one-sided service-level convention. The "GMDN families" reference (Global Medical Device Nomenclature) is technically accurate. The "GHX or Workday item catalog" reference is current as of mid-2024 (GHX is the dominant healthcare supply-chain GPO data exchange).

#### Finding V1: TODO-Verify Markers Should Be Tracked Through Publication

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Inline `<!-- TODO (TechWriter): ... -->` comments at N1 (Amazon Forecast deprecation status), V1 (SageMaker / Glue / DynamoDB pricing), N2 (sample-repo links), N3 (Python companion existence), A1 (accuracy and operational benchmarks), N4 (external-link audit).
- **Problem:** Six TODO-verify markers should be resolved (or accepted-as-hedge with reviewer signoff) during the TechEditor pass. They are appropriate hedges for the draft stage but should not survive into publication.
- **Fix:** During the TechEditor pass, resolve each TODO by verifying the underlying claim, removing the TODO, and either confirming the prose or updating it. The pricing claim (V1) and the external-link audit (N4) are the most likely to need updates given the natural drift of AWS pricing pages and link targets.

#### Finding V2: Architecture Diagram Cost-and-Cardinality Annotations Missing

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Architecture Diagram Mermaid block, "Cost Estimate" row in Prerequisites, "Cost per facility per month" row in Expected Results.
- **Problem:** The cost estimate ($100-$400/month) is presented as a flat range without decomposition by SKU count, which the recipe's own framing identifies as the dominant cost driver ("dominated by SageMaker compute and SKU count"). A reader scoping a 50,000-SKU health-system implementation needs to know that the cost scales with SKU count, not facility count.
- **Fix:** Add to the cost estimate: "Per-facility cost scales with SKU count and forecast cadence. The $100-$400/month range assumes 5,000-15,000 SKUs and a weekly forecast cadence. A 50,000-SKU health-system implementation across multiple facilities scales the SageMaker training cost approximately linearly with SKU count if per-segment training is decomposed by facility, or sublinearly with SKU count if a shared DeepAR model is used across facilities."

---

## Stage 2: Expert Discussion

The four reviewers do not have conflicting findings. The Security and Architecture experts overlap on the customer-managed KMS keys per data class (Finding S1) and the partial-failure semantics in the Step Functions Map state (Finding A1) which both touch on the audit-trail integrity contract. The Networking expert's VPC-endpoint enumeration (Finding N1) intersects with the Architecture expert's reorder-point Lambda scalability (Finding A2) since the Lambda's network path to DynamoDB is the gating constraint at scale. The Voice reviewer's findings are independent and editorial.

**Priority ordering:** S1 (customer-managed KMS keys per data class) before A1 (Step Functions partial-failure semantics) only because the encryption posture is the regulatory baseline that must be correct on day one; the Step Functions partial-failure behavior is correctable in production with operational discipline. The remaining MEDIUM findings cluster around production-readiness gaps that the recipe correctly elevates in "Why This Isn't Production-Ready" but does not architecturally specify; the chapter editor should consider promoting those gaps from production-gaps prose to architectural primitives in the General Architecture Pattern as the chapter pattern matures.

**Chapter-pattern consolidation note:** Recipe 12.2 is the second recipe in Chapter 12 and the first to be expert-reviewed (Recipe 12.1's expert review has not yet been written per the iter-433 / iter-435 / iter-443 editor notes in the 12.1 file). The chapter editor should plan for the customer-managed-KMS-keys-per-data-class pattern, the Step-Functions-Map-state-with-DLQ pattern, and the cold-start-handling-for-new-time-series pattern to be consolidated across the chapter rather than restated per recipe. The chapter-9 (Computer Vision) and chapter-11 (Conversational AI) reviews demonstrate the consolidation discipline the editor should apply here.

---

## Stage 3: Synthesized Feedback

### CRITICAL Findings

**(None.)**

### HIGH Findings

**H1. Customer-managed KMS keys per data class not specified.** (Security) Prerequisites Encryption row says "SSE-KMS" without naming customer-managed keys per data class. **Fix:** Specify CMKs per data class (consumption-history, model-artifacts, forecasts, DynamoDB, SageMaker output, CloudWatch logs) with key-policy scoping per IAM principal. See Finding S1.

**H2. Step Functions Map state lacks retry, DLQ, and partial-failure semantics.** (Architecture) The fan-out for per-segment SageMaker training jobs does not specify retry policy, dead-letter routing, tolerated-failure-count, quality-gate-rejection routing, or partial-failure indicator propagation to the downstream reorder-point step. **Fix:** Specify per-iteration retry, catch-and-DLQ on persistent failure, ToleratedFailurePercentage, quality-gate rejection routing to SNS, and a `partial_failure: true/false` flag on the pipeline output. See Finding A1.

### MEDIUM Findings

**M1. CloudTrail data events not specified on PHI-bearing buckets, tables, and KMS keys.** (Security, Finding S2) **Fix:** Update CloudTrail row to enumerate data events on consumption-history, SKU-master, model-artifacts, forecasts S3 buckets, the DynamoDB serving table, and customer-managed KMS keys.

**M2. Reorder-point Lambda scalability not specified for multi-thousand-SKU portfolios.** (Architecture, Finding A2) **Fix:** Specify per-segment Lambda fan-out under a Step Functions parallel state with bounded SKU counts per invocation.

**M3. Cold-start handling for new SKUs architecturally implicit despite explicit prose elevation.** (Architecture, Finding A3) **Fix:** Add a `cold_start` segment to Step 2 with named lookup discipline (predecessor-from-master-data, similar-SKU-from-category-clustering, configured-default).

**M4. Forecast monitoring and drift detection architecturally implicit.** (Architecture, Finding A4) **Fix:** Add a separate drift-detection Lambda invoked from EventBridge after each cycle's actuals are available, with per-SKU and per-segment error metrics in CloudWatch.

**M5. DynamoDB write idempotency and conditional-write semantics not specified.** (Architecture, Finding A5) **Fix:** Specify the `pipeline_run_id`-derived `generated_at`, the conditional-write `ConditionExpression` on the `CURRENT` record, and the bounded-retry-with-metric on BatchWriteItem `UnprocessedItems`.

**M6. VPC endpoint enumeration incomplete and endpoint-type not distinguished.** (Networking, Finding N1) **Fix:** Enumerate the full endpoint set (gateway: S3, DynamoDB; interface: SageMaker API, SageMaker Runtime, Step Functions, EventBridge, Glue, Lambda, KMS, CloudWatch Logs, CloudWatch Monitoring, Secrets Manager).

### LOW Findings

**L1. BAA framing more hedged than chapter pattern warrants.** (Security, Finding S3) **Fix:** Reframe to BAA-required-by-default with a hedge in the negative case.

**L2. TLS minimum version and ERP integration egress not specified.** (Networking, Finding N2) **Fix:** Specify TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary and the ERP-integration egress path options.

**L3. TODO-verify markers should be tracked through publication.** (Voice, Finding V1) Six TODO markers (N1, V1, N2, N3, A1, N4) are appropriate draft hedges; resolve during the TechEditor pass.

**L4. Architecture diagram and cost estimate lack cardinality annotations.** (Voice, Finding V2) **Fix:** Decompose the $100-$400/month cost estimate by SKU count and clarify how the cost scales for multi-facility health-system deployments.

---

## Summary Table

| Severity | Count | Action |
|----------|-------|--------|
| CRITICAL | 0     | None. |
| HIGH     | 2     | Customer-managed KMS keys per data class; Step Functions Map-state retry-and-DLQ-and-partial-failure semantics. |
| MEDIUM   | 6     | CloudTrail data events; reorder-point Lambda scalability; cold-start handling; drift detection; idempotency and conditional writes; VPC endpoint enumeration. |
| LOW      | 4     | BAA framing; TLS minimum and ERP egress; TODO marker resolution; cost estimate cardinality. |

**Verdict: PASS** (0 CRITICAL findings; HIGH count of 2 is below the > 3 = FAIL threshold).

---

## Recommended Next Steps

1. TechWriter or TechEditor addresses HIGH findings H1 (customer-managed KMS keys per data class) and H2 (Step Functions Map-state retry-and-DLQ-and-partial-failure semantics) before publication.
2. MEDIUM findings M1 through M6 are correctness-and-discipline gaps that should be addressed before publication; most can be incorporated as architecture-text additions without restructuring the recipe.
3. LOW findings are editorial and can be folded into the TechEditor pass.
4. The chapter editor should plan for chapter-wide consolidation of the customer-managed-KMS-keys-per-data-class pattern, the Step-Functions-Map-state-with-DLQ pattern, and the cold-start-handling-for-new-time-series pattern as more chapter-12 recipes accumulate expert reviews.
5. Recipe 12.2 inherits the forecasting-machinery framing from Recipe 12.1; the chapter editor should ensure that the patterns identified here propagate forward into 12.3 (ED Arrival Forecasting) through 12.10 so that each subsequent recipe builds on a consistent architectural baseline rather than restating the same primitives.
