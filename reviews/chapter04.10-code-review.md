# Code Review: Recipe 4.10 - Dynamic Treatment Regime Recommendation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-21
**Files reviewed:**
- `chapter04.10-dynamic-treatment-regime-recommendation.md` (main recipe pseudocode)
- `chapter04.10-python-example.md` (Python companion)

**Validation performed:**
- Walked the six pseudocode steps against Python functions one-to-one
- Verified boto3 API call shapes for DynamoDB resource (`get_item`, `put_item`, `update_item`, `scan`), Bedrock Runtime (Anthropic Messages API), Kinesis (`put_record`), CloudWatch (`put_metric_data`), S3, EventBridge, SageMaker
- Traced numeric values flowing into DynamoDB through `_to_decimal` / `_to_decimal_dict` / `_from_decimal`
- Walked the demo runner end-to-end against Sara (the index patient) to verify the demo path
- Traced `_q_policy` semantics across training, serving, and OPE call sites
- Traced cohort feature flow from synthetic generator through trajectories, behavior policy, OPE, recommendation record, and surveillance
- Verified opaque-ID discipline, PHI handling at the LLM boundary, eligibility/contraindication filters, customer-managed KMS posture, structured-then-narrative direction
- Traced the four-layer validator logic against the curated mock narrative outputs

---

## Summary

The Python companion is structurally faithful to the main recipe's six pseudocode steps and the architectural picture (regime catalog, longitudinal trajectory pipeline with explicit decision points and rewards, behavior policy estimation with cohort-stratified calibration, multi-method regime training with Q-learning backward induction as the workhorse, multi-estimator off-policy evaluation with cohort stratification and sensitivity analysis, recommendation serving with eligibility / OOD / similar-trajectory / four-layer-validator-protected narrative, action-taken capture and periodic surveillance). The Decimal-at-the-DynamoDB-boundary discipline is consistent with proper bool guards, the structured-then-narrative direction is enforced (the LLM never makes clinical decisions; the structured recommendation is the source of truth and the narrative renders on top with strict validator enforcement), the opaque-ID pattern is correct (UUID-based, no embedded patient_id), the OOD detector combines k-NN extrapolation distance with propensity floor / ceiling, the similar-trajectory retrieval is privacy-aware (k-anonymity threshold), the multi-estimator OPE structure (DR plus self-normalized IS plus FQE plus method-agreement plus cohort-stratified plus sensitivity) matches the recipe text, the propensity floor `max(b_prob, 1e-3)` is the right mitigation for the deterministic-target-policy variance problem, and the four-layer validator (schema, fact grounding, prohibited language, required content) is appropriately strict for the highest-stakes recipe in Chapter 4.

That said, three WARNINGs need attention before this goes to readers, plus a handful of NOTEs. The first WARNING is that `serve_recommendation` builds a recommendation record whose `state` field is a flat dict of state-schema features (`current_a1c`, `current_egfr`, etc.) without any cohort-features sub-dict, but `run_surveillance` reads cohort values via `r.get("state").get("cohort", {}).get(axis, "unknown")`. Since "cohort" is not a key on the flat state dict, every patient lands in the `"unknown"` cohort across every axis; the cohort-stratified surveillance loop then iterates exactly one cohort per axis, computes `disparity = max - min` over a single value, and gets 0.0 every time. No cohort disparity alert can ever fire. The recipe describes cohort-stratified surveillance as "non-negotiable" and explicitly calls out the Obermeyer pattern; the demo silently disables it. The second WARNING is that `_q_policy` always uses the first non-None Q model in the list (`q_model = next((m for m in q_models if m is not None), None)`) regardless of decision-point index, and the same `_q_policy` is the target policy passed into all three OPE estimators (`target_policy = lambda s: _q_policy(cand["models"], s, regime)`). Q-learning with backward induction fits Q_0, Q_1, ..., Q_{T-1}, one per decision point; the OPE evaluation of a trajectory step at decision point t should use Q_t to determine the recommended action and value. Using Q_0 throughout silently evaluates a different policy than the one Q-learning produced; the OPE point estimates and CIs do not represent the trained backward-induction policy. The comment in `_q_policy` acknowledges the simplification for serving but does not flag that OPE has the same issue. The third WARNING is that `record_action_taken` does not append the action-taken event to the patient's trajectory record, but the pseudocode's `record_action_taken(...)` explicitly does (`append_to_trajectory(rec.patient_id, rec.regime_id, {decision_point_id, timestamp, state, action, recommendation_id, followed_regime})` after the recommendation update and before the Kinesis emit). The recipe text calls out the in-production trajectories continuously feeding the next training cycle as the load-bearing feedback loop; the Python silently omits the trajectory append without comment, so the demo's pseudocode-to-Python consistency is broken on the load-bearing step.

Beyond those, eight NOTEs cover the demo runner's print-vs-reality mismatch (same as 4.6 / 4.7 / 4.8 / 4.9), the Scan-where-Query-suffices and missing-pagination pattern in `run_surveillance`, the missing identity-boundary check that the pseudocode's `record_action_taken` includes, the missing `globals()` mock-injection comment (chapter-wide pattern), the dead `_emit_metric` helper (defined but never called), the unused `PATIENT_NARRATIVE_MODEL_ID` constant (defined but never invoked), the bare `try/except: pass` patterns inside the Kinesis emits, and the misleadingly-named `observed_reward` variable in `run_surveillance` (it is actually the average of predicted Q values across recent recommendations, not an observed outcome).

---

## Verdict: PASS

No ERRORs. Three WARNINGs (at the FAIL threshold of more than three; three is not more than three). Eight NOTEs.

The three WARNINGs are localized and well-scoped: the cohort-features bug silently breaks fairness instrumentation that the recipe says is non-negotiable, the `_q_policy`-during-OPE bug silently evaluates the wrong policy and produces misleading point estimates and CIs, and the missing trajectory-append step breaks the feedback loop. They should all be addressed before the recipe ships, because they teach incorrect design patterns to a reader who copies the example into a real deployment, but they do not block the demo from running to completion.

---

## Findings

### Finding 1: Recommendation Record Lacks `cohort_features`; `run_surveillance` Cohort-Stratified Loop Always Sees a Single `"unknown"` Cohort, Disabling Disparity Alerting

- **Severity:** WARNING
- **File:** `chapter04.10-python-example.md`
- **Locations:** `serve_recommendation` (the recommendation record construction in Step 5F), `run_surveillance` (Step 6C cohort-stratified surveillance loop), `_evaluate_eligibility` (the only consumer of `patient_profile`)
- **Description:**

  `serve_recommendation` builds the recommendation record like this:

  ```python
  record = {
      "recommendation_id":   recommendation_id,
      "patient_id":          patient_id,
      "regime_id":           regime["regime_id"],
      "regime_version":      regime["version"],
      "outcome":             "served",
      "state":               {
          f: float(patient_state.get(f, 0.0))
          for f in regime["state_schema"]
      },
      "eligibility":         eligibility,
      "ood_flag":            ood_result["flagged"],
      ...
  }
  ```

  `regime["state_schema"]` is `["current_a1c", "current_egfr", "current_acr", "current_systolic_bp", "comorbidity_tier", "polypharmacy_count"]`. The persisted `state` dict has those six keys and nothing else.

  `serve_recommendation` does take `patient_profile` as a parameter, but the only place it gets used is `_evaluate_eligibility(patient_state, patient_profile, regime)`. The cohort fields on the profile (`age_band`, `preferred_language`, `race_ethnicity`, etc.) are never copied onto the recommendation record.

  Then `run_surveillance` does its cohort-stratified loop:

  ```python
  cohort_metrics = {}
  for axis in COHORT_AXES:
      per_cohort = {}
      cohort_values = sorted({
          (r.get("state") or {}).get("cohort", {}).get(axis, "unknown")
          for r in recs
      })
      for value in cohort_values:
          sub = [r for r in recs
                  if (r.get("state") or {}).get(
                      "cohort", {}).get(axis) == value]
          ...
  ```

  Tracing this against Sara's recommendation record:

  1. `r.get("state")` returns `{"current_a1c": 8.4, "current_egfr": 41.0, "current_acr": 78.0, "current_systolic_bp": 134.0, "comorbidity_tier": 3.0, "polypharmacy_count": 7.0}`.
  2. `.get("cohort", {})` looks for the key `"cohort"` on that flat state dict. There is no such key. Returns `{}`.
  3. `.get(axis, "unknown")` on the empty dict returns `"unknown"` for every axis.

  The set comprehension collapses to `{"unknown"}` for every axis. The inner loop iterates exactly one cohort value (`"unknown"`), computes the per-cohort follow-rate, and ends up with `rates = [some_single_value]`. Then:

  ```python
  rates = [v["follow_rate"] for v in per_cohort.values()]
  disparity = float(max(rates) - min(rates)) if rates else 0.0
  ```

  `max([x]) - min([x]) = 0.0`. Always. For every cohort axis. The disparity alert threshold (`COHORT_DISPARITY_ALERT_THRESHOLD = 0.10`) is never crossed because the disparity is always zero.

  Two consequences:

  1. **The cohort-stratified surveillance does not work.** The recipe text describes this as the load-bearing equity instrumentation: *"Cohort-stratified surveillance: outcome trajectories by cohort, regime adherence by cohort, OOD-flag rates by cohort. Disparities trigger committee review."* The demo silently disables every disparity check the recipe says are required.
  2. **The bug is invisible without inspection.** The demo runs to completion, prints `Surveillance alerts: 0`, and a learner concludes the system found no fairness issues. In production, a regime with a meaningful cohort disparity would silently sit at zero alerts for the same reason.

  The synthetic generator already attaches `cohort_features` to every trajectory step (the cohort axes are correctly populated for OPE in Step 4), and the trajectory storage carries them through. The plumbing is in place; the recommendation record is the missing link.

- **Suggested fix:** Persist the cohort features on the recommendation record at the time of generation, and read from that field in surveillance. In `serve_recommendation`:

  ```python
  cohort_features = {
      "race_ethnicity":   patient_profile.get("race_ethnicity", "unknown"),
      "language":         patient_profile.get("preferred_language", "unknown"),
      "age_band":         patient_profile.get("age_band", "unknown"),
      "comorbidity_tier": int(patient_state.get("comorbidity_tier", 0)),
  }
  record = {
      "recommendation_id":  recommendation_id,
      ...
      "cohort_features":    cohort_features,
      ...
  }
  ```

  And update `run_surveillance` to read from the new field:

  ```python
  cohort_values = sorted({
      r.get("cohort_features", {}).get(axis, "unknown")
      for r in recs
  })
  ...
  sub = [r for r in recs
         if r.get("cohort_features", {}).get(axis) == value]
  ```

  Verify the fix by re-running the demo against multiple synthetic patients with different cohort profiles and confirming that the per-cohort follow-rates differ (and that the disparity computation actually crosses the threshold when the synthetic generator's encoded Spanish-language access disparity surfaces in the recommendations). As a defensive add, log a warning in `run_surveillance` when every record has `cohort_features={}`:

  ```python
  if recs and all(not r.get("cohort_features") for r in recs):
      logger.warning(
          "All %d recommendations missing cohort_features; "
          "cohort-stratified surveillance will produce zero "
          "disparity for every axis. Caller is likely persisting "
          "recommendations without cohort attribution.",
          len(recs),
      )
  ```

  This makes the silent failure noisy and saves the next person from chasing the same bug.

---

### Finding 2: `_q_policy` Always Uses Q Model at Index 0; OPE Evaluates a Different Policy Than Q-Learning Trained

- **Severity:** WARNING
- **File:** `chapter04.10-python-example.md`
- **Locations:** `_q_policy` (the `q_model = next(...)` line), `_train_q_learning_backward` (which produces a list of Q models, one per decision point), `_doubly_robust_ope` / `_self_normalized_is` / `_fitted_q_evaluation` (all three call `target_policy = lambda s: _q_policy(cand["models"], s, regime)`)
- **Description:**

  Q-learning with backward induction produces a separate Q model per decision point. `_train_q_learning_backward` walks `t = T-1, T-2, ..., 0` and fits a `GradientBoostingRegressor` at each step:

  ```python
  q_models = [None] * horizon
  for t in range(horizon - 1, -1, -1):
      ...
      model = GradientBoostingRegressor(...)
      model.fit(X, targets)
      q_models[t] = model
  return q_models, metadata
  ```

  The horizon in `SAMPLE_REGIME` is 4 decision points, so the demo trains four distinct Q models: `q_models[0]`, `q_models[1]`, `q_models[2]`, `q_models[3]`.

  The intended use of these models is decision-point-indexed: at decision point t, evaluate `Q_t(s, a)` to get the recommended action and its value. The pseudocode and the recipe prose are explicit on this. In `_train_q_learning_backward`, the targets are computed as `r_t + V_{t+1}(s')`, where `V_{t+1}` is computed by indexing `q_models[t+1]`. So each Q model is specifically calibrated to its own decision-point index.

  But `_q_policy` discards the index:

  ```python
  def _q_policy(q_models: list, state: np.ndarray, regime: dict) -> dict:
      ...
      # Use the first valid Q model in the horizon for the demo. Real
      # serving uses the Q model corresponding to the patient's current
      # decision-point index in the trajectory.
      q_model = next((m for m in q_models if m is not None), None)
      ...
      q_values = []
      for a in range(n_actions):
          x = np.concatenate([state, _action_one_hot(a, n_actions)])
          q_values.append(float(q_model.predict(x.reshape(1, -1))[0]))
      ...
  ```

  And the same `_q_policy` gets wrapped as `target_policy` and passed to all three OPE estimators:

  ```python
  for cand in candidate_regimes:
      target_policy = lambda s: _q_policy(cand["models"], s, regime)
      dr_value, dr_lo, dr_hi = _doubly_robust_ope(
          trajectories, target_policy,
          behavior_policy["model"], cand["models"], regime,
      )
      is_value, is_lo, is_hi = _self_normalized_is(
          trajectories, target_policy,
          behavior_policy["model"], regime,
      )
      fqe_value, fqe_lo, fqe_hi = _fitted_q_evaluation(
          trajectories, target_policy,
          cand["models"], regime,
      )
  ```

  Inside `_doubly_robust_ope`, the trajectory is walked step by step:

  ```python
  for steps in trajectories:
      v = 0.0
      rho = 1.0
      for step in steps:
          ...
          state = np.array(step["state"])
          action_idx = step["action_idx"]
          ...
          target = target_policy(state)
          t_prob = 1.0 if target["recommended_action_idx"] == action_idx else 0.0
          q_baseline = float(target["recommended_value"])
          q_taken = float(target["q_values"][action_idx])
          rho = rho * (t_prob / b_prob)
          v += rho * (step["reward"] - q_taken) + q_baseline
  ```

  Every call to `target_policy(state)` inside this loop uses the same `q_models[0]`. So at decision point 0, OPE uses the right model. At decision point 1, OPE uses Q_0, not Q_1. At decision point 2, OPE uses Q_0, not Q_2. The recommended action and the Q values at later decision points are computed from a Q model trained on different targets.

  Two consequences:

  1. **OPE evaluates a different policy than the one Q-learning produced.** The recommended action at step t (from `target["recommended_action_idx"]`) is `argmax_a Q_0(s, a)`, not `argmax_a Q_t(s, a)`. The trained policy is `pi(s, t) = argmax_a Q_t(s, a)`; the policy OPE evaluates is `pi'(s) = argmax_a Q_0(s, a)`, which is a stationary policy. The DR / IS / FQE point estimates and CIs all describe the value of the wrong policy.
  2. **The bug is silent and methodologically central.** The recipe text spends substantial space describing OPE as the load-bearing inference: *"OPE is not a sanity check; it is the load-bearing inference. A team that under-invests in OPE (uses one estimator, skips cohort stratification, omits sensitivity analysis) is shipping policies whose deployment risk they cannot accurately characterize."* The demo runs three estimators and produces a method-agreement score, but they all evaluate the wrong policy, so the agreement is not informative about the trained policy's value.

  The comment in `_q_policy` ("The demo uses the Q model at decision point 0 for serving; production picks the appropriate decision-point Q model from the patient's trajectory state") flags the simplification for serving but not for OPE. A reader copying the OPE structure into a real deployment carries this bug forward.

- **Suggested fix:** Make `_q_policy` accept an optional decision-point index, and have the OPE estimators pass it explicitly. Sketch:

  ```python
  def _q_policy(q_models: list, state: np.ndarray, regime: dict,
                  decision_point_index: int = 0) -> dict:
      n_actions = len(regime["action_catalog"])
      # Pick the Q model trained for this specific decision point.
      # If the model for this index is missing (rare; happens when
      # there were no training rows at that decision point), fall back
      # to the closest available model and log the substitution.
      q_model = q_models[decision_point_index] if (
          0 <= decision_point_index < len(q_models)
          and q_models[decision_point_index] is not None
      ) else next((m for m in q_models if m is not None), None)
      ...
  ```

  Update each OPE estimator to pass the step's `decision_point_index`:

  ```python
  def _doubly_robust_ope(...):
      for steps in trajectories:
          for step in steps:
              ...
              target = _q_policy(q_models, state, regime,
                                  decision_point_index=step["decision_point_index"])
              ...
  ```

  And similarly for `_self_normalized_is` and `_fitted_q_evaluation`. Update the `target_policy` lambda signatures or replace them with direct calls to `_q_policy`. For serving (`serve_recommendation`), pass the patient's current decision-point index from the trajectory metadata:

  ```python
  trajectory_metadata = DynamoDB.GetItem(...)
  current_dp_index = int(trajectory_metadata.get(
      "last_decision_point_index", 0)) + 1
  policy = _q_policy(q_models, state_vec, regime,
                       decision_point_index=current_dp_index)
  ```

  Verify the fix by re-running the demo and confirming that DR / IS / FQE values change (they should, because the policy being evaluated is now different) and that the method-agreement score remains high (because the three estimators are now consistently evaluating the same trained policy).

  As an alternative if the fix is too invasive for the demo's scope: explicitly clamp the horizon to 1 in `SAMPLE_REGIME` (`"horizon_decision_points": 1`), so Q-learning trains a single Q model and the simplification in `_q_policy` is correct by construction. This is a smaller change but limits the demo's pedagogical value (it can no longer show backward induction). Either fix is acceptable; pick the one whose teaching content the recipe wants to keep.

---

### Finding 3: `record_action_taken` Does Not Append the Action to the Patient's Trajectory; Feedback Loop Pseudocode-to-Python Inconsistency on a Load-Bearing Step

- **Severity:** WARNING
- **File:** `chapter04.10-python-example.md`
- **Locations:** `record_action_taken` (the function body), the main recipe's pseudocode for `record_action_taken(...)` in Step 6
- **Description:**

  The pseudocode in the main recipe explicitly includes a trajectory-append step:

  ```
  FUNCTION record_action_taken(recommendation_id, action_taken_payload):
      ...
      DynamoDB.UpdateItem("recommendation-records", recommendation_id, {
          action_taken: action_taken_payload.action_id,
          action_taken_kind: classify_action(...),
          action_rationale: action_taken_payload.rationale,
          patient_share_decision: action_taken_payload.patient_share_decision,
          action_recorded_at: current UTC timestamp
      })

      // Append to the patient's trajectory record. This is the same
      // trajectory record that powers training; the in-production
      // trajectories continuously feed the next training cycle.
      append_to_trajectory(rec.patient_id, rec.regime_id, {
          decision_point_id: rec.decision_point_id,
          timestamp: current UTC timestamp,
          state: rec.state,
          action: action_taken_payload.action_id,
          recommendation_id: recommendation_id,
          followed_regime: classify_action(...) == "followed_recommendation"
      })

      Kinesis.PutRecord(stream = "dtr-events", record = {...})
  ```

  Three steps in pseudocode: update the recommendation record, append to the trajectory record, emit a Kinesis event.

  The Python `record_action_taken` does steps 1 and 3 but skips step 2:

  ```python
  def record_action_taken(recommendation_id: str,
                              action_taken_payload: dict) -> dict:
      ...
      try:
          rec_table.update_item(
              Key={"recommendation_id": recommendation_id},
              UpdateExpression=(
                  "SET action_taken = :a, action_taken_kind = :k, "
                  "action_rationale = :r, patient_share_decision = :p, "
                  "action_recorded_at = :t"
              ),
              ExpressionAttributeValues=_to_decimal_dict({...}),
          )
      except Exception as exc:
          logger.warning(...)

      try:
          kinesis_client.put_record(
              StreamName=DTR_EVENTS_STREAM_NAME,
              ...
          )
      except Exception:
          pass
      return update
  ```

  No call to `append_to_trajectory`, no S3 put updating the trajectory blob, no DynamoDB update on `trajectory-metadata`. The trajectory record persisted in `build_trajectories` is never extended with the post-decision (state, action, recommendation_id, followed_regime) tuple.

  Two consequences:

  1. **The feedback loop is broken on its load-bearing step.** The recipe text frames the trajectory append as the mechanism that turns the regime from a static artifact into a living one: *"The feedback loop is what turns the regime from a static artifact into a living one. Skip the action-taken capture and you cannot tell whether clinicians follow the recommendations; skip the outcome surveillance and you cannot tell whether the regime is performing as the OPE estimated."* The Python keeps the action-taken capture (on the recommendation record) but loses the in-production trajectories that feed the next training cycle, which is exactly the half-step the recipe warns against.
  2. **The pseudocode-to-Python inconsistency teaches the wrong pattern.** A reader looking at the demo as the reference for translating the recipe sees only update-recommendation and emit-Kinesis. The trajectory append, which is the bridge between operational events and the next training cycle, is silently omitted with no comment. A learner copying the pattern reproduces the gap.

  The recipe text's "Sample governance package" section under Expected Results even reports:

  > | Per-recommendation evidence depth (similar-trajectory N) | 0 (none surfaced) | 5-20 anonymized trajectories |

  But the similar-trajectory pool is the historical training data; in-production trajectories do not flow back to enrich it. This is a chapter-wide pattern worth establishing correctly here because Recipe 4.10 is the recipe whose feedback loop is most central to its value claim.

- **Suggested fix:** Add the trajectory-append step to `record_action_taken`. The simplest version reads the existing trajectory metadata, fetches the trajectory blob from S3, appends the new step, and writes it back. Sketch:

  ```python
  def record_action_taken(recommendation_id: str,
                              action_taken_payload: dict) -> dict:
      ...
      # Append to the patient's trajectory record. This is the same
      # trajectory record that powers training; the in-production
      # trajectories continuously feed the next training cycle. Skip
      # this and the regime ages out of relevance because the
      # surveillance pipeline cannot enrich the training data with
      # post-decision observations.
      _append_to_trajectory(
          patient_id=rec["patient_id"],
          regime_id=rec["regime_id"],
          new_step={
              "decision_point_index": rec.get("decision_point_index", 0),
              "timestamp":            _now_iso(),
              "state":                rec.get("state"),
              "action_id":            action_id,
              "action_idx":           _action_id_to_idx(action_id),
              "recommendation_id":    recommendation_id,
              "followed_regime":      kind == "followed_recommendation",
              "out_of_catalog":       kind == "out_of_catalog",
          },
      )

      try:
          kinesis_client.put_record(...)
      except Exception:
          pass
      return update


  def _append_to_trajectory(patient_id: str, regime_id: str,
                              new_step: dict) -> None:
      """
      Append a new step to the patient's trajectory record. Reads the
      existing trajectory blob from S3, appends, writes back. Updates
      the trajectory-metadata pointer.

      Production: this is a Lambda consumer on the dtr-events stream
      with idempotency keys to prevent duplicate appends on retry.
      The demo collapses it for clarity.
      """
      metadata_table = dynamodb.Table(TRAJECTORY_METADATA_TABLE)
      metadata = _safe_get_item(metadata_table, {
          "patient_id": patient_id, "regime_id": regime_id,
      })
      if not metadata:
          logger.warning(
              "No trajectory metadata for (%s, %s); cannot append.",
              patient_id, regime_id,
          )
          return
      ...
  ```

  Alternatively, if a full S3 read-append-write is too heavy for a demo, write the new step to a "trajectory-appendix" partition and acknowledge in the comment that production reconciles the appendix with the base trajectory in the next training cycle. Either fix closes the pseudocode gap; the second is less code.

  As a minimum-effort fix: leave the body as-is but add a `# TODO` block at the end of the function that explicitly names the missing step and links to the production-grade pattern in the Gap to Production section. This is the lowest-effort fix that prevents the silent inconsistency from teaching the wrong pattern.

---

### Finding 4: Demo Runner's Print Statements Imply Operations Persisted When DynamoDB Tables Don't Exist

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block) and `run_full_demo_cycle`
- **Description:**

  Same class of issue flagged in 4.6, 4.7, 4.8, and 4.9 reviews. The demo runs against unprovisioned DynamoDB tables and S3 buckets; every persistence call is wrapped in `try/except Exception as exc: logger.warning(...)` (good discipline), so the demo runs to completion. But the print statements imply the underlying state transitions actually happen:

  ```
  Step 1: build trajectories...
    Trajectories built: 200; short: 0; out-of-catalog: 0
  Step 2: estimate behavior policy...
    Behavior policy version: bp-...; overall ECE: 0.063; calibration blocking: 0
  Step 3: train regime...
    Candidate regimes: 1; methods: ['q_learning']
  Step 4: run OPE...
    DR value: 0.79 (CI 0.74-0.83); IS value: 0.77; FQE value: 0.80; agreement: 0.96
    Cohort axes evaluated: 4; insufficient-data cells: ...
  Step 5: serve recommendation...
    Recommendation id: rec-...; outcome: served
    Recommended action: add_sglt2_dapagliflozin_10_mg_daily; value: ...; OOD: False
    Validator passed: True; layers: ['schema', 'fact_grounding', 'prohibited_language', 'required_content']
  Step 6: record action-taken...
    Action taken kind: followed_recommendation
  Step 6: run surveillance...
    Surveillance alerts: 0
  ```

  In practice against unprovisioned tables:
  - Trajectory metadata persistence to DynamoDB fails silently with logged warnings.
  - Trajectory blob persistence to S3 fails (NoSuchBucket), warning logged.
  - Behavior policy artifact persistence to S3 fails, warning logged.
  - Regime version persistence to DynamoDB fails, warning logged.
  - OPE results persistence to S3 fails, warning logged.
  - Recommendation record persistence to DynamoDB and S3 archive both fail, warnings logged.
  - `record_action_taken`'s `_safe_get_item` returns `{}` because the table doesn't exist; the function logs "Recommendation %s not found for action capture" and returns `{}`. The print line shows `Action taken kind: None` because `action_record.get('action_taken_kind')` is None on the empty dict. Closer to honest, but still implies the action capture flow ran.
  - `run_surveillance`'s scan fails, returns no recommendations, `recs` is empty, the function logs "No actioned recommendations to surveil" and returns `[]`. The print shows `Surveillance alerts: 0`, which is technically true because zero alerts were raised, but only because zero records were available to evaluate.

  None of the Step 1-6 prints reflect what actually happened in storage.

- **Suggested fix:** Same suggestion as 4.7 / 4.8 / 4.9 reviews:

  1. **Lighter fix:** Add a clear "running offline against unprovisioned tables" disclaimer at the top of the demo runner, and reframe the prints to describe what each step would do in a provisioned environment rather than what executes in the offline run.
  2. **Heavier fix:** Provide a DynamoDB-Local + Kinesis-Local + S3-mock docker-compose snippet in Setup so the demo can be exercised end-to-end. Recipes 4.7 / 4.8 / 4.9 deferred this; consistency suggests deferring here too unless the project plans to retrofit it across the chapter.

  Adjacent cleanup: the `try/except Exception: pass` patterns around the Kinesis emits should become `try/except Exception as exc: logger.warning(...)` so a developer with `logger.setLevel(logging.WARNING)` sees the failures (Finding 8).

---

### Finding 5: `run_surveillance` Uses Scan Without Pagination Where Query Would Suffice

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** `run_surveillance` (the `rec_table.scan()` block)
- **Description:**

  Same pattern flagged in 4.6 Finding 2, 4.8 Finding 6, and 4.9 Finding 4.

  ```python
  recs = []
  try:
      response = rec_table.scan()
      for item in response.get("Items", []):
          r = _from_decimal(item)
          if r.get("regime_id") != regime_id:
              continue
          if r.get("action_taken_kind") is None:
              continue
          recs.append(r)
  except Exception as exc:
      logger.warning("Scan failed in surveillance: %s", exc)
  ```

  Two issues:

  1. **Scan instead of Query.** The function comment names the production fix (`# Production: a (regime_id, action_recorded_at) GSI; the demo scans because the example does not provision indexes`), so the issue is acknowledged. But the demo's pragmatic shortcut becomes the reference pattern a reader carries forward. At the recipe's stated cohort (50,000 active patients in regime-eligible cohorts with quarterly decision points), the recommendation-records table grows to hundreds of thousands of rows per regime per year; scan-and-filter dominates surveillance cost.
  2. **No pagination.** The Scan returns at most 1MB of items per call; production volumes silently truncate without a `LastEvaluatedKey` loop. Surveillance metrics computed on a truncated subset look complete but are biased toward whatever rows happened to land in the first 1MB.

- **Suggested fix:** Use a `(regime_id, action_recorded_at)` GSI Query with pagination:

  ```python
  from boto3.dynamodb.conditions import Key

  recs = []
  try:
      kwargs = {
          "IndexName": "regime-id-action-recorded-at-index",
          "KeyConditionExpression": (
              Key("regime_id").eq(regime_id)
              & Key("action_recorded_at").gte(window_start)
          ),
          "FilterExpression": "attribute_exists(action_taken_kind)",
      }
      while True:
          response = rec_table.query(**kwargs)
          for item in response.get("Items", []):
              recs.append(_from_decimal(item))
          if "LastEvaluatedKey" not in response:
              break
          kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
  except Exception as exc:
      logger.warning("Surveillance query failed: %s", exc)
  ```

  Document the GSI in a comment block above the function and in the IAM permissions list in Setup. If retaining the Scan for demo simplicity, at minimum add a pagination loop and update the function comment to name both the GSI and the pagination requirements as production fixes.

---

### Finding 6: `record_action_taken` Pseudocode Includes an Identity-Boundary Check; Python Implementation Skips It

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** `record_action_taken`
- **Description:**

  The pseudocode's `record_action_taken` includes an identity-boundary check after fetching the recommendation:

  ```
  // Identity-boundary check: the clinician_id must match the
  // session that received the recommendation; mismatch is logged
  // and rejected.
  IF action_taken_payload.clinician_id != rec.served_to_clinician_id:
      log_security_violation(...)
      REJECT
  ```

  The Python `record_action_taken` does not implement this check. There is no `served_to_clinician_id` field on the recommendation record (the recommendation record built by `serve_recommendation` does not capture which clinician received it), and `record_action_taken` does not consult `action_taken_payload.get("clinician_id")` against any session-bound identity.

  The pseudocode frames this as a security primitive: the recommendation API is invoked by an authenticated EHR session (typically a SMART on FHIR app), and the action-taken event must come from the same session. Skipping the check means any caller who knows a recommendation_id can record an action against it. In a real deployment this is a hard fail; in the demo, the omission is silent.

  The demo runner does pass `"clinician_id": "clinician-0142"` in the action-taken payload, but the field is never read. A learner reading the demo as the reference for the action-taken step does not see the identity-boundary check translated.

- **Suggested fix:** Add the served-to-clinician capture in `serve_recommendation` (extract `calling_clinician_id` from the request context, persist it on the recommendation record), and the identity-boundary check in `record_action_taken`. Sketch:

  In `serve_recommendation`, take a `calling_clinician_id` parameter and persist:

  ```python
  record = {
      ...
      "served_to_clinician_id": calling_clinician_id,
      ...
  }
  ```

  In `record_action_taken`, validate the match:

  ```python
  if action_taken_payload.get("clinician_id") != rec.get("served_to_clinician_id"):
      logger.warning(
          "Identity-boundary mismatch: action-taken clinician %s "
          "does not match recommendation's served_to_clinician_id %s "
          "for recommendation %s.",
          action_taken_payload.get("clinician_id"),
          rec.get("served_to_clinician_id"),
          recommendation_id,
      )
      return {"status": "rejected", "reason": "identity_boundary_mismatch"}
  ```

  At minimum, add a `# TODO` block in `record_action_taken` that names the omission and points to where it would be wired up in production. The pseudocode-to-Python consistency rule expects that pseudocode-mentioned security primitives either appear in the Python or are explicitly flagged as out-of-scope in the function comment.

---

### Finding 7: `globals()` Mock Injection Without Explanatory Comment (Same Pattern as 4.5/4.6/4.7/4.8/4.9)

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** Demo runner (`if __name__ == "__main__":` block)
- **Description:**

  ```python
  globals()["_bedrock_invoke_clinician_narrative"] = _mock_bedrock
  ```

  The pattern works (same-module name resolution against module globals at call time), but isn't explained. Same finding as 4.6 Finding 7, 4.7 Finding 9, 4.8 Finding 8, and 4.9 Finding 5. A learner who tries to apply the pattern across module boundaries discovers it doesn't work the same way.

- **Suggested fix:** Add the comment used in (or recommended for) prior reviews:

  ```python
  # Patch the module-level Bedrock helper for the offline demo.
  # This works because the calling functions resolve the
  # _bedrock_invoke_clinician_narrative name against the module
  # global namespace at call time, and globals() in __main__ returns
  # this module's dict. Production never bypasses this; the real
  # Bedrock calls run.
  globals()["_bedrock_invoke_clinician_narrative"] = _mock_bedrock
  ```

---

### Finding 8: Bare `try/except: pass` Patterns Hide Persistence Failures From Local Development

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Locations:** seven Kinesis `put_record` blocks (in `build_trajectories`, `estimate_behavior_policy`, `train_regime`, `run_ope`, `_emit_recommendation_event`, `record_action_taken`, `run_surveillance`, plus the `narrative_validator_fallback` emit in `_generate_clinician_narrative`)
- **Description:**

  Every Kinesis emit follows this shape:

  ```python
  try:
      kinesis_client.put_record(
          StreamName=DTR_EVENTS_STREAM_NAME,
          PartitionKey=...,
          Data=json.dumps({...}, default=str).encode("utf-8"),
      )
  except Exception:
      pass
  ```

  The `try/except: pass` swallows the failure silently with no log entry. A developer running the demo locally with `logger.setLevel(logging.WARNING)` sees no indication that the Kinesis stream doesn't exist; in production, a transient Kinesis throttling event would also be invisible. The DynamoDB and S3 write paths in this same file use the better pattern (`logger.warning`); the inconsistency is a hazard.

  Same pattern flagged in 4.7 Finding 6, 4.8 Finding 5, and 4.9 Finding 7.

- **Suggested fix:** Replace each `except Exception: pass` with the file's existing logging pattern:

  ```python
  except Exception as exc:
      logger.warning(
          "Kinesis put_record for event %s failed: %s",
          event_type, exc,
      )
  ```

  Apply across all seven call sites for consistency.

---

### Finding 9: `_emit_metric` Helper Is Defined But Never Called; Dead Observability Code

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** `_emit_metric` (the helper definition) and the file's overall lack of metric publishing
- **Description:**

  The shared helpers section defines:

  ```python
  def _emit_metric(name: str, value: float, dimensions: dict) -> None:
      """
      Emit a CloudWatch custom metric. Swallows errors so a metric-publish
      failure never breaks recommendation generation. ...
      """
      try:
          clean_dims = [
              {"Name": k, "Value": str(v)[:255]}
              for k, v in dimensions.items() if v is not None
          ]
          cloudwatch_client.put_metric_data(
              Namespace=METRIC_NAMESPACE,
              MetricData=[{
                  "MetricName": name,
                  "Dimensions": clean_dims,
                  "Value":      float(value),
                  "Unit":       "Count",
              }],
          )
      except Exception as exc:
          logger.warning("Metric publish failed for %s: %s", name, exc)
  ```

  The helper is well-formed (correctly filters None-valued dimensions, swallows errors so metric-publish failures don't break the recommendation path), and the recipe's main text describes CloudWatch metrics as a load-bearing observability primitive: *"CloudWatch alarms on training failure rates, OPE-confidence-interval-violation rates, OOD-flag rates, and cohort fairness threshold crossings."* The Setup section also names CloudWatch in the IAM permissions list and grants `cloudwatch:PutMetricData`.

  But `_emit_metric` is never called anywhere in the file. No metrics are published at trajectory-build, behavior-policy-estimation, regime-training, OPE, recommendation-serving, action-capture, or surveillance time. A reader expecting the recipe's described observability instrumentation finds the helper but no usage.

  The cohort-stratified surveillance and the validator first-attempt pass rate are the two metrics most worth emitting in this recipe; both are mentioned in the recipe text's performance benchmarks table. Without the helper being wired up, the recipe's claim that "track per-layer fail rates as separate CloudWatch metrics" or "cohort fairness alarms" is aspirational rather than illustrated.

- **Suggested fix:** Either (a) wire the helper into the load-bearing observation points or (b) remove the helper entirely with a comment in the surveillance section pointing to CloudWatch as a production gap. Option (a) costs four to six call sites; option (b) is a five-line deletion.

  Sketch of (a) at the recommendation-serving boundary:

  ```python
  _emit_metric(
      "recommendation_served", value=1,
      dimensions={
          "regime_id":      regime["regime_id"],
          "regime_version": regime["version"],
          "outcome":        record["outcome"],
          "ood_flagged":    str(record.get("ood_flag", False)),
          "validator_passed": str(narrative.get("validator_status", False)),
          "cohort_language": (patient_profile.get("preferred_language") or "unknown"),
      },
  )
  ```

  Same coverage in `_generate_clinician_narrative` for validator-layer fail rates and in `run_surveillance` for cohort follow-rate disparity. Either way, the reader should not be left looking at a defined-but-unused helper.

---

### Finding 10: `PATIENT_NARRATIVE_MODEL_ID` Defined But Never Used; Patient-Facing Narrative Path Missing Despite Being Named

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Locations:** `PATIENT_NARRATIVE_MODEL_ID` (the constant), the file's overall lack of a patient-narrative function
- **Description:**

  The configuration section defines:

  ```python
  CLINICIAN_NARRATIVE_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  PATIENT_NARRATIVE_MODEL_ID    = "anthropic.claude-3-5-haiku-20241022-v1:0"
  ```

  And the inline comment frames the two-model choice deliberately: *"Two distinct LLM use cases. Clinician briefings go to a Sonnet-class model... Patient-facing summaries can use a Haiku-class model for cost efficiency where reading-level allows."*

  The main recipe also enumerates two distinct LLM use cases: clinician-facing regime briefing and patient-facing regime summary. The cost section in the recipe budgets *"~50,000 recommendations per month average across clinician and patient narratives."*

  But the Python implements only the clinician narrative. There is no `_generate_patient_narrative` function, no patient-facing prompt, no patient-facing validator, and no call site for `PATIENT_NARRATIVE_MODEL_ID`. The constant is dead code.

  The Gap to Production section does acknowledge this: *"The example focuses on the clinician narrative. Production supports an optional patient-facing narrative when the clinician chooses to share the recommendation, with reading-level matching, language localization, and the same four-layer validator with patient-specific prohibited-language patterns."* Good acknowledgment.

  The mismatch is between the configuration-time intent (two model IDs, two use cases) and the implementation-time scope (one use case implemented). A reader who notices the unused constant either assumes the patient narrative is missing or that they should implement it themselves.

- **Suggested fix:** Either (a) remove the unused `PATIENT_NARRATIVE_MODEL_ID` constant with a comment that the patient-facing narrative is in Gap to Production, or (b) add a minimal patient-facing narrative function as a stub (could be templated-only, with a comment that production wires the actual Bedrock call). Option (a) is the lower-effort fix; it removes the inconsistency between the configuration and the implementation while preserving the recipe's framing in the Gap to Production section.

---

### Finding 11: `observed_reward` in `run_surveillance` Is Misleadingly Named; Compares Average Predicted Q-Value to OPE Baseline, Not Real Outcomes

- **Severity:** NOTE
- **File:** `chapter04.10-python-example.md`
- **Location:** `run_surveillance` (Step 6B outcome surveillance block)
- **Description:**

  The surveillance computes drift severity as:

  ```python
  # Step 6B: outcome surveillance against OPE baseline. The demo
  # uses observed reward as a proxy; production wires real outcome
  # tracking (A1c trajectories, AKI events, hospitalizations).
  observed_reward = float(np.mean([
      r.get("recommended_action_value", 0.0) for r in recs
  ])) if recs else 0.0
  drift_severity = (
      abs(observed_reward - ope_baseline.get("dr_value", 0.0)) /
      max(abs(ope_baseline.get("dr_value", 1.0)), 1e-3)
  )
  ```

  The variable named `observed_reward` is computed by averaging `recommended_action_value` across recent recommendations. `recommended_action_value` is the Q value the regime predicted for the recommended action at scoring time; it is the model's prediction, not an observed outcome. Comparing the average prediction to the OPE baseline value tells you whether the policy's predicted values have drifted from training-time expectations, which is a different signal from "are observed outcomes consistent with what OPE estimated."

  Two consequences:

  1. **The naming is misleading.** A reader skimming the function sees `observed_reward` and `outcome surveillance against OPE baseline` and concludes that the demo wires up real outcome tracking. The comment does say "the demo uses observed reward as a proxy," but the variable name reinforces the wrong interpretation.
  2. **The drift signal is weak by construction.** Predicted Q values for the recommended action across patients drift only when the policy itself drifts (different patients getting different recommended actions), not when realized outcomes diverge from predicted values. Real calibration drift is detected by comparing observed outcomes to predicted outcomes; this proxy detects something closer to "patient mix drift."

- **Suggested fix:** Rename the variable to reflect what it actually computes, and update the comment to be clear about what the demo is and is not measuring. Sketch:

  ```python
  # Step 6B: outcome surveillance against OPE baseline. The demo
  # computes the average predicted action-value across recent
  # recommendations as a coarse proxy for population-level drift
  # detection. This is NOT a calibration-against-observed-outcomes
  # check; for that, production wires real outcome tracking
  # (A1c trajectories at follow-up labs, AKI events, hospitalizations)
  # and matches them against the predictions stored on the
  # recommendation records.
  avg_predicted_value = float(np.mean([
      r.get("recommended_action_value", 0.0) for r in recs
  ])) if recs else 0.0
  predicted_value_drift = (
      abs(avg_predicted_value - ope_baseline.get("dr_value", 0.0)) /
      max(abs(ope_baseline.get("dr_value", 1.0)), 1e-3)
  )
  outcome_metrics = {
      "avg_predicted_value":     avg_predicted_value,
      "ope_baseline_value":      ope_baseline.get("dr_value"),
      "predicted_value_drift":   float(predicted_value_drift),
  }
  ```

  And use `predicted_value_drift` consistently in the drift-trigger check. The fix is purely cosmetic but eliminates the misleading variable name; a learner copying the surveillance pattern carries forward an honest one rather than a name that overstates the measurement.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Function | Consistent? |
|----------------|-----------------|-------------|
| `build_trajectories(refresh_window)` | `build_trajectories(refresh_window, source_trajectories, regime)` | Yes (eligible-patient identification, decision-point identification, state construction, action labeling, reward computation, censoring handling, trajectory persistence to S3 + DynamoDB metadata, out-of-catalog tracking, short-trajectory exclusion). Synthetic source instead of EHR ETL is documented. |
| `estimate_behavior_policy(trajectories, regime)` | `estimate_behavior_policy(trajectories, regime)` | Yes (training-data assembly skipping censored and out-of-catalog steps, multinomial logistic fit, overall ECE, cohort-stratified ECE with sample-size minimums and insufficient-data flags, calibration blocking enforcement). The cohort blocking logic logs and continues for the demo (production raises an exception), which the comment names. |
| `train_regime(trajectories, behavior_policy, regime)` | `train_regime(trajectories, behavior_policy, regime)` | Yes for Q-learning with backward induction (per-decision-point regression, V_{t+1} computation via the next-step Q model, target = reward + future value). Offline RL, A-learning, and MSM are explicit `logger.info("TODO: ...")` placeholders that match the recipe's framing of method-diversity-as-future-work. SageMaker Model Registry registration is replaced with a DynamoDB write, documented in the comment. **`_q_policy` indexing bug per Finding 2 affects how this trained model is used downstream.** |
| `run_ope(candidate_regimes, behavior_policy, trajectories, regime)` | `run_ope(candidate_regimes, behavior_policy, trajectories, regime)` | Yes for the multi-estimator structure (DR, self-normalized IS, FQE, method-agreement score), cohort-stratified DR per axis with sample-size minimums, demo-grade sensitivity bound, governance package generation. **Each estimator passes the same `target_policy` lambda that always uses Q[0] per Finding 2, so the OPE evaluates a stationary policy rather than the trained backward-induction policy.** |
| `serve_recommendation(patient_id, regime_id, decision_point_id)` | `serve_recommendation(patient_id, patient_state, regime, q_models, behavior_policy, trajectories, ood_index, patient_profile)` | Yes for the structural pieces (state construction, eligibility evaluation, OOD check via k-NN distance plus propensity floor / ceiling, policy invocation, alternative-actions enumeration with CIs, similar-trajectory retrieval with k-anonymity stub, contraindication check, guideline references, validator-protected narrative). **Cohort features absent from the recommendation record per Finding 1.** The pseudocode's identity-boundary check (`treatment_relationship_check`, `consistency_check`) is omitted; out of scope for the demo, but should at least be flagged as a TODO. |
| `record_action_taken(recommendation_id, action_taken_payload)` | `record_action_taken(recommendation_id, action_taken_payload)` | **Trajectory append step missing per Finding 3; identity-boundary check missing per Finding 6.** The recommendation-record update and the Kinesis emit are both correct; the action-classification logic (`followed_recommendation` / `chose_alternative` / `out_of_catalog`) matches the pseudocode. |
| `run_surveillance(regime_id, surveillance_window)` | `run_surveillance(regime_id, surveillance_window, ope_baseline)` | Yes for the surveillance structure (adherence tracking, outcome-against-baseline drift, cohort-stratified metrics, drift-driven retraining via EventBridge, surveillance-metric persistence, alert generation). **Cohort axes always evaluate to `"unknown"` per Finding 1; the misnamed `observed_reward` variable per Finding 11; Scan-without-pagination per Finding 5.** |

Intentional deviations clearly framed:

- The pseudocode's `Athena.Query(...)` for source data ingestion in Step 1 becomes `generate_synthetic_trajectories(...)` so the demo runs offline. The synthetic generator is well-designed: it intentionally encodes a Spanish-language access disparity in the behavior policy so cohort-stratified OPE has heterogeneity to surface.
- The pseudocode's `SageMaker.CreateTrainingJob(...)` and SageMaker Endpoint inference become in-process scikit-learn fits and predictions. Documented at the function level.
- The pseudocode's `Bedrock.InvokeModel(...)` is wrapped in `_bedrock_invoke_clinician_narrative` and monkey-patched by the demo runner via `globals()` per Finding 7.
- The pseudocode's offline RL, A-learning, and MSM stages are explicit no-op placeholders with `logger.info("TODO: ...")` calls that match the recipe's framing.
- The pseudocode's behavior policy validation includes raising `BehaviorPolicyCalibrationFailure` and `BehaviorPolicyCohortCalibrationFailure`. The Python logs the blocking and returns a result with `calibration_blocking` populated; the recipe text's claim that the demo "logs and continues for illustration; production raises an exception that fails the training cycle" is honored in the comment.

The methodologically central deviation (Finding 2: OPE evaluates a stationary policy at Q[0] instead of the trained backward-induction policy) is the consistency gap that has the largest pedagogical consequence, because it silently produces OPE numbers that don't represent the trained policy.

---

## AWS SDK Accuracy

| API Call | Method | Notes |
|----------|--------|-------|
| DynamoDB GetItem | `_safe_get_item(table, {"recommendation_id": ...})` | Correct. The `_safe_get_item` helper wraps `get_item` in try/except, returning `{}` on failure. Used in `record_action_taken`. The pattern is consistent with 4.9. |
| DynamoDB PutItem | `table.put_item(Item=_to_decimal_dict(...))` | Correct across `regime-catalog`, `trajectory-metadata`, `regime-versions`, `recommendation-records`, `surveillance-metrics`, `surveillance-alerts`. All numeric values flow through `_to_decimal_dict`; bool guards prevent `Decimal(True)`. |
| DynamoDB PutItem with idempotency | `rec_table.put_item(Item=..., ConditionExpression="attribute_not_exists(recommendation_id)")` | Correct in `_persist_recommendation`. The idempotency guard means a Step Functions retry that re-invokes serving with the same `recommendation_id` is a no-op rather than a duplicate. |
| DynamoDB UpdateItem | `rec_table.update_item(Key, UpdateExpression="SET ...", ExpressionAttributeValues=...)` | Correct shape in `record_action_taken`. SET-only expression; no ADD on List attributes (the 4.7 Finding 1 issue is not present). No reserved-word collisions in this file (no `status` field on the update, etc.). |
| DynamoDB Scan | `rec_table.scan()` (in `run_surveillance`) | Functional but the right call is Query per Finding 5. No pagination handling. |
| Bedrock InvokeModel | `bedrock_runtime.invoke_model(modelId=..., body=...)` with `anthropic_version="bedrock-2023-05-31"`, `max_tokens=1500`, `temperature=0.0`, `messages=[{"role": "user", "content": prompt}]` | Correct. Model ID `anthropic.claude-3-5-sonnet-20241022-v2:0` is current; Setup notes the cross-region inference profile caveat. |
| Bedrock response parsing | `payload["content"][0]["text"]` and `re.search(r"\{.*\}", completion, re.DOTALL)` | Correct for Anthropic Messages API on Bedrock. Greedy regex match of the outer JSON object handles Bedrock's tendency to wrap completions in prose. |
| Kinesis PutRecord | `kinesis_client.put_record(StreamName, PartitionKey=..., Data=json.dumps(..., default=str).encode("utf-8"))` | Correct. PartitionKey alternates between `regime_id` (catalog-scoped events: `trajectory_built`, `behavior_policy_estimated`, `regime_trained`, `ope_completed`, `surveillance_completed`) and `patient_id` (patient-scoped events: `recommendation_generated`, `action_taken`, `narrative_validator_fallback`). Choices are reasonable. The bare `try/except: pass` pattern is Finding 8. |
| EventBridge PutEvents | `eventbridge_client.put_events(Entries=[{Source, DetailType, EventBusName, Detail}])` | Correct shape in the drift-triggered retraining path. `Detail` is JSON-serialized; bus name is configured. |
| CloudWatch PutMetricData | `cloudwatch_client.put_metric_data(Namespace, MetricData=[...])` with low-cardinality dimensions | Correct shape in the helper, but the helper is dead code per Finding 9. The helper does correctly filter None-valued dimensions, which would avoid the present-with-None CloudWatch dashboard split flagged in 4.5/4.6/4.7/4.8. |
| S3 PutObject | `s3_client.put_object(Bucket, Key, Body)` | Correct. Bucket constants do not include leading slashes or `s3://` schemes; Body is bytes-encoded. Keys use forward slashes (`{regime_id}/{patient_id}/{trajectory_id}.json`, `{regime_id}/behavior_policy/{version}.json`, `{regime_id}/protocol/protocol_v{...}.json`, `{regime_id}/ope/ope_run_{...}.json`, `{regime_id}/package_{...}.json`, `{recommendation_id}.json`, `{regime_id}/window_{...}.json`) without leading slash. |
| SageMaker | `sagemaker_client` is module-level but only the registry pattern is mentioned in comments; no actual API calls in the demo | The Model Registry pattern is described in the Step 3F comment but implemented as a DynamoDB write. The skip is documented. |

The SDK-level concerns are: Finding 5 (Scan-where-Query-suffices and no pagination), Finding 8 (bare except). All other API surfaces are current and correct.

---

## DynamoDB and Data Type Check

- `_to_decimal` correctly uses `Decimal(str(value))` and short-circuits on already-Decimal inputs.
- `_to_decimal_dict` recursively converts nested dicts and lists, with the `not isinstance(v, bool)` guard so booleans don't flow into Decimal. Lists are walked element-by-element with the same guards.
- `_from_decimal` recursively unwraps Decimals to floats and traverses dict and list containers.
- All `update_item` and `put_item` writes route numerics through `_to_decimal_dict` at the persistence boundary.
- Numeric values (reward weights like `1.0`, `1.5`, `0.8`, `1.0`, `-0.4`; A1c values like `8.4`; eGFR values like `41.0`; comorbidity tier integers; behavior-policy ECE; OPE point estimates and CIs; cohort sample sizes; drift severity) all flow through `_to_decimal_dict` correctly.
- Boolean flags like `censored`, `out_of_catalog`, `ood_flag`, `eligible`, `evaluable`, `k_anonymity_passed` are preserved as Python bool (the bool guard prevents `Decimal(True)`).
- No floats are persisted to DynamoDB. The synthetic trajectory steps include `float(reward)`, `float(state[0])`, etc., that flow through `_to_decimal_dict` if persisted. The demo persists trajectory blobs to S3 (as JSON, not DynamoDB), so the Decimal conversion does not apply there; for the trajectory metadata write that does go to DynamoDB (`current_state`, last index, censoring status, last_updated, trajectory_uri), the `_to_decimal_dict` handles the nested list of floats correctly.
- One consideration: `SAMPLE_REGIME["horizon_decision_points"]` is an int (`4`). After `_to_decimal_dict` and `_from_decimal` round-trip through a DynamoDB read, it becomes a float (`4.0`). The demo doesn't read it back from DynamoDB (it uses the in-memory dict throughout), so this isn't an issue in practice. Worth a comment if production needs int-typed indexing on read-back.

The Decimal discipline is correct. No type-handling bugs.

---

## S3 and Credentials Check

- The example uses S3 in `build_trajectories` (trajectory blob), `estimate_behavior_policy` (behavior-policy metadata), `train_regime` (protocol persist), `run_ope` (OPE results, governance package), `_persist_recommendation` (recommendation archive), and `run_surveillance` (surveillance metrics blob). All are wrapped in `try/except`.
- No leading slashes in the bucket name constants or the S3 key paths.
- No hardcoded credentials. Module-level boto3 clients use the documented environment credential chain.
- The IAM permissions list in Setup matches the API surface used by the code: DynamoDB on the six named tables; S3 on the six named buckets; Bedrock on the named foundation-model ARNs; Kinesis on the dtr-events stream; EventBridge on the dtr-bus; SageMaker Model Registry actions; SageMaker InvokeEndpoint; CloudWatch; Logs.

Pass.

---

## Comment Quality Assessment

Comments consistently explain the "why":

- The Heads-up at the top names every major production gap before the code starts (no real EHR / claims / lab / pharmacy / registry feeds, no real upstream-recipe signal aggregation from Recipes 4.5 through 4.9, no clinically curated regime catalog, no real interaction database integration, no validated reward function, no methodologically rigorous offline RL or A-learning, no SMART on FHIR plan-review surface, no real OOD detector beyond k-NN distance, no federated or consortium estimation, no regulatory analysis).
- The PHI-logging guidance at the module level: *"Never log a raw (patient_id, trajectory_id, state, action, reward) join. The row implicitly identifies the patient, the active condition list, the historical care path, and the recommended next action; the trajectory and recommendation tables are clinical-record-equivalent PHI."*
- The structured-then-narrative discipline framing: *"Off-policy evaluation is the load-bearing inference, not a sanity check. The OPE estimators (doubly-robust, importance sampling, fitted Q evaluation) plus the sensitivity analysis are what produce a value estimate with confidence intervals that the governance committee actually cares about."*
- The four-layer validator framing: *"The four-layer validator from Recipes 4.5 through 4.9 carries forward. Schema and length, fact grounding, prohibited-language patterns, and required content. The regime-narrative-specific prohibited-language patterns are stricter (no policy-as-directive framing, no recommendation language that elides alternatives, no probabilistic claims framed as guarantees, explicit override-encouragement framing required)."*
- The regime-catalog framing: *"The regime catalog is the substrate of the system. State definitions, action catalogs, reward functions, decision-point cadences, eligibility predicates, and model risk tiers are the artifacts the rest of the pipeline operates on."*
- The reward-function rationale documented inline on `SAMPLE_REGIME["reward_function"]["rationale"]`: *"Weights reflect the program's tradeoffs: renal protection is the headline goal (eGFR stabilization weighted highest), with A1c reduction and harm avoidance close behind, and burden as a small but non-zero penalty. Approved by the regime governance committee 2026-03-15."*
- The synthetic generator's intentional encoding of cohort access disparity for the Spanish-language cohort, so OPE has heterogeneity to surface: *"Cohort-driven access disparity: spanish-language patients historically saw less SGLT2 prescribing."* This is a thoughtful pedagogical choice that lets a learner see the Obermeyer-style finding emerge in the cohort-stratified OPE.
- The behavior-policy validation rationale: *"Skip its discipline and the OPE results are not trustworthy."* And the cohort blocking discipline: *"Cohort-specific calibration failure is also a blocker; OPE on a regime trained on miscalibrated importance weights produces misleading equity assessments."*
- The Q-learning backward induction comment: *"For t = T-1, T-2, ..., 0 fit Q_t(s, a) = E[reward_t + V_{t+1}(s')] where V_{t+1}(s') = max_a Q_{t+1}(s', a). At t = T-1 there is no future, so Q is just E[reward_T-1 | s, a]."* The explanation is exactly the standard formulation, accessible to a learner who hasn't seen Q-learning before.
- The OPE method-diversity discipline: *"Method diversity is the discipline; using only one estimator and shipping it produces a regime that has not been cross-validated against the alternative methodological choices. Skip the multi-method approach and the resulting regime is no more reliable than a single-method ML model."*
- The cohort-stratified OPE rationale: *"Cohorts with too few samples are flagged rather than silently dropped."* This is an important pattern for the Obermeyer-style equity work and is correctly enforced via `MIN_COHORT_SAMPLE = 50`.
- The OOD-flag policy explanation: *"The OOD flag is information, not necessarily a stop. The regime risk tier determines whether OOD-flagged patients still receive a recommendation, receive one with explicit warnings, or are blocked."*
- The similar-trajectory retrieval privacy discipline: *"Privacy-aware: the surface returns anonymized summaries rather than raw patient identifiers, and applies a k-anonymity check before sharing individual examples."*
- The opaque-ID rationale in `_make_recommendation_id`: *"NOTE: A PHI-safe id. Production-equivalent guidance: never embed plain-text patient_id, regime_id, decision_point_id, or other structured fields into identifiers that travel in URLs, EHR responses, event payloads, or logs. Use UUIDs or HMAC-SHA256 over the composite with a per-environment secret. Mirror the language flagged in 4.4 through 4.9."*
- The Bedrock de-identification stance in `_redact_for_llm`: *"Strip patient and clinician identifiers from a payload before sending to an LLM. The LLM does not need them, and stripping at the boundary limits any vendor-side logging exposure. Bedrock service terms commit to not training on prompts, but defense-in-depth still applies."*
- The synthetic-data labeling: *"All sample patients, trajectories, actions, narratives, and outcomes in the example are synthetic."*
- The collapse-to-single-file note: *"The example collapses Step Functions, Lambda, EventBridge, SageMaker Endpoints, and Bedrock into a single Python file for readability. In production these are separate workflow stages with their own error handling, IAM, and DLQs."*
- The behavior-policy-floor mitigation in `_doubly_robust_ope` and `_self_normalized_is`: `b_prob = max(float(b_probs[action_idx]), 1e-3)` correctly prevents division-by-zero in the importance weights, though it is not explicitly commented. A brief inline comment naming this as a "behavior policy floor" mitigation would help a learner understand why the clamp is there.

The Gap to Production section is unusually thorough (20+ items spanning methodology validation against randomized-trial benchmarks, multi-method estimator triangulation, sequential target trial emulation, behavior policy validation depth, OPE rigor, cohort-stratified OPE, OOD detection sophistication, reward-function governance, real EHR ingestion, SageMaker Feature Store integration, Model Registry, real interaction database, SMART on FHIR surface, validator extension, Bedrock cost / latency, patient-facing narrative, cross-recipe orchestration, regime deprecation, operational privacy, tracking-ID privacy, Step Functions / DLQ coverage, idempotency, VPC / encryption / audit, synthetic data and testing, FDA SaMD framework, patient consent, clinician engagement, drift-driven retraining, runbooks). The breadth honestly tells the reader how much sits between the recipe and a production deployment.

Calibration is appropriate for a mixed audience.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** Module-level logger comment is explicit. Logger calls in the file mostly stay on the safe side; cohort_features are not logged (and are not even attached to recommendation records per Finding 1, which is its own bug).
- **Synthetic data labeling.** All sample patient IDs (`pat-syn-{i:06d}`, `pat-009315`), conditions, medications, actions, and outcomes are obviously synthetic. The Heads-up section warns explicitly.
- **Eligibility predicates as hard constraints.** Step 5B's `_evaluate_eligibility` returns `not_eligible` outcome with a named failing predicate when any predicate fails; the recommendation record persists the failure rather than silently no-recommendation. Hard constraints, not soft features.
- **Decimal at the DynamoDB boundary.** Consistent. Bool guards prevent boolean-to-Decimal conversion.
- **OOD detection.** The k-NN distance plus propensity floor / ceiling combination is a reasonable demo-grade OOD detector. The threshold constants (`OOD_KNN_DISTANCE_THRESHOLD = 2.0`, `OOD_PROPENSITY_FLOOR = 0.02`, `OOD_PROPENSITY_CEILING = 0.98`) are exposed at the configuration layer for tuning. Production additions are named in the Gap to Production section (density estimation, conformal prediction, per-cohort OOD calibration).
- **Tracking-ID privacy.** All `_make_*_id` functions use UUID-based opaque format (`rec-{uuid.uuid4().hex[:16]}`, `traj-{...}`, `alert-{...}`, `anonymized_{idx:03d}`). The discipline is intentional: patient_id, regime_id, decision_point_id, and clinical content are never embedded in the identifier. The comment in `_make_recommendation_id` explicitly names the discipline.
- **Bedrock de-identification.** `_redact_for_llm` strips patient/clinician identifiers from the payload before LLM calls; `_strip_field` walks the nested dict/list structure recursively. Defense-in-depth pattern even though Bedrock service terms commit to not training on prompts.
- **Cohort-features sensitivity.** The synthetic generator attaches cohort_features to every trajectory step, and OPE correctly slices by them in cohort-stratified OPE. **The cohort-features-on-recommendations issue is Finding 1.** Gap to Production names the SDOH-cohort PHI boundary and the elevated audit posture for regime artifacts.
- **Customer-managed KMS posture.** Documented in Setup and Gap to Production.
- **Validator strictness on policy-as-directive language.** The patient-facing prompt and validator collaboratively avoid recommendation-language patterns; the prohibited list (`\bguaranteed\b`, `\b100%\s+(?:effective|safe)\b`, `\bdefinitely will\b`, `\bnever fail`, `\bmust\s+(?:start|use|prescribe|add|stop)\b`, `\bthe regime requires\b`, `\byou are required to\b`) is reasonable for the regime-narrative use case. The required content layer enforces uncertainty disclosure, regime version, and override-encouragement framing.
- **Structured-then-narrative direction.** The LLM never makes clinical decisions; the structured recommendation record is built deterministically through Step 5A-5G and the LLM only renders narrative on top. The validator's fact-grounding layer (substring heuristic with allow-list, with the same caveat as 4.9 that the heuristic is loose) enforces that the LLM cannot introduce clinical claims absent from the structured recommendation.
- **Templated fallback as respectable artifact.** The `_templated_clinician_narrative` produces a clean, structured presentation that lists the recommendation's elements without LLM narration. The recipe's "Honest Take" section explicitly argues for investing in the templated fallback so the clinical team prefers it to a polished-but-uncertain LLM narrative; the Python honors that.
- **Frozen-at-decision predictions discipline.** The recommendation record persists the recommended action's value, the alternative actions' values, and the OOD detail — the snapshot of what the clinician saw when deciding. Critical for audit and for after-the-fact analysis. **The cohort-features omission per Finding 1 is the single piece missing from this snapshot.**

Pass on healthcare-specific handling, with Finding 1 being the operational gap.

---

## Logical Flow

The file reads top-to-bottom in pedagogical order matching the pseudocode numbering: Setup, Configuration and Constants, Reference Data (synthetic regime catalog, synthetic trajectory generator with intentionally-encoded cohort disparity), Shared Helpers, Step 1 (trajectory build with decision-point identification, state construction, action labeling, reward computation, censoring handling, persistence), Step 2 (behavior policy estimation with overall and cohort-stratified ECE, calibration blocking discipline), Step 3 (Q-learning backward induction with placeholders for offline RL / A-learning / MSM, target trial protocol persistence, SageMaker Model Registry pattern as DynamoDB stub), Step 4 (multi-estimator OPE with DR / IS / FQE, cohort stratification, demo-grade sensitivity, governance package), Step 5 (recommendation serving with eligibility / OOD / policy invocation / similar-trajectory / contraindication / four-layer validator / templated fallback), Step 6 (action capture and surveillance with adherence tracking, drift detection, cohort-stratified surveillance, drift-driven retraining trigger), Putting It All Together, Demo Runner, Gap Between This and Production.

Each step opens with a short italic prose paragraph that restates the pseudocode step before the code block, matching the cookbook's established pattern. The italic paragraphs are slightly heavier on framing than 4.9's, which fits the recipe's higher-stakes content.

The demo runner builds the index patient (Sara from the recipe's opening narrative: 52, T2DM with CKD3b and HTN, currently on metformin / lisinopril / HCTZ / GLP-1, A1c 8.4, eGFR 41, ACR 78). The synthetic patient is well-chosen to exercise the regime's intended use: T2DM-with-CKD makes SGLT2 the renal-protection-favored recommendation, the prior actions on the regime (`["add_glp1", "increase_glp1", "no_change", "no_change"]`) put her in the path-dependent territory the recipe argues for, and the cohort axes are populated for the eligibility flow.

---

## What Is Done Particularly Well

Worth calling out explicitly:

- The structured-then-narrative discipline is enforced rigorously. Steps 1-5A-G build the recommendation record deterministically through eligibility / OOD / policy / similar-trajectory / contraindication; Step 5H only renders narrative on top via Bedrock. The validator's fact-grounding layer (with the same allow-list-extension caveat as 4.9 Finding 1) prevents the LLM from introducing clinical claims. The Honest Take's framing is operationalized in code.
- The synthetic trajectory generator intentionally encodes a Spanish-language access disparity in the behavior policy. This is a thoughtful pedagogical choice: it gives the cohort-stratified OPE in Step 4 something concrete to surface, demonstrating the Obermeyer-style finding the recipe spends substantial space on. Most demo data either avoids the disparity entirely or hand-waves; this one bakes it in deliberately.
- The behavior policy validation discipline is structurally correct: overall ECE, per-cohort ECE with sample-size minimums and insufficient-data flags, blocking enforcement on either failure mode. The recipe says "the behavior-policy estimator is itself a model that requires validation, calibration, and monitoring," and the Python honors it.
- The multi-estimator OPE structure (DR + self-normalized IS + FQE + method agreement + cohort stratification + sensitivity) matches the recipe's "agreement among methods is the trustworthy signal" framing exactly. The method-agreement score is a coarse signal, but the structure is right.
- The propensity floor `max(b_prob, 1e-3)` in the OPE estimators is the right mitigation for the deterministic-target-policy variance problem, though it is not explicitly commented. A learner copying the OPE structure will carry this discipline forward.
- The cohort-stratified OPE's insufficient-data flag (`MIN_COHORT_SAMPLE = 50`) is correctly enforced. Cohorts with too few samples are flagged rather than silently dropped, matching the recipe's discipline that "the honest output reports the wide intervals; the dishonest output reports a point estimate as if it were precise."
- The OOD detector combines two complementary signals (k-NN distance and behavior-policy propensity overlap). The thresholds are exposed at the configuration layer; the detail dict surfaces all three signal values to the recommendation record so the clinician-facing surface can show "why" if the flag fires.
- The similar-trajectory retrieval surface is privacy-aware: anonymized trajectory IDs, k-anonymity threshold (`K_ANONYMITY_THRESHOLD = 5`) named in configuration. The demo collapses the privacy check to a stub but the framing is correct.
- The opaque-ID discipline is consistent across every `_make_*_id` helper. No patient_id, regime_id, decision_point_id, or clinical content is embedded in identifiers.
- The four-layer validator (schema, fact grounding, prohibited-language, required content) is appropriately strict for the regime use case. The required-content layer's check that the regime version disclosure includes the actual version string (`if regime["version"] not in (rvd or "")`) is a nice belt-and-suspenders pattern that catches LLMs that paraphrase the disclosure text.
- The templated fallback is treated as a respectable artifact: it lists the recommendation's structure with the recommended action, value, CI, top alternative, OOD flag, regime version, governance status, and decision-point cadence. The clinical team can read the recommendation even when the LLM narrative is unavailable; the recipe's argument that the templated fallback is better than a polished-but-uncertain LLM narrative is operationalized.
- The behavior-policy reverse-engineering of the Spanish-language access disparity (in the synthetic generator) is at the right level of subtlety: enough to be detectable by cohort-stratified OPE, not so blatant that it dominates the rest of the signal. A learner looking at the generator gets a concrete example of how disparities encoded in historical data manifest in propensity scores and importance weights.
- The Heads-up's enumeration of production gaps is candid: *"no real EHR, claims, lab, pharmacy, or registry feed integration, no real upstream-recipe signal aggregation from Recipes 4.5 through 4.9, no clinically curated regime catalog (the example ships a synthetic diabetes / CKD stepwise-therapy regime), no real interaction database integration, no validated reward function, no methodologically rigorous offline RL or A-learning implementation (Q-learning with gradient-boosted regression is the only estimator), no SMART on FHIR plan-review surface, no real OOD detector beyond a coarse k-NN distance heuristic, no real federated or consortium estimation, no regulatory analysis."*
- The Bedrock model-ID separation by use case (Sonnet for clinician-facing narratives because the prompt is long-context and the validator is strict; Haiku for patient-facing narratives where the cost / latency tradeoff favors the smaller model) is well-tuned for the highest-stakes recipe in the chapter, even though the patient-facing path is not implemented per Finding 10.

---

## Closing Assessment

The teaching content is well-organized and faithful to the main recipe in structure, prose framing, and pedagogical ordering. The six pseudocode steps map onto Python functions with helpers in the right places. The Bedrock + DynamoDB + Kinesis + EventBridge + S3 + SageMaker API call shapes are correct (modulo the Scan/Query and pagination items in Finding 5). The structured-then-narrative discipline is rigorously enforced. The behavior-policy validation, multi-estimator OPE, OOD detection, similar-trajectory retrieval, four-layer validator, and templated fallback are all structurally correct. The opaque-ID discipline is consistent. The synthetic generator's intentional encoding of cohort disparity is a thoughtful pedagogical choice.

The three WARNINGs are localized and well-scoped. Finding 1 (recommendation record lacks `cohort_features`; surveillance always sees one `"unknown"` cohort) silently breaks the cohort-stratified surveillance the recipe describes as non-negotiable; the fix is to add `cohort_features` to the recommendation record at serve time and read from that field in surveillance. Finding 2 (`_q_policy` always uses `q_models[0]` for OPE) silently evaluates a stationary policy at decision point 0 rather than the trained backward-induction policy across the horizon; the fix is to thread the decision-point index through `_q_policy` and the OPE estimators. Finding 3 (`record_action_taken` does not append to the trajectory record) breaks the in-production-trajectories-feed-next-training-cycle feedback loop; the fix is to add the trajectory append step or at minimum add a `# TODO` block naming the gap.

The eight NOTEs are smaller items: the demo-runner print-vs-reality mismatch (chapter pattern), Scan-where-Query-suffices in `run_surveillance` (with no pagination), the missing identity-boundary check in `record_action_taken`, the `globals()` mock-injection pattern without a comment (chapter pattern), the dead `_emit_metric` helper, the unused `PATIENT_NARRATIVE_MODEL_ID` constant, the bare `try/except: pass` patterns around Kinesis emits, and the misleadingly-named `observed_reward` variable in surveillance.

PASS verdict per the persona's rule: no ERRORs, three WARNINGs (the persona threshold is *more* than three, so three is at the boundary but does not trigger FAIL). The three WARNINGs and several NOTEs should be addressed before the recipe ships, because they teach incorrect design patterns to a reader who copies the example into a real deployment, but they do not block the demo from running to completion.

Recipe 4.10 is the recipe in Chapter 4 with the highest clinical stakes and the strictest required discipline. The Python companion mostly honors that, with the three WARNINGs being the residual gaps. Closing them brings the example up to the standard the recipe text claims.

---

## Re-review Checklist

A re-reviewer should verify:

1. **(WARNING)** `serve_recommendation` persists `cohort_features` (race_ethnicity, language, age_band, comorbidity_tier) on the recommendation record at serve time, populated from `patient_profile`. `run_surveillance` reads cohort axis values via `r.get("cohort_features", {}).get(axis, "unknown")` rather than via the non-existent `r["state"]["cohort"][axis]`. Re-running the demo against multiple synthetic patients with different cohort profiles produces non-zero `disparity` values across at least one axis, and a cohort-disparity alert fires when the synthetic generator's encoded Spanish-language access disparity exceeds `COHORT_DISPARITY_ALERT_THRESHOLD`.

2. **(WARNING)** `_q_policy` accepts a `decision_point_index` argument (default 0 for backwards compatibility) and selects `q_models[decision_point_index]` instead of `q_models[0]`. The DR / IS / FQE estimators pass each step's `decision_point_index` into `_q_policy` so the OPE evaluates the trained backward-induction policy. Re-running the demo produces DR / IS / FQE values that differ from the pre-fix values, and the method-agreement score remains high (because all three estimators evaluate the same policy consistently). Alternative acceptable fix: clamp `SAMPLE_REGIME["horizon_decision_points"]` to 1 in the demo so backward induction collapses to a single Q model and the simplification is correct by construction (but this loses pedagogical value).

3. **(WARNING)** `record_action_taken` either appends a new step to the patient's trajectory record (reading the existing blob from S3, appending the post-decision step with `decision_point_index`, `state`, `action`, `recommendation_id`, `followed_regime`, writing back, updating the `trajectory-metadata` pointer), or contains an explicit `# TODO` block at the end of the function naming the missing trajectory-append step and pointing to the production-grade pattern in the Gap to Production section.

4. **(NOTE)** The demo runner's print messages either acknowledge that operations are structural-not-persisted when run offline against unprovisioned tables, or a DynamoDB-Local + Kinesis-Local + S3-mock docker-compose snippet is provided in Setup so the demo can be exercised end-to-end.

5. **(NOTE)** The Scan call in `run_surveillance` is replaced with a `(regime_id, action_recorded_at)` GSI Query with `LastEvaluatedKey` pagination. The GSI is documented in a comment block above the function and in the IAM permissions list in Setup.

6. **(NOTE)** `record_action_taken` either implements an identity-boundary check (validates `action_taken_payload.clinician_id` against `rec.served_to_clinician_id`, with `serve_recommendation` extended to capture `served_to_clinician_id` from the request context), or contains a `# TODO` block naming the omission and pointing to the production wiring.

7. **(NOTE)** The `globals()` mock-injection block carries an explanatory comment matching the pattern from 4.5 / 4.6 / 4.7 / 4.8 / 4.9.

8. **(NOTE)** The `_emit_metric` helper is either wired into the load-bearing observation points (recommendation-served, validator outcome, cohort follow-rate disparity), or removed with a comment in the surveillance section pointing to CloudWatch as a production gap.

9. **(NOTE)** The `PATIENT_NARRATIVE_MODEL_ID` constant is either used (minimal patient-facing narrative function with templated body and a `# TODO` for the actual Bedrock wiring), or removed with the patient-facing path being explicitly out of scope per the Gap to Production section.

10. **(NOTE)** The bare `try/except: pass` patterns around the Kinesis emits are replaced with `try/except Exception as exc: logger.warning(...)` so failures surface during local development.

11. **(NOTE)** The `observed_reward` variable in `run_surveillance` is renamed to `avg_predicted_value` (or similar), with the comment updated to clarify that the demo computes population-level predicted-value drift as a proxy and that real outcome-against-prediction calibration requires production wiring of follow-up labs and adverse-event tracking.

After the WARNING fixes, re-run the demo end-to-end and confirm:
- All six steps execute (already true; the demo runs to completion under the bugs).
- DR / IS / FQE values change to reflect the trained backward-induction policy.
- A cohort-disparity alert fires when the synthetic generator's encoded disparities exceed the threshold.
- The trajectory blob is extended after the action-taken event, or the `# TODO` block is present.
- Print output remains coherent.
