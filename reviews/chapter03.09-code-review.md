# Code Review: Recipe 3.9 Cybersecurity / Access Pattern Anomalies (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-14
**Files reviewed:**
- `chapter03.09-cybersecurity-access-pattern-anomalies.md` (main recipe pseudocode)
- `chapter03.09-python-example.md` (Python companion)

**Validation performed:**
- Walked the eight pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource, Kinesis, S3, EventBridge, CloudWatch, SageMaker Runtime, SageMaker Feature Store Runtime, and Bedrock Runtime
- Traced numeric values flowing into DynamoDB for Python-float writes (workforce identity, patient context, schedule, user-state, case-state, suppression rules)
- Inspected S3 keys for leading slashes and `s3://` scheme leakage
- Checked the `model` and `calibrator` plumbing through the pipeline driver
- Verified healthcare requirements: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption posture, suppression semantics, outcome label derivation, workforce-PII handling

---

## Verdict: PASS

Zero ERROR findings, three WARNING findings, eleven NOTE findings. Three WARNINGs lands at PASS per persona policy (more than 3 WARNINGs would mean FAIL).

The three WARNINGs are correctness gaps in case lookup, off-hours role mapping, and the new-patient-fraction feature. `find_existing_case` uses `table.scan` with `Limit=10` together with a `FilterExpression`, which silently misses an existing open case when the matching item isn't in the first ten scanned (and unordered) records, so duplicate cases are created for the same user-patient pair instead of grouping events into one investigation. `enrich_event` constructs the `is_off_hours` role key as `f"{user_role}_day"`, which only matches the `registered_nurse_day` and `physician_day` entries in the `role_normal_windows` dictionary; the explicit `billing_analyst` and `database_administrator` entries in that dictionary are unreachable, and those roles silently fall through to the day-shift default (7-19) instead of their intended business-hours window (8-18). `aggregate_user_activity` computes `never_seen_before_fraction` after `append_to_user_state` has already added the current patient_id to `known_patients`, which makes the fraction always zero in the demo flow and zero in production for any patient currently being aggregated.

The eleven NOTEs cluster around editorial and operational hygiene: unused imports, missing logger handler, S3 `put_object` calls without `SSEKMSKeyId`, EventBridge `put_events` responses not inspected for `FailedEntryCount`, an older Bedrock model ID, a `Key()`-vs-`Attr()` API misuse in `FilterExpression`, the trained `model` from `train_demo_model` being passed to the pipeline but never invoked at scoring time, the `score_via_sagemaker_endpoint` function being defined but never called, `find_existing_case` using a full-table scan rather than a GSI-backed query, `check_care_relationship` accepting an `as_of` parameter without filtering by time, and the score record's `feature_snapshot` being embedded directly rather than persisted via `feature_snapshot_id` as the pseudocode shows.

The Decimal discipline at the DynamoDB boundary is consistent with Recipe 3.7 and 3.8: the recursive `_decimalize` walker handles nested dicts and lists correctly, every DynamoDB write site goes through it, and float precision is bounded at the configured quantization (`Decimal(precision)` defaults to `0.0001`). The PHI logging discipline (logger comment names workforce identity, patient identity, break-glass reasons, and Bedrock prompts as PHI/PII) is in good shape; nothing in the example dumps full payloads or feature vectors. The Bedrock prompt constraints (no clinical or employment-action recommendations, no assertions of intent, required end-phrase "This is decision support; investigator judgment governs.", `temperature=0.0`) are appropriate for an investigator-facing summary, and the Bedrock-failure fallback to a structured-only summary preserves case-builder functionality.

The eight-step pseudocode-to-Python mapping is faithful in shape. Step boundaries align between the recipe and the companion, helper functions appear just before they're used, and the prose between code blocks names what's simplified for teaching, what's deferred to production, and what's a deliberate teaching choice. The Heads-up section names every production gap before the code starts; the Gap to Production section repeats the production-readiness checklist with concrete actionable items, including the workforce-policy and joint privacy-and-infosec governance work that has to happen alongside the technology.

---

## Findings

### Finding 1: `find_existing_case` uses `scan` with `Limit=10 + FilterExpression`; silently misses an existing open case and produces duplicate cases

- **Severity:** WARNING
- **Location:** `chapter03.09-python-example.md`, `find_existing_case` (Step 7)
- **Description:** The case-grouping lookup is implemented as:

  ```python
  response = table.scan(
      FilterExpression=(
          (Key("workforce_id").eq(workforce_id))
          & (Key("patient_id").eq(patient_id))
          & (Key("status").eq("open_for_review"))
          & (Key("opened_at").gte(cutoff))
      ),
      Limit=10,
  )
  items = response.get("Items", [])
  return _undecimalize(items[0]) if items else None
  ```

  DynamoDB applies `Limit` before `FilterExpression` on both `query` and `scan`. With `Limit=10`, the scan reads exactly ten items from the table (in unspecified order, since `scan` has no ordering guarantee) and only then evaluates the filter. If none of those ten items match the four filter conditions, the response is empty even when a matching open case exists later in the table. `find_existing_case` returns `None`, `build_case` proceeds to the new-case branch, and a duplicate case is opened for the same workforce-patient pair.

  The recipe explicitly relies on case grouping: the same user repeatedly accessing the same patient over the seven-day window should land as one investigation with multiple events attached, not many separate cases. Same-name family-relationship snooping often produces a cluster of accesses over hours or days; if those accesses fragment into separate cases, the privacy-office investigator sees disconnected evidence and the LLM-generated narratives for each fragment lose the cumulative context. Worse, the case-state table grows faster than expected (one case per scored event instead of one per user-patient pair), the privacy office's daily case queue inflates, and the `Suppressed_RecentDismissal` metric understates suppression effectiveness because each new fragment is evaluated independently.

  Same finding pattern as Recipe 3.8 Finding 1, but for a `scan` rather than a `query`. The fix in the recipe text already names the production answer ("Production indexes case_state by (workforce_id, patient_id) for this lookup"), and the inline comment names the GSI shape ("In production, query via a GSI on (workforce_id, patient_id, opened_at)"); the Python implementation doesn't follow either path.

  Pedagogical impact is substantial because case grouping is a first-order feature of the privacy-office workflow described in the recipe, and a reader copying this pattern carries the silent-loss bug into a production privacy-monitoring deployment.

- **How to fix:** Provision a GSI on the case-state table keyed on `(workforce_id, patient_id)` with `opened_at` as the sort key, and replace the scan with:

  ```python
  response = table.query(
      IndexName="workforce-patient-index",
      KeyConditionExpression=(
          Key("workforce_id").eq(workforce_id)
          & Key("opened_at").gte(cutoff)
      ),
      FilterExpression=(
          Attr("patient_id").eq(patient_id)
          & Attr("status").eq("open_for_review")
      ),
      ScanIndexForward=False,
      Limit=10,
  )
  ```

  Or, if the demo wants to avoid prerequisite GSI provisioning, drop `Limit` and let the filter run against all case rows (acceptable for a small teaching dataset; comment that it does not scale):

  ```python
  response = table.scan(
      FilterExpression=(
          Attr("workforce_id").eq(workforce_id)
          & Attr("patient_id").eq(patient_id)
          & Attr("status").eq("open_for_review")
          & Attr("opened_at").gte(cutoff)
      ),
  )
  ```

  Either way, switch from `Key()` to `Attr()` inside `FilterExpression` (see Finding 6).

---

### Finding 2: `is_off_hours` role-key construction renders the `billing_analyst` and `database_administrator` dictionary entries unreachable

- **Severity:** WARNING
- **Location:** `chapter03.09-python-example.md`, `is_off_hours` (Step 2) and the call site in `enrich_event`
- **Description:** The dictionary inside `is_off_hours` defines per-role hour windows:

  ```python
  role_normal_windows = {
      "registered_nurse_day": (7, 19),
      "registered_nurse_night": (19, 7),
      "physician_day": (7, 19),
      "physician_night": (19, 7),
      "billing_analyst": (8, 18),
      "database_administrator": (8, 18),
      "default": (7, 19),
  }
  ```

  But the call site in `enrich_event` always appends `_day`:

  ```python
  event["is_off_hours"] = is_off_hours(
      event["observed_at"],
      f"{event['user_role']}_day" if event.get("user_role") else "default",
  )
  ```

  The constructed key for `user_role="registered_nurse"` is `registered_nurse_day`, which matches the dict (7-19). Same for `physician_day`. But for `user_role="billing_analyst"`, the constructed key is `billing_analyst_day`, which is not in the dictionary; `dict.get(key, default)` falls through to the `default` entry, which is also (7-19). For `database_administrator`, same story. The two intended-to-be-tighter (8-18) windows are dead code; no input value ever produces those keys.

  The behavioral consequence is that RULE-040 ("off-hours access by users on standard daytime schedules without scheduled coverage") evaluates against a wider 7-19 window than the dictionary intends for those roles. A DBA accessing at 7:30 AM is treated as "in normal hours" rather than "off-hours" because (7-19) covers it; the rule fails to fire. A billing analyst accessing at 6:30 PM hits the same bug. Both scenarios are exactly the cases the broader-than-clinical "business hours" entries are designed to catch, and both are silently lost.

  The bug is also a pedagogical hazard. A reader inspecting the dictionary sees explicit per-role entries and assumes they're applied; tracing the code reveals the call site never produces those keys. The intent of the dictionary contradicts the intent of the call site, and a reader copying the pattern (dictionary plus `_day`-suffix call) into production carries a silent-coverage gap. The recipe's prose around RULE-040 references off-hours patterns being "low-confidence" but real signal; the implementation collapses non-clinical-role coverage to the clinical-role default.

  The recipe text doesn't claim per-role business-hours windows as a teaching point, so the fix is small: either drop the dead dictionary entries, or stop appending `_day` and look up the bare role.

- **How to fix:** Drop the `_day` suffix at the call site so the dictionary's per-role entries become reachable, and add a separate `_night` lookup based on the `shift_pattern` enrichment:

  ```python
  shift_pattern = state.get("shift_pattern", "day")  # from user-state record
  role_key = (
      f"{event['user_role']}_{shift_pattern}"
      if event.get("user_role") and event.get("user_role") in {"registered_nurse", "physician"}
      else event.get("user_role") or "default"
  )
  event["is_off_hours"] = is_off_hours(event["observed_at"], role_key)
  ```

  Or, cleaner, restructure the dictionary so the lookup is explicit:

  ```python
  ROLE_WINDOWS = {
      ("registered_nurse", "day"):   (7, 19),
      ("registered_nurse", "night"): (19, 7),
      ("physician", "day"):          (7, 19),
      ("physician", "night"):        (19, 7),
      ("billing_analyst", "day"):    (8, 18),
      ("database_administrator", "day"): (8, 18),
  }
  DEFAULT_WINDOW = (7, 19)
  ```

  And do a tuple-keyed lookup inside `is_off_hours`. Either path makes the dictionary contents and the call-site behavior agree.

---

### Finding 3: `aggregate_user_activity.never_seen_before_fraction` is always 0 because `append_to_user_state` adds the current patient_id to `known_patients` before the aggregator runs

- **Severity:** WARNING
- **Location:** `chapter03.09-python-example.md`, `aggregate_user_activity` (Step 4), interaction with `append_to_user_state` ordering in `run_access_anomaly_pipeline`
- **Description:** The pipeline driver calls `append_to_user_state` before `run_baseline_detector`:

  ```python
  # Update user-state before computing baselines so the windows
  # include the current event.
  append_to_user_state(enriched["workforce_id"], enriched)

  print(f"[4-5/8] running baseline + graph detectors for ...")
  baseline_output = run_baseline_detector(enriched)
  ```

  The comment justifies the ordering for the time-window aggregations, which is correct: the current event should be in the window. But `append_to_user_state` also unconditionally adds the current `patient_id` to `known_patients`:

  ```python
  known = set(state.get("known_patients", []))
  known.add(enriched_event["patient_id"])
  state["known_patients"] = list(known)[-1000:]
  ```

  And `aggregate_user_activity` uses the post-update `known_patients` set as the "seen-before" history:

  ```python
  unique_patients = {e["patient_id"] for e in in_window}
  ...
  seen_before = set(state.get("known_patients", []))
  ...
  "never_seen_before_fraction": sum(
      1 for p in unique_patients if p not in seen_before
  ) / max(len(unique_patients), 1),
  ```

  Two conditions ensure this fraction is always zero. First, the current event's `patient_id` was just added to `known_patients` and is also in `unique_patients`. Second, every other patient in the recent-events window was added to `known_patients` when their event was previously appended. The set difference `unique_patients - seen_before` is therefore always empty, and `never_seen_before_fraction` is always `0`.

  The recipe explicitly cites "new_patient_fraction" as one of the deviation signals worth tracking ("a user who normally opens 30-60 charts per day suddenly opens 300; ... `new_patient_fraction_24_hour`" appears in the per-feature z-score block). The intent is "what fraction of patients accessed in this window are new to this user"; the implementation answers "always zero." The feature is dead.

  The downstream effect is real: `FEATURE_WEIGHTS["new_patient_fraction_24_hour"] = 1.2` weights this feature meaningfully into the per-feature z-score that drives `run_baseline_detector.deviation_score`, and the `top_n_drivers` SHAP-style ranking in `build_case` would have surfaced it for an investigator. With the feature stuck at zero, its z-score against any non-zero baseline is constant and the feature never appears as a top driver. A reader copying the pattern into production wires a feature into the model that contributes nothing.

  Pedagogical impact is meaningful because Step 4 is the per-user behavioral baseline (the classic UEBA backbone the recipe spends pages on), and a feature that the recipe's prose specifically calls out as one of the headline deviation signals doesn't actually work.

- **How to fix:** Compute `seen_before` from `known_patients` *before* the current patient is appended, or move the `known_patients` update to *after* the aggregator runs. The cleaner option is to pass the previous `known_patients` set into the aggregator explicitly:

  ```python
  def aggregate_user_activity(workforce_id, window_hours, ending_at,
                               known_patients_before_event):
      ...
      seen_before = set(known_patients_before_event)
      ...

  # In the pipeline driver:
  state_response = dynamodb.Table(USER_STATE_TABLE).get_item(
      Key={"workforce_id": enriched["workforce_id"]}
  )
  prior_state = _undecimalize(state_response.get("Item")) or {}
  known_before = prior_state.get("known_patients", [])

  append_to_user_state(enriched["workforce_id"], enriched)
  baseline_output = run_baseline_detector(enriched, known_before=known_before)
  ```

  Or, restructure so `append_to_user_state` returns the prior state alongside the update, and the aggregator reads from the returned prior. Either approach makes the new-patient-fraction feature non-trivial.

---

### Finding 4: Several unused imports

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, imports block at the top of Configuration
- **Description:** The imports block declares modules and classes the file never exercises:

  - `import io` — never used
  - `import joblib` — never used (the in-process model is created and passed by reference, not serialized)
  - `import pandas as pd` — never used (feature engineering uses dicts and numpy directly)
  - `from collections import defaultdict, Counter` — neither used
  - `from typing import Optional` — never used (no type hints)

  Same pattern flagged in Recipes 3.7 and 3.8 reviews. Lint-clean teaching code reads better; absent any use of `pandas`, `joblib`, `defaultdict`, or `Counter`, the imports suggest features the example doesn't actually demonstrate.

- **How to fix:** Remove all five unused imports.

---

### Finding 5: Module logger has no handler configured; structured logs drop silently when running directly

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, Configuration block (logger setup)
- **Description:** Same pattern flagged in earlier Chapter 3 reviews. The module-level logger is configured with a level but no handler:

  ```python
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  ```

  Without `logging.basicConfig` or an attached handler, `logger.info` and `logger.warning` calls (unknown workforce user, suppressed-by-recent-dismissal, Bedrock invocation failed, metric emit failed, OpenSearch index failed if added) do not reach the console when the file runs as `__main__`. The print-based narration in `run_access_anomaly_pipeline` keeps step-by-step output visible, but the diagnostic logs that would help a reader trace anomalies don't appear.

- **How to fix:** Add one line near the top of Configuration:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document with a one-liner: "Visible when running this file directly; Lambda configures its own root handler and this becomes a no-op there."

---

### Finding 6: `find_existing_case` uses `Key()` inside `FilterExpression` instead of `Attr()`

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `find_existing_case` (Step 7)
- **Description:** The scan's `FilterExpression` is built with `Key()`:

  ```python
  response = table.scan(
      FilterExpression=(
          (Key("workforce_id").eq(workforce_id))
          & (Key("patient_id").eq(patient_id))
          & (Key("status").eq("open_for_review"))
          & (Key("opened_at").gte(cutoff))
      ),
      Limit=10,
  )
  ```

  In boto3, `boto3.dynamodb.conditions.Key` and `boto3.dynamodb.conditions.Attr` share the same base `ConditionBase` class, so `Key().eq(...)` inside a `FilterExpression` works at runtime. The convention, however, is `Key` for `KeyConditionExpression` (where the condition must reference a partition or sort key) and `Attr` for `FilterExpression` (where any attribute is fair game). Using `Key` in a filter context teaches a misleading habit: a reader who later writes a query and accidentally puts a non-key attribute in the `KeyConditionExpression` via `Key()` will hit `ValidationException` and won't immediately understand why.

- **How to fix:** Switch to `Attr` for the filter and import it:

  ```python
  from boto3.dynamodb.conditions import Key, Attr
  ...
  FilterExpression=(
      Attr("workforce_id").eq(workforce_id)
      & Attr("patient_id").eq(patient_id)
      & Attr("status").eq("open_for_review")
      & Attr("opened_at").gte(cutoff)
  ),
  ```

---

### Finding 7: S3 `put_object` calls set `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, two call sites: `on_ehr_audit_event` (raw events lake) and `on_investigator_action` (training labels)
- **Description:** Both S3 writes request KMS encryption without specifying a customer-managed key:

  ```python
  s3_client.put_object(
      Bucket=RAW_EVENTS_BUCKET,
      Key=...,
      Body=json.dumps(canonical_event, default=str).encode("utf-8"),
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (`aws/s3` alias). For PHI and workforce PII, customer-managed keys are required: rotation on a documented schedule, scoping grants per bucket, auditing `kms:Decrypt` per principal via CloudTrail, and the ability to disable the key to revoke access immediately. The AWS-managed default cannot be disabled, scoped, or revoked.

  This is the ninth recipe in Chapters 2 and 3 with the same omission. The recipe text and Gap to Production section explicitly say "Every data-at-rest store ... is encrypted with customer-managed KMS keys scoped by role." The example doesn't demonstrate the pattern the prose requires. The audit-event payloads include workforce identifiers, patient identifiers, IP addresses, and break-glass override reasons; the training-label payloads include adjudication outcomes and case identifiers. Both warrant customer-managed-key encryption.

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
- **Location:** `chapter03.09-python-example.md`, four call sites: `build_case` (CaseOpened), `initiate_breach_review`, `refer_to_hr`, `on_investigator_action` (CaseClosed)
- **Description:** Every `put_events` call discards the response. EventBridge's `put_events` returns `FailedEntryCount` plus per-entry `ErrorCode` and `ErrorMessage`. A failed publish is silent if the response is not inspected: upstream code thinks the event went out, downstream subscribers never see it. Same finding pattern as Recipes 3.7 and 3.8.

  In an access-monitoring pipeline, the consequence ranges from "the case management UI back end never gets the new case" (failed `CaseOpened`) to "the breach-notification clock never starts" (failed `BreachReviewInitiated`) to "HR never receives the referral package" (failed `HRReferral`). All silent. The breach-notification clock failure is particularly serious because the HIPAA 60-day window starts at discovery, and a silent EventBridge failure on `BreachReviewInitiated` means the discovery time is never officially recorded for the downstream notification workflow. State law windows (California's 15-business-day rule, for example) are even tighter.

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

  Replace the four direct `eventbridge.put_events(Entries=[...])` call sites with `_put_events_checked([...], source="...")`.

---

### Finding 9: Bedrock model ID hardcoded to a two-generations-old Claude version

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, Configuration block
- **Description:** The Configuration pins:

  ```python
  BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
  ```

  The main recipe's TODO calls out the need to "confirm the current set of HIPAA-eligible Bedrock foundation models." The Python pins to one specific version without surfacing the verification need. By the time of writing (2026), Claude 3 Sonnet is two generations old; Claude 3.5 Sonnet, 3.5 Haiku, and 3.7 Sonnet have all shipped on Bedrock with better instruction-following for structured-output prompts (which matters for the case-narrative prompt that constrains the model from making intent assertions). Same finding as Recipes 3.7 and 3.8.

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

### Finding 10: `train_demo_model` returns a `model` that's passed to `run_access_anomaly_pipeline` but never invoked at scoring time

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `train_demo_model`, `run_access_anomaly_pipeline`, and `composite_score`
- **Description:** The Heads-up section says: "We train a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint." A reader reasonably interprets this as: the trained `model` substitutes for the SageMaker composite-anomaly endpoint that the recipe describes, with `model.predict_proba` plugged into `composite_score` in place of the real-time endpoint call.

  In the actual implementation, the `model` is passed into `run_access_anomaly_pipeline` and never used:

  ```python
  def run_access_anomaly_pipeline(audit_events, model, calibrator, feature_order,
                                   graph):
      ...
      score_record = composite_score(
          enriched, rules_flags, baseline_output,
          graph_output, sequence_output, calibrator,
      )
  ```

  And `composite_score` builds the score from a hand-coded weighted sum of detector outputs, not from the trained model:

  ```python
  raw_composite = (
      weights["rules"]    * rules_confidence
    + weights["baseline"] * baseline_output["deviation_score"]
    + weights["graph"]    * graph_output["graph_score"]
    + weights["sequence"] * sequence_score
  )
  calibrated = apply_calibration(raw_composite, calibrator, ...)
  ```

  The trained `model` is used only by `train_demo_model` itself to generate `raw_probs` for fitting the `IsotonicRegression` calibrator. After training, the `model` object is dead weight: it occupies the function signature of `run_access_anomaly_pipeline`, gets bound at the call site (`model, calibrator, feature_order = train_demo_model()`), and never participates in scoring. A reader who runs the example and inspects which sklearn methods get called is going to be confused.

  The deeper concern is calibration validity. The calibrator was fit on `model.predict_proba` outputs over synthetic 8-feature vectors that don't correspond to the 4-detector composite that scoring actually computes. When `apply_calibration(raw_composite, calibrator, ...)` runs, it's mapping a hand-coded weighted sum through a calibration curve learned on a different distribution. The teaching example produces numbers, but the calibration step is illustrative rather than functional. The recipe's prose says "Calibration is shown as isotonic regression on a small held-out set" which is technically accurate, but the held-out set isn't the same distribution as the inputs to which calibration is later applied.

  This is a NOTE rather than a WARNING because the recipe is upfront about this being a teaching simplification and the real production path is a SageMaker endpoint, but the model parameter and `score_via_sagemaker_endpoint` function (defined but never called) leave a reader uncertain about which path the demo actually uses.

- **How to fix:** Either remove the unused `model` parameter from `run_access_anomaly_pipeline` and add a comment naming the simplification:

  ```python
  def run_access_anomaly_pipeline(audit_events, calibrator, graph):
      """End-to-end pipeline. The composite score is a hand-coded weighted
      sum of detector outputs; production replaces this with a SageMaker
      endpoint call to a trained anomaly model. The calibrator here is
      illustrative; production calibration is fit on real adjudicated
      cases, not on synthetic probabilities."""
  ```

  Or, the more thorough fix: thread the trained model into `composite_score` so the example actually exercises `model.predict_proba` on a constructed feature vector (the four detector scores plus rule confidence and care-relationship strength), with a comment noting the production endpoint swap. Either path resolves the dead-parameter confusion.

---

### Finding 11: `find_existing_case` performs a full-table scan; in production code shape, this should be a GSI-backed query

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `find_existing_case` (Step 7)
- **Description:** Independent of Finding 1's correctness bug, the choice of `table.scan` rather than `table.query` against a GSI is itself a teaching concern. The case-state table in production grows linearly with case volume; a privacy-monitoring program operating across a 10,000-workforce health system produces tens of cases per day, accumulating tens of thousands of cases in the first year and continuing to grow. A `scan` reads (and bills for) every item in the table on every call, even when only a tiny subset matches the filter.

  The recipe's prose names the production shape ("In production, query via a GSI on (workforce_id, patient_id, opened_at)") but the code does not implement it. A reader copying this pattern into production triggers DynamoDB scan throughput limits and pays for full-table reads on every case-grouping check.

  The teaching alternative, even without provisioning a real GSI, is to write the call shape that mirrors production:

  ```python
  # Production GSI: workforce-patient-index, partition=workforce_id, sort=opened_at
  response = table.query(
      IndexName="workforce-patient-index",
      KeyConditionExpression=Key("workforce_id").eq(workforce_id),
      ...
  )
  ```

  Even if the local DynamoDB instance does not have the GSI provisioned, the call-shape teaches the right pattern.

- **How to fix:** Replace the scan with a GSI-backed query as shown above. Document the GSI in the Setup section's table-schema notes alongside the existing `case-state is keyed on case_id` line.

---

### Finding 12: `score_via_sagemaker_endpoint` is defined but never called in the demo flow

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `score_via_sagemaker_endpoint` (Step 6)
- **Description:** The function `score_via_sagemaker_endpoint` is defined with a thoughtful comment about batch-transform-vs-real-time-endpoint trade-offs, but no call site exists. The composite-scoring path uses the hand-coded weighted sum (see Finding 10). The function shows the production-shape boto3 call, which is useful for a reader, but its dead-code status in the demo means a reader running the file end-to-end never sees it exercise.

  This is a smaller concern than Finding 10 because the Heads-up section explicitly names this function as illustrative ("The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call"). Documentation is fine; readers know the intent. The NOTE flags that the function appears in the file with the appearance of being part of the demo flow when it isn't.

- **How to fix:** Either add an early-return branch in the composite-scoring path that invokes the SageMaker endpoint when an environment flag is set:

  ```python
  if os.environ.get("USE_SAGEMAKER_ENDPOINT", "false").lower() == "true":
      raw_composite = score_via_sagemaker_endpoint(features, feature_order)
  else:
      raw_composite = (
          weights["rules"]    * rules_confidence
        + weights["baseline"] * baseline_output["deviation_score"]
        + ...
      )
  ```

  Or, label the function with a clear comment block: "# Reference implementation; not invoked in the demo. Use this shape when wiring to a real SageMaker endpoint."

---

### Finding 13: `check_care_relationship` accepts an `as_of` parameter that is never used

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `check_care_relationship` (Step 2)
- **Description:** The function signature is:

  ```python
  def check_care_relationship(workforce_id, patient_id, as_of):
      ...
  ```

  And the call site in `enrich_event` passes `event["observed_at"]` for `as_of`. But inside the function body, `as_of` is not used. The graph traversal looks at all edges between the workforce and patient nodes regardless of when those edges were created.

  The recipe's prose explicitly names time-bounded relationship checking as an important enrichment ("Care-relationship enrichment ... Care teams, on-call schedules, encounter assignments, and order signatures are the primary sources" with the implication that the relationship needs to be active at access time). Production reads time-bounded edges from Neptune (the Gremlin query in `query_neptune_for_paths`'s docstring includes `between` time predicates conceptually). The teaching example accepts the parameter and discards it, which leaves a reader uncertain whether the demo is doing time-bounded checking or not.

  The behavioral consequence in the demo graph is small (the demo edges have no time attribute) but the pattern is misleading: a workforce member who had a care relationship six months ago but doesn't now appears as having a relationship today. Production has to filter by time.

- **How to fix:** Either implement a minimal time check (look for an edge attribute `valid_from`/`valid_to` and filter accordingly, even if the demo graph doesn't populate those attributes) and document why it's a no-op in the demo, or remove the parameter:

  ```python
  def check_care_relationship(workforce_id, patient_id, as_of):
      """...
      The teaching example does not filter by time because the demo graph
      edges have no `valid_from`/`valid_to` attributes. Production filters
      with a Gremlin `has('valid_from', lt(as_of)).has('valid_to', gt(as_of))`
      pattern; care relationships expire and reactivate as encounters open
      and close.
      """
  ```

  Either path makes the parameter's role explicit.

---

### Finding 14: Score record's `feature_snapshot` is embedded directly rather than persisted via `feature_snapshot_id`; pseudocode-Python divergence

- **Severity:** NOTE
- **Location:** `chapter03.09-python-example.md`, `composite_score` (Step 6) vs `chapter03.09-cybersecurity-access-pattern-anomalies.md` Step 6 pseudocode
- **Description:** The recipe's pseudocode for Step 6 includes:

  ```
  return {
      ...
      feature_snapshot_id:       persist_features(event, baseline_output, graph_output)
  }
  ```

  The Python implementation embeds the snapshot directly:

  ```python
  return {
      ...
      "feature_snapshot": baseline_output["feature_snapshot"],
      ...
  }
  ```

  The pseudocode pattern (persist features to S3 or Feature Store, store an opaque ID in the score record) is the production-correct approach because it keeps the score record bounded in size and supports point-in-time reproducibility (Recipe 3.7's review made this explicit). The Python embeds the full feature dictionary, which inflates the case-state record (each case carries multiple score records in `scoring_record_ids` or, in this implementation, the full snapshot per score) and breaks the production point-in-time pattern.

  This is acceptable as a teaching simplification in isolation, but the pseudocode-to-Python step labels the same field differently and the prose between the code blocks doesn't call out the divergence. A reader copying the example into production loses the snapshot-by-reference pattern. Same posture as Recipe 3.8 Finding 11.

- **How to fix:** Either implement `persist_features` writing to S3 with a date-partitioned key and store the resulting `feature_snapshot_id` in the score record (consistent with the pseudocode):

  ```python
  def persist_features(event, baseline_output, graph_output):
      snapshot = {
          "event_id":      event["event_id"],
          "feature_vector": baseline_output["feature_snapshot"],
          "graph_evidence": graph_output["relationship_evidence"],
      }
      snapshot_id = f"FEAT-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:8]}"
      s3_client.put_object(
          Bucket=FEATURE_SNAPSHOTS_BUCKET,
          Key=f"snapshots/year={...}/month={...}/{snapshot_id}.json",
          Body=json.dumps(snapshot, default=str).encode("utf-8"),
          ServerSideEncryption="aws:kms",
          SSEKMSKeyId=FEATURE_SNAPSHOTS_CMK_ARN,
      )
      return snapshot_id
  ```

  Or, document the divergence with a one-liner: "The teaching example embeds the snapshot inline; production persists it to S3 and stores an opaque ID, both for size containment and for point-in-time reproducibility."

---

## Pseudocode-to-Python Consistency

| Step | Pseudocode | Python | Match |
|------|-----------|--------|-------|
| 1 | `on_ehr_audit_event` | `on_ehr_audit_event` + `resolve_workforce_id` + `resolve_patient_id` + `normalize_event_type` + `normalize_resource_type` | Yes; identifier resolution stubbed and labeled as such; raw event lake write included |
| 2 | `enrich` | `enrich_event` + `is_off_hours` + `is_off_shift` + `check_care_relationship` + `geolocate_ip` + `is_unusual_for_user` | Mostly; `is_off_hours` role-key construction has a coverage bug (Finding 2); `check_care_relationship` accepts unused `as_of` (Finding 13) |
| 3 | `run_rules_engine` | `run_rules_engine` + `compute_name_uniqueness` + `zip_population` + `is_member_of_household` + `severity_from_break_glass_reason` + `max_severity_confidence` | Yes; rules RULE-001 through RULE-060 implemented; severity-floor mapping consistent with the recipe |
| 4 | `run_baseline_detector` | `run_baseline_detector` + `derive_peer_group` + `aggregate_user_activity` + `get_user_baseline` + `get_peer_baseline` + `weighted_max_z` + `days_since` | Mostly; `never_seen_before_fraction` is structurally always 0 (Finding 3); cold-start fallback to peer-only baseline implemented |
| 5 | `run_graph_detector` | `run_graph_detector` + `query_neptune_for_paths` + `query_unit_overlap` + `get_user_recent_patient_set` + `compute_graph_cohesion` + `check_family_link` | Yes; NetworkX in-process graph stands in for Neptune; cluster-cohesion threshold and family-match path documented |
| 6 | `composite_score` | `composite_score` + `cohort_for_user` + `cohort_weights_for` + `apply_calibration` + `tier_from_score` + `score_via_sagemaker_endpoint` + `generate_score_id` | Mostly; trained `model` not invoked at scoring time (Finding 10); `feature_snapshot_id` pattern not implemented (Finding 14); SageMaker endpoint function defined but unused (Finding 12) |
| 7 | `build_case` | `build_case` + `find_existing_case` + `update_existing_case` + `check_recent_dismissal` + `add_suppression_rule` + `fetch_workforce_record` + `fetch_patient_record` + `fetch_recent_user_activity` + `top_n_drivers` + `build_case_narrative_prompt` + `invoke_bedrock_narrative` + `_emit_metric` | Mostly; `find_existing_case` has the silent-loss `Limit + scan` bug (Finding 1) and uses `Key` in `FilterExpression` (Finding 6); Bedrock fallback to structured-only summary preserves functionality on Bedrock failure |
| 8 | `on_investigator_action` | `on_investigator_action` + `initiate_breach_review` + `refer_to_hr` + `update_user_state_with_prior_violation` | Yes; valid-outcome enumeration enforced; suppression rule added on dismissal; HR referral and breach-review event-bus handoffs in place |

The eight-step framing in the prose lines up with the eight code sections. The `run_access_anomaly_pipeline` driver wires Steps 1-7 in sequence with print-based narration; Step 8 is documented as event-triggered and exposed as a standalone callable. Helper functions appear just before they're used.

---

## AWS SDK Accuracy

- **DynamoDB resource API:** `Table.get_item`, `Table.put_item`, `Table.update_item`, `Table.query`, `Table.scan` shapes are correct. `UpdateExpression` syntax correct. TTL via epoch-int `ttl` attribute used in suppression rules. `find_existing_case` uses `scan` with `Limit=10 + FilterExpression` (Finding 1) and `Key()` in the filter (Finding 6); both are misleading at minimum and the first is a silent-loss bug. The `find_existing_case` lookup should be a GSI-backed `query` in production (Finding 11).
- **Kinesis:** `put_record(StreamName, Data, PartitionKey)` correct. `PartitionKey=workforce_id` provides per-user ordering for sequence-based detection downstream
- **S3:** `put_object` parameter names and key paths are correct. No leading slashes; sensible date partitioning (`source=...`, `year=...`, `month=...`, `day=...`). `SSEKMSKeyId` missing on both write sites (Finding 7). `ContentType` not set (minor; S3 defaults are usually fine for JSON archives that Athena reads)
- **EventBridge:** `put_events` shape correct at four call sites. Entry fields all valid (`Source`, `DetailType`, `Detail`, `EventBusName`). `FailedEntryCount` not inspected (Finding 8)
- **CloudWatch:** `put_metric_data` shape correct. `Value=float(value)` matches the float requirement; `Unit="Count"` default is sensible
- **SageMaker Runtime:** `invoke_endpoint` shape correct in `score_via_sagemaker_endpoint`. CSV column-0 assumption matches XGBoost/LightGBM defaults; the function is defined but unused in the demo (Finding 12)
- **SageMaker Feature Store Runtime:** Client instantiated but never used. The recipe pseudocode discusses Feature Store; the demo skips it. Acceptable teaching simplification given the in-memory state model
- **Bedrock Runtime:** `invoke_model` shape correct. Anthropic Claude 3 messages-API request body (`anthropic_version`, `max_tokens`, `temperature`, `messages` with `role`/`content`) is the right shape for Bedrock-hosted Claude. Response parsing matches the response format. Model ID is two generations old (Finding 9). Bedrock-failure fallback to a structured-only summary is the right pattern for a non-critical narrative layer
- **Boto3 Config:** `Config(retries={"max_attempts": 5, "mode": "adaptive"})` parameter names current. Adaptive-mode rationale tied to ingest burstiness is well documented

---

## DynamoDB Decimal Check

- `_to_decimal` routes through `Decimal(str(value)).quantize(Decimal(precision))`, avoiding binary-precision drift; default `"0.0001"` is sensible for confidence scores and calibrated probabilities
- `_decimalize` recursively walks dict and list trees converting `float -> Decimal`; strings, ints, bools, None pass through unchanged
- `_undecimalize` is the symmetric inverse, used at every state read site
- `seed_demo_data` writes workforce, patient, schedule, and user-state items through `_decimalize`
- `append_to_user_state` writes the state record through `_decimalize` after appending the new event entry
- `add_suppression_rule` writes through `_decimalize` (the `ttl` integer is preserved correctly through the walker)
- `build_case` writes the case through `_decimalize(case)` after the case dict has float `composite_score` and `composite_calibrated`
- `update_existing_case` uses `_to_decimal(composite)` for the explicit single-field update value
- `update_user_state_with_prior_violation` writes only boolean and string, no float
- `on_investigator_action` writes through `_decimalize(case)` after the case dict has the float `composite_score` preserved through the read-modify-write cycle

Result: clean. The recursive walker handles the nested dict structures (rules_flags with confidence floats, evidence with relationship_evidence cluster_cohesion floats, baseline_evidence with z-score floats, top_z_features list of dicts) correctly.

---

## S3 Key Check

Keys inspected:

- `f"source={source_format}/year={obs_at[:4]}/month={obs_at[5:7]}/day={obs_at[8:10]}/{canonical_event['event_id']}.json"` (raw events lake, in `on_ehr_audit_event`)
- `f"outcomes/year={case['outcome_at'][:4]}/month={case['outcome_at'][5:7]}/{label_record['label_id']}.json"` (training labels, in `on_investigator_action`)

Forward-slash partitioning, no leading slashes, no `s3://` scheme leakage. Athena and Glue can prune at the partition level for both buckets. Pass.

---

## Healthcare-Specific Requirements

- **PHI and workforce-PII logging discipline.** Logger comment names workforce identity, patient identity, break-glass reasons, full audit payloads, full feature vectors, and Bedrock prompts as PHI/PII. Logger calls in the example respect this; nothing dumps full payloads or feature vectors. The pipeline driver's `print` statements include workforce_id and patient_id (synthetic identifiers in the demo); production would gate this behind a debug flag
- **Synthetic data labeling.** Heads-up section names every category of identifier as synthetic; the demo dataset uses obviously synthetic IDs (`WF-NURSE-001`, `PT-WOJ-001`); the surname uniqueness reference (`Wojnarowski`, `Kovalenko`, `Abernathy`, `Okonkwo`) is illustrative
- **BAA / HIPAA context.** All services used (Kinesis, Lambda, DynamoDB, Neptune, Timestream, OpenSearch, SageMaker, Bedrock, Comprehend Medical, EventBridge, Step Functions, S3, CloudWatch) are HIPAA-eligible under the AWS BAA. Bedrock model ID pins to specific Claude version (Finding 9). The recipe text TODOs point to verifying current Bedrock model HIPAA eligibility, which is the right disclaimer
- **Workforce identity and patient identity treated as comparably sensitive.** The recipe and code both reflect the unusual property of access monitoring: the workforce member's identity, role, department, manager, hire date, address ZIP, and last name are all enrichment data that the system reads and stores. Logger and CloudTrail audit posture should treat workforce data with the same discipline as patient data; the comment at the top of the file does name both categories explicitly
- **Care-relationship enrichment as the central distinguishing signal.** The recipe makes "care relationship at access time" the primary determinant of legitimate-vs-problematic access. The implementation surfaces this via `check_care_relationship` (Finding 13 about the unused `as_of` parameter) and the `care_relationship_strength` numeric, which feeds into rules RULE-020 and RULE-021 (VIP weak-care, employee-patient weak-care). The recipe acknowledges that EHR care-team data is incomplete; the suppression-rule mechanism (`add_suppression_rule` with `valid_for_days`) supports the operational workaround for floor-coverage and cross-coverage gaps
- **Calibration discipline.** `IsotonicRegression` calibrator applied separately from raw scoring. Cohort-stratified threshold dictionary (`DEFAULT_TIER_THRESHOLDS`) documented as a clinical-governance dial owned by the joint privacy-and-infosec committee. Calibration currently fits on synthetic data that doesn't match the actual scoring distribution (Finding 10's deeper concern); production fits on adjudicated cases
- **Tier mapping.** Cohort-stratified thresholds; `tier_from_score` looks up per-cohort with default fallback. Recipe requires this; implementation matches. Cohort definitions (`PRIVILEGED_ROLES`, `CLINICAL_ROLES`, new-user under 90 days) align with the recipe's cohort-stratified weighting pattern
- **Suppression.** Two documented cases (recent dismissal, investigation overlap) implemented in `check_recent_dismissal` and the case-grouping path. The investigation-overlap path (`check_investigation_overlap`) is named in pseudocode but not implemented in Python; the case-grouping logic in `find_existing_case` covers a subset of that intent. Acceptable teaching simplification
- **Outcome label derivation.** Composite outcome (confirmed_violation positive; everything else negative) maps to `label = 1 if case["outcome"] == "confirmed_violation" else 0`. The label drops the "dismissed_inconclusive" nuance (Recipe 3.8 review made this same point); a reader using these labels for retraining should be aware that inconclusive cases are noisy negatives. The recipe acknowledges this in the prose ("The label problem is severe: confirmed violations are rare, the labeling latency is long, dismissed candidates are noisy negatives")
- **Workforce equity and subgroup performance.** Not implemented in Python; named as a continuous operational requirement in Gap to Production. Same posture as earlier Chapter 3 recipes
- **Acceptable-use policy and workforce notification.** Named in Gap to Production as a non-optional precondition. Not technical scope; correctly placed in the prose
- **Encryption at rest.** S3 missing `SSEKMSKeyId` on both write sites (Finding 7). Other store encryption is out of code scope; the prerequisites table names the customer-managed-key requirement for every PHI- and PII-bearing store
- **Bedrock prompt constraint.** "You are not making a determination of policy violation and you are not asserting intent." Required end-phrase: "This is decision support; investigator judgment governs." `temperature=0.0`. Strong enough to keep the LLM in the decision-support lane and prevent intent-attribution that would create labor-and-legal exposure

---

## Comment Quality

The file's narrative comments consistently explain *why*, not just *what*. High-value examples:

- The Decimal-precision-vs-routing-threshold framing in the Heads-up: "a calibrated probability stored as `0.7999999999` from float drift, compared against a `0.80` tier-1 cut, produces the wrong privacy-office routing today and might produce the right one tomorrow if the threshold moves. That kind of drift is exactly the bug class clinical-governance review will flag, except here the governance is the joint privacy-and-infosec committee."
- Adaptive retry rationale tied to ingest burstiness: "Audit-event ingest is bursty (EHRs flush large batches at quarter-hour or top-of-hour boundaries; IdP and VPN logs spike at shift change), and adaptive mode keeps burst windows from cascading into retry storms against the enrichment cache and the scoring endpoint."
- Threshold ownership statement: "These are dials, not physical constants, and the [joint governance] committee owns them."
- Same-name rule rationale: "Family-relationship access is the most common policy violation by volume; same-name is the strongest single signal. Weighted by name uniqueness so a Smith-on-Smith hit is much weaker than a Wojnarowski-on-Wojnarowski hit."
- Cluster-cohesion framing: "A legitimate user's recent patient set typically has high cohesion: the patients are on the same unit, are part of the same care team, share a hospitalist or specialist. A compromised credential being used to enumerate records produces a low-cohesion patient set."
- Cold-start handling rationale: "Every new role assignment is a cold start. A nurse who transfers from cardiology to oncology has a perfectly good baseline for 'cardiology nurse activity' and a useless one for 'oncology nurse activity,' and the detector needs to avoid producing six weeks of false positives during the transition."
- Self-monitoring of the monitoring system: "The system ironically has to apply the same access-monitoring discipline to itself that it monitors elsewhere."
- The label-derivation nuance: "'dismissed_inconclusive' cases are not the same as 'dismissed_legitimate' cases ... an inconclusive dismissal means the investigator could not determine whether a violation occurred, which is a noisy negative for retraining purposes."
- Case-grouping window justification: "The 7-day default works well for the typical curiosity-snooping pattern; programs that primarily track methodical credential-compromise patterns sometimes use longer windows (14-30 days) to keep the slower-burn cases in a single investigation."

Section headers (`## Step 1: Ingest and Normalize an Audit Event`, ...) make cross-file navigation between recipe and companion easy.

---

## Logical Flow

Top-to-bottom progression:

1. Heads-up block (production gaps, decimal discipline, synthetic data labeling, in-process model, calibration caveat, capacity simulation caveat)
2. Configuration and constants (resource names, detector weights per cohort, tier thresholds per cohort, rule severity floors, window sizes, suppression windows, name-uniqueness reference, ZIP-population reference, cohort definitions)
3. Step 1: ingest and normalize
4. Step 2: enrichment (identity, schedule, care relationship, patient context, network and device)
5. Step 3: rules engine (eight rules, severity-floor combination)
6. Step 4: per-user behavioral baselines
7. Step 5: graph-based detection
8. Step 6: composite scoring with calibration
9. Step 7: case builder with Bedrock narrative
10. Step 8: outcome capture and learning loop
11. Full pipeline driver (with synthetic data, demo graph, demo model)
12. Gap to Production

Helper functions appear just before their first use. Prose between code blocks consistently calls out what's simplified for teaching, what's deferred to production, and why. Pseudocode-to-Python step boundaries are explicit.

---

## What Is Clean

- Recursive `_decimalize` and `_undecimalize` handle nested dict/list structures (rules flags, evidence dicts, top-z-features lists)
- Identifier resolution function structure (`resolve_workforce_id`, `resolve_patient_id`) exposes the production swap point cleanly with comments explaining the EMPI and IAM mapping work
- Canonical event format separates the source-specific parser from the downstream pipeline; downstream consumers never see Epic-vs-Cerner-vs-MEDITECH differences
- Kinesis partition key by `workforce_id` preserves session ordering for the sequence-based detector that the recipe describes (and that the demo defers to a future step)
- Per-rule severity weighting via `RULE_SEVERITY_FLOOR` lets a high-severity rule with moderate confidence beat a low-severity rule with high confidence; the `max_severity_confidence` aggregation is documented
- Cohort-stratified detector weights and tier thresholds are first-class (`DEFAULT_DETECTOR_WEIGHTS`, `DEFAULT_TIER_THRESHOLDS` keyed by cohort label); the `cohort_for_user` derivation lays out the role-and-tenure logic explicitly
- Surname uniqueness reference exposes the production swap to a US Census or equivalent regional dataset
- ZIP-population reference exposes the production swap to Census ZCTA data with the small-ZIP threshold made explicit
- Break-glass severity inference from documented reason text uses keyword heuristics with a clear comment naming the production swap to a tuned classifier
- Cluster-cohesion check captures the credential-compromise reconnaissance pattern that pure rule-based detection misses
- Weighted max-of-z aggregation in `weighted_max_z` with explicit feature weights (`FEATURE_WEIGHTS`) that emphasize export volume and sensitive-patient fraction; commented rationale
- Cold-start branch in `run_baseline_detector` falls back to peer-only baseline when `baseline_age_days < MIN_BASELINE_DAYS`, with `baseline_source` tag preserved through the score record
- Case grouping over a 7-day window prevents the same user-patient pair from generating fragmented investigations (subject to Finding 1)
- Suppression-rule TTL via DynamoDB `ttl` attribute auto-expires dismissal-based suppression after the validity window
- Bedrock prompt constraints (no clinical-or-employment-action recommendations, no intent assertions, required end-phrase, `temperature=0.0`) are appropriate for a privacy-office investigator audience
- Bedrock-failure fallback to a structured-only summary keeps case-builder operating when Bedrock throttles or returns errors
- Outcome capture includes a defined enumeration of valid outcomes (`VALID_OUTCOMES`) with explicit downstream workflow handoffs for `confirmed_violation` (breach review, HR referral, prior-violation flag)
- Heads-up + Gap to Production sections together name every major production gap (EHR audit-feed integration, FHIR R4 AuditEvent ingestion, IdP / HRIS / scheduling integrations, real Neptune cluster, real SageMaker endpoint, Clarify SHAP, Feature Store with point-in-time correctness, Model Monitor, sequence-model variant, SIEM integration, privacy-office UI, HR coordination, breach-notification clock tracking, workforce-equity audits, privileged-user separate program, service-account inventory, capacity-bounded prioritization, equity dashboards, shadow-mode deployment, KMS scoping, IAM scoping per component, VPC deployment, idempotency, retention-and-legal-hold)

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The eight pseudocode steps map onto Python functions, the same-name and same-address rules are surface-level simple but high-yield (which the recipe argues is exactly the right teaching emphasis), the cluster-cohesion check captures the credential-compromise pattern the rules engine misses, the cold-start fallback to peer-only baseline implements the recipe's framing, the calibration-then-tier-then-store sequencing matches the recipe's prose on calibration discipline, the case-grouping-then-suppression-then-LLM-narrative sequencing in `build_case` matches the recipe, and the outcome-capture path closes the feedback loop with the breach-notification and HR-referral handoffs the recipe describes. The Decimal discipline at the DynamoDB boundary is consistent with Recipe 3.7 and 3.8's clean posture.

The three WARNINGs are operational-correctness gaps. Finding 1 (`find_existing_case` with `Limit + scan + FilterExpression`) is the highest-impact silent-loss bug because it produces fragmented cases for the same workforce-patient pair, which directly inflates the privacy-office case queue and breaks the case-grouping intent the recipe explicitly relies on. Finding 2 (`is_off_hours` role-key mismatch) is a subtle coverage bug that renders the per-role business-hours dictionary entries unreachable; the bug reduces sensitivity for non-clinical roles and contradicts the dictionary's own intent. Finding 3 (`never_seen_before_fraction` always 0) is a dead-feature bug that wires a heavily-weighted feature into the model that contributes nothing.

The eleven NOTEs are editorial or hygiene items. Findings 4 (unused imports), 5 (logger no handler), 7 (S3 SSE without `SSEKMSKeyId`), 8 (EventBridge response not checked), and 9 (older Bedrock model) repeat patterns flagged in earlier Chapter 2 and 3 reviews; the cookbook would benefit from a coordinated chapter-wide fix on the SSE-KMS pattern plus a STYLE-GUIDE.md addition. Finding 10 (`model` parameter passed but never used) is the highest-information item for a reader trying to understand what the demo actually scores; the others are smaller polish.

PASS verdict. The fixes are localized; a re-review pass would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `find_existing_case` either uses a GSI-backed `query` keyed on `(workforce_id, patient_id)` with `opened_at` as the sort key, or drops the `Limit=10` so the FilterExpression sees all open cases. `Attr` (not `Key`) used in `FilterExpression`.
2. **(WARNING)** `is_off_hours` role-key construction either drops the `_day` suffix at the call site (so the dictionary's per-role entries are reachable) or restructures the dictionary to use tuple keys `(role, shift_pattern)` so the lookup is explicit. Dead dictionary entries removed if not made reachable.
3. **(WARNING)** `aggregate_user_activity.never_seen_before_fraction` either accepts the prior `known_patients` as an explicit parameter (computed before `append_to_user_state` runs), or `append_to_user_state` is moved to after `run_baseline_detector` runs. The feature must produce a non-zero value when the user accesses a previously-unseen patient.
4. **(NOTE)** Unused imports (`io`, `joblib`, `pandas`, `defaultdict`, `Counter`, `Optional`) removed.
5. **(NOTE)** `logging.basicConfig(...)` added near the top of Configuration with a one-liner explaining when it's a no-op.
6. **(NOTE)** `find_existing_case`'s filter uses `Attr` rather than `Key`. `Attr` imported alongside `Key` at the top of the file.
7. **(NOTE)** S3 `put_object` calls in `on_ehr_audit_event` and `on_investigator_action` pass `SSEKMSKeyId` with documented customer-managed-key constants.
8. **(NOTE)** All `eventbridge.put_events` call sites inspect the response for `FailedEntryCount > 0`, ideally via a shared helper.
9. **(NOTE)** `BEDROCK_MODEL_ID` updated to a more recent Claude version (3.5 Sonnet v2 or newer) and either pinned with a verification comment or loaded from environment.
10. **(NOTE)** Either the trained `model` is wired into `composite_score` via `model.predict_proba` over a constructed feature vector, or the `model` parameter is removed from `run_access_anomaly_pipeline` and the simplification documented in a comment.
11. **(NOTE)** `find_existing_case` uses a GSI-backed query rather than a full-table scan; GSI documented in the Setup section's table-schema notes (subsumed by the Finding 1 fix).
12. **(NOTE)** `score_via_sagemaker_endpoint` either has a real call site (gated by an environment flag) or carries a clear "reference implementation; not invoked in the demo" comment block.
13. **(NOTE)** `check_care_relationship` either implements minimal time-bounded edge filtering against a `valid_from`/`valid_to` attribute pattern, or removes the `as_of` parameter and documents the production-shape filter in the docstring.
14. **(NOTE)** Score record's `feature_snapshot` either persisted via S3 with a returned `feature_snapshot_id` (consistent with pseudocode), or the divergence is called out with a comment explaining the size-vs-reproducibility trade-off.
