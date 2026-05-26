# Code Review: Recipe 12.3 - ED Arrival Forecasting

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.03-ed-arrival-forecasting.md` (main recipe with five-step pseudocode)
- `chapter12.03-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. One WARNING-level finding (under the FAIL threshold of >3). Several NOTE-level improvements. The five pseudocode steps map cleanly to the Python functions, the Decimal discipline is consistent across every record written through the mocks, the demo runs end-to-end against the in-memory mocks, no S3 keys are constructed (no leading-slash exposure to verify), the recursive-forecasting lag handling is correct, and the boto3 client/resource constructors and mock signatures align with current AWS SDK conventions.

---

## Pseudocode-to-Python Mapping

| Step | Recipe Pseudocode | Python Function | Status |
|------|-------------------|-----------------|--------|
| 1 | `aggregate_arrivals_to_hourly` (bucket arrivals into hourly counts per ESI) | `aggregate_arrivals_to_hourly` | ✓ (gap-fill is a Python addition; see Issue 5) |
| 2 | `build_feature_table` (calendar + weather + surveillance + event + lag features) | `build_feature_table` | ✓ |
| 3 | `train_volume_and_acuity_models` (Poisson volume + multinomial acuity, holdout MAPE / log-loss) | `train_volume_and_acuity_models` plus `PoissonGLM`, `MultinomialAcuityClassifier` | ✓ (Issue 4 on validation metric mismatch) |
| 4 | `generate_hourly_forecasts` (per-horizon point + interval + ESI breakdown) | `generate_hourly_forecasts` plus `_build_future_feature_row` | ✓ |
| 5 | `load_forecasts_to_dynamodb` (BatchWriteItem + CURRENT pointer + EventBridge + CloudWatch) | `load_forecasts_to_dynamodb` | ✓ |

The five pseudocode steps each have a one-to-one Python function. The recursive-forecasting loop in Step 4 (where `recent_history` grows with model predictions before lag lookups for longer horizons) matches the prose's "uses the model's own previous predictions" guidance. The CURRENT pointer upsert pattern after the historical batch write matches the dashboard's single-GetItem read path described in the recipe.

---

## Findings

### Issue 1 — WARNING: `MockS3` class is defined but never instantiated; the demo's S3 path is dead code

**Severity:** WARNING (misleading)
**File:** `chapter12.03-python-example.md`, "Mocks and Synthetic Data" section and `run_demo()`

The `MockS3` class implements `put_object` and `get_object` with a streaming-body shim:

```python
class MockS3:
    """In-memory stand-in for an S3 bucket.
    ...
    """
    def __init__(self):
        self.objects = {}
    def put_object(self, Bucket, Key, Body, **kwargs):
        ...
    def get_object(self, Bucket, Key, **kwargs):
        ...
```

But `run_demo()` only constructs `MockTable`, `MockEventBus`, and `MockCloudWatch`. No instance of `MockS3` is created, no function in the pipeline accepts an S3 handle, and no `put_object` / `get_object` call is made anywhere in the demo. The pseudocode's Step 1 prose says "writes hourly Parquet partitions to S3" and the comments inside `aggregate_arrivals_to_hourly` reinforce that production "writes these to S3 partitioned by (ed_id, year, month, day) as Parquet," but the Python equivalent is the in-memory `output` list that gets returned and passed to Step 2 directly. The model-artifact, weather, flu-index, and event-calendar S3 prefixes named in the configuration block are similarly never written to.

A reader sees seven S3 bucket constants and a fully-fleshed `MockS3` class and reasonably concludes the demo exercises S3 reads or writes somewhere. It does not. The same five-line `class _StreamingBody` pattern that learners would copy into their own code never gets invoked, so any subtle bug in it would go undetected.

**Fix:** Either (a) remove `MockS3` and the seven S3 bucket constants from the demo and let the comments inside `aggregate_arrivals_to_hourly` carry the "production writes to S3" message; or (b) wire `MockS3` into the pipeline by having `aggregate_arrivals_to_hourly` write the hourly rows as JSON to `(HOURLY_ARRIVALS_BUCKET, "hourly/<ed_id>/<date>/...")` and `build_feature_table` read them back, demonstrating both the keyed-write pattern and the read-side parsing. Option (a) is the lighter touch and matches the demo's existing in-process character. If option (b), make sure the constructed S3 keys never have a leading slash (the demo's prose claim of "no leading slash" only holds today because no key is constructed).

---

### Issue 2 — NOTE: Six module-level boto3 clients are constructed but never called by the demo

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, "Configuration and Constants" section

The configuration block constructs six module-level boto3 handles:

```python
s3_client          = boto3.client("s3", ...)
dynamodb           = boto3.resource("dynamodb", ...)
kinesis_client     = boto3.client("kinesis", ...)
eventbridge_client = boto3.client("events", ...)
cloudwatch_client  = boto3.client("cloudwatch", ...)
sagemaker_client   = boto3.client("sagemaker", ...)
```

The demo wires up `MockTable`, `MockEventBus`, and `MockCloudWatch` and never references the real handles. The Kinesis and SageMaker handles have no mock counterpart and never get exercised at all. boto3 client/resource creation is lazy (no network call until use), so the dead handles do not cause runtime issues, but a learner reading the file sees six clients constructed and may assume one or more is exercised somewhere.

The comment block partially acknowledges this ("The demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch via run_demo() and never touches these real handles; they are staged here so production wiring is a one-line swap"), but the comment includes `MockS3` which the demo does not actually wire up (Issue 1), and it omits the Kinesis and SageMaker clients which have no mock equivalent. The naming is also a little asymmetric: `dynamodb` (resource) vs. `s3_client`, `kinesis_client`, etc. (clients).

**Fix:** Either (a) trim the comment to match what the demo actually wires up (drop the `MockS3` mention until Issue 1 is resolved) and explicitly note that the Kinesis and SageMaker handles are staged for the production paths described in the Gap to Production section; or (b) move the client construction inside a `_build_real_clients()` helper that the production deployment would call instead of the demo, so the configuration block stays focused on resource names. Option (a) is a one-paragraph comment fix.

---

### Issue 3 — NOTE: Manual outer chunking in `load_forecasts_to_dynamodb` is redundant given `batch_writer()` auto-chunks

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, `load_forecasts_to_dynamodb`

```python
written = 0
chunk   = 25
for i in range(0, len(records), chunk):
    batch = records[i:i + chunk]
    with table.batch_writer() as bw:
        for record in batch:
            ...
            bw.put_item(Item=item)
            written += 1
```

The boto3 resource-level `batch_writer()` already chunks into 25-item batches automatically and retries `UnprocessedItems` with exponential backoff internally. The manual outer chunking the demo performs is not how production code is written: production opens a single `batch_writer()` context for the entire list and lets the SDK handle chunking and retries. The demo's approach is correct in result (writes do happen) but teaches an unnecessary outer loop that production code would never need.

The pseudocode in the main recipe also implies the manual chunking pattern ("chunk forecast_records into groups of 25"), so this is a consistency choice between the recipe and the Python rather than a bug, but it slightly miscues the reader on the canonical production idiom.

**Fix:** Either (a) collapse to a single batch_writer context:

```python
written = 0
with table.batch_writer() as bw:
    for record in records:
        ...
        bw.put_item(Item=item)
        written += 1
```

with a comment noting the SDK handles 25-item chunking and `UnprocessedItems` retry, or (b) keep the explicit chunking but add a one-line comment that this is for visibility in a pedagogical example and production typically delegates chunking to the SDK. Option (a) shrinks the function and aligns with the canonical idiom; option (b) preserves the explicit-loop teaching value with a hedged comment.

---

### Issue 4 — NOTE: Acuity macro-F1 evaluation reduces a multinomial share prediction to a dominant-class label, which understates the model's actual operational job

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, `train_volume_and_acuity_models`; main recipe Step 3 pseudocode

```python
# Acuity macro-F1 against the dominant ESI per row.
tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
for row in validation:
    if row["target_total"] == 0:
        continue
    actual_esi = max(ESI_LEVELS,
                     key=lambda e: row[f"target_esi_{e}"])
    shares = acuity_model.predict_shares(row)
    pred_esi = max(shares, key=shares.get)
    ...
```

The `MultinomialAcuityClassifier` is a per-share predictor that returns a five-element distribution per row. The pipeline downstream multiplies the volume forecast by these shares to produce per-ESI counts. That is the operationally meaningful output. The validation metric, however, collapses the predicted distribution to its argmax and the actual ESI counts to the dominant class, then computes macro-F1 across those argmax labels.

The argmax-vs-argmax F1 is a reasonable sanity-check metric, but it does not reflect how the model is actually used: multiplying its full distribution by volume to produce per-ESI counts. A model that predicts `{esi_3: 0.51, esi_4: 0.49}` and the actual hour has `{esi_3: 0.52, esi_4: 0.48}` looks identical to a model that predicts `{esi_3: 0.99, esi_4: 0.01}` under argmax F1, even though one is operationally fine and the other will badly miscount ESI 4 visits.

The pseudocode in the main recipe says the acuity classifier is evaluated by "per-class log loss" (Step 3), which would directly evaluate the share predictions. The Python implements F1 macro instead, with an inline comment acknowledging "computed against the dominant class per row for simplicity." That is honest, but the gap between the pseudocode metric (log loss on shares) and the Python metric (macro F1 on argmax labels) is wide enough that a reader trying to map one to the other will pause.

**Fix:** Either (a) replace the F1 macro with a multinomial log-loss against shares so the pseudocode and the Python agree:

```python
import math
total_logloss = 0.0
total_n       = 0
for row in validation:
    if row["target_total"] == 0:
        continue
    shares = acuity_model.predict_shares(row)
    for esi in ESI_LEVELS:
        c = row[f"target_esi_{esi}"]
        if c > 0:
            p = max(shares[esi], 1e-9)   # avoid log(0)
            total_logloss -= c * math.log(p)
            total_n       += c
acuity_logloss = total_logloss / total_n if total_n else float("nan")
```

and report `acuity_logloss` instead of `acuity_macro_f1`; or (b) update the pseudocode in the main recipe to say "macro-F1 against the dominant ESI per row" so the artifacts agree. Option (a) is more truthful to what the model is doing and aligns with what production teams would actually monitor.

---

### Issue 5 — NOTE: `aggregate_arrivals_to_hourly` quietly adds a gap-fill pass that the pseudocode does not mention

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, `aggregate_arrivals_to_hourly` final block; main recipe Step 1 pseudocode

The Python's Step 1 has a fourth substep that fills missing hours with zero-count rows:

```python
# 1d. Fill gaps. Hours with zero arrivals are real signal
# (overnight at a small ED, holiday closures), but they show
# up as missing rows in the bucketing. The model needs every
# hour represented to learn the daily curve correctly.
if output:
    ed_ids = sorted({r["ed_id"] for r in output})
    filled = []
    for ed in ed_ids:
        ed_rows = [r for r in output if r["ed_id"] == ed]
        ...
```

The pseudocode in the main recipe stops at "write the hourly counts to S3 partitioned by date and ED" and does not describe a gap-fill pass. The gap-fill is genuinely necessary (a model that never sees a 03:00 hour because no patients arrived will learn the wrong curve), but a reader comparing the pseudocode and the Python side-by-side will see a step in the Python that has no analogue in the recipe.

The implementation is also `O(N * K)` where `K` is the number of EDs and `N` is the total row count, because `[r for r in output if r["ed_id"] == ed]` walks the full list per ED. For a single-ED demo this is negligible; for a multi-ED system pipeline it would benefit from grouping once.

**Fix:** Add a Step 1d to the recipe pseudocode:

```text
// 1d. Fill missing hours with zero-count rows. A zero-arrival
// hour is real signal (overnight quiet, holiday closure) and
// must appear in the modeling-ready table or the model learns
// a biased daily curve.
FOR each ed_id in distinct ed_ids of hourly_buckets:
    fill any missing local_hour between min and max for that ED
    with zero counts across all ESI levels
```

and optionally tighten the Python loop to a single `defaultdict(list)` group-by:

```python
by_ed = defaultdict(list)
for r in output:
    by_ed[r["ed_id"]].append(r)
filled = []
for ed, ed_rows in by_ed.items():
    ...
```

Aligning the artifacts removes the pseudocode-to-Python surprise; the loop tightening is optional polish.

---

### Issue 6 — NOTE: `US_FEDERAL_HOLIDAYS` is a hardcoded set of nine dates spanning 2024-2026, which leaves training-window holidays partially unrepresented

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, top of "Step 2" section

```python
US_FEDERAL_HOLIDAYS = {
    "2025-01-01", "2025-07-04", "2025-12-25",
    "2026-01-01", "2026-07-04", "2026-12-25",
    "2024-01-01", "2024-07-04", "2024-12-25",
}
```

The synthetic history is `SYNTHETIC_HISTORY_DAYS = 730` (two years) ending at `date.today()`. Depending on when the demo runs, the history span covers 5 to 7 of these 9 dates. The other federal holidays (Memorial Day, Labor Day, Thanksgiving, MLK Day, Presidents' Day, Juneteenth, Veterans Day, Columbus Day) are missing entirely. The recipe's prose explicitly calls out Memorial Day weekend and Thanksgiving as having distinctive ED arrival patterns, so the demo's holiday flag is a thin shadow of what production needs.

The comment acknowledges the stub ("production reads from a holiday calendar table that accounts for state-specific holidays and observance shifts"), so this is not misleading the reader, but the gap between three holidays-per-year and "the holiday calendar" is wide enough that a learner copying this for a real prototype will quietly be missing the bulk of the holiday signal.

**Fix:** Either (a) expand the set to include all eleven U.S. federal holidays for 2024-2026 (still hardcoded, still a stub, but covers the operationally significant ones), or (b) add a comment one level stronger: "Production must replace this with a complete federal + state + observance calendar; the three holidays per year shown here are a placeholder and the model's holiday signal will be near-zero with this stub." Option (a) is a thirty-line fix and lets the demo actually demonstrate the holiday feature mattering.

---

### Issue 7 — NOTE: The horizon-scaling factor for prediction intervals (`sigma * sqrt(max(1.0, h / 4.0))`) is undocumented in the recipe

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, `generate_hourly_forecasts`

```python
# Prediction intervals widen with horizon. The demo uses
# a simple linear scaling; production uses the model's
# actual forward-step covariance or a quantile-regression
# approach.
horizon_sigma = sigma * math.sqrt(max(1.0, h / 4.0))
```

The comment says "linear scaling" but the formula is square-root. The intent is the random-walk-style growth in forecast variance with horizon, which is `sqrt(h)` not linear. The Python is correct (variance grows linearly, std-dev grows as `sqrt`); the comment is the part that mis-describes what the code does. A learner who reads the comment and not the formula would walk away with the wrong mental model.

The recipe pseudocode in Step 4 references `volume_lower_80, volume_upper_80, volume_lower_95, volume_upper_95` as outputs of the SageMaker endpoint without specifying how they scale with horizon, so this is fine on the recipe side but inconsistent inside the Python.

**Fix:** Tighten the comment:

```python
# Prediction intervals widen with horizon. The demo scales
# the residual standard deviation by sqrt(h/4), which models
# variance growing linearly with horizon (a random-walk-style
# approximation). Production uses the model's actual
# forward-step covariance or a direct quantile-regression
# approach for each horizon.
```

The formula stays; only the comment changes.

---

### Issue 8 — NOTE: The model classes attach private attributes (`_feat_means`, `_feat_sds`) at fit time that `predict` then relies on without declaring in `__init__`

**Severity:** NOTE
**File:** `chapter12.03-python-example.md`, `PoissonGLM.fit` and `PoissonGLM.predict`

```python
def fit(self, training_rows, n_iters=8, lr=0.001):
    ...
    self._feat_means = feat_means
    self._feat_sds   = feat_sds
    ...

def predict(self, row):
    v = self._row_to_vector(row)
    if not hasattr(self, "_feat_means"):
        return self._predict_one(v)
    vs = {name: (v[name] - self._feat_means[name]) / self._feat_sds[name]
          for name in self.FEATURE_NAMES}
    return self._predict_one(vs)
```

The instance attributes `_feat_means` and `_feat_sds` are created during `fit` and consumed during `predict`. They are not declared in `__init__`, so a reader doing static inspection of the class doesn't see them. The `hasattr` check in `predict` is a defensive guard that quietly returns an unstandardized prediction if the model has never been fit, which masks the error rather than surfacing it.

This is a minor pedagogical concern: the convention of "all instance attributes initialized in `__init__`" is widely taught and the demo bends it without explanation. A learner copying this pattern into their own model classes loses some readability.

**Fix:** Either (a) initialize them in `__init__`:

```python
def __init__(self):
    self.intercept   = 0.0
    self.coef        = {name: 0.0 for name in self.FEATURE_NAMES}
    self.sigma       = 0.0
    self._feat_means = {name: 0.0 for name in self.FEATURE_NAMES}
    self._feat_sds   = {name: 1.0 for name in self.FEATURE_NAMES}
```

and remove the `hasattr` guard in `predict`, or (b) raise an explicit error in `predict` when called before `fit`:

```python
if not hasattr(self, "_feat_means"):
    raise RuntimeError(
        "PoissonGLM.predict called before fit; call fit() first")
```

Option (a) is the cleaner teaching pattern and matches scikit-learn conventions.

---

## What Was Verified

- **DynamoDB Decimal discipline:** Every numeric attribute on a record written to the mock table passes through `_to_decimal` before assignment: `forecast_horizon_h`, `volume_point`, `volume_lower_80`, `volume_upper_80`, `volume_lower_95`, `volume_upper_95`, and each entry in `esi_breakdown`. The historical record write and the CURRENT pointer write apply the same conversion. The `_to_decimal` helper itself routes through `Decimal(str(value))` for floats (avoiding the `Decimal(0.1)` repr surprise), routes ints/Decimals/strs cleanly, raises on exotic types, and explicitly handles `bool` (which is a subclass of `int` in Python). No raw `float` lands in any `put_item` or `batch_writer().put_item` call. ✓

- **EventBridge Detail JSON safety:** The `put_events` Detail is built from the original `records` list (not the post-conversion DynamoDB items), so `r["forecast_horizon_h"]` is still an `int` when consumed by `sorted({...})` and `json.dumps`. No Decimal leaks into `json.dumps` (which would raise `TypeError: Object of type Decimal is not JSON serializable`). ✓

- **S3 keys:** No `s3_client.put_object` or `s3_client.get_object` calls in the demo (see Issue 1). The S3 buckets are referenced only as constants. No leading-slash exposure to verify, but no actual S3 path construction to validate either. ✓ (with the caveat in Issue 1)

- **boto3 client/resource construction:** Each of the six module-level handles uses a real AWS service identifier (`"s3"`, `"dynamodb"`, `"kinesis"`, `"events"`, `"cloudwatch"`, `"sagemaker"`), the adaptive retry config (`{"max_attempts": 5, "mode": "adaptive"}`) is a valid `botocore.config.Config` shape, and the region pin is explicit. ✓

- **Mock API signatures match boto3 conventions:** `MockTable.put_item(Item=...)` and `MockTable._BatchWriter.put_item(Item=...)` match `boto3.resource('dynamodb').Table(...).put_item(Item=...)` and `.batch_writer().put_item(Item=...)`. `MockEventBus.put_events(Entries=[...])` matches `boto3.client('events').put_events(Entries=[...])` and the Entry shape (`Source`, `DetailType`, `EventBusName`, `Time`, `Detail`) is the real boto3 schema with `Time` as a `datetime` and `Detail` as a JSON string. `MockCloudWatch.put_metric_data(Namespace=..., MetricData=[...])` matches `boto3.client('cloudwatch').put_metric_data(...)` and the metric shape (`MetricName`, `Value`, `Unit`) is the real schema. ✓

- **Recursive forecasting lag handling:** In `generate_hourly_forecasts`, the `recent_history` list is initialized with the last 200 rows of actual past values (about 8 days, enough to cover the 168-hour lag). For each future hour at horizon `h`, the loop computes `lag_1h_iso`, `lag_24h_iso`, `lag_168h_iso` and looks them up via `dict(recent_history).get(...)`. After predicting, the loop appends `(future_iso, volume_pred)` to `recent_history` so the next iteration's `lag_1h` can find the prediction. For `h=2`, the `lag_1h_iso` resolves to `current_hour + 1`, which was just appended at `h=1`. The recursion is correct. ✓

- **Poisson sampling in synthetic data generator:** The inter-arrival-time loop (`t += rng.expovariate(1.0); if t > mu: break`) counts events of a unit-rate Poisson process in `[0, mu]`, which is `Poisson(mu)`. Mathematically correct. ✓

- **Z-score lookup table:** `PREDICTION_INTERVAL_LEVELS = {"80": Decimal("1.282"), "95": Decimal("1.960")}`. The 80% interval z-score (1.282) and the 95% interval z-score (1.960) are the standard normal quantiles for two-sided intervals. ✓

- **Train/validation split:** `cutoff = last_hour - timedelta(days=VALIDATION_WINDOW_DAYS)` (90 days). Training is `< cutoff`, validation is `>= cutoff`. The split is contiguous and uses the most recent 90 days for validation, matching the recipe's prose. The double list-comprehension iteration is `O(2N)` but acceptable at the demo's scale. ✓

- **Feature standardization:** `feat_means` and `feat_sds` are computed once over the training set and reused for both training-pass gradient updates and inference-time prediction. The `sd if sd > 1e-9 else 1.0` guard avoids divide-by-zero on constant features. ✓

- **MAPE divide-by-zero guard:** The MAPE loop skips rows where `target_total == 0` (`if row["target_total"] == 0: continue`), avoiding the classic MAPE-on-zero error. The Acuity F1 loop applies the same guard. ✓

- **Versioning fields propagate to records:** Each forecast record carries `pipeline_version`, `volume_model_version`, and `acuity_model_version`, which the prose calls out as the audit-reconstruction primitive. ✓

- **CURRENT pointer namespace:** The historical sort key is `f"{forecast_for_hour}#{generated_at}"`; the CURRENT pointer sort key is `f"CURRENT#{forecast_for_hour}"`. The two namespaces do not collide on a `begins_with` query. ✓

- **End-to-end runnability via mocks:** The `run_demo()` runner constructs the three mocks, runs `run_ed_forecast_pipeline`, walks Steps 1–5 with print statements at each stage, and prints a sample CURRENT record using a `default=_decimalify` JSON encoder that handles Decimal and datetime. All three forecast horizons (4h, 12h, 24h) flow through to forecast records. No exception paths in the demo's happy path. ✓

- **Naive-datetime discipline:** The synthetic data generator uses naive datetimes throughout, the aggregation floors against naive `replace(minute=0, second=0, microsecond=0)`, and the recipe explicitly calls out that production must tag each record with the ED's IANA timezone identifier. The demo's all-naive approach is internally consistent. ✓

- **No fabricated boto3 methods:** Every API call name (`put_item`, `batch_writer`, `put_events`, `put_metric_data`) maps to a real AWS service operation. The retry-config keys (`max_attempts`, `mode`) are valid `botocore.config.Config.retries` keys.

- **Deploy-time guardrail:** The module-level `assert _value, f"{_name} must be set..."` block fails fast if a required resource name is left blank. The comment notes that running with `python -O` strips asserts; for a teaching example this is acceptable.

- **PHI handling stance:** The comment block above `logger` declares "Log structural metadata only (run_id, ed_id, hour_local, arrival_count, mean_error, runtime_ms), never raw ADT records, never per-patient timestamps tied to identifiable visits" and the actual `logger.info` calls in the file emit only counts, durations, and metric values, never patient-level fields. The synthetic ADT records carry an `encounter_id` placeholder but no real PHI fields. The EventBridge Detail payload deliberately omits patient identifiers. ✓

---

## Closing Notes

The Python file is well-structured: the configuration block is up-front and complete, the synthetic-data generator produces realistic-shaped two-year history with daily, weekly, and seasonal patterns, the per-step functions have clear inputs and outputs, the model classes have consistent `fit`/`predict` interfaces, and the pipeline orchestrator prints diagnostics at each stage so a reader can trace data flow. The Decimal discipline is consistent across every record-write site, the recursive-forecasting lag handling is correctly implemented, and the EventBridge JSON payload is built from the right (pre-Decimal) source so `json.dumps` will not crash on it. The single warning (the dead `MockS3` class) is a clean removal or wire-up decision. The notes are quality-of-life improvements that tighten the teaching content and align the artifacts (pseudocode and Python) more closely. Cleared for editor handoff after the warning is addressed.
