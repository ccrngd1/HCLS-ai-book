# Code Review: Recipe 4.5 - Medication Adherence Intervention Targeting

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-16
**Files reviewed:**
- `chapter04.05-medication-adherence-intervention-targeting.md` (main recipe pseudocode)
- `chapter04.05-python-example.md` (Python companion)

**Validation performed:**
- Walked the eight pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for Athena (`start_query_execution`, `get_query_execution`), SageMaker (`create_transform_job`, `describe_transform_job`), SageMaker Feature Store Runtime (`put_record`), DynamoDB resource (`get_item`, `put_item`, `update_item`, `batch_writer`), Bedrock Runtime (Anthropic Messages API), Kinesis (`put_record`), S3 paths, and CloudWatch (`put_metric_data`)
- Traced numeric values flowing into DynamoDB through `_to_decimal` / `_to_decimal_dict` / `_from_decimal`
- Inspected S3 URIs for leading slashes and `s3://` scheme handling
- Walked the demo runner end-to-end against the seeded synthetic patients to verify barrier classification, candidate eligibility filtering, scoring, priority computation, allocation, and the simulated barrier_elicited / pharmacy_fill_observed events
- Checked healthcare-specific requirements: PHI logging discipline, eligibility filters as hard constraints, customer-managed KMS posture, synthetic data labeling, contact-cap enforcement, tracking-ID PHI leakage, cohort-features sensitivity, validator on LLM-tailored outreach, identity-boundary check on engagement events

---

## Summary

The Python companion is a strong teaching example for an adherence-intervention recommender. The eight pseudocode steps map cleanly to Python functions, the Bedrock + DynamoDB + Kinesis + Athena + SageMaker API call shapes are current, the heterogeneous-capacity allocator with multi-intervention-per-patient and equity floors is implemented in two passes (primary plus top-up) that match the pseudocode, the per-intervention-type orchestration branches are enumerated for all six intervention types, the engagement-attribution path enforces the (event.patient_id, rec.patient_id) identity boundary that the chapter has established, the Decimal-at-the-DynamoDB-boundary discipline is consistent throughout via `_to_decimal` and `_to_decimal_dict`, and the tracking-ID PHI leakage is acknowledged in code comments and in the Gap to Production section.

One issue is a real correctness bug that needs fixing before this goes to readers: the contact-cap reconciliation path on `intervention_outreach_failed` events constructs a `ConditionExpression` that references the placeholder `:zero` without defining it in `ExpressionAttributeValues`. DynamoDB rejects this with a `ValidationException` at runtime; the broad `except Exception` wrapper swallows the error, the counter never decrements, and members with flaky channels accumulate phantom contact-cap consumption indefinitely. This is the exact failure mode the surrounding code comment promises to fix, and the same gap was flagged as a TODO in the Recipe 4.4 main recipe and reproduced here without the boto3 syntax check. A handful of smaller polish items round out the review.

---

## Verdict: FAIL

One ERROR, seven NOTEs, no WARNINGs. Per persona rules, an ERROR finding automatically means FAIL.

The fix is small (one line) and the rest of the file is solid; a re-review pass would be quick.

---

## Findings

### Finding 1: ConditionExpression References Undefined Placeholder `:zero`; Contact-Cap Reconciliation Silently Never Works

- **Severity:** ERROR
- **File:** `chapter04.05-python-example.md`
- **Location:** `process_adherence_event`, the `intervention_outreach_failed` / `intervention_outreach_bounced` branch (Step 8)
- **Description:**

  ```python
  if event_type in ("intervention_outreach_failed",
                    "intervention_outreach_bounced"):
      try:
          profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
          profile_table.update_item(
              Key={"patient_id": patient_id},
              UpdateExpression="ADD outreach_recent_30d_count :neg",
              ExpressionAttributeValues={":neg": Decimal("-1")},
              # Only decrement if the counter is positive; never go
              # below zero (would suggest a bug elsewhere).
              ConditionExpression="outreach_recent_30d_count > :zero",
              ExpressionAttributeNames={},
          )
      except Exception as exc:
          logger.warning(
              "Contact-cap reconciliation failed for %s: %s", patient_id, exc,
          )
  ```

  The `ConditionExpression` references `:zero`, but `:zero` is never declared in `ExpressionAttributeValues`. Only `:neg` is declared. DynamoDB validates expression placeholders at request time and rejects this with:

  ```
  ValidationException: An expression attribute value used in expression is not
  defined; attribute value: :zero
  ```

  Two consequences, both bad:

  1. **The reconciliation never works.** Every `intervention_outreach_failed` and `intervention_outreach_bounced` event that reaches Step 8 fires the broken UpdateItem, the validation exception is swallowed by the broad `except Exception`, the warning gets logged, and the counter is never decremented. Members with flaky channels accumulate phantom 30-day contact-cap consumption every time their reminder bounces, and the recommender systematically excludes them from future allocations they should still be eligible for.
  2. **The bug is invisible until you audit it.** The reconciliation appears to be wired up (the surrounding comment says "Without this reconciliation, members with flaky channels accumulate phantom contact-cap consumption..."), the code looks structurally correct, the warning log shows up only at the WARN level. A reader copying this code into production will believe the reconciliation works and only discover otherwise when the equity dashboard surfaces a disparity in cap-deferral rates by channel reliability.

  This is the same failure mode flagged as a TODO in the Recipe 4.4 main recipe ("Without these, members with flaky channels accumulate phantom contact-cap consumption and get systematically excluded from future allocations they should still be eligible for"). Recipe 4.5 added the reconciliation code to fix the gap but introduced the boto3 syntax error in doing so.

  Side note: `ExpressionAttributeNames={}` is empty and unnecessary (the attribute name `outreach_recent_30d_count` is not a DynamoDB reserved word, so no name placeholder is needed). Empty dict is allowed by the API but doesn't accomplish anything.

- **Suggested fix:** Declare the missing placeholder and drop the unused `ExpressionAttributeNames`:

  ```python
  profile_table.update_item(
      Key={"patient_id": patient_id},
      UpdateExpression="ADD outreach_recent_30d_count :neg",
      # Guard against under-zero: only decrement if the counter is positive.
      # A counter at zero suggests an upstream bug or a duplicate failure
      # event; either way, don't compound it by going negative.
      ConditionExpression="outreach_recent_30d_count > :zero",
      ExpressionAttributeValues={
          ":neg":  Decimal("-1"),
          ":zero": Decimal("0"),
      },
  )
  ```

  Note that `ConditionalCheckFailedException` (raised when the condition evaluates to False, i.e., the counter is already zero) is a legitimate outcome that the broad `except Exception` will continue to swallow appropriately. After the fix, the warning log will only fire on real reconciliation failures (counter at zero), which is what the comment promises.

  Optional: narrow the `except` to `botocore.exceptions.ClientError` so a programming error in this branch propagates up rather than being silently absorbed.

---

### Finding 2: `policy_weights` Parameter Declared on `allocate_heterogeneous` but Never Used

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `allocate_heterogeneous` signature
- **Description:**

  ```python
  def allocate_heterogeneous(
      prioritized: list,
      intervention_catalog: list,
      member_profiles: dict,
      policy_weights: dict = POLICY_WEIGHTS,
      equity_floors: dict = EQUITY_FLOORS,
      run_horizon_days: int = 7,
      run_date: str = None,
  ) -> list:
  ```

  `policy_weights` appears in the signature with `POLICY_WEIGHTS` as the default, but the function body never references it. The priority-combination math has already been done in Step 5 (`compute_priority`), so by the time the candidates reach `allocate_heterogeneous` they already carry their `priority` and `priority_components` fields. The allocator only consults `priority` directly.

  Dead-code level. A reader looking at this signature might assume the allocator re-applies the weights for some reason (a tie-breaker, a per-cohort weight override, etc.) and try to extend it via that path before realizing the parameter is just unused.

- **Suggested fix:** Remove `policy_weights` from the signature. The `equity_floors` parameter is genuinely used and should stay. If a future variation of the allocator needs to tweak weights mid-run, that's a separate change with its own justification.

---

### Finding 3: Inline `import re as _re` in Four Bedrock Helpers

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `_bedrock_barrier_second_opinion`, `_bedrock_tailor_reminder`, `_bedrock_pharmacist_brief`, `_bedrock_pcp_briefing`
- **Description:** Each of the four Bedrock helpers ends with the same defensive JSON extraction pattern:

  ```python
      payload = json.loads(response["body"].read())
      completion = payload["content"][0]["text"]
      import re as _re
      match = _re.search(r"\{.*\}", completion, _re.DOTALL)
      if not match:
          raise ValueError("LLM returned no JSON object")
      return json.loads(match.group(0))
  ```

  The `import re as _re` is inline at point of use, with the alias presumably to avoid clobbering a `re` name elsewhere. Standard Python style is to import at the top of the file; inline imports are usually a sign of either lazy-loading optimization (not needed here; `re` is part of the standard library and is already loaded) or a workaround for circular imports (not the case here). A learner copying this pattern will start sprinkling inline imports throughout their codebase without a clear reason.

  Same finding pattern was flagged in the Recipe 4.4 review (one occurrence). This recipe has four occurrences, suggesting a copy-paste rather than a deliberate stylistic choice.

- **Suggested fix:** Move the import to the top of the file with the other imports (`import re`), drop the alias, and use `re.search(...)` and `re.DOTALL` at the four call sites. Consider extracting the JSON-extraction-and-parse pattern into a small helper so the four sites collapse to a single call:

  ```python
  def _extract_json_from_completion(completion: str) -> dict:
      """Pull the first JSON object out of an LLM completion."""
      match = re.search(r"\{.*\}", completion, re.DOTALL)
      if not match:
          raise ValueError("LLM returned no JSON object")
      return json.loads(match.group(0))
  ```

---

### Finding 4: `event_id` Construction and Stored `timestamp` Use Different `_now_iso()` Values When Timestamp Is Missing

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `process_adherence_event`, the `event_id` and `events_table.put_item` block (Step 8)
- **Description:**

  ```python
  event_id = (
      f"{tracking_id}:{event_type}:{event.get('timestamp', _now_iso())}"
      if tracking_id else
      f"organic:{patient_id}:{event_type}:{event.get('timestamp', _now_iso())}"
  )
  try:
      events_table.put_item(Item=_to_decimal_dict({
          "event_id":            event_id,
          ...
          "timestamp":           event.get("timestamp", _now_iso()),
          ...
      }))
  ```

  When the inbound event has a `timestamp` field, both sites read the same value and the row's `event_id` and stored `timestamp` agree. When the inbound event does not, each `event.get("timestamp", _now_iso())` call evaluates `_now_iso()` independently and gets a slightly different value (microsecond-level difference). The result: the `event_id` ends with one timestamp and the stored `timestamp` field is a different timestamp.

  Two consequences, mild but real:

  1. **Idempotency degrades for events without timestamps.** Two events arriving microseconds apart with the same `(tracking_id, event_type)` and no timestamp produce different `event_ids` (different `_now_iso()` evaluations) and don't dedupe. The intent of including the timestamp in the `event_id` was probably exactly this dedup check; the missing-timestamp path defeats it.
  2. **Auditors can't reconstruct the `event_id` from the stored row** because the stored `timestamp` was a separately-evaluated `_now_iso()`, not the one embedded in the `event_id`.

  Same finding pattern was flagged in the Recipe 4.3 and 4.4 reviews. In the demo runner, every simulated event explicitly sets `"timestamp": _now_iso()`, so the demo never exercises the divergent path. Production traffic with bare events will.

- **Suggested fix:** Compute the timestamp once and reuse it everywhere:

  ```python
  event_ts = event.get("timestamp") or _now_iso()
  event_id = (
      f"{tracking_id}:{event_type}:{event_ts}"
      if tracking_id else
      f"organic:{patient_id}:{event_type}:{event_ts}"
  )
  events_table.put_item(Item=_to_decimal_dict({
      "event_id":  event_id,
      ...
      "timestamp": event_ts,
      ...
  }))
  ```

  The same pattern applies to `_record_pcp_override`'s `event.get("timestamp", _now_iso())` call, which has the same divergence on missing timestamps.

---

### Finding 5: `_compute_regimen_features` Does One DynamoDB GetItem per Patient

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `_compute_regimen_features`, the per-patient profile lookup loop (Step 1 helper)
- **Description:**

  ```python
  profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
  records = []
  for patient_id, entry in by_patient.items():
      try:
          response = profile_table.get_item(Key={"patient_id": patient_id})
          profile = _from_decimal(response.get("Item") or {})
      except Exception:
          profile = {}
      records.append({...})
  ```

  At the recipe's stated scale of 80,000 chronic-medication patients running nightly, this is 80,000 serial DynamoDB reads where a `BatchGetItem`-with-chunking pattern would do the same work in roughly 800 round trips. The serial GetItem-per-patient pattern teaches a habit that scales poorly and was the same finding pattern flagged in the Recipe 4.4 review (where the cohort-feature lookup ran one GetItem per (member, program) pair).

  The function comment doesn't acknowledge the throughput cost, so a reader copying this pattern won't realize the problem until they're paying for DynamoDB read capacity.

- **Suggested fix:** Use `BatchGetItem` with the 100-key chunking pattern:

  ```python
  unique_pids = list(by_patient.keys())
  profiles_by_id = {}
  for i in range(0, len(unique_pids), 100):
      chunk = unique_pids[i:i + 100]
      request = {PATIENT_PROFILE_TABLE: {"Keys": [{"patient_id": p} for p in chunk]}}
      attempts = 0
      while request and attempts < 5:
          response = dynamodb.batch_get_item(RequestItems=request)
          for item in response.get("Responses", {}).get(PATIENT_PROFILE_TABLE, []):
              profiles_by_id[item["patient_id"]] = _from_decimal(item)
          request = response.get("UnprocessedKeys") or {}
          if request:
              time.sleep(0.05 * (2 ** attempts))
              attempts += 1
  ```

  Then read `profiles_by_id.get(patient_id, {})` inside the records loop. Optional but worth showing as the pattern; the existing comments can stay.

---

### Finding 6: `compute_priority` Normalization Yields Zero for Single-Row Intervention Types

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `compute_priority`, the per-type normalization block (Step 5)
- **Description:**

  ```python
  for intervention_type, type_rows in by_type.items():
      for component in ("engagement_prob", "uplift_estimate"):
          values = [r[component] for r in type_rows]
          lo, hi = min(values), max(values)
          spread = hi - lo if hi > lo else 1.0
          for r in type_rows:
              r[f"{component}_norm"] = (r[component] - lo) / spread
  ```

  When an intervention_type has only a single candidate in the run (e.g., the demo's `education-001` is eligible only for pat-000482's statins, not pat-000915's RAS antagonists), `lo == hi`, the spread guard produces `1.0`, and the formula reduces to `(r[component] - lo) / 1.0 = 0`. So a single-row intervention type always gets `engagement_prob_norm = 0`, `uplift_estimate_norm = 0`, and `cost_efficiency_norm = 0`, regardless of how good the absolute scores were.

  In the demo, `education-001` and `med-sync-001` each appear as single-row types, so both get systematically deflated against the multi-row intervention types (text_reminder, pharmacist_consult, cost_assistance, regimen_simplification, all with two candidates). The reader who walks the demo will see those interventions persistently underranked without an obvious reason; the `priority_components` row will show `engagement_contrib = 0.0` and `uplift_contrib = 0.0`, which looks like a feature failure when it's a normalization artifact.

  At a 400K-member, 80K-target weekly run, this is less of an issue (most intervention types will have many candidates, the single-candidate pathology is rare). But the demo specifically exercises the pathological case and the reader can see the deflation.

- **Suggested fix:** When `lo == hi`, fall back to a neutral value (0.5) rather than 0, so a single-row intervention type doesn't get punished for having no peers to compare against:

  ```python
  for r in type_rows:
      if hi > lo:
          r[f"{component}_norm"] = (r[component] - lo) / (hi - lo)
      else:
          r[f"{component}_norm"] = 0.5  # neutral when there's nothing to compare
  ```

  Alternatively, normalize across the whole candidate pool rather than within intervention type, accepting that engagement and uplift have type-dependent scales. The current pseudocode has the same comparison choice (within-type normalization), so this is a NOTE about behavior under sparse types, not a bug per se. A short comment explaining the design choice and its limitation would also be enough.

---

### Finding 7: `_compute_target_window` Uses `datetime.date.today()` (Local Time) While the Rest of the File Uses UTC

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `_compute_target_window` (Step 7 pharmacist consult dispatch helper)
- **Description:**

  ```python
  def _compute_target_window() -> dict:
      """
      The window in which the pharmacist should attempt the consult.
      Tighter window for time-sensitive interventions; this example
      uses a 7-day default.
      """
      today = datetime.date.today()
      return {
          "start": today.isoformat(),
          "end":   (today + datetime.timedelta(days=7)).isoformat(),
      }
  ```

  `datetime.date.today()` returns the local-system date, not UTC. Every other timestamp in the file uses `_now_iso()` (which is `datetime.datetime.now(timezone.utc).isoformat()`) or `_today_str()` (which is `datetime.datetime.now(timezone.utc).date().isoformat()`). A pharmacist consult queued near midnight UTC from a Lambda running in the us-east-1 region will get a target window dated for the previous local day; for an us-west-2 deployment, the window will be off by 8 hours from the rest of the recommendation log's `run_date` and `created_at` fields.

  Same trap pattern as previous chapters: timezone consistency matters because audit queries that join on dates need consistent semantics across all timestamps in the system.

- **Suggested fix:** Use the existing UTC helper:

  ```python
  def _compute_target_window() -> dict:
      today = datetime.datetime.now(timezone.utc).date()
      return {
          "start": today.isoformat(),
          "end":   (today + datetime.timedelta(days=7)).isoformat(),
      }
  ```

  Or just call `_today_str()` and parse it back to a date. Either is fine.

---

### Finding 8: Cohort-Feature `None` Surfaces as the String `"None"` in CloudWatch Dimensions

- **Severity:** NOTE
- **File:** `chapter04.05-python-example.md`
- **Location:** `process_adherence_event`, the cohort-sliced metric emission (Step 8); `_lookup_cohort_features_from_profile` (Step 6)
- **Description:** `_lookup_cohort_features_from_profile` returns explicit `None` for unset axes:

  ```python
  return {
      "engagement_history_quartile": member.get("engagement_history_quartile", "q3"),
      "language":                    member.get("preferred_language", "en"),
      "sdoh_cohort":                 member.get("sdoh_cohort"),
      "age_band":                    member.get("age_band"),
  }
  ```

  Then the metric emission downstream stringifies them:

  ```python
  _emit_metric(
      "adherence_engagement",
      value=1,
      dimensions={
          ...
          "engagement_history_q":   str(cohort.get("engagement_history_quartile", "unknown")),
          "language":               str(cohort.get("language", "unknown")),
          "sdoh_cohort":            str(cohort.get("sdoh_cohort", "unknown")),
      },
  )
  ```

  `dict.get(key, default)` returns `default` only when the key is *absent*. When the key is *present* with value `None`, it returns `None`. Then `str(None)` is the literal string `"None"`. So a member whose `sdoh_cohort` field is null in DynamoDB ends up tagged as `sdoh_cohort=None` in CloudWatch, distinct from the `sdoh_cohort=unknown` bucket. The equity dashboard then has three buckets (`unknown`, `None`, and the actual cohort labels) that are semantically the same for "we don't know."

  Same pattern flagged in the Recipe 4.4 review. The seed data in this recipe doesn't trigger the path (both demo patients have `sdoh_cohort` populated), but production traffic will.

- **Suggested fix:** Normalize at the cohort-lookup boundary so the metric layer doesn't have to:

  ```python
  return {
      "engagement_history_quartile": member.get("engagement_history_quartile") or "unknown",
      "language":                    member.get("preferred_language") or "en",
      "sdoh_cohort":                 member.get("sdoh_cohort") or "unknown",
      "age_band":                    member.get("age_band") or "unknown",
  }
  ```

  Apply the same pattern to `language` and `age_band` for consistency.

---

## Pseudocode-to-Python Consistency

All eight pseudocode steps map cleanly to Python functions:

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `compute_adherence_features(patients, run_date)` | `compute_adherence_features(run_date)` | Yes (helpers `_compute_pdc_for_class`, `_is_sporadic_pattern`, `_is_consistent_then_stopped`, `_assess_data_quality`, `_compute_regimen_features` are explicit support utilities; `_load_settled_fills` is a stub the demo monkey-patches) |
| `classify_barriers(target_set, features, run_date)` | `classify_barriers_for_target_set(target_set, adherence_features, regimen_features, member_profiles, run_date)` | Yes (extra dict parameters thread state explicitly rather than re-deriving; rule + supervised + LLM stages match the pseudocode's Stage A/B/C; `_blend_rule_and_supervised`, `_should_invoke_llm`, `_proxy_need_score`, `_flag_for_pharmacist_review` are explicit support utilities) |
| `build_candidate_triples(target_set, intervention_catalog, run_date)` | `build_candidate_triples(target_set, intervention_catalog, barriers_by_class, member_profiles, medication_metadata, run_date)` | Yes (extra dict parameters thread eligibility-relevant state; the eligibility filter chain matches the pseudocode's hard filters) |
| `score_candidates(candidates, run_date)` | `score_candidates(candidates, run_date)` | Yes (the synthetic `_score_candidates_via_batch_transform` returns deterministic plausible scores; the production-shape comments are explicit; barrier-fit is correctly framed as a deterministic dot product, not a model call) |
| `compute_priority(scored_candidates, policy)` | `compute_priority(scored_candidates, policy_weights, policy_version)` | Yes (the policy is decomposed into named arguments rather than a single policy object; Finding 6 flags the single-row normalization edge case) |
| `allocate_heterogeneous(prioritized, interventions, policy, run_date)` | `allocate_heterogeneous(prioritized, intervention_catalog, member_profiles, policy_weights, equity_floors, run_horizon_days, run_date)` | Yes (greedy primary pass + equity-floor top-up pass + DynamoDB persistence + metric emission; Finding 2 flags the unused `policy_weights` parameter) |
| `orchestrate_interventions(allocated, run_date, policy)` | `orchestrate_interventions(allocated, member_profiles, medication_metadata, run_date)` | Yes (six per-intervention-type dispatch helpers; the `BRANCH on intervention.type` shape from the pseudocode is implemented as an explicit if/elif/else; LLM tailoring + validators + channel-optimizer or staff-queue routing all match) |
| `process_adherence_event(event)` | `process_adherence_event(event)` | Yes (identity-boundary check, raw event persist, short/medium-horizon training-data routing, PCP-override flagging, cohort-sliced metric emit; Finding 1 flags the broken contact-cap reconciliation; Finding 4 flags the event_id/timestamp default mismatch) |

Intentional deviations, all clearly framed:

- The pseudocode's `Athena.Query(...)` for fill ingestion in Step 1 becomes `_load_settled_fills(...)` returning an empty dict, with the comment naming the production Glue-job replacement and noting the demo monkey-patches the loader. The demo bypasses Step 1 entirely and supplies pre-computed `adherence_features` to `run_weekly_batch`.
- The pseudocode's `SageMaker.FeatureStore.PutRecord(...)` becomes a try/except wrapper around `sagemaker_featurestore.put_record(...)` so the demo can run offline (the feature group doesn't exist). The exception path logs at DEBUG level and continues.
- The pseudocode's per-intervention SageMaker Batch Transform fan-out in Step 4 becomes the synthetic `_score_candidates_via_batch_transform` that produces deterministic heuristic scores. The comment is explicit: "Production: write candidates to S3, kick off three Batch Transform jobs (need / engagement / uplift) for this intervention, wait, join the scores back to the candidates."
- The pseudocode's `Bedrock.InvokeModel(...)` calls in Steps 2 (barrier second opinion), 7 (reminder tailoring, pharmacist brief, PCP briefing) are wrapped in helpers and monkey-patched by the demo runner via `globals()` so the demo runs offline. Production never bypasses these.
- The pseudocode's `flag_for_pharmacist_review(...)` becomes a `logger.info` call; the comment names the production destination (`pharmacist-review-queue` table).

---

## AWS SDK Accuracy

| API Call | Method | Parameters | Response Parsing | Correct? |
|----------|--------|------------|------------------|----------|
| Athena StartQueryExecution | `athena_client.start_query_execution()` | `QueryString`, `QueryExecutionContext`, `WorkGroup`, `ResultConfiguration` | `execution["QueryExecutionId"]` | Yes |
| Athena GetQueryExecution | `athena_client.get_query_execution(QueryExecutionId)` | N/A | `response["QueryExecution"]["Status"]["State"]` and `StateChangeReason` | Yes |
| SageMaker CreateTransformJob | `sagemaker_client.create_transform_job(...)` | Not actually called in this example (the synthetic scorer replaces it); the placeholder is documented | N/A | Documented but not invoked |
| SageMaker DescribeTransformJob | `sagemaker_client.describe_transform_job(TransformJobName)` | N/A | `response["TransformJobStatus"]` and `FailureReason` | Yes (helper `_wait_for_transform_job` is correct, even if not exercised in the demo) |
| SageMaker Feature Store PutRecord | `sagemaker_featurestore.put_record(FeatureGroupName, Record)` | `Record` is a list of `{"FeatureName", "ValueAsString"}` dicts; ISO-8601 UTC timestamp on `event_time` | N/A | Yes |
| Bedrock InvokeModel (Claude Haiku) | `bedrock_runtime.invoke_model()` | `modelId="anthropic.claude-3-5-haiku-20241022-v1:0"`, body with `anthropic_version="bedrock-2023-05-31"`, `max_tokens`, `temperature`, `messages` array | `payload["content"][0]["text"]` matches Anthropic Messages response shape on Bedrock | Yes (with the caveat in Setup that some regions require cross-region inference profile prefixes like `us.anthropic...`) |
| DynamoDB GetItem | `table.get_item(Key={...})` | Single PK on each table | `response.get("Item")` handled with None-checks; `_from_decimal(... or {})` for the fallback | Yes |
| DynamoDB PutItem | `table.put_item(Item=...)` | All numeric values via `_to_decimal` (which uses `Decimal(str(...))`) at the persistence boundary; nested maps via `_to_decimal_dict` | N/A | Yes |
| DynamoDB UpdateItem (positive `ADD`) | `profile_table.update_item(Key, UpdateExpression="ADD outreach_recent_30d_count :one ...", ExpressionAttributeValues={":one": Decimal("1"), ":now": _now_iso()})` | All placeholders are declared | N/A | Yes |
| DynamoDB UpdateItem (negative `ADD` with condition) | See Finding 1 | `:zero` is referenced but not declared | N/A | **No** (Finding 1) |
| DynamoDB BatchWriter | `with rec_table.batch_writer() as batch` then `batch.put_item(...)` | Each item passed through `_to_decimal_dict` for numerics | N/A | Yes (the resource-client batch_writer auto-retries on UnprocessedItems internally) |
| Kinesis PutRecord | `kinesis_client.put_record(StreamName, PartitionKey, Data)` | `PartitionKey=patient_id` keeps a single patient's events ordered within a shard; `Data` JSON-encoded with `default=str` then UTF-8 bytes | N/A | Yes |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData)` | `MetricName`, `Dimensions` (low-cardinality: event_type, intervention_type, therapeutic_class, language, engagement_history_q, sdoh_cohort), `Value`, `Unit` | N/A | Yes (Finding 8 flags the None-string dimension issue) |

Method names, parameter names, and response-path traversals match current SDK shapes (with the one ConditionExpression bug flagged in Finding 1). The Bedrock model ID `anthropic.claude-3-5-haiku-20241022-v1:0` is current; the request body's `anthropic_version`, `max_tokens`, `temperature`, and `messages` array conform to the Anthropic Messages API on Bedrock. The Feature Store `put_record` Record shape with `{"FeatureName", "ValueAsString"}` entries is correct, including the `event_time` ISO-8601 UTC timestamp.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits when the input is already a Decimal. The `str` route avoids the binary-precision artifacts that `Decimal(float_value)` introduces.
- `_to_decimal_dict` recursively converts nested dicts and lists, with explicit `not isinstance(v, bool)` guards so booleans don't flow into Decimal (Decimal would refuse the `True`/`False` strings). Lists are walked element-by-element with the same guards.
- `_from_decimal` recursively converts Decimals back to floats and traverses dict and list containers.
- All `update_item` `ADD` operations target top-level attributes (`outreach_recent_30d_count`); none target nested map paths, so the cold-start nested-map bug from Recipe 4.2's review does not apply. The contact-cap counter has the syntax error flagged in Finding 1; the optimistic increment on the orchestration side is correct.
- DynamoDB BatchWriter via `with rec_table.batch_writer() as batch` correctly handles the unprocessed-items loop internally.
- The `priority_components` map is persisted as a flat DynamoDB map of Decimal values; reading it back through `_from_decimal(rec.get("priority_components", {}))` round-trips cleanly.
- The demo's seed `outreach_recent_30d_count` uses `Decimal("0")` and `Decimal("1")`; the allocator's `int(member.get("outreach_recent_30d_count", 0))` cast is correct (`int(Decimal("0"))` is `0`).
- The `event_payload` maps for the simulated `pharmacy_fill_observed` event include a Python float (`copay_paid: 5.0`); `_to_decimal_dict` converts it to `Decimal("5.0")` via str. Good.
- No floats are persisted to any DynamoDB table.

Pass on the type discipline. Finding 1 is the boto3 syntax issue; finding 5 is the throughput pattern.

---

## S3 and Credentials Check

- All S3 URI construction goes through f-strings with explicit prefixes (`f"s3://{ATHENA_RESULTS_BUCKET}/fills/{run_date}/"`, `f"s3://{FEATURE_STORE_OFFLINE_BUCKET}/run_date={run_date}/adherence-features.parquet"`). No leading slashes inside the key portion. No `s3://` scheme leakage when keys would be passed to S3 client calls (the example doesn't actually call S3 client APIs directly; the URIs are constructed for documentation and Athena result-location pointers).
- `_parse_s3_uri` raises a `ValueError` if the URI doesn't start with `s3://`, the right defensive shape.
- No hardcoded credentials. Module-level boto3 clients use the environment credential chain documented in Setup.
- The IAM permissions list in the Setup section matches the API surface used by the code (Athena query execution, SageMaker transform jobs + Feature Store PutRecord/GetRecord/BatchGetRecord, DynamoDB on six named tables, S3 on named buckets, Bedrock on three named model uses, Kinesis PutRecord, SES SendEmail with a BAA-covered identity, CloudWatch PutMetricData, CloudWatch Logs).

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why," which is what a learner needs:

- The Heads-up at the top names every major production gap before the code starts (no real PBM ingestion, no NCPDP X12 parsing, no validated PDC methodology against PQA specifications, no randomized-pilot infrastructure, no production propensity-score modeling, no LP-based heterogeneous allocator, no live PCP-EHR integration, no real outcome-evaluation methodology with pre-registration).
- The PHI-logging guidance at the module level: *"Never log a raw (patient_id, therapeutic_class, barrier) join along with clinical context; the row implicitly identifies both the medication and the suspected reason. The barrier-classifications table and the recommendation log are highly inferential PHI."* The right framing for an inference-rich domain.
- The barrier-classifier framing: *"The barrier classifier is the part most plans skip and the part that distinguishes a good adherence program from a reminder spam campaign."* Sets the right operational expectation up front.
- The settled-lag rationale: *"30-day settled lag: retail claims arrive on a 1-2 day lag, mail-order on a 5-14 day lag, and specialty up to 30. Computing PDC against claims that haven't all arrived yet produces noisy, biased numbers that systematically under-estimate adherence for mail-order users."* Saves a reader from a real production bug.
- The carry-forward PDC math: *"Each fill contributes a half-open interval `[fill_date, fill_date + days_supply)`. Overlapping fills (early refills, stockpiling) extend the covered set without double-counting. The set membership test for 'is day d covered' is what makes mail-order, retail, and synchronized refills all produce the same PDC for the same actual adherence."* Captures the entire PDC-correctness intuition.
- The barrier-fit dot product: *"Patient barriers `[cost: 0.72, beliefs: 0.21]` dotted with cost-assistance supports `{cost: 1.0, beliefs: 0.0, ...}` = 0.72. Same patient with text-reminder supports `{forgetfulness: 1.0, cost: 0.0, ...}` = 0.0."* Concrete arithmetic example beats abstract description.
- The cost-efficiency framing in the priority math: *"The cost_efficiency weight is what stops a $80 pharmacist consult from being chosen over a $0.05 reminder for every candidate where uplift is similar."* Names the failure mode the term prevents.
- The Bedrock de-identification stance: *"IMPORTANT: pass de-identified context to the LLM. Don't pass raw patient_id, name, phone, or NDC into the prompt; the LLM doesn't need them, and stripping them at this boundary limits any vendor-side logging exposure (Bedrock service terms commit to not using prompts to train foundation models, but defense-in-depth still applies)."* Defense-in-depth framing that's hard to argue with.
- The tracking-ID PHI-leakage warning: *"Production must replace this with an opaque, non-reversible identifier (UUID or HMAC over the composite). Plain-text patient_id and therapeutic_class embedded in tracking IDs (carried in email open-tracking pixels, SMS click-through links, vendor outreach platform handoffs) are PHI leakage."* Names the specific exposure surfaces that make this real.
- The contact-cap reconciliation comment: *"Without this reconciliation, members with flaky channels accumulate phantom contact-cap consumption and get systematically excluded from future allocations they should still be eligible for."* Promises the right thing; Finding 1 is that the implementation doesn't deliver on the promise.
- The synthetic-data labeling: *"All sample patients, medications, fills, interventions, and engagement signals are synthetic."*
- The Bedrock model-ID note in Setup: *"Bedrock model IDs change over time. Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`)."* Same caveat flagged in 4.1, 4.2, 4.3, 4.4; consistent across the chapter.
- The collapse-to-single-file note: *"The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability. In production these are separate workflow stages with their own error handling, IAM, and DLQs."*
- The PDC-on-no-history sentinel: *"Sentinel record for a (patient, class) with no fills."* The `_empty_pdc_record` returns `gap_days=999` and `data_quality_flag="no_history"` so downstream gating is unambiguous.
- The mock-injection comment in the demo: *"Patch the module-level functions for the offline demo. Production never bypasses these; the real Bedrock and SageMaker calls run."* Sets expectations clearly.

Calibration is appropriate for a mixed audience: a reader learning Python can follow the mechanics; a practicing engineer gets the operational notes and production gaps without being talked down to.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Module-level logger comment is explicit about the (patient_id, therapeutic_class, barrier) join hazard. Loggers in the file mostly stay on the safe side (patient_id appears in some warning paths but the clinical context isn't co-logged); cohort_features are scoped on the engagement row only and aren't joined to verbatim clinical text.
- **Synthetic data labeling.** All sample patient IDs (`pat-000482`, `pat-000915`), NDCs (`00071-0156-23`, `00378-3825-77`), pharmacy IDs (`PHARM-CHAIN-A`, `PHARM-LOCAL-XYZ`), and engagement events are obviously synthetic. The Heads-up section warns explicitly: *"All patients, fills, interventions, and engagement events in the example are synthetic."*
- **Eligibility filters as hard constraints.** Step 3's `build_candidate_triples` enforces brand-only / class-applicable / LIS-required / partner-pharmacy-required / language / cooldown / mutual-exclusion filters before downstream scoring sees the candidate. A pharmacist consult on a Spanish-only patient with no Spanish-speaking pharmacist support cannot reach the allocator, which matches the recipe's "eligibility is a correctness boundary, not a relevance feature" framing.
- **Decimal at the DynamoDB boundary.** All numeric persistence routes through `_to_decimal` / `_to_decimal_dict`, with explicit bool guards so booleans don't accidentally become `Decimal("True")`. The seed data uses `Decimal("0")` and `Decimal("1")` consistently. No accidental float persistence.
- **Tracking-ID privacy.** The `_make_tracking_id` helper carries an explicit NOTE comment naming the PHI-leakage problem with plaintext patient_id and therapeutic_class in tracking IDs, and the Gap to Production section repeats and elaborates on the fix. The example uses the readable form for clarity but the warning is unmistakable.
- **Bedrock de-identification.** Each Bedrock helper builds a structured de-identified context block before invocation; identifiers are not in the prompt. The pharmacist-brief prompt uses age band, not age. The reminder prompt uses adherence summary status, not exact PDC.
- **Identity boundary on engagement events.** `process_adherence_event` drops events where `event.patient_id != rec.patient_id`, matching the chapter-wide pattern.
- **Cohort-features sensitivity.** The recommendation log carries `cohort_features` (engagement quartile, language, SDOH cohort, age band) for fairness monitoring; the inline comment in the Gap to Production section names the reidentifiability risk for small SDOH cohorts in specific geographies.
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production. Not implemented in the example application code, which is correct: encryption-at-rest is a table-level setting configured at provision time, not something the application toggles per-call.
- **Outreach validator.** `_validate_reminder` and `_validate_pharmacist_brief` enforce structural shape and a small over-promising-language blocklist (`"guaranteed"`, `"cure"`, `"100%"`, `"definitely will"`, `"must take"`); the Gap to Production section is explicit that production extends with an approved-claims list per medication owned by clinical/compliance plus a sample-and-review workflow.
- **CloudWatch dimensions.** Dimensions are event_type, intervention_type, therapeutic_class, language, engagement_history_q, sdoh_cohort. All low-cardinality cohort labels. Patient-level identifiers are not used as dimensions. Finding 8 is the cosmetic `"None"`-string issue.
- **PCP override path.** `_record_pcp_override` writes to a dedicated `pcp-overrides` table and emits a per-(intervention_type, therapeutic_class) metric. The override reason is captured for medical-director review.

Pass on healthcare-specific handling, with Finding 1 (contact-cap reconciliation) being the one functional gap in the otherwise-solid PHI/audit posture.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants, Reference Data (synthetic intervention catalog with structured eligibility, supported-barriers, capacity, cost), Shared Helpers (`_now_iso`, `_today_str`, `_emit_metric`, `_to_decimal`, `_to_decimal_dict`, `_from_decimal`, `_make_tracking_id`, `_parse_s3_uri`, `_wait_for_athena_query`, `_wait_for_transform_job`), Step 1 (adherence features with `_compute_pdc_for_class` + supporting analytics + sentinel record + Feature Store persistence + regimen-feature aggregation), Step 2 (barrier classification with rule + supervised + LLM stages + blender + need proxy + LLM-gate + pharmacist-review flag), Step 3 (candidate triples with eligibility filters + cooldown + in-flight conflict), Step 4 (scoring with synthetic Batch Transform stand-in + barrier-fit dot product), Step 5 (priority with within-type normalization + cost-efficiency + per-(patient, class) ranking), Step 6 (allocator with greedy primary pass + equity-floor top-up + DynamoDB persistence + metric), Step 7 (orchestration with six per-type dispatch helpers + LLM tailoring + validators + contact-counter optimistic update + Kinesis emit), Step 8 (engagement attribution with identity check + raw event persist + per-event-type training-data routing + PCP override + cohort metric), Putting It All Together (`run_weekly_batch`), Demo Runner (with `__main__` block), Gap Between This and Production (extensive 30+ items).

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern.

The Heads-up at the top names every major production gap before the code starts; the Gap to Production section repeats and elaborates on each item with concrete actionable next steps. The demo runner at the bottom seeds two synthetic patients with deliberately different cohort and barrier profiles (English / no LIS / partner pharmacy / engagement-q3 / sporadic statin fill pattern versus Spanish / LIS-enrolled / non-partner pharmacy / engagement-q1 / consistent-then-stopped RAS pattern with high-copay alignment) so a reader can see the rule-based barrier classifier produce different top-1 barriers (beliefs vs cost) and see eligibility filtering exclude med-sync for the second patient.

The mock-via-`globals()` pattern in `__main__` is the same technique used in 4.4; the comment is honest about it being a demo construct that production never uses.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- The `_compute_pdc_for_class` carry-forward implementation is honest about the math: it builds the covered-days set, restricts to the trailing window, and computes PDC as a ratio. The set-construction approach makes overlapping fills (early refills, stockpiling) and same-day fills converge correctly without double-counting. A reader who copies this pattern will not silently produce the "90-day mail-order patient looks like a non-adherent retail patient" pathology.
- The `_assess_data_quality` flag is checked into the feature record at Step 1 and surfaces all the way through to the recommendation log, the engagement events, and the cohort dashboard. Downstream consumers can gate on `cash_pay_partial` or `multi_pharmacy_fragmented` rather than confidently labeling those patients non-adherent.
- The barrier classifier's three-stage design (rules + supervised + LLM second opinion) is implemented correctly: `_blend_rule_and_supervised` does a weighted sum with explicit per-barrier source attribution; `_should_invoke_llm` gates the LLM call on top-1 confidence and need score so the LLM cost stays bounded; `_flag_for_pharmacist_review` is the safety valve when the LLM materially disagrees on a high-need case. The pseudocode's intent is reproduced in code.
- The greedy-with-equity-floors allocator is two-passed (primary greedy by priority, then top-up over the cohort pool to fill any unmet floors). The floor accounting decrements `equity_remaining[intervention_id][floor_cohort]` only when a floor candidate is found and slots are available, and the `for floor_cohort in applicable: ... break` correctly assigns to one floor and stops. Cap and exclusion checks are explicit and ordered (per-intervention capacity, per-patient interventions cap, per-patient high-touch cap, contact-cap, cross-intervention exclusion, equity floor accounting).
- The `_make_tracking_id` helper produces a stable composite key that flows from the recommendation log through outreach to engagement events. The companion comment explicitly flags the PHI leakage in the readable form and points to the production fix.
- The orchestration step's six dispatch helpers (`_dispatch_text_reminder`, `_dispatch_education`, `_dispatch_pharmacist_consult`, `_dispatch_cost_assistance`, `_dispatch_med_sync`, `_dispatch_regimen_simplification`) are enumerated rather than collapsed into a single `if/elif` block. Each produces a structured dispatch record with intervention-type-specific fields (the pharmacist consult carries the brief, the cost-assistance record carries the LIS status and formulary tier, the med-sync record routes to partner API or pharmacist queue based on partnership status, the regimen-simplification record carries the PCP briefing). A reader extending this with a new intervention type follows the pattern naturally.
- The `_intervention_generates_contact` predicate centralizes the contact-cap-relevance question. The `regimen_simplification` intervention is explicitly marked as not generating patient contact (it's PCP-mediated), so it correctly skips both the optimistic increment and the failure decrement.
- The `process_adherence_event` raw-event persistence path uses an explicit `event_id` construction (with the timestamp issue from Finding 4) so duplicate events with the same `(tracking_id, event_type, timestamp)` would dedupe; the `_to_decimal_dict` wrapper protects against accidental float persistence on the `event_payload` column.
- The Gap to Production section is unusually thorough (30+ explicit gap items with actionable framing): PBM ingestion contracts, PDC methodology validation against PQA specifications, barrier-classifier label generation, uplift training data, propensity-score modeling, Feature Store integration, Batch Transform output schema, eligibility SQL via Glue, Step Functions orchestration, DLQ coverage, Bedrock cost and latency, outreach-message governance, multilingual outreach quality, PCP-EHR integration, partner-pharmacy med-sync API, vendor reporting reconciliation, Star Ratings cycle awareness, cross-recipe contact-cap reconciliation, tracking-ID privacy, DynamoDB Decimal gotchas, cohort-feature PHI sensitivity, idempotency and retry semantics, outreach-failure reconciliation paths, specialty pharmacy adherence, newly prescribed medications, cost-assistance cascade, refill-gap real-time triggers, cohort fairness review process, outcome evaluation methodology rigor, VPC/encryption/audit, synthetic data and testing, cold-start handling for new interventions, member-stated preferences as hard filters, cross-recipe orchestration with 4.4 and 4.7, cost-per-PDC-point-gained tracking. The breadth tells a reader honestly how much work sits between this recipe and a 400K-member production deployment.
- The Decimal discipline at the DynamoDB boundary is consistent throughout via `_to_decimal` and `_to_decimal_dict`, applied at every persistence site. Reads route back through `_from_decimal` for downstream Python comparisons. No accidental float persistence anywhere except for the one bug flagged in Finding 1 (which is a syntax issue, not a Decimal issue).
- The synthetic intervention catalog (`SAMPLE_INTERVENTIONS`) carries fully-specified eligibility, supported-barrier weights, marginal cost, daily capacity, language support, cooldown days, and default templates. A reader extending this to add a new intervention type has the schema to follow without guessing.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe. The eight pseudocode steps map onto Python functions with helpers in the right places, the Bedrock + DynamoDB + Kinesis + Athena + SageMaker Feature Store API call shapes are current, the heterogeneous-capacity allocator with multi-intervention-per-patient and equity floors is implemented correctly, the per-intervention-type orchestration enumerates all six dispatch paths, the engagement-attribution path enforces the chapter's standard identity-boundary check, and the Decimal-at-the-DynamoDB-boundary discipline is uniform.

The one ERROR is a real correctness bug: the contact-cap reconciliation on `intervention_outreach_failed` events references a `:zero` placeholder that is never declared in `ExpressionAttributeValues`. DynamoDB rejects the call with a `ValidationException`, the broad `except Exception` swallows the error, the counter never decrements, and members with flaky channels accumulate phantom contact-cap consumption indefinitely. This is exactly the failure mode the comment promises to fix, and the same gap was flagged as a TODO in Recipe 4.4's main recipe and reproduced here without the boto3 syntax check. The fix is one extra entry in `ExpressionAttributeValues` plus a small cleanup of the unused empty `ExpressionAttributeNames`.

The seven NOTEs are smaller items: a dead `policy_weights` parameter on the allocator, four inline `import re as _re` statements that should be a single top-of-file import, an `event_id`/`timestamp` default mismatch on missing-timestamp events (same pattern flagged in 4.3 and 4.4 reviews), a per-patient DynamoDB GetItem fan-out in `_compute_regimen_features` that would cause throughput pain at scale (same pattern as 4.4 finding), a `compute_priority` normalization that yields zero for single-row intervention types, a `datetime.date.today()` in `_compute_target_window` that should be UTC, and the `dict.get(key, default)`-vs-explicit-`None` pattern in cohort metric dimensions (same pattern as 4.4). Several repeat patterns from earlier reviews; a coordinated chapter-wide STYLE-GUIDE.md addition (covering the falsy-default-vs-`is None` pattern, the timestamp-default consistency pattern, the inline-import discouragement, and the BatchGetItem-over-serial-GetItem pattern) would be more durable than re-litigating these once per recipe.

FAIL verdict on the one ERROR. The fix is localized to one update_item call; a re-review pass after that fix and any of the NOTEs the author chooses to address would be quick.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(ERROR)** The contact-cap reconciliation in `process_adherence_event`'s `intervention_outreach_failed` / `intervention_outreach_bounced` branch declares `:zero` in `ExpressionAttributeValues`. The `ExpressionAttributeNames={}` is removed (it was empty and unnecessary). The `ConditionalCheckFailedException` from a counter-already-zero condition continues to be handled gracefully (currently absorbed by the broad `except Exception`; optionally narrowed to `botocore.exceptions.ClientError`).
2. **(NOTE)** The unused `policy_weights` parameter on `allocate_heterogeneous` is removed. The `equity_floors` parameter stays.
3. **(NOTE)** The four inline `import re as _re` statements in `_bedrock_barrier_second_opinion`, `_bedrock_tailor_reminder`, `_bedrock_pharmacist_brief`, and `_bedrock_pcp_briefing` are consolidated into a single top-of-file `import re`. Optionally, the JSON-extraction-and-parse pattern is extracted into a small helper.
4. **(NOTE)** `process_adherence_event` computes the timestamp once and uses the same value for `event_id` construction and the stored `timestamp` field, regardless of whether the inbound event includes a timestamp. The same pattern applies to `_record_pcp_override`.
5. **(NOTE)** `_compute_regimen_features`'s per-patient profile lookup uses `BatchGetItem` with the 100-key chunking pattern (and `UnprocessedKeys` retry) rather than a serial GetItem per patient. Or the comment explicitly acknowledges the throughput trade-off so a reader doesn't carry the simplification into production.
6. **(NOTE)** `compute_priority`'s normalization either falls back to a neutral value (e.g., `0.5`) when `lo == hi` for a single-row intervention type, or adds an inline comment naming the design choice and its limitation.
7. **(NOTE)** `_compute_target_window` uses `datetime.datetime.now(timezone.utc).date()` (or calls `_today_str()` and parses it back to a date) instead of `datetime.date.today()`.
8. **(NOTE)** `_lookup_cohort_features_from_profile` normalizes `None` values to `"unknown"` (or the metric-emission sites use `or "unknown"` rather than `dict.get(key, default)` with stringification) so a member with a null `sdoh_cohort` doesn't surface as the literal string `"None"` in CloudWatch dimensions. Apply symmetrically to `language`, `age_band`, and `engagement_history_quartile`.
