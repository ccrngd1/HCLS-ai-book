# Code Review: Recipe 12.5 - Hospital Census Forecasting

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter12.05-hospital-census-forecasting.md` (main recipe with five-step pseudocode)
- `chapter12.05-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. No WARNING-level findings (under the FAIL threshold of >3). Several NOTE-level improvements. The five pseudocode steps map cleanly to the Python functions, the Decimal discipline is consistent across every record written through the mocks, the demo runs end-to-end against the in-memory mocks, every constructed S3 key avoids leading slashes, the Knuth Poisson sampler is mathematically correct, the exponential survival hazard-to-marginal-probability transformation is correctly transcribed (per-hour marginals plus end-horizon survival sum to 1 by construction), the Monte Carlo composition with overflow redistribution is logically sound, the boto3 client/resource constructors and mock signatures align with current AWS SDK conventions, and PHI-bearing data is never logged at the structured-logging boundary (only run-level metadata: `run_id`, snapshot counts, sample counts, runtime). The `_to_decimal` helper handles the `bool`-is-`int` Python subtlety correctly so `True` does not silently become `Decimal('1')` at the DynamoDB boundary.

---

## Pseudocode-to-Python Mapping

| Step | Recipe Pseudocode | Python Function | Status |
|------|-------------------|-----------------|--------|
| 1 | `snapshot_current_state` (active in-progress encounters + per-patient features + S3 partitioned write) | `snapshot_current_state`, `current_census_by_unit` | ✓ |
| 2 | `forecast_inflows` (per-source Poisson for ED/direct/transfer-in, deterministic OR schedule, ED-board Bernoulli, transfer-queue Bernoulli, multinomial unit assignment) | `forecast_inflows`, `PoissonInflowModel`, `MultinomialUnitAssigner` | ✓ |
| 3 | `forecast_outflows` (per-encounter survival model + per-Monte-Carlo-sample discharge time draw) | `forecast_outflows`, `ExponentialSurvivalModel.discharge_probability_per_hour`, `ExponentialSurvivalModel.hazard_per_hour` | ✓ |
| 4 | `compose_census` (Monte Carlo trajectories + overflow redistribution + percentile aggregation) | `compose_census`, `_distribute_overflow`, `_percentile` | ✓ |
| 5 | `deliver_forecast` (DynamoDB batch + EventBridge cycle event + CloudWatch metrics + per-unit max utilization) | `deliver_forecast` | ✓ |

The pseudocode's three modeling layers (Inflow, Outflow, Composition) plus the Snapshot anchor and the Delivery surface are each represented by a one-to-one Python function or class. The compose-step's overflow redistribution matches the pseudocode's `distribute_overflow` helper, and the percentile output (p10/p50/p90 plus `expected_occupancy`) matches the pseudocode's prediction-interval output schema. The hazard-multiplier discipline in the survival model honors the recipe's prose claim that "the discharge order is the strongest single feature" by applying a 6.0x multiplier when the order is in.

---

## Findings

### Issue 1 — NOTE: ED-board pending admits and the `ed_admit` Poisson source can overlap in early hours

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `forecast_inflows`

The function generates ED admits via two distinct paths that can both contribute admits in hours 0-2:

```python
poisson_sources = ["ed_admit", "direct_admit", "transfer_in"]
for sample_id in range(n_samples):
    for hour_offset in range(horizon_hours):
        target_ts = snapshot_ts + timedelta(hours=hour_offset)
        for source in poisson_sources:
            count = inflow_models[source].sample_count(target_ts, rng)
            ...
```

then later:

```python
for sample_id in range(n_samples):
    for ed_entry in ed_board:
        if rng.random() < 0.92:    # very likely to admit
            # Land the admit between hour 0 and hour 2.
            hour = rng.randint(0, min(2, horizon_hours - 1))
            ...
```

Conceptually the two streams represent different populations: the `ed_admit` Poisson covers ED arrivals that happen during the forecast horizon and become admissions, while the `ed_board` entries are admit-decided patients already in the ED who have not yet been placed. In a real production system the modeling would split these explicitly: the ED Poisson rate would be calibrated to exclude the ED-board pending population, or the Poisson would only fire for hours 3+ to avoid the overlap with the ED-board's hour-0-to-hour-2 window. The demo applies them additively without addressing the overlap, which can subtly inflate the early-horizon admit count by a small amount (roughly the 0.92 * 3 entries / 3 hours / sample = ~0.92 extra admits per early hour in expectation).

The recipe's prose distinguishes these populations clearly ("ED admissions are the largest source... about 12 to 18% of ED visits become admissions" vs. "the ED tracking board provides current ED census, holds, and admitted-but-not-yet-placed patients") but the inline comments in `forecast_inflows` do not call out the disjoint-vs-overlapping question or how production handles it.

**Fix:** Add a comment block above the ED-board sub-step explicitly noting that production calibrates these as disjoint populations. One paragraph fix:

```python
# 2b. ED tracking board: pending admits expected to land in
# the next 1-3 hours with high probability. In production the
# `ed_admit` Poisson rate is calibrated to exclude the ED-board
# pending population so the two streams are disjoint by
# construction; the demo applies them additively for simplicity,
# which slightly inflates the early-horizon admit count. Adjust
# the Poisson rate or the ED-board hour window if you need a
# cleaner split.
```

No code change required.

---

### Issue 2 — NOTE: Module-level boto3 clients are constructed but never exercised by the demo

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, "Configuration and Constants" section

The configuration block constructs seven module-level boto3 handles:

```python
s3_client          = boto3.client("s3", ...)
dynamodb           = boto3.resource("dynamodb", ...)
healthlake_client  = boto3.client("healthlake", ...)
eventbridge_client = boto3.client("events", ...)
cloudwatch_client  = boto3.client("cloudwatch", ...)
sagemaker_runtime  = boto3.client("sagemaker-runtime", ...)
lambda_client      = boto3.client("lambda", ...)
```

The demo wires up `MockHealthLake`, `MockS3`, `MockTable`, `MockEventBus`, and `MockCloudWatch` and never references the real handles. The `sagemaker_runtime` and `lambda_client` handles have no mock counterpart at all and never get exercised. boto3 client/resource creation is lazy (no network call until first use), so the unused handles do not cause runtime issues, but a learner reading the file sees seven clients constructed and may assume one or more is exercised somewhere. The naming is also slightly asymmetric: `dynamodb` (resource) vs. `s3_client`, `healthlake_client`, `eventbridge_client`, etc. (clients).

The comment block above the construction does acknowledge this ("The demo wires up MockS3 / MockTable / MockEventBus / MockCloudWatch / MockHealthLake via run_demo() and never touches these real handles"), but it omits `sagemaker_runtime` and `lambda_client` which have no mock equivalent.

**Fix:** Either (a) trim the comment to call out which handles are demo-mocked and which are staged purely for the production paths described in the Gap to Production section ("`sagemaker_runtime` and `lambda_client` are staged for the per-source SageMaker endpoint and the Monte Carlo composition Lambda described in Gap to Production"), or (b) move the client construction inside a `_build_real_clients()` helper that the production deployment would call instead of the demo, so the configuration block stays focused on resource names. Option (a) is a one-paragraph comment fix.

---

### Issue 3 — NOTE: Manual outer chunking in `deliver_forecast` is redundant given `batch_writer()` auto-chunks

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `deliver_forecast`

```python
written = 0
chunk = 25
for i in range(0, len(forecast_records), chunk):
    batch = forecast_records[i:i + chunk]
    with table.batch_writer() as bw:
        for rec in batch:
            item = { ... }
            bw.put_item(Item=item)
            written += 1
```

The boto3 resource-level `batch_writer()` already chunks into 25-item batches automatically and retries `UnprocessedItems` with exponential backoff internally. The manual outer chunking the demo performs is not how production code is written; production opens a single `batch_writer()` context for the entire list and lets the SDK handle chunking and retries. The demo's approach is correct in result (writes do happen) but teaches an unnecessary outer loop that production code would never need.

The pseudocode in the main recipe also implies the manual chunking pattern ("chunk forecast into groups of 25" appears in Step 5), so this is a consistency choice rather than a bug, but it slightly miscues the reader on the canonical production idiom. It is also identical to the pattern in 12.4 and 12.6, so a fix here should propagate.

**Fix:** Either (a) collapse to a single `batch_writer` context:

```python
written = 0
with table.batch_writer() as bw:
    for rec in forecast_records:
        item = { ... }
        bw.put_item(Item=item)
        written += 1
```

or (b) keep the outer loop as a teaching moment and add an explicit comment that production lets `batch_writer()` handle the chunking ("The outer 25-item chunk loop here is redundant; `batch_writer()` already chunks. The demo keeps the explicit loop to mirror the pseudocode's `chunk forecast into groups of 25` step. Production drops the outer loop and lets the SDK handle chunking and `UnprocessedItems` retry internally.").

---

### Issue 4 — NOTE: The Gap-to-Production claim about handling `BatchWriteItem` `UnprocessedItems` is slightly misleading

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, "Gap to Production" section

The Gap to Production section says:

> Also handle the `BatchWriteItem` `UnprocessedItems` response with exponential backoff; `MockTable` ignores this case but DynamoDB returns unprocessed items under throttling.

This advice is correct for the lower-level `boto3.client('dynamodb').batch_write_item()` API. It is **not** correct for the resource-level `boto3.resource('dynamodb').Table.batch_writer()` context manager that the demo's mock pattern mirrors and that production code in the same shape would use. The resource-level `batch_writer()` already collects items, dispatches `BatchWriteItem` calls in 25-item batches, inspects `UnprocessedItems`, and retries with exponential backoff internally. A learner who follows this advice and writes their own `UnprocessedItems` handling on top of `batch_writer()` is doing redundant work.

**Fix:** Tighten the wording: "Note that `batch_writer()` (the resource-level context manager) already handles chunking and `UnprocessedItems` retry internally with exponential backoff; the manual outer chunking the demo shows is unnecessary in production. The lower-level `boto3.client('dynamodb').batch_write_item()` API does not retry automatically and would require explicit `UnprocessedItems` handling." This clarifies which API surface the advice applies to.

---

### Issue 5 — NOTE: `generated_at_ts` is computed inside the per-record loop in `compose_census`

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `compose_census`

```python
for hour_offset in range(horizon_hours):
    forecast_for_ts = (snapshot_ts +
                       timedelta(hours=hour_offset + 1)).isoformat()
    for u_idx, unit_code in enumerate(unit_codes):
        ...
        forecast_records.append({
            ...
            "generated_at_ts":           datetime.now(timezone.utc).isoformat(),
            ...
        })
```

`datetime.now(timezone.utc)` is called once per (hour, unit) record. Across 24 hours and 5 units that is 120 separate `datetime.now()` calls, each producing a slightly different timestamp. Per-record `generated_at_ts` differing by microseconds undermines the operational meaning of the field: a consumer reading "when was this forecast cycle produced" expects one timestamp per cycle, not 120 timestamps that drift by tens of microseconds. The audit trail is also slightly less clean (a forensic question of "which cycle produced this forecast" is answered by the `run_id`, but `generated_at_ts` should be a stable per-cycle anchor too).

In production this would also add 120 system calls per cycle for no benefit; in the demo it is just a slightly muddled signal.

**Fix:** Capture once before the loop:

```python
generated_at_ts = datetime.now(timezone.utc).isoformat()
for hour_offset in range(horizon_hours):
    forecast_for_ts = (snapshot_ts +
                       timedelta(hours=hour_offset + 1)).isoformat()
    for u_idx, unit_code in enumerate(unit_codes):
        ...
        forecast_records.append({
            ...
            "generated_at_ts": generated_at_ts,
            ...
        })
```

One-line change.

---

### Issue 6 — NOTE: Mixed naive and timezone-aware ISO timestamps in forecast records

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `run_census_forecast_pipeline` and `compose_census`

`run_census_forecast_pipeline` strips the timezone from `snapshot_ts`:

```python
snapshot_ts = datetime.now(timezone.utc).replace(
    tzinfo=None, microsecond=0)
```

so `snapshot_ts.isoformat()` produces a naive string like `"2026-05-25T06:34:18"`. `forecast_for_ts` derives from `snapshot_ts + timedelta(...)` which inherits naive-ness:

```python
forecast_for_ts = (snapshot_ts +
                   timedelta(hours=hour_offset + 1)).isoformat()
```

Meanwhile `generated_at_ts` is built fresh from `datetime.now(timezone.utc).isoformat()` and is timezone-aware (`"2026-05-25T06:34:18+00:00"`). The DynamoDB record therefore has two timestamps with different conventions. As long as each timestamp is interpreted on its own (snapshot anchor vs. record creation time) this works, but the mix is inconsistent and the recipe's "Expected Results" example shows timezone-aware timestamps throughout (`"forecast_for_ts": "2026-05-25T14:00:00-05:00"`), which the Python's actual sample output does not match.

The comment on the timezone strip is also slightly off: "no microsecond" is the intent, but `tzinfo=None` is what the code does. A reader expecting a UTC-aware timestamp downstream gets a naive one.

**Fix:** Either (a) keep the timezone on `snapshot_ts`:

```python
snapshot_ts = datetime.now(timezone.utc).replace(microsecond=0)
```

so `forecast_for_ts` is also timezone-aware and matches the recipe's expected-results format, or (b) strip the timezone consistently from `generated_at_ts` too if naive UTC is the chosen convention. Option (a) matches the recipe better and is one parameter change. The downstream `datetime.fromisoformat(...)` parsers in the synthetic-input generator and the OR-schedule path also need to be aware-or-naive-consistent if option (a) is chosen.

---

### Issue 7 — NOTE: New admits during the horizon are never sampled for discharge

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `forecast_outflows` and `compose_census`

`forecast_outflows` runs the survival model only on the snapshot population (`state_records`):

```python
for record in state_records:
    per_hour, survival = survival_model.discharge_probability_per_hour(
        features=record["features"],
        snapshot_ts=snapshot_ts,
        horizon_hours=horizon_hours)
```

A patient admitted in hour 4 of the horizon (via the inflow process) has no survival model run against them and cannot discharge before the horizon ends. For a 24-hour horizon this matters less (most new admits would not discharge same-day anyway), but for the 72-hour horizon the recipe's expected-results table shows accuracy figures for, this is a real modeling limitation: a patient admitted via the OR schedule at hour 12 with a typical 60-hour ortho post-op LOS would discharge at hour 72, and the demo's pipeline silently misses that.

The pseudocode does not address this either; it is a shared simplification. Production handles it by either (a) sampling synthetic per-patient features for each new admit and running the survival model on them, or (b) using an aggregate count-based outflow model for the new-admit cohort.

**Fix:** Add a comment in the inflow section calling this out explicitly:

```python
# New admits added by the inflow process do not get a discharge
# sampled in this demo; the survival model only scores the
# snapshot population. For a 24-hour horizon this is mostly fine
# (most new admits would not discharge same-day anyway). For
# longer horizons (72+ hours), production samples synthetic
# per-patient features for each new admit and runs the survival
# model on them, or layers an aggregate count-based outflow on
# top of the per-patient outflow.
```

The pedagogical takeaway is the comment, not a code change. Optionally, the Gap to Production section could grow a "Survival sampling for in-horizon admits" bullet.

---

### Issue 8 — NOTE: `current_census_by_unit` silently drops occupants of unknown units

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `current_census_by_unit` and `compose_census`

```python
def current_census_by_unit(state_records):
    by_unit = defaultdict(int)
    for r in state_records:
        by_unit[r["current_unit"]] += 1
    return dict(by_unit)
```

If an encounter's `current_unit` is not present in `UNIT_CATALOG` (because of a typo, an ADT mapping miss, a unit that was renamed, or a unit that the bed-management team added after the catalog was last updated), the count silently aggregates under that unknown key. `compose_census` then filters with `if u in unit_index`:

```python
by_unit = current_census_by_unit(state_records)
for u, count in by_unit.items():
    if u in unit_index:
        initial_census[unit_index[u]] = count
```

so the unknown-unit count is dropped on the floor without a warning. The forecast then under-counts the hospital by the dropped occupants and the bed huddle sees a confidence interval that does not match reality. A learner copying this pattern into production would have a silent data-quality bug that takes weeks to diagnose.

**Fix:** Either (a) emit a `logger.warning` when an unknown unit is encountered, or (b) collect unknown-unit counts into a single `unknown_units` accumulator and surface them in the operational signals so the bed-management team can alarm on it. Option (a) is one line:

```python
def current_census_by_unit(state_records):
    by_unit = defaultdict(int)
    for r in state_records:
        unit = r["current_unit"]
        by_unit[unit] += 1
    unknown = set(by_unit) - set(UNIT_CATALOG)
    if unknown:
        logger.warning(
            "current_census_by_unit found %d encounters in unknown units: %s",
            sum(by_unit[u] for u in unknown), sorted(unknown))
    return dict(by_unit)
```

The pedagogical value is showing the reader that data-quality monitoring belongs even in the snapshot step.

---

### Issue 9 — NOTE: `compose_census` applies all outflows before all inflows within an hour

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `compose_census`

The hour walk in `compose_census` does outflows-then-inflows-then-overflow within each hour:

```python
for hour_offset in range(horizon_hours):
    # Apply this sample's outflows for this hour.
    for u_idx in range(n_units):
        census[u_idx] -= outflow_samples[sample_id][hour_offset][u_idx]
        ...
    # Apply this sample's inflows for this hour with overflow.
    for u_idx in range(n_units):
        ...
```

In reality discharges and admissions are interleaved throughout each hour. For hour-granularity forecasting this ordering matters less than for sub-hour granularity, but the order does subtly affect overflow behavior: if telemetry is at 28 of 28 capacity at the start of the hour and the sample has 2 outflows and 3 inflows planned, the demo subtracts 2 first (census = 26), then adds 3 (census = 28, with 1 inflow rejected and overflowed). If the order were reversed (add 3 with 0 capacity left, overflow 3; subtract 2; final census = 26 + 0 = 26 with 3 unplaced) the result is operationally different.

The current order (outflows first) is the more permissive interpretation and matches the convention used in many real bed-management simulators. It is the right choice pedagogically. But the choice is not documented, and a learner who picks the opposite convention will get materially different overflow behavior without realizing why.

**Fix:** Add a comment block at the top of the hour loop:

```python
# Order of operations within an hour: outflows first, then
# inflows with overflow. This matches the convention that a
# discharge happening at hour 14 frees the bed before any
# admission at hour 14 is placed, which is the more permissive
# interpretation. Production sometimes flips this if the
# operational model is "admissions land first, discharges
# follow", which produces a tighter (more conservative)
# overflow profile.
```

No code change.

---

### Issue 10 — NOTE: ISO timestamps in S3 keys contain `:` characters

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `forecast_inflows`, `forecast_outflows`, `compose_census`

```python
s3_key = (f"inflows/run_id={run_id}/"
          f"snapshot_ts={snapshot_ts.isoformat()}/inflows.json")
```

`snapshot_ts.isoformat()` produces strings with `:` separators, e.g., `2026-05-25T06:34:18`. S3 allows colons in object keys (they are in the [safe character set](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html)) but they require URL encoding for some downstream tools: Athena partition projection queries, Glue Data Catalog table partitions, and the S3 console URL all need careful handling of colons. boto3 handles the encoding transparently for `put_object` and `get_object`, so the demo runs cleanly, but a learner partitioning S3 prefixes by `snapshot_ts={iso_string}` and then trying to query with Athena later will hit a known gotcha.

The `snapshots/` prefix in `snapshot_current_state` already uses a safer Hive-style date partitioning (`year=...`/`month=...`/`day=...`/`hour=...`); the inflow, outflow, and trajectory paths could match this style for consistency.

**Fix:** Either (a) replace `snapshot_ts.isoformat()` in the path with a Hive-friendly format like `snapshot_ts.strftime("%Y%m%dT%H%M%S")` or `"%Y-%m-%dT%H-%M-%S"` so colons disappear from the key, or (b) match the snapshot prefix convention with `year=...`/`month=...`/`day=...`/`hour=...` partitions and an opaque filename. Option (a) is the smaller change.

---

### Issue 11 — NOTE: The `default=str` argument to `json.dumps` is unnecessary in some paths

**Severity:** NOTE
**File:** `chapter12.05-python-example.md`, `snapshot_current_state`, `forecast_inflows`, `forecast_outflows`

Multiple `s3.put_object` sites pass `default=str`:

```python
s3.put_object(Bucket=bucket, Key=s3_key,
              Body=json.dumps(state_records, default=str))
```

For `state_records`, every field is already JSON-safe (strings for IDs, ISO strings for timestamps, ints/floats/bools in the features dict). The same is true for `inflow_samples` (nested lists of ints) and `outflow_samples` (nested lists of ints). The `default=str` is defensive and harmless, but it can mask future bugs: if someone adds a `datetime` object to a record and runs the demo, the `default=str` swallows the type error and serializes whatever `str(datetime_obj)` returns (which is `2026-05-25 06:34:18` with a space, not an ISO `T`-separated string). A future reader debugging mismatched timestamps in S3 then has to figure out where the silent stringification happened.

The `compose_census` site does need `default=str` because `sample_overflow_residuals` is a list of ints (no datetimes) but the wider trajectory dict could in principle grow datetime fields; reasonable defensive choice there.

**Fix:** Drop `default=str` from the three sites where the data is fully JSON-safe and let any future type mismatch raise loudly. One-line removal per site. Alternatively, leave it in place with a comment that it is defensive and is not protecting against any current type.

---

## Summary

The Python companion is a faithful, mathematically correct implementation of the five pseudocode steps from the main recipe. The Knuth Poisson sampler, the exponential survival hazard transformation, the Monte Carlo composition with overflow redistribution, and the percentile aggregation are all correctly transcribed from their standard formulations. The `_to_decimal` helper handles the `bool`/`int`/`float`/`Decimal` discipline correctly at the DynamoDB boundary; every numeric field on every forecast record passes through it. S3 keys avoid leading slashes throughout. boto3 client and resource constructors use current service names (`s3`, `dynamodb`, `healthlake`, `events`, `cloudwatch`, `sagemaker-runtime`, `lambda`) and a current adaptive retry config. The mocks (`MockHealthLake`, `MockS3`, `MockTable`, `MockEventBus`, `MockCloudWatch`) implement the operations the demo calls and produce a runnable end-to-end pipeline against in-memory state without provisioning any AWS resources.

The findings above are NOTEs about (a) the ED-board / Poisson overlap modeling subtlety that should be called out in the inline comments, (b) module-level boto3 handles that are constructed but never exercised by the demo, (c) the manual outer chunking around `batch_writer()` that is redundant in production, (d) a Gap-to-Production claim about `UnprocessedItems` handling that does not apply to the resource-level API the demo uses, (e) `generated_at_ts` being recomputed per record instead of once per cycle, (f) inconsistent naive-vs-timezone-aware timestamp handling between `snapshot_ts` and `generated_at_ts`, (g) new admits during the horizon never being sampled for discharge, (h) `current_census_by_unit` silently dropping occupants of unknown units, (i) within-hour outflows-before-inflows ordering not being documented, (j) ISO timestamps with colons in S3 keys, and (k) defensive `default=str` arguments to `json.dumps` that mask future type mismatches.

None of these block publication. The companion teaches the right shape of a hospital census forecasting pipeline (flow not volume, three layers, per-patient survival, Monte Carlo prediction intervals, unit-level not just aggregate, capacity as a hard constraint with overflow redistribution), the comments explain the modeling choices and the production substitutions clearly, and the Gap to Production section sets expectations correctly about how far the demo is from a real deployment.

**Verdict: PASS**
