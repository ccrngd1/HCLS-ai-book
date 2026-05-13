# Code Review: Recipe 3.3 Billing Code Anomalies (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-12
**Files reviewed:**
- `chapter03.03-billing-code-anomalies.md` (main recipe, pseudocode walkthrough)
- `chapter03.03-python-example.md` (Python companion)

**Validation performed:**
- Pseudocode's five steps walked against Python functions, one-to-one
- boto3 DynamoDB resource-API calls (`Table.put_item`, `Table.get_item`, `Table.query`, `Table.update_item`, `batch_writer`) verified for parameter names, `Key` / `Attr` usage, `IndexName`, `UpdateExpression`, and `ExpressionAttribute*` shapes
- boto3 S3 `put_object`, `get_object`, `copy_object`, and `get_paginator("list_objects_v2")` calls checked for leading slashes, SSE parameters, encoding, and `ServerSideEncryption` / `SSEKMSKeyId` pairing
- boto3 Athena `start_query_execution`, `get_query_execution`, `get_query_results` call shapes verified against current API; response parsing (`ResultSet.Rows[].Data[].VarCharValue`) checked
- boto3 SageMaker Feature Store `put_record` call shape verified (`FeatureGroupName`, `Record=[{FeatureName, ValueAsString}]`)
- boto3 SNS `publish`, CloudWatch `put_metric_data` call shapes verified
- Every numeric value flowing into DynamoDB traced for Python-float writes (z-scores, stddev, percentiles, exposure, shift magnitudes, anomaly scores, peer-group stats)
- S3 keys inspected for leading slashes (none present)
- Module-load evaluated: `assert` statement, client instantiation, module-level model cache globals
- `datetime.fromisoformat` call sites inspected for `Z`-suffix handling and naive/aware mixing on external events
- Healthcare-specific: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption for signals/labels/model artifacts, retention context, CPT code correctness, subgroup-fairness discipline in retraining sketch

---

## Verdict: PASS (with reservations)

Three WARNING findings and six NOTEs. Per persona policy the threshold is "more than 3 WARNINGs means FAIL," so this lands at PASS, but it is at the boundary. The three WARNINGs are:

1. The module-load `assert` on `ANALYST_NOTIFICATION_TOPIC_ARN` uses a broken guard clause (`__name__ != "__production__"`) that never fires, so the "deploy-time guardrail" teaches a pattern that looks reasonable but does not actually guard anything. Same bug shape as Chapter 3.2 Finding 1.
2. All four S3 write paths (`_write_signal_payload`, `_write_label_to_s3`, and two calls inside `retrain_isolation_forest_quarterly`) set `ServerSideEncryption="aws:kms"` without passing `SSEKMSKeyId`, silently falling back to the AWS-managed `aws/s3` key for PHI-adjacent signal payloads, label writes, and model artifacts. Same pattern flagged in Chapter 3.1 and Chapter 3.2 reviews.
3. The Athena polling loop inside `_pull_evidence_claims` is a tight `while True` with no `time.sleep()` between `get_query_execution` calls and no max-iteration cap. A reader who copies this into a Lambda or Processing job will burn Athena API throttle budget and risk an unbounded loop if Athena never reaches a terminal state.

None of these prevent the teaching flow. Decimal discipline is consistent across every code path that touches DynamoDB (`_to_decimal` routes through `Decimal(str(value))` with `.quantize(Decimal("0.0001"))`; thresholds, z-scores, exposure, peer-group stats, and case records all stay in `Decimal` at the DynamoDB boundary). The five pseudocode steps map cleanly onto five Python functions plus a `run_monthly_pipeline` orchestrator. S3 keys are correctly formatted (`period={start}/{provider_id}.json`, `labels/year=.../month=.../day=.../{uuid}.json`, `versions/iforest-{date}.joblib`, `current/isolation_forest.joblib`), no leading slashes. Comments consistently explain the *why* (Decimal gotcha, leave-one-out correctness, peer-group definition as the highest-leverage design decision, signal-family separation, PHI-minimum SNS payload, self-confirming-label trap).

Fix the three WARNINGs and this is a clean pass. NOTEs are editorial or mirror items acknowledged in the code.

---

## Findings

### Finding 1: Module-load `assert` uses a guard clause that never fires; "deploy-time guardrail" is dead code

- **Severity:** WARNING
- **Location:** `chapter03.03-python-example.md`, Configuration block, lines 106-107
- **Description:** The Configuration block defines an example SNS topic ARN and immediately asserts a compound expression:

  ```python
  ANALYST_NOTIFICATION_TOPIC_ARN = (
      "arn:aws:sns:us-east-1:123456789012:payment-integrity-new-case"
  )
  ...
  assert "123456789012" not in ANALYST_NOTIFICATION_TOPIC_ARN or __name__ != "__production__", \
      "ANALYST_NOTIFICATION_TOPIC_ARN still uses the example AWS account ID. Replace before deploying."
  ```

  Structured as `(value_has_been_replaced) OR (we_are_not_in_production)`. The first clause is `False` (the substring `"123456789012"` is literally inside the ARN). The second clause is `True` for an unintended reason: Python's `__name__` is either `"__main__"` (when the file runs as a script) or the module name (when imported); it is never `"__production__"`. There is no Python convention that sets `__name__` that way. `False or True` is `True`, so the assert never fires. The guardrail guards nothing.

  This is the same bug shape flagged in Chapter 3.2 Finding 1. The teaching harm is that the pattern looks like a reasonable idiom and it is broken. A reader who copies `assert X != placeholder or __name__ != "__production__"` into their own config guards will think they are protected against unreplaced values and will not be.

  Secondary issue that applies to any `assert`-based runtime check: `assert` statements are removed when Python runs with `-O` (optimized mode), so even a correctly-wired assertion would silently disappear in production deployments that strip asserts.

- **How to fix:** Three options, smallest edit first:

  1. Remove the assert. The prose already tells the reader to replace the resource names.
  2. Replace with a runtime warning emitted only when a function actually tries to reach SNS:
     ```python
     if "123456789012" in ANALYST_NOTIFICATION_TOPIC_ARN:
         logger.warning(
             "ANALYST_NOTIFICATION_TOPIC_ARN still uses the example account ID; "
             "_notify_analysts will fail when it tries to publish."
         )
     ```
  3. Move the check behind a function callers invoke before deploying, keyed on an explicit environment signal instead of `__name__`:
     ```python
     def check_config_replaced() -> None:
         if os.environ.get("DEPLOYMENT_STAGE") == "prod" and \
            "123456789012" in ANALYST_NOTIFICATION_TOPIC_ARN:
             raise RuntimeError(
                 "ANALYST_NOTIFICATION_TOPIC_ARN still uses the example AWS account ID."
             )
     ```

  Option 1 is the smallest edit; option 3 is the most defensible posture if the intent is "refuse to run in production with a placeholder value."

---

### Finding 2: All four S3 write paths set SSE-KMS without specifying a customer-managed KMS key

- **Severity:** WARNING
- **Location:** `chapter03.03-python-example.md`, `_write_signal_payload` (line ~926), `_write_label_to_s3` (line ~1486), `retrain_isolation_forest_quarterly` `put_object` (line ~1682), `retrain_isolation_forest_quarterly` `copy_object` (line ~1692)
- **Description:** All four S3 write/copy paths set server-side encryption but omit the key ARN:

  ```python
  # _write_signal_payload
  s3_client.put_object(
      Bucket=ANOMALY_SIGNALS_BUCKET,
      Key=key,
      Body=json.dumps(_decimal_to_float(payload), default=str).encode("utf-8"),
      ContentType="application/json",
      ServerSideEncryption="aws:kms",
  )

  # _write_label_to_s3
  s3_client.put_object(
      Bucket=LABELS_BUCKET,
      Key=key,
      Body=json.dumps(training_row, default=str).encode("utf-8"),
      ContentType="application/json",
      ServerSideEncryption="aws:kms",
  )

  # retrain_isolation_forest_quarterly (versioned artifact)
  s3_client.put_object(
      Bucket=MODEL_ARTIFACTS_BUCKET,
      Key=version_key,
      Body=buf.read(),
      ServerSideEncryption="aws:kms",
  )

  # retrain_isolation_forest_quarterly (current pointer)
  s3_client.copy_object(
      Bucket=MODEL_ARTIFACTS_BUCKET,
      Key="current/isolation_forest.joblib",
      CopySource={"Bucket": MODEL_ARTIFACTS_BUCKET, "Key": version_key},
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias), not a customer-managed key. For PHI-adjacent workloads the difference is real: customer-managed keys let you rotate on your schedule, apply key-specific grants, audit `kms:Decrypt` per principal via CloudTrail, and revoke access by disabling the key. The AWS-managed key can neither be disabled nor scoped with custom policies.

  The signal payloads carry provider IDs plus period ranges plus peer-group keys, which is re-identifying in combination. The label archive carries the same information plus disposition and exposure, and is explicitly the feed to the supervised retraining workflow. The model artifact bucket is less obviously PHI-bearing but a leaked Isolation Forest model can be inverted to approximate training-data characteristics; policy posture should match. The main recipe's Gap to Production section is explicit: "All data at rest (DynamoDB tables, S3 buckets, Feature Store offline and online stores, CloudWatch Logs, Athena results) is encrypted with customer-managed KMS keys." The Python companion does not demonstrate the pattern the prose requires.

  Same gap as Chapter 3.1 Finding 2 and Chapter 3.2 Finding 2.

- **How to fix:** Add key-ARN constants near the top of the Configuration block and pass them through on all four calls:

  ```python
  SIGNALS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."
  LABELS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."
  MODEL_ARTIFACTS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."

  # _write_signal_payload
  s3_client.put_object(
      Bucket=ANOMALY_SIGNALS_BUCKET,
      Key=key,
      Body=json.dumps(_decimal_to_float(payload), default=str).encode("utf-8"),
      ContentType="application/json",
      ServerSideEncryption="aws:kms",
      SSEKMSKeyId=SIGNALS_CMK_ARN,
  )
  ```

  Same pattern for the other three call sites with the matching key constants. Document the constants with a one-line comment: "Customer-managed KMS key ARN. Separate keys per bucket so rotation and access grants can be scoped independently."

---

### Finding 3: Athena polling loop in `_pull_evidence_claims` has no sleep between polls and no iteration cap

- **Severity:** WARNING
- **Location:** `chapter03.03-python-example.md`, `_pull_evidence_claims` (Step 4), lines ~1147-1155
- **Description:** The Athena query-completion poll is a tight loop:

  ```python
  # Poll for completion. Real deployments drive this via Step Functions
  # so the polling is framework-managed; here we loop for illustration.
  while True:
      state = athena.get_query_execution(QueryExecutionId=execution_id)
      status = state["QueryExecution"]["Status"]["State"]
      if status in ("SUCCEEDED", "FAILED", "CANCELLED"):
          break
  ```

  Three problems in one block:

  1. **No `time.sleep()` between polls.** The loop will call `GetQueryExecution` as fast as the network allows. Athena's control-plane API has throttle limits (by default 20 requests per second per account for `GetQueryExecution`); a single evidence pull for one case will plausibly saturate the limit for the whole account in under a second. For a monthly assembly run that processes tens of cases, the throttling cascades and later `get_query_execution` calls start throwing `ThrottlingException`, which this loop does not handle.

  2. **No max-iteration or max-wall-time cap.** If Athena never reaches a terminal state (a queued query behind a busy workgroup, or a control-plane issue), the loop spins forever. The comment's framing ("Real deployments drive this via Step Functions") does not protect the reader who runs this code as-is.

  3. **No error handling around `get_query_execution`.** A `ThrottlingException`, `InvalidRequestException`, or transient network error propagates out of the loop, which for the case-assembly Lambda means the entire per-provider case build fails and the signal payload stays in S3 orphaned.

  The comment acknowledges the Step Functions framing but does not address the missing sleep, which is the most common and most damaging of the three issues. A reader who sees `while True: ... break on terminal status` treats this as an idiomatic pattern and carries it into production.

- **How to fix:** Add a sleep, a cap, and a basic throttling-aware retry:

  ```python
  import time
  ...
  MAX_POLL_SECONDS = 120
  POLL_INTERVAL_SECONDS = 1.0

  deadline = time.monotonic() + MAX_POLL_SECONDS
  while time.monotonic() < deadline:
      state = athena.get_query_execution(QueryExecutionId=execution_id)
      status = state["QueryExecution"]["Status"]["State"]
      if status in ("SUCCEEDED", "FAILED", "CANCELLED"):
          break
      time.sleep(POLL_INTERVAL_SECONDS)
  else:
      logger.warning("evidence_query_timeout", extra={
          "provider_id": provider_id,
          "execution_id": execution_id,
      })
      return []
  ```

  The `time.sleep(1)` is the single most important change. The deadline guard prevents the infinite-loop failure mode. Note that the adaptive-retry Boto3 `Config` at the top of the module does handle `ThrottlingException` inside each individual `get_query_execution` call, so no explicit retry is needed beyond that.

---

### Finding 4: Module logger has no handler configured; `logger.info` / `logger.warning` calls drop silently in the `__main__` run

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, Configuration block (`logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)`)
- **Description:** Same pattern flagged in Chapter 3.1 Finding 4 and Chapter 3.2 Finding 4. Without `logging.basicConfig(...)` or an explicit handler, calls like `logger.info("rollup_complete", ...)`, `logger.info("cases_assembled", ...)`, and `logger.warning("evidence_query_failed", ...)` do not reach the console when the file runs as `__main__`. The `run_monthly_pipeline` orchestrator's `print("[1/4] ...")` statements keep step narration visible, but the structured logs (which are the more useful artifacts for a learner tracing a run) disappear. In Lambda this is not an issue (Lambda configures a root handler), but the `if __name__ == "__main__":` block is the first way most readers exercise the code.
- **How to fix:** Add one line near the top of the Configuration block:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document as "visible when running this file directly; Lambda configures its own handler and this becomes a no-op there."

---

### Finding 5: `EM_CODES` includes 99201, which was deleted from CPT in 2021

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, Configuration block, line 191
- **Description:** The E&M code mapping includes `99201`:

  ```python
  EM_CODES = {
      # Office or outpatient, established patient (levels 1-5).
      "99211": 1, "99212": 2, "99213": 3, "99214": 4, "99215": 5,
      # Office or outpatient, new patient (levels 1-5).
      "99201": 1, "99202": 2, "99203": 3, "99204": 4, "99205": 5,
  }
  ```

  CPT 99201 was deleted effective January 1, 2021 as part of the CMS/AMA E/M documentation overhaul. Current new-patient office/outpatient codes are 99202-99205 (levels 2-5); level 1 for new patients no longer exists. The recipe explicitly dates sample data to 2026 (`"service_date": "2026-05-10"`), so including 99201 is incorrect for the recipe's own stated timeframe.

  The consequence for a reader is small (the code will simply never match against real 2026 claims, because no one bills 99201 anymore), but including a deleted code in the canonical lookup table teaches that the crosswalk does not need to be maintained against the CPT update calendar, which is the opposite of the lesson a billing-anomaly pipeline should convey. The comment above the table does say "Real deployments use a much larger crosswalk including hospital, nursing facility, home, and specialty E/M ranges," but it does not caution that the codes in the example itself may be stale.

- **How to fix:** Remove 99201 from the mapping and update the comment:

  ```python
  EM_CODES = {
      # Office or outpatient, established patient (levels 1-5).
      "99211": 1, "99212": 2, "99213": 3, "99214": 4, "99215": 5,
      # Office or outpatient, new patient (levels 2-5; 99201 was
      # deleted effective 2021-01-01 and is intentionally omitted).
      "99202": 2, "99203": 3, "99204": 4, "99205": 5,
  }
  ```

  The one-line comment names the omission, which turns the absence into a teaching point rather than a silent oversight.

---

### Finding 6: `_query_prior_cases` uses `Key(...)` in `FilterExpression` and is not paginated

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, `_query_prior_cases` (Step 4)
- **Description:** Two small issues in the same DynamoDB call:

  ```python
  response = table.query(
      IndexName="provider_id_index",
      KeyConditionExpression=Key("provider_id").eq(provider_id),
      FilterExpression=Key("period_start").gte(cutoff),
  )
  return response.get("Items", [])
  ```

  First, `FilterExpression` should use `boto3.dynamodb.conditions.Attr`, not `Key`. Both classes share a base that supports `.gte()`, so the call works, but the idiomatic and documented form is `Attr("period_start").gte(cutoff)`. A reader copying this pattern into their own code may not realize that the `Key` class is for the key schema specifically; mixing the two is a code smell.

  Second, the query is unpaginated. Same class of issue as Chapter 3.1 Finding 7 and Chapter 3.2 Finding 6. In this specific case the practical risk is low because a single provider rarely has more than a handful of cases in a 3-month lookback window, and each case record is small. But `FilterExpression` applies *after* the 1 MB page limit on the GSI query, which means a hot provider with many historical cases could produce a result where the returned items are a truncated slice before filtering, and `persistence` comes back artificially low. The case record then reports fewer consecutive periods than the provider actually has, which weakens the severity calculation.

- **How to fix:** Use `Attr` and add pagination:

  ```python
  from boto3.dynamodb.conditions import Attr

  items = []
  params = {
      "IndexName": "provider_id_index",
      "KeyConditionExpression": Key("provider_id").eq(provider_id),
      "FilterExpression": Attr("period_start").gte(cutoff),
  }
  while True:
      response = table.query(**params)
      items.extend(response.get("Items", []))
      if "LastEvaluatedKey" not in response:
          break
      params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
  return items
  ```

  Or if keeping the single-page version for teaching simplicity, strengthen the existing comment (there is none today) to name the specific failure mode: "In production, paginate with LastEvaluatedKey; a single query caps at 1 MB per response and FilterExpression applies after that cap, so persistence will be understated for providers with many historical cases."

---

### Finding 7: Outcome event payload is trusted without validation; missing fields propagate as `KeyError`

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, `on_investigation_outcome` (Step 5)
- **Description:** The handler directly indexes required event fields with no pre-validation:

  ```python
  def on_investigation_outcome(event: dict) -> None:
      case_id = event["case_id"]
      ...
      ":disp":         event["disposition"],
      ":notes":        event.get("notes", ""),
      ":resolved_at":  event["resolved_at"],
      ":resolved_by":  event["resolved_by"],
      ":dollars":      _to_decimal(event.get("dollars_recovered", 0.0)),
  ```

  A malformed EventBridge payload (missing `case_id`, `disposition`, `resolved_at`, or `resolved_by`) raises `KeyError` from the handler. EventBridge treats the unhandled exception as a retry-eligible failure; at-least-once delivery plus no idempotency guard means a persistently-malformed event retries indefinitely until it ages out of the event bus and lands in the DLQ. In the meantime the handler spams error logs and consumes Lambda-invocation budget.

  Chapter 3.1's companion established the pattern: a dedicated `_validate_verdict_event` helper that raises `ValueError` with a specific message for each missing-or-bad field before touching any downstream state. Chapter 3.3 does not bring the pattern forward, and the `_derive_label` function's handling of unknown dispositions (returns `"unknown"` and excludes from training) is a partial safety net that fires after the handler has already tried to update DynamoDB.

- **How to fix:** Add a one-line validator and call it first:

  ```python
  REQUIRED_OUTCOME_FIELDS = {"case_id", "disposition", "resolved_at", "resolved_by"}

  def _validate_outcome_event(event: dict) -> None:
      missing = REQUIRED_OUTCOME_FIELDS - set(event.keys())
      if missing:
          raise ValueError(f"outcome event missing required fields: {sorted(missing)}")
      if not isinstance(event.get("disposition"), str):
          raise ValueError(f"disposition must be a string; got {type(event.get('disposition'))}")

  def on_investigation_outcome(event: dict) -> None:
      _validate_outcome_event(event)
      ...
  ```

  Optionally narrow the accepted `disposition` values to a controlled vocabulary (same approach as Chapter 3.1's `VALID_VERDICTS`) so the label-derivation path is not the first place a bad disposition is caught.

---

### Finding 8: `_to_decimal` silently masks NaN and Inf to zero; error signal is lost

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, `_to_decimal` (Configuration block)
- **Description:** The Decimal coercion helper treats `NaN` and `Inf` as if they were zero:

  ```python
  def _to_decimal(value) -> Decimal:
      ...
      if value is None:
          return Decimal("0.0000")
      if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
          return Decimal("0.0000")
      return Decimal(str(value)).quantize(Decimal("0.0001"))
  ```

  DynamoDB does reject `Decimal("NaN")` and `Decimal("Infinity")`, so the helper has to do something. Silently coercing to zero is the most dangerous choice: a `NaN` in a z-score, shift magnitude, or exposure computation is a signal that upstream math produced an undefined result (divide by zero in the leave-one-out stddev, an empty feature series, missing history), and turning that into `Decimal("0.0000")` tells the downstream case-assembly layer that the signal is cleanly zero when it is actually unknown. A provider-period with a legitimately undefined peer-z-score now stores as `zscore: 0.0000` and never fires a signal.

  The pattern this file inherits from Chapter 3.2 uses the same helper shape, but Chapter 3.2's call sites do not produce many NaN/Inf inputs (the scorer's output is always a bounded probability). Here the CUSUM and z-score math can legitimately produce NaN when the baseline or peer stddev is zero, and the helper silently swallows that case. A loud failure (raise `ValueError`) would at least prevent a zero-severity case from being created from undefined math; the current behavior makes the error invisible.

- **How to fix:** Either raise, or return a sentinel the downstream code explicitly checks for:

  ```python
  def _to_decimal(value) -> Decimal:
      if isinstance(value, Decimal):
          return value
      if value is None:
          return Decimal("0.0000")
      if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
          # NaN / Inf usually mean upstream math is undefined (zero stddev,
          # empty series). Loud failure is safer than a silent zero, which
          # would create a misleading zero-severity signal downstream.
          raise ValueError(f"_to_decimal received non-finite value: {value!r}")
      return Decimal(str(value)).quantize(Decimal("0.0001"))
  ```

  If the raise-on-NaN posture is too aggressive for the teaching example, at minimum strengthen the comment to name the masking behavior and route the caller toward an explicit check: "Callers that may produce NaN (divide-by-zero in z-score or CUSUM) should guard and skip the signal rather than relying on this helper to coerce silently."

---

### Finding 9: `_emit_metric` casts `dollars_recovered` to `int`, dropping cents

- **Severity:** NOTE
- **Location:** `chapter03.03-python-example.md`, `on_investigation_outcome` (Step 5)
- **Description:** The dollars-recovered metric is emitted with a cast to `int`:

  ```python
  _emit_metric(
      "dollars_recovered",
      value=int(event.get("dollars_recovered", 0.0)),
      dimensions={"severity": case["overall_severity"]},
  )
  ```

  `_emit_metric`'s signature is `(metric_name: str, value: int = 1, dimensions: dict = None)`, so the cast is to satisfy the type hint. But CloudWatch `put_metric_data`'s `Value` field accepts float, not just int; the cast drops up to 99 cents per case. For a program that emits this metric on every closed case and rolls it up into a monthly recovery total, the dropped cents accumulate. Over a year with tens of thousands of closed cases, the metric can be off by hundreds of dollars relative to the true total. Not a catastrophe, but for a metric whose whole purpose is to report how much money the program recovered, the rounding in the wrong direction is awkward.

- **How to fix:** Either loosen the `_emit_metric` signature to accept float:

  ```python
  def _emit_metric(metric_name: str, value: float = 1, dimensions: dict = None) -> None:
      ...
      "Value": value,
  ```

  and drop the `int()` cast at the call site, or emit the value in cents (`int(dollars * 100)`) with a `CentsOrDollars` unit dimension. The first option is simpler and matches how CloudWatch treats the value internally.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function(s) | Consistent? |
|-----------------|---------------------|---------------------|-------------|
| Step 1 | `rollup_provider_period(period_start, period_end)` | `rollup_provider_period(claims_df, period_start, period_end)` + `_compute_provider_features` + `write_features_to_feature_store` + helpers `_shannon_entropy`, `_modifier_rate` | Yes. Python adds `claims_df` argument in place of the pseudocode's Athena query; heads-up block acknowledges this simplification. Feature list, low-volume guard, E&M distribution rule, modifier-rate computation, and unit-mode fraction all map directly |
| Step 2 | `assign_peer_groups()` + per-group distribution statistics | `assign_peer_groups(provider_master_df)` + `compute_peer_group_statistics(features_df, peer_assignments)` + helper `_count_all_candidate_groups` + `_leave_one_out_stats` | Yes. Split into two functions (assignment vs. statistics) matches pseudocode's two-phase framing. Leave-one-out implementation uses the sum/sumsq sufficient-statistics trick, documented in the comment; math verified against standard sample-variance formula |
| Step 3 | `score_anomalies(period_start, period_end)` | `score_anomalies(features_df, history_df, peer_assignments, period_start, period_end)` + `_score_peer_zscores`, `_score_self_cusum`, `_score_isolation_forest`, `_load_isolation_forest`, `_write_signal_payload` + severity helpers | Yes. Three signal families kept separate as the pseudocode and recipe prose both emphasize; each signal's rich metadata (peer_mean, baseline_mean, top_contributors, severity) survives into the JSON payload; per-file S3 layout matches |
| Step 4 | `assemble_cases(period_start)` | `assemble_cases(period_start, period_end)` + `_assemble_one_case`, `_query_prior_cases`, `_count_consecutive_periods`, `_pull_evidence_claims`, `_overall_severity`, `_determine_routing`, `_build_narrative`, `_case_for_dynamo`, `_signal_for_dynamo`, `_notify_analysts`, `_emit_metric` | Yes. Consolidation, persistence check, evidence pull, severity scoring, routing, capacity-cap-with-bump, and notification all match pseudocode. Adds `period_end` parameter and the `PAYMENT_INTEGRITY_QUEUE_CAPACITY` cap with `watch_list` overflow, both of which the recipe narrative describes but the pseudocode does not spell out |
| Step 5 | `on_investigation_outcome(event)` | `on_investigation_outcome` + helpers `_derive_label`, `_outcome_lag_days`, `_write_label_to_s3` | Yes. Case update, label derivation, definitive-only filter for the supervised training path, and metric emission all match. No validator on the event payload (Finding 7) |
| Retrain | `retrain_supervised_quarterly()` (referenced only) | `retrain_isolation_forest_quarterly` + placeholder `_load_training_window` | Partial. Main recipe names both the Isolation Forest retrain and the supervised retrain; Python implements only the Isolation Forest sketch. Comment at the end explicitly defers the supervised retrain to Recipe 3.2's code template, which is a reasonable pedagogical choice |

The `run_monthly_pipeline` orchestrator chains Steps 1 through 4 (rollup → peer assignment → scoring → case assembly). Step 5 and the retrain run separately (EventBridge-triggered Lambda, EventBridge-scheduled training job), which matches the pseudocode and recipe framing.

---

## AWS SDK Accuracy

### DynamoDB
- `dynamodb.resource("dynamodb", ...)` and `table.put_item / get_item / query / update_item / batch_writer`: current API shapes
- `table.query(IndexName="provider_id_index", KeyConditionExpression=Key("provider_id").eq(...), FilterExpression=Key("period_start").gte(...))`: functional but idiomatically should use `Attr` for the FilterExpression (Finding 6)
- `table.update_item(Key=..., UpdateExpression=..., ExpressionAttributeNames=..., ExpressionAttributeValues=...)` in `on_investigation_outcome`: correct; `#status` alias used because `status` is a reserved word
- `table.batch_writer()` context manager in `assign_peer_groups`: correct, auto-batches and retries
- Every numeric value reaching DynamoDB is `Decimal`, string, int, or a nested dict/list of the same. No Python float on any write path (see Decimal section below)

### S3
- `s3_client.put_object`, `get_object`, `copy_object`: parameter names correct
- `s3_client.get_paginator("list_objects_v2").paginate(Bucket=..., Prefix=...)` in `_list_signal_payloads`: correct
- Keys use partition-style paths (`period={start}/{provider_id}.json`, `labels/year=.../month=.../day=.../{uuid}.json`, `versions/iforest-{date}.joblib`, `current/isolation_forest.joblib`), no leading slashes, no `s3://` scheme leakage
- `SSEKMSKeyId` missing on all four write/copy sites (Finding 2)

### Athena
- `athena.start_query_execution(QueryString=..., QueryExecutionContext={"Database": ...}, ResultConfiguration={"OutputLocation": ...})`: current shape
- `athena.get_query_execution(QueryExecutionId=...)` and `athena.get_query_results(QueryExecutionId=...)`: correct
- Result parsing (`response["ResultSet"]["Rows"][0]["Data"][i]["VarCharValue"]`, skipping header row): matches the real response shape
- Polling loop issue (Finding 3)
- SQL string interpolation: the inline comment names the risk ("use parameterized queries... do not copy this pattern for any external-input code path") and `_sql_escape` is applied to `provider_id`; `period_start` and `period_end` are not escaped but come from system config, which the comment justifies. Acceptable for teaching with the caveat noted

### SageMaker Feature Store Runtime
- `featurestore_runtime.put_record(FeatureGroupName=..., Record=[{"FeatureName": ..., "ValueAsString": ...}])`: parameter names match current API
- `event_time` record entry is added at the end with the period_end value: correct
- Complex fields (dicts) JSON-encoded before conversion to string: correct pattern; scorer decodes back

### SNS
- `sns.publish(TopicArn=..., Message=..., Subject=...)`: correct
- `Message` is a JSON-encoded string of a minimal payload (case_id, provider_id, severity, routing, created_at); no PHI in the notification body, which the comment explicitly requires. Pass

### CloudWatch
- `cloudwatch.put_metric_data(Namespace="BillingAnomaly", MetricData=[{MetricName, Value, Unit, Dimensions}])`: current shape
- `ScorerVersion` dimension on every metric: right pattern for attributing metric shifts
- Try/except around `put_metric_data` with a warning log: appropriate; metric-emission failures do not block the pipeline
- `int()` cast on `dollars_recovered` drops cents (Finding 9)

### EventBridge
- `eventbridge = boto3.client("events", ...)` is instantiated but the module never calls `put_events` or any other method on it. Setup acknowledges this as consumption-only ("for publishing investigation-outcome events from the analyst workstation side"), matching Chapter 3.2's posture. Following Chapter 3.2's precedent, not raising as a finding; the Step 5 flow is fundamentally an EventBridge consumer and the client declaration is forward-looking. Noting here for completeness

### Boto3 Config
- `Config(retries={"max_attempts": 5, "mode": "adaptive"})`: current parameter names, appropriate for bursty monthly scoring. Rationale explained in the comment above the config block

---

## DynamoDB Decimal Check

- `_to_decimal` helper routes through `Decimal(str(value))` with `.quantize(Decimal("0.0001"))`, avoiding binary-precision drift. Masks NaN/Inf to zero (Finding 8) but does coerce int, float, and None correctly
- `_decimal_to_float` recursively inverts the coercion for JSON output and ML input; pairs cleanly with `_to_decimal`
- `Z_SIGNAL_THRESHOLD` and `ISOLATION_FOREST_THRESHOLD` are `Decimal` constants; `CUSUM_H` and `CUSUM_K` are `float` because the CUSUM math stays in float through the scorer (results are Decimal-ified before DynamoDB writes). Comparison `abs(z) >= float(Z_SIGNAL_THRESHOLD)` converts to float at comparison time: works, even if idiomatically inconsistent
- `compute_peer_group_statistics`: `stats = {"count": int(...), "sum": float(...), "sumsq": float(...), "mean": float(...), "stddev": float(...), "p50/p90/p95/p99": float(...)}`, then `{k: _to_decimal(v) for k, v in stats.items()}` at write time. No float reaches DynamoDB
- `_score_peer_zscores`: every numeric value in the returned signal dict (`value`, `peer_mean`, `peer_stddev`, `zscore`) passes through `_to_decimal`. `_leave_one_out_stats` math stays in float but the results are Decimal-ified before the dict is emitted
- `_score_self_cusum`: same pattern; `pre_change_mean`, `post_change_mean`, `shift_magnitude`, `baseline_stddev` all `_to_decimal`
- `_score_isolation_forest`: `anomaly_score` is `_to_decimal(score)`; top-contributor entries' `value`, `training_mean`, `zscore` all `_to_decimal`
- `_case_for_dynamo`: `exposure_dollars` converted to Decimal; `_signal_for_dynamo` recursively walks the signal dicts converting floats to Decimals
- `on_investigation_outcome`'s `update_item`: `:dollars` is `_to_decimal(event.get("dollars_recovered", 0.0))`, correct

Result: no Python float reaches DynamoDB in any code path. Pass (modulo the NaN-masking note in Finding 8, which is a semantic issue rather than a type-correctness issue).

---

## S3 Key Check

Keys inspected:

- `period={payload["period_start"]}/{payload["provider_id"]}.json` (`_write_signal_payload`)
- `labels/year={resolved_dt.year:04d}/month={resolved_dt.month:02d}/day={resolved_dt.day:02d}/{uuid.uuid4()}.json` (`_write_label_to_s3`)
- `versions/iforest-{datetime.now(timezone.utc).strftime('%Y%m%d')}.joblib` (versioned artifact)
- `current/isolation_forest.joblib` (current pointer)
- Default model load key: `current/isolation_forest.joblib`

All keys use forward-slash partitioning, no leading slashes, no reserved characters. UUID-based leaf for labels, provider-ID-based leaf for signal payloads, and date-versioned leaf for model artifacts all avoid collisions.

Pass.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Logger setup comment: "Claim and provider records are PHI-adjacent (an NPI plus a date range plus a patient population is re-identifying even without names), so we log structural metadata only. Never log full claim bodies, patient identifiers, or full feature vectors in regular application logs." Inline calls respect this: `logger.info("rollup_complete", extra={"period": period_start, "providers_scored": ..., "providers_skipped_low_volume": ...})`, `logger.info("cases_assembled", extra={...counts only...})`, `logger.info("scoring_complete", ...)`. No provider IDs in high-volume log calls, no feature vectors in logs. Pass.
- **Minimum-PHI SNS payload.** `_notify_analysts` builds a message with only case_id, provider_id, severity, routing, and created_at. The comment names the rule: "The message carries the case id only; the analyst UI fetches the full record by id so the notification channel never carries PHI." Provider ID is in the message (arguably more than the comment claims), but no claim content, no peer-group key, no signal details. Reasonable for payer-side notifications. Pass.
- **Encryption at rest.** S3 writes set SSE-KMS; the key is the AWS-managed default rather than a customer-managed key (Finding 2). DynamoDB encryption configuration is out of the Python code's scope (set at table creation time) and the main recipe's Prerequisites table covers it. Pass modulo Finding 2.
- **Synthetic data labeling.** Heads-up block and the `__main__` sample both label the data as synthetic: "All example provider, claim, and patient data is synthetic. Provider IDs, NPIs, CPT codes, claim IDs, and patient IDs in the sample data and outputs are illustrative and do not refer to any real people, providers, or services. Use Synthea in a development environment and never use real PHI in a teaching example." Pass.
- **BAA / HIPAA context.** All services (DynamoDB, S3, SageMaker Feature Store Runtime, CloudWatch, EventBridge, Athena, SNS) are HIPAA-eligible under the AWS BAA. Main recipe's Prerequisites table confirms. Pass.
- **CPT code accuracy.** 99201 in `EM_CODES` is stale (Finding 5). `TIME_BASED_CODES` list is plausible, non-exhaustive, and labeled as such in the comment. Pass with caveat.
- **Subgroup fairness discipline.** The Isolation Forest retrain sketch does not include subgroup monitoring, which the main recipe explicitly requires ("Build the subgroup dashboard into the initial deployment, with thresholds that escalate to the health equity team when a subgroup's flag rate is more than 1.5x the overall rate for more than two consecutive periods"). The Python companion defers this to a "retraining pipeline" it does not implement, and also defers the supervised-classifier retrain (which is where Chapter 3.2's subgroup-regression gate lives) back to Chapter 3.2. Pedagogically reasonable, but a reader building from this file who does not cross-reference Chapter 3.2 will not learn the fairness-gate pattern from 3.3 alone. Pass in architecture, with note.
- **Self-confirming label warning.** Comment above `on_investigation_outcome`: "The trap to avoid here is self-confirming labels... The 'periodically random-sample unflagged providers for review' discipline in the main recipe is what breaks this loop; implement it in operational practice, not just the model training code." Names the failure mode and points at the operational mitigation. Pass.
- **Retention.** Main recipe's Gap to Production section covers retention (6-year HIPAA baseline, 7-10 years anti-fraud specific, Object Lock COMPLIANCE mode for the labels bucket). Python code does not enforce Object Lock at `put_object` time (correct: Object Lock is bucket-level). Pass.

---

## Comment Quality

Comments consistently explain *why*, not just *what*. High-value examples:

- "All numeric scores must be Decimal. DynamoDB rejects Python `float` for numeric attributes (precision loss, which for z-scores and severity aggregation is a quiet disaster over thousands of case writes)." Names the gotcha and the specific accounting-level failure mode it produces.
- "The single most consequential design decision in this whole recipe is the peer group definition. Whatever groups you define on day one you will redefine within three months based on what the payment integrity team tells you. Make the fallback order config-driven... rather than hard-coded through the logic; you will edit it." Frames `PEER_GROUP_FALLBACK_ORDER`'s existence as a constant in operational terms.
- "The one subtle bit to get right: leave-one-out. The peer-group statistics used to score provider X must not include provider X in the computation. If you leave them in, an extreme outlier pulls the group mean toward themselves and their own z-score is artificially low." Ties the sum/sumsq trick to the correctness property.
- "Keep this deterministic and explainable rather than LLM-generated; an analyst who scans twenty cases an hour needs consistent phrasing." On `_build_narrative`: states why templated narrative beats LLM-generated narrative for this specific use case.
- "The message carries the case id only; the analyst UI fetches the full record by id so the notification channel never carries PHI." On SNS publish: names the minimum-PHI rule and the architecture that enforces it.
- "Every anomaly signal, case record, and captured label records the scorer version. This is how retraining picks its training window and how monitoring attributes regressions to a specific version of the pipeline." On `SCORER_VERSION`: names the two downstream uses of the field.
- "Providers with fewer than MIN_CLAIMS_FOR_STATS claims in a period produce unstable aggregate statistics. Peer groups with fewer than PEER_GROUP_MIN_SIZE members produce unstable peer statistics. Both guards exist to keep the signal-to-noise ratio defensible on the sparse tails." Explains why both thresholds are needed and what happens without them.
- Step headers explicitly reference the pseudocode function: "*The pseudocode calls this `rollup_provider_period(period_start, period_end)`.*" Makes cross-file navigation easy.
- Heads-up block enumerates every production gap (no real warehouse integration, no Glue wrapping, no Step Functions orchestration, no SageMaker Processing wrapper, no QuickSight, no subgroup fairness monitoring harness, no case-lineage across periods, no Isolation Forest retraining pipeline, no analyst UI). Pedagogically honest.
- Gap to Production section is extensive and honest: real claims warehouse integration, idempotency, error handling, structured logging with PHI discipline, IAM scoping, VPC deployment, KMS customer-managed keys, SageMaker wrapping for the scorer, Athena query safety, provider entity resolution, peer group refresh cadence, Isolation Forest retraining cadence, supervised classifier discipline, subgroup fairness monitoring, case lineage across periods, analyst tooling, monitoring and alarms, retention and legal hold, testing, Decimal serialization, cost per investigated case.

---

## Logical Flow

The file reads cleanly top-to-bottom:

1. Heads-up block (scope and production caveats)
2. Setup (dependencies, IAM, knowns-upfront)
3. Configuration and constants (retry config, clients, resource names, scorer version, volume guards, thresholds, case-routing constants, feature lists, E&M code mapping, time-based codes, peer-group fallback order, `_to_decimal` / `_decimal_to_float` helpers)
4. Step 1: `rollup_provider_period` + `_compute_provider_features` + helpers + `write_features_to_feature_store`
5. Step 2: `assign_peer_groups` + `_count_all_candidate_groups` + `compute_peer_group_statistics` + `_leave_one_out_stats`
6. Step 3: `_load_isolation_forest` + `score_anomalies` + `_score_peer_zscores` + `_score_self_cusum` + `_score_isolation_forest` + severity helpers + `_write_signal_payload`
7. Step 4: `assemble_cases` + `_list_signal_payloads` + `_assemble_one_case` + `_query_prior_cases` + `_count_consecutive_periods` + `_pull_evidence_claims` + `_sql_escape` + `_overall_severity` + `_determine_routing` + `_severity_rank` + `_build_narrative` + `_case_for_dynamo` + `_signal_for_dynamo` + `_notify_analysts` + `_emit_metric`
8. Step 5: `on_investigation_outcome` + `_derive_label` + `_outcome_lag_days` + `_write_label_to_s3`
9. Full monthly pipeline: `run_monthly_pipeline` orchestrator + `__main__` example
10. Quarterly Isolation Forest retrain sketch: `retrain_isolation_forest_quarterly` + `_load_training_window` placeholder
11. Gap to Production

The orchestrator's step-by-step `print` statements make the flow visible in a direct run, though the structured logger is not wired to a handler (Finding 4). The `__main__` example is minimal; it exercises the rollup and case-assembly paths but most signals stay silent because the example ships with empty peer-group stats, empty history, and no trained Isolation Forest. The prose explicitly names this ("Running this against empty peer-group and history tables means the peer z-score and CUSUM paths stay silent...").

---

## What Is Clean

- `_to_decimal` helper applied consistently; no Python float reaches DynamoDB in any code path
- `_decimal_to_float` provides the clean inverse for JSON writes and ML inputs
- Leave-one-out peer statistics implemented via the sum/sumsq sufficient-statistics trick rather than recomputing per-scoring-call; math verified against standard sample-variance formula
- Three signal families (peer z-scores, self-history CUSUM, multivariate Isolation Forest) kept architecturally separate all the way through the case record; the narrative builder can explain which family fired without any post-hoc attribution
- Capacity-cap-with-bump logic in `assemble_cases`: high-severity cases are sorted by severity and exposure, the top N kept in the payment-integrity queue, the rest bumped to the watch list with a `"capacity_bump"` reason, so no case is silently dropped
- Minimum-volume guards at three layers (provider claim count in rollup, E&M count for distribution computation, peer-group member count for stable stats); each guard is named and documented
- Scorer version and label-derivation version threaded through every signal payload, case record, and training row; retraining can attribute performance shifts to specific releases
- Isolation Forest contribution explanation uses training-time means and stddevs captured in the model metadata, not recomputed on the fly; comment correctly flags this as a SHAP proxy and points at the `shap` library for production-grade attribution
- `PAYMENT_INTEGRITY_QUEUE_CAPACITY` constant makes the operational-capacity cap a configuration knob, which the recipe names as one of the most frequently-tuned parameters
- Narrative summary is template-driven and deterministic; the comment explicitly names "keep this deterministic and explainable rather than LLM-generated"
- Heads-up block, Gap to Production section, and inline "why" comments together frame the file as "sketchpad, not pipeline," which matches the project's pedagogical posture

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The five pseudocode steps map cleanly onto Python functions, the three signal families stay architecturally separate through case assembly, the leave-one-out peer-statistics trick is implemented correctly, and the Decimal discipline carries through every DynamoDB boundary. The `PEER_GROUP_FALLBACK_ORDER` constant at the top of the module, the capacity-cap-with-bump pattern in `assemble_cases`, and the template-driven narrative builder all demonstrate production-grade payment-integrity design that a reader will benefit from copying.

The three WARNINGs are fixable in under an hour each. Finding 1 (broken `__name__ != "__production__"` assert) is the same dead-guard pattern flagged in Chapter 3.2 Finding 1; remove the assert or replace with an explicit `check_config_replaced()` function gated on `os.environ.get("DEPLOYMENT_STAGE")`. Finding 2 (missing `SSEKMSKeyId` on all four S3 write/copy sites) mirrors Chapter 3.1 Finding 2 and Chapter 3.2 Finding 2 one-for-one; add key-ARN constants and pass them through. Finding 3 (tight Athena polling loop) is the only new class of issue for Chapter 3; add `time.sleep(1)` and a deadline guard so the loop cannot spin or burn API budget.

The NOTEs are editorial or mirror items acknowledged elsewhere (logger handler, unpaginated query, `datetime.fromisoformat` hardening). The 99201-is-deprecated note (Finding 5) and the `_to_decimal` NaN-masking note (Finding 8) are healthcare-specific and worth a small comment even if the code change is minor. The missing outcome-event validator (Finding 7) is the most consequential NOTE because it brings the Chapter 3.1 `_validate_verdict_event` pattern forward; implementing it prevents a malformed EventBridge payload from retrying indefinitely against a DynamoDB `update_item` call that will never succeed.

With the three WARNINGs addressed this becomes a clean pass. The overall quality is on par with Chapter 3.2 and carries the Decimal and PHI discipline through cleanly.

---

## Re-review Checklist

When this review is addressed, a re-reviewer should verify:

1. The `assert` on `ANALYST_NOTIFICATION_TOPIC_ARN` is either removed, converted to a runtime log-and-continue warning, or replaced with an explicit `check_config_replaced()` function gated on an environment signal (not `__name__`). The module can be imported with the placeholder values in place.
2. All four S3 write/copy call sites (`_write_signal_payload`, `_write_label_to_s3`, and both calls inside `retrain_isolation_forest_quarterly`) pass `SSEKMSKeyId` with documented customer-managed key constants (e.g., `SIGNALS_CMK_ARN`, `LABELS_CMK_ARN`, `MODEL_ARTIFACTS_CMK_ARN`), or the comments next to each call are strengthened to explicitly require CMK enforcement via bucket policy with a named bucket-policy example.
3. The Athena polling loop in `_pull_evidence_claims` adds `time.sleep()` between polls and a deadline or max-iteration guard so the loop cannot spin indefinitely or burn API throttle budget.
4. (Optional) `logging.basicConfig(...)` is added so `logger.info` / `logger.warning` output is visible in direct runs.
5. (Optional) `EM_CODES` drops 99201 (deleted from CPT effective 2021-01-01) or adds a comment naming the omission as intentional.
6. (Optional) `_query_prior_cases` uses `Attr("period_start")` rather than `Key("period_start")` in the FilterExpression, and either paginates with `LastEvaluatedKey` or the inline comment names the truncation risk explicitly.
7. (Optional) A `_validate_outcome_event` helper is added and called at the top of `on_investigation_outcome` so a malformed EventBridge payload raises a named `ValueError` before any DynamoDB side-effect.
8. (Optional) `_to_decimal` either raises on non-finite float input or the comment explicitly names the zero-masking behavior and routes callers toward an explicit guard.
9. (Optional) `_emit_metric`'s signature accepts float, and the `int()` cast on `dollars_recovered` at the call site is dropped so cents are not silently lost.
