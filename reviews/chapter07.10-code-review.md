# Code Review: Recipe 7.10 - Optimal Intervention Timing Prediction

**Reviewed:** `chapter07.10-python-example.md`
**Against:** `chapter07.10-optimal-intervention-timing-prediction.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and faithfully implements the main recipe's pseudocode steps. The code would run without errors given the stated prerequisites, DynamoDB values correctly use Decimal, and boto3 API calls (in the commented SageMaker integration point) use correct method names and parameters. The temporal feature engineering is clinically reasonable, the intervention window scoring logic matches the pseudocode, and the "Gap to Production" section is thorough and honest. Two WARNINGs and three NOTEs identified below.

---

## Findings

### WARNING 1: Pseudocode slope threshold mismatch in intervention scoring

**Location:** `chapter07.10-python-example.md`, Step 4, `score_intervention_window()` function

The main recipe's pseudocode uses `hazard_slope > 0.01` for Case 1 (rising risk with peak ahead) and `hazard_slope < 0.005` for Case 3 (flat high risk). The Python companion uses `hazard_slope > 0.001` for Case 1 and `abs(hazard_slope) < 0.0005` for Case 3. These are order-of-magnitude differences.

While the Python code's thresholds are internally consistent with its simplified hazard model (which produces smaller slope values than a trained neural network would), the discrepancy is unexplained. A reader comparing the pseudocode to the Python implementation would wonder whether the thresholds are wrong or intentionally different.

**Fix:** Add a comment in the Python code explaining the threshold difference: "Thresholds are lower than the main recipe's pseudocode because our simplified hazard model produces smaller absolute slope values. In production with a trained survival model, use the thresholds from the main recipe and calibrate against your model's output distribution."

---

### WARNING 2: `store_recommendation` sets `action_window_days` to `None` without DynamoDB handling

**Location:** `chapter07.10-python-example.md`, Step 6, `store_recommendation()` function

```python
"action_window_days": recommendation.get("action_window_days"),
```

When `recommended_action` is `"monitor"`, `action_window_days` is `None`. DynamoDB does not accept `None` as an attribute value in `put_item`. The boto3 DynamoDB resource layer will raise `TypeError: Unsupported dynamodb type: <class 'NoneType'>` unless the table has been configured with a type serializer that strips None values, or the code explicitly omits the key.

This would fail if a "monitor" patient's record were stored (though in the current pipeline flow, only actionable recommendations reach `store_recommendation`). A learner adapting this pattern to store all scored patients would hit this error.

**Fix:** Either conditionally include `action_window_days` only when not None, or use a DynamoDB-compatible sentinel value:
```python
"action_window_days": recommendation.get("action_window_days") or 0,
```
Or filter None values before put_item:
```python
record = {k: v for k, v in record.items() if v is not None}
```

---

### NOTE 1: `generate_synthetic_timeline` uses `hash()` for seeding which is non-deterministic across Python sessions

**Location:** `chapter07.10-python-example.md`, Step 1, `generate_synthetic_timeline()` function

```python
np.random.seed(hash(patient_id) % 2**32)
```

Python's `hash()` is randomized by default (PYTHONHASHSEED) since Python 3.3. This means the synthetic data will differ between runs unless the user sets `PYTHONHASHSEED=0`. For a teaching example where reproducibility helps learners verify their output matches expected results, this is a minor issue.

**Fix:** Use a deterministic hash like `int(hashlib.md5(patient_id.encode()).hexdigest(), 16) % 2**32` or simply use sequential integer seeds. Add a comment noting the reproducibility consideration.

---

### NOTE 2: Pseudocode Step 5 `generate_explanation` references SHAP values/attention weights not present in Python

**Location:** `chapter07.10-python-example.md`, Step 5, `generate_explanation()` function

The main recipe's pseudocode includes:
```
top_drivers = get top 3 feature contributors for this patient
```
referencing "model's attention weights or SHAP values." The Python companion instead derives explanations directly from the feature values (A1C level, medication gap days, encounter recency). This is a reasonable simplification since the Python example uses a heuristic model rather than a trained neural network, but the structural difference from the pseudocode isn't called out.

**Fix:** Add a brief comment: "In production with a trained model, you'd use SHAP values or attention weights to identify the top contributing features. Here we use the raw feature values directly since our simplified model doesn't produce interpretability artifacts."

---

### NOTE 3: The `run_intervention_timing_pipeline` demo prints clinical feature values to stdout

**Location:** `chapter07.10-python-example.md`, "Putting It All Together" section

```python
print(f"  Features: A1C={features.get('a1c_current')}, "
      f"med_gap={features.get('med_gap_days')}d, "
      f"slope={features.get('a1c_slope_per_day')}")
```

The "Gap to Production" section correctly warns against logging PHI, but the demo code itself prints clinical values (A1C, medication gaps) to stdout. While this is synthetic data in a demo context, it establishes a pattern a learner might carry into production. The code's own later section says "Never log the clinical features themselves (A1C values, medication names, diagnosis codes). Those are PHI."

**Fix:** Add an inline comment on the print statement: "# Demo only. In production, never log clinical feature values. Log only patient_id, scores, and actions."

---

## Summary

This is a strong Python companion. The code is well-organized, builds understanding progressively from data assembly through scoring to delivery, and the inline comments consistently explain "why" rather than just "what." The synthetic data generation is clever and produces realistic timeline shapes that demonstrate different intervention timing scenarios effectively.

Key strengths:
- DynamoDB `Decimal` handling is correct for all top-level numeric fields
- The SageMaker integration point is clearly marked with correct `invoke_endpoint` API usage (`EndpointName`, `ContentType`, `Body` parameters, `response["Body"].read()` parsing)
- No S3 paths with leading slashes
- The "Gap to Production" section is comprehensive and honest about the distance between demo and deployment
- Feature engineering faithfully implements the pseudocode's temporal dynamics (recency, velocity, acceleration, gaps)
- The intervention window scoring logic correctly implements the three cases from the pseudocode with appropriate clinical reasoning

The two WARNINGs are minor: one is a documentation gap (threshold differences unexplained) and the other is a DynamoDB edge case that only manifests if the code is adapted beyond its current usage pattern. Neither would prevent a learner from running the example successfully as written.

---

*Reviewed 2026-05-31. Verdict: PASS (0 ERRORs, 2 WARNINGs, 3 NOTEs)*
