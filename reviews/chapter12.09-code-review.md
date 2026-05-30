# Code Review: Recipe 12.9 - Epidemic Forecasting

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.09-epidemic-forecasting.md` (main recipe with five-step pseudocode)
- `chapter12.09-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. Two WARNING-level findings (under the FAIL threshold of >3). Several NOTE-level improvements. The five pseudocode steps map cleanly to the Python functions, the Decimal discipline is consistent across every record written to the mock DynamoDB table, S3 keys are constructed without leading slashes, the demo runs end-to-end against in-memory mocks, and the boto3 client/resource constructors and mock signatures align with current AWS SDK conventions. The epidemiological modeling logic (SEIR compartmental, ARIMA statistical baseline, Bayesian state-space nowcast, Vincentized ensemble combination, WIS-weighted calibration) is pedagogically sound and correctly simplified for teaching purposes.

---

## Pseudocode-to-Python Mapping

| Step | Recipe Pseudocode | Python Function | Status |
|------|-------------------|-----------------|--------|
| 1 | `harmonize_surveillance_feed` (geo mapping, time alignment, unit conversion) | `harmonize_surveillance` + per-feed `harmonize_*_record` helpers + `build_signal_panel` | ✓ |
| 2 | `nowcast_current_state` (reverse reporting-delay convolution, multi-signal fusion) | `BayesianStateSpaceNowcaster.fit` + `run_nowcast` | ✓ |
| 3 | `run_model_forecast` (per-model parallel generation) | `SEIRCompartmentalModel.forecast` + `StatisticalARIMABaseline.fit`/`.forecast` + `run_per_model_forecasts` | ✓ |
| 4 | `combine_ensemble` (WIS-weighted Vincentized quantile combination) | `EnsembleCombiner.combine` + `run_ensemble` | ✓ |
| 5 | `validate_and_surface` (calibration check, scenario composition, DynamoDB/registry/EventBridge/CloudWatch delivery) | `compute_holdout_calibration` + `detect_calibration_drift` + `compose_scenario_forecasts` + `deliver_forecast` | ✓ |

The pseudocode's multi-source harmonization (geography mapping, epi-week alignment, unit conversion) is implemented per-feed with explicit helpers. The nowcast's inverse-variance-weighted fusion with reporting-delay correction captures the pseudocode's "reverse the reporting-delay convolution" intent. The per-model fan-out runs sequentially (with a comment noting production uses Step Functions Distributed Map). The Vincentized quantile combination averages quantile values across models weighted by inverse-WIS, matching the pseudocode's specification. The delivery step writes operational summaries to DynamoDB with Decimal-safe values, full bundles to the registry, events to EventBridge, and metrics to CloudWatch.

---

## Findings

### Issue 1 - WARNING: `compose_scenario_forecasts` uses `min()` across all horizons for `peak_p10` which is semantically wrong

**Severity:** WARNING (misleading)
**File:** `chapter12.09-python-example.md`, `compose_scenario_forecasts` function

```python
peak_p10 = min(
    f["quantiles"].get("0.1", 1e9)
    for f in forecast["forecast_quantiles"])
peak_p90 = max(
    f["quantiles"].get("0.9", 0)
    for f in forecast["forecast_quantiles"])
```

The variable is named `peak_p10` and is placed in a list called `peak_incidence_p10_p90`, implying it represents the 10th percentile of the peak incidence. However, `min()` across all horizons' p10 values gives the lowest p10 across all weeks, not the p10 of the peak week. Similarly, `max()` across all horizons' p90 gives the highest p90 across all weeks, not the p90 of the peak week.

The semantically correct approach for "uncertainty around the peak" would be to find the peak week (already identified via `peak_week`) and report that week's p10 and p90. The current implementation produces a wider range than the actual peak-week uncertainty, which could mislead a reader into thinking this is how peak uncertainty is properly computed.

**Fix:** Replace with the peak week's own quantiles:

```python
peak_week_forecast = next(
    (f for f in forecast["forecast_quantiles"]
     if f["quantiles"].get("0.5", 0) == peak_p50), None)
peak_p10 = peak_week_forecast["quantiles"].get("0.1", 0) if peak_week_forecast else 0
peak_p90 = peak_week_forecast["quantiles"].get("0.9", 0) if peak_week_forecast else 0
```

Or rename the variables to `min_p10_across_horizons` and `max_p90_across_horizons` with a comment explaining the intent is to show the full range envelope rather than peak-week uncertainty.

---

### Issue 2 - WARNING: `EventBridge.put_events` `Time` parameter is passed as a `datetime` object but the real boto3 API expects a `datetime` (correct) or string; however the mock's `Entries` parameter name uses positional-style calling that differs from the real API's keyword-only pattern

**Severity:** WARNING (misleading)
**File:** `chapter12.09-python-example.md`, `deliver_forecast` function and `MockEventBus` class

The `deliver_forecast` function calls:

```python
event_bus.put_events(Entries=[{...}])
```

The real `boto3.client('events').put_events()` API uses the parameter name `Entries` (correct). However, the `MockEventBus.put_events` method signature is:

```python
def put_events(self, Entries):
```

This works in Python but teaches a pattern where the mock accepts `Entries` as a positional argument. The real boto3 call is keyword-only. More importantly, the `Time` field in the entry is passed as a `datetime` object. The real EventBridge API accepts `datetime` objects for `Time` (boto3 serializes them), so this is technically correct. However, the mock simply appends the raw entry dict including the `datetime` object without serialization, which means `json.dumps` on the mock's stored events would fail without a `default` handler. This is a minor inconsistency but could confuse a reader who tries to inspect the mock's stored events.

**Fix:** Add a brief comment in the mock noting that production boto3 serializes `Time` automatically, or convert `Time` to ISO string in the mock's `put_events` for consistency with what would land in the actual event bus.

---

### Issue 3 - NOTE: `_epi_week_to_str` uses ISO week which differs from CDC MMWR epi-week convention

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, `_epi_week_to_str` helper

The comment correctly states "The demo uses a simple ISO-week approximation; production uses the official MMWR week computation that handles year-end edge cases." This is honest and appropriate for a teaching example. However, the ISO week starts on Monday while CDC epi-weeks start on Sunday, and the year-end boundary handling differs (ISO week 1 is the week containing the first Thursday of January; MMWR week 1 is the week containing January 4). For the synthetic data in the demo this produces no visible error, but a reader who copies this helper into a real surveillance pipeline will get incorrect epi-week assignments at year boundaries.

**Fix:** The existing comment is sufficient for a teaching example. Consider strengthening it slightly:

```python
# WARNING: ISO weeks start Monday; CDC MMWR epi-weeks start Sunday.
# At year boundaries (late December / early January) this helper
# will assign the wrong week number. Production must use the MMWR
# week algorithm. See CDC's MMWR week definition for the correct
# computation.
```

---

### Issue 4 - NOTE: `StatisticalARIMABaseline.fit` OLS estimator can produce unstable AR coefficients that the stability cap silently corrects

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, `StatisticalARIMABaseline.fit`

```python
# Stability cap to keep the recursion bounded.
phi1 = max(min(phi1, 1.4), -0.5)
phi2 = max(min(phi2, 0.4), -0.5)
```

The cap at `phi1 = 1.4` allows a unit-root or mildly explosive AR(1) coefficient. For a stationary AR(2) process, the stationarity conditions are `phi1 + phi2 < 1`, `phi2 - phi1 < 1`, and `|phi2| < 1`. The cap does not enforce these jointly, so the recursion can still produce exponentially growing forecasts if `phi1 = 1.4` and `phi2 = 0.4` (sum = 1.8 > 1). In the demo's synthetic data this is unlikely to trigger because the outbreak curve is bounded, but a reader who adapts this code to a different dataset could hit explosive forecasts.

**Fix:** Add a comment noting the stationarity conditions and that production uses proper SARIMAX with built-in stationarity enforcement:

```python
# Stability cap. This is a crude bound; the proper stationarity
# conditions for AR(2) are phi1+phi2<1, phi2-phi1<1, |phi2|<1.
# Production statsmodels SARIMAX enforces stationarity via
# parameter transformation during MLE optimization.
```

---

### Issue 5 - NOTE: `compute_holdout_calibration` WIS approximation is simplified but the comment does not flag the simplification

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, `compute_holdout_calibration`

```python
# Approximate WIS contribution: penalty for distance
# outside the 95 interval plus interval width.
width = q975 - q025
if actual < q025:
    wis_total += width + 2 * (q025 - actual) / 0.05
elif actual > q975:
    wis_total += width + 2 * (actual - q975) / 0.05
else:
    wis_total += width
```

The real Weighted Interval Score (Bracher et al. 2021) sums over multiple quantile pairs (not just the 95% interval) with specific alpha-level weights. The demo's approximation uses only the 95% interval, which produces a score that correlates with the real WIS but has different magnitude and sensitivity properties. This is fine for a teaching example but a reader who uses this as their calibration metric will get different rankings than the standard WIS.

**Fix:** Add a brief comment:

```python
# Simplified WIS using only the 95% interval. The full WIS
# (Bracher et al. 2021) sums over all quantile pairs in the
# grid with alpha-specific weights. Production uses the full
# formulation for proper model ranking.
```

---

### Issue 6 - NOTE: `SEIRCompartmentalModel.forecast` quantile computation uses index rounding that can produce duplicate quantile values at small sample sizes

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, `SEIRCompartmentalModel.forecast` and `StatisticalARIMABaseline.forecast`

```python
for q in QUANTILE_GRID:
    idx = max(0, min(len(week_values) - 1,
                     int(round(q * len(week_values)))))
    quantiles[str(q)] = round(max(week_values[idx], 0.1), 2)
```

With `num_samples=200` (the default), `q=0.025` maps to index `round(0.025 * 200) = round(5.0) = 5` and `q=0.1` maps to `round(0.1 * 200) = round(20.0) = 20`, which is fine. But with smaller sample sizes (e.g., if a reader reduces `num_posterior_samples` to 20 for faster iteration), `q=0.025` maps to `round(0.5) = 0` and `q=0.1` maps to `round(2.0) = 2`, producing coarse quantile estimates. The formula `int(round(q * len(week_values)))` also has an off-by-one: for `q=0.975` with 200 samples it maps to index `round(195.0) = 195`, but the 97.5th percentile of 200 sorted values should be at index 194 (0-indexed, since `0.975 * 199 = 194.025`).

**Fix:** This is a minor pedagogical issue. Add a comment noting the approximation:

```python
# Empirical quantile via index rounding. For the demo's 200
# samples this is adequate; production uses numpy.quantile or
# equivalent with proper interpolation.
```

---

### Issue 7 - NOTE: Module-level boto3 clients are constructed but never called in the demo

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, Configuration and Constants section

Seven module-level boto3 handles are constructed (`s3_client`, `dynamodb`, `kinesis_client`, `eventbridge_client`, `cloudwatch_client`, `sagemaker_runtime`, `lambda_client`). The demo wires up mocks and never references the real handles. boto3 client creation is lazy (no network call until use), so this causes no runtime issue, but a learner may wonder why they exist.

**Fix:** The existing comment ("they are staged here so production wiring is a one-line swap") is adequate. No change needed.

---

### Issue 8 - NOTE: `deliver_forecast` CloudWatch `put_metric_data` uses model_id in MetricName which may contain hyphens

**Severity:** NOTE
**File:** `chapter12.09-python-example.md`, `deliver_forecast`

```python
metrics_payload.extend([
    {"MetricName": f"Coverage95_{model_id}",
     "Value":      float(metrics["coverage_95"]),
     "Unit":       "None"},
```

CloudWatch metric names allow hyphens, so `Coverage95_seir-age-stratified-v3` is valid. However, the lack of `Dimensions` means all jurisdictions' metrics land in the same metric name. Production would use dimensions for jurisdiction and model_id rather than encoding model_id in the metric name. This is fine for a teaching example but worth noting.

**Fix:** Add a brief comment:

```python
# Production uses Dimensions (jurisdiction, model_id) rather
# than encoding model_id in the MetricName, which enables
# per-jurisdiction alarming and cross-jurisdiction aggregation.
```

---

## What Was Verified

- **DynamoDB Decimal discipline:** Every numeric attribute on records written to `MockTable` passes through `_to_decimal` before assignment: `p_025`, `p_10`, `p_25`, `p_50`, `p_75`, `p_90`, `p_975`, `horizon_weeks`. The `_to_decimal` helper routes through `Decimal(str(round(float(value), 6)))` for floats (avoiding the `Decimal(0.1)` repr surprise), handles int/Decimal/str/bool/None cleanly, and raises `TypeError` on exotic types. No raw `float` lands in any `put_item` or `batch_writer().put_item` call. ✓

- **S3 keys have no leading slashes:** All S3 key constructions use f-strings like `f"harmonized/{HARMONIZATION_VERSION}/{jurisdiction['fips']}/{feed_id}.json"`, `f"nowcasts/{NOWCAST_MODEL_VERSION}/{jurisdiction['fips']}/{run_id}.json"`, `f"per-model-forecasts/{forecast['model_id']}/{jurisdiction['fips']}/{run_id}.json"`, `f"ensemble-forecasts/{ENSEMBLE_CONFIG_VERSION}/{jurisdiction['fips']}/{run_id}.json"`, `f"calibration/{jurisdiction['fips']}/{run_id}.json"`, and `f"raw-surveillance/{jurisdiction['fips']}/{feed_id}/{run_id}.json"`. None start with `/`. ✓

- **boto3 client/resource construction:** All seven module-level handles use valid AWS service identifiers (`"s3"`, `"dynamodb"`, `"kinesis"`, `"events"`, `"cloudwatch"`, `"sagemaker-runtime"`, `"lambda"`). The adaptive retry config `{"max_attempts": 5, "mode": "adaptive"}` is a valid `botocore.config.Config` shape. Region is explicit. ✓

- **Mock API signatures match boto3 conventions:** `MockS3.put_object(Bucket=..., Key=..., Body=...)` and `.get_object(Bucket=..., Key=...)` match `boto3.client('s3').put_object/get_object`. `MockTable.batch_writer().put_item(Item=...)` matches `boto3.resource('dynamodb').Table(...).batch_writer().put_item(Item=...)`. `MockEventBus.put_events(Entries=[...])` matches `boto3.client('events').put_events(Entries=[...])`. `MockCloudWatch.put_metric_data(Namespace=..., MetricData=[...])` matches `boto3.client('cloudwatch').put_metric_data(...)`. ✓

- **EventBridge Entry schema:** The entry passed to `put_events` contains `Source`, `DetailType`, `EventBusName`, `Time` (datetime), and `Detail` (JSON string). This matches the real boto3 Entry schema. ✓

- **SEIR compartmental math:** The Euler-discretized SEIR correctly conserves population (S + E + I + R = N at every step via the `new_inf = min(new_inf, S)` guard). The `beta_daily` derivation from R0 and gamma is standard. The weekly aggregation sums daily `new_progress` (E->I transitions, which represent new symptomatic cases) rather than `new_inf` (S->E transitions), which is the correct observable for surveillance-anchored forecasting. ✓

- **Nowcast fusion math:** The inverse-variance-weighted fusion correctly weights each feed by its `fusion_weight * correction_factor`, normalizes by total weight, and computes fusion SD from the weighted variance across feed estimates. The reporting-delay correction inflates uncertainty for the most recent week (1.5x multiplier). The z-score for p10/p90 (1.282) is correct for a normal distribution's 10th/90th percentiles. ✓

- **Vincentized ensemble combination:** The combiner correctly averages quantile values (not distributions) across models, weighted by inverse-WIS. The weight normalization (`weight_total`) handles the case where not all models provide all quantiles. ✓

- **Calibration coverage computation:** The holdout evaluation correctly checks whether actuals fall within the [q25, q75] (50%), [q10, q90] (80%), and [q025, q975] (95%) intervals and computes empirical coverage as the fraction of horizons where the actual is contained. ✓

- **Synthetic data generator:** The lead/lag structure (wastewater leads by ~1 week via `ww_lead_idx = min(history_weeks - 1, w + 1)`, ED is current week, lab lags by ~1 week via `lab_lagged_idx = max(0, w - 1)`, hospitalizations lag by ~2 weeks via `hosp_lagged_idx = max(0, w - 2)`) matches the prose's description of signal timing relationships. The reporting-delay under-counting on recent weeks (70% and 85% factors for the last two weeks of lab data) correctly simulates the "most recent data is systematically under-reported" phenomenon the nowcast is designed to correct. ✓

- **Versioning fields propagate:** Every persisted artifact carries `run_id`, `feed_spec_version`, `harmonization_version`, `nowcast_model_version`, `pipeline_version`, and model-specific version identifiers. The DynamoDB operational records carry the full version chain for audit reconstruction. ✓

- **No fabricated boto3 methods:** Every API call name (`put_object`, `get_object`, `put_item`, `batch_writer`, `put_events`, `put_metric_data`) maps to a real AWS service operation. No invented method names. ✓

- **Deploy-time guardrail:** The module-level `assert _value, f"{_name} must be set..."` block validates all 11 resource name constants are non-empty at import time. ✓

- **PHI logging discipline:** The `logger` calls log only structural metadata (feed count, jurisdiction FIPS, pipeline stage, runtime values like nowcast p50). No raw surveillance counts at sub-state resolution, no line-list records, no per-geography forecast values are logged. The EventBridge event similarly contains only structural metadata (run_id, jurisdiction FIPS, counts of horizons/scenarios/alarms). ✓

- **End-to-end runnability:** `run_demo()` constructs all mocks, seeds the registry with warmup calibration records, runs the full pipeline, and prints diagnostics at each stage including a sample DynamoDB record and a sample registry bundle summary. The deterministic seed (`SYNTHETIC_RANDOM_SEED = 4242`) ensures reproducible output. ✓

---

## Closing Notes

This is an exceptionally thorough Python companion for a complex recipe. The epidemic forecasting pipeline covers multi-source surveillance harmonization, Bayesian state-space nowcasting, compartmental and statistical model families, Vincentized ensemble combination, calibration validation, scenario forecasting, and multi-target operational delivery. The code correctly implements all five pseudocode steps, maintains Decimal discipline at the DynamoDB boundary, constructs S3 keys without leading slashes, and uses correct boto3 API patterns throughout. The two warnings are both in the "misleading for a learner" category rather than "code won't work" category: the scenario peak-uncertainty computation uses a semantically incorrect aggregation, and the EventBridge mock has a minor serialization inconsistency. The notes are quality-of-life improvements that would tighten the teaching content. The Gap to Production section is comprehensive and honest about the distance between the demo and a real state public-health deployment. Cleared for editor handoff after the two warnings are addressed.
