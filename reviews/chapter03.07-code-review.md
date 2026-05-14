# Code Review: Recipe 3.7 Patient Deterioration Early Warning (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-14
**Files reviewed:**
- `chapter03.07-patient-deterioration-early-warning.md` (main recipe pseudocode)
- `chapter03.07-python-example.md` (Python companion)

**Validation performed:**
- Walked the eight pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource, Timestream Write/Query, S3, EventBridge, SNS, CloudWatch, SageMaker Runtime, SageMaker Feature Store Runtime, and Bedrock Runtime against the current SDK
- Traced numeric values flowing into DynamoDB for Python-float writes (state record, scoring history, alert state, explanation structured drivers)
- Inspected S3 keys for leading slashes and `s3://` scheme leakage
- Checked module load: import surface, client instantiation, unused symbols
- Verified healthcare requirements: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption, LOINC anchoring, calibration discipline, alert suppression semantics, time-to-acknowledge, outcome label derivation

---

## Verdict: PASS

Zero ERROR findings, two WARNING findings, eleven NOTE findings. Two WARNINGs lands at PASS per persona policy (more than 3 WARNINGs would mean FAIL).

The two WARNINGs are concurrency and consistency hazards in the state-update and explanation-build paths: `update_patient_state` uses a non-atomic get-then-put that can lose updates under realistic Kinesis fan-out, and `build_explanation` queries scoring history with default eventually-consistent reads while assuming `items[0]` is the score that was just written. Both are localized fixes that don't require restructuring the file.

The eleven NOTEs cluster around editorial and operational hygiene: unused imports, missing logger handler, a PHI-policy-vs-practice contradiction in one suppression log, three feature-engineering gaps relative to the pseudocode (lab trajectory, hours-since-medication, recent oxygen titration), Timestream queries built via f-string interpolation, S3 `put_object` calls missing `SSEKMSKeyId`, EventBridge `put_events` responses not checked for `FailedEntryCount`, brittle SageMaker CSV response parsing, a hardcoded older Bedrock model ID, undocumented Feature Store all-strings convention, and a `"DEFAULT"` unit-type sentinel leaking into the data plane.

The Decimal discipline at the DynamoDB boundary is the cleanest in Chapter 3 so far. The recursive `_decimalize` walker handles nested dicts and lists correctly, and every DynamoDB write site goes through it. This closes the gap that bit Chapter 3.6's nested `evidence_summary` write. The PHI guardrails in the Bedrock prompt (constrained role, explicit "you are not making a clinical judgment", required end-phrase, `temperature=0.0`) are in good shape, and the Bedrock-failure fallback to a structured-only explanation is the right pattern for a non-critical narrative layer.

The eight-step pseudocode-to-Python mapping is faithful in shape. Step boundaries align cleanly between the recipe and the companion, helper functions appear just before they're used, and the prose between code blocks consistently names what's simplified, what's deferred to production, and what's a deliberate teaching choice. The Heads-up section names every production gap before the code starts; the Gap to Production section repeats the production-readiness checklist with concrete actionable items.

---

## Findings

### Finding 1: `update_patient_state` uses non-atomic get-then-put; concurrent events for the same encounter can lose updates

- **Severity:** WARNING
- **Location:** `chapter03.07-python-example.md`, `update_patient_state` (Step 2)
- **Description:** The state updater reads, mutates locally, and writes back the entire record:

  ```python
  response = table.get_item(Key=key)
  state = response.get("Item")
  ...
  state["current_vitals"][vital_key] = {...}
  ...
  table.put_item(Item=_decimalize(state))
  ```

  This is a classic non-atomic read-modify-write. Two concurrent invocations for the same `(patient_id, encounter_id)` both read the same baseline, both apply their own mutation locally, and the second write wins. The first update is silently lost.

  Several realistic operational paths produce concurrency: the periodic-tick handler running concurrently with an event-driven update during a vitals-charting burst at shift change, an ADT transfer event arriving while a vital is mid-update, or the quarantine-replay path back-filling a delayed event into an already-updated state record. Any of these can drop a vital, lose an ADT transfer, or strand a medication administration.

  The teaching impact is that a reader who lifts this pattern for production carries the silent-loss bug along. The pseudocode hides the operation behind `update_patient_state(canonical)` without showing the mechanics, so the Python companion is the reader's reference. The contrast with the immediately adjacent `score_patient` function (which correctly uses `UpdateExpression="SET last_scored_at = :ts"` plus `ConditionExpression="attribute_exists(patient_id)"`) makes the inconsistency more confusing pedagogically: one function in the same file demonstrates the right pattern, the other does not.

- **How to fix:** Use atomic `update_item` with `UpdateExpression` for each field type. The vitals branch becomes:

  ```python
  table.update_item(
      Key=key,
      UpdateExpression=(
          "SET current_vitals.#vk = :vital, "
          "    last_vital_at = :observed_at, "
          "    updated_at = :now"
      ),
      ExpressionAttributeNames={"#vk": vital_key},
      ExpressionAttributeValues={
          ":vital": _decimalize({
              "value": payload["value"],
              "observed_at": canonical_event["observed_at"],
              "recorded_at": canonical_event.get("recorded_at"),
          }),
          ":observed_at": canonical_event["observed_at"],
          ":now": datetime.now(timezone.utc).isoformat(),
      },
      ConditionExpression=(
          "attribute_not_exists(current_vitals.#vk) OR "
          "current_vitals.#vk.observed_at < :observed_at"
      ),
  )
  ```

  Catch `ConditionalCheckFailedException` and treat as success (a newer observation already won). Same pattern for labs, medication appends (use `list_append`), order appends, and ADT transfers. If the simpler get-then-put shape is needed for teaching clarity, add a version counter and a `ConditionExpression="version = :expected_v"` so concurrent updates fail closed instead of silently overwriting.

---

### Finding 2: `build_explanation` relies on eventually-consistent query for the prior score; `score_change_from_last` can be wrong

- **Severity:** WARNING
- **Location:** `chapter03.07-python-example.md`, `build_explanation` (Step 6)
- **Description:** After `score_patient` writes a new scoring-history row, `build_explanation` queries the same table for the two most recent rows and takes `items[1]` as the prior score:

  ```python
  history = history_table.query(
      KeyConditionExpression=Key("patient_id").eq(score_record["patient_id"]),
      ScanIndexForward=False,    # most recent first
      Limit=2,
  )
  prior_score = None
  items = history.get("Items", [])
  if len(items) >= 2:
      # items[0] is the current score we just wrote; items[1] is prior.
      prior_score = float(items[1].get("calibrated_probability", 0))
  ```

  Two correctness issues:

  1. DynamoDB `Query` is eventually consistent by default. The `put_item` in `score_patient` happened milliseconds before this query. Eventual consistency means there is a small window where the just-written item may not yet be visible. If it isn't, `items[0]` is the prior score and `items[1]` is the score-before-prior; the narrative reports a delta from two-scores-ago instead of from one-score-ago.
  2. The "items[0] is the current score we just wrote" comment assumes lexicographic ordering of the sort key (`scored_at` ISO8601 timestamp). If two scoring requests for the same patient land within the same millisecond (event-driven plus periodic-tick race), the ordering between them is not guaranteed.

  Operational consequence: `score_change_from_last` flows into the Bedrock prompt and into the structured explanation. If it's wrong, the LLM narrative says things like "score has increased substantially over the last 4 hours" when the actual delta is small, or vice versa. Clinicians who learn to trust narrative-vs-tier alignment lose that trust the first time they catch the mismatch.

  The immediately adjacent `route_alert` function gets this right: it calls `get_last_score(patient_id, exclude_score_id=score_record["score_id"])` which explicitly skips over the current score by ID. `build_explanation` should use the same helper.

- **How to fix:** Replace the inline query with the existing helper:

  ```python
  prior = get_last_score(score_record["patient_id"],
                          exclude_score_id=score_record["score_id"])
  prior_score = float(prior["calibrated_probability"]) if prior else None
  ```

  This consolidates "find the most recent prior score" into a single helper used by both `build_explanation` and `route_alert`, and it's correct independent of consistency mode because the exclusion is by ID rather than by ordinal position.

---

### Finding 3: Several unused imports

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, imports block at the top of Configuration
- **Description:** The imports block declares modules and classes the file never exercises:

  - `import io` — never used
  - `import joblib` — never used (the in-process model is created and passed by reference, not serialized)
  - `import pandas as pd` — never used (feature engineering uses numpy directly)
  - `from collections import defaultdict` — never used
  - `from typing import Optional` — never used
  - `from sklearn.ensemble import IsolationForest` — imported but never instantiated. `train_demo_model` returns only a `LogisticRegression`. The `score_via_local_model` function has a fallback path that mentions "Isolation Forest path" via `decision_function`, but that path is never reached.

  Lint warnings aside, the IsolationForest reference is a small pedagogical drag because the comment in `score_via_local_model` reads as if there's an exercised IF code path when there isn't.

- **How to fix:** Remove all six unused imports. Either drop the IsolationForest import and trim the fallback branch in `score_via_local_model` to match, or wire an IsolationForest into `train_demo_model` as an optional second model so the fallback is exercised. The first option is the smaller edit and matches what the example does today.

---

### Finding 4: Module logger has no handler configured; structured logs drop silently when running directly

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, Configuration block (logger setup)
- **Description:** Same pattern flagged in Chapters 3.1 through 3.6. The module-level logger is configured with a level but no handler:

  ```python
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  ```

  Without `logging.basicConfig` or an attached handler, structured `logger.info` and `logger.warning` calls (event normalization confirmation, unknown vital LOINC, unknown encounter quarantining, feature store write failure, metric emit failure, Bedrock invocation failure, alert suppression) do not reach the console when the file runs as `__main__`. The print-based narration in `run_deterioration_pipeline` keeps step-by-step output visible, but the diagnostic logs that would help a reader trace anomalies (a vital with an unknown LOINC silently dropping, a Bedrock failure falling back to the structured-only explanation) don't appear.

  Lambda configures a root handler so this isn't an issue in production. The gap shows up only in the most common first-time path: a reader running the file directly.

- **How to fix:** Add one line near the top of the Configuration block:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document with a one-liner: "Visible when running this file directly; Lambda configures its own root handler and this becomes a no-op there."

---

### Finding 5: `route_alert`'s suppression-log info call emits raw `patient_id`, contradicting the file's PHI logging policy

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `route_alert` (Step 7), the `if suppression["suppressed"]:` branch
- **Description:** The Configuration block opens with:

  ```python
  # Vitals, labs, patient identifiers, and unit assignments are PHI.
  # Log structural metadata only. Never log full vital values with patient
  # identifiers, raw clinical event payloads, lab result values, or full
  # feature vectors in application logs.
  ```

  The first sentence names patient identifiers as PHI; the second narrows the prohibition to "full vital values with patient identifiers." The two sentences set different bars. The `route_alert` suppression branch then emits the raw patient_id:

  ```python
  if suppression["suppressed"]:
      logger.info("alert suppressed", extra={
          "patient_id":    patient_id,
          "tier":          tier,
          "reason":        suppression["reason"],
      })
  ```

  Under the strict reading of the policy comment, this violates it. Under the narrow reading, it's allowed. The neighboring logs (`event for unknown encounter; quarantining` uses `event_id` only; `unknown vital LOINC` uses `loinc` only) are policy-compliant under either reading. The suppression log is the outlier.

- **How to fix:** Pick one interpretation and align both the policy comment and the code to it. Either narrow the policy comment to remove "patient identifiers" from the PHI list and explain the rationale (patient_id as a DynamoDB key is a non-identifying record locator when the patient master is access-controlled separately), or hash the patient_id in the suppression log:

  ```python
  logger.info("alert suppressed", extra={
      "patient_id_hash": _hash_patient_id(patient_id),
      "tier":            tier,
      "reason":          suppression["reason"],
  })
  ```

  The cleaner edit is to align the comment to the practice and explain the design choice, since hashing would also need a defined hash algorithm and salt management.

---

### Finding 6: Three feature-engineering gaps relative to the pseudocode

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `compute_features` (Step 4)
- **Description:** The main recipe's Step 4 pseudocode lists feature classes the Python doesn't produce:

  1. **Lab trajectory features.** Pseudocode lists `lab_{lab_code}_slope_24h` and `lab_{lab_code}_baseline` (median over `LAB_BASELINE_WINDOW_HOURS`). The Python produces only `lab_{lab_key}_current` and `lab_{lab_key}_age_hours`. The `LAB_TRAJECTORY_WINDOW_HOURS = 48` and `LAB_BASELINE_WINDOW_HOURS = 168` constants are defined but never read. Lab trajectories carry real signal: rising creatinine over 48h, falling hemoglobin, lactate trajectory if drawn serially.
  2. **`hours_since_{class}` medication features.** Pseudocode says: "Time since most recent administration of each class. FOR each class in TRACKED_MED_CLASSES: latest_admin = max_observed_at_for_class(...); features[f'hours_since_{class}'] = ...". The Python produces only the boolean `has_active_{cls}` flag, not the time-since feature. Time-since matters for confounder reasoning (the dose of opioid the patient just got might explain the respiratory rate change).
  3. **`recent_oxygen_titration` order feature.** Pseudocode includes `features["recent_oxygen_titration"] = has_recent_oxygen_change(state, hours = 2)` alongside `recent_lactate_order` and `recent_blood_culture_order`. The Python implements only the latter two.

  The Heads-up section says "the code maps to the eight core pseudocode steps." The feature engine is the single most consequential step for model quality, and three feature classes from the pseudocode aren't produced. A reader extending the example for their own population will reach for these features and find them missing.

- **How to fix:** Add three blocks to `compute_features`:

  ```python
  # Lab trajectory features.
  for lab_key in CORE_LAB_KEYS:
      lab_history = _query_lab_history(
          patient_id, encounter_id, lab_key,
          LAB_TRAJECTORY_WINDOW_HOURS, as_of,
      )
      features[f"lab_{lab_key}_slope_24h"] = _compute_slope(lab_history)
      lab_baseline = _query_lab_history(
          patient_id, encounter_id, lab_key,
          LAB_BASELINE_WINDOW_HOURS, as_of,
      )
      if len(lab_baseline) >= 3:
          features[f"lab_{lab_key}_baseline"] = float(
              np.median([v["value"] for v in lab_baseline])
          )
      else:
          features[f"lab_{lab_key}_baseline"] = None

  # Hours since most recent administration of each tracked class.
  for cls in TRACKED_MED_CLASSES:
      same_class = [
          m["administered_at"] for m in state.get("recent_medications", [])
          if m.get("therapeutic_class") == cls
      ]
      if same_class:
          latest_dt = datetime.fromisoformat(max(same_class).replace("Z", "+00:00"))
          features[f"hours_since_{cls}"] = (as_of_dt - latest_dt).total_seconds() / 3600.0
      else:
          features[f"hours_since_{cls}"] = None

  # Recent oxygen titration order.
  two_hour_cutoff = (as_of_dt - timedelta(hours=2)).isoformat()
  features["recent_oxygen_titration"] = any(
      o.get("order_type") == "respiratory"
      and "OXYGEN" in (o.get("order_code") or "").upper()
      and o.get("ordered_at", "") >= two_hour_cutoff
      for o in (state.get("recent_orders") or [])
  )
  ```

  Add `_query_lab_history` as a sibling of `_query_vital_history` and a `TRACKED_MED_CLASSES` constant in Configuration listing the classes used in `has_active_*` so the time-since features stay in sync.

---

### Finding 7: Timestream queries built via f-string interpolation rather than parameter binding

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `_query_vital_history` (Step 4)
- **Description:** The Timestream query embeds `patient_id`, `encounter_id`, `vital_key`, and timestamps directly into the SQL string:

  ```python
  query = f'''
      SELECT time, measure_value::double AS value
      FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_VITALS_TABLE}"
      WHERE patient_id = '{patient_id}'
        AND encounter_id = '{encounter_id}'
        AND vital_key = '{vital_key}'
        ...
  '''
  response = timestream_query.query(QueryString=query)
  ```

  The inputs are internal (patient_id and encounter_id from the EHR integration; vital_key from `CORE_VITAL_KEYS`; timestamps from `datetime.isoformat()`), so this isn't an immediately exploitable injection vulnerability. But the pattern is poor on two grounds.

  First, Timestream supports parameterized queries through `QueryString` with `?` placeholders plus a separate `Parameters` list. Production code should use them. Teaching f-string interpolation in a healthcare-data context teaches a habit a reader may carry into a less-safe context.

  Second, the f-string form is fragile: a patient_id with an apostrophe (rare but possible with legacy systems that allow free-text MRN suffixes) breaks the query at the SQL parser before the data layer ever sees it.

- **How to fix:** Use the parameterized form:

  ```python
  query = (
      "SELECT time, measure_value::double AS value "
      f'FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_VITALS_TABLE}" '
      "WHERE patient_id = ? "
      "  AND encounter_id = ? "
      "  AND vital_key = ? "
      "  AND time BETWEEN from_iso8601_timestamp(?) "
      "                AND from_iso8601_timestamp(?) "
      "ORDER BY time"
  )
  response = timestream_query.query(
      QueryString=query,
      Parameters=[
          {"Name": "patient_id",   "Value": {"ScalarValue": patient_id}},
          {"Name": "encounter_id", "Value": {"ScalarValue": encounter_id}},
          {"Name": "vital_key",    "Value": {"ScalarValue": vital_key}},
          {"Name": "start",        "Value": {"ScalarValue": start_dt.isoformat()}},
          {"Name": "end",          "Value": {"ScalarValue": as_of_dt.isoformat()}},
      ],
  )
  ```

  Same fix applies to the labs query when Finding 6 is addressed.

---

### Finding 8: S3 `put_object` calls set `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, two call sites: `normalize_clinical_event` (raw events lake) and `on_clinical_outcome` (training labels)
- **Description:** Both S3 writes request KMS encryption without specifying a customer-managed key:

  ```python
  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=json.dumps(canonical, default=str).encode("utf-8"),
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias). The difference matters for PHI: customer-managed keys allow rotation on a documented schedule, scoping grants per bucket, auditing `kms:Decrypt` per principal via CloudTrail, and disabling the key to revoke access immediately. The AWS-managed default cannot be disabled, scoped, or revoked.

  This is the seventh recipe in Chapter 3 with the same omission. The Gap to Production section in this file explicitly says "Every data-at-rest store ... is encrypted with customer-managed KMS keys scoped by role." The example doesn't demonstrate the pattern the prose requires.

  The data being written is PHI: raw clinical events (vitals, labs, medications, ADT) and training-label rows (encounter ID, outcome type, timestamp). Both buckets need stricter access control than the AWS-managed default key allows.

- **How to fix:** Add KMS key ARN constants and pass them through:

  ```python
  RAW_EVENTS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."
  TRAINING_LABELS_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."

  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=...,
      ServerSideEncryption="aws:kms",
      SSEKMSKeyId=RAW_EVENTS_CMK_ARN,
  )
  ```

  Given this is the seventh recipe in Chapter 3 with the same omission, a coordinated fix across the chapter plus a STYLE-GUIDE.md addition would be more durable than re-litigating this finding once per recipe.

---

### Finding 9: `eventbridge.put_events` response not checked for `FailedEntryCount`

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, multiple call sites: `invoke_scoring_orchestrator`, `score_patient`, `route_alert`'s dashboard and EHR-banner publishers, `on_clinician_acknowledgment`, `on_clinical_outcome`
- **Description:** Every `put_events` call discards the response. EventBridge's `put_events` returns `FailedEntryCount` plus per-entry `ErrorCode` and `ErrorMessage`. A failed publish is silent if the response isn't inspected: the upstream code thinks the event went out, downstream subscribers never see it, and the operational consequence is a missed alert, missed score, or missed outcome capture.

  In a deterioration pipeline the consequence is patient-safety relevant. If a `DashboardAlert` event fails silently, the charge nurse dashboard doesn't light up. If a `ScoreProduced` event fails silently in a deployment that uses EventBridge fan-out for explanation building, the explanation never gets built.

- **How to fix:** Wrap the call sites in a small helper that inspects the response:

  ```python
  def _put_events_checked(entries, *, source):
      response = eventbridge.put_events(Entries=entries)
      if response.get("FailedEntryCount", 0) > 0:
          for entry in response.get("Entries", []):
              if entry.get("ErrorCode"):
                  logger.error(
                      "eventbridge entry failed",
                      extra={
                          "source":       source,
                          "error_code":   entry["ErrorCode"],
                          "error_message": entry.get("ErrorMessage"),
                      },
                  )
          _emit_metric(f"EventBridgeFailedEntries_{source}",
                       response["FailedEntryCount"])
      return response
  ```

  Use it everywhere `put_events` is called.

---

### Finding 10: SageMaker `invoke_endpoint` response parsing assumes column 0 of CSV is the deterioration probability

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `score_via_sagemaker_endpoint` (Step 5)
- **Description:** The SageMaker invocation parses the response as CSV and takes the first column:

  ```python
  body = response["Body"].read().decode("utf-8").strip()
  # The CSV inference output is typically the predicted probability.
  raw_score = float(body.split(",")[0])
  ```

  The "typically" is doing real work. The actual response shape depends on the inference container:

  - SKLearn container with `LogisticRegression` and `predict_proba` returns CSV with two columns (P(class=0), P(class=1)). Column 0 is the probability of "no deterioration", not "deterioration". Tier mapping inverts.
  - SKLearn container with `predict` returns the binary prediction, not a probability.
  - XGBoost and LightGBM containers return single-column probability for binary classification.

  For most production deterioration models (XGBoost or LightGBM), the current code is correct. For a `LogisticRegression`-backed deployment using the default SKLearn container, the code returns the wrong probability and routes patients into the wrong tier.

  The local-model path (`score_via_local_model`) gets this right via `predict_proba(X)[0, 1]`. The endpoint path is the silent-bug version of the same.

- **How to fix:** Switch to JSON content type for self-documentation:

  ```python
  response = sagemaker_runtime.invoke_endpoint(
      EndpointName=SAGEMAKER_ENDPOINT_NAME,
      ContentType="application/json",
      Accept="application/json",
      Body=json.dumps({
          "instances": [_feature_vector_to_array(features, feature_order)[0].tolist()]
      }),
  )
  body = json.loads(response["Body"].read())
  raw_score = float(body["predictions"][0])
  ```

  If CSV is preferred, document the assumed column convention with a comment naming the inference-container compatibility constraint.

---

### Finding 11: Bedrock model ID hardcoded to a two-generations-old Claude version

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, Configuration block
- **Description:** The Configuration pins:

  ```python
  BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
  ```

  Two issues. First, the main recipe's TODO calls out the need to "confirm the set of HIPAA-eligible Bedrock foundation models as of the current year." The Python pins to one specific version without surfacing the verification need. Second, by the time of writing (2026), Claude 3 Sonnet is two generations old; Claude 3.5 Sonnet, Claude 3.5 Haiku, and Claude 3.7 Sonnet have all shipped on Bedrock with better instruction-following for structured-output prompts and lower cost-per-token.

- **How to fix:** Load from environment with a recent default, and document the verification path:

  ```python
  # HIPAA-eligible Bedrock model ID. Verify availability under the AWS BAA
  # for your deployment region. The Bedrock console's model-access page is
  # the source of truth; the AWS HIPAA Eligible Services Reference confirms
  # BAA coverage. Loaded from environment so shadow-mode A/B testing of
  # new models doesn't require code changes.
  BEDROCK_MODEL_ID = os.environ.get(
      "BEDROCK_MODEL_ID",
      "anthropic.claude-3-5-sonnet-20241022-v2:0",
  )
  ```

---

### Finding 12: Feature Store all-strings convention is undocumented

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `compute_features` (Step 4), Feature Store write block
- **Description:** The Feature Store write coerces every value to `ValueAsString`:

  ```python
  feature_record = [
      {"FeatureName": "patient_encounter_id",
       "ValueAsString": f"{patient_id}:{encounter_id}"},
      {"FeatureName": "event_time", "ValueAsString": as_of},
  ]
  for k, v in features.items():
      if v is None:
          continue
      if isinstance(v, bool):
          feature_record.append({"FeatureName": k, "ValueAsString": str(v).lower()})
      else:
          feature_record.append({"FeatureName": k, "ValueAsString": str(v)})
  ```

  The API is correct: SageMaker Feature Store's `PutRecord` accepts `ValueAsString` for all types because the feature group definition specifies the type per feature, and the runtime coerces at read time. The teaching gap is that the feature group definition (which names each feature's `FeatureType`: `Integral`, `Fractional`, `String`) isn't visible in the example. A reader looking at `put_record` without knowing how the feature group is defined can't tell that the numeric features are actually numeric.

  The bool branch emits "true"/"false" lowercase, which is one of two conventions Feature Store accepts (the other is "True"/"False"; integer 0/1 also works for boolean features defined as `Integral`).

  The `None`-skip is correct in shape but unexplained.

- **How to fix:** Add an explanatory comment, ideally with a sketch of the feature group definition:

  ```python
  # SageMaker Feature Store's PutRecord uses ValueAsString for all types.
  # The feature group definition (created in advance via
  # SageMaker.create_feature_group) declares each feature's FeatureType
  # (Integral, Fractional, String); the runtime coerces ValueAsString to
  # the declared type at read time. Booleans are written as "true"/"false"
  # lowercase per Feature Store convention; None values are skipped
  # (Feature Store treats absent features as missing).
  ```

---

### Finding 13: `"DEFAULT"` unit-type sentinel leaks into the data plane

- **Severity:** NOTE
- **Location:** `chapter03.07-python-example.md`, `_create_initial_patient_state` (Step 2) and `compute_features` (Step 4)
- **Description:** The initial state record falls back to the literal string `"DEFAULT"` when the ADT payload doesn't include a unit type:

  ```python
  "current_unit_type": adt_event["payload"].get("new_unit_type", "DEFAULT"),
  ```

  Same in `compute_features`:

  ```python
  features["unit_type"] = state.get("current_unit_type", "DEFAULT")
  ```

  This value flows through DynamoDB, into the EventBridge `ScoreProduced` event, into the alert payload, and into the OpenSearch alert audit index. An investigator reading the audit later sees `unit_type=DEFAULT` and has to recover the meaning ("we didn't know the actual unit when this scored"). The literal "DEFAULT" mixes the absence-of-data case with the "this is genuinely the default cohort" case.

  Functionally, the threshold map's fallback to `DEFAULT_TIER_THRESHOLDS["DEFAULT"]` produces the right tier mapping either way, so this isn't a routing bug. But the data-plane representation conflates two cases that should be distinct.

- **How to fix:** Use `None` as the missing-data sentinel and let the threshold map's fallback handle it:

  ```python
  "current_unit_type": adt_event["payload"].get("new_unit_type"),
  ```

  In `map_to_tier`:

  ```python
  thresholds = DEFAULT_TIER_THRESHOLDS.get(
      unit_type or "DEFAULT",
      DEFAULT_TIER_THRESHOLDS["DEFAULT"],
  )
  ```

  Document with a one-liner: "Unit type is None when the integration layer didn't populate it; the threshold map falls through to DEFAULT. Storing None makes 'we did not know' visually distinct in the alert audit from 'we knew it was the default-cohort medical floor'."

---

## Pseudocode-to-Python Consistency

| Step | Pseudocode | Python | Match |
|------|-----------|--------|-------|
| 1 | `normalize_clinical_event` | `normalize_clinical_event` + helpers | Mostly; `update_patient_state(canonical)` is factored out as a separate function called from the driver, which is an acceptable simplification |
| 2 | `update_patient_state(event)` | `update_patient_state` + `_create_initial_patient_state` + `_filter_recent_meds` | Partial; get-then-put isn't atomic (Finding 1). Out-of-order delivery guard for vitals and labs is correct |
| 3 | `on_state_change` + `on_periodic_tick` | Same names + `should_rescore_on_state_change` + `invoke_scoring_orchestrator` | Yes. Stream record diffing logic and periodic-tick GSI query both correct |
| 4 | `compute_features` | `compute_features` + `_compute_slope` + `_query_vital_history` | Partial; missing lab trajectory features, hours_since_{class} medication features, and recent_oxygen_titration order feature (Finding 6). Timestream f-string interpolation (Finding 7) |
| 5 | `score_patient` | `_feature_vector_to_array` + `score_via_sagemaker_endpoint` + `score_via_local_model` + `apply_calibration` + `map_to_tier` + `score_patient` | Mostly; CSV column-0 assumption is brittle for some inference containers (Finding 10). `last_scored_at` update with `attribute_exists` guard is correct |
| 6 | `build_explanation` | `compute_top_drivers` + `humanize_driver` + `build_explanation` + `invoke_bedrock_narrative` | Mostly; prior-score lookup uses eventually-consistent query and assumes items[0] is the just-written score (Finding 2) |
| 7 | `route_alert` + `check_suppression_rules` | Same names + `get_last_alert_for_patient` + `get_last_score` + channel-specific publishers | Yes. Suppression rules, delta detection, repage interval, channel fan-out all correct |
| 8 | `on_clinician_acknowledgment` + `on_clinical_outcome` | Same names | Yes. Atomic version increment via `ADD ack_version :one`, fail-closed `ConditionExpression`, `dismissed_as_noise` route to EventBridge for tuning, S3 label write with date partitioning |

The eight-step framing in the prose lines up exactly with the eight code sections. The `run_deterioration_pipeline` driver wires Steps 1-7 in sequence with print-based narration; Step 8 is documented as event-triggered and exposed as standalone callables.

---

## AWS SDK Accuracy

- **DynamoDB resource API:** `Table.get_item`, `Table.put_item`, `Table.update_item`, `Table.query` shapes are correct. `UpdateExpression` syntax with mixed `SET`/`ADD` in `on_clinician_acknowledgment` is correct. GSI query with boolean-as-string partition key (`is_active="true"`) is the standard workaround for boolean-typed GSI partition keys
- **Timestream:** `write_records` with `Dimensions`, `MeasureName`, `MeasureValue` (string), `MeasureValueType="DOUBLE"`, `Time` (string milliseconds), `TimeUnit="MILLISECONDS"` matches the current Write API. `query` shape is correct; parameterization isn't used (Finding 7). Pagination via `NextToken` not handled, but explicitly noted as a teaching simplification
- **S3:** `put_object` parameter names and key paths are correct. No leading slashes; sensible date partitioning (`year=/month=/day=` for events, `year=/month=` for outcomes). `SSEKMSKeyId` missing (Finding 8)
- **EventBridge:** `put_events` shape correct at six call sites. Entry fields (`Source`, `DetailType`, `Detail`, `EventBusName`) all valid. `FailedEntryCount` not inspected (Finding 9)
- **SNS:** `publish(TopicArn=, Subject=, Message=)` correct. Pager-tier message is a structural summary, not a feature dump
- **CloudWatch:** `put_metric_data` shape correct. `Value=float(value)` matches the float requirement
- **SageMaker Runtime:** `invoke_endpoint` shape correct. CSV column-0 assumption is brittle (Finding 10)
- **SageMaker Feature Store Runtime:** `put_record` shape correct; all-strings approach is right per the API but undocumented (Finding 12)
- **Bedrock Runtime:** `invoke_model` shape correct. Anthropic Claude 3 messages-API request body (`anthropic_version`, `max_tokens`, `temperature`, `messages` with `role`/`content`) is the right shape for Bedrock-hosted Claude. Response parsing (`response["body"].read()` -> `json.loads(...)["content"][0]["text"]`) matches the response format. Model ID is two generations old (Finding 11)
- **Boto3 Config:** `Config(retries={"max_attempts": 5, "mode": "adaptive"})` parameter names current. Adaptive-mode rationale tied to vitals-charting burstiness is well documented
- **Kinesis client** is instantiated but never called; the example accepts events as Python dicts directly. Acceptable teaching simplification

---

## DynamoDB Decimal Check

- `_to_decimal` routes through `Decimal(str(value)).quantize(Decimal(precision))`, avoiding binary-precision drift; default `"0.001"` is sensible for milliprob-scale values
- `_decimalize` recursively walks dict and list trees converting `float -> Decimal`; strings, ints, bools, None pass through unchanged
- `_undecimalize` is the symmetric inverse, used at every state read site
- `score_patient`'s record:
  - `raw_score` and `calibrated_probability` go through `_to_decimal`
  - `feature_count` is int, passes through
  - `put_item(Item=_decimalize(score_record))` is defensive (the floats are already Decimals via `_to_decimal`) and correct
- `route_alert`'s alert record:
  - `score`, `score_delta` are floats; `_decimalize(alert)` converts at the put boundary
  - `explanation` is a nested dict containing structured drivers with float `value` and `contribution` fields plus the Bedrock narrative string; `_decimalize` walks the structure correctly
- `update_patient_state`'s state record:
  - Vitals, labs, medication doses are floats in-memory; `_decimalize(state)` converts at put boundary
- `on_clinician_acknowledgment`'s `update_item`:
  - `:one` is int `1`; DynamoDB accepts int for `ADD` on number attribute
- `on_clinical_outcome`'s `linked_outcome` update:
  - `_decimalize({...})` wraps the outcome dict including `time_from_alert_minutes` float

Result: clean. The recursive `_decimalize` walker handles the nested-dict case that broke Chapter 3.6's review, where floats inside an `evidence_summary` dict bypassed top-level Decimal coercion.

---

## S3 Key Check

Keys inspected:

- `f"event_type={event_type}/year={...}/month={...}/day={...}/{event_id}.json"` (raw events lake)
- `f"outcomes/year={...}/month={...}/{label_id}.json"` (training labels)

Forward-slash partitioning, no leading slashes, no `s3://` scheme leakage. Consistent with Chapter 3.5's outcome-record partitioning. Athena and Glue can prune at the partition level for both buckets. Pass.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** `_redact_for_logs` produces structural summary only. Most logger calls respect the rule; `route_alert` suppression log is the outlier (Finding 5)
- **Synthetic data labeling.** Setup section names every category of identifier as synthetic; points to MIMIC-IV (with CITI training and DUA), eICU, and Synthea as appropriate dev data sources. Real LOINC codes used illustratively for vitals
- **BAA / HIPAA context.** All services used (Kinesis, DynamoDB, Timestream, S3, EventBridge, SNS, CloudWatch, SageMaker, Bedrock) are HIPAA-eligible under the AWS BAA. Bedrock model ID pins to specific Claude version; the verification need is named in the recipe TODO but not in the Python (Finding 11)
- **LOINC anchoring.** `VITAL_LOINC` and `LAB_LOINC` constants use real LOINC codes. Source-code-to-canonical-key mapping matches the recipe pseudocode
- **Calibration discipline.** Frozen `IsotonicRegression` calibrator applied separately from raw scoring. Training-data calibration optimistic-bias caveat is explicit
- **Tier mapping.** Unit-stratified thresholds; `map_to_tier` looks up per-unit with default fallback. Recipe requires this; implementation matches
- **Alert suppression.** Four documented cases (ICU patient, comfort care, recent RRT, explicit registry) all implemented in `check_suppression_rules`. `last_rrt_activation_at` and `is_comfort_care` fields are read but never set in the example, called out via comments
- **Delta detection and repage interval.** `score_delta >= DELTA_ALERT_THRESHOLD` plus `cooled_down` check work as the recipe describes. Comment names the tradeoff
- **Bedrock prompt constraint.** "You are not making a clinical judgment", required end-phrase, `temperature=0.0`. Strong enough to keep the LLM in the decision-support lane
- **Encryption at rest.** S3 missing `SSEKMSKeyId` (Finding 8). Other store encryption is out of code scope
- **Outcome label derivation.** Composite endpoint (ICU transfer, code blue, unexpected death, sepsis bundle initiation, rapid response activation) maps to label=1; uneventful_discharge maps to label=0. Matches the recipe's recommended outcome definition
- **Acknowledgment capture.** Enum-validated disposition; atomic version increment via `ADD ack_version :one`; fail-closed `ConditionExpression`. `dismissed_as_noise` forwarded to EventBridge for operational tuning
- **Time-to-acknowledge metric.** Computed and emitted on every ack
- **Subgroup performance monitoring.** Not implemented in Python; named as a continuous operational requirement in Gap to Production. Same posture as Chapters 3.4-3.6
- **FDA SaMD determination, decommissioning criteria, retention.** Named in Gap to Production; not implemented in code

---

## Comment Quality

The file's narrative comments consistently explain *why*, not just *what*. High-value examples:

- The Decimal-precision-vs-routing-threshold framing in the Heads-up: "a calibrated probability stored as `0.5999999999` from float drift, compared against a `0.60` high-tier cut, produces the wrong routing today and might produce the right routing tomorrow if the threshold moves; that kind of drift is exactly the bug class clinical safety review will flag"
- Adaptive retry rationale tied to vitals-charting rhythm: "vitals charting is bursty (med-pass rounds at 0600/1200/1800/2200 on inpatient units, plus admission/transfer surges)"
- Threshold ownership statement: "These are dials, not physical constants, and the clinical governance committee owns them"
- Out-of-order delivery handling commentary: "That guard is the difference between 'vitals jumped, then jumped back, then jumped again' feature artifacts and a clean trajectory"
- Event-driven vs periodic split rationale: "A pipeline that does only event-driven scoring will miss patients whose deterioration is gradual; a pipeline that does only periodic scoring will be slow to catch acute changes. Both paths exist in every production deterioration system"
- Feature-count tradeoff: "More features past this point produce diminishing returns and operational pain: drift detection becomes harder, feature pipeline maintenance becomes harder, missingness patterns multiply, and model-monitoring dashboards turn into a wall of charts that nobody reads"
- Zombie-state-record framing for the `attribute_exists(patient_id)` guard
- Explanation-layer-on-non-critical-path framing
- Repage and delta tuning frame

Section headers (`## Step 1: Normalize a Clinical Event`, ...) make cross-file navigation between recipe and companion easy.

---

## Logical Flow

Top-to-bottom progression:

1. Heads-up block (production gaps, decimal discipline, synthetic data, in-process model, calibration caveat)
2. Configuration and constants
3. Step 1: normalization
4. Step 2: state update
5. Step 3: scoring trigger (event + periodic)
6. Step 4: feature engine
7. Step 5: scoring + calibration
8. Step 6: explanation
9. Step 7: alert routing
10. Step 8: acknowledgment + outcome
11. Full pipeline driver
12. Gap to Production

Helper functions appear just before their first use. Prose between code blocks consistently calls out what's simplified for teaching, what's deferred to production, and why. Pseudocode-to-Python step boundaries are explicit.

---

## What Is Clean

- Recursive `_decimalize` and `_undecimalize` handle nested dict/list structures; this closes the Chapter 3.6 nested-evidence-summary gap
- `_redact_for_logs` keeps structural metadata only
- Bedrock prompt is constrained: explicit "you are not making a clinical judgment" guardrail, required end-phrase, `temperature=0.0`
- Anthropic Claude 3 messages-API request and response shapes are correct
- Bedrock-failure fallback to structured-only explanation is the right pattern for a non-critical narrative layer
- `last_scored_at` update with `attribute_exists(patient_id)` ConditionExpression prevents zombie-state writes for discharged patients; comment names the failure mode
- Out-of-order delivery guard for vitals and labs (only overwrite if `observed_at` is newer); comment names the trajectory-feature artifact this prevents
- Event-driven plus periodic scoring split with `last_scored_at` cooldown
- Tier mapping is unit-stratified; threshold dictionary documented as a clinical-governance dial
- Alert suppression covers all four cases with documented reasons
- Delta detection plus repage interval enforcement
- Atomic `ADD ack_version :one` with fail-closed `ConditionExpression` on acknowledgment
- `dismissed_as_noise` forwarding to EventBridge for operational tuning
- Outcome label derivation with date-partitioned S3 write
- Time-to-acknowledge metric emission
- Adaptive retry config with documented rationale
- Heads-up + Gap to Production sections together name every major production gap

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The eight pseudocode steps map cleanly onto Python functions, the LOINC-anchored vital-sign coding is correct, the calibration-then-tier-then-store sequencing matches the recipe's prose on calibration discipline, the suppression-then-delta-then-channels sequencing in `route_alert` matches the recipe, and the acknowledgment-and-outcome path closes the feedback loop with proper label derivation. The Decimal discipline at the DynamoDB boundary is the cleanest in Chapter 3 so far.

The two WARNINGs are operational-correctness gaps. The non-atomic `update_patient_state` (Finding 1) is the more consequential because under realistic Kinesis fan-out concurrent ADT/vital/lab events for the same encounter can lose each other's writes, and the immediately adjacent `score_patient` function correctly demonstrates the right pattern (`UpdateExpression` plus `ConditionExpression`). The eventually-consistent `build_explanation` prior-score query (Finding 2) is narrower but the fix is trivial because the `route_alert` function already has the right helper (`get_last_score(exclude_score_id=...)`); reusing it consolidates two query sites into one.

The eleven NOTEs are editorial or hygiene items. Findings 8 (S3 SSE without `SSEKMSKeyId`) and 5 (PHI policy contradiction in suppression log) are repeats of patterns flagged in earlier Chapter 3 reviews, and the cookbook would benefit from a coordinated chapter-wide fix on the SSE-KMS pattern plus a STYLE-GUIDE.md addition rather than re-litigating these once per recipe. Findings 6 (feature-engineering gaps) and 10 (CSV column-0 assumption) are the highest-information items for a reader who's actually building this; the others are smaller polish.

PASS verdict. The fixes are localized; a re-review pass would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `update_patient_state` uses atomic `update_item` with `UpdateExpression` for each field type (vital, lab, medication append, ADT, order), with out-of-order-delivery `ConditionExpression` guards on vital and lab. `ConditionalCheckFailedException` is caught and treated as success on the out-of-order guard.
2. **(WARNING)** `build_explanation` uses `get_last_score(score_record["patient_id"], exclude_score_id=score_record["score_id"])` for the prior score, or uses `ConsistentRead=True` plus an explicit exclude-by-id loop.
3. **(NOTE)** Unused imports (`io`, `joblib`, `pandas`, `defaultdict`, `Optional`, `IsolationForest`) removed, or `IsolationForest` actually wired into `train_demo_model` as a second model with the fallback path exercised.
4. **(NOTE)** `logging.basicConfig(...)` added near the top of Configuration.
5. **(NOTE)** `route_alert`'s suppression log either hashes the patient_id or the policy comment is rewritten to permit patient_id in operational diagnostics with rationale documented.
6. **(NOTE)** `compute_features` produces `lab_{lab_key}_slope_24h`, `lab_{lab_key}_baseline`, `hours_since_{class}` for tracked classes, and `recent_oxygen_titration`. `LAB_TRAJECTORY_WINDOW_HOURS` and `LAB_BASELINE_WINDOW_HOURS` are exercised. `_query_lab_history` and `TRACKED_MED_CLASSES` defined.
7. **(NOTE)** Timestream queries use parameterized form via `Parameters=[{"Name": ..., "Value": {"ScalarValue": ...}}]`.
8. **(NOTE)** S3 `put_object` calls in `normalize_clinical_event` and `on_clinical_outcome` pass `SSEKMSKeyId` with documented customer-managed-key constants.
9. **(NOTE)** All `eventbridge.put_events` call sites inspect the response for `FailedEntryCount > 0`, ideally via a shared helper.
10. **(NOTE)** `score_via_sagemaker_endpoint` either uses JSON content type with `predictions[0]` parsing or carries a clear comment naming the assumed CSV column convention and the inference-container compatibility constraint.
11. **(NOTE)** `BEDROCK_MODEL_ID` updated to a more recent Claude version (3.5 Sonnet v2 or newer) and either pinned with a verification comment or loaded from environment.
12. **(NOTE)** `compute_features`'s Feature Store write block carries a comment explaining `ValueAsString` convention and the implicit feature-group definition dependency.
13. **(NOTE)** `_create_initial_patient_state` uses `None` (not `"DEFAULT"`) as the missing-unit-type sentinel; `map_to_tier` falls back via `unit_type or "DEFAULT"`.
