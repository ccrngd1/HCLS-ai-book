# Recipe 6.3: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 6.3. It shows one way you could translate payer mix financial risk clustering into working Python. It is not production-ready. The synthetic data here is tiny (500 patients), the feature engineering is minimal, and there's no error handling to speak of. Think of it as the napkin sketch that helps you understand the shape of the solution before you build the real thing. A starting point, not a destination.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateProcessingJob` (if you use SageMaker for production runs), and `athena:StartQueryExecution` (for downstream profiling queries).

For this example, we run clustering locally with scikit-learn. In production, you'd run this as a SageMaker Processing Job for larger populations. The algorithm is the same; the execution environment changes.

---

## Config and Constants

These go at the top of your module. They define the feature set, encoding schemes, and thresholds that drive the clustering. Treat these as configuration, not magic numbers buried in functions.

```python
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import json
import logging
from datetime import datetime, timezone

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log patient identifiers.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Payer type ordinal encoding. Higher number = generally higher expected
# reimbursement. This is a simplification (plan design matters more than
# payer category alone), but it preserves the financial ordering that
# K-Means needs to work with categorical data.
PAYER_ENCODING = {
    "commercial_ppo": 5,
    "commercial_hmo": 4,
    "commercial_hdhp": 3,
    "medicare": 3,
    "medicaid": 2,
    "self_pay": 1,
}

# Features used for clustering. Order matters for readability, not for
# the algorithm. Each feature should contribute a distinct signal about
# financial risk. Correlated features (e.g., write_off_ratio and
# payment_ratio) are both included because they capture different
# aspects: one is about what was lost, the other about what was collected.
FEATURE_COLUMNS = [
    "payer_ordinal",
    "payment_ratio",
    "write_off_ratio",
    "avg_days_to_pay",
    "utilization_intensity",
    "ed_proportion",
    "no_show_rate",
    "coverage_changes_24mo",
    "collections_count",
]

# Range of k values to evaluate. Healthcare financial risk clustering
# typically lands between 4-7 clusters. Fewer than 3 is too coarse
# (you're just rediscovering payer categories). More than 8 is too
# granular for most finance teams to operationalize.
K_RANGE = range(3, 9)

# Population shift alert threshold (percentage points).
# A 5pp shift in any cluster between runs is worth investigating.
SHIFT_THRESHOLD_PP = 5.0
```

---

## Step 1: Generate Synthetic Patient Financial Data

*The main recipe's Step 1 pulls from billing, EHR, and eligibility systems. Here we generate synthetic data that mimics the shape of what those joins would produce. In production, this step is a Glue ETL job that queries your actual source systems.*

```python
def generate_synthetic_patients(n_patients: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    Create synthetic patient financial data for demonstration.

    This simulates the output of the ETL step: one row per patient with
    columns from billing (payment behavior), EHR (utilization), and
    eligibility (coverage characteristics).

    The synthetic data is structured to produce recognizable clusters:
    stable commercial payers, HDHP patients with payment challenges,
    Medicare utilizers, Medicaid high-utilization, and coverage-unstable
    high-risk patients. Real data won't be this clean, but the patterns
    are realistic.
    """
    rng = np.random.default_rng(seed)

    # Define cluster archetypes. Each archetype represents a financial
    # risk profile with characteristic feature distributions.
    # In real data, these emerge from the algorithm. Here we plant them
    # so the example produces interpretable results.
    archetypes = [
        {  # Stable commercial, low risk
            "name": "stable_commercial",
            "weight": 0.30,
            "payer": "commercial_ppo",
            "payment_ratio": (0.90, 0.05),
            "write_off_ratio": (0.02, 0.01),
            "avg_days_to_pay": (20, 8),
            "utilization_intensity": (0.4, 0.2),
            "ed_proportion": (0.05, 0.03),
            "no_show_rate": (0.05, 0.03),
            "coverage_changes_24mo": (0.1, 0.3),
            "collections_count": (0.0, 0.1),
        },
        {  # HDHP commercial, payment challenged
            "name": "hdhp_challenged",
            "weight": 0.20,
            "payer": "commercial_hdhp",
            "payment_ratio": (0.60, 0.12),
            "write_off_ratio": (0.18, 0.06),
            "avg_days_to_pay": (65, 20),
            "utilization_intensity": (0.7, 0.3),
            "ed_proportion": (0.15, 0.08),
            "no_show_rate": (0.12, 0.05),
            "coverage_changes_24mo": (0.8, 0.7),
            "collections_count": (1.2, 1.0),
        },
        {  # Medicare, stable utilizers
            "name": "medicare_stable",
            "weight": 0.22,
            "payer": "medicare",
            "payment_ratio": (0.87, 0.06),
            "write_off_ratio": (0.05, 0.03),
            "avg_days_to_pay": (32, 10),
            "utilization_intensity": (1.0, 0.4),
            "ed_proportion": (0.10, 0.05),
            "no_show_rate": (0.08, 0.04),
            "coverage_changes_24mo": (0.2, 0.4),
            "collections_count": (0.2, 0.4),
        },
        {  # Medicaid, high utilization
            "name": "medicaid_high_util",
            "weight": 0.18,
            "payer": "medicaid",
            "payment_ratio": (0.72, 0.10),
            "write_off_ratio": (0.12, 0.05),
            "avg_days_to_pay": (45, 15),
            "utilization_intensity": (1.5, 0.5),
            "ed_proportion": (0.25, 0.10),
            "no_show_rate": (0.18, 0.07),
            "coverage_changes_24mo": (1.5, 1.0),
            "collections_count": (0.5, 0.6),
        },
        {  # Coverage unstable, high risk
            "name": "coverage_unstable",
            "weight": 0.10,
            "payer": "self_pay",
            "payment_ratio": (0.35, 0.15),
            "write_off_ratio": (0.40, 0.12),
            "avg_days_to_pay": (110, 30),
            "utilization_intensity": (0.8, 0.4),
            "ed_proportion": (0.35, 0.12),
            "no_show_rate": (0.25, 0.08),
            "coverage_changes_24mo": (3.0, 1.2),
            "collections_count": (2.5, 1.5),
        },
    ]

    patients = []
    patient_id = 1000

    for archetype in archetypes:
        n = int(n_patients * archetype["weight"])
        for _ in range(n):
            patient_id += 1
            patient = {
                "patient_id": f"PAT-{patient_id}",
                "payer_type": archetype["payer"],
                "payment_ratio": np.clip(
                    rng.normal(*archetype["payment_ratio"]), 0, 1
                ),
                "write_off_ratio": np.clip(
                    rng.normal(*archetype["write_off_ratio"]), 0, 1
                ),
                "avg_days_to_pay": max(
                    0, rng.normal(*archetype["avg_days_to_pay"])
                ),
                "utilization_intensity": max(
                    0, rng.normal(*archetype["utilization_intensity"])
                ),
                "ed_proportion": np.clip(
                    rng.normal(*archetype["ed_proportion"]), 0, 1
                ),
                "no_show_rate": np.clip(
                    rng.normal(*archetype["no_show_rate"]), 0, 1
                ),
                "coverage_changes_24mo": max(
                    0, int(rng.normal(*archetype["coverage_changes_24mo"]))
                ),
                "collections_count": max(
                    0, int(rng.normal(*archetype["collections_count"]))
                ),
            }
            patients.append(patient)

    return pd.DataFrame(patients)
```

---

## Step 2: Engineer and Normalize Features

*The main recipe's Step 2 transforms raw data into a normalized feature matrix. This is where domain expertise matters most. The choice of features, encoding scheme, and normalization method has more impact on cluster quality than the choice of algorithm.*

```python
def engineer_features(df: pd.DataFrame) -> tuple[np.ndarray, StandardScaler, pd.DataFrame]:
    """
    Transform raw patient data into a normalized feature matrix ready for clustering.

    Three things happen here:
    1. Encode categorical payer type as an ordinal number
    2. Select the feature columns that carry financial risk signal
    3. Z-score normalize so no single feature dominates distance calculations

    Returns:
        feature_matrix: numpy array ready for K-Means (n_patients x n_features)
        scaler: fitted StandardScaler (save this for transforming new patients)
        df: the dataframe with payer_ordinal added (for profiling later)
    """
    # Encode payer type as ordinal. This preserves the financial ordering
    # that matters for this use case. A fancier approach would use
    # one-hot encoding, but ordinal works well when the categories have
    # a natural ordering (which reimbursement rates provide).
    df = df.copy()
    df["payer_ordinal"] = df["payer_type"].map(PAYER_ENCODING).fillna(1)

    # Extract the feature columns into a matrix.
    feature_df = df[FEATURE_COLUMNS].copy()

    # Handle any remaining NaN values. In production, you'd investigate
    # why data is missing. Here, median imputation is a safe default
    # that places unknown patients in the middle of the distribution.
    feature_df = feature_df.fillna(feature_df.median())

    # Z-score normalization: subtract mean, divide by standard deviation.
    # Without this, avg_days_to_pay (range 0-150) would completely dominate
    # no_show_rate (range 0-0.3) in the distance calculation.
    scaler = StandardScaler()
    feature_matrix = scaler.fit_transform(feature_df)

    logger.info(
        "Feature matrix: %d patients x %d features",
        feature_matrix.shape[0],
        feature_matrix.shape[1],
    )

    return feature_matrix, scaler, df
```

---

## Step 3: Run Clustering and Evaluate

*The main recipe's Step 3 runs K-Means for multiple k values and evaluates using silhouette score. The best k balances statistical quality with business interpretability.*

```python
def find_optimal_clusters(
    feature_matrix: np.ndarray,
    k_range: range = K_RANGE,
) -> tuple[KMeans, np.ndarray, list[dict]]:
    """
    Run K-Means for multiple k values and select the best segmentation.

    We evaluate each k using silhouette score (higher = better cluster
    separation). But the final decision should also consider whether
    finance leadership can name and act on the resulting segments.

    Returns:
        best_model: the fitted KMeans model for the best k
        best_labels: cluster assignments for each patient
        all_results: evaluation metrics for all k values (for comparison)
    """
    all_results = []

    for k in k_range:
        # n_init=10: run K-Means 10 times with different random seeds,
        # keep the best result. K-Means is sensitive to initialization;
        # multiple runs avoid getting stuck in a bad local minimum.
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = model.fit_predict(feature_matrix)

        # Silhouette score: measures how similar each point is to its own
        # cluster vs. the nearest neighboring cluster. Range -1 to 1.
        # Above 0.25 is decent for real-world financial data.
        sil_score = silhouette_score(feature_matrix, labels)

        # Inertia: within-cluster sum of squares. Always decreases with k.
        # Useful for the elbow method but not a standalone selection criterion.
        inertia = model.inertia_

        all_results.append({
            "k": k,
            "silhouette_score": round(sil_score, 4),
            "inertia": round(inertia, 2),
            "model": model,
            "labels": labels,
        })

        logger.info("  k=%d: silhouette=%.4f, inertia=%.1f", k, sil_score, inertia)

    # Select the k with the highest silhouette score.
    best = max(all_results, key=lambda x: x["silhouette_score"])
    logger.info(
        "Best k=%d (silhouette=%.4f)", best["k"], best["silhouette_score"]
    )

    return best["model"], best["labels"], all_results
```

---

## Step 4: Profile Clusters

*The main recipe's Step 4 computes summary statistics for each cluster and generates human-readable profiles. A CFO doesn't care about cluster 0 vs. cluster 3. They care about "high-deductible patients who don't pay their patient responsibility."*

```python
def profile_clusters(df: pd.DataFrame, labels: np.ndarray) -> list[dict]:
    """
    Compute summary statistics for each cluster and generate profiles
    that finance leadership can understand and act on.

    Returns a list of cluster profile dictionaries, each containing
    size, percentage, feature means, and a suggested human-readable label.
    """
    df = df.copy()
    df["cluster"] = labels
    total_patients = len(df)

    profiles = []

    for cluster_id in sorted(df["cluster"].unique()):
        cluster_df = df[df["cluster"] == cluster_id]
        size = len(cluster_df)

        profile = {
            "cluster_id": int(cluster_id),
            "size": size,
            "percentage": round(size / total_patients * 100, 1),
            "dominant_payer": cluster_df["payer_type"].mode().iloc[0],
            "payer_distribution": cluster_df["payer_type"]
            .value_counts(normalize=True)
            .round(3)
            .to_dict(),
            "avg_payment_ratio": round(cluster_df["payment_ratio"].mean(), 3),
            "avg_write_off_ratio": round(cluster_df["write_off_ratio"].mean(), 3),
            "avg_days_to_pay": round(cluster_df["avg_days_to_pay"].mean(), 1),
            "avg_utilization_intensity": round(
                cluster_df["utilization_intensity"].mean(), 2
            ),
            "avg_ed_proportion": round(cluster_df["ed_proportion"].mean(), 3),
            "avg_no_show_rate": round(cluster_df["no_show_rate"].mean(), 3),
            "avg_collections_count": round(
                cluster_df["collections_count"].mean(), 2
            ),
        }

        # Generate a suggested label based on dominant characteristics.
        # This heuristic picks the most distinguishing features.
        profile["suggested_label"] = _generate_cluster_label(profile)
        profiles.append(profile)

    return profiles


def _generate_cluster_label(profile: dict) -> str:
    """
    Heuristic label generator. In production, a human reviews and
    assigns final labels. This gives them a starting point.
    """
    payer = profile["dominant_payer"].replace("_", " ").title()
    risk_level = "High Risk"

    if profile["avg_payment_ratio"] > 0.85:
        risk_level = "Low Risk"
    elif profile["avg_payment_ratio"] > 0.65:
        risk_level = "Moderate Risk"

    utilization = "Low Util"
    if profile["avg_utilization_intensity"] > 1.2:
        utilization = "High Util"
    elif profile["avg_utilization_intensity"] > 0.6:
        utilization = "Moderate Util"

    return f"{payer} - {risk_level} - {utilization}"
```

---

## Step 5: Detect Population Shifts

*The main recipe's Step 5 compares cluster distributions between runs and alerts when shifts exceed a threshold. This turns a static segmentation into a monitoring system.*

```python
def detect_population_shift(
    current_profiles: list[dict],
    previous_profiles: list[dict],
    threshold: float = SHIFT_THRESHOLD_PP,
) -> list[dict]:
    """
    Compare cluster distributions between two time periods and flag
    significant shifts.

    A 5-percentage-point shift in any cluster is worth investigating.
    A 10-point shift is an alarm. These thresholds are configurable
    because what counts as "significant" depends on your organization's
    tolerance for revenue volatility.

    Returns a list of alert dictionaries for clusters that shifted
    beyond the threshold.
    """
    # Build lookup: cluster_id -> percentage for each period.
    current_dist = {p["cluster_id"]: p["percentage"] for p in current_profiles}
    previous_dist = {p["cluster_id"]: p["percentage"] for p in previous_profiles}

    alerts = []

    for cluster_id, current_pct in current_dist.items():
        previous_pct = previous_dist.get(cluster_id, 0.0)
        shift = current_pct - previous_pct

        if abs(shift) >= threshold:
            direction = "growing" if shift > 0 else "shrinking"
            alerts.append({
                "cluster_id": cluster_id,
                "direction": direction,
                "shift_pp": round(shift, 1),
                "current_pct": current_pct,
                "previous_pct": previous_pct,
                "message": (
                    f"Cluster {cluster_id} is {direction}: "
                    f"{previous_pct}% -> {current_pct}% ({shift:+.1f} pp)"
                ),
            })

    return alerts
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what you'd call from a SageMaker Processing Job or a scheduled Lambda.

```python
def run_payer_mix_clustering_pipeline(n_patients: int = 500) -> dict:
    """
    Run the full payer mix financial risk clustering pipeline.

    In production, this would:
    1. Pull real data from Glue catalog / Athena queries
    2. Run on SageMaker Processing for large populations
    3. Write results to S3 as Parquet
    4. Trigger QuickSight dashboard refresh
    5. Compare against previous run and alert on shifts

    Here, we use synthetic data and run locally to demonstrate the flow.
    """
    logger.info("=" * 60)
    logger.info("Payer Mix Financial Risk Clustering Pipeline")
    logger.info("=" * 60)

    # Step 1: Get patient data (synthetic here, ETL in production).
    logger.info("\nStep 1: Generating synthetic patient data...")
    df = generate_synthetic_patients(n_patients)
    logger.info("  Generated %d patients", len(df))

    # Step 2: Engineer features and normalize.
    logger.info("\nStep 2: Engineering features...")
    feature_matrix, scaler, df = engineer_features(df)

    # Step 3: Find optimal clusters.
    logger.info("\nStep 3: Running K-Means for k=%d to k=%d...", K_RANGE.start, K_RANGE.stop - 1)
    best_model, labels, all_results = find_optimal_clusters(feature_matrix)

    # Step 4: Profile the clusters.
    logger.info("\nStep 4: Profiling clusters...")
    profiles = profile_clusters(df, labels)

    # Print cluster profiles for inspection.
    logger.info("\n--- Cluster Profiles ---")
    for p in profiles:
        logger.info(
            "  Cluster %d: %s (%d patients, %.1f%%)",
            p["cluster_id"],
            p["suggested_label"],
            p["size"],
            p["percentage"],
        )
        logger.info(
            "    Payment ratio: %.3f | Write-off: %.3f | Days to pay: %.1f",
            p["avg_payment_ratio"],
            p["avg_write_off_ratio"],
            p["avg_days_to_pay"],
        )

    # Step 5: Shift detection (simulated previous run with slight differences).
    logger.info("\nStep 5: Checking for population shifts...")
    # Simulate a previous period by slightly adjusting percentages.
    simulated_previous = []
    for p in profiles:
        prev = p.copy()
        prev["percentage"] = p["percentage"] + np.random.uniform(-3, 3)
        simulated_previous.append(prev)

    alerts = detect_population_shift(profiles, simulated_previous)
    if alerts:
        for alert in alerts:
            logger.info("  ALERT: %s", alert["message"])
    else:
        logger.info("  No significant shifts detected.")

    # Assemble output.
    output = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_patients": n_patients,
        "optimal_k": best_model.n_clusters,
        "silhouette_score": round(
            silhouette_score(feature_matrix, labels), 4
        ),
        "cluster_profiles": profiles,
        "evaluation_results": [
            {"k": r["k"], "silhouette_score": r["silhouette_score"]}
            for r in all_results
        ],
        "shift_alerts": alerts,
    }

    logger.info("\nDone. Optimal k=%d, silhouette=%.4f",
                output["optimal_k"], output["silhouette_score"])

    return output


# Run the pipeline.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_payer_mix_clustering_pipeline(n_patients=500)
    print("\n" + json.dumps(
        {k: v for k, v in result.items() if k != "cluster_profiles"},
        indent=2, default=str,
    ))
    print("\nCluster Profiles:")
    print(json.dumps(result["cluster_profiles"], indent=2, default=str))
```

---

## Uploading Results to S3 (AWS Integration)

In production, cluster assignments go to S3 as Parquet for Athena queries and QuickSight dashboards. Here's how that integration looks:

```python
import boto3
import io

def upload_results_to_s3(
    df: pd.DataFrame,
    labels: np.ndarray,
    profiles: list[dict],
    bucket: str,
    prefix: str = "cluster-assignments",
) -> dict:
    """
    Write cluster assignments and profiles to S3 for downstream consumption.

    Two outputs:
    1. Patient-level assignments (Parquet): one row per patient with their
       cluster label. Athena queries this for ad-hoc analysis.
    2. Cluster profiles (JSON): summary stats per cluster. QuickSight
       dashboards read this for the executive view.
    """
    s3 = boto3.client("s3")
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Write patient-level assignments as Parquet.
    # Only include patient_id and cluster label. Do NOT include raw
    # financial features in the output that goes to broad dashboards.
    # Those features are PHI-adjacent and should stay in the restricted zone.
    assignments_df = df[["patient_id"]].copy()
    assignments_df["cluster_id"] = labels
    assignments_df["run_date"] = run_date

    parquet_buffer = io.BytesIO()
    assignments_df.to_parquet(parquet_buffer, index=False)
    parquet_buffer.seek(0)

    assignments_key = f"{prefix}/{run_date}/assignments.parquet"
    s3.put_object(
        Bucket=bucket,
        Key=assignments_key,
        Body=parquet_buffer.getvalue(),
        ServerSideEncryption="aws:kms",
    )

    # Write cluster profiles as JSON.
    profiles_key = f"{prefix}/{run_date}/profiles.json"
    s3.put_object(
        Bucket=bucket,
        Key=profiles_key,
        Body=json.dumps(profiles, indent=2, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
        ContentType="application/json",
    )

    return {
        "assignments_key": assignments_key,
        "profiles_key": profiles_key,
        "patients_written": len(assignments_df),
    }
```

---

## The Gap Between This and Production

This example works. Run it and you'll get cluster assignments with interpretable profiles. But there's a meaningful distance between "works in a script with synthetic data" and "runs quarterly against your real patient population." Here's where that gap lives:

**Real data integration.** The synthetic data generator is a stand-in for a Glue ETL job that joins billing, EHR, and eligibility systems. That join logic is where 70% of your implementation time goes. Patient identity resolution across systems, handling different date formats, dealing with patients who appear in one system but not another. The clustering algorithm is the easy part.

**Missing data handling.** This example uses median imputation, which is fine for a demo. Real patient data has structured missingness: new patients have no payment history, patients who only use the ED have no primary care utilization data, patients with coverage gaps have incomplete eligibility records. You need imputation strategies that account for why data is missing, not just that it is.

**Feature validation.** Before clustering, validate that your features actually carry signal. Check for features with near-zero variance (they contribute nothing). Check for highly correlated feature pairs (they double-count the same signal). Run feature importance analysis on a supervised proxy task (predict write-off rate) to confirm your features are relevant.

**Cluster stability testing.** Run the algorithm 50 times with different random seeds and bootstrap samples. If a patient's cluster assignment changes in more than 15% of runs, that patient is on a boundary and their assignment isn't reliable. Report stability metrics alongside cluster assignments.

**Temporal validation.** Cluster on Q1 data, then check whether the clusters predict Q2 financial outcomes. If "high risk" patients in Q1 don't actually have higher write-off rates in Q2, your clustering isn't capturing real financial risk. It might be capturing data artifacts instead.

**Ethical review.** Before operationalizing, check whether cluster membership correlates with race, ethnicity, or other protected characteristics. If your "high financial risk" cluster is disproportionately patients of color, you have a fairness problem that needs addressing before deployment. This isn't optional.

**IAM least-privilege.** The S3 upload function uses whatever credentials are in the environment. Production uses a dedicated IAM role with `s3:PutObject` scoped to the specific bucket and prefix, `kms:GenerateDataKey` for the specific CMK, and nothing else.

**VPC and encryption.** SageMaker Processing Jobs run in a VPC with no internet access. S3 access goes through a VPC endpoint. All data at rest uses KMS customer-managed keys with rotation enabled. The feature matrix contains financial data that constitutes PHI when combined with patient identifiers.

**Monitoring and alerting.** The shift detection function here prints to stdout. Production routes alerts through SNS to the revenue cycle team's Slack channel and creates a ticket in your incident management system when shifts exceed the alarm threshold.

**Scheduling.** This runs manually. Production uses EventBridge to trigger the pipeline quarterly (or monthly, depending on your population's volatility). The schedule should align with your finance team's reporting cadence so clusters are fresh when they need them.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.3](chapter06.03-payer-mix-financial-risk-clustering) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
