# Recipe 6.5: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 6.5. It shows one way you could translate provider practice pattern clustering into working Python code. It is not production-ready. The synthetic data is tiny, the case-mix adjustment is basic, and the clustering runs on a single machine. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy against your real provider roster on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateProcessingJob`, and `redshift:GetClusterCredentials` if you're connecting to Redshift. For this example, we'll work with local data and S3 storage to keep things focused on the clustering logic.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the analysis. These thresholds and parameters live at the top of your module because they're the knobs you'll tune most often. The minimum panel size, the number of clusters to try, the winsorization bounds: these are all judgment calls that depend on your provider population and organizational goals.

```python
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Analysis Configuration ---

# Minimum number of attributed patients for a provider to be included.
# Below this threshold, metrics are too noisy to be meaningful.
# 50 is typical for primary care. Specialists with lower volumes
# might need a lower threshold (20-30), but you trade stability for coverage.
MIN_PANEL_SIZE = 50

# Range of cluster counts to evaluate. Provider profiling typically
# lands between 3 and 6 meaningful practice styles per specialty.
# More than 6 clusters becomes hard to explain to a medical director.
K_RANGE = [3, 4, 5, 6]

# Winsorization bounds (in standard deviations). Values beyond this
# are capped to prevent extreme outliers from distorting cluster centroids.
# 2.5 SD covers roughly the 99th percentile in a normal distribution.
WINSORIZE_SD = 2.5

# PCA variance threshold. Keep enough components to explain this
# fraction of total variance. 0.85 is a reasonable default that
# balances dimensionality reduction with information preservation.
PCA_VARIANCE_THRESHOLD = 0.85

# Metrics used for provider profiling. Each metric gets case-mix adjusted
# before clustering. The names here must match your data columns.
PROFILE_METRICS = [
    "lab_rate",
    "imaging_rate",
    "mri_rate",
    "referral_rate",
    "referral_breadth",
    "generic_rx_rate",
    "avg_cost_per_patient",
    "ed_rate",
    "readmit_rate",
    "quality_composite",
]

# Patient-level features used for case-mix adjustment.
# These predict "expected" utilization given the provider's patient mix.
CASE_MIX_FEATURES = [
    "avg_age",
    "pct_female",
    "avg_hcc_score",
    "avg_chronic_conditions",
    "pct_dual_eligible",
]
```

---

## Step 1: Generate Synthetic Provider Data

*The pseudocode calls this `aggregate_provider_metrics()`. In production, you'd query your claims warehouse or Redshift. Here we generate realistic synthetic data so you can run this example without any external dependencies.*

```python
def generate_synthetic_providers(n_providers: int = 150, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic provider-level data for demonstration.

    Creates a population of internal medicine providers with realistic
    distributions of utilization metrics and patient panel characteristics.
    The data includes natural correlations (sicker panels correlate with
    higher utilization) so the case-mix adjustment has something to work with.

    In production, this function is replaced by a Redshift query that
    aggregates claims/encounter data to the provider level over your
    chosen time window.
    """
    rng = np.random.default_rng(seed)

    # Generate patient panel characteristics (these drive case-mix adjustment).
    # Providers with sicker panels should have higher raw utilization.
    avg_age = rng.normal(55, 8, n_providers).clip(35, 80)
    pct_female = rng.normal(0.55, 0.08, n_providers).clip(0.3, 0.8)
    avg_hcc_score = rng.normal(1.2, 0.4, n_providers).clip(0.5, 3.0)
    avg_chronic_conditions = rng.normal(2.5, 0.8, n_providers).clip(0.5, 6.0)
    pct_dual_eligible = rng.normal(0.15, 0.08, n_providers).clip(0.0, 0.5)

    # Generate raw utilization metrics. These are intentionally correlated
    # with panel complexity (avg_hcc_score) to simulate the confounding
    # that case-mix adjustment needs to remove.
    complexity_signal = avg_hcc_score  # sicker patients drive higher utilization

    # Add a "practice style" signal that varies independently of case mix.
    # This is what clustering should ultimately detect.
    practice_style = rng.normal(0, 1, n_providers)

    lab_rate = (4.0 + 1.5 * complexity_signal + 0.8 * practice_style
                + rng.normal(0, 0.5, n_providers)).clip(1.0, 12.0)
    imaging_rate = (0.8 + 0.4 * complexity_signal + 0.3 * practice_style
                    + rng.normal(0, 0.2, n_providers)).clip(0.1, 3.0)
    mri_rate = (0.2 + 0.15 * complexity_signal + 0.1 * practice_style
                + rng.normal(0, 0.08, n_providers)).clip(0.0, 1.0)
    referral_rate = (0.12 + 0.05 * complexity_signal + 0.04 * rng.normal(0, 1, n_providers)
                     + rng.normal(0, 0.02, n_providers)).clip(0.02, 0.4)
    referral_breadth = (rng.poisson(8, n_providers) + (referral_rate * 20)).astype(int).clip(2, 30)
    generic_rx_rate = (0.85 - 0.02 * complexity_signal
                       + rng.normal(0, 0.05, n_providers)).clip(0.5, 0.98)
    avg_cost_per_patient = (3200 + 800 * complexity_signal + 400 * practice_style
                            + rng.normal(0, 300, n_providers)).clip(1500, 8000)
    ed_rate = (0.15 + 0.08 * complexity_signal
               + rng.normal(0, 0.03, n_providers)).clip(0.02, 0.5)
    readmit_rate = (0.10 + 0.04 * complexity_signal
                    + rng.normal(0, 0.02, n_providers)).clip(0.02, 0.3)
    quality_composite = (82 - 2 * complexity_signal + 3 * rng.normal(0, 1, n_providers)
                         + rng.normal(0, 3, n_providers)).clip(50, 100)

    panel_size = rng.integers(60, 400, n_providers)

    df = pd.DataFrame({
        "provider_id": [f"PROV-{i:04d}" for i in range(n_providers)],
        "specialty": "Internal Medicine",
        "panel_size": panel_size,
        # Case-mix features
        "avg_age": avg_age.round(1),
        "pct_female": pct_female.round(3),
        "avg_hcc_score": avg_hcc_score.round(2),
        "avg_chronic_conditions": avg_chronic_conditions.round(1),
        "pct_dual_eligible": pct_dual_eligible.round(3),
        # Utilization metrics
        "lab_rate": lab_rate.round(2),
        "imaging_rate": imaging_rate.round(2),
        "mri_rate": mri_rate.round(3),
        "referral_rate": referral_rate.round(3),
        "referral_breadth": referral_breadth,
        "generic_rx_rate": generic_rx_rate.round(3),
        "avg_cost_per_patient": avg_cost_per_patient.round(0),
        "ed_rate": ed_rate.round(3),
        "readmit_rate": readmit_rate.round(3),
        "quality_composite": quality_composite.round(1),
    })

    return df
```

---

## Step 2: Case-Mix Adjustment

*The pseudocode calls this `case_mix_adjust()`. This is the most important step in the pipeline. It separates practice style from patient complexity by calculating observed-to-expected ratios for each metric. Without this, you're just measuring who has sicker patients.*

```python
from sklearn.linear_model import LinearRegression

def case_mix_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adjust each utilization metric for patient panel complexity.

    For each metric, we build a simple linear regression predicting
    the metric from patient panel characteristics (age, HCC score, etc.).
    The observed-to-expected ratio (O/E) isolates the provider's practice
    style from their patient mix.

    O/E = 1.0 means "exactly as expected given your patients."
    O/E = 1.3 means "30% more than expected" (a practice style signal).
    O/E = 0.7 means "30% less than expected."

    In production, you'd use more sophisticated models (ridge regression,
    gradient boosting) and validate the adjustment with held-out data.
    The linear model here is intentionally simple for clarity.
    """
    # Note: we train and predict on the same data here for simplicity.
    # Production systems use cross-validation or held-out splits to avoid
    # overfitting the adjustment model to the training providers.

    # Extract the case-mix features (patient panel characteristics).
    X = df[CASE_MIX_FEATURES].values

    adjusted = df.copy()

    for metric in PROFILE_METRICS:
        y = df[metric].values

        # Fit a regression: metric = f(panel characteristics).
        # This learns what utilization you'd EXPECT given the patient mix.
        model = LinearRegression()
        model.fit(X, y)

        # Predict expected values for each provider.
        expected = model.predict(X)

        # Avoid division by zero for metrics where expected could be near zero.
        # Replace near-zero expected values with a small floor.
        expected = np.maximum(expected, 0.01)

        # Calculate observed-to-expected ratio.
        # This is the provider's practice style signal, separated from case mix.
        oe_ratio = y / expected

        # Store the adjusted metric. Column name gets "_oe" suffix.
        adjusted[f"{metric}_oe"] = oe_ratio.round(3)

        r_squared = model.score(X, y)
        logger.info(
            "  %s: R²=%.3f (%.0f%% of variation explained by case mix)",
            metric, r_squared, r_squared * 100
        )

    return adjusted
```

---

## Step 3: Feature Engineering and Normalization

*The pseudocode calls this `prepare_features()`. It normalizes the adjusted metrics, caps extreme outliers, and optionally reduces dimensionality with PCA. This prepares the data for clustering by ensuring all features contribute equally to distance calculations.*

```python
def prepare_features(df: pd.DataFrame) -> tuple[np.ndarray, list[str], PCA | None]:
    """
    Normalize, winsorize, and optionally reduce dimensionality of
    the case-mix-adjusted provider metrics.

    Returns:
        - feature_matrix: numpy array ready for clustering
        - feature_names: list of column names (or PCA component names)
        - pca_model: fitted PCA object (None if PCA wasn't applied)
    """
    # Extract the O/E ratio columns (our adjusted metrics).
    oe_columns = [f"{m}_oe" for m in PROFILE_METRICS]
    raw_features = df[oe_columns].values

    # Step 3a: Z-score normalization.
    # Each metric gets zero mean and unit variance so that metrics with
    # larger numeric ranges don't dominate the distance calculations.
    scaler = StandardScaler()
    normalized = scaler.fit_transform(raw_features)

    # Step 3b: Winsorization.
    # Cap extreme values at +/- WINSORIZE_SD standard deviations.
    # After z-scoring, values beyond 2.5 are extreme outliers that
    # would pull cluster centroids toward them disproportionately.
    winsorized = np.clip(normalized, -WINSORIZE_SD, WINSORIZE_SD)

    # Step 3c: PCA (if we have many features).
    # Reduces noise and helps clustering find cleaner structure.
    pca_model = None
    if winsorized.shape[1] > 8:
        pca_model = PCA(n_components=PCA_VARIANCE_THRESHOLD)
        feature_matrix = pca_model.fit_transform(winsorized)
        n_components = feature_matrix.shape[1]
        explained = pca_model.explained_variance_ratio_.sum()
        logger.info(
            "  PCA: %d components explain %.1f%% of variance",
            n_components, explained * 100
        )
        feature_names = [f"PC{i+1}" for i in range(n_components)]
    else:
        feature_matrix = winsorized
        feature_names = oe_columns

    return feature_matrix, feature_names, pca_model
```

---

## Step 4: Clustering

*The pseudocode calls this `cluster_providers()`. It runs K-Means for multiple values of K, evaluates each with silhouette score, and selects the best segmentation. In production, you'd also evaluate with domain experts to ensure the clusters are clinically interpretable.*

```python
def cluster_providers(feature_matrix: np.ndarray) -> tuple[np.ndarray, KMeans, dict]:
    """
    Try multiple cluster counts and select the best segmentation.

    Evaluates K-Means for each K in K_RANGE using silhouette score.
    Returns the assignments from the best model along with evaluation
    metrics for all K values (useful for the "elbow plot" conversation
    with your medical director).

    Returns:
        - assignments: cluster label for each provider
        - best_model: the fitted KMeans object
        - evaluation: dict of K -> {silhouette, inertia} for all K tried
    """
    evaluation = {}
    best_score = -1
    best_model = None
    best_assignments = None

    for k in K_RANGE:
        # Fit K-Means. n_init=10 runs the algorithm 10 times with different
        # random initializations and keeps the best result. This reduces
        # sensitivity to the random starting centroids.
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        assignments = model.fit_predict(feature_matrix)

        # Silhouette score measures how well-separated the clusters are.
        # Range: -1 to 1. Higher is better.
        # 0.25-0.45 is typical for provider data (it's noisy).
        score = silhouette_score(feature_matrix, assignments)

        evaluation[k] = {
            "silhouette": round(score, 3),
            "inertia": round(model.inertia_, 1),
        }

        logger.info("  K=%d: silhouette=%.3f, inertia=%.1f", k, score, model.inertia_)

        if score > best_score:
            best_score = score
            best_model = model
            best_assignments = assignments

    logger.info("  Selected K=%d (silhouette=%.3f)", best_model.n_clusters, best_score)

    return best_assignments, best_model, evaluation
```

---

## Step 5: Cluster Interpretation

*The pseudocode calls this `interpret_clusters()`. It characterizes each cluster by identifying which metrics are most distinctive relative to the overall population. This is what turns "Cluster 0" into "Conservative/Efficient" in the medical director's vocabulary.*

```python
def interpret_clusters(
    df: pd.DataFrame,
    assignments: np.ndarray,
) -> list[dict]:
    """
    Characterize each cluster by its most distinctive metrics.

    For each cluster, calculates the mean of each O/E metric and compares
    it to the overall population mean. The metrics with the largest
    deviations become the cluster's "signature" and drive the label.

    Returns a list of cluster profile dicts with size, distinctive features,
    and a suggested label.
    """
    oe_columns = [f"{m}_oe" for m in PROFILE_METRICS]

    df = df.copy()
    df["cluster"] = assignments

    # Overall population statistics for comparison.
    overall_means = df[oe_columns].mean()
    overall_stds = df[oe_columns].std()

    profiles = []

    for cluster_id in sorted(df["cluster"].unique()):
        members = df[df["cluster"] == cluster_id]
        cluster_means = members[oe_columns].mean()

        # Z-score of cluster mean relative to overall population.
        # Positive = this cluster is above average on this metric.
        # Negative = below average.
        z_scores = (cluster_means - overall_means) / overall_stds

        # Top distinctive features (largest absolute z-scores).
        top_features = z_scores.abs().nlargest(5)
        distinctive = []
        for col in top_features.index:
            z = z_scores[col]
            metric_name = col.replace("_oe", "")
            # Use O/E ratio relative to 1.0 (expected) for both direction
            # and magnitude. This keeps the interpretation consistent:
            # O/E > 1.0 means "above expected," O/E < 1.0 means "below expected."
            direction = "above" if cluster_means[col] > 1.0 else "below"
            pct_diff = abs(cluster_means[col] - 1.0) * 100
            distinctive.append({
                "metric": col,
                "z_score": round(z, 2),
                "interpretation": f"{pct_diff:.0f}% {direction} expected {metric_name}",
            })

        # Generate a suggested label based on the dominant pattern.
        label = _suggest_label(z_scores)

        # Outcome metrics for this cluster (not adjusted, just raw).
        outcomes = {
            "quality_composite": round(members["quality_composite"].mean(), 1),
            "readmit_rate": round(members["readmit_rate"].mean(), 3),
            "avg_cost_per_patient": round(members["avg_cost_per_patient"].mean(), 0),
        }

        profiles.append({
            "cluster_id": int(cluster_id),
            "label": label,
            "size": len(members),
            "distinctive_features": distinctive[:3],
            "outcomes": outcomes,
        })

    return profiles

def _suggest_label(z_scores: pd.Series) -> str:
    """
    Heuristic label generation based on the cluster's metric profile.

    In production, these labels should be reviewed and refined by
    clinical leadership. The algorithm suggests; humans decide.

    These thresholds are calibrated for the synthetic data in this example.
    With real provider data, the z-score distributions will differ because
    cluster means have lower variance than individual providers. Tune these
    empirically or replace with a rule engine that clinical leadership can
    configure without code changes.
    """
    cost_z = z_scores.get("avg_cost_per_patient_oe", 0)
    imaging_z = z_scores.get("imaging_rate_oe", 0)
    referral_z = z_scores.get("referral_rate_oe", 0)
    quality_z = z_scores.get("quality_composite_oe", 0)

    if cost_z < -0.5 and imaging_z < -0.5:
        return "Conservative / Efficient"
    elif cost_z > 0.5 and imaging_z > 0.5:
        return "Thorough / Resource-Intensive"
    elif referral_z > 1.0:
        return "Referral-Oriented"
    elif quality_z > 0.8:
        return "Balanced / Guideline-Adherent"
    else:
        return "Mixed Practice Style"
```

---

## Step 6: Generate Provider Reports and Upload to S3

*The pseudocode calls this `generate_reports()`. It produces individual provider reports and an aggregate summary, then stores them in S3 for downstream consumption by QuickSight dashboards or direct provider access.*

```python
import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

# Replace with your actual bucket name.
RESULTS_BUCKET = "provider-practice-patterns"

def generate_provider_report(
    provider_row: pd.Series,
    cluster_profiles: list[dict],
) -> dict:
    """
    Build an individual provider report showing their cluster assignment,
    peer comparison, and key metrics.

    This is what a provider sees when they log into the dashboard.
    It answers: "Where do I fit? How do I compare? What's distinctive
    about my practice style?"
    """
    cluster_id = int(provider_row["cluster"])
    profile = next(p for p in cluster_profiles if p["cluster_id"] == cluster_id)

    oe_columns = [f"{m}_oe" for m in PROFILE_METRICS]

    report = {
        "provider_id": provider_row["provider_id"],
        "specialty": provider_row["specialty"],
        "panel_size": int(provider_row["panel_size"]),
        "analysis_date": datetime.now(timezone.utc).isoformat(),
        "cluster_assignment": {
            "cluster_id": cluster_id,
            "label": profile["label"],
            "cluster_size": profile["size"],
        },
        "metrics": {
            col.replace("_oe", ""): {
                "oe_ratio": round(provider_row[col], 2),
                "interpretation": _interpret_oe(provider_row[col]),
            }
            for col in oe_columns
        },
        "cluster_outcomes": profile["outcomes"],
    }

    return report

def _interpret_oe(oe_ratio: float) -> str:
    """Human-readable interpretation of an O/E ratio."""
    if oe_ratio < 0.8:
        return f"{(1 - oe_ratio) * 100:.0f}% below expected"
    elif oe_ratio > 1.2:
        return f"{(oe_ratio - 1) * 100:.0f}% above expected"
    else:
        return "Near expected"

def upload_results_to_s3(
    cluster_profiles: list[dict],
    provider_reports: list[dict],
    evaluation: dict,
) -> None:
    """
    Upload analysis results to S3 for downstream consumption.

    Three outputs:
    - cluster_profiles.json: aggregate cluster characteristics (for dashboards)
    - provider_reports.json: individual provider reports (for row-level-security views)
    - evaluation.json: model evaluation metrics (for audit trail)
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"results/{timestamp}"

    # Cluster profiles (aggregate view for medical directors).
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=f"{prefix}/cluster_profiles.json",
        Body=json.dumps(cluster_profiles, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    # Individual provider reports (row-level security in QuickSight
    # ensures each provider only sees their own report).
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=f"{prefix}/provider_reports.json",
        Body=json.dumps(provider_reports, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    # Evaluation metrics (audit trail: which K was selected, why).
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=f"{prefix}/evaluation.json",
        Body=json.dumps(evaluation, indent=2),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    logger.info("  Uploaded results to s3://%s/%s/", RESULTS_BUCKET, prefix)
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Step Functions workflow or SageMaker Processing job would invoke.

```python
def run_practice_pattern_analysis(upload_to_s3: bool = False) -> dict:
    """
    Run the full provider practice pattern analysis pipeline.

    Steps:
    1. Load/generate provider data
    2. Case-mix adjust all metrics
    3. Prepare features (normalize, winsorize, PCA)
    4. Cluster providers
    5. Interpret clusters
    6. Generate reports
    7. (Optional) Upload to S3

    Returns the analysis summary including cluster profiles and evaluation metrics.
    """
    print("=" * 60)
    print("Provider Practice Pattern Analysis")
    print("=" * 60)

    # Step 1: Generate synthetic data (replace with Redshift query in production).
    print("\nStep 1: Loading provider data...")
    df = generate_synthetic_providers(n_providers=150)
    print(f"  Loaded {len(df)} providers in {df['specialty'].iloc[0]}")
    print(f"  Panel sizes: {df['panel_size'].min()}-{df['panel_size'].max()} patients")

    # Filter by minimum panel size.
    df = df[df["panel_size"] >= MIN_PANEL_SIZE].reset_index(drop=True)
    print(f"  After panel size filter (>={MIN_PANEL_SIZE}): {len(df)} providers")

    # Step 2: Case-mix adjustment.
    print("\nStep 2: Case-mix adjusting metrics...")
    df = case_mix_adjust(df)
    print("  Calculated O/E ratios for all metrics")

    # Step 3: Feature preparation.
    print("\nStep 3: Preparing features...")
    feature_matrix, feature_names, pca_model = prepare_features(df)
    print(f"  Feature matrix shape: {feature_matrix.shape}")

    # Step 4: Clustering.
    print("\nStep 4: Clustering providers...")
    assignments, model, evaluation = cluster_providers(feature_matrix)
    df["cluster"] = assignments
    print(f"  Assigned {len(df)} providers to {model.n_clusters} clusters")

    # Step 5: Interpretation.
    print("\nStep 5: Interpreting clusters...")
    cluster_profiles = interpret_clusters(df, assignments)
    for profile in cluster_profiles:
        print(f"  Cluster {profile['cluster_id']}: {profile['label']} "
              f"(n={profile['size']})")
        for feat in profile["distinctive_features"]:
            print(f"    - {feat['interpretation']}")

    # Step 6: Generate reports.
    print("\nStep 6: Generating provider reports...")
    provider_reports = []
    for _, row in df.iterrows():
        report = generate_provider_report(row, cluster_profiles)
        provider_reports.append(report)
    print(f"  Generated {len(provider_reports)} individual reports")

    # Step 7: Upload to S3 (optional).
    if upload_to_s3:
        print("\nStep 7: Uploading results to S3...")
        upload_results_to_s3(cluster_profiles, provider_reports, evaluation)
    else:
        print("\nStep 7: Skipping S3 upload (set upload_to_s3=True to enable)")

    # Summary output.
    summary = {
        "analysis_date": datetime.now(timezone.utc).isoformat(),
        "specialty": "Internal Medicine",
        "provider_count": len(df),
        "clusters": cluster_profiles,
        "evaluation": evaluation,
    }

    print("\n" + "=" * 60)
    print("Analysis Complete")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))

    return summary

# Run the pipeline.
if __name__ == "__main__":
    result = run_practice_pattern_analysis(upload_to_s3=False)
```

---

## The Gap Between This and Production

This example works. Run it and you'll get cluster assignments for 150 synthetic providers with interpretable labels and individual reports. But there's a meaningful distance between "works in a script" and "runs quarterly against your real provider roster." Here's where that gap lives:

**Data sourcing.** The synthetic data generator is a placeholder. A real system queries your claims data warehouse (Redshift, Snowflake, or whatever you use) for 12 months of encounters, orders, referrals, prescriptions, and outcomes. That query alone is complex: you need provider attribution logic, specialty assignment, and panel definition rules that are specific to your organization.

**Case-mix model sophistication.** The linear regression here is intentionally basic. Production systems use ridge regression or gradient boosting for the adjustment models, with cross-validation to prevent overfitting. You'd also want to validate the adjustment by checking that adjusted metrics are uncorrelated with panel complexity (if they're still correlated, the adjustment is incomplete).

**Provider attribution.** This example assumes you know which patients belong to which provider. In reality, patient attribution is its own complex problem. Primary care attribution uses different logic than specialist attribution. Get this wrong and every downstream metric is contaminated.

**Specialty segmentation.** We only handle one specialty here. A production system runs separate analyses for each specialty (or role: hospitalists, surgeons, PCPs). The feature set, minimum panel size, and cluster count may differ by specialty.

**Temporal stability.** A production system tracks cluster assignments over time and flags providers whose assignments shift dramatically between quarterly runs. Is that real practice evolution or noise? You need monitoring to distinguish the two.

**Provider feedback mechanism.** The reports need a way for providers to contest their assignment or provide context. "My imaging rate is high because I run a concussion clinic" is legitimate. Build a structured feedback channel and incorporate validated exceptions.

**Error handling and retries.** Every S3 and SageMaker call should be wrapped in try/except with specific handling for throttling, service unavailability, and malformed responses. The boto3 adaptive retry config helps, but you still need application-level error handling.

**IAM least-privilege.** The IAM role for this pipeline should have exactly the permissions it needs: `s3:PutObject` scoped to the specific results bucket, `s3:GetObject` scoped to the data lake prefix, `sagemaker:CreateProcessingJob` if running on SageMaker. Not `s3:*`. Not `AdministratorAccess`.

**VPC configuration.** Provider practice data is linked to patient panels and contains PHI. In production, SageMaker Processing jobs run in VPC mode with VPC endpoints for S3. Redshift lives in a private subnet. Nothing traverses the public internet.

**Encryption.** This example uses `ServerSideEncryption="aws:kms"` for S3 uploads, which is correct. Production adds KMS customer-managed keys with rotation enabled, and CloudTrail logging of every key usage event.

**Logging and audit trail.** The `print()` statements here are placeholders. A real system uses structured logging (JSON format) with consistent fields: analysis run ID, timestamp, provider count, cluster count, silhouette score, and any anomalies detected. This is your audit trail when someone asks "why was Dr. Smith classified as high-utilization last quarter?"

**Testing.** There are no tests here. A production pipeline has unit tests for the case-mix adjustment (does it actually reduce correlation with panel complexity?), integration tests for the full pipeline with known synthetic data, and regression tests that verify cluster stability across code changes.

**Regulatory considerations.** In some states, provider profiling data has specific legal protections. Peer review privilege may apply. Consult legal counsel before sharing results broadly or tying them to compensation.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.5](chapter06.05-provider-practice-pattern-analysis.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
