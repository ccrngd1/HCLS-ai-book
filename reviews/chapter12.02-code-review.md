# Code Review: Recipe 12.2 - Supply Inventory Forecasting

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.02-supply-inventory-forecasting.md` (main recipe with five-step pseudocode)
- `chapter12.02-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. One WARNING-level finding (under the FAIL threshold of >3). Several NOTE-level improvements. The five pseudocode steps map cleanly to the Python functions, the Decimal discipline is consistent across every record written through the mocks, the demo runs end-to-end against the in-memory mocks, no S3 keys are constructed (no leading-slash exposure), and the boto3 client/resource constructors and mock signatures align with current AWS SDK conventions.

---

## Pseudocode-to-Python Mapping

| Step | Recipe Pseudocode | Python Function | Status |
|------|-------------------|-----------------|--------|
| 1 | `prepare_consumption_data` (group/fill/successor/calendar features) | `prepare_consumption_data` | ✓ (see Issue 4) |
| 2 | `segment_skus` (ADI/CV² four-corner + procedure-driven override) | `segment_skus` | ✓ |
| 3 | `train_segment_model` (per-segment model family) | `train_segment_models` plus `SmoothModel`, `SBAModel`, `ProcedureDrivenModel` | ✓ |
| 4 | `generate_sku_forecasts_and_reorder_points` (forecast + safety stock) | `generate_sku_forecasts_and_reorder_points` | ✓ |
| 5 | `load_forecasts_to_dynamodb` (BatchWriteItem + CURRENT pointer) | `load_forecasts_to_dynamodb` | ✓ |

The four-corner segmentation in Python (`adi < ADI_THRESHOLD and cv2 < CV2_THRESHOLD` etc.) matches the pseudocode's threshold logic exactly. The procedure-driven override fires before the quantitative classification, matching the recipe's "regardless of demand pattern" guidance. The classical safety-stock formula (`z * sqrt(lead_time) * sigma_daily`) is implemented as written. The CURRENT pointer upsert per SKU after the batch write matches the pseudocode's intent for low-latency single-GetItem consumer reads.

---

## Findings

### Issue 1 — WARNING: Setup section over-specifies dependencies; pandas, numpy, prophet, and statsmodels are listed but never imported

**Severity:** WARNING (misleading)
**File:** `chapter12.02-python-example.md`, Setup section (lines ~12–18) and the imports block (lines ~52–66)

The Setup section instructs the reader to install four packages beyond boto3:

```bash
pip install boto3 pandas numpy
# Optional, for the smooth-segment Prophet branch:
pip install prophet
# Optional, for the case-volume model in the procedure-driven branch:
pip install statsmodels
```

None of these packages are imported by the example. The actual import block uses only `json`, `logging`, `math`, `random`, `uuid`, `collections.defaultdict`, `datetime`, `decimal.Decimal`, `statistics.mean`/`stdev`, `typing.Optional`, `boto3`, and `botocore.config.Config`. The `SmoothModel`, `SBAModel`, and `ProcedureDrivenModel` classes are pure-Python implementations using the standard library, not Prophet/statsmodels wrappers. The "in-process pandas transform" referenced in the heads-up paragraph is actually a `defaultdict(int)` aggregation in `prepare_consumption_data`, not a pandas DataFrame.

A learner who follows the setup instructions will install pandas, numpy, prophet, and statsmodels, run the demo, and watch nothing in those libraries get exercised. Worse, a reader skimming the imports to learn what they need for "this kind of pipeline" will see the gap and either question the setup instructions or assume that the imports are wrong and the libraries should be wired in.

**Fix:** Either (a) trim the install command to `pip install boto3` (the only actual runtime dependency) and move the optional Prophet/statsmodels mention into the "Gap to Production" section where production-grade replacements are already discussed; or (b) actually import pandas/numpy and use them where the comments say they would be (for example, the daily aggregation in `prepare_consumption_data` could legitimately use `pd.DataFrame.groupby([...])['quantity'].sum()` and the SmoothModel's OLS could use `numpy.polyfit`). Option (a) keeps the demo's pure-stdlib character and is consistent with the prose's framing ("in-process Python file so the focus stays on the segmentation, the per-segment modeling, the reorder-point math").

---

### Issue 2 — NOTE: `from typing import Optional` is imported but never used

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, imports block

`Optional` is imported but no type annotation in the file uses it. Removing the import keeps the import block honest about the file's surface area and avoids teaching an unnecessary import.

**Fix:** Remove the `from typing import Optional` line, or add type annotations on the public functions that use it (e.g., `def predict_horizon(self, last_date_iso: Optional[str], horizon_days: int) -> list:`). Removing is the lighter touch given the file's minimal type-hint convention.

---

### Issue 3 — NOTE: Pseudocode Step 1 references row-level features (`scheduled_cases`, `flu_season_index`) that the Python omits

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, `prepare_consumption_data`; main recipe Step 1 pseudocode

The pseudocode for Step 1 enumerates five calendar/exogenous features per row:

```text
row.day_of_week        = day index (0-6) of row.date
row.month              = month of row.date
row.is_holiday         = TRUE if row.date is in holiday_calendar
row.scheduled_cases    = lookup forecasted_cases(facility, date)  // for procedure-driven SKUs
row.flu_season_index   = seasonal indicator for respiratory SKUs
```

The Python emits `day_of_week`, `month`, and `is_holiday` (hardcoded `False` with an acknowledging comment) but omits `scheduled_cases` and `flu_season_index`. The procedure-driven branch reads `case_volume_by_date` directly in `ProcedureDrivenModel.fit()` rather than via a row attribute, which works for the demo but means the "feature engineering produces a self-contained modeling-ready row" pattern from the pseudocode is not literally exercised.

A reader comparing the two artifacts side-by-side will notice the gap. Either the pseudocode should be trimmed to the features actually carried on rows in the Python, or the Python should attach the case volume and a respiratory-season indicator to each row so the modeling-ready table is visibly self-contained.

**Fix:** Add `scheduled_cases` and `flu_season_index` to each row in `prepare_consumption_data` (the procedure-driven model can then read it from `row["scheduled_cases"]` rather than the side-channel `case_volume_by_date` parameter), or trim those two lines from the pseudocode in the main recipe. The first option is preferable because it teaches the row-as-feature-vector pattern the pseudocode advocates.

---

### Issue 4 — NOTE: Per-segment count log uses an unnecessarily complex set/sorted/comprehension chain

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, `segment_skus` final log call

```python
logger.info(
    "Segmented %d SKUs: %s",
    len(segments),
    ", ".join(f"{seg}={n}" for seg, n in
              sorted({(s, sum(1 for v in segments.values() if v == s))
                      for s in set(segments.values())})))
```

The inner expression builds a set comprehension `{(s, count) for s in set(segments.values())}`, which is functionally a list (since each segment-name `s` is unique and produces one tuple). The outer `set(segments.values())` is then iterated, and for each segment a `sum(1 for v in segments.values() if v == s)` re-walks the full mapping to count. The result is correct but the construct is harder to read than it needs to be and re-walks `segments.values()` once per segment.

**Fix:** Replace with a `Counter`:

```python
from collections import Counter   # or import alongside defaultdict
seg_counts = Counter(segments.values())
logger.info(
    "Segmented %d SKUs: %s",
    len(segments),
    ", ".join(f"{seg}={n}" for seg, n in sorted(seg_counts.items())))
```

This is one O(N) walk and reads more like the prose intent.

---

### Issue 5 — NOTE: Module-level boto3 clients (`s3_client`, `dynamodb`, `sagemaker_client`) are constructed but never called

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, Configuration and Constants section

The file constructs five module-level boto3 handles:

```python
s3_client          = boto3.client("s3", ...)
dynamodb           = boto3.resource("dynamodb", ...)
eventbridge_client = boto3.client("events", ...)
cloudwatch_client  = boto3.client("cloudwatch", ...)
sagemaker_client   = boto3.client("sagemaker", ...)
```

The demo wires up `MockTable`, `MockEventBus`, and `MockCloudWatch` and never references the real handles. boto3 client/resource creation is lazy (no network call until use), so the dead handles do not cause runtime issues, but a learner reading the file sees five clients constructed and may assume they are exercised somewhere. The naming is also a little asymmetric: `dynamodb` (resource) vs. `s3_client`, `eventbridge_client`, etc. (clients).

**Fix:** Either (a) add a one-line comment after the client block explaining that the demo overrides each with a mock and the real handles are staged for production wiring, or (b) move the client construction inside a `_build_real_clients()` helper that the production deployment would call instead of the demo. Option (a) is sufficient and adds two lines.

---

### Issue 6 — NOTE: BatchWriter comment understates what `boto3.resource('dynamodb').Table(...).batch_writer()` already provides

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, `load_forecasts_to_dynamodb`

```python
# DynamoDB BatchWriteItem accepts up to 25 items per call. The
# demo loops in chunks; production also handles unprocessed
# items returned from BatchWriteItem with exponential backoff.
```

The boto3 resource-level `batch_writer()` already chunks into 25-item batches automatically and handles `UnprocessedItems` retries with exponential backoff internally. The comment as written suggests production has to do the chunking and retry handling on top of `batch_writer()`. The actual production discipline is closer to: use `batch_writer()` and let it handle batching/retries, and add explicit error logging on the rare cases where it ultimately fails after exhausting retries.

**Fix:** Soften to:

```python
# The boto3 resource-level batch_writer() chunks into 25-item
# batches and retries UnprocessedItems with exponential backoff
# internally. The explicit chunking below is for clarity in a
# pedagogical mock; production typically just hands the full
# list of records to a single batch_writer() context.
```

---

### Issue 7 — NOTE: SBA daily-residual variance is correct for safety-stock math but the comment's "MAPE blows up on zero days" framing slightly miscues the reader

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, `SBAModel.fit`

```python
# Residual standard deviation against the constant
# forecast. SBA forecasts are constant per day, which
# makes residual variance simple to compute. Production
# uses MASE (mean absolute scaled error) for intermittent
# demand because MAPE blows up on zero days.
residuals = [q - self.daily_forecast for q in daily_quantities]
```

The variance computed here is the variance of daily demand around the constant per-day forecast, which is exactly what the safety-stock formula `z * sqrt(lead_time) * sigma_daily` consumes. That is correct.

The MASE-vs-MAPE comment is true but it pertains to forecast accuracy reporting, not to safety-stock variance estimation. A learner could read the comment as suggesting that the `residuals` list is the input to a MASE/MAPE calculation, when in fact it is the input to the std-dev calculation that feeds the reorder point. The two are distinct.

**Fix:** Reword the comment to separate the two concerns:

```python
# Residual standard deviation against the constant forecast.
# This is the per-day demand variability, which the safety-stock
# formula consumes via z * sqrt(lead_time) * sigma. For accuracy
# reporting, production uses MASE rather than MAPE because MAPE
# is undefined on zero-demand days; that's a separate metric
# from the std-dev used for reorder-point calculation.
```

---

### Issue 8 — NOTE: Reorder-point arithmetic round-trips through float

**Severity:** NOTE
**File:** `chapter12.02-python-example.md`, `generate_sku_forecasts_and_reorder_points`

```python
reorder_point = int(round(float(
    Decimal(str(mean_demand_lead)) + safety_stock)))
```

`mean_demand_lead` is a Python float (sum of float `point` values). The expression converts it to Decimal via str, adds the Decimal `safety_stock`, converts the Decimal sum back to float, rounds, and casts to int. The intermediate Decimal conversion buys nothing because the immediate `float(...)` discards Decimal's precision benefit, and the float-then-round-then-int is what determines the final integer. Either compute everything in float (since the result is rounded to int anyway) or stay in Decimal end-to-end.

**Fix:**

```python
# All-Decimal:
mean_demand_lead_dec = Decimal(str(mean_demand_lead))
reorder_point = int((mean_demand_lead_dec + safety_stock)
                    .quantize(Decimal("1")))
```

or

```python
# All-float (Decimal only at the DynamoDB boundary):
reorder_point = int(round(mean_demand_lead + float(safety_stock)))
```

The all-float form matches the demo's existing float-then-Decimal-at-boundary pattern.

---

## What Was Verified

- **DynamoDB Decimal discipline:** Every numeric attribute on a record written to the mock table passes through `_to_decimal` before assignment: `forecast_horizon_days`, `mean_demand_horizon`, `lower_bound`, `upper_bound`, `lead_time_days`, `service_level_target`, `reorder_point`, `order_quantity`, `sigma_daily`. The `_to_decimal` helper itself routes through `Decimal(str(value))` for floats (avoiding the `Decimal(0.1)` repr surprise), routes ints/Decimals/strs cleanly, raises on exotic types, and explicitly handles `bool` (which is a subclass of `int` in Python). No raw `float` lands in any `put_item` or `batch_writer().put_item` call. ✓

- **S3 keys:** No `s3_client.put_object` or `s3_client.get_object` calls in the demo. The S3 buckets are referenced only as constants. No leading-slash exposure to verify. ✓

- **boto3 client/resource construction:** Each of the five module-level handles uses a real AWS service identifier (`"s3"`, `"dynamodb"`, `"events"`, `"cloudwatch"`, `"sagemaker"`), the adaptive retry config (`{"max_attempts": 5, "mode": "adaptive"}`) is a valid `botocore.config.Config` shape, and the region pin is explicit. ✓

- **Mock API signatures match boto3 conventions:** `MockTable.put_item(Item=...)` and `MockTable._BatchWriter.put_item(Item=...)` match `boto3.resource('dynamodb').Table(...).put_item(Item=...)` and `.batch_writer().put_item(Item=...)`. `MockEventBus.put_events(Entries=[...])` matches `boto3.client('events').put_events(Entries=[...])`. `MockCloudWatch.put_metric_data(Namespace=..., MetricData=[...])` matches `boto3.client('cloudwatch').put_metric_data(...)`. The Entry shape passed to `put_events` (`Source`, `DetailType`, `EventBusName`, `Time`, `Detail`) is the real boto3 Entry schema with `Time` as a `datetime` and `Detail` as a JSON string. ✓

- **Decimal arithmetic in safety-stock formula:** `z_score`, `safety_stock`, `sigma_daily`, and the lookup-table interpolation in `_z_score_for_service_level` all operate on Decimals end-to-end, so no precision loss between the service-level lookup and the reorder-point calculation. ✓

- **Per-segment model routing:** `train_segment_models` routes `"smooth"` to `SmoothModel`, `"procedure_driven"` to `ProcedureDrivenModel`, and `"intermittent"` / `"erratic"` / `"lumpy"` to `SBAModel`. The recipe's prose acknowledges in the inline comment that production differentiates Croston/SBA/TSB and aggregates lumpy SKUs at the category level; the demo's three-way collapse is consistent with the pedagogical scope. ✓

- **Procedure-driven override:** `segment_skus` checks `is_procedure_driven` before computing ADI/CV² and routes to `procedure_driven` segment regardless of the quantitative classification. The flag flows from `sku_master` → `prepare_consumption_data` (per-row attribute) → `segment_skus` (per-SKU set membership). ✓

- **Insufficient-history fallback:** SKUs with fewer than 12 non-zero observations route to `lumpy` with an explicit `override_reason="insufficient_non_zero_history"` rather than producing a divide-by-zero or a noisy ADI. ✓

- **Versioning fields propagate to records:** Each forecast record carries `pipeline_version`, `model_version`, `safety_stock_version`, `segmentation_version`, and `run_id`, which the prose calls out as the audit-reconstruction primitive. ✓

- **CURRENT pointer upsert:** After the batch writes complete, the per-record loop creates a `current_pointer = dict(record)`, sets `generated_at = "CURRENT"` plus a `points_to` field referencing the original sort-key value, and writes via `table.put_item`. Consumers can do a single GetItem with `{"facility_sku": ..., "generated_at": "CURRENT"}`. ✓

- **End-to-end runnability via mocks:** The `run_demo()` runner constructs the three mocks, runs `run_supply_forecast_pipeline`, walks Steps 1–5 with print statements at each stage, and prints a sample CURRENT record using a `default=_decimalify` JSON encoder that handles Decimal and datetime. All five SKUs in the synthetic master flow through to forecast records. No exception paths in the demo's happy path. ✓

- **No fabricated boto3 methods:** Every API call name (`put_item`, `batch_writer`, `put_events`, `put_metric_data`) maps to a real AWS service operation. The retry-config keys (`max_attempts`, `mode`) are valid `botocore.config.Config.retries` keys.

- **Deploy-time guardrail:** The module-level `assert _value, f"{_name} must be set..."` block fails fast if a required resource name is left blank. The comment notes that running with `python -O` strips asserts; for a teaching example this is acceptable.

---

## Closing Notes

The Python file is well-structured: the configuration block is up-front and complete, the mocks are minimal and clearly labelled, the synthetic-data generator produces shapes that exercise each branch (smooth/erratic/intermittent/lumpy/procedure-driven), the per-segment model classes have a uniform `fit`/`predict_horizon`/`sigma` interface, and the pipeline orchestrator prints diagnostics at each stage so a reader can trace data flow. The Decimal discipline is consistent across every record-write site, which is the most common place this kind of demo regresses. The single warning (the misleading setup install list) is a one-line fix in the prose. The notes are quality-of-life improvements that tighten the teaching content. Cleared for editor handoff after the warning is addressed.
