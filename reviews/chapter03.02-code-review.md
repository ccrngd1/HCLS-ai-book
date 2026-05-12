# Code Review: Recipe 3.2 Patient No-Show Pattern Detection (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-12
**Files reviewed:**
- `chapter03.02-patient-no-show-pattern-detection.md` (main recipe, pseudocode walkthrough)
- `chapter03.02-python-example.md` (Python companion)

**Validation performed:**
- Pseudocode's five steps walked against Python functions, one-to-one
- boto3 DynamoDB resource-API calls (`Table.get_item`, `Table.put_item`, `Table.query`, `batch_get_item`) verified for parameter names, `Key` condition shape, `IndexName` usage, and Decimal discipline
- boto3 S3 `put_object`, `get_object`, `copy_object` calls checked for leading slashes, SSE parameters, encoding, and `ServerSideEncryption` / `SSEKMSKeyId` pairing
- boto3 Pinpoint `send_messages` call shape verified against the current `MessageRequest` schema (Addresses, MessageConfiguration, Context)
- boto3 SageMaker Feature Store runtime `get_record` call verified
- boto3 CloudWatch `put_metric_data` call shape verified
- Every numeric value flowing into DynamoDB traced for Python-float writes (`risk_score`, `baseline_rate`, `deviation`, `rolling_no_show_rate`, `observation_count`, `features_snapshot`, `review_duration_sec`)
- S3 keys inspected for leading slashes (none present)
- Module-load evaluated: `assert` statement, boto3 client instantiation, global model cache
- `datetime.fromisoformat` call sites inspected for `Z`-suffix and naive/aware mixing
- Healthcare concerns reviewed: PHI logging, BAA eligibility of services, synthetic data labeling, SMS/voice minimum-PHI bodies, encryption for labels and model artifacts, retention context

---

## Verdict: PASS (with reservations)

Three WARNING findings and eight NOTEs. Per persona policy the threshold is "more than 3 WARNINGs means FAIL," so this lands at PASS, but it is close. The three WARNINGs are:

1. The module-load `assert` on `PINPOINT_APPLICATION_ID` uses a broken guard clause (`__name__ != "__production__"`) that never fires, so the "deploy-time guardrail" teaches a pattern that does not actually guard anything.
2. Both S3 `put_object` calls (label archive in `_write_label_to_s3`, model artifact in `_publish_model`, plus the `copy_object` in `_publish_model`) set `ServerSideEncryption="aws:kms"` without passing `SSEKMSKeyId`, silently falling back to the AWS-managed `aws/s3` key for PHI-carrying label writes and for model artifacts. Same pattern flagged in Chapter 3.1's review.
3. `execute_outreach`'s channel loop appends a `"sent"` status entry even when the channel value is not one of `sms` / `voice` / `email`, then breaks. An unrecognized channel preference silently "succeeds" without any message being sent.

None of these prevents the teaching flow. Decimal discipline is consistent across every code path that touches DynamoDB (`_to_decimal` routes through `Decimal(str(value))`; thresholds, alpha, baseline math, and risk-score comparisons all stay in `Decimal`). The five pseudocode steps map cleanly to five Python functions plus a `run_nightly_scoring` orchestrator. S3 keys are correctly formatted (`labels/year=.../month=.../day=.../{uuid}.json`, `versions/{SCORER_VERSION}/model.joblib`, `current/model.joblib`), no leading slashes. Comments consistently explain the *why* (point-in-time-correctness, the Decimal gotcha, minimum-PHI message bodies, intervention exclusion from training, patient-stratified split to prevent leakage, subgroup-regression promotion gate). The Gap to Production section enumerates every real-world gap honestly.

Fix the three WARNINGs and this is a clean pass. NOTEs are editorial and primarily mirror items already acknowledged in the code or the recipe.

---

## Findings

### Finding 1: Module-load `assert` uses a guard clause that never fires; "deploy-time guardrail" is dead code

- **Severity:** WARNING
- **Location:** `chapter03.02-python-example.md`, Configuration block, lines ~98-99
- **Description:** The Configuration block defines a placeholder Pinpoint application ID and immediately asserts a compound expression:

  ```python
  PINPOINT_APPLICATION_ID = "0123456789abcdef0123456789abcdef"
  ...
  # Deploy-time guardrail: catch unreplaced example values.
  assert PINPOINT_APPLICATION_ID != "0123456789abcdef0123456789abcdef" or __name__ != "__production__", \
      "PINPOINT_APPLICATION_ID still uses the example placeholder. Replace before deploying."
  ```

  The assertion is structured as `(value_has_been_replaced) OR (we_are_not_in_production)`. The first clause is `False` (the value has not been replaced). The second clause is `True` for a reason the author probably did not intend: Python's `__name__` is either `"__main__"` (when the file is executed as a script) or the module name (when imported). It is never `"__production__"`. There is no Python convention that sets `__name__` to `"__production__"`, and nothing in the file sets it that way. So the second clause is always `True`, `False or True` is `True`, and the assert never fires. The "deploy-time guardrail" guards nothing.

  This is different from Chapter 3.1's Finding 1 (where a similar assert fires at import because the substring check actually matches). Here the assert is silently dead. A reader who adopts this pattern for their own config guards (`assert X != placeholder or __name__ != "__production__"`) will think they are protected against unreplaced values and will not be. That is the teaching harm: the pattern looks like a reasonable idiom and it is broken.

  A secondary issue: even if the guard were wired correctly, `assert` statements are removed when Python runs with `-O` (optimized mode). Production deployments that run with `python -O` silently lose every assertion-based guard. This is a general "don't use asserts for runtime validation" rule that also applies here.

- **How to fix:** Three options, in order of pedagogical friendliness:

  1. Remove the assert entirely. The prose already tells the reader to replace the resource names.
  2. Replace with a function invoked by callers before deploying:
     ```python
     def check_config_replaced() -> None:
         if PINPOINT_APPLICATION_ID == "0123456789abcdef0123456789abcdef":
             raise RuntimeError(
                 "PINPOINT_APPLICATION_ID still uses the example placeholder. "
                 "Replace before deploying."
             )
     ```
     Invoked from a deploy script or from an environment-gated hook, not at module import.
  3. Replace with a runtime warning emitted when a function actually tries to call Pinpoint, similar to the pattern suggested for Chapter 3.1:
     ```python
     if PINPOINT_APPLICATION_ID == "0123456789abcdef0123456789abcdef":
         logger.warning(
             "PINPOINT_APPLICATION_ID is still the example placeholder; "
             "execute_outreach will fail when it reaches Pinpoint."
         )
     ```

  Option 1 is the smallest edit. Option 2 is the most defensible posture if the intent is "refuse to run in production with a placeholder value"; wire it to an explicit environment signal (`os.environ.get("DEPLOYMENT_STAGE") == "prod"`) rather than a nonexistent `__name__` value.

---

### Finding 2: S3 `put_object` and `copy_object` calls set SSE-KMS without specifying a customer-managed KMS key

- **Severity:** WARNING
- **Location:** `chapter03.02-python-example.md`, `_write_label_to_s3` (Step 5) and `_publish_model` (retrain sketch); three call sites total
- **Description:** All three S3 write paths set server-side encryption but omit the key ARN:

  ```python
  # _write_label_to_s3:
  s3_client.put_object(
      Bucket=LABELS_BUCKET,
      Key=key,
      Body=json.dumps(training_row, default=str).encode("utf-8"),
      ContentType="application/json",
      ServerSideEncryption="aws:kms",
  )

  # _publish_model (versioned artifact):
  s3_client.put_object(
      Bucket=MODEL_ARTIFACTS_BUCKET,
      Key=version_key,
      Body=buf.read(),
      ServerSideEncryption="aws:kms",
  )

  # _publish_model (current-pointer copy):
  s3_client.copy_object(
      Bucket=MODEL_ARTIFACTS_BUCKET,
      Key="current/model.joblib",
      CopySource={"Bucket": MODEL_ARTIFACTS_BUCKET, "Key": version_key},
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias), not a customer-managed key. For PHI workloads the difference is real: customer-managed keys let you rotate on your schedule, apply key-specific grants, audit `kms:Decrypt` per principal via CloudTrail, and revoke access by disabling the key. The AWS-managed key can be neither disabled nor scoped with custom policies.

  The label archive carries PHI (patient IDs, scheduled times, features, outcome labels) and is explicitly called out in the main recipe's Gap to Production section: "All data at rest (DynamoDB tables, S3 buckets, Feature Store offline/online, CloudWatch Logs) is encrypted with customer-managed KMS keys." The Chapter 3.1 companion had the same gap and this review flagged it; this file repeats the pattern.

  The model artifact bucket is less obviously PHI-bearing on its own, but a leaked model can be inverted to approximate training data characteristics, and the policy posture for PHI-adjacent model artifacts should match the policy for training data. Customer-managed keys for both.

- **How to fix:** Add key constants near the top of the Configuration block and pass them on all three calls:

  ```python
  LABELS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."
  MODEL_ARTIFACTS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."

  # _write_label_to_s3:
  s3_client.put_object(
      Bucket=LABELS_BUCKET,
      Key=key,
      Body=json.dumps(training_row, default=str).encode("utf-8"),
      ContentType="application/json",
      ServerSideEncryption="aws:kms",
      SSEKMSKeyId=LABELS_CMK_ARN,
  )
  ```

  Same change for the two `_publish_model` calls with `SSEKMSKeyId=MODEL_ARTIFACTS_CMK_ARN`. Document the constants with a one-line comment: "Customer-managed KMS key ARN. Separate keys per bucket so rotation and access grants can be scoped independently."

---

### Finding 3: `execute_outreach` silently marks unrecognized channels as "sent"

- **Severity:** WARNING
- **Location:** `chapter03.02-python-example.md`, Step 4 `execute_outreach`
- **Description:** The channel dispatch loop handles three known channels, then unconditionally records success and breaks:

  ```python
  for channel in channels:
      try:
          if channel == "sms":
              _send_sms_reminder(queue_item, patient_preferences, intervention_id)
          elif channel == "voice":
              _send_voice_reminder(queue_item, patient_preferences, intervention_id)
          elif channel == "email":
              _send_email_reminder(queue_item, patient_preferences, intervention_id)
          attempts.append({"channel": channel, "status": "sent"})
          # Break on first successful send. A real policy may continue
          # through all preferred channels; keep it simple for the example.
          break
      except pinpoint.exceptions.BadRequestException as ex:
          ...
  ```

  If `channel` is anything other than `"sms"`, `"voice"`, or `"email"` (for example, `"push"`, `"portal"`, or a typo in the patient-preferences store), all three `elif` branches fall through, no message is sent, but the code still executes `attempts.append({"channel": channel, "status": "sent"})` and then `break`. The downstream intervention record claims a reminder was sent when nothing happened. The CloudWatch `intervention_executed` metric gets emitted with `status: "sent"`. The outcome joiner later attributes any show/no-show to a nonexistent intervention.

  This is a teaching hazard. A reader reading the outer control-flow (`try` → dispatch → `append("sent")` → `break`) sees what looks like a clean first-success-wins pattern and does not notice that the dispatch step has no else-branch. If they extend the list (add `"push"`, add `"portal"`) without also extending the dispatch, they inherit the bug. Misleading the operations team about which outreach actually went out is exactly the kind of failure that is hard to detect (the message never arrived; the log says it did) and produces garbage training data (intervention effect measurements become noise).

  Related minor issue in the same loop: `_send_*_reminder` functions raise `KeyError` if the required preference key is missing (`prefs["phone_number"]` in `_send_sms_reminder`, `prefs["email"]` in `_send_email_reminder`). A `KeyError` is not caught by the `except pinpoint.exceptions.BadRequestException` clause, so a patient with SMS in their preferences but no phone number in the record takes the whole outreach down with an uncaught exception.

- **How to fix:** Add an explicit unknown-channel branch that logs and skips (does not claim success), and broaden the exception handling to at least capture the common data-shape failures:

  ```python
  KNOWN_CHANNELS = {"sms", "voice", "email"}

  for channel in channels:
      if channel not in KNOWN_CHANNELS:
          attempts.append({"channel": channel, "status": "skipped_unknown"})
          logger.warning("outreach_unknown_channel", extra={
              "intervention_id": intervention_id,
              "channel":         channel,
          })
          continue
      try:
          if channel == "sms":
              _send_sms_reminder(queue_item, patient_preferences, intervention_id)
          elif channel == "voice":
              _send_voice_reminder(queue_item, patient_preferences, intervention_id)
          elif channel == "email":
              _send_email_reminder(queue_item, patient_preferences, intervention_id)
          attempts.append({"channel": channel, "status": "sent"})
          break
      except KeyError as ex:
          attempts.append({"channel": channel, "status": "failed", "error": f"missing_pref:{ex}"})
          logger.warning("outreach_missing_preference", extra={
              "intervention_id": intervention_id,
              "channel":         channel,
          })
          continue
      except pinpoint.exceptions.BadRequestException as ex:
          attempts.append({"channel": channel, "status": "failed", "error": str(ex)})
          logger.warning("outreach_channel_failed", extra={
              "intervention_id": intervention_id,
              "channel":         channel,
          })
          continue
  ```

  The minimal fix is just the unknown-channel guard. The `KeyError` handling is a quality-of-life add that stops one malformed preference record from taking down an entire nightly outreach batch.

---

### Finding 4: Module logger has no handler configured; `logger.info` / `logger.warning` calls drop silently in the `__main__` run

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, Configuration block (`logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)`)
- **Description:** Same pattern flagged in Chapter 3.1 Finding 4 and earlier reviews. Without `logging.basicConfig(...)` or an explicit handler, calls like `logger.info("model_loaded", extra={...})`, `logger.warning("unprocessed_keys_on_batch_get", ...)`, and `logger.warning("metric_emit_failed", ...)` do not reach the console when the file runs as `__main__`. The orchestrator's `print("[1/4] Assembling features...")` statements keep the step narration visible, but the structured logs (which are the more useful artifacts for a learner tracing a run) disappear. In Lambda this is not an issue (Lambda configures a root handler), but the `if __name__ == "__main__":` block is the first way most readers exercise the code.
- **How to fix:** Add one line near the top of the Configuration block:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document as "visible when running this file directly; Lambda configures its own handler and this becomes a no-op there."

---

### Finding 5: `_put_queue_item` stores `Decimal("-1")` as a None-sentinel for `baseline_rate`

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, Step 3 `_put_queue_item`
- **Description:** When a patient has no baseline yet (cold-start), the router sets `baseline_rate = None` in the decision dict. The queue writer encodes None as `Decimal("-1")`:

  ```python
  "baseline_rate":  decision["baseline_rate"] if decision["baseline_rate"] is not None else Decimal("-1"),
  ```

  A downstream reader of the queue (care-coordinator UI, investigation workflow, analytics job) has to know that `-1` means "no baseline" and cannot be interpreted as a rate. A no-show rate is a probability in `[0, 1]`; `-1` is out-of-range in a way that signals "sentinel" to a careful reader but is easy to miss in a chart, a dashboard filter, or a join where the sentinel leaks into aggregates as a legitimate-looking value. DynamoDB supports absence-of-attribute perfectly well; the cleaner encoding is to omit `baseline_rate` from the Item when None, and let consumers check for its absence with `.get("baseline_rate")`.

  Functionally it works. The `INTERVENTION_CAPACITY_PER_DAY` sort uses `risk_score`, not `baseline_rate`, so the sentinel does not corrupt the sort. But a reader copying this pattern into their own queue tables inherits the sentinel convention, and the first time an analyst writes `AVG(baseline_rate)` over the investigation queue, the answer is wrong.
- **How to fix:** Either (a) omit the attribute when None:

  ```python
  item = {
      "appointment_id": decision["appointment_id"],
      ...
      "deviation":      decision["deviation"],
      "action":         decision["action"],
      "reason":         decision["reason"],
      "scorer_version": decision["scorer_version"],
      "scored_at":      decision["scored_at"],
      "enqueued_at":    datetime.now(timezone.utc).isoformat(),
  }
  if decision["baseline_rate"] is not None:
      item["baseline_rate"] = decision["baseline_rate"]
  table.put_item(Item=item)
  ```

  or (b) add a companion boolean attribute so the semantics are explicit:

  ```python
  "baseline_rate":      decision["baseline_rate"] if decision["baseline_rate"] is not None else Decimal("0"),
  "baseline_available": decision["baseline_rate"] is not None,
  ```

  Option (a) is idiomatic DynamoDB; option (b) makes the schema explicit for consumers that cannot cleanly branch on attribute presence. Either is better than the `-1` sentinel.

---

### Finding 6: `_query_interventions_for_appointment` is unpaginated; edge cases silently truncate

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, Step 5 `_query_interventions_for_appointment`
- **Description:** The GSI query is a single call:

  ```python
  response = table.query(
      IndexName="appointment_id_index",
      KeyConditionExpression=Key("appointment_id").eq(appointment_id),
  )
  return response.get("Items", [])
  ```

  DynamoDB's `Query` returns at most 1 MB of items per response. A single appointment rarely generates enough intervention records to exceed 1 MB, but two edge cases do: (1) the same high-risk appointment is re-reviewed weekly across a long lead time, producing ten or more intervention records each with a nontrivial `channels_attempted` payload; (2) a retry storm in the outreach Lambda writes duplicate intervention records for the same appointment. In either case the count that feeds the training row (`"intervention_count": len(interventions)`) is silently wrong, and the outcome-joiner produces a label that looks intervened when the full count would show twice as many.

  Same class of issue as Chapter 3.1 Finding 7. The fix pattern is identical.

- **How to fix:** Either add a pagination loop:

  ```python
  items = []
  params = {
      "IndexName": "appointment_id_index",
      "KeyConditionExpression": Key("appointment_id").eq(appointment_id),
  }
  while True:
      response = table.query(**params)
      items.extend(response.get("Items", []))
      if "LastEvaluatedKey" not in response:
          break
      params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
  return items
  ```

  or strengthen the existing inline comment to name the specific failure mode:

  ```python
  # In production, paginate with LastEvaluatedKey; a single query caps at
  # 1 MB per response and silently truncates the intervention list. The
  # resulting intervention_count in the training row is wrong, not raised.
  ```

---

### Finding 7: `_evaluate_subgroups` has two bugs that will only surface when `retrain_monthly` is wired up

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, `_evaluate_subgroups` (retrain sketch)
- **Description:** The subgroup-evaluation helper has two issues that do not manifest today (because `_load_labels` returns an empty DataFrame) but will break the first time someone points it at a real labels archive:

  ```python
  for column in ["insurance_type", "age_band"]:
      if column not in val_meta.columns:
          continue
      for value, mask in val_meta.groupby(column).groups.items():
          group_idx = [i for i in range(len(val_meta)) if val_meta.iloc[i].name in mask]
          if len(group_idx) < 30:
              continue
          preds = pipeline.predict_proba(X_val.iloc[group_idx])[:, 1]
          results[f"{column}={value}"] = roc_auc_score(y_val[group_idx], preds)
  ```

  First, `age_band` is never populated anywhere in the pipeline. `FEATURE_COLUMNS` has `age` (a numeric); `CATEGORICAL_COLUMNS` has `insurance_type` but no `age_band`. The label-writing path (`on_appointment_outcome`) writes `features_snapshot` from the prediction archive, which contains `age` as an int, never `age_band`. So the subgroup loop skips `age_band` silently every time, and the fairness dashboard the recipe promises ("Subgroup AUC spread") only covers `insurance_type`. Either drop `age_band` from the list, or derive `age_band` from `age` at label-write time (e.g., 0-17, 18-40, 41-65, 65+) so the subgroup loop can evaluate it.

  Second, the `group_idx` construction is O(n*m) and semantically fragile:

  ```python
  group_idx = [i for i in range(len(val_meta)) if val_meta.iloc[i].name in mask]
  ```

  `val_meta.iloc[i].name` is the DataFrame's index label at positional offset `i`. `mask` is the set of index labels groupby returned for this value. The test `... .name in mask` works only if `val_meta` has unique, hashable index labels. If `val_meta` was produced by `.iloc[val_idx]` earlier in the function (which it was), the index labels are the original row positions from the pre-split DataFrame, which works. But a reader extending the pipeline (adding a `.reset_index()` for any reason, or using a different split strategy) breaks this in non-obvious ways.

  The idiomatic pandas version is straightforward:

  ```python
  for value, group_df in val_meta.groupby(column):
      if len(group_df) < 30:
          continue
      # Use group_df's positional indexer against X_val / y_val.
      positional = val_meta.index.get_indexer(group_df.index)
      preds = pipeline.predict_proba(X_val.iloc[positional])[:, 1]
      results[f"{column}={value}"] = roc_auc_score(y_val[positional], preds)
  ```

  The recipe frames the retrain function as a sketch ("In production, the same logic runs as a SageMaker Training Job..."), so a reader is expected to do more work here. But the two issues above are not production gaps; they are correctness bugs that will produce silent wrong answers (no `age_band` subgroup coverage; fragile index-label arithmetic) the first time the sketch is exercised. Worth naming inline.
- **How to fix:** Either derive `age_band` at label-write time and fix the indexing:

  ```python
  # In on_appointment_outcome, add to training_row:
  age = prediction["features_snapshot"].get("age", 45)
  training_row["age_band"] = _age_band(age)  # helper returning "0-17" / "18-40" / ...
  ```

  and use the idiomatic pandas groupby pattern shown above. Or, since this is a sketch, add a one-line comment naming both gaps: "Note: age_band must be written into the label row (on_appointment_outcome does not do this today; add _age_band() there), and `group_idx` construction assumes the post-split DataFrame has unique, hashable index labels."

---

### Finding 8: `_patient_stratified_split` uses `np.random.shuffle` without seeding; retrains are non-reproducible

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, `_patient_stratified_split` (retrain sketch)
- **Description:** The split relies on the global numpy RNG:

  ```python
  def _patient_stratified_split(patient_ids, test_size=0.2):
      unique = np.array(sorted(set(patient_ids)))
      np.random.shuffle(unique)
      ...
  ```

  Two runs of the retrain produce two different train/val splits, which means two different AUCs, which means the promotion gate (`val_metrics.auc > incumbent_metrics.auc + 0.005`) is measuring noise on top of signal. For a teaching example this is fine; for the retrain gate's production framing it is a source of flaky decisions. The small fix is a dedicated RNG with an explicit seed:

  ```python
  def _patient_stratified_split(patient_ids, test_size=0.2, seed=42):
      rng = np.random.default_rng(seed)
      unique = np.array(sorted(set(patient_ids)))
      rng.shuffle(unique)
      ...
  ```

  Related: the promotion-gate logic uses `training_df.iloc[val_idx]` to index metadata, but `val_idx` is a list of integer positions returned by `_patient_stratified_split`. That works for positional indexing on a default-indexed DataFrame and breaks if the DataFrame has been re-indexed for any reason. Same class of fragility as Finding 7.
- **How to fix:** Seed an explicit RNG at function scope (never `np.random` globally) and make the seed either a parameter or a module-level constant. Optional but worth noting: use `sklearn.model_selection.GroupShuffleSplit` instead, which is a standard, tested implementation of patient-stratified splits and avoids both the seeding issue and the index-label fragility.

---

### Finding 9: `_load_model` and `score_appointment` cache the model globally; no thread-safety note

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, Step 2 `_load_model` / `score_appointment`
- **Description:** The module caches the fitted sklearn Pipeline in `_MODEL` / `_MODEL_META` and lazy-loads on first call:

  ```python
  _MODEL = None
  _MODEL_META = None

  def _load_model(model_key: str = "current/model.joblib") -> None:
      global _MODEL, _MODEL_META
      response = s3_client.get_object(...)
      ...

  def score_appointment(features: dict) -> dict:
      if _MODEL is None:
          _load_model()
      ...
  ```

  This is the standard "load once, reuse warm container" pattern for Lambda and is documented in the comment above. Two small teaching notes that are worth adding alongside:

  1. The `_MODEL is None` check is not thread-safe. In a Lambda this is fine (single-threaded handler). In a containerized service with multiple request threads, two requests can race on the first call and both call `_load_model()`. The fix is a `threading.Lock` or a module-level `_load_model()` call at import (eager load). Not required for the teaching example; worth a sentence.
  2. `_load_model` does not validate that the joblib payload contains the expected keys (`"pipeline"`, `"meta"`). A malformed or wrong-version artifact raises `KeyError` on the dict access rather than a clear "unexpected artifact format" error. One-line check and raise is enough.
- **How to fix:** Add a one-line comment in `score_appointment`:

  ```python
  # The _MODEL is None check is single-threaded-safe (Lambda invokes
  # one request per container at a time). In a multi-threaded service,
  # guard with a lock or eager-load at import.
  ```

  Optional belt-and-suspenders in `_load_model`:

  ```python
  if "pipeline" not in payload or "meta" not in payload:
      raise RuntimeError(f"Model artifact at {model_key} missing required keys")
  ```

---

### Finding 10: `datetime.fromisoformat` is used on external payloads without `Z`-suffix handling

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, `assemble_features` (`appointment["scheduled_time"]`, `appointment["scheduled_at"]`), `on_appointment_outcome` (`event["actual_arrival_time"]`, `prediction["scheduled_time"]`), and `_write_label_to_s3` (`outcome_recorded_at`)
- **Description:** Same issue flagged in Chapter 3.1 Finding 8. `datetime.fromisoformat` in Python 3.7 through 3.10 does not accept a trailing `Z` (UTC shorthand). Python 3.11+ relaxed this. The code's own timestamp writers emit `+00:00` (via `datetime.now(timezone.utc).isoformat()`), so the round-trip through this file works on all supported Pythons. But incoming data from the EHR integration, from non-Python workstations, or from EventBridge payloads produced by JavaScript services typically uses `Z` by default and fails to parse on older Python runtimes with `ValueError: Invalid isoformat string`.

  Inside `assemble_features` the appointment payload comes from the nightly scheduling export; inside `on_appointment_outcome` the event comes from the EHR's outcome publisher. Both are external surfaces. A single malformed or `Z`-suffixed timestamp propagates a `ValueError` out of the Lambda, which EventBridge retries. The retry storm can saturate the DLQ in the window before anyone notices.

- **How to fix:** Add a small helper and use it everywhere external timestamps are parsed:

  ```python
  def _parse_iso(value: str) -> datetime:
      """Parse ISO-8601 allowing the Z shorthand used by non-Python producers."""
      return datetime.fromisoformat(value.replace("Z", "+00:00"))
  ```

  Or, one-line note in the comment above the `datetime.fromisoformat` calls: "In production, accept the `Z` suffix and other ISO-8601 variants via `dateutil.parser.isoparse` or an equivalent helper."

---

### Finding 11: `_write_label_to_s3` uses `json.dumps(..., default=str)`, which silently mishandles any remaining Decimals

- **Severity:** NOTE
- **Location:** `chapter03.02-python-example.md`, `_write_label_to_s3` (Step 5)
- **Description:** The label writer uses `default=str` as the JSON fallback:

  ```python
  Body=json.dumps(training_row, default=str).encode("utf-8"),
  ```

  `training_row` has already been sanitized via `_decimal_to_jsonable` for `features_snapshot` and `float()` for `risk_score_at_scoring`. But `default=str` is a catch-all that will stringify anything else the serializer does not recognize, including `Decimal`, `datetime`, and `UUID`. That means any Decimal that slips past the sanitization (say, if someone adds a new field to `training_row` from `prediction` without thinking about it) gets emitted as a JSON string like `"0.35"` rather than a number. The training pipeline that reads these labels back (Athena, pandas) will read `risk_score` as a string in one row and a number in another, depending on which code path produced the row.

  Same class of bug Chapter 2.10 Finding 10 flagged: mixing `default=str` fallback with an explicit `_decimal_to_jsonable` pre-pass is a subtle inconsistency that shows up as rounding drift months later. The main recipe's Gap to Production note ("In production, use a single consistent custom JSON encoder across the entire codebase...") acknowledges this, but the example code demonstrates the mixed pattern the prose warns against.
- **How to fix:** Either drop `default=str` and rely on `_decimal_to_jsonable` to produce a fully JSON-ready structure (and let the serializer raise on any unrecognized type, which is the desired fail-fast behavior), or replace with a single custom encoder class used everywhere:

  ```python
  class _TrainingRowEncoder(json.JSONEncoder):
      def default(self, o):
          if isinstance(o, Decimal):
              return float(o)
          if isinstance(o, datetime):
              return o.isoformat()
          return super().default(o)

  Body=json.dumps(training_row, cls=_TrainingRowEncoder).encode("utf-8"),
  ```

  Consistent across callers.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function(s) | Consistent? |
|-----------------|---------------------|---------------------|-------------|
| Step 1 | `assemble_features(appointment)` | `assemble_features` + helpers `_get_patient_features`, `_cold_start_patient_features`, `_patient_provider_no_show_rate` | Yes. Feature-store read with cold-start fallback, appointment-level derivations, merge-and-stamp flow matches pseudocode exactly |
| Step 2 | Batch Transform over feature batch | `score_appointment` + `archive_prediction` (+ `_load_model`) | Yes. The in-process scikit-learn scoring is a pedagogical simplification of Batch Transform, which the prose explicitly calls out. `archive_prediction` is an added function that fills the gap between pseudocode Step 2 (writes predictions) and Step 5 (reads `predictions-archive`); sensible addition |
| Step 3 | `route_scored_appointments(predictions_uri)` | `route_predictions(predictions)` + helpers `_batch_get_baselines`, `_put_queue_item`, `_emit_metric` | Yes. Deviation computation, threshold routing, capacity-cap-with-bump, and queue writes all match pseudocode. Minor naming drift: pseudocode uses `bumped_reason`, Python overwrites `reason` with `"capacity_bump"` (not a bug, just a divergence) |
| Step 4 | `execute_outreach(intervention)` | `execute_outreach(queue_item, patient_preferences)` + helpers `_pick_channels`, `_send_sms_reminder`, `_send_voice_reminder`, `_send_email_reminder`, `_build_*` | Mostly. Python adds the second argument (patient_preferences); pseudocode passes only the intervention record. Either the pseudocode implicitly assumes the intervention record carries preferences or the Python version factors out preferences for clarity. Tolerable divergence. See Finding 3 for the dispatch-loop bug |
| Step 5 | `on_appointment_outcome(event)` | `on_appointment_outcome` + helpers `_derive_label`, `_update_patient_baseline`, `_query_interventions_for_appointment`, `_write_label_to_s3`, `_decimal_to_jsonable` | Yes. Five-phase pattern (pull prediction → find interventions → derive label → write training row → update baseline) matches pseudocode one-to-one |
| Retrain | `retrain_monthly()` | `retrain_monthly` + helpers `_patient_stratified_split`, `_evaluate_subgroups`, `_no_subgroup_regression`, `_publish_model`, `_load_labels`, `_fetch_incumbent_metrics` | Structurally yes. The function is explicitly a sketch; `_load_labels` returns an empty DataFrame by design (TODO noted). See Findings 7 and 8 for correctness bugs that activate when the sketch is exercised |

The `run_nightly_scoring` orchestrator chains Steps 1 through 3 (assemble → score → archive → route). Steps 4 and 5 run separately (outreach Lambda on the intervention queue, outcome-joiner Lambda on EventBridge), which matches the pseudocode framing.

---

## AWS SDK Accuracy

### DynamoDB
- `dynamodb.resource("dynamodb", ...)` and `table.put_item / get_item / query / batch_get_item`: current API shapes
- `table.query(IndexName="appointment_id_index", KeyConditionExpression=Key("appointment_id").eq(...))`: correct GSI usage
- `dynamodb.batch_get_item(RequestItems={...})` with 100-key chunking: correct; `UnprocessedKeys` handled with a warning log (see Finding 6 for a related unpaginated query)
- Every numeric value in every `Item` is `Decimal`, string, or int. No Python float reaches DynamoDB (see Decimal section below)

### S3
- `s3_client.put_object`, `get_object`, `copy_object`: parameter names correct
- Keys use Hive-style partitioning (`labels/year=YYYY/month=MM/day=DD/{uuid}.json`), no leading slashes, no `s3://` scheme leakage
- `SSEKMSKeyId` is missing on all three write/copy calls (Finding 2)

### SageMaker Feature Store Runtime
- `featurestore_runtime.get_record(FeatureGroupName=..., RecordIdentifierValueAsString=...)`: parameter names match the current API
- `ResourceNotFound` exception handling via `featurestore_runtime.exceptions.ResourceNotFound`: correct boto3 pattern
- Record parsing (`response.get("Record", [])`, iterating `FeatureName`/`ValueAsString` pairs): matches the actual response shape

### Pinpoint
- `pinpoint.send_messages(ApplicationId=..., MessageRequest={Addresses, MessageConfiguration, Context})`: current API shape
- `Context` is a valid top-level `MessageRequest` attribute (map of string to string), used correctly to carry `intervention_id`
- SMS `MessageConfiguration` with `SMSMessage.Body` and `MessageType="TRANSACTIONAL"`: correct
- Voice `MessageConfiguration` with `VoiceMessage.OriginationNumber`, `LanguageCode`, `VoiceId`: correct; `VoiceId="Joanna"` is a valid Polly voice
- Email `MessageConfiguration` with `EmailMessage.SimpleEmail` (Subject, HtmlPart, TextPart) and `FromAddress`: correct
- `BadRequestException` via `pinpoint.exceptions.BadRequestException`: correct exception namespace
- Note: the boto3 client name `pinpoint` and IAM service prefix `mobiletargeting` are both documented in the comment above the client instantiation; correct

### CloudWatch
- `cloudwatch.put_metric_data(Namespace="NoShowScorer", MetricData=[{MetricName, Value, Unit, Dimensions}])`: current shape
- `ScorerVersion` dimension on every metric: right pattern for attributing metric shifts
- Try/except around `put_metric_data` with a warning log: appropriate; metric-emission failures do not block scoring

### EventBridge
- `eventbridge = boto3.client("events", ...)` is instantiated but the code never calls `eventbridge.put_events` or any other method. The file consumes EventBridge events (receiving), it does not produce them. Unlike Chapter 3.1 (where the same dangling client was a WARNING), this file's Setup section acknowledges the consumption-only role ("for publishing outcome events from the EHR integration side"), so the client is forward-looking rather than dead. Marginal — could arguably be removed for the same reason as Chapter 3.1 Finding 3, but the rationale is weaker here because the EventBridge consumer pattern is the whole Step 5 flow. Leaving unflagged.

### Boto3 Config
- `Config(retries={"max_attempts": 5, "mode": "adaptive"})`: current parameter names, appropriate for bursty nightly scoring. Rationale explained in the comment above the config block

---

## DynamoDB Decimal Check

- `_to_decimal` helper routes through `Decimal(str(value))`, avoiding binary-precision drift. Used on `risk_score` in `score_appointment`, on `baseline_rate` and `deviation` in `route_predictions`, on the full `features_snapshot` in `archive_prediction`, on every value written to `intervention-queue` / `investigation-queue` / `intervention-log` / `patient-baselines`
- `HIGH_RISK_THRESHOLD`, `DEVIATION_FLAG_THRESHOLD`, `BASELINE_ALPHA`, `POPULATION_PRIOR_NO_SHOW_RATE`: all `Decimal` constants, so threshold comparisons (`pred["risk_score"] >= HIGH_RISK_THRESHOLD`, `deviation >= DEVIATION_FLAG_THRESHOLD`) stay in `Decimal`
- `_update_patient_baseline` math stays in `Decimal`: `(Decimal("1.0") - BASELINE_ALPHA) * prior_rate + BASELINE_ALPHA * (Decimal("1.0") if is_positive else Decimal("0.0"))`. No Python float creeps in
- `score_appointment` converts `float(probabilities[0, 1])` (a numpy float) through `_to_decimal` on its way into the prediction dict, so the `risk_score` in DynamoDB is `Decimal`
- `archive_prediction`'s `feature_snapshot` dict comprehension converts all `int`/`float` values to `Decimal`: `k: _to_decimal(v) if isinstance(v, (int, float)) else v for k, v in features.items()`

Result: no Python float reaches DynamoDB in any code path. Pass.

---

## S3 Key Check

Keys inspected:

- `labels/year={recorded_dt.year:04d}/month={recorded_dt.month:02d}/day={recorded_dt.day:02d}/{uuid.uuid4()}.json`
- `versions/{SCORER_VERSION}/model.joblib`
- `current/model.joblib`
- Default model load key: `current/model.joblib`

All keys use forward-slash partitioning, no leading slashes, no reserved characters, UUID / version-string leaf names avoid collisions.

Pass.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Comment at the logger setup: "Appointment records are PHI (a patient ID plus a provider plus a date is re-identifying), so we log structural metadata only. Never log the full appointment body, the full feature vector, or any patient demographic fields in regular application logs." Inline calls respect this: `logger.info("model_loaded", extra={"version": ...})`, `logger.warning("outreach_channel_failed", extra={"intervention_id": ..., "channel": ...})`. No full feature vectors or patient payloads in logs. Pass.
- **Minimum-PHI message bodies.** `_build_sms_body`, `_build_voice_ssml`, `_build_email_html`, `_build_email_text` all produce generic "you have an appointment tomorrow" text with no visit type, no provider name, no clinic identifier, no diagnosis. Comment explicitly names the rule: "Your appointment tomorrow at 9 AM" is acceptable; "Your oncology follow-up tomorrow" is not. Pass.
- **Encryption at rest.** S3 writes set `ServerSideEncryption="aws:kms"`; the key is the AWS-managed default rather than a customer-managed key (Finding 2). DynamoDB encryption configuration is out of the Python code's scope (table-creation-time) and the main recipe's Prerequisites table covers it. Pass, modulo Finding 2.
- **Synthetic data labeling.** The heads-up block and the `__main__` sample both label the data as synthetic: "All example patient data is synthetic. Patient IDs, provider IDs, clinic IDs, and appointment IDs in the sample output are illustrative and do not refer to any real patients, providers, or services. Use Synthea in a development environment and never use real PHI in a teaching example." Pass.
- **BAA / HIPAA context.** All services (DynamoDB, S3, SageMaker Feature Store Runtime, CloudWatch, EventBridge, Pinpoint) are HIPAA-eligible. Pinpoint specifically requires configuration to remain compliant (SMS carrier routing, voice origination, TCPA opt-outs); the Gap to Production section names this explicitly. Pass.
- **Subgroup fairness.** `_evaluate_subgroups` and `_no_subgroup_regression` implement the promotion gate: new model promotes only if overall AUC improves AND no subgroup regresses materially. Correct architecture; bugs noted in Finding 7 prevent this from working today on `age_band` specifically. Pass on architecture, with caveat.
- **Intervention exclusion from training.** `retrain_monthly` filters out intervened appointments: `training_df = training_df[training_df["intervention_count"] == 0].copy()`. This matches the main recipe's "The Feedback Loop" section. Pass.
- **Patient-stratified split.** `_patient_stratified_split` ensures each patient appears in exactly one of train/val, preventing the same-patient-both-sides leakage. Correct pattern, weakened only by the non-seeded RNG (Finding 8). Pass on structure.
- **Retention.** Main recipe's Prerequisites table covers 6-year HIPAA retention with S3 lifecycle policies; Python code does not enforce Object Lock at `put_object` time (correct: Object Lock is bucket-level). Pass.

---

## Comment Quality

Comments consistently explain *why*, not just *what*. High-value examples:

- "Probabilities and rates must be Decimal. DynamoDB rejects Python `float` for numeric attributes (precision loss, which for rolling-rate math is a quiet disaster over thousands of updates). Every rate, probability, and score value passes through `Decimal` on its way into DynamoDB and back out. This is the same gotcha that bites every DynamoDB tutorial reader at least once; the example code handles it so you see the pattern." Names the gotcha and the class of reader most likely to miss it.
- "The correctness property that matters here is **point-in-time-correctness**: every feature must reflect what was known at the moment the appointment was scored, not what becomes known later." Ties feature-store design to a concrete correctness property.
- "How often has this specific patient no-showed for this specific provider? This is one of the strongest pair-level features but cannot be stored in the patient-features group (the feature key is patient_id, not patient_id + provider_id). Compute on demand." Explains why this feature is computed inline rather than stored.
- "Break on first successful send. A real policy may continue through all preferred channels; keep it simple for the example." Acknowledges the simplification explicitly (though the loop itself has the Finding 3 bug).
- "Voice messages carry the same minimum-PHI rule as SMS: appointment time and clinic name, not visit reason." Ties the function to the domain rule.
- "Reschedules with good lead time are a separate cohort; short-lead-time reschedules count as late cancellations." Explains the label derivation rule.
- "This is a read-modify-write. In a high-throughput system, protect against concurrent updates with an optimistic-lock attribute (`version` field + ConditionExpression). Simpler version shown here." Honest about the simplification and names the production-grade pattern.
- "Exclude appointments that received interventions; see 'The Feedback Loop' in the main recipe for why naive inclusion causes the model to progressively downweight the features that correctly identified risk." Ties the training-data filter to a specific failure mode.
- "Patient-stratified split. A patient appears in exactly one of train or val; prevents leakage where the same patient is on both sides (which would flatter the AUC in ways that do not hold up on unseen patients)." Explains why the split strategy matters.
- "Only ship if overall AUC beats the incumbent AND no subgroup regresses materially." Names the fairness gate as a hard precondition for promotion.
- Step headers explicitly reference the pseudocode function: "*The pseudocode calls this `assemble_features(appointment)`.*" Makes cross-file navigation easy.
- The heads-up block at the top enumerates every production gap (no real EHR integration, no Step Functions orchestration, no SageMaker Batch Transform wrapping, no QuickSight, no subgroup fairness monitoring harness, no override workflow, no care-coordinator UI). Pedagogically honest.

---

## Logical Flow

The file reads cleanly top-to-bottom:

1. Heads-up block (scope and production caveats)
2. Setup (dependencies, IAM, knowns-upfront)
3. Configuration and constants (retry config, clients, resource names, scorer version, feature lists, routing thresholds, baseline math, cohort prior, label schema, channel ladder, `_to_decimal` helper)
4. Step 1: `assemble_features` + helpers
5. Step 2: `_load_model`, `score_appointment`, `archive_prediction`
6. Step 3: `route_predictions` + helpers
7. Step 4: `execute_outreach` + channel dispatch helpers + message-body builders
8. Step 5: `on_appointment_outcome` + helpers
9. Full nightly pipeline: `run_nightly_scoring` orchestrator + `__main__` example
10. Monthly retrain sketch: `retrain_monthly` + helpers
11. Gap to Production

The orchestrator's step-by-step `print` statements make the flow visible in a direct run, though the structured logger is not wired to a handler (Finding 4). The `__main__` example is minimal and calls real AWS resources; actually running it requires DynamoDB tables, a populated Feature Store, and a model artifact in S3. The recipe's heads-up block acknowledges this ("Running this against empty DynamoDB tables and with a freshly-trained model will route appointments based purely on the absolute risk score").

---

## What Is Clean

- `_to_decimal` helper applied consistently; no Python float reaches DynamoDB in any path
- Thresholds (`HIGH_RISK_THRESHOLD`, `DEVIATION_FLAG_THRESHOLD`) are `Decimal` constants, so score comparisons stay in Decimal and are reproducible
- Baseline math stays in Decimal end-to-end; `(1 - alpha) * prior + alpha * observation` is Decimal-native
- Feature-store read gracefully handles the `ResourceNotFound` case with a cold-start default vector, and the cold-start path is its own function (`_cold_start_patient_features`) so the two code paths are easy to compare
- Model version (`SCORER_VERSION`) and label-derivation version (`LABEL_DERIVATION_VERSION`) are threaded through every prediction, routing decision, intervention record, and training row; retraining can attribute performance shifts to specific releases
- Capacity-cap-with-bump logic: excess high-risk appointments are sorted by risk desc, the top N kept in the outreach queue, the rest dropped to the investigation queue with a `"capacity_bump"` reason, so no appointment is silently dropped
- Message-body builders are minimum-PHI by construction; the comments name the rule ("Your appointment tomorrow at 9 AM" is acceptable; "Your oncology follow-up tomorrow" is not)
- Outreach `Context` field carries `intervention_id` so delivery-receipt events can tie back to a specific intervention without parsing the message body (avoids a common PHI leak pattern)
- Label derivation is a pure function (`_derive_label(outcome, actual_arrival_time, scheduled_time)`); the comment acknowledges "the definition is stable across the training window, not that it is clever," which is the right framing
- `_update_patient_baseline` seeds the initial baseline from `POPULATION_PRIOR_NO_SHOW_RATE` rather than zero, so the first update moves from a defensible starting point rather than an implausible floor
- `run_nightly_scoring` orchestrator's `print("[1/4]...")` statements make the flow legible when the file is exercised as `__main__`, even with the logger handler issue (Finding 4)
- Retrain promotion gate requires `overall_auc > incumbent_auc + 0.005 AND no subgroup regression`; the subgroup gate is a hard AND rather than a soft warning, which is the right posture for a fairness-sensitive model
- Gap to Production section is substantial and honest: real EHR integration, idempotency via `ConditionExpression`, structured logging with PHI discipline, per-Lambda IAM scoping, VPC endpoints, KMS customer-managed keys, SageMaker wrapping for the scorer, Pinpoint HIPAA configuration, patient preference storage, monitoring and alarms, subgroup fairness monitoring, intervention effect measurement, appeal and override workflow, retention and legal hold, testing, Decimal serialization consistency

---

## Closing Assessment

The teaching content is solid and the Decimal discipline is rigorous. The five pseudocode steps map cleanly onto five Python functions (plus a sensible sixth, `archive_prediction`, that fills a pseudocode gap), the `_to_decimal` helper is applied at every DynamoDB boundary, S3 keys are correctly formatted, and the retrain promotion gate correctly encodes "must beat incumbent AND must not regress any subgroup." The minimum-PHI message bodies and the `Context`-field pattern for linking delivery receipts back to intervention IDs both demonstrate production-grade PHI handling that a reader will benefit from copying.

The three WARNINGs are fixable in under an hour each. Finding 1 (the broken `__name__ != "__production__"` guard) is a teaching hazard because the broken pattern looks reasonable at a glance and a reader is likely to copy it; replace with an explicit `check_config_replaced()` function or simply remove. Finding 2 (missing `SSEKMSKeyId` on S3 writes) mirrors Chapter 3.1's Finding 2 one-for-one; add key-ARN constants and pass them through. Finding 3 (channel dispatch silently marks unknown channels as "sent") is a real correctness bug that will misattribute intervention effects when it fires; add an explicit unknown-channel branch.

The NOTEs are editorial and primarily consist of issues already acknowledged in comments (read-modify-write race, unpaginated query, `retrain_monthly` is a sketch) plus small hygiene items (no `logging.basicConfig`, `np.random` without seed, `datetime.fromisoformat` without `Z` handling, the `Decimal("-1")` sentinel in the queue writer). Subgroup evaluation's `age_band` gap (Finding 7) is worth fixing before the retrain sketch is wired to real data; today it is silent.

With the three WARNINGs addressed this becomes a clean pass. The overall quality is on par with Chapter 3.1 and carries the Decimal / PHI discipline through cleanly.

---

## Re-review Checklist

When this review is addressed, a re-reviewer should verify:

1. The `assert` on `PINPOINT_APPLICATION_ID` is either removed, converted to a runtime log-and-continue warning, or replaced with an explicit `check_config_replaced()` function that callers invoke before deploying. The module can be imported with the placeholder value in place.
2. `_write_label_to_s3` and both `_publish_model` calls pass `SSEKMSKeyId` with documented customer-managed key constants (`LABELS_CMK_ARN`, `MODEL_ARTIFACTS_CMK_ARN`), or the comments next to each call are strengthened to explicitly require CMK enforcement via bucket policy with a named bucket-policy example.
3. `execute_outreach`'s channel dispatch adds an explicit unknown-channel branch that logs and skips without appending a `"sent"` status, and (ideally) broadens exception handling to catch `KeyError` on missing preference keys so one malformed preference record does not take down an entire outreach batch.
4. (Optional) `logging.basicConfig(...)` is added so `logger.info` / `logger.warning` output is visible in direct runs.
5. (Optional) `_put_queue_item` either omits `baseline_rate` when None, or adds a companion `baseline_available` boolean, rather than using `Decimal("-1")` as a sentinel.
6. (Optional) `_query_interventions_for_appointment` either paginates with `LastEvaluatedKey` or the inline comment is strengthened to name the silent-truncation failure mode.
7. (Optional) `_evaluate_subgroups` either drops `age_band` (and the comment names it as a gap to be closed by deriving `age_band` in `on_appointment_outcome`), or the label-writing path derives `age_band` from `age` so the subgroup loop can actually evaluate it; the index-label arithmetic is replaced with `val_meta.index.get_indexer(...)` or equivalent.
8. (Optional) `_patient_stratified_split` takes an explicit `seed` parameter and uses `np.random.default_rng(seed)` rather than the global RNG, or the function is replaced with `sklearn.model_selection.GroupShuffleSplit`.
9. (Optional) `datetime.fromisoformat` call sites add a `.replace("Z", "+00:00")` substitution (or move to `dateutil.parser.isoparse`) to handle timestamp payloads produced by non-Python publishers.
10. (Optional) `_write_label_to_s3` drops the `default=str` fallback and relies on `_decimal_to_jsonable` to produce a fully JSON-ready structure, or replaces both with a single custom `JSONEncoder` subclass used consistently.
