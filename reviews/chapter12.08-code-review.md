# Code Review: Recipe 12.8 - Disease Progression Trajectory Modeling

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter12.08-disease-progression-trajectory-modeling.md` (main recipe with pseudocode)
- `chapter12.08-python-example.md` (Python companion, ~2200 lines)

---

## Verdict: PASS

No ERROR-level findings. One WARNING-level finding (under the FAIL threshold of >3). Several NOTE-level improvements. The code runs end-to-end against the in-memory mocks, the Decimal discipline holds at every DynamoDB write site, every constructed S3 key avoids leading slashes, the inverse-variance-weighted population slope and normal-conjugate per-patient shrinkage are correctly transcribed from the standard Bayesian linear mixed-effects formulation, the Monte Carlo time-to-endpoint simulator propagates uncertainty across the right components (slope, intercept, treatment-effect prior), and the boto3 client/resource constructors plus mock signatures align with current AWS SDK conventions. The single WARNING concerns the counterfactual `_apply_treatment_change` helper not deduping a treatment that the patient is already on, which produces double-counted modifiers in `_treatment_modifier` for the SGLT2 scenario on patients with prior SGLT2 exposure (a real teaching hazard).

---

## Pseudocode-to-Python Mapping

| Step | Pseudocode (main recipe) | Python Function | Status |
|------|--------------------------|-----------------|--------|
| 1 | `define_disease_cohort` (inclusion/exclusion ICD-10, observation-window floor, minimum eGFR count) | `define_disease_cohort` | ✓ |
| 2 | `harmonize_trajectory_data` (canonical LOINC, UCUM units, time-since-diagnosis anchor, acute-vs-chronic tagging, treatment timeline alignment) | `harmonize_patient_trajectory` + `harmonize_cohort` | ✓ |
| 3 | `train_trajectory_model` (population slope from priors + cohort, per-patient deviations, treatment-effect modifiers, temporal-holdout calibration) | `BayesianHierarchicalMixedEffects.fit` + `train_trajectory_model` | ✓ (see N4) |
| 4 | `infer_patient_trajectory` (fitted-trajectory through observed history, forward forecast, time-to-endpoint distribution) | `infer_patient_trajectory` + `infer_all_trajectories` | ✓ |
| 5 | `evaluate_counterfactual_scenarios` (per-scenario forecast, time-to-endpoint, assumption disclosure, write to DynamoDB / S3 / EventBridge / CloudWatch) | `evaluate_counterfactual_scenarios` + `deliver_trajectory_payloads` | ✓ (see W1) |

The Python file's section headers (`## Step 1`, `## Step 2`, etc.) match the main recipe's pseudocode steps in label, function, and order. The five-step preamble in the file's "Heads up" block also matches. No extra steps slipped in, no pseudocode steps got dropped. The shapes of the inputs and outputs (cohort dicts, harmonized records, model artifact, inference results, counterfactual payloads) align across the two files.

---

## Findings

### Issue W1 — WARNING: `_apply_treatment_change` does not dedupe a drug class the patient is already taking, producing double-counted treatment modifiers in `_treatment_modifier`

**Severity:** WARNING
**File:** `chapter12.08-python-example.md`, `_apply_treatment_change` (line 1419) and `BayesianHierarchicalMixedEffects._treatment_modifier` (line 968), exercised in the demo's `start_sglt2_now` scenario

`_apply_treatment_change` blindly appends to `new_timeline` when the change spec is `"add"`:

```python
if "add" in change:
    spec = change["add"]
    new_timeline.append({
        "drug_class":             spec["drug_class"],
        "start_months_from_zero": (anchor_months
                                   + spec.get("start_offset_months", 0)),
        "end_months_from_zero":   None,
    })
```

`_treatment_modifier` then iterates every entry in the timeline and compounds the trial-derived modifier:

```python
def _treatment_modifier(self, treatments, months_from_zero):
    modifier = 1.0
    for tx in treatments:
        if tx["start_months_from_zero"] > months_from_zero:
            continue
        if (tx["end_months_from_zero"] is not None
                and tx["end_months_from_zero"] < months_from_zero):
            continue
        prior = self.trial_priors.get(tx["drug_class"])
        if not prior:
            continue
        modifier *= (1.0 - prior["slope_modifier_mean"])
    return modifier
```

When a patient already on SGLT2 receives the `start_sglt2_now` scenario, the modified timeline ends up with two `sglt2_inhibitor` entries (one from the patient's actual treatment, one from the scenario add). `_treatment_modifier` multiplies through both: `(1 - 0.25) * (1 - 0.25) = 0.5625` instead of the intended `0.75`. The forecast slope at any time after the scenario starts is therefore `0.5625 * baseline_slope` rather than `0.75 * baseline_slope`, a 25% over-attribution of the SGLT2 effect. The Monte Carlo time-to-endpoint inherits the same compounding because it independently samples the per-drug-class modifier and applies it once per timeline entry:

```python
modifier = 1.0
for tx in modified_timeline:
    if tx["start_months_from_zero"] > m:
        continue
    if (tx["end_months_from_zero"] is not None
            and tx["end_months_from_zero"] < m):
        continue
    modifier *= (1.0 - sampled_modifiers.get(tx["drug_class"], 0.0))
```

The synthetic data generator picks `on_sglt2_from_month` from `rng.choice([None, None, None, 24, 36])`, so roughly two-fifths of the demo cohort will hit this path. Inspect the demo's stdout for those patients and the `start_sglt2_now` scenario will show an unrealistically large eGFR improvement relative to `current_continued` because of the double-counting, not because of biology.

The demo guards against the analogous case for tolvaptan inside `run_trajectory_pipeline`:

```python
already_on_tolvaptan = any(
    t["drug_class"] == "tolvaptan" for t in patient["treatments"])
scenarios = scenarios_to_evaluate
if already_on_tolvaptan:
    scenarios = [s for s in scenarios_to_evaluate
                 if s["name"] != "start_tolvaptan_now"]
```

The same protection is not extended to SGLT2 (or to any other class), and the protection lives at the orchestration level rather than inside `_apply_treatment_change` itself. A reader who copies `_apply_treatment_change` into their own pipeline and adds new "start X" scenarios will inherit the bug silently.

This is the kind of teaching hazard the review checklist explicitly calls out: a reader carrying this pattern into production will confidently produce double-counted treatment effects, get a clinical sanity-check failure when a clinician notices the projected SGLT2 benefit is twice the trial-derived size, and have to reverse-engineer where the duplication came from.

**Fix:** Two clean options.

(a) Make `_apply_treatment_change` idempotent on drug-class. Skip the append when the patient is already on the same class (or close out the existing one and start fresh from the anchor):

```python
if "add" in change:
    spec = change["add"]
    new_class = spec["drug_class"]
    already_active = any(
        tx["drug_class"] == new_class
        and tx["start_months_from_zero"] <= anchor_months
        and (tx["end_months_from_zero"] is None
             or tx["end_months_from_zero"] >= anchor_months)
        for tx in new_timeline
    )
    if not already_active:
        new_timeline.append({
            "drug_class":             new_class,
            "start_months_from_zero": (anchor_months
                                       + spec.get("start_offset_months", 0)),
            "end_months_from_zero":   None,
        })
```

(b) Extend the orchestration guard to all "add" scenarios, mirroring the tolvaptan filter:

```python
for scenario in scenarios_to_evaluate:
    add_class = (scenario.get("change") or {}).get("add", {}).get("drug_class")
    if add_class and any(t["drug_class"] == add_class
                         for t in patient["treatments"]):
        continue
    scenarios_for_patient.append(scenario)
```

Option (a) is the more defensive fix and is what production should do. Option (b) is closer to the existing pattern and a smaller diff. Either works; the prose around the scenario filter should also be updated to call out that the production version of `_apply_treatment_change` must reconcile pre-existing treatment with the requested change rather than blindly appending.

---

### Issue N1 — NOTE: `_normal_cdf` is defined but never called

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, line 327

```python
def _normal_cdf(z):
    """Standard normal CDF using the error function approximation."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
```

A grep for `_normal_cdf` returns one match: the definition. The forecasting paths use `pred_mean - z * pred_sd` / `pred_mean + z * pred_sd` with the inverse-CDF z values (`1.282`, `1.645`, `1.96`) hard-coded inline; the calibration check uses the same hard-coded zs. The CDF helper is dead code.

**Fix:** Either delete it (cleanest), or wire it into the calibration computation as a normality check (which is actually informative when the residuals fail the normality assumption). If kept, add a `# Reserved for production calibration metrics; the demo does not use this.` comment so a learner does not chase the apparent gap.

---

### Issue N2 — NOTE: `import statistics` and `from statistics import mean, median, stdev` are unused

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, lines 60 and 65

```python
import statistics
...
from statistics import mean, median, stdev
```

A grep for `statistics.`, `stdev(`, `median(`, and `mean(` (function calls, not the local variable `mean_x` / `mean_y`) returns no usages. Both imports are dead. They suggest to a learner that the demo uses Python's `statistics` module when it does not.

**Fix:** Delete both lines. Pure-Python mean/SD/median are computed inline (`sum(xs) / n`, the residual variance loop, etc.).

---

### Issue N3 — NOTE: Module-level boto3 clients are constructed but never invoked in the demo path

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, lines 96-115

```python
s3_client          = boto3.client("s3", ...)
dynamodb           = boto3.resource("dynamodb", ...)
healthlake_client  = boto3.client("healthlake", ...)
eventbridge_client = boto3.client("events", ...)
cloudwatch_client  = boto3.client("cloudwatch", ...)
sagemaker_runtime  = boto3.client("sagemaker-runtime", ...)
lambda_client      = boto3.client("lambda", ...)
```

`run_demo` injects `MockS3`, `MockTable`, `MockEventBus`, `MockCloudWatch`, `MockHealthLake` into `run_trajectory_pipeline`; the module-level handles are never referenced anywhere in the source after construction. The intent (per the comment block above) is "these are staged so production wiring is a one-line swap." That is reasonable, but a reader scanning the file is left wondering why the clients exist at all if they are never used.

`boto3.client()` does not actually open a network connection at construction time, so this is harmless at runtime. The teaching cost is the confusion. The `dynamodb` resource handle in particular shadows what a learner might expect to be the actual table interface.

**Fix:** Either rename the demo-time mocks so the boto3 handles read more clearly as the production swap target (and add a comment showing the one-line change), or move the boto3 client construction inside a `_get_real_clients()` helper that the production runner calls and the demo bypasses. The current arrangement is workable; the comment block does call it out, but a one-line swap example in a code comment would close the gap.

---

### Issue N4 — NOTE: The "temporal holdout" calibration check uses already-fit per-patient parameters; the metric labels could mislead a learner

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, `BayesianHierarchicalMixedEffects._compute_calibration` (line 1117), called from `fit` (line 1100)

The training loop fits per-patient parameters on the full series:

```python
for pid, ols in per_patient_ols.items():
    ...
    self.per_patient_params[pid] = {
        "slope_mean":     shrunk_mean,
        ...
    }
```

then `_compute_calibration` holds out the last 20% of each patient's series and "predicts" using the already-fit posterior:

```python
n_hold = max(1, int(round(n * holdout_fraction)))
holdout = pdata["series"][-n_hold:]
for (m, v, c) in holdout:
    ...
    pred_mean = (params["intercept_mean"]
                 + params["slope_mean"] * modifier * m)
```

The comment in `fit` is honest about it: `# refit (here, just predict at held-out times using the already-fit per-patient posterior)`. But the resulting numbers get stored as `coverage_50`, `coverage_80`, `coverage_90`, `coverage_95` and surfaced in `summary["calibration"]` and the demo stdout. Without reading the comment a learner would assume those are out-of-sample coverage metrics when they are in-sample. The whole point of the calibration section in the main recipe is "the calibration backtest is not optional"; a demo that labels in-sample numbers as calibration is teaching the opposite of the recipe's main lesson.

**Fix:** Either (a) actually refit on `series[:-n_hold]` per patient (the simplest defensible change, only a few extra lines because the per-patient OLS is already a closed-form computation) and report true held-out coverage; or (b) rename the keys to `pseudo_holdout_coverage_50` / `in_sample_coverage_50` and add a one-line note in the printed output that this is the closed-form sketch's stand-in, not a real backtest. Option (a) is the better teaching move because it shows the reader what real holdout coverage looks like; option (b) is the smaller diff. The Gap to Production section already calls out that the demo's calibration is "one slice" rather than the continuous backtest, but the in-sample-vs-out-of-sample distinction is a separate issue and worth flagging in the code itself.

---

### Issue N5 — NOTE: `_percentile` and the local `_pct` use `len(data)` instead of `len(data) - 1` for the index calculation

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, line 1364 (`_percentile` inside `infer_patient_trajectory`) and line 1573 (`_pct` inside `evaluate_counterfactual_scenarios`)

```python
def _percentile(data, pct):
    if not data:
        return None
    idx = max(0, min(len(data) - 1, int(round(pct / 100.0 * len(data)))))
    return data[idx]
```

For the 50th percentile of a 200-element sorted list, this returns `data[round(0.5 * 200)] = data[100]`, which is technically the 50.5th percentile of the empirical distribution (between elements 99 and 100, 0-indexed). The expected formulation is `int(round(pct / 100.0 * (len(data) - 1)))`, which gives `data[100]` for a 201-element list and `data[99]` for a 200-element list. The off-by-one is a small bias, especially at p10 and p90 with 400 samples (`int(round(0.1 * 400)) = 40` instead of `int(round(0.1 * 399)) = 40` — coincidentally the same here, but for different sample sizes the answers diverge).

The two helpers also duplicate the same logic. A common helper at module scope would be cleaner.

**Fix:** Replace with `int(round(pct / 100.0 * (len(data) - 1)))` and consolidate `_pct` to call `_percentile`. The bias is small for the demo's `num_endpoint_samples=400`, but a learner copying this for a smaller-sample use case (say, 50 posterior draws) would see the bias more clearly.

---

### Issue N6 — NOTE: TKV (LOINC `33914-3`) is declared as a trajectory feature but never generated in synthetic data

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, `ADPKD_COHORT_DEFINITION.trajectory_loincs` (line 189), `LOINC_CATALOG` (line 210), `populate_synthetic_healthlake` (line 542)

The cohort definition declares `33914-3` (Total Kidney Volume) as a trajectory LOINC, and the LOINC catalog defines its canonical unit and clip range. The synthetic data generator emits eGFR (`48642-3`) and SBP (`8480-6`) observations but never emits a TKV observation. The harmonization function silently produces an empty TKV series for every patient, and the model's `primary_outcome_loinc` is `48642-3` so TKV would not affect the fit anyway, but a learner stepping through the data flow may be confused why a declared feature has no data.

The discrepancy shows up most visibly in the demo's stdout, which prints the chronic-vs-acute observation count without breaking it down by LOINC. A reader who expects to see "TKV is present and has been harmonized" gets nothing and has no way to tell whether the absence is a declared-but-unimplemented feature (it is) or a synthetic-data scarcity (also true).

**Fix:** Either (a) add a small TKV-generation block in `populate_synthetic_healthlake` (low frequency, since real-world TKV is annual to biennial; perhaps once every 12-24 months across the patient's history), or (b) drop TKV from `ADPKD_COHORT_DEFINITION.trajectory_loincs` and the `LOINC_CATALOG` so the declared interface matches what the demo actually exercises. Option (a) is the more useful demonstration because real ADPKD trajectory work does use TKV; the multimodal-integration variation in the main recipe explicitly calls this out.

---

### Issue N7 — NOTE: `if end_month else None` collapses `0.0` to `None`

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, `harmonize_patient_trajectory` (line 877)

```python
end_month = None
if med.get("end_dt"):
    end_date = date.fromisoformat(med["end_dt"][:10])
    end_month = (end_date - time_zero_date).days / 30.44
harmonized_treatments.append({
    "drug_class":             drug_class,
    "start_months_from_zero": round(start_month, 2),
    "end_months_from_zero":   round(end_month, 2) if end_month else None,
})
```

The `if end_month else None` test treats `0.0` as falsy. A medication that ended exactly at the diagnosis-date anchor (`end_month == 0.0`) would lose its end-date and become a treatment of indefinite duration. The synthetic data does not exercise this edge case (no medications end on the diagnosis date), but a reader copying this into a real harmonizer that has different time anchors (some real disease anchors land on the diagnosis date for medications that were stopped at diagnosis) would silently drop end dates.

**Fix:** Use the explicit `is not None` test:

```python
"end_months_from_zero":   round(end_month, 2) if end_month is not None else None,
```

The earlier `end_month = None` initialization combined with `if end_month is not None` is the standard Python idiom for "optional numeric." The current form is a small bug-magnet.

---

### Issue N8 — NOTE: The free-function `_forecast_at_time` reaches into the model's `_treatment_modifier` and `trial_priors` directly

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, `_forecast_at_time` (line 1230) and `_treatment_modifier` (line 968)

```python
def _forecast_at_time(model, params, treatments, m_target,
                      treatment_override=None):
    treatments_to_use = treatment_override or treatments
    modifier = model._treatment_modifier(treatments_to_use, m_target)
    ...
    for tx in treatments_to_use:
        ...
        prior = model.trial_priors.get(tx["drug_class"])
```

`_forecast_at_time` lives at module scope and reaches into the model's underscored `_treatment_modifier` method and the `trial_priors` instance attribute. The `_treatment_modifier` underscore signals "private, do not call from outside the class." A reader interpreting the underscore convention is then confused why a free function calls it.

The structure is workable for a demo, but it suggests the boundary between "model object" and "forecasting helpers" should be tighter. A cleaner version would either (a) move `_forecast_at_time` to be a method on `BayesianHierarchicalMixedEffects` (where it has natural access to `self._treatment_modifier` and `self.trial_priors`), or (b) make `_treatment_modifier` a public method (`treatment_modifier`).

**Fix:** Promote `_forecast_at_time` to a model method or rename `_treatment_modifier` to drop the underscore. Either choice is small. The choice between the two depends on whether the helper is conceptually "the model's forecasting method" (then make it a method) or "a free post-processing step" (then make the dependencies public).

---

### Issue N9 — NOTE: The `_treatment_modifier(self, treatments, ...)` call in `_compute_calibration` uses `params["treatments"]` which the demo's per-patient param dict still carries, but the persisted artifact strips them

**Severity:** NOTE
**File:** `chapter12.08-python-example.md`, `train_trajectory_model` (line 1185)

The demo's in-memory per-patient params include `"treatments"` for downstream use:

```python
self.per_patient_params[pid] = {
    "slope_mean":     shrunk_mean,
    ...
    "treatments":     per_patient_series[pid]["treatments"],
}
```

But the artifact serialized to S3 explicitly drops them:

```python
"per_patient_params":  {
    pid: {k: (round(v, 4) if isinstance(v, (int, float)) else v)
          for k, v in params.items()
          if k != "treatments"}
    for pid, params in model.per_patient_params.items()
},
```

If a downstream consumer were to deserialize the artifact and expect to reuse it, they would lose the treatments and `_compute_calibration` (or a future retrofit) would break with a `KeyError` on `params["treatments"]`. The demo never deserializes the artifact, so the inconsistency is invisible at runtime, but the artifact-vs-runtime divergence is a foot-gun.

**Fix:** Either persist the treatments in the artifact (the harmonized record already lives in S3 and the artifact does not need to duplicate them; just include the patient_id so the consumer can rejoin), or surface this in a comment near the artifact write so a future reader knows the artifact alone is not a full state restore. The Gap to Production section already says "production has full posterior samples" and "production stores the full state," so this is consistent with the demo-vs-production framing, but a comment at the write site would catch the foot-gun.

---

## What was checked

- Pseudocode-to-Python mapping across all 5 steps (cohort → harmonize → train → infer → counterfactual)
- boto3 method names and parameter names (`s3.put_object(Bucket=, Key=, Body=)`, `dynamodb.batch_writer().put_item(Item=)`, `events.put_events(Entries=)`, `cloudwatch.put_metric_data(Namespace=, MetricData=)`) against current AWS SDK
- DynamoDB Decimal discipline: every write site (`bw.put_item(Item=...)`) passes numeric values through `_to_decimal` which uses `Decimal(str(...))` to avoid float precision artifacts; bool short-circuit handles the bool-is-int subtlety; None passthrough is appropriate
- S3 key construction: every constructed key (`f"cohorts/{name}/{version}/cohort.json"`, `f"cohorts/.../harmonized/{patient_id}.json"`, `f"models/{name}/{model_version}/{prior_version}/artifact.json"`, `f"forecasts/{name}/{patient_id}/{date}.json"`, `f"counterfactuals/adpkd/{patient_id}/{ts}.json"`) starts with a non-slash character — no leading-slash bug
- EventBridge `Time` field uses `datetime.now(timezone.utc)` (correct: boto3 serializes the datetime object itself)
- CloudWatch `Value` field is a Python `float` (correct: CloudWatch accepts float, unlike DynamoDB)
- Bayesian linear mixed-effects math: inverse-variance-weighted population slope, normal-conjugate update with literature prior, per-patient shrinkage via `1/var = 1/prior_var + 1/obs_var`, residual variance estimation with `n-2` degrees of freedom — all consistent with the standard derivation
- Variance propagation in `_forecast_at_time`: slope variance scaled by `(modifier * t)^2`, intercept variance, observation noise, and trial-prior modifier variance via `(prior_sd * slope_mean * t)^2` are all the right Jacobian-times-input-variance contributions for the linear model `y = intercept + slope * modifier * t + noise`
- Monte Carlo time-to-endpoint: per-draw sampling of slope, intercept, and per-class modifier from their posteriors (or the prior for unmodeled classes), per-step trajectory walk with first-crossing detection, percentile aggregation
- Treatment timeline filtering in `_treatment_modifier`: start time before query time, end time after query time (handles `None` end times correctly)
- Synthetic data consistency: the generator's effective slope adjustments (×0.90 for ACEi/ARB, ×0.75 for SGLT2, ×0.70 for tolvaptan) match the trial-derived `slope_modifier_mean` values (0.10, 0.25, 0.30), so the model can in principle recover the priors from the data
- Acute-vs-chronic filtering: synthetic data injects two inpatient eGFR values per patient with `encounter_class="inpatient"`, harmonization tags them as `"acute"`, training and inference filter to `"chronic"` only
- LOINC and UCUM passthrough: synthetic data uses `"mL/min/1.73m2"` for eGFR and `"mmHg"` for SBP, which match the canonical units in `LOINC_CATALOG`, so `_convert_units` is a no-op (the demo acknowledges this and points to the production conversion table)
- Cohort qualification: inclusion ICD-10 from `["Q61.2", "Q61.3"]`, exclusion from `["Q61.4", "Q61.5", "Z94.0"]`, minimum 24 month observation window, minimum 6 chronic eGFR measurements; demo's synthetic-data parameters (3-9 year history, ~3-month eGFR cadence) qualify essentially all 14 generated patients
- Versioning: every surfaced record carries `cohort_definition_version`, `model_version`, `trial_prior_version`, `pipeline_version`; DynamoDB sort key `disease#model_version#generated_at#scenario_name` supports the audit-trail recall requirements

---

## Notes for next iteration

If the recipe ever expands to multiple disease cohorts in one pipeline run (CKD plus ADPKD plus IPF), the W1 dedup issue compounds across the orchestration: each disease's scenario set may need different "skip if already on" rules, and putting the dedup inside `_apply_treatment_change` becomes the only sane place for it.

The N4 calibration note becomes more important if the recipe ever grows the calibration-drift-monitor variation. A learner who took the in-sample number at face value and then built a "real" backtest expecting the same coverage would see a sudden drop and spend time chasing a model bug instead of recognizing the original metric was always optimistic.

The Gap to Production section already calls out joint models, real PyMC/Stan/NumPyro replacement, calibration-drift monitoring, equity audits, and EHR integration. Those are correctly scoped as production gaps, not findings against the demo.
