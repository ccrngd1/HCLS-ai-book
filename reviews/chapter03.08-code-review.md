# Code Review: Recipe 3.8 Readmission Risk Anomaly Detection (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-14
**Files reviewed:**
- `chapter03.08-readmission-risk-anomaly-detection.md` (main recipe pseudocode)
- `chapter03.08-python-example.md` (Python companion)

**Validation performed:**
- Walked the eight pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource, Kinesis, Timestream Write/Query, S3, EventBridge, CloudWatch, SageMaker Runtime, SageMaker Feature Store Runtime, and Bedrock Runtime
- Traced numeric values flowing into DynamoDB for Python-float writes (state record, scoring history, intervention history, worklist state)
- Inspected S3 keys for leading slashes and `s3://` scheme leakage
- Checked module load: import surface, client instantiation, unused symbols
- Verified healthcare requirements: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption, LOINC anchoring, calibration discipline, suppression semantics, outcome label derivation, unit conversion safety

---

## Verdict: PASS

Zero ERROR findings, three WARNING findings, eleven NOTE findings. Three WARNINGs lands at PASS per persona policy (more than 3 WARNINGs would mean FAIL).

The three WARNINGs are correctness gaps in patient lookup, query pagination, and explanation math. `on_canonical_event` uses `Limit=1` together with `FilterExpression` to find a patient's active enrollment, which silently misses the active record when the patient has earlier inactive encounters. `daily_scoring_pipeline` and `build_worklist` query the `is_active-index` GSI without pagination, which silently drops patients past the 1MB DynamoDB response limit (the recipe explicitly targets 2,000 monitored patients). `compute_top_drivers` uses within-sample normalization (`(X - mean(X)) / std(X)` across feature values within a single observation) rather than per-feature standardization against training-data statistics, producing meaningless contribution values that are then rendered as the "clinical_meaning" column in worklist rows.

The eleven NOTEs cluster around editorial and operational hygiene: unused imports, missing logger handler, Timestream f-string interpolation rather than parameterized queries, S3 `put_object` calls missing `SSEKMSKeyId`, EventBridge `put_events` responses not checked for `FailedEntryCount`, an older Bedrock model ID, the recipe's prerequisite OpenSearch indexing not implemented in code, scoring-history TTL named in setup but not set, `cohort_priority` list inconsistency between two functions, falsy-value guards on glucose features, and intervention-history trim plus aggregate counts that disagree.

The Decimal discipline at the DynamoDB boundary is consistent with Recipe 3.7's review: the recursive `_decimalize` walker handles nested dicts and lists correctly, and every DynamoDB write site goes through it. The PHI guardrails in the Bedrock prompt (constrained role, explicit "you are not making a clinical judgment", required end-phrase, `temperature=0.0`) are in good shape, and the Bedrock-failure fallback to a structured-only summary is the right pattern for a non-critical narrative layer. Unit conversion (`convert_to_canonical_units`) is paranoid for the right reasons and the comment names the silent-bias bug class explicitly.

The eight-step pseudocode-to-Python mapping is faithful in shape. Step boundaries align cleanly between the recipe and the companion, helper functions appear just before they're used, and the prose between code blocks names what's simplified, what's deferred to production, and what's a deliberate teaching choice. The Heads-up section names every production gap before the code starts; the Gap to Production section repeats the production-readiness checklist with concrete actionable items.

---

## Findings

### Finding 1: `on_canonical_event` uses `Limit=1` with `FilterExpression`; misses active enrollment when patient has older inactive records

- **Severity:** WARNING
- **Location:** `chapter03.08-python-example.md`, `on_canonical_event` (Step 3)
- **Description:** The event normalizer looks up the active enrollment by patient_id like this:

  ```python
  response = table.query(
      KeyConditionExpression=Key("patient_id").eq(patient_id),
      FilterExpression=Key("is_active").eq("true"),
      Limit=1,
  )
  items = response.get("Items", [])
  if not items:
      logger.info("event for non-enrolled patient", ...)
      return None
  ```

  DynamoDB applies `Limit` before `FilterExpression`. With `Limit=1`, the query reads exactly one item from the partition (the first by sort key, default ascending) and only then evaluates the filter. If that item is `is_active="false"` (a previous discharge that has since been closed by readmission, graduation, or program-end), the filter rejects it and the query returns empty. The active record on a later encounter_id is never read.

  The recipe explicitly handles re-enrollment: `on_outcome_event` sets `is_active="false"` on readmission, and `on_discharge_event` creates a new record with the new encounter_id when the patient is discharged again. After a single readmit-and-rediscarge cycle, every subsequent canonical event for that patient routes through `on_canonical_event`, hits the `Limit=1` branch, reads the older inactive record, and silently drops the event. Weights, blood pressures, and symptom check-ins for the patient's current monitoring window stop landing in state and stop landing in trajectory history. The worklist UI shows the patient as having no recent data; the engagement-decay flag fires; the model under-scores the patient because the trajectory features are missing.

  The teaching impact is that a reader who lifts this pattern carries the silent-loss bug into production. The correct DynamoDB pattern for "find one item matching a filter" requires either a query with `ScanIndexForward=False` plus enough `Limit` headroom to land the active record before `FilterExpression` rejects it, or a GSI keyed on `(patient_id, is_active)` so the filter becomes a key condition.

- **How to fix:** Use a GSI keyed on `(patient_id, is_active)` (composite GSI on the patient-state table). The query becomes:

  ```python
  response = table.query(
      IndexName="patient-active-index",
      KeyConditionExpression=Key("patient_id").eq(patient_id) & Key("is_active").eq("true"),
      Limit=1,
  )
  ```

  Or, if the existing schema is preserved, drop the `Limit` and let the filter run against all records for the patient (a small partition is fine):

  ```python
  response = table.query(
      KeyConditionExpression=Key("patient_id").eq(patient_id),
      FilterExpression=Attr("is_active").eq("true"),
  )
  items = response.get("Items", [])
  ```

  Note the `Attr` (not `Key`) on the FilterExpression while we're here; FilterExpression takes attribute conditions, and using `Key` works but is misleading for readers learning the API.

---

### Finding 2: `daily_scoring_pipeline` and `build_worklist` GSI queries lack pagination; silently drop patients past 1MB response limit

- **Severity:** WARNING
- **Location:** `chapter03.08-python-example.md`, `daily_scoring_pipeline` (Step 4) and the inline GSI sweep in `run_post_discharge_pipeline`
- **Description:** The daily scoring sweep iterates active patients via the `is_active-index` GSI:

  ```python
  response = table.query(
      IndexName="is_active-index",
      KeyConditionExpression=Key("is_active").eq("true"),
  )
  for item in response.get("Items", []):
      ...
  ```

  DynamoDB caps each query response at 1MB. When the total active-patient state set exceeds 1MB (the 2,000-patient program target the recipe explicitly names is comfortably above this threshold once you account for `discharge_features`, `latest_values`, `intervention_history`, and `recent_acute_events` on each record), the response is truncated and `LastEvaluatedKey` is set. Without a pagination loop, every subsequent active patient is silently dropped from the daily scoring run. The worklist for those patients stops updating; the care management team sees stale rows; readmissions for the silently-dropped subset are not flagged.

  This is the highest-impact silent failure mode in a post-discharge program: the patients most at risk of accumulation problems (the ones with rich intervention histories, multiple medication events, recent ED visits) have the largest state records and are exactly the ones that drop out first when the response truncates.

  The same pattern applies to `score_patient`'s iteration in `run_post_discharge_pipeline`. Both call sites use the GSI sweep without pagination.

  Production-grade code paginates; the teaching example here has the same shape as the production code (read GSI, iterate items) but skips the loop construct that makes it correct. A reader who copies this pattern and deploys against any non-trivial cohort hits the silent-truncation bug as soon as the active-patient set grows.

- **How to fix:** Wrap the GSI sweep in a pagination loop:

  ```python
  table = dynamodb.Table(PATIENT_STATE_TABLE)
  active_patients = []
  last_evaluated_key = None
  while True:
      kwargs = dict(
          IndexName="is_active-index",
          KeyConditionExpression=Key("is_active").eq("true"),
      )
      if last_evaluated_key:
          kwargs["ExclusiveStartKey"] = last_evaluated_key
      response = table.query(**kwargs)
      active_patients.extend(response.get("Items", []))
      last_evaluated_key = response.get("LastEvaluatedKey")
      if not last_evaluated_key:
          break

  for item in active_patients:
      score_record = score_patient(...)
  ```

  In production, replace the in-process accumulation with a Step Functions Map state that fans out per-patient scoring tasks; the loop above is the right teaching shape. Same fix applies to the iteration in `run_post_discharge_pipeline`.

---

### Finding 3: `compute_top_drivers` standardization is mathematically nonsensical; produces meaningless contribution values that ship into worklist rows

- **Severity:** WARNING
- **Location:** `chapter03.08-python-example.md`, `compute_top_drivers` (Step 6)
- **Description:** The "approximate top contributing features" function computes:

  ```python
  X = _feature_vector_to_array(features, feature_order)[0]
  ...
  if importances is not None and len(importances) == len(X):
      x_std = (X - np.mean(X)) / (np.std(X) + 1e-6)
      contribs = importances * x_std
  ```

  `X` is a single feature vector (one observation, one row, multiple columns). `np.mean(X)` and `np.std(X)` therefore compute the mean and standard deviation across feature values within that single observation. Concretely: if the observation has features `[days_post_discharge=4, discharge_risk_score=0.62, WEIGHT_current=92.5, hf_dyspnea_score=3, ...]`, then `mean(X)` is the mean of `(4, 0.62, 92.5, 3, ...)`, dominated by the largest feature (weight). `std(X)` is the spread across those mixed-scale feature values, also dominated by weight. Dividing `(X - mean(X))` by this `std(X)` produces "standardized" values that have no statistical interpretation: they describe how each feature value compares against an aggregate over unrelated features in the same vector.

  Multiplying the model's raw-feature-space coefficients (LogisticRegression `coef_` here) by these nonsense standardized values gives "contributions" that are not approximate Shapley values, not even directionally correct partial contributions to the logit, just an arithmetic combination with no model-explanation meaning.

  The function then sorts by `abs(contribution)` and returns the top 5. `build_explanation` filters to `contribution > 0` and ships them into the worklist row as:

  ```json
  {
    "feature": "WEIGHT_slope_3d",
    "value": 1.05,
    "contribution": 0.22,
    "clinical_meaning": "3-day weight slope (kg/day): 1.05"
  }
  ```

  The `contribution: 0.22` value implies "this feature drove 22% of the score" or similar, but the number is arithmetic noise. Care managers reading the worklist will see top drivers that don't correspond to what the model actually keyed on. Worse, the field `explanation_version` in `build_explanation` is set to `"shap_proxy_plus_bedrock_v1"`, claiming SHAP proxy semantics that the implementation doesn't deliver.

  The recipe text explicitly says "Production uses SageMaker Clarify (or SHAP directly against the deployed model) for per-prediction Shapley values" and acknowledges the example uses a proxy. That framing is fine when the proxy is at least directionally correct (e.g., `coef_ * X` for a linear model gives true partial contribution to the logit, scaled by a constant). The current implementation does not satisfy "directionally correct."

  Pedagogical impact is meaningful because Step 6 is the layer that justifies the worklist row to a care manager, and a reader copying the code into a real deployment ships visibly wrong explanations until SageMaker Clarify is wired. The Bedrock narrative is built on top of these contributions and inherits the wrongness.

- **How to fix:** Replace the within-sample standardization with a directionally-correct proxy. For linear models, multiply coefficients by raw feature values:

  ```python
  if importances is not None and len(importances) == len(X):
      contribs = importances * X
      for i, name in enumerate(feature_order):
          contributions.append({
              "feature":      name,
              "value":        float(X[i]),
              "contribution": float(contribs[i]),
          })
  ```

  This computes the partial contribution of each feature to the logit, which is a defensible proxy for SHAP on a linear model. For tree-based models with `feature_importances_`, multiply by the feature value (still a proxy, but at least correlates with what the model actually used) or fall back to feature-importance-only ranking with a comment explaining why this is a placeholder until Clarify is wired:

  ```python
  # Placeholder ranking by feature importance × feature value. This is a
  # rough heuristic, not a Shapley value; production wires SageMaker
  # Clarify for per-prediction SHAP. For a teaching example this gives
  # at least a directionally sensible ranking.
  ```

  Additionally, change `explanation_version` from `"shap_proxy_plus_bedrock_v1"` to `"importance_heuristic_plus_bedrock_v1"` so the audit trail accurately names what was used.

---

### Finding 4: Several unused imports

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, imports block at the top of Configuration
- **Description:** The imports block declares modules and classes the file never exercises:

  - `import io` — never used
  - `import joblib` — never used (the in-process model is created and passed by reference, not serialized)
  - `import pandas as pd` — never used (feature engineering uses numpy directly)
  - `from collections import defaultdict` — never used
  - `from typing import Optional` — never used

  Same pattern flagged in Recipe 3.7's review. Lint-clean teaching code reads better; absent any use of `pandas` or `joblib`, the imports suggest features the example doesn't actually demonstrate.

- **How to fix:** Remove all five unused imports.

---

### Finding 5: Module logger has no handler configured; structured logs drop silently when running directly

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, Configuration block (logger setup)
- **Description:** Same pattern flagged in earlier Chapter 3 reviews. The module-level logger is configured with a level but no handler:

  ```python
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  ```

  Without `logging.basicConfig` or an attached handler, `logger.info` and `logger.warning` calls (patient enrolled, event for non-enrolled patient, unknown RPM LOINC, device not assigned, Bedrock invocation failed, feature store write failed, worklist row suppressed, metric emit failed) do not reach the console when the file runs as `__main__`. The print-based narration in `run_post_discharge_pipeline` keeps step-by-step output visible, but the diagnostic logs that would help a reader trace anomalies do not appear.

- **How to fix:** Add one line near the top of Configuration:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document with a one-liner: "Visible when running this file directly; Lambda configures its own root handler and this becomes a no-op there."

---

### Finding 6: Timestream queries built via f-string interpolation rather than parameter binding

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, `fetch_modality_history` (Step 5)
- **Description:** The Timestream query embeds `patient_id`, `modality`, and timestamps directly into the SQL string:

  ```python
  query = f'''
      SELECT time, measure_value::double AS value
      FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_RPM_TABLE}"
      WHERE patient_id = '{patient_id}'
        AND modality = '{modality}'
        AND time BETWEEN from_iso8601_timestamp('{start_dt.isoformat()}')
                     AND from_iso8601_timestamp('{as_of_dt.isoformat()}')
      ORDER BY time
  '''
  response = timestream_query.query(QueryString=query)
  ```

  The inputs are internal (patient_id from patient state, modality from a hardcoded enum, timestamps from `datetime.isoformat()`), so this is not an immediately exploitable injection vulnerability. But the pattern is poor on two grounds. First, Timestream supports parameterized queries through `QueryString` with `?` placeholders plus a separate `Parameters` list; production code should use them, and teaching f-string interpolation in a healthcare-data context teaches a habit a reader may carry into a less-safe context. Second, the f-string form is fragile: a patient_id with an apostrophe (rare but possible with legacy systems that allow free-text MRN suffixes) breaks the query at the SQL parser. Same finding as Recipe 3.7.

- **How to fix:** Use the parameterized form:

  ```python
  query = (
      "SELECT time, measure_value::double AS value "
      f'FROM "{TIMESTREAM_DATABASE}"."{TIMESTREAM_RPM_TABLE}" '
      "WHERE patient_id = ? "
      "  AND modality = ? "
      "  AND time BETWEEN from_iso8601_timestamp(?) "
      "                AND from_iso8601_timestamp(?) "
      "ORDER BY time"
  )
  response = timestream_query.query(
      QueryString=query,
      Parameters=[
          {"Name": "patient_id", "Value": {"ScalarValue": patient_id}},
          {"Name": "modality",   "Value": {"ScalarValue": modality}},
          {"Name": "start",      "Value": {"ScalarValue": start_dt.isoformat()}},
          {"Name": "end",        "Value": {"ScalarValue": as_of_dt.isoformat()}},
      ],
  )
  ```

---

### Finding 7: S3 `put_object` calls set `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, two call sites: `on_canonical_event` (raw events lake) and `on_outcome_event` (training labels)
- **Description:** Both S3 writes request KMS encryption without specifying a customer-managed key:

  ```python
  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=json.dumps(canonical_event, default=str).encode("utf-8"),
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias). For PHI, customer-managed keys are required: rotation on a documented schedule, scoping grants per bucket, auditing `kms:Decrypt` per principal via CloudTrail, and the ability to disable the key to revoke access immediately. The AWS-managed default cannot be disabled, scoped, or revoked.

  This is the eighth recipe in Chapter 3 with the same omission. The Gap to Production section in this file explicitly says "Every data-at-rest store ... is encrypted with customer-managed KMS keys scoped by role." The example does not demonstrate the pattern the prose requires.

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

  A coordinated chapter-wide fix plus a STYLE-GUIDE.md addition would be more durable than re-litigating this once per recipe.

---

### Finding 8: `eventbridge.put_events` response not checked for `FailedEntryCount`

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, multiple call sites: `on_discharge_event`, `on_canonical_event`, `score_patient`, `build_worklist`, `on_outcome_event`
- **Description:** Every `put_events` call discards the response. EventBridge's `put_events` returns `FailedEntryCount` plus per-entry `ErrorCode` and `ErrorMessage`. A failed publish is silent if the response is not inspected: upstream code thinks the event went out, downstream subscribers never see it. Same finding as Recipe 3.7.

  In a post-discharge program, the consequence ranges from "the care management UI back end never gets the new patient" (failed `PatientEnrolled`) to "a critical re-score request is dropped" (failed `RescoreRequest`) to "the daily worklist never reaches the consumers" (failed `WorklistGenerated`). All silent.

- **How to fix:** Wrap call sites in a small helper that inspects the response:

  ```python
  def _put_events_checked(entries, *, source):
      response = eventbridge.put_events(Entries=entries)
      if response.get("FailedEntryCount", 0) > 0:
          for entry in response.get("Entries", []):
              if entry.get("ErrorCode"):
                  logger.error("eventbridge entry failed", extra={
                      "source":         source,
                      "error_code":     entry["ErrorCode"],
                      "error_message":  entry.get("ErrorMessage"),
                  })
          _emit_metric(f"EventBridgeFailedEntries_{source}",
                       response["FailedEntryCount"])
      return response
  ```

---

### Finding 9: Bedrock model ID hardcoded to a two-generations-old Claude version

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, Configuration block
- **Description:** The Configuration pins:

  ```python
  BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
  ```

  The main recipe's TODO calls out the need to "confirm the set of HIPAA-eligible Bedrock foundation models as of the current year." The Python pins to one specific version without surfacing the verification need. By the time of writing (2026), Claude 3 Sonnet is two generations old; Claude 3.5 Sonnet, 3.5 Haiku, and 3.7 Sonnet have all shipped on Bedrock with better instruction-following for structured-output prompts. Same finding as Recipe 3.7.

- **How to fix:** Load from environment with a recent default and document the verification path:

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

### Finding 10: OpenSearch indexing named in setup and recipe pseudocode but never implemented in code

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, Setup section and full pipeline
- **Description:** The Setup section lists permissions for `worklist-index`, `scoring-index`, and `intervention-index` in OpenSearch:

  > The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `worklist-index`, `scoring-index`, and `intervention-index` indices

  And the main recipe pseudocode (Steps 4, 7, 8) shows OpenSearch.Index calls alongside DynamoDB writes:

  ```
  DynamoDB.PutItem(table = "scoring-history", item = score_record)
  OpenSearch.Index("scoring-index", score_record)
  ...
  DynamoDB.PutItem(table = "worklist-state", item = worklist)
  OpenSearch.Index("worklist-index", worklist)
  ```

  But the Python code never instantiates an OpenSearch client and never writes to any index. `score_patient`, `build_worklist`, and `on_care_manager_action` all write to DynamoDB only. The on_outcome_event function uses `OpenSearch.Search` in pseudocode but the Python implementation queries DynamoDB.

  The audit-index value-add (governance queries, ad-hoc clinical safety review, performance analytics) the recipe relies on is not demonstrated in the example. A reader looking to understand "where does the audit trail live" sees the IAM permissions and the recipe pseudocode but no code path that actually writes there.

- **How to fix:** Either add a small OpenSearch indexing helper called from the same sites that write to DynamoDB:

  ```python
  from opensearchpy import OpenSearch, RequestsHttpConnection
  from requests_aws4auth import AWS4Auth

  # In Configuration:
  OPENSEARCH_HOST = "search-...es.amazonaws.com"

  def _index_to_opensearch(index_name, document_id, document):
      """Index a document into OpenSearch for audit and analytics.
      Wrap in try/except; index failures are logged and metric'd but do
      not block the upstream DynamoDB write."""
      try:
          client = OpenSearch(
              hosts=[{"host": OPENSEARCH_HOST, "port": 443}],
              http_auth=...,   # AWS4Auth in production
              use_ssl=True,
              connection_class=RequestsHttpConnection,
          )
          client.index(index=index_name, id=document_id, body=document)
      except Exception as e:
          logger.warning("opensearch index failed", extra={
              "index":       index_name,
              "document_id": document_id,
              "error":       str(e),
          })
          _emit_metric(f"OpenSearchIndexFailed_{index_name}", 1)
  ```

  And call from `score_patient`, `build_worklist`, and `on_care_manager_action`. Or remove the OpenSearch references from Setup and the pseudocode if they are out of teaching scope; the inconsistency is what trips readers up.

---

### Finding 11: Scoring-history TTL named in setup but never set on records

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, Setup section vs `score_patient` (Step 4)
- **Description:** The Setup section says:

  > `scoring-history` is keyed on `patient_id` (partition) and `scored_at` (sort) with a TTL attribute for automatic expiration after the audit retention window.

  But `score_patient` builds the score record without a TTL attribute:

  ```python
  score_record = {
      "score_id":               str(uuid.uuid4()),
      "patient_id":             patient_id,
      "encounter_id":           encounter_id,
      "scored_at":              as_of,
      ...
  }
  ```

  TTL on DynamoDB requires an attribute holding a Unix epoch timestamp; without one, the table accumulates rows indefinitely. This is a behavioral mismatch between setup and code that a reader provisioning the table per the Setup instructions will encounter (TTL configured on the table, no records have the attribute, nothing ever expires).

- **How to fix:** Add a TTL attribute when the record is written:

  ```python
  retention_days = 365 * 7   # HIPAA baseline 6 years plus headroom
  expiration_epoch = int(
      (datetime.now(timezone.utc) + timedelta(days=retention_days)).timestamp()
  )
  score_record["expires_at"] = expiration_epoch
  ```

  Document the chosen retention window with a one-liner. Same pattern can be added to intervention-history and worklist-state if those tables have TTL configured.

---

### Finding 12: `cohort_priority` list inconsistency between `tier_from_discharge_score` and `map_to_tier`

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, Step 1 (`tier_from_discharge_score`) and Step 4 (`map_to_tier`)
- **Description:** The two functions priority-rank cohorts to pick which threshold dictionary applies, and their lists differ:

  ```python
  # tier_from_discharge_score:
  cohort_priority = ["heart_failure", "post_op_cardiac", "copd", "diabetes",
                     "hypertension", "general"]

  # map_to_tier:
  cohort_priority = ["heart_failure", "post_op_cardiac", "copd", "diabetes",
                     "hypertension"]
  ```

  The first list includes `"general"`, the second does not. A patient in the `["general"]` cohort goes through `tier_from_discharge_score` and gets `primary_cohort = "general"`, then `DEFAULT_TIER_THRESHOLDS.get("general", DEFAULT_TIER_THRESHOLDS["DEFAULT"])` falls through to DEFAULT thresholds. The second function with `cohort_priority` not containing `"general"` returns `primary = "DEFAULT"` directly, which `DEFAULT_TIER_THRESHOLDS.get("DEFAULT")` also resolves correctly. Different code paths, same result, but reading the two functions side by side suggests a drafting inconsistency rather than a design decision.

- **How to fix:** Hoist the priority list into a module-level constant and use it in both places:

  ```python
  COHORT_PRIORITY_FOR_THRESHOLDS = [
      "heart_failure", "post_op_cardiac", "copd", "diabetes",
      "hypertension", "general",
  ]
  ```

  Both functions then `next((c for c in COHORT_PRIORITY_FOR_THRESHOLDS if c in cohorts), "DEFAULT")`. One source of truth.

---

### Finding 13: Falsy-value guards on glucose features collapse 0-readings into the "no data" branch

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, `compute_features` (Step 5)
- **Description:** The diabetes-cohort feature block uses Python truthiness to default missing values:

  ```python
  glucose_max_3d = features.get("GLUCOSE_max_3d") or 0
  glucose_min_3d = features.get("GLUCOSE_min_3d") or float("inf")
  features["dm_recent_high_glucose"] = glucose_max_3d >= 300 if glucose_max_3d else False
  features["dm_recent_low_glucose"]  = glucose_min_3d <= 70 if glucose_min_3d != float("inf") else False
  ```

  A glucose value of `0` is medically implausible but technically possible from a sensor failure or a unit-conversion bug. With `or 0`, a real measurement of `0` collapses into the "no data" branch and the conditional flag never fires. The teaching pattern "use `or` to default a missing value" is widely deployed in Python and works fine when sentinel and signal values are disjoint; for clinical numerics, they aren't. A glucose `0` is not the same as a glucose `None`; they should be distinguished.

- **How to fix:** Use explicit `is None` checks:

  ```python
  glucose_max_3d = features.get("GLUCOSE_max_3d")
  glucose_min_3d = features.get("GLUCOSE_min_3d")
  features["dm_recent_high_glucose"] = (
      glucose_max_3d is not None and glucose_max_3d >= 300
  )
  features["dm_recent_low_glucose"] = (
      glucose_min_3d is not None and glucose_min_3d <= 70
  )
  ```

  Same fix applies to the COPD `peak_flow` block.

---

### Finding 14: `intervention_history` is trimmed to last 30 entries but `compute_features` aggregates total counts

- **Severity:** NOTE
- **Location:** `chapter03.08-python-example.md`, `on_care_manager_action` (Step 8) vs `compute_features` (Step 5)
- **Description:** `on_care_manager_action` trims the in-state intervention history:

  ```python
  state["intervention_history"] = state["intervention_history"][-30:]
  ```

  And `compute_features` then computes "total" counts from that trimmed list:

  ```python
  features["outreach_attempts_total"] = sum(
      1 for i in interventions if i.get("interaction_type") == "outreach_attempted"
  )
  features["successful_contacts_total"] = sum(
      1 for i in interventions if i.get("contact_outcome") == "connected"
  )
  features["interventions_delivered_total"] = sum(
      1 for i in interventions if i.get("interaction_type") == "intervention_delivered"
  )
  ```

  The feature names say "total" but the values reflect "total within the last 30 events." For a high-touch patient with 50+ outreach attempts in the program window, the count caps at 30. The model learns from an artificially-bounded count; the bound depends on the trim threshold, which is a state-storage convenience rather than a clinical signal.

  Either fix the feature semantics (rename the features to make the bounded count explicit, e.g. `outreach_attempts_recent_30`) or compute the counts from the canonical intervention-history table (which is keyed on `patient_id` and `occurred_at` and isn't trimmed) rather than from the trimmed in-state list.

- **How to fix:** Read counts from the intervention-history table directly:

  ```python
  intervention_table = dynamodb.Table(INTERVENTION_HISTORY_TABLE)
  resp = intervention_table.query(
      KeyConditionExpression=(
          Key("patient_id").eq(state["patient_id"])
          & Key("occurred_at").gte(state["enrolled_at"])
      ),
  )
  full_history = [_undecimalize(i) for i in resp.get("Items", [])
                  if _undecimalize(i).get("encounter_id") == state["encounter_id"]]
  features["outreach_attempts_total"] = sum(
      1 for i in full_history if i.get("interaction_type") == "outreach_attempted"
  )
  ...
  ```

  Same pagination caveat from Finding 2 applies; wrap in a loop. Or rename to `_recent_30` and document the bound.

---

## Pseudocode-to-Python Consistency

| Step | Pseudocode | Python | Match |
|------|-----------|--------|-------|
| 1 | `on_discharge_event` | `on_discharge_event` + `determine_cohorts` + `tier_from_discharge_score` | Yes |
| 2 | `on_rpm_webhook` + `on_pro_check_in` | Same names + `verify_vendor_signature` + `parse_vendor_payload` + `convert_to_canonical_units` + `compute_symptom_score` | Yes; vendor signature verification is stubbed and labeled as such |
| 3 | `on_canonical_event` | Same name + `_is_more_recent` + `_trim_recent_acute_events` + `_trim_medication_events` + `classify_medication` + `should_rescore_immediately` | Mostly; `Limit=1` lookup pattern is unsafe (Finding 1) |
| 4 | `daily_scoring_pipeline` + `score_patient` | Same names + `run_modality_detector` + `cohort_prior_for` + `map_to_tier` + `score_via_sagemaker_endpoint` + `score_via_local_model` | Mostly; GSI sweep lacks pagination (Finding 2) |
| 5 | `compute_features` | Same name + `_compute_slope` + `fetch_modality_history` + `compute_patient_baseline` | Yes; cold-start fallback to cohort priors implemented; engagement decay, EHR-derived, medication, and SDOH features all present |
| 6 | `build_explanation` | Same name + `compute_top_drivers` + `humanize_driver` + `suggested_outreach_for` + `invoke_bedrock_narrative` | Mostly; SHAP proxy math is broken (Finding 3) |
| 7 | `build_worklist` + `check_suppression` | Same names + `current_capacity_for_cohorts` + `apply_capacity_caps` | Yes; suppression for inpatient, recent intervention, program-end, explicit hold all implemented |
| 8 | `on_care_manager_action` + `on_outcome_event` | Same names | Yes; outcome label derivation includes readmission, ED visit, death, observation stay; readmission closes the program window |

The eight-step framing in the prose lines up exactly with the eight code sections. The `run_post_discharge_pipeline` driver wires Steps 1-7 in sequence with print-based narration; Step 8 is documented as event-triggered and exposed as standalone callables.

---

## AWS SDK Accuracy

- **DynamoDB resource API:** `Table.get_item`, `Table.put_item`, `Table.update_item`, `Table.query` shapes are correct. `UpdateExpression` syntax correct. GSI query with boolean-as-string partition key (`is_active="true"`) is the standard workaround, comment explains. Pagination missing on GSI sweeps (Finding 2). `Limit=1 + FilterExpression` pattern is unsafe in `on_canonical_event` (Finding 1)
- **Kinesis:** `put_record(StreamName, Data, PartitionKey)` correct. PartitionKey by patient_id provides per-patient ordering
- **Timestream:** `write_records` with `Dimensions`, `MeasureName`, `MeasureValue` (string), `MeasureValueType="DOUBLE"`, `Time` (string milliseconds), `TimeUnit="MILLISECONDS"` matches the current Write API. `query` shape is correct; parameterization is not used (Finding 6). Query pagination via `NextToken` not handled but explicitly noted as a teaching simplification
- **S3:** `put_object` parameter names and key paths are correct. No leading slashes; sensible date partitioning. `SSEKMSKeyId` missing (Finding 7). `ContentType` not set (minor, S3 defaults are usually fine)
- **EventBridge:** `put_events` shape correct at five call sites. Entry fields all valid. `FailedEntryCount` not inspected (Finding 8)
- **CloudWatch:** `put_metric_data` shape correct. `Value=float(value)` matches the float requirement
- **SageMaker Runtime:** `invoke_endpoint` shape correct. CSV column-0 assumption matches XGBoost/LightGBM defaults; less robust for SKLearn LogisticRegression, comment is silent on the constraint
- **SageMaker Feature Store Runtime:** `put_record` shape correct; `ValueAsString` convention applied per the API contract. Feature group definition assumed but not shown in the example (consistent with Recipe 3.7's posture)
- **Bedrock Runtime:** `invoke_model` shape correct. Anthropic Claude 3 messages-API request body (`anthropic_version`, `max_tokens`, `temperature`, `messages` with `role`/`content`) is the right shape for Bedrock-hosted Claude. Response parsing matches the response format. Model ID is two generations old (Finding 9)
- **Boto3 Config:** `Config(retries={"max_attempts": 5, "mode": "adaptive"})` parameter names current. Adaptive-mode rationale tied to RPM-burstiness is well documented

---

## DynamoDB Decimal Check

- `_to_decimal` routes through `Decimal(str(value)).quantize(Decimal(precision))`, avoiding binary-precision drift; default `"0.001"` is sensible for milliprob-scale calibrated probabilities
- `_decimalize` recursively walks dict and list trees converting `float -> Decimal`; strings, ints, bools, None pass through unchanged
- `_undecimalize` is the symmetric inverse, used at every state read site
- `on_discharge_event` writes through `_decimalize(state)` (state contains `discharge_risk_score` as float)
- `on_canonical_event` writes through `_decimalize(state)` after appending events with float values (medication doses, measurement values)
- `score_patient` writes the score_record with `composite_raw` and `composite_calibrated` already converted via `_to_decimal` and the rest wrapped in `_decimalize`
- `build_worklist` writes through `_decimalize(worklist)` which handles the nested rows including float `composite_score`, `top_drivers` contributions, and `engagement_status` numerics
- `on_care_manager_action` and `on_outcome_event` write through `_decimalize(...)`

Result: clean. The recursive walker handles the nested dict structures (intervention_history, top_drivers, worklist rows) correctly.

---

## S3 Key Check

Keys inspected:

- `f"event_type={event_type}/year={...}/month={...}/day={...}/{event_id}.json"` (raw events lake, in `on_canonical_event`)
- `f"outcomes/year={...}/month={...}/{label_id}.json"` (training labels, in `on_outcome_event`)

Forward-slash partitioning, no leading slashes, no `s3://` scheme leakage. Athena and Glue can prune at the partition level for both buckets. Pass.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Logger comment names weights, BPs, symptom scores, patient identifiers, RPM payloads, and feature vectors as PHI. Logger calls in the example respect this; nothing dumps full payloads or feature vectors. The `worklist row suppressed` log emits `patient_id` similar to Recipe 3.7's pattern; the same finding from Recipe 3.7 (PHI-policy-vs-practice contradiction) could apply here, but the policy comment in this file is narrower ("Log structural metadata only. Never log full measurement values with patient identifiers") which permits patient_id alone in operational diagnostics. Consistent with the comment as written
- **Synthetic data labeling.** Heads-up section names every category of identifier as synthetic; points to Synthea for synthetic discharge-and-readmission events. Real LOINC codes used illustratively for tracked metrics
- **BAA / HIPAA context.** All services used (API Gateway, Lambda, Kinesis, DynamoDB, Timestream, S3, EventBridge, SageMaker, Bedrock, OpenSearch, CloudWatch) are HIPAA-eligible under the AWS BAA. Bedrock model ID pins to specific Claude version (Finding 9)
- **LOINC anchoring.** `RPM_LOINC` constants use real LOINC codes (29463-7 weight, 8480-6 SBP, 8462-4 DBP, 2708-6 SpO2, 2345-7 glucose, 33452-4 peak flow, 8867-4 heart rate). Source-code-to-canonical-key mapping matches the recipe pseudocode
- **Unit conversion safety.** `convert_to_canonical_units` is paranoid, handles kg/lb for weight and mg/dL/mmol/L for glucose, raises on unknown units. The comment explicitly names the silent-bias bug class. Strong teaching pattern
- **Calibration discipline.** Frozen `IsotonicRegression` calibrator applied separately from raw scoring. Cohort-stratified threshold dictionary documented as a clinical-governance dial
- **Tier mapping.** Cohort-stratified thresholds; `map_to_tier` looks up per-cohort with default fallback. Recipe requires this; implementation matches. Inconsistency with `tier_from_discharge_score`'s priority list (Finding 12)
- **Suppression.** Four documented cases (currently inpatient, recent successful intervention cool-down, program-end, explicit hold) all implemented in `check_suppression`. `is_currently_inpatient` and `has_active_program_hold` are read but never set in the example, an acceptable teaching simplification
- **Engagement decay.** First-class feature with the `engagement_decay_flag` boolean and the `days_since_last_data` numeric. Recipe says this is "the single most underrated feature class in post-discharge programs"; the implementation reflects that
- **Cold-start handling.** `compute_patient_baseline` returns None when fewer than `MIN_BASELINE_OBSERVATIONS=3` exist; `compute_features` falls back to `cohort_prior_for(...)` and tags `baseline_source` accordingly. Faithful to the recipe's cold-start framing
- **Bedrock prompt constraint.** "You are not making a clinical judgment", required end-phrase ("This is decision support; clinical judgment governs."), `temperature=0.0`. Strong enough to keep the LLM in the decision-support lane
- **Encryption at rest.** S3 missing `SSEKMSKeyId` (Finding 7). Other store encryption is out of code scope
- **Outcome label derivation.** Composite outcome (readmission OR ED visit OR death OR observation stay) maps to label=1; program graduation maps to label=0. Matches the recipe's recommended outcome definition. Comment names the labeling-disagreement audit cadence
- **Subgroup performance monitoring.** Not implemented in Python; named as a continuous operational requirement in Gap to Production. Same posture as earlier Chapter 3 recipes
- **FDA SaMD determination, equity-aware deployment, decommissioning criteria, retention.** Named in Gap to Production; not implemented in code

---

## Comment Quality

The file's narrative comments consistently explain *why*, not just *what*. High-value examples:

- The Decimal-precision-vs-routing-threshold framing in the Heads-up: "a calibrated probability stored as `0.5999999999` from float drift, compared against a `0.60` tier-1 cut, produces the wrong outreach intensity today and might produce the right one tomorrow if the threshold moves"
- Adaptive retry rationale tied to morning-weigh-in burstiness: "RPM webhooks are bursty (devices upload at consistent times of day, often clustered around morning weigh-ins on weight-tracking programs), and adaptive mode keeps burst windows from cascading into retry storms"
- Threshold ownership statement: "These are dials, not physical constants, and the clinical governance committee owns them"
- Unit-conversion paranoia: "A silent unit-conversion bug here multiplies every weight feature by 2.2 and the model still produces nonsense scores that look superficially sensible. This is the single most common bug class in RPM pipelines."
- Engagement-decay framing: "The single most underrated feature class in post-discharge programs. A patient who stops checking in is communicating; the model just has to listen."
- Cohort-determination as routing key: "Treat the cohort label as a routing key, not a clinical category."
- Suppression-rate-as-governance-signal: "A spike in suppressed rows ... often means the team is working its head off and patients are getting interventions that the model would otherwise re-surface ... Track both numbers; report them weekly."
- Out-of-order delivery handling: "Patients sometimes upload weights twice from a device that retried the sync, and a delayed delivery can land an older measurement after a newer one."

Section headers (`## Step 1: Enroll the Patient at Discharge`, ...) make cross-file navigation between recipe and companion easy.

---

## Logical Flow

Top-to-bottom progression:

1. Heads-up block (production gaps, decimal discipline, synthetic data, in-process model, calibration caveat, staffing realities)
2. Configuration and constants (resource names, LOINC codes, cohort-modality map, window sizes, threshold dictionary, suppression windows)
3. Step 1: enrollment
4. Step 2: RPM and PRO ingest
5. Step 3: state and trajectory update
6. Step 4: daily scoring pipeline
7. Step 5: feature engine
8. Step 6: scoring and explanation
9. Step 7: worklist build
10. Step 8: intervention and outcome capture
11. Full pipeline driver (with synthetic-data demo model)
12. Gap to Production

Helper functions appear just before their first use. Prose between code blocks consistently calls out what's simplified for teaching, what's deferred to production, and why. Pseudocode-to-Python step boundaries are explicit.

---

## What Is Clean

- Recursive `_decimalize` and `_undecimalize` handle nested dict/list structures
- LOINC anchoring on tracked RPM modalities is real; comment names the production reference-table lookup
- Unit conversion is paranoid: kg/lb for weight, mg/dL/mmol/L for glucose, raises on unknown units, comment names the silent-bias bug class
- Out-of-order delivery guard via `_is_more_recent` on `latest_values` updates
- State-record size bounded via `_trim_recent_acute_events` (14d), `_trim_medication_events` (21d), and `intervention_history[-30:]` (note: see Finding 14 for the count-vs-trim mismatch)
- Cohort priors fall back appropriately when patient-specific baseline observations are insufficient (`MIN_BASELINE_OBSERVATIONS=3`)
- Cold-start branch is explicit: `baseline_source` field tags `"patient_specific"` vs `"cohort_prior"`
- Engagement-decay flag is a first-class feature with documentation
- Heart-failure 3-lb-in-3-days textbook threshold encoded as both a numeric and a boolean feature with comment naming the patient-self-management origin
- Calibration via frozen `IsotonicRegression` applied separately from raw scoring
- Cohort-stratified tier thresholds with documented governance ownership
- Suppression covers four documented cases; the comment names suppression rate as a governance signal
- Bedrock prompt constraints (no clinical judgment, no specific drug or dose, required end-phrase, temperature=0.0)
- Bedrock-failure fallback to structured-only summary preserves worklist functionality
- Outcome label derivation via composite endpoint with linkage window
- Readmission closes program window on the encounter (sets `is_active="false"`, `program_end_reason`, `program_end_at`)
- Adaptive retry config with documented rationale tied to RPM webhook burst patterns
- CloudWatch metrics emitted at `ScoresProduced`, `Tier_*`, `WorklistsGenerated`, `WorklistRowsSurfaced`, `Suppressed_*`, action-type, `SuccessfulContacts`, `Outcome_*`
- Heads-up + Gap to Production sections together name every major production gap

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The eight pseudocode steps map cleanly onto Python functions, the LOINC-anchored RPM modality coding is correct, the unit-conversion paranoia and the silent-bias commentary are exactly the right teaching emphasis for an RPM pipeline, the cold-start fallback to cohort priors faithfully implements the recipe's framing, the engagement-decay feature is given the first-class treatment the recipe argues for, the calibration-then-tier-then-store sequencing matches the recipe's prose on calibration discipline, the suppression-then-rank-then-cap sequencing in `build_worklist` matches the recipe, and the intervention-and-outcome path closes the feedback loop with proper composite-outcome label derivation and the right encounter-window closure on readmission. The Decimal discipline at the DynamoDB boundary is consistent with Recipe 3.7's clean posture.

The three WARNINGs are operational-correctness gaps. The `Limit=1 + FilterExpression` pattern in `on_canonical_event` (Finding 1) is the highest-impact silent-loss bug because it manifests for any patient who has been re-enrolled after a previous program cycle. The missing GSI pagination (Finding 2) is the second silent-loss bug because the recipe explicitly targets a 2,000-patient cohort which is comfortably above the 1MB response limit. The broken SHAP proxy math (Finding 3) is the most pedagogically consequential because the contributions ship into worklist rows that care managers read, and the `explanation_version` field claims "shap_proxy" semantics the math does not deliver.

The eleven NOTEs are editorial or hygiene items. Findings 7 (S3 SSE without `SSEKMSKeyId`), 6 (Timestream f-string queries), 8 (EventBridge response not checked), and 9 (older Bedrock model) repeat patterns flagged in earlier Chapter 3 reviews; the cookbook would benefit from a coordinated chapter-wide fix on the SSE-KMS pattern plus a STYLE-GUIDE.md addition. Finding 10 (OpenSearch indexing in setup but not code) is the highest-information item for a reader trying to understand the audit-trail layer; the others are smaller polish.

PASS verdict. The fixes are localized; a re-review pass would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `on_canonical_event` patient lookup uses either a composite GSI keyed on `(patient_id, is_active)` or drops `Limit=1` so the FilterExpression sees all encounters for the patient. `Attr` (not `Key`) used in `FilterExpression`.
2. **(WARNING)** `daily_scoring_pipeline` and `run_post_discharge_pipeline`'s GSI sweeps wrap the `table.query` in a `LastEvaluatedKey` pagination loop. Same pattern applied to any other GSI sweep that could exceed the 1MB response limit.
3. **(WARNING)** `compute_top_drivers` replaces the within-sample standardization with either `coef_ * X` (for linear models, partial contribution to logit) or `feature_importances_ * X` (for tree models, importance-weighted feature value). `explanation_version` field updated to accurately name what was computed.
4. **(NOTE)** Unused imports (`io`, `joblib`, `pandas`, `defaultdict`, `Optional`) removed.
5. **(NOTE)** `logging.basicConfig(...)` added near the top of Configuration.
6. **(NOTE)** Timestream queries in `fetch_modality_history` use parameterized form via `Parameters=[{"Name": ..., "Value": {"ScalarValue": ...}}]`.
7. **(NOTE)** S3 `put_object` calls in `on_canonical_event` and `on_outcome_event` pass `SSEKMSKeyId` with documented customer-managed-key constants.
8. **(NOTE)** All `eventbridge.put_events` call sites inspect the response for `FailedEntryCount > 0`, ideally via a shared helper.
9. **(NOTE)** `BEDROCK_MODEL_ID` updated to a more recent Claude version (3.5 Sonnet v2 or newer) and either pinned with a verification comment or loaded from environment.
10. **(NOTE)** OpenSearch indexing implemented at the `score_patient`, `build_worklist`, and `on_care_manager_action` write sites, or removed from Setup and recipe pseudocode if out of teaching scope.
11. **(NOTE)** Score record includes a TTL `expires_at` epoch attribute; retention window documented.
12. **(NOTE)** `cohort_priority` list hoisted to a single module-level constant used by both `tier_from_discharge_score` and `map_to_tier`.
13. **(NOTE)** Glucose and peak-flow falsy-value guards replaced with explicit `is None` checks so a real `0` reading is distinguished from missing data.
14. **(NOTE)** `compute_features` aggregate intervention counts either renamed to make the 30-event bound explicit or sourced from the canonical intervention-history table with pagination.
