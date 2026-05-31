# Recipe 6.3: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 6.3. It's meant to show one way you could translate payer mix financial risk clustering into working Python code. It is not production-ready. There's no real data pipeline here, no Glue ETL, no SageMaker training job. It's scikit-learn on synthetic data in a script. Think of it as the whiteboard sketch that helps you understand the shape of the solution before you build the real thing. A starting point, not a destination.

---

## Setup

You'll need scikit-learn for clustering, pandas for data manipulation, and boto3 for the AWS integration pieces:

```bash
pip install boto3 pandas scikit-learn numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `s3:GetObject`, `s3:PutObject`, and `sagemaker:CreateProcessingJob` if you want to run this on SageMaker Processing. For the local version shown here, you only need S3 access for reading/writing data.

---

## Config and Constants

Before we get to the logic, here's the configuration that drives the clustering. These live at the top of your module so they're easy to find and tune. The feature list, the payer encoding, and the number-of-clusters range are the knobs you'll turn most often.

```python
import logging
import json
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log patient identifiers or
# financial details (they're PHI when combined with other data).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Feature Configuration ---
# These are the columns we'll use for clustering. Each one captures a
# different dimension of financial risk. The order doesn't matter for
# K-Means (it's distance-based), but keeping them organized helps
# when you're debugging why a cluster looks weird.

FEATURE_COLUMNS = [
    "payer_ordinal",           # encoded payer type (commercial=4, medicare=3, etc.)
    "payment_ratio",           # total_payments / total_charges
    "write_off_ratio",         # total_write_offs / total_charges
    "avg_days_to_pay",         # mean days from service to payment
    "utilization_intensity",   # visits per month
    "ed_proportion",           # ED visits / total visits
    "avg_complexity",          # average RVU per visit
    "no_show_rate",            # missed appointments / scheduled appointments
    "coverage_changes_24mo",   # number of payer changes in 24 months
    "deductible_amount",       # current plan deductible in dollars
    "collections_count",       # accounts sent to collections
    "charity_app_count",       # charity care applications filed
]

# Payer type encoding: ordinal based on expected reimbursement level.
# This preserves the financial ordering that matters for this use case.
# Commercial plans generally reimburse highest, self-pay lowest.
# These are rough ordinals, not precise reimbursement rates.
PAYER_ENCODING = {
    "commercial": 4,
    "medicare": 3,
    "medicaid": 2,
    "self_pay": 1,
}

# Range of cluster counts to evaluate. K-Means needs you to specify k
# upfront, so we try several and pick the best one.
# Fewer than 3 is too coarse (just rediscovering payer categories).
# More than 8 is too granular for most finance teams to operationalize.
K_RANGE = range(3, 9)

# Population shift alert threshold (percentage points).
# If any cluster's share of the population changes by more than this
# between runs, fire an alert to the revenue cycle team.
SHIFT_THRESHOLD_PP = 5.0
```

---

## Step 1: Generate Synthetic Patient Financial Data

*The pseudocode calls this `extract_patient_financial_data(date_range)`. In production, this would be a Glue ETL job pulling from billing, EHR, and eligibility systems. Here we generate realistic synthetic data so you can run this end-to-end without any real infrastructure.*

```python
def generate_synthetic_patients(n_patients: int = 5000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic patient financial data that mimics real-world distributions.

    Real healthcare populations aren't uniformly distributed. You get clusters
    of commercially-insured patients with good payment behavior, clusters of
    Medicaid patients with high utilization, and a tail of coverage-unstable
    patients with poor payment histories. This function creates data with
    those natural groupings so the clustering algorithm has something
    meaningful to discover.

    Args:
        n_patients: Number of synthetic patients to generate.
        seed: Random seed for reproducibility. Same seed = same patients every time.

    Returns:
        DataFrame with one row per patient and columns matching our feature set.
    """
    rng = np.random.default_rng(seed)

    # We'll generate patients in groups that roughly correspond to the
    # clusters we expect to find. This isn't cheating; it's simulating
    # the real-world structure that exists in actual patient populations.
    # Real data has these patterns because they reflect actual market dynamics.

    segments = {
        # Stable commercial: good payers, moderate utilization, low risk.
        "stable_commercial": {
            "n": int(n_patients * 0.30),
            "payer": "commercial",
            "payment_ratio": (0.88, 0.06),       # mean, std
            "write_off_ratio": (0.02, 0.015),
            "avg_days_to_pay": (20, 8),
            "utilization_intensity": (0.4, 0.2),
            "ed_proportion": (0.05, 0.03),
            "avg_complexity": (1.2, 0.4),
            "no_show_rate": (0.05, 0.03),
            "coverage_changes_24mo": (0.2, 0.4),
            "deductible_amount": (500, 300),
            "collections_count": (0.05, 0.2),
            "charity_app_count": (0.01, 0.1),
        },
        # HDHP commercial: high deductibles, struggle with patient responsibility.
        "hdhp_commercial": {
            "n": int(n_patients * 0.20),
            "payer": "commercial",
            "payment_ratio": (0.58, 0.12),
            "write_off_ratio": (0.18, 0.08),
            "avg_days_to_pay": (65, 20),
            "utilization_intensity": (0.5, 0.25),
            "ed_proportion": (0.12, 0.06),
            "avg_complexity": (1.5, 0.5),
            "no_show_rate": (0.12, 0.06),
            "coverage_changes_24mo": (0.8, 0.7),
            "deductible_amount": (4500, 1500),
            "collections_count": (0.8, 0.9),
            "charity_app_count": (0.3, 0.5),
        },
        # Medicare stable: predictable reimbursement, moderate utilization.
        "medicare_stable": {
            "n": int(n_patients * 0.22),
            "payer": "medicare",
            "payment_ratio": (0.85, 0.07),
            "write_off_ratio": (0.05, 0.03),
            "avg_days_to_pay": (30, 10),
            "utilization_intensity": (0.7, 0.3),
            "ed_proportion": (0.10, 0.05),
            "avg_complexity": (1.8, 0.6),
            "no_show_rate": (0.08, 0.04),
            "coverage_changes_24mo": (0.1, 0.3),
            "deductible_amount": (200, 50),
            "collections_count": (0.1, 0.3),
            "charity_app_count": (0.05, 0.2),
        },
        # Medicaid high-utilization: frequent visits, moderate payment issues.
        "medicaid_high_util": {
            "n": int(n_patients * 0.16),
            "payer": "medicaid",
            "payment_ratio": (0.70, 0.10),
            "write_off_ratio": (0.12, 0.06),
            "avg_days_to_pay": (42, 15),
            "utilization_intensity": (1.2, 0.5),
            "ed_proportion": (0.25, 0.10),
            "avg_complexity": (1.4, 0.5),
            "no_show_rate": (0.18, 0.08),
            "coverage_changes_24mo": (1.5, 1.0),
            "deductible_amount": (0, 0),
            "collections_count": (0.4, 0.6),
            "charity_app_count": (0.5, 0.7),
        },
        # Coverage unstable: frequent payer changes, high write-offs, high risk.
        "coverage_unstable": {
            "n": n_patients - int(n_patients * 0.88),  # remainder
            "payer": "self_pay",
            "payment_ratio": (0.32, 0.15),
            "write_off_ratio": (0.40, 0.15),
            "avg_days_to_pay": (110, 35),
            "utilization_intensity": (0.6, 0.4),
            "ed_proportion": (0.35, 0.15),
            "avg_complexity": (1.6, 0.7),
            "no_show_rate": (0.25, 0.10),
            "coverage_changes_24mo": (3.0, 1.5),
            "deductible_amount": (0, 0),
            "collections_count": (2.5, 1.5),
            "charity_app_count": (1.8, 1.2),
        },
    }

    all_patients = []

    for segment_name, params in segments.items():
        n = params["n"]
        patients = pd.DataFrame({
            "patient_id": [f"PAT-{segment_name[:3].upper()}-{i:05d}" for i in range(n)],
            "payer_type": params["payer"],
            "payment_ratio": rng.normal(params["payment_ratio"][0], params["payment_ratio"][1], n),
            "write_off_ratio": rng.normal(params["write_off_ratio"][0], params["write_off_ratio"][1], n),
            "avg_days_to_pay": rng.normal(params["avg_days_to_pay"][0], params["avg_days_to_pay"][1], n),
            "utilization_intensity": rng.normal(params["utilization_intensity"][0], params["utilization_intensity"][1], n),
            "ed_proportion": rng.normal(params["ed_proportion"][0], params["ed_proportion"][1], n),
            "avg_complexity": rng.normal(params["avg_complexity"][0], params["avg_complexity"][1], n),
            "no_show_rate": rng.normal(params["no_show_rate"][0], params["no_show_rate"][1], n),
            "coverage_changes_24mo": rng.normal(params["coverage_changes_24mo"][0], params["coverage_changes_24mo"][1], n),
            "deductible_amount": rng.normal(params["deductible_amount"][0], params["deductible_amount"][1], n),
            "collections_count": rng.normal(params["collections_count"][0], params["collections_count"][1], n),
            "charity_app_count": rng.normal(params["charity_app_count"][0], params["charity_app_count"][1], n),
        })
        patients["_true_segment"] = segment_name  # for validation only; not used in clustering
        all_patients.append(patients)

    df = pd.concat(all_patients, ignore_index=True)

    # Clip values to realistic ranges. Ratios can't exceed 1.0 or go below 0.
    # Counts can't be negative. Days can't be negative.
    df["payment_ratio"] = df["payment_ratio"].clip(0.0, 1.0)
    df["write_off_ratio"] = df["write_off_ratio"].clip(0.0, 1.0)
    df["ed_proportion"] = df["ed_proportion"].clip(0.0, 1.0)
    df["no_show_rate"] = df["no_show_rate"].clip(0.0, 1.0)
    df["avg_days_to_pay"] = df["avg_days_to_pay"].clip(0, None)
    df["utilization_intensity"] = df["utilization_intensity"].clip(0, None)
    df["avg_complexity"] = df["avg_complexity"].clip(0.1, None)
    df["coverage_changes_24mo"] = df["coverage_changes_24mo"].clip(0, None).round()
    df["deductible_amount"] = df["deductible_amount"].clip(0, None).round(-1)  # round to nearest $10
    df["collections_count"] = df["collections_count"].clip(0, None).round()
    df["charity_app_count"] = df["charity_app_count"].clip(0, None).round()

    return df
```

---

## Step 2: Engineer and Normalize Features

*The pseudocode calls this `engineer_features(patient_features)`. It encodes the payer type as an ordinal, selects the feature columns, imputes missing values, and z-score normalizes everything so no single feature dominates the distance calculation.*

```python
def engineer_features(df: pd.DataFrame) -> tuple[np.ndarray, StandardScaler, pd.DataFrame]:
    """
    Transform raw patient data into a normalized feature matrix ready for clustering.

    Three things happen here:
    1. Payer type gets encoded as an ordinal number (commercial=4 down to self_pay=1).
    2. Missing values get imputed with the column median.
    3. All features get z-score normalized (mean=0, std=1).

    That third step is critical. Without it, deductible_amount (range: $0-$7000)
    would completely dominate the distance calculation, and no_show_rate
    (range: 0.0-0.4) would be effectively invisible to the algorithm.

    Args:
        df: Raw patient DataFrame from Step 1.

    Returns:
        Tuple of:
        - feature_matrix: numpy array of shape (n_patients, n_features), normalized
        - scaler: the fitted StandardScaler (save this for transforming new patients)
        - df: the DataFrame with payer_ordinal added (for profiling later)
    """
    # Encode payer type as ordinal. This preserves the financial ordering
    # that's central to this use case. A purely one-hot encoding would lose
    # the information that commercial > medicare > medicaid > self_pay
    # in terms of expected reimbursement.
    df = df.copy()
    df["payer_ordinal"] = df["payer_type"].map(PAYER_ENCODING)

    # Handle any unmapped payer types (shouldn't happen with clean data,
    # but defensive coding for when someone adds "tricare" to the source).
    if df["payer_ordinal"].isna().any():
        unmapped = df[df["payer_ordinal"].isna()]["payer_type"].unique()
        logger.warning("Unmapped payer types found: %s. Defaulting to 2.", unmapped)
        df["payer_ordinal"] = df["payer_ordinal"].fillna(2)

    # Select feature columns and impute missing values with median.
    # Median is more robust than mean for skewed distributions (which
    # financial data almost always is). A patient with no payment history
    # gets placed in the middle of the distribution rather than at an extreme.
    feature_df = df[FEATURE_COLUMNS].copy()
    for col in FEATURE_COLUMNS:
        median_val = feature_df[col].median()
        feature_df[col] = feature_df[col].fillna(median_val)

    # Z-score normalization: subtract mean, divide by standard deviation.
    # After this, every feature has mean=0 and std=1, so they all contribute
    # equally to the Euclidean distance calculation in K-Means.
    scaler = StandardScaler()
    feature_matrix = scaler.fit_transform(feature_df.values)

    return feature_matrix, scaler, df
```

---

## Step 3: Run Clustering and Evaluate

*The pseudocode calls this `cluster_patients(feature_matrix, k_range)`. It runs K-Means for each candidate k, computes silhouette scores, and returns the best model along with all results for comparison.*

```python
def cluster_patients(feature_matrix: np.ndarray) -> tuple[KMeans, np.ndarray, list]:
    """
    Run K-Means clustering for multiple values of k and select the best.

    "Best" here means highest silhouette score, which measures how well-separated
    the clusters are. But silhouette score is a starting point, not the final word.
    The real test is whether your finance team can look at the cluster profiles
    and immediately name them. If they can't, the segmentation isn't useful
    regardless of what the metrics say.

    Args:
        feature_matrix: Normalized feature array from Step 2.

    Returns:
        Tuple of:
        - best_model: the KMeans model with the highest silhouette score
        - best_labels: cluster assignments for each patient
        - all_results: list of dicts with metrics for each k (for comparison)
    """
    all_results = []

    for k in K_RANGE:
        # n_init=10: run K-Means 10 times with different random centroid
        # placements and keep the best result. K-Means is sensitive to
        # initialization; this avoids getting stuck in a bad local minimum.
        # random_state=42: reproducible results across runs.
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = model.fit_predict(feature_matrix)

        # Silhouette score: measures how similar each point is to its own
        # cluster vs. the nearest neighboring cluster. Range: -1 to 1.
        # Above 0.3 is decent for real-world data. Above 0.5 is strong.
        sil_score = silhouette_score(feature_matrix, labels)

        # Inertia (within-cluster sum of squares): always decreases with k.
        # Useful for the elbow method but not for direct comparison.
        inertia = model.inertia_

        all_results.append({
            "k": k,
            "silhouette_score": round(sil_score, 4),
            "inertia": round(inertia, 2),
            "model": model,
            "labels": labels,
        })

        logger.info("  k=%d: silhouette=%.4f, inertia=%.2f", k, sil_score, inertia)

    # Select the k with the highest silhouette score.
    best = max(all_results, key=lambda x: x["silhouette_score"])
    logger.info("Best k=%d with silhouette=%.4f", best["k"], best["silhouette_score"])

    return best["model"], best["labels"], all_results
```

---

## Step 4: Profile Clusters

*The pseudocode calls this `profile_clusters(patient_data, labels, feature_columns)`. It computes summary statistics for each cluster and generates human-readable profiles that a CFO can actually use.*

```python
def profile_clusters(df: pd.DataFrame, labels: np.ndarray) -> list[dict]:
    """
    Compute summary statistics for each cluster and generate interpretable profiles.

    Raw cluster labels (0, 1, 2, 3, 4) mean nothing to a revenue cycle director.
    This function translates them into profiles like "High-deductible commercial
    patients with poor payment histories" that finance teams can act on.

    Args:
        df: Patient DataFrame (with payer_ordinal added from Step 2).
        labels: Cluster assignment array from Step 3.

    Returns:
        List of profile dicts, one per cluster, sorted by cluster ID.
    """
    df = df.copy()
    df["cluster"] = labels
    total_patients = len(df)

    profiles = []

    for cluster_id in sorted(df["cluster"].unique()):
        cluster_df = df[df["cluster"] == cluster_id]
        n = len(cluster_df)

        profile = {
            "cluster_id": int(cluster_id),
            "size": n,
            "percentage": round(n / total_patients * 100, 1),
            # Payer mix within this cluster.
            "payer_distribution": cluster_df["payer_type"].value_counts(normalize=True).round(3).to_dict(),
            # Key financial metrics (means).
            "avg_payment_ratio": round(cluster_df["payment_ratio"].mean(), 3),
            "avg_write_off_ratio": round(cluster_df["write_off_ratio"].mean(), 3),
            "avg_days_to_pay": round(cluster_df["avg_days_to_pay"].mean(), 1),
            "avg_collections_count": round(cluster_df["collections_count"].mean(), 2),
            "avg_charity_app_count": round(cluster_df["charity_app_count"].mean(), 2),
            # Utilization metrics.
            "avg_utilization_intensity": round(cluster_df["utilization_intensity"].mean(), 3),
            "avg_ed_proportion": round(cluster_df["ed_proportion"].mean(), 3),
            "avg_no_show_rate": round(cluster_df["no_show_rate"].mean(), 3),
            # Coverage stability.
            "avg_coverage_changes": round(cluster_df["coverage_changes_24mo"].mean(), 2),
            "avg_deductible": round(cluster_df["deductible_amount"].mean(), 0),
        }

        # Generate a suggested label based on dominant characteristics.
        # This is a simple heuristic. In practice, your finance team will
        # rename these to something that makes sense in their context.
        profile["suggested_label"] = _generate_cluster_label(profile)
        profiles.append(profile)

    return profiles


def _generate_cluster_label(profile: dict) -> str:
    """
    Heuristic label generator based on dominant cluster characteristics.

    This is intentionally simple. The real labels come from your finance team
    looking at the profiles and saying "oh, that's our HDHP non-payers."
    This just gives them a starting point.
    """
    # Determine dominant payer.
    payer_dist = profile["payer_distribution"]
    dominant_payer = max(payer_dist, key=payer_dist.get) if payer_dist else "unknown"

    # Determine risk level based on write-off ratio.
    write_off = profile["avg_write_off_ratio"]
    if write_off < 0.05:
        risk = "Low Risk"
    elif write_off < 0.15:
        risk = "Moderate Risk"
    else:
        risk = "High Risk"

    # Determine utilization level.
    util = profile["avg_utilization_intensity"]
    if util < 0.4:
        util_label = "Low Util"
    elif util < 0.8:
        util_label = "Moderate Util"
    else:
        util_label = "High Util"

    payer_labels = {
        "commercial": "Commercial",
        "medicare": "Medicare",
        "medicaid": "Medicaid",
        "self_pay": "Self-Pay/Unstable",
    }
    payer_label = payer_labels.get(dominant_payer, dominant_payer.title())

    return f"{payer_label} - {risk} - {util_label}"
```

---

## Step 5: Detect Population Shifts

*The pseudocode calls this `detect_population_shift(current_distribution, previous_distribution, threshold)`. It compares cluster distributions between runs and fires alerts when shifts exceed the threshold.*

```python
def detect_population_shift(
    current_profiles: list[dict],
    previous_profiles: list[dict],
    threshold_pp: float = SHIFT_THRESHOLD_PP,
) -> list[dict]:
    """
    Compare cluster distributions between two time periods and flag significant shifts.

    A 5-percentage-point shift in any cluster over a quarter is worth investigating.
    A 10-point shift is an alarm. This function identifies those shifts and
    generates alert messages for the revenue cycle team.

    Args:
        current_profiles: Cluster profiles from the current run.
        previous_profiles: Cluster profiles from the previous run.
        threshold_pp: Minimum percentage-point change to trigger an alert.

    Returns:
        List of alert dicts for clusters that shifted beyond the threshold.
    """
    # Build lookup of previous percentages by cluster ID.
    prev_pcts = {p["cluster_id"]: p["percentage"] for p in previous_profiles}

    alerts = []

    for profile in current_profiles:
        cluster_id = profile["cluster_id"]
        current_pct = profile["percentage"]
        previous_pct = prev_pcts.get(cluster_id, 0.0)
        shift = current_pct - previous_pct

        if abs(shift) >= threshold_pp:
            direction = "growing" if shift > 0 else "shrinking"
            alerts.append({
                "cluster_id": cluster_id,
                "label": profile.get("suggested_label", f"Cluster {cluster_id}"),
                "direction": direction,
                "shift_pp": round(shift, 1),
                "current_pct": current_pct,
                "previous_pct": previous_pct,
                "message": (
                    f"Cluster {cluster_id} ({profile.get('suggested_label', 'Unknown')}) "
                    f"is {direction}: {previous_pct}% -> {current_pct}% "
                    f"({shift:+.1f} pp)"
                ),
            })

    return alerts
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what you'd call from a SageMaker Processing Job or a scheduled Lambda.

```python
def run_payer_mix_clustering(n_patients: int = 5000) -> dict:
    """
    Run the full payer mix financial risk clustering pipeline.

    In production, this would:
    1. Pull real data from S3 (deposited by a Glue ETL job)
    2. Run on a SageMaker Processing Job (for compute isolation and scaling)
    3. Write cluster assignments back to S3 in Parquet format
    4. Trigger downstream Athena queries and QuickSight refreshes

    Here, we generate synthetic data and run everything locally to demonstrate
    the algorithm and interpretation workflow.

    Args:
        n_patients: Number of synthetic patients to generate.

    Returns:
        Dict with cluster profiles, evaluation metrics, and any shift alerts.
    """
    print("=" * 60)
    print("PAYER MIX FINANCIAL RISK CLUSTERING")
    print("=" * 60)

    # Step 1: Generate (or in production, load) patient financial data.
    print("\nStep 1: Generating synthetic patient financial data...")
    df = generate_synthetic_patients(n_patients=n_patients)
    print(f"  Generated {len(df)} patients across {df['payer_type'].nunique()} payer types")
    print(f"  Payer distribution: {df['payer_type'].value_counts().to_dict()}")

    # Step 2: Engineer features and normalize.
    print("\nStep 2: Engineering features and normalizing...")
    feature_matrix, scaler, df = engineer_features(df)
    print(f"  Feature matrix shape: {feature_matrix.shape}")
    print(f"  Features: {FEATURE_COLUMNS}")

    # Step 3: Run clustering for multiple k values and select best.
    print("\nStep 3: Running K-Means clustering (evaluating k=3 through k=8)...")
    best_model, labels, all_results = cluster_patients(feature_matrix)
    print(f"\n  Selected k={best_model.n_clusters}")
    print(f"  Silhouette score: {silhouette_score(feature_matrix, labels):.4f}")

    # Print evaluation summary for all k values.
    print("\n  Evaluation summary:")
    print(f"  {'k':<4} {'Silhouette':<12} {'Inertia':<12}")
    print(f"  {'-'*4} {'-'*12} {'-'*12}")
    for r in all_results:
        marker = " <-- best" if r["k"] == best_model.n_clusters else ""
        print(f"  {r['k']:<4} {r['silhouette_score']:<12.4f} {r['inertia']:<12.2f}{marker}")

    # Step 4: Profile clusters.
    print(f"\nStep 4: Profiling {best_model.n_clusters} clusters...")
    profiles = profile_clusters(df, labels)

    for p in profiles:
        print(f"\n  Cluster {p['cluster_id']}: {p['suggested_label']}")
        print(f"    Size: {p['size']} patients ({p['percentage']}%)")
        print(f"    Avg payment ratio: {p['avg_payment_ratio']:.1%}")
        print(f"    Avg write-off ratio: {p['avg_write_off_ratio']:.1%}")
        print(f"    Avg days to pay: {p['avg_days_to_pay']:.0f}")
        print(f"    Avg ED proportion: {p['avg_ed_proportion']:.1%}")
        print(f"    Payer mix: {p['payer_distribution']}")

    # Step 5: Simulate a population shift detection.
    # In production, you'd load the previous period's profiles from S3.
    # Here we simulate a previous period by slightly adjusting percentages.
    print("\nStep 5: Checking for population shifts (simulated previous period)...")
    simulated_previous = []
    for p in profiles:
        prev = p.copy()
        # Simulate: the high-risk cluster was smaller last quarter.
        if p["avg_write_off_ratio"] > 0.15:
            prev["percentage"] = p["percentage"] - 6.0  # simulate growth
        else:
            prev["percentage"] = p["percentage"] + 1.5  # others shrank slightly
        simulated_previous.append(prev)

    alerts = detect_population_shift(profiles, simulated_previous)
    if alerts:
        print(f"  ALERTS ({len(alerts)}):")
        for alert in alerts:
            print(f"    {alert['message']}")
    else:
        print("  No significant population shifts detected.")

    # Assemble results.
    results = {
        "n_patients": n_patients,
        "k_selected": best_model.n_clusters,
        "silhouette_score": round(silhouette_score(feature_matrix, labels), 4),
        "cluster_profiles": profiles,
        "evaluation_results": [
            {"k": r["k"], "silhouette": r["silhouette_score"], "inertia": r["inertia"]}
            for r in all_results
        ],
        "shift_alerts": alerts,
    }

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    return results


# Run the pipeline.
if __name__ == "__main__":
    results = run_payer_mix_clustering(n_patients=5000)

    # Pretty-print the cluster profiles as JSON (what you'd write to S3).
    print("\n\nCluster profiles (JSON output):")
    print(json.dumps(results["cluster_profiles"], indent=2, default=str))
```

---

## The Gap Between This and Production

This example runs end-to-end. Generate synthetic data, cluster it, profile the results, check for shifts. But there's a meaningful distance between "works in a script" and "runs quarterly on real patient data at a health system." Here's where that gap lives:

**Real data integration.** The synthetic data generator is a stand-in for a Glue ETL job that pulls from your billing system, EHR, and eligibility feed. That ETL is where 70% of the implementation effort lives. Different source systems use different patient identifiers, different date formats, different definitions of "active patient." The join logic across systems is where the bugs hide. You'll need an MPI (Master Patient Index) or at minimum a deterministic matching strategy.

**SageMaker for scale.** This script runs scikit-learn locally. For populations over 500K patients, you'd run this as a SageMaker Processing Job (which gives you managed compute, VPC isolation, and KMS-encrypted volumes) or use SageMaker's built-in K-Means algorithm (which distributes across multiple instances). The API is different but the algorithm is the same.

**Feature store.** In production, your engineered features should live in a feature store (SageMaker Feature Store or a well-organized S3 prefix with Parquet files). This lets you version features, reproduce past clustering runs, and share features across models. Without it, you'll end up with "which version of the feature engineering code produced these clusters?" confusion.

**Cluster stability tracking.** This example runs once. Production tracks cluster assignments over time: what percentage of patients stay in the same cluster between runs? If stability is below 85%, your features are too noisy or your k is too high. Store historical assignments in S3 and compute transition matrices quarterly.

**Error handling and retries.** No try/except blocks here. A production pipeline handles Glue job failures, S3 access errors, and SageMaker training job timeouts gracefully. Use Step Functions to orchestrate the pipeline with retry logic and failure notifications.

**IAM least-privilege.** The SageMaker execution role needs exactly: `s3:GetObject` on the feature bucket, `s3:PutObject` on the output bucket, `kms:Decrypt` and `kms:GenerateDataKey` for the KMS key. Not `s3:*`. Not `AmazonSageMakerFullAccess`. Scope it tight.

**VPC and encryption.** SageMaker Processing Jobs should run in a VPC with no internet access, using VPC endpoints for S3 and KMS. The feature matrix contains financial data combined with patient identifiers, which is PHI. It should never traverse the public internet, even encrypted.

**Bias auditing.** Before operationalizing clusters, audit them for demographic bias. Do certain clusters disproportionately contain patients from specific racial or ethnic groups? If so, using those clusters for resource allocation decisions could perpetuate disparities. This isn't a technical problem; it's a governance requirement. Build the audit into your quarterly re-clustering workflow.

**Governance guardrails.** The main recipe emphasizes this: these clusters inform financial planning, not clinical access. In production, enforce this with access controls. The cluster assignments table should be accessible to revenue cycle and finance teams, not to scheduling or clinical staff. Document the permitted and prohibited uses in your data governance policy.

**Monitoring and alerting.** The `detect_population_shift` function here just prints. In production, it publishes to SNS, which routes to the revenue cycle director's email and a Slack channel. Use EventBridge to schedule the re-clustering pipeline (monthly or quarterly) and Lambda to run the shift detection after each run.

**Testing.** No tests in this example. A production pipeline has unit tests for feature engineering (does the payer encoding handle edge cases?), integration tests for the full pipeline on a fixed synthetic dataset (do you get the same clusters with the same seed?), and validation tests that check cluster stability against a baseline.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.3](chapter06.03-payer-mix-financial-risk-clustering) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
