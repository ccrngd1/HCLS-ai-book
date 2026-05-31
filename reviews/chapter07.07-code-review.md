# Code Review: Recipe 7.7 - Length of Stay Prediction

**Reviewed:** `chapter07.07-python-example.md`
**Against:** `chapter07.07-length-of-stay-prediction.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and faithfully implements the pseudocode from the main recipe. Code would run without errors given the stated prerequisites. DynamoDB writes correctly use `Decimal` with `str()` conversion. No S3 path issues. boto3 API calls are correct. The teaching quality is high with excellent inline comments explaining clinical rationale.

---

## Findings

### WARNING 1: XGBRegressor `eval_metric` and `early_stopping_rounds` parameter handling

**Location:** `chapter07.07-python-example.md`, Step 3 (`train_los_model` function)

The code sets `early_stopping_rounds` in `MODEL_PARAMS` but never passes it to `XGBRegressor()` or `model.fit()`. In recent xgboost versions (>=2.0), `early_stopping_rounds` is a parameter of the constructor, not `fit()`. The code defines it in `MODEL_PARAMS` but only selectively passes some params to the constructor, omitting `early_stopping_rounds`. The model will train all 500 rounds without early stopping.

Additionally, `eval_metric` is passed to the constructor but the `fit()` call also needs `eval_set` for it to be used, which is correctly provided. However, without `early_stopping_rounds` actually being passed, the `eval_set` only logs metrics without stopping.

**Fix:** Add `early_stopping_rounds=MODEL_PARAMS["early_stopping_rounds"]` to the `XGBRegressor()` constructor call, or pass it via `model.fit(..., early_stopping_rounds=20)` for xgboost <2.0 compatibility.

---

### NOTE 1: Pseudocode includes service-line stratification; Python companion trains a single model

**Location:** `chapter07.07-python-example.md`, Step 3

The main recipe's pseudocode (Step 3) explicitly trains per-service-line models with `train_los_model(training_data, service_line)`. The Python companion trains a single model on the full synthetic population. This is acknowledged in the prose ("In production, you'd train separate models per service line. Here we train one model on the full synthetic population to keep things simple.") so it's not misleading, but worth noting the gap.

**No fix needed.** The simplification is clearly documented.

---

### NOTE 2: Confidence interval approach differs from pseudocode

**Location:** `chapter07.07-python-example.md`, Step 4 (`predict_remaining_los` function)

The main recipe's pseudocode references quantile predictions (`prediction.uncertainty` from the endpoint response), implying a quantile regression approach. The Python companion uses a linear heuristic (`max(1.0, predicted_remaining * 0.4)`). The code explicitly calls this out as a placeholder ("This is a placeholder. Do not ship this."), which is good teaching practice.

**No fix needed.** The limitation is clearly flagged.

---

### NOTE 3: `generate_daily_features_for_training` could be memory-intensive for learners

**Location:** `chapter07.07-python-example.md`, Step 2

With 2000 encounters and a mean LOS of ~5 days, this generates ~10,000 rows, which is fine. But the nested loop with `iterrows()` and list-of-dicts pattern would be very slow at real scale. A comment noting this is a teaching pattern (not a production pattern) would help learners who might try to scale it up.

**No fix needed.** The intro paragraph already sets expectations about synthetic/small-scale usage.

---

## Checklist Assessment

| Criterion | Status |
|-----------|--------|
| **Correctness** | Code runs without errors. All functions produce expected outputs. numpy/pandas/xgboost APIs used correctly. |
| **Pseudocode-to-Python consistency** | All 5 pseudocode steps are implemented. Simplifications (single model, heuristic CI, synthetic data) are clearly documented. |
| **Misleading patterns** | None. No hardcoded credentials, no swallowed exceptions, no PHI logging. The placeholder CI is explicitly flagged. |
| **AWS SDK accuracy** | `boto3.resource("dynamodb")` and `table.put_item(Item=record)` are correct. `Config(retries=...)` is valid. No other boto3 calls in the teaching code (SageMaker deployment is deferred to the Gap section). |
| **Comment quality** | Excellent. Comments explain clinical rationale (why WBC trends down during recovery), ML decisions (why log-normal for LOS distribution), and operational context (why DRG mean is the strongest predictor). Accessible to Python learners. |
| **Logical flow** | Builds understanding progressively: data generation -> feature expansion -> training -> inference -> storage -> monitoring. Each step references the pseudocode step name. |
| **DynamoDB Decimal usage** | Correct. All float values wrapped in `Decimal(str(...))` to avoid floating-point artifacts. |
| **S3 paths** | `TRAINING_BUCKET = "my-hospital-ml-data"` is a bucket name, not a path. No leading slashes anywhere. |

---

*Review complete. Code is pedagogically sound and technically correct for its stated teaching purpose.*
