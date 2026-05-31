# Code Review: Recipe 6.4

## Summary

The Python companion for Disease Severity Stratification is excellent. It faithfully implements all pseudocode steps from the main recipe, uses correct scikit-learn and boto3 APIs, properly handles DynamoDB Decimal requirements, avoids leading slashes in S3 keys, and builds understanding progressively from configuration through clustering to operationalization. The synthetic data generator is well-designed with realistic clinical distributions that let readers run the full pipeline without real PHI.

One minor issue with the `to_parquet()` call and one pedagogical note about the key drivers computation. Neither prevents the code from running correctly.

---

## Issues

### Issue 1: to_parquet() Without Engine May Fail on Some Installations

- **File:** Python companion (`chapter06.04-python-example.md`)
- **Location:** Step 8, `upload_results_to_s3()` function
- **Severity:** WARNING (may fail depending on reader's environment)
- **Description:** The code calls `results_df.to_parquet(index=False)` to get bytes, then passes the result to `s3_client.put_object(Body=parquet_buffer)`. This works correctly in pandas 1.2+ when `pyarrow` is installed (the default engine). However, the `pip install` line at the top only lists `boto3 pandas numpy scikit-learn`. A reader who doesn't have `pyarrow` installed will get a `ModuleNotFoundError` at this line with no indication of what's missing. The error message from pandas is not always clear about which parquet engine is needed.
- **Suggested fix:** Add `pyarrow` to the pip install line: `pip install boto3 pandas numpy scikit-learn pyarrow`. Alternatively, add a comment above the `to_parquet()` call noting the pyarrow dependency.

### Issue 2: Key Drivers Use Weighted Z-Scores But Comment Says "Z-Scores"

- **File:** Python companion (`chapter06.04-python-example.md`)
- **Location:** Step 6, `compute_key_drivers()` function
- **Severity:** NOTE (slightly misleading but not incorrect)
- **Description:** The function receives the `normalized` matrix, which at this point has already had clinical weights applied (from Step 2). So the values being sorted by absolute magnitude are actually weighted z-scores, not raw z-scores. The docstring says "We use z-scores as a proxy" and the returned dict labels the field `"z_score"`. This is technically inaccurate since a feature with weight 1.5 will appear more extreme than its true z-score. A patient with a raw z-score of 1.0 on `complication_count` will show as 1.5 in the output. This could confuse a reader who expects z-scores to represent standard deviations from the mean.
- **Suggested fix:** Either (a) rename the field to `"weighted_z_score"` and update the docstring to say "weighted z-scores," or (b) pass the unweighted normalized matrix to this function and apply weights only for the clustering step. Option (a) is simpler and preserves the current logic.

### Issue 3: Feature Set Mismatch Between Pseudocode and Python

- **File:** Python companion (`chapter06.04-python-example.md`)
- **Location:** Configuration section, `FEATURE_COLUMNS`
- **Severity:** NOTE (acceptable simplification, but worth documenting)
- **Description:** The main recipe's pseudocode defines a feature set that includes `pct_time_above_target` (percentage of HbA1c readings above 7.0). The Python companion omits this feature and doesn't include it in `FEATURE_COLUMNS`. This is a reasonable simplification for the teaching example (the synthetic data generator would need CGM-like data to produce this), but the divergence is not called out anywhere. A reader comparing the two files might wonder if they missed something.
- **Suggested fix:** Add a brief comment in the `FEATURE_COLUMNS` section noting that `pct_time_above_target` from the pseudocode is omitted because it requires continuous glucose monitoring data that's harder to synthesize realistically.

---

## Pseudocode vs. Python Consistency

The Python implementation follows the main recipe's pseudocode closely with appropriate simplifications for a teaching context:

**Step 1 (Feature Assembly):** Pseudocode describes a Glue ETL job pulling from multiple source systems. Python generates synthetic data. This is explicitly acknowledged in the code and is the correct approach for a runnable example.

**Step 2 (Preprocess):** Python matches pseudocode exactly: z-score normalization, median imputation for continuous features, 0 imputation for binary features, clinical weight application. The zero-std-dev guard from the pseudocode is not explicitly present in the Python (StandardScaler handles it by producing 0/NaN), but with synthetic data this edge case won't trigger.

**Step 3 (Clustering):** Python matches pseudocode: K-Means with multiple K values, silhouette scoring, inertia tracking. Parameters align (n_init=10, max_iter=300, random_seed=42).

**Step 4 (Validate and Label):** Python implements tier profiling and severity-based reordering. The pseudocode includes an outcome validation step (checking hospitalization rates per tier) that the Python omits. This is acceptable since synthetic data has no real outcomes to validate against.

**Step 5 (Clinical Labels):** Python provides pre-defined label sets for K=3,4,5 matching the pseudocode's approach.

**Step 6 (Store):** Python matches pseudocode's DynamoDB storage pattern including key_drivers, expires_at, and S3 upload. The key_drivers computation is an addition that implements the pseudocode's "top 3 features with highest z-scores" specification.

---

## AWS SDK Accuracy

- `boto3.resource("dynamodb")` / `dynamodb.Table(name)`: Correct resource-level API usage.
- `table.batch_writer()`: Correct. Handles batching into groups of 25 and retries unprocessed items automatically.
- `batch.put_item(Item=record)`: Correct method and parameter name for batch_writer context.
- `s3_client.put_object(Bucket, Key, Body, ServerSideEncryption)`: Correct parameters. `ServerSideEncryption="aws:kms"` is valid.
- S3 key `f"{S3_OUTPUT_PREFIX}/{run_date}/results.parquet"`: No leading slash. Correct.
- DynamoDB Decimal usage: All float values in `key_drivers` are wrapped with `Decimal(str(...))`. The `tier_numeric` field is stored as `int`, which is fine (boto3 handles int correctly, only float is rejected). Correct.

---

## Comment Quality

Comments are consistently strong. Highlights:

- The configuration section explains why weights exist and what different weight values mean (1.0 = as-is, 1.5 = 50% more influence). This is exactly what a learner needs.
- The `preprocess_features` docstring explains why normalization matters with a concrete example (HbA1c vs ER visits scale difference).
- The `run_clustering` function explains what silhouette score measures and why it's comparable across K values while inertia is not.
- The `select_and_profile` function explains why raw feature averages (not z-scores) are shown to clinicians.
- The gap-to-production section is thorough and covers equity auditing, tier migration, refresh orchestration, and VPC requirements.

---

## Logical Flow

The code builds understanding progressively:

1. Configuration (what are we clustering and why these features)
2. Data generation (what does the input look like)
3. Preprocessing (why normalization and weighting matter)
4. Clustering (the algorithm itself, kept simple)
5. Selection and profiling (interpreting results clinically)
6. Labeling (making results actionable)
7. Explainability (why each patient is in their tier)
8. Storage (operationalizing for downstream systems)

This ordering is pedagogically sound. Each step depends only on prior steps, and the orchestration function at the end ties everything together with print statements that show progress.

---

## Verdict

- [x] Ready as-is
- [ ] Needs minor fixes (list them)
- [ ] Needs significant rework

**PASS** (1 WARNING, 2 NOTEs)

**Recommended fix:**
1. Add `pyarrow` to the pip install dependencies to prevent confusing import errors when running the parquet export step.

**Optional improvements:**
2. Clarify that key_drivers reports weighted z-scores, not raw z-scores, to avoid confusion about the magnitude of reported values.
3. Add a comment noting the `pct_time_above_target` feature from the pseudocode was intentionally omitted from the Python example.
