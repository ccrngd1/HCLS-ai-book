# Recipe 6.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 6.3. It shows one way you could translate payer mix financial risk clustering into working Python code. It is not production-ready. There's no error handling, no retry logic, no input validation. Think of it as the whiteboard sketch: useful for understanding the shape of the solution, not something you'd deploy against your actual patient population on Monday morning. Consider it a starting point, not a destination.
>
> This example uses SageMaker Processing Jobs with scikit-learn rather than SageMaker's built-in K-Means algorithm. For populations under 500K patients, scikit-learn is simpler and more flexible. The built-in algorithm is better when you're clustering millions of records and need distributed compute.

---

## Setup

You'll need the AWS SDK for Python and scikit-learn:

```bash
pip install boto3 pandas numpy scikit-learn pyarrow
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`
- `s3:PutObject`
- `sagemaker:CreateProcessingJob`
- `sagemaker:DescribeProcessingJob`
- `athena:StartQueryExecution`
- `athena:GetQueryResults`
- `sns:Publish`

For the SageMaker Processing Job, you'll also need a SageMaker execution role with S3 access. That's a separate IAM role from the one running this script.

---

## Configuration and Constants

Everything that's really configuration rather than logic lives here. The feature definitions, payer encodings, and thresholds are the pieces that change between organizations. Treat them as configuration you version-control, not magic numbers buried in functions.

```python
import logging
import json
import datetime
from datetime import timezone

import boto3
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Feature Configuration ---

# The features we'll use for clustering. Each maps to a column in the
# patient feature matrix. Order matters: it determines column order in
# the numpy array passed to K-Means.
FEATURE_COLUMNS = [
    "payer_ordinal",
    "payment_ratio",
    "write_off_ratio",
    "avg_days_to_pay",
    "utilization_intensity",
    "ed_proportion",
    "avg_complexity",
    "no_show_rate",
    "coverage_changes_24mo",
    "deductible_amount",
    "collections_count",
    "charity_app_count",
]

# Payer type ordinal encoding. Higher = generally better reimbursement.
# This is a simplification. In reality, a Medicaid managed care plan
# might reimburse better than a high-deductible commercial plan for
# certain services. But as a clustering feature, this ordinal captures
# the broad financial ordering that matters for segmentation.
PAYER_ENCODING = {
    "commercial": 4,
    "medicare": 3,
    "medicaid": 2,
    "self_pay": 1,
}

# Range of k values to evaluate. Start at 3 (fewer is just rediscovering
# payer categories) and stop at 8 (more is too granular to operationalize).
K_RANGE = range(3, 9)

# Population shift detection threshold (percentage points).
# A shift of 5+ pp in any cluster between runs triggers an alert.
SHIFT_THRESHOLD_PP = 5.0

# S3 paths for the pipeline artifacts.
S3_BUCKET = "my-health-system-analytics"
S3_PREFIX_FEATURES = "payer-risk-clustering/features/"
S3_PREFIX_RESULTS = "payer-risk-clustering/results/"
S3_PREFIX_HISTORY = "payer-risk-clustering/history/"

# SNS topic for shift alerts.
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:payer-risk-alerts"
```

---

## Step 1: Generate Synthetic Patient Data

*The pseudocode calls this `extract_patient_financial_data(date_range)`. In production, this step pulls from your billing system, EHR, and eligibility feeds via Glue ETL. Here we generate synthetic data that mimics the statistical properties of a real patient population. No real PHI is used or needed for development.*

```python
def generate_synthetic_patients(n_patients: int = 5000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic patient financial data for clustering development.

    The distributions here are loosely based on published healthcare
    utilization statistics. They're realistic enough to produce meaningful
    clusters but are NOT derived from any actual patient data.

    In production, replace this entire function with your Glue ETL job
    that joins billing, EHR, and eligibility data.

    Args:
        n_patients: Number of synthetic patients to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with one row per patient and columns matching the
        raw data you'd get from source system extracts.
    """
    # TODO (TechWriter): Code review Issue 1 (WARNING). The iterrows/loc pattern below
    # is correct but extremely slow (~35K individual cell assignments for 5K patients).
    # Consider vectorizing with boolean masks per payer type, or at minimum add a
    # prominent comment warning readers not to copy this pattern for large populations.
    rng = np.random.default_rng(seed)

    # Assign payer types with a realistic distribution.
    # National averages: ~50% commercial, ~20% Medicare, ~20% Medicaid, ~10% self-pay.
    # Your system's mix will differ. That's fine; the clustering adapts.
    payer_types = rng.choice(
        ["commercial", "medicare", "medicaid", "self_pay"],
        size=n_patients,
        p=[0.48, 0.22, 0.20, 0.10],
    )

    patients = pd.DataFrame({"patient_id": range(1, n_patients + 1), "payer_type": payer_types})

    # Generate financial and utilization features conditioned on payer type.
    # Each payer segment has different statistical properties. This conditioning
    # is what makes the synthetic data produce realistic clusters.
    for idx, row in patients.iterrows():
        payer = row["payer_type"]

        if payer == "commercial":
            # Commercial patients: generally good payment, moderate utilization.
            # But with a subgroup of HDHP patients who struggle with patient responsibility.
            is_hdhp = rng.random() < 0.35  # 35% of commercial are high-deductible
            if is_hdhp:
                patients.loc[idx, "payment_ratio"] = rng.beta(3, 4)  # skewed lower
                patients.loc[idx, "avg_days_to_pay"] = rng.gamma(8, 8)  # longer
                patients.loc[idx, "deductible_amount"] = rng.uniform(3000, 8000)
                patients.loc[idx, "write_off_ratio"] = rng.beta(2, 8)
            else:
                patients.loc[idx, "payment_ratio"] = rng.beta(8, 2)  # skewed higher
                patients.loc[idx, "avg_days_to_pay"] = rng.gamma(3, 5)
                patients.loc[idx, "deductible_amount"] = rng.uniform(250, 2000)
                patients.loc[idx, "write_off_ratio"] = rng.beta(1, 20)
            patients.loc[idx, "utilization_intensity"] = rng.gamma(2, 1.5)
            patients.loc[idx, "ed_proportion"] = rng.beta(1, 10)
            patients.loc[idx, "coverage_changes_24mo"] = rng.poisson(0.3)

        elif payer == "medicare":
            # Medicare: reliable payer, higher utilization, older population.
            patients.loc[idx, "payment_ratio"] = rng.beta(7, 2)
            patients.loc[idx, "avg_days_to_pay"] = rng.gamma(4, 7)
            patients.loc[idx, "deductible_amount"] = rng.uniform(200, 500)
            patients.loc[idx, "write_off_ratio"] = rng.beta(1, 15)
            patients.loc[idx, "utilization_intensity"] = rng.gamma(4, 1.5)
            patients.loc[idx, "ed_proportion"] = rng.beta(2, 8)
            patients.loc[idx, "coverage_changes_24mo"] = rng.poisson(0.1)

        elif payer == "medicaid":
            # Medicaid: variable payment, higher ED use, coverage instability.
            patients.loc[idx, "payment_ratio"] = rng.beta(4, 3)
            patients.loc[idx, "avg_days_to_pay"] = rng.gamma(5, 8)
            patients.loc[idx, "deductible_amount"] = rng.uniform(0, 100)
            patients.loc[idx, "write_off_ratio"] = rng.beta(2, 10)
            patients.loc[idx, "utilization_intensity"] = rng.gamma(3, 2)
            patients.loc[idx, "ed_proportion"] = rng.beta(3, 7)
            patients.loc[idx, "coverage_changes_24mo"] = rng.poisson(1.2)

        else:  # self_pay
            # Self-pay: lowest payment rates, highest write-offs, coverage churn.
            patients.loc[idx, "payment_ratio"] = rng.beta(2, 5)
            patients.loc[idx, "avg_days_to_pay"] = rng.gamma(10, 10)
            patients.loc[idx, "deductible_amount"] = 0.0  # no insurance, no deductible
            patients.loc[idx, "write_off_ratio"] = rng.beta(4, 5)
            patients.loc[idx, "utilization_intensity"] = rng.gamma(1.5, 2)
            patients.loc[idx, "ed_proportion"] = rng.beta(4, 6)
            patients.loc[idx, "coverage_changes_24mo"] = rng.poisson(2.0)

    # Features that are less payer-dependent.
    patients["avg_complexity"] = rng.gamma(2, 1, size=n_patients)
    patients["no_show_rate"] = rng.beta(2, 10, size=n_patients)
    patients["collections_count"] = rng.poisson(0.5, size=n_patients)
    patients["charity_app_count"] = rng.poisson(0.2, size=n_patients)

    # Clip unrealistic values.
    patients["payment_ratio"] = patients["payment_ratio"].clip(0, 1)
    patients["write_off_ratio"] = patients["write_off_ratio"].clip(0, 1)
    patients["no_show_rate"] = patients["no_show_rate"].clip(0, 1)
    patients["ed_proportion"] = patients["ed_proportion"].clip(0, 1)
    patients["avg_days_to_pay"] = patients["avg_days_to_pay"].clip(0, 365)

    logger.info("Generated %d synthetic patients", n_patients)
    return patients
```

---

## Step 2: Engineer and Normalize Features

*The pseudocode calls this `engineer_features(patient_features)`. This transforms raw patient data into a numeric feature matrix suitable for K-Means. The key operations: encode payer type as an ordinal, impute missing values with medians, and z-score normalize so no single feature dominates the distance calculation.*

```python
def engineer_features(patients: pd.DataFrame) -> tuple[np.ndarray, StandardScaler, pd.DataFrame]:
    """
    Transform raw patient data into a normalized feature matrix for clustering.

    Three things happen here:
    1. Payer type gets ordinal encoding (preserving financial ordering).
    2. Missing values get median imputation (new patients land in the middle).
    3. All features get z-score normalization (equal contribution to distance).

    The scaler object is returned because you'll need it later to transform
    new patients into the same feature space for cluster assignment.

    Args:
        patients: DataFrame from generate_synthetic_patients or your ETL.

    Returns:
        Tuple of (feature_matrix, scaler, patients_with_features):
        - feature_matrix: numpy array ready for K-Means (n_patients x n_features)
        - scaler: fitted StandardScaler for transforming new data
        - patients_with_features: original DataFrame with payer_ordinal added
    """
    # Encode payer type as ordinal. This preserves the financial ordering
    # that's central to this use case. One-hot encoding would work too,
    # but it loses the "commercial > medicare > medicaid > self_pay"
    # reimbursement hierarchy that we want the clustering to see.
    patients = patients.copy()
    patients["payer_ordinal"] = patients["payer_type"].map(PAYER_ENCODING)

    # Handle missing values with median imputation.
    # In production, new patients (< 6 months of history) will have nulls
    # in payment_ratio, avg_days_to_pay, etc. Median imputation places them
    # in the middle of the distribution rather than at an extreme.
    feature_df = patients[FEATURE_COLUMNS].copy()
    for col in FEATURE_COLUMNS:
        median_val = feature_df[col].median()
        feature_df[col] = feature_df[col].fillna(median_val)

    # Z-score normalization. Without this, deductible_amount (range 0-8000)
    # would completely dominate no_show_rate (range 0-1) in the distance
    # calculation. After normalization, both have mean=0 and std=1.
    scaler = StandardScaler()
    feature_matrix = scaler.fit_transform(feature_df.values)

    logger.info(
        "Feature matrix shape: %s (patients x features)", feature_matrix.shape
    )
    return feature_matrix, scaler, patients
```

---

## Step 3: Run Clustering and Evaluate

*The pseudocode calls this `cluster_patients(feature_matrix, k_range)`. We run K-Means for each candidate k, compute silhouette scores, and select the best segmentation. The silhouette score is a starting point; final k selection requires human review of the cluster profiles.*

```python
def cluster_and_evaluate(
    feature_matrix: np.ndarray,
) -> tuple[KMeans, np.ndarray, list[dict]]:
    """
    Run K-Means for multiple k values and select the best segmentation.

    For each k in K_RANGE, we:
    1. Fit K-Means with 10 random initializations (n_init=10 avoids local minima).
    2. Compute the silhouette score (measures cluster separation quality).
    3. Record inertia (within-cluster sum of squares) for the elbow plot.

    The "best" k is the one with the highest silhouette score. But this is
    a suggestion, not a final answer. If k=5 has silhouette 0.38 and k=4
    has silhouette 0.36, but your finance team can only act on 4 strategies,
    pick k=4. Actionability beats metrics.

    Args:
        feature_matrix: Normalized numpy array from engineer_features.

    Returns:
        Tuple of (best_model, best_labels, all_results):
        - best_model: fitted KMeans object for the best k
        - best_labels: cluster assignments (array of ints, one per patient)
        - all_results: list of dicts with k, silhouette, inertia for comparison
    """
    all_results = []
    best_score = -1
    best_model = None
    best_labels = None

    for k in K_RANGE:
        # n_init=10: run 10 times with different random centroids, keep the best.
        # random_state=42: reproducible results for development. Remove in production
        # if you want to assess stability across random seeds.
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = model.fit_predict(feature_matrix)

        score = silhouette_score(feature_matrix, labels)
        inertia = model.inertia_

        all_results.append({
            "k": k,
            "silhouette_score": round(score, 4),
            "inertia": round(inertia, 2),
        })

        logger.info("  k=%d: silhouette=%.4f, inertia=%.2f", k, score, inertia)

        if score > best_score:
            best_score = score
            best_model = model
            best_labels = labels

    logger.info(
        "Best k=%d with silhouette=%.4f",
        best_model.n_clusters,
        best_score,
    )
    return best_model, best_labels, all_results
```

---

## Step 4: Profile Clusters

*The pseudocode calls this `profile_clusters(patient_data, labels, feature_columns)`. This is where raw cluster IDs become something a CFO can understand. For each cluster, we compute summary statistics and generate a human-readable label based on the dominant characteristics.*

```python
def profile_clusters(patients: pd.DataFrame, labels: np.ndarray) -> list[dict]:
    """
    Generate human-readable profiles for each cluster.

    For each cluster, compute:
    - Size and percentage of total population
    - Mean values for all financial and utilization features
    - Dominant payer type (mode)
    - A suggested label based on the most distinguishing characteristics

    The suggested labels are heuristic. They're a starting point for the
    conversation with your finance team, who will rename them to match
    their mental model. "Cluster 3" means nothing. "HDHP Payment-Challenged"
    means everything.

    Args:
        patients: DataFrame with patient data (including payer_type).
        labels: Cluster assignment array from cluster_and_evaluate.

    Returns:
        List of profile dicts, one per cluster, sorted by cluster ID.
    """
    patients = patients.copy()
    patients["cluster"] = labels

    profiles = []

    for cluster_id in sorted(patients["cluster"].unique()):
        cluster_df = patients[patients["cluster"] == cluster_id]
        n = len(cluster_df)
        pct = round(n / len(patients) * 100, 1)

        # Compute feature means for this cluster.
        profile = {
            "cluster_id": int(cluster_id),
            "size": n,
            "percentage": pct,
            "dominant_payer": cluster_df["payer_type"].mode().iloc[0],
            "payer_distribution": cluster_df["payer_type"].value_counts(normalize=True).round(3).to_dict(),
            "avg_payment_ratio": round(cluster_df["payment_ratio"].mean(), 3),
            "avg_write_off_ratio": round(cluster_df["write_off_ratio"].mean(), 3),
            "avg_days_to_pay": round(cluster_df["avg_days_to_pay"].mean(), 1),
            "avg_utilization_intensity": round(cluster_df["utilization_intensity"].mean(), 2),
            "avg_ed_proportion": round(cluster_df["ed_proportion"].mean(), 3),
            "avg_no_show_rate": round(cluster_df["no_show_rate"].mean(), 3),
            "avg_deductible": round(cluster_df["deductible_amount"].mean(), 0),
            "avg_coverage_changes": round(cluster_df["coverage_changes_24mo"].mean(), 2),
            "avg_collections_count": round(cluster_df["collections_count"].mean(), 2),
            "avg_charity_apps": round(cluster_df["charity_app_count"].mean(), 2),
        }

        # Generate a suggested label based on dominant characteristics.
        profile["suggested_label"] = _generate_cluster_label(profile)
        profiles.append(profile)

    return profiles


def _generate_cluster_label(profile: dict) -> str:
    """
    Heuristic label generation based on cluster characteristics.

    This is intentionally simple. The real labels come from your finance
    team after they review the profiles. This just gives them a starting point.
    """
    payer = profile["dominant_payer"]
    payment = profile["avg_payment_ratio"]
    write_off = profile["avg_write_off_ratio"]
    deductible = profile["avg_deductible"]

    if payment > 0.85 and write_off < 0.05:
        risk_level = "Low Risk"
    elif payment > 0.6 and write_off < 0.15:
        risk_level = "Moderate Risk"
    else:
        risk_level = "High Risk"

    payer_label = payer.replace("_", " ").title()

    if payer == "commercial" and deductible > 3000:
        payer_label = "HDHP Commercial"

    return f"{payer_label} - {risk_level}"
```

---

## Step 5: Detect Population Shifts

*The pseudocode calls this `detect_population_shift(current_distribution, previous_distribution, threshold)`. This compares cluster distributions between runs and fires alerts when the population is shifting in a financially meaningful direction.*

```python
def detect_population_shift(
    current_profiles: list[dict],
    previous_profiles: list[dict],
) -> list[dict]:
    """
    Compare cluster distributions between the current and previous run.

    A shift of SHIFT_THRESHOLD_PP percentage points in any cluster triggers
    an alert. In practice, a 5pp shift in a quarter is significant: it means
    thousands of patients are moving between financial risk segments.

    WARNING: This implementation matches clusters by suggested_label, which
    is non-deterministic across runs. In production, match clusters by
    centroid similarity (Hungarian method on centroid distances) or use the
    previous run's centroids as initialization. Label-based matching will
    produce false positives when a cluster hovers near a threshold boundary
    (e.g., payment_ratio near 0.85 flipping between "Low Risk" and
    "Moderate Risk" labels).

    Args:
        current_profiles: Profiles from this run's clustering.
        previous_profiles: Profiles from the last run (loaded from S3 history).

    Returns:
        List of alert dicts for clusters that shifted beyond threshold.
        Empty list means the population is stable (good news).
    """
    # TODO (TechWriter): Code review Issue 3 (WARNING). Replace label-based matching
    # with centroid-distance matching for production reliability. The current approach
    # will produce false shift alerts when labels flip due to threshold boundary effects.
    # Build lookup by cluster label (not ID, since IDs can shift between runs).
    previous_by_label = {p["suggested_label"]: p["percentage"] for p in previous_profiles}

    alerts = []

    for profile in current_profiles:
        label = profile["suggested_label"]
        current_pct = profile["percentage"]
        previous_pct = previous_by_label.get(label, 0.0)
        shift = current_pct - previous_pct

        if abs(shift) >= SHIFT_THRESHOLD_PP:
            direction = "growing" if shift > 0 else "shrinking"
            alerts.append({
                "cluster_label": label,
                "direction": direction,
                "shift_pp": round(shift, 1),
                "current_pct": current_pct,
                "previous_pct": previous_pct,
                "message": (
                    f"Cluster '{label}' is {direction}: "
                    f"{previous_pct}% -> {current_pct}% ({shift:+.1f} pp)"
                ),
            })

    if alerts:
        logger.info("Population shift detected: %d cluster(s) beyond threshold", len(alerts))
    else:
        logger.info("Population stable: no clusters shifted beyond %.1f pp", SHIFT_THRESHOLD_PP)

    return alerts
```

---

## Step 6: Upload Results to S3

*In production, cluster assignments go back to S3 as Parquet for Athena queries. Profiles and evaluation metrics go as JSON for dashboards and monitoring.*

```python
def upload_results_to_s3(
    patients: pd.DataFrame,
    labels: np.ndarray,
    profiles: list[dict],
    evaluation: list[dict],
) -> dict:
    """
    Write cluster assignments and profiles to S3 for downstream consumption.

    Three artifacts are written:
    1. Cluster assignments (Parquet): patient_id + cluster_id for Athena queries.
    2. Cluster profiles (JSON): summary stats for dashboards.
    3. Evaluation metrics (JSON): silhouette scores for audit trail.

    Args:
        patients: DataFrame with patient data.
        labels: Cluster assignment array.
        profiles: List of profile dicts from profile_clusters.
        evaluation: List of evaluation dicts from cluster_and_evaluate.

    Returns:
        Dict with S3 keys for each uploaded artifact.
    """
    s3_client = boto3.client("s3")
    run_date = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Cluster assignments as Parquet (for Athena).
    assignments_df = pd.DataFrame({
        "patient_id": patients["patient_id"],
        "cluster_id": labels,
        "run_date": run_date,
    })
    assignments_key = f"{S3_PREFIX_RESULTS}{run_date}/assignments.parquet"
    # to_parquet() with no path argument returns bytes in memory,
    # which we pass directly to S3.
    parquet_buffer = assignments_df.to_parquet(index=False)
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=assignments_key,
        Body=parquet_buffer,
        ServerSideEncryption="aws:kms",
    )

    # 2. Cluster profiles as JSON (for dashboards and monitoring).
    profiles_key = f"{S3_PREFIX_RESULTS}{run_date}/profiles.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=profiles_key,
        Body=json.dumps(profiles, indent=2),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    # 3. Evaluation metrics as JSON (audit trail).
    eval_key = f"{S3_PREFIX_RESULTS}{run_date}/evaluation.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=eval_key,
        Body=json.dumps(evaluation, indent=2),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    # 4. Copy profiles to history for shift detection on next run.
    history_key = f"{S3_PREFIX_HISTORY}{run_date}/profiles.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=history_key,
        Body=json.dumps(profiles, indent=2),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    logger.info("Uploaded results to s3://%s/%s", S3_BUCKET, S3_PREFIX_RESULTS + run_date)
    return {
        "assignments_key": assignments_key,
        "profiles_key": profiles_key,
        "evaluation_key": eval_key,
        "history_key": history_key,
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This runs locally for development. In production, you'd run the clustering step as a SageMaker Processing Job and orchestrate with Step Functions or EventBridge.

```python
def run_payer_risk_clustering_pipeline(
    n_patients: int = 5000,
    previous_profiles: list[dict] | None = None,
) -> dict:
    """
    Run the full payer mix financial risk clustering pipeline.

    Covers all five steps from the Recipe 6.3 pseudocode:
      1. Extract/generate patient financial data
      2. Engineer and normalize features
      3. Run clustering and evaluate multiple k values
      4. Profile clusters with human-readable labels
      5. Detect population shifts (if previous run available)

    Plus uploads results to S3 for Athena and QuickSight consumption.

    Args:
        n_patients: Number of patients (synthetic data mode).
        previous_profiles: Profiles from last run for shift detection.
                          None on first run.

    Returns:
        Dict with profiles, evaluation metrics, alerts, and S3 keys.
    """
    print("=" * 60)
    print("PAYER MIX FINANCIAL RISK CLUSTERING")
    print("=" * 60)

    # Step 1: Generate synthetic patient data.
    # In production: replace with Glue ETL pulling from billing, EHR, eligibility.
    print("\nStep 1: Generating patient financial data...")
    patients = generate_synthetic_patients(n_patients=n_patients)
    print(f"  {len(patients)} patients with {len(patients.columns)} raw features")

    # Step 2: Engineer features and normalize.
    print("\nStep 2: Engineering and normalizing features...")
    feature_matrix, scaler, patients = engineer_features(patients)
    print(f"  Feature matrix: {feature_matrix.shape[0]} patients x {feature_matrix.shape[1]} features")
    print(f"  Features: {FEATURE_COLUMNS}")

    # Step 3: Cluster and evaluate.
    print("\nStep 3: Running K-Means for k={} through k={}...".format(K_RANGE.start, K_RANGE.stop - 1))
    best_model, best_labels, evaluation = cluster_and_evaluate(feature_matrix)
    print(f"\n  Best k={best_model.n_clusters}")
    print("  Evaluation summary:")
    for result in evaluation:
        marker = " <-- best" if result["k"] == best_model.n_clusters else ""
        print(f"    k={result['k']}: silhouette={result['silhouette_score']:.4f}{marker}")

    # Step 4: Profile clusters.
    print("\nStep 4: Profiling clusters...")
    profiles = profile_clusters(patients, best_labels)
    print(f"\n  Cluster Profiles:")
    print(f"  {'Label':<35} {'Size':>6} {'%':>6} {'Pay Ratio':>10} {'Write-off':>10} {'Days AR':>8}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*8}")
    for p in profiles:
        print(
            f"  {p['suggested_label']:<35} {p['size']:>6} {p['percentage']:>5.1f}% "
            f"{p['avg_payment_ratio']:>10.3f} {p['avg_write_off_ratio']:>10.3f} "
            f"{p['avg_days_to_pay']:>7.1f}"
        )

    # Step 5: Detect population shifts.
    alerts = []
    if previous_profiles:
        print("\nStep 5: Checking for population shifts...")
        alerts = detect_population_shift(profiles, previous_profiles)
        if alerts:
            print("  ALERTS:")
            for alert in alerts:
                print(f"    {alert['message']}")
        else:
            print("  No significant shifts detected.")
    else:
        print("\nStep 5: Skipped (no previous run for comparison).")

    # Upload to S3 (commented out for local development).
    # s3_keys = upload_results_to_s3(patients, best_labels, profiles, evaluation)

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    return {
        "profiles": profiles,
        "evaluation": evaluation,
        "best_k": best_model.n_clusters,
        "alerts": alerts,
    }


if __name__ == "__main__":
    result = run_payer_risk_clustering_pipeline(n_patients=5000)

    # Pretty-print the profiles as JSON.
    print("\n\nFull profiles JSON:")
    print(json.dumps(result["profiles"], indent=2))
```

---

## The Gap Between This and Production

This example works: run it and it will produce meaningful financial risk clusters from synthetic data. The distance between that and a production deployment is real. Here's where it lives.

**Real data integration is 70% of the work.** This example generates synthetic data in one function call. In production, you're joining billing system extracts (often in HL7 835/837 formats), EHR utilization data (FHIR or proprietary APIs), and eligibility feeds (X12 270/271). Each system has its own patient identifier, its own data model, and its own update cadence. The Glue ETL job that resolves these to a single patient record is where most of the engineering effort goes. Budget 3-4 weeks for data integration alone.

**Patient identity resolution.** The join in Step 1 assumes a shared `patient_id`. In reality, your billing system uses account numbers, your EHR uses MRNs, and your eligibility feed uses member IDs. You need an MPI (Master Patient Index) or entity resolution layer (see Chapter 5) to link these. Without it, you'll cluster on incomplete records and produce segments that reflect data availability rather than actual financial risk.

**Feature drift and staleness.** Payment behavior changes. Payer contracts get renegotiated. New plan designs emerge. The features that separated clusters well last year might not work this year. Monitor feature distributions between runs. If a feature's variance collapses (everyone has the same value), it's no longer contributing to separation and should be replaced or re-engineered.

**Cluster stability across runs.** This example runs once. In production, you re-cluster monthly or quarterly. If 30% of patients change clusters between runs, your segments aren't stable enough to act on. Common causes: too many clusters (reduce k), noisy features (smooth or remove them), or genuine population change (which is the signal you're trying to detect, not noise). Track the percentage of patients who stay in the same cluster between runs. Below 85% stability, investigate before operationalizing.

**SageMaker Processing Jobs for scale.** This example runs scikit-learn locally. For populations over 100K patients, run the clustering as a SageMaker Processing Job with a larger instance type (ml.m5.4xlarge or ml.m5.12xlarge). The code is identical; you just package it in a container and submit it to SageMaker. For populations over 1M, consider SageMaker's built-in K-Means algorithm, which distributes across multiple instances.

**Ethical guardrails and access controls.** Cluster assignments reveal financial vulnerability. They must never be used to gate clinical access, delay care, or discriminate in scheduling. Build this into your data governance: restrict who can query cluster assignments, audit all access via CloudTrail, and document the approved use cases (financial planning, charity care budgeting, financial counseling targeting). If someone queries cluster assignments joined with scheduling data, that's an alert.

**Missing data handling for new patients.** Median imputation works for patients with partial history. But a brand-new patient (first visit, no payment history, no utilization data) gets median values for everything, which places them in the middle of the distribution. That's not wrong, but it's not informative either. Consider a separate "insufficient data" category for patients with less than 6 months of history, and assign them to clusters only after enough behavioral data accumulates.

**Outlier handling.** A single patient with $2M in charges from a transplant episode will distort the clustering if left untreated. Options: winsorize extreme values (cap at the 99th percentile), use robust scaling (median and IQR instead of mean and std), or remove extreme outliers before clustering and assign them to a separate "high-cost outlier" segment. This example does none of these. Production should.

**VPC and encryption.** Patient financial data combined with utilization data is PHI. The SageMaker Processing Job runs in a VPC with no internet access. S3 buckets use SSE-KMS with customer-managed keys. Athena query results are encrypted. All API calls over TLS. CloudTrail logs every access to the cluster assignment data.

**Testing.** There are no tests here. A production pipeline has unit tests for feature engineering (does the scaler produce the expected output for known inputs?), integration tests for the full pipeline with synthetic data, and regression tests that verify cluster stability when re-run on the same data with the same seed. The synthetic data generator itself should be tested: verify that the statistical properties match your expectations.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.3: Payer Mix Financial Risk Clustering](chapter06.03-payer-mix-financial-risk-clustering) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
