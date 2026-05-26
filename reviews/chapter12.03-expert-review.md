# Expert Review: Recipe 12.3 - ED Arrival Forecasting

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-25
**Recipe file:** `chapter12.03-ed-arrival-forecasting.md`

---

## Overall Assessment

**Verdict: PASS**

This is the third recipe in Chapter 12 (Time Series Analysis / Forecasting) and the chapter's first true hourly-cadence recipe. It correctly differentiates itself from 12.1 (Appointment Volume Forecasting) and 12.2 (Supply Inventory Forecasting) by putting the recipe-distinct primitives front and center: count data on a fast clock, two-axis forecasting (volume plus ESI acuity mix), multiple simultaneous seasonalities (hourly, daily, weekly, annual), exogenous drivers that genuinely move the needle (weather, flu surveillance, local events), and the dominant operational insight that the upper tail of the prediction interval, not the point estimate, is the operational primitive for staffing decisions.

The opening Wednesday-evening vignette ("17:42 on a Wednesday in February ... thirty-one people in the waiting room ... the on-call attending physician for the surge protocol just declined because they're already on a different shift tomorrow") earns its position. It frames the operational stakes at exactly the right "this is what an actual ED looks like at the end of a bad shift" register, names the specific failure modes that drive forecasting demand (LWBS, door-to-doctor times, boarders, surge plan triggers, per-diem labor spend), and ties them to the exogenous drivers that the model will need to capture. The "130 million ED visits per year, distributed across roughly five thousand EDs" framing is operationally accurate (CDC NHAMCS reports about 130 million annual ED visits in the United States; AHA reports approximately 5,500-6,000 EDs).

The Technology section is the chapter's strongest articulation of why hourly forecasting is qualitatively different from daily forecasting. The four-bullet "Why ED Arrivals Are a Different Beast" framing (count data on a fast clock, acuity mix matters as much as count, genuinely hourly pattern with multiple seasonalities, exogenous drivers actually drive things) ties cleanly to the method-family selection downstream. The three method families (Poisson and negative binomial GLMs with calendar features; classical SARIMA / Holt-Winters / TBATS for multiple seasonalities; modern Prophet / DeepAR / TFT) are correctly named, correctly bounded, and correctly recommended in priority order ("a sensible starting architecture is a Poisson regression with calendar and weather features for volume, plus a separate multinomial classifier for acuity mix"). The two-axis acuity-mix problem is correctly framed as either joint per-ESI-level forecasting or volume-times-mix-classifier; the recommendation to default to the second is operationally sensible for most EDs.

The seven-bullet "Why This Is Harder Than It Looks" enumeration (walkouts and LWBS distortions, diversion events, acuity drift over time, holidays and special events, weather and respiratory virus seasonality, forecast horizon and uncertainty, boarding and downstream coupling) is the recipe's strongest single architectural framing. Each item ties a specific operational concern to a specific architectural primitive (or, in the case of boarding-and-coupling, an explicit cross-recipe dependency on 12.5 Hospital Census Forecasting).

The five-stage architecture (ADT stream -> feature engineering and aggregation -> volume + acuity models -> forecast generation -> ED operational consumers) is the right shape for an hourly forecasting pipeline. The decoupling of hourly inference from weekly retraining is correctly factored. The DynamoDB access pattern (partition key `ed_id`, sort key `forecast_for_hour#generated_at`, optional `CURRENT` record per `(ed_id, forecast_for_hour)`) is operationally correct and matches the chapter pattern established in 12.2. The Mermaid diagram is clean and correctly highlights the dual-pipeline pattern (hourly inference and weekly retraining sharing a SageMaker endpoint).

The Honest Take is publication-ready. The four observations earn the recipe's voice: model-selection-gets-too-much-attention-relative-to-data-plumbing; the-forecast-charge-nurses-actually-want-is-the-staffing-decision-not-the-volume-number; acuity-is-harder-than-volume; concept-drift-is-real-and-faster-than-you-think. The closing observation that "the prediction interval, not the point estimate, is the operational primitive" is consistent with 12.2's framing and continues the chapter's emerging thesis that probabilistic forecasts earn their keep where point forecasts cannot.

That said, two correctness gaps at HIGH severity need attention before publication, and a third is borderline-HIGH that I am routing as HIGH because the hourly cadence amplifies its operational consequences. First, the encryption posture in the Prerequisites table specifies "SSE-KMS" without naming customer-managed keys per data class, exactly as flagged in the 12.2 expert review; the chapter pattern is consolidating around per-class CMKs and 12.3 should adopt the same baseline. Second, the Step Functions orchestration for the hourly inference pipeline does not specify retry policy, dead-letter routing, or partial-failure semantics, and the diagram's `I -->|Errors| Z[CloudWatch Alarms / SNS Topic]` reads as an alarm-only design rather than a retry-and-recovery design; for an hourly cadence where missing forecasts have direct clinical-operational consequences (surge plan blind spots, charge-nurse decisions made on stale data), this needs to be architecturally specified. Third, the late-record / out-of-order-ADT problem is operationally critical at the hourly cadence (a registration that lands in the stream 13 minutes late biases the most-recent-hour count by exactly the lag) and is correctly elevated in "Why This Isn't Production-Ready" but is not architecturally specified; for a forecasting pipeline whose lag features include `lag_1h`, this gap will produce systematically biased recent inputs unless the architecture specifies an explicit watermark and a late-record reconciliation pass.

Six MEDIUM findings cluster on architectural specificity (CloudTrail data events not specified on PHI-bearing buckets and tables; VPC endpoint enumeration incomplete and endpoint-type not distinguished; DynamoDB write idempotency and conditional-write semantics implicit; drift detection and forecast monitoring architecturally implicit; diversion-window and acuity-placeholder reconciliation architecturally implicit; iterated multi-step lag-feature forecasting in Step 4 produces compounding errors not flagged).

Five LOW findings: time-zone and DST handling correctly flagged in pseudocode but not architecturally specified; Bedrock optional explanation step does not call out HIPAA-eligible model selection; cost estimate does not decompose by ED size; weather and surveillance API egress path not specified; the four inline TODO-verify markers (N1, V1, A1, N2, N3, N4) should be tracked through to publication.

Voice is excellent. **Em dash count: 0** (verified by U+2014 codepoint scan). En dash count: 12 (used appropriately in numeric ranges and date ranges; en dashes are not forbidden by STYLE-GUIDE.md). The 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout.

Priority breakdown: 0 CRITICAL, 3 HIGH, 6 MEDIUM, 5 LOW. **Verdict: PASS** because there are 0 CRITICAL findings and HIGH count (3) is at, but not above, the > 3 = FAIL threshold.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review (OWASP, CIS, NIST SP 800-66 for HIPAA)

#### What's Done Well

- **BAA framing is correctly affirmative.** "AWS BAA signed. ADT messages contain PHI directly (patient identifiers, demographics, chief complaints). Even aggregated hourly counts are derived from PHI and should be treated under the BAA." The recipe defaults to BAA-required, matches the chapter pattern that 12.2 was hedging against, and correctly identifies that ADT messages are PHI in the strongest sense (not just PHI-by-association). This is the right baseline.
- **Encryption coverage spans the full data path.** S3 (SSE-KMS), DynamoDB (encryption at rest enabled by default), Kinesis (server-side encryption with KMS), SageMaker training and inference (encrypted EBS volumes, KMS-encrypted output), and CloudWatch log groups (configure KMS encryption explicitly). The explicit elevation of CloudWatch log-group KMS configuration is correct.
- **VPC enforcement framed correctly for production.** "SageMaker training and inference in VPC with VPC endpoints for S3, Kinesis, CloudWatch Logs, and KMS. Required for HIPAA workloads."
- **CloudTrail enabled with correct service enumeration.** "log all SageMaker, S3, DynamoDB, and Kinesis API calls for HIPAA audit trail."
- **Synthetic-data discipline in the Sample Data row.** "Never use real ED arrival data in dev." The MIMIC-IV-ED reference is correctly hedged as "with permission via PhysioNet credentialing" and the synthetic generation suggestion (Poisson with hour-of-day intensity plus weekly seasonality plus weather effects plus noise) is appropriately structured for healthcare-realistic test data.
- **IAM permissions list is accurate for the architecture.** `sagemaker:CreateTrainingJob`, `sagemaker:InvokeEndpoint`, `kinesis:GetRecords`, `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `states:StartExecution`, `dynamodb:BatchWriteItem`, `kms:Decrypt`.

#### Finding S1: Customer-Managed KMS Keys Per Data Class Not Specified

- **Severity:** HIGH
- **Expert:** Security (key custody, blast-radius containment, regulatory)
- **Location:** Prerequisites Encryption row: "S3: SSE-KMS; DynamoDB: encryption at rest enabled (default); Kinesis: server-side encryption with KMS; SageMaker training and inference: encrypted EBS volumes and KMS-encrypted output; CloudWatch log groups: configure KMS encryption explicitly."
- **Problem:** The encryption row says SSE-KMS for S3 and KMS encryption elsewhere but does not specify customer-managed keys versus AWS-managed keys, and does not differentiate keys per data class. A single AWS-managed key for the arrivals-hourly bucket, the weather and flu-index buckets, the events bucket, the forecasts bucket, the DynamoDB serving table, the SageMaker training output, the Kinesis stream, and the CloudWatch logs creates a blast-radius problem: a single compromised IAM principal that has `kms:Decrypt` on the shared key gets every data class. The data classes for this recipe are: (a) raw ADT records and arrivals-hourly aggregates (PHI in the strongest sense per the recipe's own BAA framing), (b) weather and surveillance feeds (operational, no PHI), (c) event calendars (operational, no PHI), (d) model artifacts (no PHI but high integrity-and-availability concern; a tampered model produces wrong forecasts that drive wrong staffing decisions), (e) forecasts (operational, no direct PHI but downstream-sensitive), (f) DynamoDB serving table (operational), (g) CloudWatch logs (may contain payload fragments). This finding mirrors S1 in the 12.2 expert review and is the chapter-wide consolidation pattern.
- **Fix:** Update the Encryption row to specify customer-managed keys (CMKs) per data class:
  > "All buckets, streams, tables, and log groups: SSE-KMS with customer-managed KMS keys. Separate CMKs per data class for blast-radius containment: a CMK for the ADT stream and the arrivals-hourly bucket (PHI), a CMK for the weather, flu-index, and event-calendar buckets (operational, no PHI), a CMK for the model-artifacts bucket, a CMK for the forecasts bucket and the DynamoDB serving table, a CMK for the SageMaker training output, a CMK for CloudWatch log groups. Key policies grant decrypt only to the IAM principals that have a need-to-know for each data class. Bedrock and SageMaker model-invocation logging (where enabled) routes to a destination encrypted to the same standard."

  Add to the IAM permissions row: "Per-Lambda least-privilege execution roles. The DynamoDB-loader Lambda has `kms:Decrypt` on only the forecasts-and-DynamoDB CMK. The training-job role has `kms:Decrypt` on the ADT and arrivals-hourly CMK and `kms:Encrypt` on the model-artifacts CMK. The Glue ETL role has `kms:Decrypt` on the ADT CMK and `kms:Encrypt` on the same CMK for the cleaned hourly output. Cross-class permissions are not granted at the IAM-policy level."

#### Finding S2: CloudTrail Data Events Not Specified on PHI-Bearing Buckets, Tables, and Streams

- **Severity:** MEDIUM
- **Expert:** Security (audit trail, forensic reconstruction)
- **Location:** Prerequisites CloudTrail row: "Enabled: log all SageMaker, S3, DynamoDB, and Kinesis API calls for HIPAA audit trail."
- **Problem:** "Log all SageMaker, S3, DynamoDB, and Kinesis API calls" reads as management-event coverage but does not specify CloudTrail data events on the arrivals-hourly bucket, the DynamoDB serving table, the Kinesis stream, or the customer-managed KMS keys. CloudTrail data events are required to reconstruct who-read-what-when on PHI-bearing buckets, streams, and tables; management-events alone log the bucket and table creation but not the GetObject, GetRecord, and GetItem calls. The hourly inference pipeline reads from the arrivals-hourly bucket every cycle; without data events, a forensic auditor cannot establish what specific arrival data was read by which IAM principal at which time.
- **Fix:** Update the CloudTrail row: "Enabled at the account level. Data events enabled on the arrivals-hourly S3 bucket, the model-artifacts S3 bucket, the forecasts S3 bucket, the DynamoDB serving table, the Kinesis stream, and the customer-managed KMS keys. Management events for SageMaker, Kinesis, Glue, Step Functions, EventBridge, DynamoDB, and Lambda. CloudTrail logs in a dedicated S3 bucket with Object Lock in compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days."

#### Finding S3: Bedrock Optional Explanation Step Does Not Call Out HIPAA-Eligible Model Selection

- **Severity:** LOW
- **Expert:** Security (regulatory, vendor-tier eligibility)
- **Location:** "Amazon Bedrock or AWS Lambda for explanation generation (optional)" paragraph in "Why These Services."
- **Problem:** The explanation prompt as written ("Volume forecast 22% above seasonal baseline; main drivers: cold front arriving 18:00, increased flu surveillance signal in surrounding zip codes, basketball tournament downtown") is operational and contains no PHI in the example. But the practical deployment risk is that prompts include feature contributions that may, at the per-shift granularity for small EDs, indirectly identify cohorts or facilities. Bedrock has model-by-model HIPAA eligibility; the recipe should specify that the chosen Bedrock model is on the HIPAA-eligible list, that the BAA covers Bedrock usage at the account level, and that prompt logging is configured to a HIPAA-aligned destination if any feature inputs to the explainer touch PHI-derived signals.
- **Fix:** Update the Bedrock paragraph: "If using Bedrock, select a HIPAA-eligible foundation model (consult the AWS HIPAA Eligible Services list at deployment time as the eligible model set evolves), confirm BAA coverage at the account level, configure model-invocation logging to a destination encrypted with the model-artifacts CMK, and treat the prompt-construction layer as PHI-adjacent: a feature contribution like 'flu surveillance for zip codes [list]' is a PHI-by-association input even when the resulting one-line explanation does not name a patient."

---

### Architecture Expert Review

#### What's Done Well

- **Five-stage architecture is the right shape.** Stream ingest -> feature engineering and aggregation -> volume and acuity models -> forecast generation -> operational consumers. The decoupling of hourly inference from weekly retraining is correctly factored.
- **Two-track modeling is correctly factored.** Volume model and acuity classifier as separate trained artifacts, atomically deployed behind a single SageMaker endpoint. The pseudocode in Step 3 correctly notes the atomic-deployment intent ("Atomically deploy both models behind a single SageMaker endpoint") and correctly rejects models that regress against the current production model on either axis.
- **DynamoDB access pattern matches the chapter pattern.** Partition key `ed_id`, sort key `forecast_for_hour#generated_at`, optional `CURRENT` record per `(ed_id, forecast_for_hour)`. Operationally correct for low-latency dashboard queries and supports after-action review queries (which the recipe correctly highlights: "an older forecast can still be retrieved by querying the sort key range, which is useful for after-action reviews").
- **Two-axis quality gate in Step 3 is the right shape.** The 20% regression threshold on either MAPE or log loss matches 12.2 and is a reasonable Simple/MVP default.
- **Local-time-zone handling correctly elevated in the pseudocode.** Step 1's comment "Hour boundaries are local time at the ED, not UTC. ED operations are local. Mixing time zones here will produce subtle but real bugs." is the correct framing for a multi-ED health system that crosses time zones.
- **"Why This Isn't Production-Ready" correctly elevates seven structural gaps.** Late-record problem, drift detection, acuity-level timing, diversion-window handling, charge-nurse override and feedback, surge plan trigger logic, coupling to inpatient census, idempotency. Each is operationally accurate.
- **The variations section is well-scoped.** Sub-hourly granularity, coupled ED-and-inpatient forecasting, acuity-specific uncertainty for high-stakes levels, real-time updating with current-shift signals, multi-ED hierarchical forecasting. The cross-recipe links (12.5, 14.2, 7.1, 3.10) are operationally accurate.

#### Finding A1: Step Functions Hourly Inference Pipeline Lacks Retry, DLQ, and Partial-Failure Semantics

- **Severity:** HIGH
- **Expert:** Architecture (orchestration, error handling, distributed systems, clinical-operational impact)
- **Location:** Mermaid diagram: `H[EventBridge Schedule hourly] -->|Trigger| I[Step Functions inference-pipeline]` and `I -->|Errors| Z[CloudWatch Alarms SNS Topic]`. The "AWS Step Functions for orchestration" paragraph in "Why These Services" mentions "explicit retry logic" and "the hourly cycle: aggregate the latest hour, refresh feature data, run inference, write forecasts" but the diagram and pseudocode do not specify retry counts, backoff, DLQ routing, or per-step failure-tolerance.
- **Problem:** A Step Functions hourly inference pipeline with four serial stages (aggregate -> features -> inference -> dynamodb-load) has four independent failure points each cycle. Without explicit retry policy and DLQ routing, the failure modes are: (a) Glue ETL fails on a transient infrastructure issue and the pipeline aborts; the dashboard then shows the previous hour's forecast as the most recent, with no signal that the current hour's forecast did not generate; (b) the SageMaker endpoint returns a 5xx on a transient issue and the entire cycle is lost; (c) the DynamoDB BatchWriteItem fails on a partial-success-then-throttle scenario and a subset of forecast records are written while others are not, leaving the dashboard with mixed staleness across forecast horizons. The hourly cadence and the clinical-operational consequences (surge plan blind spots, charge-nurse decisions made on stale forecast data, missed call-in windows) elevate this above the equivalent finding in 12.2 (where the cadence is weekly and the operational consequences accumulate over days). The diagram's `I -->|Errors| Z[CloudWatch Alarms SNS Topic]` reads as an alarm-only design, which is the wrong response for a clinical-operational system; alerting the on-call engineer at 03:14 that the hourly forecast is missing is a degradation-in-place response, not a recovery response.
- **Fix:** Add explicit retry, error-catch, and partial-failure semantics to each stage of the hourly inference pipeline. Specifically:
  1. **Per-stage retry policy.** Each stage retries on `States.TaskFailed` and equivalent transient-failure exceptions up to 3 times with exponential backoff (initial 30s, multiplier 2.0, max 240s; the budget is constrained by the 60-minute inference-cycle deadline, so retries must complete within roughly 8 minutes of stage budget).
  2. **Catch-and-route on persistent failure.** After retries are exhausted, the stage catches into a fail-soft state that emits a CloudWatch metric (`inference_stage_failed` with stage and ed_id dimensions), logs the failure to a CloudWatch Logs group with the full input payload (PHI scrubbed), and routes the failure record to an SQS DLQ for the on-call engineer to inspect.
  3. **Stale-forecast signaling.** When an hourly cycle fails, the DynamoDB serving table receives an explicit "stale" record for the missed hour with `model_freshness: "stale"` and `last_successful_cycle: <timestamp>` so the dashboard can render the staleness explicitly. This is a clinical-safety primitive: charge nurses must see "this forecast is stale, last refreshed 3 hours ago" rather than implicitly seeing the previous hour's forecast as the current one.
  4. **DynamoDB-load partial-failure recovery.** The BatchWriteItem step retries on `UnprocessedItems` with bounded backoff (5 retries) and surfaces a metric on the count of unprocessed items. Items still unprocessed after retries route to the DLQ for replay.
  5. **Alarm thresholds for clinical-operational risk.** CloudWatch alarms fire on `inference_stage_failed` count > 0 in any 1-hour window (page the on-call) and on consecutive-hourly-failures > 2 (escalate to the medical informatics director).

  Add this to the architecture diagram: a DLQ box (SQS) wired from each stage's catch path, an SNS topic for the on-call alerts and a separate SNS topic for clinical-operational escalation, and the explicit "stale" record write path to DynamoDB.

#### Finding A2: Late-Record / Out-of-Order ADT Watermarking and Reconciliation Architecturally Implicit

- **Severity:** HIGH
- **Expert:** Architecture (data freshness, streaming correctness, forecast bias)
- **Location:** "Why This Isn't Production-Ready" section, "Real-time data freshness and the late-record problem" paragraph: "ADT messages do not always arrive in order. A registration that happened at 14:32 might land in your stream at 14:45 because of EHR queue delays. Hourly aggregation needs an explicit watermark and a late-record reconciliation pass. Without this, the most recent hour's count is always wrong, and the model sees biased recent history."
- **Problem:** The recipe correctly diagnoses the failure mode in prose but does not architecturally specify the watermark or the reconciliation pass. The downstream consequence is sharp at the hourly cadence: the inference pipeline at 14:00 reads the 13:00 hourly count as a `lag_1h` feature, but the 13:00 count is biased low because some 13:42 registrations have not yet arrived in the stream. The 14:00 forecast then under-predicts. By the time the late records arrive and the 13:00 count is corrected, the 14:00 forecast is locked. The bias compounds because `lag_1h`, `lag_24h`, and `lag_168h` all depend on point-in-time accurate hourly counts. Under the described pipeline, the lag features are systematically under-counted near the trailing edge of the data. This is operationally critical at hourly cadence in a way it is not at the weekly cadence of 12.2; for 12.2, late records have a week to settle before the next cycle. At 12.3's hourly cadence, late records arrive after the cycle that consumed them.
- **Fix:** Promote the late-record handling from production-gaps prose to an architectural primitive in the General Architecture Pattern. Specifically:
  1. **Explicit watermark on hourly aggregation.** The Glue (or Spark Streaming) job that aggregates the ADT stream into hourly counts uses an event-time watermark with a configurable lateness tolerance (15 minutes is a reasonable default for EHR queue delays; some EHRs run slower, profile per deployment). The hourly count for hour H is finalized at H+15 minutes, not at H+0.
  2. **Late-record reconciliation pass.** A separate scheduled job (every 4-6 hours is a reasonable cadence) sweeps the prior 24 hours of arrivals data, re-aggregates from the underlying records, and updates the hourly counts where the new aggregate differs from the stored one. The reconciliation writes a delta record with `revision: <integer>` and `previous_value: <count>` for audit-trail integrity.
  3. **Inference uses watermarked data.** The inference pipeline at hour H reads only hourly counts up to H-1 (which has been finalized at the watermark). The current hour H is not used as a `lag` feature for itself; the latest available `lag_1h` at inference time H is the count at H-1, which is fully finalized.
  4. **Backfill of corrected forecasts on reconciliation.** When a reconciled hourly count differs from the originally stored count by more than a configured threshold (e.g., 10% relative change), the inference pipeline backfills the affected forecast records in DynamoDB with the corrected forecast and an audit-trail record. This keeps after-action review queries accurate.
  5. **CloudWatch metric on late-record arrival.** Track `late_records_per_hour` and `reconciliation_delta_distribution` so the data engineer can profile actual EHR queue behavior and tune the watermark lateness tolerance.

#### Finding A3: DynamoDB Write Idempotency and Conditional-Write Semantics Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (idempotency, rerun safety, after-action review correctness)
- **Location:** Step 5 pseudocode `load_forecasts_to_dynamodb(forecast_records, table_name)`: "The latest generated_at for a given (ed_id, forecast_for_hour) wins when the dashboard queries for 'current' forecasts ... write batch to DynamoDB table_name with: partition_key = ed_id, sort_key = forecast_for_hour + '#' + generated_at ... upsert 'CURRENT#<forecast_for_hour>' record per ed_id pointing to latest forecast."
- **Problem:** This finding mirrors A5 in the 12.2 expert review. The pseudocode does not specify: (a) the idempotency key for BatchWriteItem retry on `UnprocessedItems` (since BatchWriteItem is not transactional, a partial-success-then-retry produces duplicates with different `generated_at` timestamps if the timestamp is computed inside the Lambda); (b) the conditional-write semantics on the `CURRENT` record (a stale upsert that overwrites a newer `CURRENT` is a regression and produces a dashboard that briefly shows older forecasts as current); (c) the at-least-once delivery contract from EventBridge that the pipeline trigger relies on (a pipeline that runs twice on the same hour's data should produce idempotent writes, not double writes); (d) what happens when a backfill from the late-record reconciliation pass writes a corrected forecast for a `forecast_for_hour` that already has a `CURRENT` pointer.
- **Fix:** Specify the idempotency contract in Step 5:
  - The `generated_at` timestamp is computed once at the pipeline-start step and propagated through the Step Functions state, not recomputed per Lambda invocation. Reruns of the same pipeline with the same `pipeline_run_id` produce the same `generated_at`.
  - The `CURRENT` upsert uses a conditional write: `ConditionExpression: attribute_not_exists(generated_at) OR generated_at < :new_generated_at`.
  - The pipeline trigger from EventBridge uses a `pipeline_run_id` derived from the schedule's invocation ID so that at-least-once trigger delivery produces idempotent pipeline runs.
  - The BatchWriteItem retry on `UnprocessedItems` is bounded (5 retries with exponential backoff) and surfaces a metric on the count of unprocessed items.
  - Backfill writes from reconciliation use a `revision` attribute and the `CURRENT` conditional write logic still applies; backfills are not allowed to overwrite a newer manual override (if such overrides exist) without explicit operator action.

#### Finding A4: Drift Detection and Forecast Monitoring Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (operational discipline, model lifecycle)
- **Location:** "Why This Isn't Production-Ready" section, "Forecast monitoring and drift detection" paragraph: "Track forecast error against actuals on a rolling basis at each horizon. Alert when MAPE exceeds tolerance for two consecutive cycles. Retrain on a schedule (weekly is the practical default) and on demand when drift is detected."
- **Problem:** Forecast monitoring is correctly elevated as a production concern but is not architecturally specified. Same shape as A4 in the 12.2 review. The recipe's quality-gate in Step 3 ("REJECT if volume_mape > current_volume_mape * 1.20") is a release-gate, not a runtime drift detector. A model that passed the release gate but degrades over four weeks of actuals will not be caught by the release gate; it will only be caught by a runtime drift detector that compares each cycle's forecast against subsequent actuals at each forecast horizon. For a multi-horizon recipe (4-hour, 12-hour, 24-hour, 7-day), drift detection has to be horizon-aware.
- **Fix:** Add a "Drift Detection" architectural primitive: a separate Lambda (or Step Functions step) that runs after each cycle's actuals are available at each horizon, joins the prior cycle's forecasts at that horizon against the actuals, computes per-ED and per-horizon MAPE and per-horizon prediction-interval calibration (coverage rate of the 80% interval), writes the metrics to CloudWatch with dimensions `(ed_id, horizon_hours)`, and alerts on two-consecutive-cycle threshold breaches at any horizon. The drift-detection step is invoked from EventBridge on a separate schedule from the inference pipeline (typically a few hours after the forecast horizon closes).

#### Finding A5: Diversion-Window and Acuity-Placeholder Reconciliation Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (data quality, training-time correctness)
- **Location:** "Why This Isn't Production-Ready" section, "Diversion window handling" and "Acuity-level timing" paragraphs.
- **Problem:** Both gaps are correctly elevated as production concerns but are not architecturally specified. (a) Diversion windows artificially suppress arrival counts; a model trained on diversion-affected history under-predicts true demand. The recipe says "Production systems mark diversion windows in the data and either exclude them or model the effect explicitly" but the architecture does not show where the diversion log is sourced, how it is joined into the feature table, or how the training pipeline treats it. (b) ESI placeholder records bias the most-recent acuity counts; the recipe says "A second-pass reconciliation that updates ESI levels as triage data arrives keeps the historical record clean" but the architecture does not show the second-pass reconciliation step.
- **Fix:** Add two architectural primitives to the General Architecture Pattern:
  1. **Diversion-Log Integration.** A maintained diversion log (often manually entered into the EHR by the charge nurse, sometimes inferred from EMS data) is ingested as a separate feed and joined into the feature table as a per-hour boolean indicator. The training pipeline either excludes diversion-affected hours or includes them with the indicator as a feature; the choice is a configurable option in the recipe with a recommended default (include with indicator for short-history EDs, exclude for high-history EDs).
  2. **ESI-Reconciliation Second Pass.** A scheduled job (every 4-6 hours) sweeps the prior 24 hours of records, identifies records with placeholder `esi_unknown` values, queries the EHR for updated ESI assignments from triage, and updates the per-acuity counts with a `revision` attribute. Same shape as the late-record reconciliation in A2.

#### Finding A6: Iterated Multi-Step Lag-Feature Forecasting Compounds Error

- **Severity:** MEDIUM
- **Expert:** Architecture (forecasting correctness)
- **Location:** Step 4 pseudocode `generate_hourly_forecasts`: "lag features (using actual past values for lags <= h, predicted for lags > h)."
- **Problem:** The pseudocode describes an iterated multi-step forecasting strategy: for forecast horizon h, the `lag_1h` feature for h=2 uses the predicted value at h=1 instead of the actual; for h=3, the `lag_1h` uses the predicted h=2; and so on. Iterated forecasting compounds errors. By h=24, the `lag_1h` feature has been derived from a chain of 23 prior predictions and the prediction interval at h=24 is much wider than a model fit directly to the h=24 horizon would produce. The recipe's accuracy benchmarks ("4-hour MAPE 10-18%, 24-hour MAPE 15-28%") are consistent with iterated forecasting at this horizon range, but the architecture does not flag the alternative: direct multi-step forecasting with a separate model per horizon (or a single multi-output model that emits the full horizon vector at once). DeepAR natively does direct multi-step; Prophet does iterated; Poisson regression with engineered lag features as described does iterated. The choice has measurable accuracy implications and should be architecturally explicit.
- **Fix:** Add a paragraph to "The Methods That Actually Work" or "The General Architecture Pattern" that names the iterated-versus-direct trade-off explicitly: "The lag-feature pseudocode above describes iterated multi-step forecasting, where short-horizon predictions feed long-horizon predictions and errors compound. The alternative is direct multi-step forecasting, where a separate model is fit per horizon (or a single multi-output model emits the full horizon vector at once). DeepAR is direct by construction; Poisson regression with engineered lag features is iterated unless the lag features are restricted to those known at forecast time without recursion. For 4-hour horizons, iterated and direct perform comparably. For 24-hour and 7-day horizons, direct is meaningfully more accurate. Pick one approach explicitly and evaluate per horizon."

---

### Networking Expert Review

#### What's Done Well

- **VPC enforcement framed correctly for production.** "SageMaker training and inference in VPC with VPC endpoints for S3, Kinesis, CloudWatch Logs, and KMS. Required for HIPAA workloads." This is the right baseline framing.
- **The recipe correctly separates real-time ADT ingest from batch external feeds.** Kinesis (or HealthLake) for the streaming ADT path, scheduled API pulls for weather and CDC FluView. The two paths have different egress profiles and the recipe acknowledges this implicitly.

#### Finding N1: VPC Endpoint Enumeration Incomplete and Endpoint-Type Not Distinguished

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites VPC row: "SageMaker training and inference in VPC with VPC endpoints for S3, Kinesis, CloudWatch Logs, and KMS."
- **Problem:** Same shape as N1 in the 12.2 expert review. The list omits VPC endpoints for SageMaker (API and Runtime), DynamoDB, Step Functions, EventBridge, Glue, Lambda, and Secrets Manager (where used for weather-API or EHR-integration credentials). It does not distinguish gateway endpoints (S3 and DynamoDB; free) from interface endpoints (everything else; per-AZ-per-endpoint pricing). A reader copying the list creates only the four named endpoints and discovers at deploy time that the SageMaker training jobs cannot pull container images, that the DynamoDB-loader Lambda cannot reach DynamoDB without a NAT or a gateway endpoint, that Step Functions cannot start training jobs without a SageMaker API endpoint, and that EventBridge Scheduler cannot invoke Step Functions without an EventBridge endpoint.
- **Fix:** Update the VPC row to enumerate the full set with endpoint type:
  > "Production: All compute (SageMaker training, SageMaker inference, Lambda, Glue) deployed inside a VPC with no internet egress for PHI-bearing paths. Gateway endpoints for S3 and DynamoDB (free, no per-AZ cost). Interface endpoints (per-AZ-per-endpoint cost) for SageMaker (API), SageMaker (Runtime), Kinesis Streams, Step Functions, EventBridge, Glue, Lambda, KMS, CloudWatch Logs, CloudWatch Monitoring, and Secrets Manager (if used for weather-API or EHR-integration credentials). Required for HIPAA workloads."

#### Finding N2: Weather, Surveillance, and Event-Calendar API Egress Path Not Specified

- **Severity:** LOW
- **Expert:** Networking (egress posture, vendor data flow)
- **Location:** Mermaid diagram: `W[Weather API] -->|Hourly Pull| D[S3 Bucket weather/]`, `F[CDC FluView / State Surveillance] -->|Daily Pull| E[S3 Bucket flu-index/]`, `EV[Local Events Calendar] -->|Manual / API| G[S3 Bucket events/]`. "Why These Services" does not call out the egress path.
- **Problem:** The weather, surveillance, and event-calendar API pulls are not PHI-bearing in their incoming direction (they pull data into S3) but the outgoing requests can include the facility's IP address, the API key, and (for fine-grained weather) the facility's location coordinates. None of this is PHI but the egress posture should be specified: whether the puller Lambda runs in the VPC and egresses through a NAT gateway with logging, whether the API key is stored in Secrets Manager with rotation, whether TLS 1.2 minimum is enforced. The recipe does not call any of this out.
- **Fix:** Add a paragraph to the AWS Implementation: "External-feed egress: weather-API, CDC FluView, state-surveillance, and event-calendar puller Lambdas run inside the VPC with egress through a NAT gateway in a public subnet. NAT gateway flow logs are enabled. API keys are stored in Secrets Manager and rotated on a schedule (90 days is a reasonable default). All external API calls enforce TLS 1.2 minimum (TLS 1.3 preferred). The puller Lambdas have IAM permissions scoped to write only to the specific destination S3 bucket and prefix per feed."

#### Finding N3: TLS Minimum Version Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Same as N2 in the 12.2 review. The recipe does not specify TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary.
- **Fix:** Add a sentence to the VPC row: "TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary, including the SageMaker endpoint, the DynamoDB query path from the dashboard, and all external-feed puller calls."

---

### Voice Reviewer (STYLE-GUIDE.md, RECIPE-GUIDE.md)

**Em dash count: 0** (verified by U+2014 codepoint scan).
**En dash count: 12** (used appropriately in numeric ranges like "$200-$700/month", "10-18% MAPE", "8 to 25 arrivals per hour", and date ranges; en dashes are not forbidden by STYLE-GUIDE.md, only em dashes).
**TODO-verify markers: 6** (N1 Amazon Forecast deprecation, V1 pricing, N2 sample-repo links, N3 Python companion existence, A1 accuracy benchmarks, N4 external-link audit). All are appropriately scoped to verifiable factual claims; these are author hedges, not blocking issues.

**Voice consistency:** The Wednesday-evening vignette earns its position. The "thirty-one people in the waiting room ... two ambulance bays are full ... the on-call attending physician for the surge protocol just declined because they're already on a different shift tomorrow ... inpatient is at 96% capacity and has been holding the boarders the ED sent up two hours ago" framing is the recipe's clearest operational stake-setting and lands at exactly the "I have lived this exact bad shift" register. The "This scene plays out somewhere in the United States about every fifteen minutes" follow-up correctly sets the scale.

The first-person aside in The Problem ("I've seen them spike above 12% on bad nights") is in CC's voice and earns its place. The "Nobody throws a parade for a 22% reduction in agency staffing spend or a 1.4-minute reduction in median door-to-doctor time, but the chief medical officer notices, the CFO notices, and the patients who would otherwise have left without being seen quietly get the care they came for" closing of The Problem is the recipe's strongest single sentence.

The Honest Take's four observations land cleanly: "the model selection question gets way more attention than it deserves"; "the forecast that the charge nurse actually wants is not the volume forecast. It's the answer to 'do I need to call someone in?'"; "Acuity is harder than volume"; "Concept drift is real and faster than you think." The closing observation that "the prediction interval, not the point estimate, is the operational primitive" is consistent with 12.2's framing and continues the chapter's emerging thesis.

**Vendor-balance (70/30):** Maintained. The Problem and Technology sections are 100% vendor-agnostic. The General Architecture Pattern is vendor-agnostic. AWS service names appear first in "The AWS Implementation" section as expected. The 30% AWS-specific content covers the implementation in appropriate depth without becoming a service-name-soup.

**Healthcare-domain accuracy:** High. The 130-million-ED-visits-per-year and 5,000-EDs framing is correct (CDC NHAMCS reports approximately 130 million annual ED visits; AHA reports approximately 5,500-6,000 EDs in the United States). ESI 1-5 levels and the "level 1 resuscitation, level 5 routine" framing are correct (per AHRQ ESI Implementation Handbook). LWBS rates above 5% being common and spiking above 12% on bad nights is operationally accurate. The "influenza surveillance leads ED visits by about a week" framing is approximately correct (FluView is reported with about a 7-10 day lag and the surveillance signal leads or lags ED visits depending on the wave's phase). The Poisson assumption for hourly arrival counts is the standard textbook framing. The negative binomial as the over-dispersion fallback is the correct extension. The TBATS reference (Hyndman fpp3) is correct. Prophet, DeepAR, and Temporal Fusion Transformer are correctly framed for their respective use cases. MIMIC-IV-ED, CDC FluView, AHRQ ESI Handbook, and Hyndman fpp3 are all real, currently-accessible resources at the cited URLs. The "Boston academic medical center" framing for MIMIC-IV-ED is correct (MIMIC-IV-ED is sourced from BIDMC's emergency department).

**External link verification:** All cited links are real and currently accessible: `physionet.org/content/mimic-iv-ed/`, `cdc.gov/flu/weekly/`, `ahrq.gov/patient-safety/settings/emergency-dept/esi.html`, `otexts.com/fpp3/`, `facebook.github.io/prophet/`, the AWS docs links for SageMaker DeepAR, Kinesis, HealthLake, Step Functions, the SageMaker pricing page, the HIPAA-Eligible Services list, and the Architecting-for-HIPAA whitepaper. The two GitHub references are to the official `amazon-sagemaker-examples` repo, which is verified.

#### Finding V1: TODO-Verify Markers Should Be Tracked Through Publication

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Inline `<!-- TODO (TechWriter): ... -->` comments at N1 (Amazon Forecast deprecation status), V1 (SageMaker / Kinesis / DynamoDB pricing), N2 (sample-repo links), N3 (Python companion existence), A1 (accuracy benchmarks), N4 (external-link audit).
- **Problem:** Six TODO-verify markers should be resolved (or accepted-as-hedge with reviewer signoff) during the TechEditor pass. They are appropriate hedges for the draft stage but should not survive into publication.
- **Fix:** During the TechEditor pass, resolve each TODO by verifying the underlying claim, removing the TODO, and either confirming the prose or updating it. The Python-companion TODO (N3) should be resolved by confirming the companion file is drafted before the recipe is published.

#### Finding V2: Cost Estimate Does Not Decompose by ED Size

- **Severity:** LOW
- **Expert:** Voice (operational specificity)
- **Location:** Prerequisites Cost Estimate row: "Total: $200-$700/month per ED, depending on retraining frequency and inference volume."
- **Problem:** The cost estimate is presented as a flat per-ED range without decomposition by ED size (community ED with 25,000 annual visits versus large urban Level I trauma center with 100,000+ annual visits). The dominant cost driver at the per-ED level is the Kinesis ingest volume (proportional to ADT message rate, which scales with ED visit volume) and, secondarily, the SageMaker inference invocation count (constant per-cycle, but the cycle cadence may vary by ED size). A reader scoping a multi-ED health-system implementation needs to know which factors drive the cost variance.
- **Fix:** Add to the cost estimate: "Per-ED cost scales with annual visit volume and inference cadence. The $200-$700/month range assumes a 30,000-80,000-annual-visit community-to-mid-size ED with hourly inference and weekly retraining. A high-volume Level I trauma center (150,000+ annual visits) with 15-minute-bucket forecasting and continuous retraining can reach $1,500-$3,000/month. Multi-ED health-system deployments amortize the retraining cost across EDs when a single shared model is used (DeepAR pattern), reducing per-ED cost meaningfully at scale."

#### Finding V3: Time-Zone and DST Handling Correctly Flagged in Pseudocode but Not Architecturally Specified

- **Severity:** LOW
- **Expert:** Voice (architectural specificity)
- **Location:** Step 1 pseudocode: "Hour boundaries are local time at the ED, not UTC. ED operations are local. Mixing time zones here will produce subtle but real bugs."
- **Problem:** The pseudocode comment correctly flags the local-time-zone requirement but the architecture does not address daylight-saving-time transitions, which create a duplicated hour in the fall (the 01:00-02:00 hour appears twice on the day DST ends) and a missing hour in the spring (the 02:00-03:00 hour does not exist on the day DST starts). For an hourly aggregation pipeline keyed by `(ed_id, local_hour)`, both produce real bugs: the fall transition produces a key collision, and the spring transition produces a missing key that downstream features may interpret as a zero-arrival hour.
- **Fix:** Add a sentence to the pseudocode comment or to the architecture text: "Use a time-zone-aware library (e.g., `zoneinfo` in Python 3.9+) and key on the UTC instant plus the local-time label (`local_hour_iso` as a string with offset, e.g., `2026-04-15T18:00:00-05:00`); this disambiguates the duplicated fall-transition hour. For the spring-transition missing hour, the aggregator emits a zero-arrival record with an explicit `dst_transition: "spring_forward"` flag that the model can ignore at training time."

---

## Stage 2: Expert Discussion

The four reviewers do not have conflicting findings. The Security and Architecture experts overlap on three patterns: (a) the customer-managed KMS keys per data class (Finding S1) ties to the Step Functions partial-failure recovery (Finding A1) because audit-trail integrity depends on encryption-and-orchestration both being correct; (b) the CloudTrail data events (Finding S2) intersect with the DynamoDB write idempotency (Finding A3) because forensic reconstruction of forecast revisions requires both the data-event log and the revision-attribute history; (c) the late-record reconciliation (Finding A2) and the diversion-window-and-acuity-placeholder reconciliation (Finding A5) are the same architectural shape (a scheduled second-pass that updates a stored value with a `revision` attribute) and should be specified as a single reusable primitive in the chapter pattern. The Networking expert's VPC-endpoint enumeration (Finding N1) is the same finding as N1 in the 12.2 review and should be consolidated at the chapter level. The Voice reviewer's findings are independent and editorial.

**Priority ordering:** S1 (customer-managed KMS keys per data class) before A1 (Step Functions retry / DLQ / partial-failure semantics) before A2 (late-record reconciliation). The encryption posture is the regulatory baseline that must be correct on day one. The Step Functions partial-failure recovery is the operational baseline that must be correct because the hourly cadence amplifies clinical-operational risk; a missed forecast cycle produces a stale dashboard that charge nurses may not recognize as stale. The late-record reconciliation is the data-quality baseline that determines whether the forecast model sees an accurate recent history; without it, the lag features are systematically biased near the trailing edge.

**Chapter-pattern consolidation note:** Recipe 12.3 is the third recipe in Chapter 12 and the second to be expert-reviewed (after 12.2). The same patterns surfaced in 12.2 surface again here, with the addition of two recipe-distinct concerns (late-record handling at hourly cadence; iterated-versus-direct multi-step forecasting). The chapter editor should plan for the customer-managed-KMS-keys-per-data-class pattern, the Step-Functions-pipeline-with-DLQ pattern, the DynamoDB-conditional-write-on-CURRENT-record pattern, the drift-detection pattern, and the late-record-and-reconciliation pattern to be consolidated across the chapter rather than restated per recipe. Specifically, recipes 12.4 (Lab Result Trend Analysis), 12.5 (Hospital Census Forecasting), 12.7 (Vital Sign Trajectory Monitoring), and 12.10 (whatever the closing recipe is) will all hit the same primitives and the chapter editor should plan for a chapter-level "Architectural Primitives" section in the chapter preface or a dedicated cross-reference recipe.

The Honest Take's framing that "the prediction interval, not the point estimate, is the operational primitive" is becoming the chapter's central thesis. The chapter editor should consider lifting this into the chapter preface so 12.4 onward can build on it without restating it.

---

## Stage 3: Synthesized Feedback

### CRITICAL Findings

**(None.)**

### HIGH Findings

**H1. Customer-managed KMS keys per data class not specified.** (Security, Finding S1) Prerequisites Encryption row says "SSE-KMS" without naming customer-managed keys per data class. **Fix:** Specify CMKs per data class (ADT-and-arrivals-hourly, weather-flu-events, model-artifacts, forecasts-and-DynamoDB, SageMaker output, CloudWatch logs) with key-policy scoping per IAM principal. Mirrors H1 in the 12.2 expert review and should be consolidated at the chapter level.

**H2. Step Functions hourly inference pipeline lacks retry, DLQ, and partial-failure semantics.** (Architecture, Finding A1) The hourly inference pipeline has four serial stages each capable of failing transiently; the diagram's `Errors -> CloudWatch Alarms / SNS Topic` is alarm-only, not retry-and-recovery. Missed hourly cycles produce stale dashboards that drive wrong staffing decisions. **Fix:** Specify per-stage retry policy, catch-and-DLQ on persistent failure, explicit `model_freshness: "stale"` signaling on missed cycles, bounded BatchWriteItem `UnprocessedItems` retry, and CloudWatch alarms with clinical-operational escalation thresholds.

**H3. Late-record / out-of-order ADT watermarking and reconciliation architecturally implicit.** (Architecture, Finding A2) The recipe correctly diagnoses the late-record problem in "Why This Isn't Production-Ready" but does not architecturally specify the watermark or the reconciliation pass. At hourly cadence, the lag features (`lag_1h`, `lag_24h`, `lag_168h`) are systematically biased near the trailing edge unless the architecture specifies an explicit watermark. **Fix:** Promote late-record handling from production-gaps prose to an architectural primitive with: (1) explicit event-time watermark with configurable lateness tolerance, (2) scheduled reconciliation pass that re-aggregates and writes delta records with `revision` attribute, (3) inference-uses-watermarked-data discipline, (4) forecast backfill on reconciliation when delta exceeds threshold, (5) CloudWatch metrics on late-record arrival.

### MEDIUM Findings

**M1. CloudTrail data events not specified on PHI-bearing buckets, tables, streams, and KMS keys.** (Security, Finding S2) **Fix:** Update CloudTrail row to enumerate data events on arrivals-hourly, model-artifacts, forecasts S3 buckets, the DynamoDB serving table, the Kinesis stream, and customer-managed KMS keys.

**M2. DynamoDB write idempotency and conditional-write semantics not specified.** (Architecture, Finding A3) **Fix:** Specify the `pipeline_run_id`-derived `generated_at`, the conditional-write `ConditionExpression` on the `CURRENT` record, the bounded-retry-with-metric on BatchWriteItem `UnprocessedItems`, and backfill-from-reconciliation conditional-write rules. Mirrors M5 in the 12.2 expert review.

**M3. Drift detection and forecast monitoring architecturally implicit.** (Architecture, Finding A4) **Fix:** Add a separate horizon-aware drift-detection Lambda invoked from EventBridge after each cycle's actuals are available at each forecast horizon, with per-ED, per-horizon MAPE and prediction-interval-coverage metrics in CloudWatch. Mirrors M4 in the 12.2 expert review.

**M4. Diversion-window and acuity-placeholder reconciliation architecturally implicit.** (Architecture, Finding A5) **Fix:** Add Diversion-Log Integration and ESI-Reconciliation Second Pass as architectural primitives in the General Architecture Pattern. The reconciliation pattern shape matches the late-record reconciliation in H3; consolidate as a single reusable primitive.

**M5. Iterated multi-step lag-feature forecasting compounds error and trade-off is not architecturally explicit.** (Architecture, Finding A6) **Fix:** Add a paragraph to "The Methods That Actually Work" or to the General Architecture Pattern naming the iterated-versus-direct trade-off explicitly and recommending direct multi-step for 24-hour and 7-day horizons.

**M6. VPC endpoint enumeration incomplete and endpoint-type not distinguished.** (Networking, Finding N1) **Fix:** Enumerate the full endpoint set (gateway: S3, DynamoDB; interface: SageMaker API, SageMaker Runtime, Kinesis Streams, Step Functions, EventBridge, Glue, Lambda, KMS, CloudWatch Logs, CloudWatch Monitoring, Secrets Manager). Mirrors M6 in the 12.2 expert review.

### LOW Findings

**L1. Bedrock optional explanation step does not call out HIPAA-eligible model selection.** (Security, Finding S3) **Fix:** Specify HIPAA-eligible model selection, BAA coverage at the account level, model-invocation logging configuration, and PHI-by-association posture for prompt construction.

**L2. Weather, surveillance, and event-calendar API egress path not specified.** (Networking, Finding N2) **Fix:** Add a paragraph specifying VPC-internal puller Lambdas, NAT gateway with flow logs, Secrets Manager for API keys with rotation, TLS 1.2 minimum, and IAM-scoped destinations per feed.

**L3. TLS minimum version not specified at external boundaries.** (Networking, Finding N3) **Fix:** Add TLS 1.2 minimum (TLS 1.3 preferred) to the VPC row.

**L4. TODO-verify markers should be tracked through publication.** (Voice, Finding V1) Six TODO markers (N1, V1, N2, N3, A1, N4) are appropriate draft hedges; resolve during the TechEditor pass.

**L5. Cost estimate does not decompose by ED size.** (Voice, Finding V2) **Fix:** Decompose the $200-$700/month cost estimate by ED annual visit volume and clarify how cost scales for high-volume trauma centers and multi-ED health-system deployments.

**L6. Time-zone and DST handling correctly flagged in pseudocode but not architecturally specified.** (Voice, Finding V3) **Fix:** Specify the UTC-instant-plus-local-label key strategy and the spring-forward / fall-back disambiguation logic.

---

## Summary Table

| Severity | Count | Action |
|----------|-------|--------|
| CRITICAL | 0     | None. |
| HIGH     | 3     | Customer-managed KMS keys per data class; Step Functions hourly-pipeline retry-and-DLQ-and-partial-failure semantics; late-record / out-of-order ADT watermarking and reconciliation. |
| MEDIUM   | 6     | CloudTrail data events; DynamoDB idempotency and conditional writes; drift detection; diversion-window and acuity-placeholder reconciliation; iterated-versus-direct multi-step trade-off; VPC endpoint enumeration. |
| LOW      | 6     | Bedrock HIPAA-eligible model selection; weather and surveillance API egress; TLS minimum; TODO marker resolution; cost estimate cardinality; DST handling. |

**Verdict: PASS** (0 CRITICAL findings; HIGH count of 3 is at, but not above, the > 3 = FAIL threshold).

---

## Recommended Next Steps

1. TechWriter or TechEditor addresses HIGH findings H1 (customer-managed KMS keys per data class), H2 (Step Functions hourly-pipeline retry-and-DLQ-and-partial-failure semantics), and H3 (late-record / out-of-order ADT watermarking and reconciliation) before publication.
2. MEDIUM findings M1 through M6 are correctness-and-discipline gaps that should be addressed before publication; most can be incorporated as architecture-text additions without restructuring the recipe.
3. LOW findings are editorial and can be folded into the TechEditor pass.
4. The chapter editor should plan for chapter-wide consolidation of the customer-managed-KMS-keys-per-data-class pattern, the Step-Functions-pipeline-with-DLQ pattern, the DynamoDB-conditional-write-on-CURRENT-record pattern, the drift-detection pattern, and the late-record-and-reconciliation pattern. These primitives now appear in two consecutive recipes (12.2 and 12.3) and will likely appear in 12.4 onward.
5. The Honest Take's framing that "the prediction interval, not the point estimate, is the operational primitive" should be considered for promotion to the chapter preface so subsequent recipes can build on it without restating.
6. Confirm the Python companion file (`chapter12.03-python-example.md`) is drafted before this recipe is published; the recipe references it explicitly and TODO N3 acknowledges its non-existence in the current branch.
