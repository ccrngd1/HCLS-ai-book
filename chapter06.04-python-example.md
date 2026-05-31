# Recipe 6.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 6.4. It shows one way you could translate disease severity stratification into working Python code. It is not production-ready. There's no error handling, no retry logic, no input validation. Think of it as the whiteboard sketch: useful for understanding the shape of the solution, not something you'd deploy against your actual patient population on Monday morning. Consider it a starting point, not a destination.
>
> This example uses scikit-learn for clustering locally rather than SageMaker's built-in K-Means algorithm. For populations under 100K patients, scikit-learn is simpler and more flexible. The built-in SageMaker algorithm is better when you're clustering millions of records and need distributed compute. We'll show how to store results in DynamoDB for operational lookups.

---

## Setup

You'll need the AWS SDK for Python and scikit-learn:

```bash
pip install boto3 pandas numpy scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `dynamodb:GetItem`

---

## Configuration and Constants

Everything that's really configuration rather than logic lives here. The feature definitions, clinical weights, and tier count are the pieces that change between organizations and disease cohorts. Treat them as configuration you version-control, not magic numbers buried in functions.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Cohort Configuration ---
# Which patients are we stratifying? This defines the inclusion criteria.
# In production, this drives a SQL query against your clinical data warehouse.
COHORT_CONFIG = {
    "disease": "type_2_diabetes",
    "diagnosis_codes": ["E11"],           # ICD-10 prefix for Type 2 Diabetes
    "min_enrollment_months": 12,          # must have 12 months of data
    "min_age": 18,                        # adults only
}

# --- Feature Configuration ---
# The features we'll use for clustering. Each maps to a column in the
# patient feature matrix. These are the dimensions of "severity" for
# this disease cohort. A different disease (heart failure, COPD) would
# have a completely different feature set.
FEATURE_COLUMNS = [
    "latest_hba1c",
    "hba1c_trend_12mo",
    "complication_count",
    "has_ckd",
    "has_retinopathy",
    "has_neuropathy",
    "has_cvd_event",
    "phq9_latest",
    "adl_limitations",
    "er_visits_12mo",
    "hospitalizations_12mo",
    "specialist_visits_12mo",
    "medication_changes_12mo",
]

# --- Clinical Weights ---
# Clinicians told us that complication burden and utilization matter more
# than a single lab value for determining "true" severity. These weights
# amplify those features in the distance calculation.
#
# A weight of 1.0 means "use as-is after normalization."
# A weight of 1.5 means "this feature counts 50% more than average."
# Set to None to skip weighting entirely (all features equal).
CLINICAL_WEIGHTS = {
    "latest_hba1c": 1.0,
    "hba1c_trend_12mo": 1.2,
    "complication_count": 1.5,
    "has_ckd": 1.3,
    "has_retinopathy": 1.0,
    "has_neuropathy": 1.0,
    "has_cvd_event": 1.4,
    "phq9_latest": 0.8,
    "adl_limitations": 1.1,
    "er_visits_12mo": 1.3,
    "hospitalizations_12mo": 1.4,
    "specialist_visits_12mo": 0.7,
    "medication_changes_12mo": 0.9,
}

# --- Clustering Configuration ---
# How many tiers to try. We'll run K-Means for each value and pick the
# best one based on silhouette score and operational feasibility.
K_RANGE = [3, 4, 5]
RANDOM_SEED = 42

# --- AWS Configuration ---
S3_BUCKET = "my-health-data-lake"
S3_OUTPUT_PREFIX = "severity-stratification/diabetes"
DYNAMODB_TABLE = "severity-tiers"
```

---

## Step 1: Generate Synthetic Patient Data

*The pseudocode calls this the "feature assembly" step. In production, you'd pull this from your clinical data warehouse via Glue or Athena. Here we generate realistic synthetic data so you can run this example without any real patient data.*

```python
def generate_synthetic_cohort(n_patients: int = 2000) -> pd.DataFrame:
    """
    Generate a synthetic diabetes cohort with realistic feature distributions.

    This creates fake-but-plausible patient data that mimics what you'd see
    in a real Type 2 Diabetes population. The distributions are loosely based
    on published epidemiology, not exact replicas. Good enough for demonstrating
    the clustering approach; not good enough for clinical research.

    Args:
        n_patients: Number of synthetic patients to generate.

    Returns:
        DataFrame with one row per patient and columns matching FEATURE_COLUMNS.
    """
    rng = np.random.default_rng(RANDOM_SEED)

    # We'll create patients in rough severity groups, then let the algorithm
    # rediscover those groups. This lets us validate that clustering works.
    # In real life, you don't have these labels. That's the whole point.

    # Assign patients to latent severity groups (the algorithm won't see these)
    # Distribution: ~45% mild, ~30% moderate, ~18% high, ~7% severe
    group_probs = [0.45, 0.30, 0.18, 0.07]
    groups = rng.choice(4, size=n_patients, p=group_probs)

    records = []
    for i in range(n_patients):
        g = groups[i]
        patient = {"patient_id": f"PAT-{i:05d}"}

        # HbA1c: mild patients cluster around 6.5-7.5, severe around 9-11
        hba1c_means = [6.8, 7.6, 8.5, 9.5]
        patient["latest_hba1c"] = max(5.0, rng.normal(hba1c_means[g], 0.6))

        # HbA1c trend: negative = improving, positive = worsening
        trend_means = [-0.1, 0.0, 0.2, 0.5]
        patient["hba1c_trend_12mo"] = rng.normal(trend_means[g], 0.3)

        # Complication count: 0-6 depending on severity
        comp_means = [0.3, 1.8, 3.2, 4.8]
        patient["complication_count"] = max(0, int(rng.normal(comp_means[g], 0.8)))

        # Binary complications: probability increases with severity
        ckd_probs = [0.05, 0.20, 0.45, 0.70]
        patient["has_ckd"] = int(rng.random() < ckd_probs[g])

        retinopathy_probs = [0.03, 0.15, 0.35, 0.55]
        patient["has_retinopathy"] = int(rng.random() < retinopathy_probs[g])

        neuropathy_probs = [0.05, 0.25, 0.40, 0.60]
        patient["has_neuropathy"] = int(rng.random() < neuropathy_probs[g])

        cvd_probs = [0.02, 0.10, 0.25, 0.45]
        patient["has_cvd_event"] = int(rng.random() < cvd_probs[g])

        # PHQ-9 depression score (0-27 scale)
        phq9_means = [3, 6, 10, 15]
        patient["phq9_latest"] = max(0, min(27, int(rng.normal(phq9_means[g], 3))))

        # ADL limitations (0-6)
        adl_means = [0.1, 0.5, 1.5, 3.0]
        patient["adl_limitations"] = max(0, min(6, int(rng.normal(adl_means[g], 0.8))))

        # Utilization: ER visits, hospitalizations, specialist visits
        er_means = [0.2, 0.8, 3.0, 6.0]
        patient["er_visits_12mo"] = max(0, int(rng.poisson(er_means[g])))

        hosp_means = [0.05, 0.3, 1.0, 2.5]
        patient["hospitalizations_12mo"] = max(0, int(rng.poisson(hosp_means[g])))

        spec_means = [1.0, 2.5, 4.0, 6.0]
        patient["specialist_visits_12mo"] = max(0, int(rng.poisson(spec_means[g])))

        med_means = [0.5, 1.5, 3.0, 4.5]
        patient["medication_changes_12mo"] = max(0, int(rng.poisson(med_means[g])))

        # Store the latent group for validation (not used in clustering)
        patient["_latent_group"] = g

        records.append(patient)

    df = pd.DataFrame(records)
    logger.info("Generated synthetic cohort: %d patients", len(df))
    return df
```

---

## Step 2: Preprocess and Normalize Features

*The pseudocode calls this `preprocess_features(feature_matrix, clinical_weights)`. It handles missing values, normalizes features to a common scale, and applies clinical weights so that more important features have more influence on the clustering.*

```python
def preprocess_features(df: pd.DataFrame) -> tuple[np.ndarray, StandardScaler]:
    """
    Normalize the feature matrix and apply clinical weights.

    Why this matters: raw features are on wildly different scales. HbA1c
    ranges from 5 to 14. ER visits range from 0 to 50. Without normalization,
    K-Means would cluster almost entirely on whichever feature has the largest
    numeric range, ignoring everything else.

    Z-score normalization (subtract mean, divide by std) puts every feature
    on a common scale where 0 = cohort average and 1 = one standard deviation
    above average. After normalization, a patient who is 2 standard deviations
    above average on ER visits is "equally far from normal" as a patient who
    is 2 standard deviations above average on HbA1c.

    Args:
        df: DataFrame with patient features (columns matching FEATURE_COLUMNS).

    Returns:
        Tuple of (normalized feature matrix as numpy array, fitted scaler).
        The scaler is returned so you can transform new patients later.
    """
    # Extract just the feature columns as a numpy array.
    # This drops patient_id and any other non-feature columns.
    feature_matrix = df[FEATURE_COLUMNS].values.astype(float)

    # Handle missing values: impute with column median for continuous features,
    # 0 for binary features. In production, you'd have a more sophisticated
    # imputation strategy, but median is a reasonable default.
    for col_idx, col_name in enumerate(FEATURE_COLUMNS):
        col_data = feature_matrix[:, col_idx]
        mask = np.isnan(col_data)
        if mask.any():
            if col_name.startswith("has_"):
                # Binary feature: missing = assume absent
                feature_matrix[mask, col_idx] = 0
            else:
                # Continuous feature: impute with median
                median_val = np.nanmedian(col_data)
                feature_matrix[mask, col_idx] = median_val

    # Z-score normalization using scikit-learn's StandardScaler.
    # fit_transform computes mean and std from this data, then applies the
    # transformation. The scaler object remembers the parameters so you can
    # apply the same transformation to new patients later.
    scaler = StandardScaler()
    normalized = scaler.fit_transform(feature_matrix)

    # Apply clinical weights. Multiply each column by its weight so that
    # more important features have more influence on the distance calculation.
    if CLINICAL_WEIGHTS:
        for col_idx, col_name in enumerate(FEATURE_COLUMNS):
            weight = CLINICAL_WEIGHTS.get(col_name, 1.0)
            normalized[:, col_idx] *= weight

    logger.info(
        "Preprocessed %d patients x %d features",
        normalized.shape[0], normalized.shape[1]
    )
    return normalized, scaler
```

---

## Step 3: Run Clustering

*The pseudocode calls this `run_clustering(normalized_matrix, cluster_config)`. It runs K-Means for each candidate K value and records quality metrics so we can choose the best tier count.*

```python
def run_clustering(normalized: np.ndarray) -> dict:
    """
    Run K-Means for each candidate K and return results with quality metrics.

    K-Means works by placing K cluster centers in the feature space, assigning
    each patient to the nearest center, then iteratively adjusting centers
    until assignments stabilize. It's fast, deterministic (given a seed), and
    produces compact clusters.

    We run multiple K values because the "right" number of tiers depends on
    both the data's natural structure and your operational capacity. The
    silhouette score helps identify which K produces the most well-separated
    clusters.

    Args:
        normalized: The preprocessed, normalized feature matrix.

    Returns:
        Dict mapping K -> {model, labels, inertia, silhouette}.
    """
    results = {}

    for k in K_RANGE:
        # n_init=10 means K-Means runs 10 times with different random
        # initializations and keeps the best result. This avoids getting
        # stuck in a bad local minimum.
        model = KMeans(
            n_clusters=k,
            random_state=RANDOM_SEED,
            n_init=10,
            max_iter=300,
        )

        labels = model.fit_predict(normalized)

        # Inertia: sum of squared distances from each point to its assigned
        # cluster center. Lower = tighter clusters. Always decreases with
        # more K, so it's useful for the "elbow method" but not for direct
        # comparison across K values.
        inertia = model.inertia_

        # Silhouette score: measures how similar each patient is to their own
        # cluster vs. the nearest other cluster. Ranges from -1 to 1.
        # Higher = better separation. This IS comparable across K values.
        sil_score = silhouette_score(normalized, labels)

        results[k] = {
            "model": model,
            "labels": labels,
            "inertia": inertia,
            "silhouette": sil_score,
        }

        logger.info(
            "K=%d: silhouette=%.3f, inertia=%.1f",
            k, sil_score, inertia
        )

    return results
```

---

## Step 4: Select Best K and Profile Tiers

*The pseudocode calls this `validate_and_label(clustering_results, feature_matrix, outcomes_data)`. It picks the best K based on silhouette score, profiles each tier by computing feature averages, and assigns clinically meaningful labels.*

```python
def select_and_profile(
    clustering_results: dict,
    df: pd.DataFrame,
    normalized: np.ndarray,
) -> tuple[int, np.ndarray, dict]:
    """
    Choose the best K, profile each tier, and assign clinical labels.

    The "best" K is the one with the highest silhouette score, subject to
    operational constraints. If your care management team can only support
    3 intervention programs, K=3 is the answer regardless of what the
    silhouette score says.

    After choosing K, we profile each cluster by computing the average of
    each raw (un-normalized) feature. This tells clinicians what the "typical
    patient" in each tier looks like in terms they understand (actual HbA1c
    values, actual ER visit counts).

    Args:
        clustering_results: Output of run_clustering().
        df: Original DataFrame with raw feature values.
        normalized: Normalized feature matrix.

    Returns:
        Tuple of (best_k, labels array, tier_profiles dict).
    """
    # Pick K with highest silhouette score
    best_k = max(clustering_results, key=lambda k: clustering_results[k]["silhouette"])
    best = clustering_results[best_k]
    labels = best["labels"]

    logger.info(
        "Selected K=%d (silhouette=%.3f)", best_k, best["silhouette"]
    )

    # Profile each tier using raw (un-normalized) feature values.
    # Clinicians want to see "average HbA1c = 8.4" not "average z-score = 1.2"
    tier_profiles = {}
    for tier_idx in range(best_k):
        mask = labels == tier_idx
        tier_df = df.loc[mask, FEATURE_COLUMNS]
        profile = tier_df.mean().to_dict()
        profile["patient_count"] = int(mask.sum())
        profile["pct_of_cohort"] = round(mask.sum() / len(labels) * 100, 1)
        tier_profiles[tier_idx] = profile

    # Sort tiers by a composite severity indicator so Tier 0 = mildest.
    # We use complication_count + er_visits as a simple severity proxy.
    severity_order = sorted(
        tier_profiles.keys(),
        key=lambda t: (
            tier_profiles[t]["complication_count"]
            + tier_profiles[t]["er_visits_12mo"]
        ),
    )

    # Remap labels so 0 = mildest, highest = most severe
    label_remap = {old: new for new, old in enumerate(severity_order)}
    remapped_labels = np.array([label_remap[l] for l in labels])

    # Rebuild profiles with remapped indices
    remapped_profiles = {}
    for old_idx, new_idx in label_remap.items():
        remapped_profiles[new_idx] = tier_profiles[old_idx]

    # Print tier profiles for inspection
    logger.info("--- Tier Profiles (K=%d) ---", best_k)
    for tier_idx in sorted(remapped_profiles.keys()):
        p = remapped_profiles[tier_idx]
        logger.info(
            "Tier %d: n=%d (%.1f%%), avg HbA1c=%.1f, "
            "avg complications=%.1f, avg ER visits=%.1f",
            tier_idx, p["patient_count"], p["pct_of_cohort"],
            p["latest_hba1c"], p["complication_count"], p["er_visits_12mo"],
        )

    return best_k, remapped_labels, remapped_profiles
```

---

## Step 5: Assign Clinical Labels

*This maps numeric tier indices to human-readable labels that care managers can act on. The labels come from clinical consensus on what each tier profile represents.*

```python
def assign_tier_labels(best_k: int, tier_profiles: dict) -> dict:
    """
    Map numeric tier indices to clinically meaningful labels.

    These labels are what care managers see in their workflow tools. They
    need to be immediately understandable without looking at the underlying
    feature averages. In production, clinicians review the tier profiles
    and agree on labels during the validation phase.

    Args:
        best_k: Number of tiers.
        tier_profiles: Dict of tier_index -> feature averages.

    Returns:
        Dict mapping tier_index -> label string.
    """
    # Pre-defined label sets for common K values.
    # In production, these come from clinical governance review.
    label_sets = {
        3: {
            0: "Well-Controlled, Low Complexity",
            1: "Moderate Complexity, Stable",
            2: "High Severity, Active Complications",
        },
        4: {
            0: "Well-Controlled, Low Complexity",
            1: "Moderate, Stable Complications",
            2: "High Complexity, Active Complications",
            3: "Severe, Functional Decline",
        },
        5: {
            0: "Well-Controlled, Minimal Risk",
            1: "Mild, Early Complications",
            2: "Moderate, Multiple Complications",
            3: "High Complexity, Frequent Utilization",
            4: "Severe, Functional Decline",
        },
    }

    labels = label_sets.get(best_k)
    if labels is None:
        # Fallback for unexpected K values
        labels = {i: f"Tier {i}" for i in range(best_k)}

    return labels
```

---

## Step 6: Compute Key Drivers for Explainability

*This identifies which features most influenced each patient's tier assignment. Care managers need to understand why a patient is in a given tier. "The algorithm said so" is not acceptable.*

```python
def compute_key_drivers(
    normalized: np.ndarray,
    labels: np.ndarray,
    df: pd.DataFrame,
    top_n: int = 3,
) -> list[list[dict]]:
    """
    For each patient, identify the top features driving their tier assignment.

    We use z-scores as a proxy for "how much this feature contributed to
    the patient being in a high-severity tier." Features with high positive
    z-scores are the ones where this patient is far above the cohort average,
    which is what pushes them toward a higher-severity cluster.

    This is a simplification. True feature importance for clustering would
    require SHAP values or permutation importance. But z-scores are fast,
    interpretable, and good enough for the explainability use case.

    Args:
        normalized: Normalized feature matrix.
        labels: Tier assignments.
        df: Original DataFrame with raw values.
        top_n: Number of top drivers to return per patient.

    Returns:
        List of lists: for each patient, a list of top_n driver dicts.
    """
    all_drivers = []

    for i in range(len(labels)):
        # Get this patient's z-scores (from the normalized matrix)
        z_scores = normalized[i, :]

        # Find the top_n features with highest absolute z-scores.
        # These are the features where this patient deviates most from average.
        top_indices = np.argsort(np.abs(z_scores))[::-1][:top_n]

        drivers = []
        for idx in top_indices:
            feature_name = FEATURE_COLUMNS[idx]
            raw_value = df.iloc[i][feature_name]
            drivers.append({
                "feature": feature_name,
                "value": float(raw_value),
                "z_score": round(float(z_scores[idx]), 2),
            })

        all_drivers.append(drivers)

    return all_drivers
```

---

## Step 7: Store Results in DynamoDB

*The pseudocode calls this `store_tier_assignments(...)`. It writes each patient's tier assignment to DynamoDB for real-time lookups by care management platforms and EHR integrations.*

```python
dynamodb = boto3.resource("dynamodb")


def store_tier_assignments(
    df: pd.DataFrame,
    labels: np.ndarray,
    tier_labels: dict,
    key_drivers: list[list[dict]],
    run_date: str,
) -> int:
    """
    Write tier assignments to DynamoDB for operational lookups.

    Each record includes the patient ID, their tier label, the run date,
    key drivers (for explainability), and an expiration date. Care management
    platforms query this table by patient_id to get the current tier.

    Args:
        df: DataFrame with patient_id column.
        labels: Tier assignment array.
        tier_labels: Dict mapping tier_index -> label string.
        key_drivers: Per-patient key driver lists.
        run_date: ISO date string for this run.

    Returns:
        Count of records written.
    """
    table = dynamodb.Table(DYNAMODB_TABLE)

    # Compute expiration date (90 days from run date).
    # Tier assignments should be refreshed quarterly. Stale assignments
    # get flagged in the care management UI.
    run_dt = datetime.date.fromisoformat(run_date)
    expires_at = (run_dt + datetime.timedelta(days=90)).isoformat()

    count = 0
    # DynamoDB batch_writer handles batching and retries for us.
    # It groups put_item calls into batches of 25 (the DynamoDB limit)
    # and retries any unprocessed items automatically.
    with table.batch_writer() as batch:
        for i, row in df.iterrows():
            tier_idx = int(labels[i])

            # Convert key drivers to DynamoDB-safe format.
            # DynamoDB doesn't accept Python floats; use Decimal.
            drivers_for_dynamo = []
            for d in key_drivers[i]:
                drivers_for_dynamo.append({
                    "feature": d["feature"],
                    "value": Decimal(str(round(d["value"], 2))),
                    "z_score": Decimal(str(d["z_score"])),
                })

            record = {
                "patient_id": row["patient_id"],
                "disease_cohort": COHORT_CONFIG["disease"],
                "tier_label": tier_labels[tier_idx],
                "tier_numeric": tier_idx,
                "run_date": run_date,
                "key_drivers": drivers_for_dynamo,
                "expires_at": expires_at,
            }

            batch.put_item(Item=record)
            count += 1

    logger.info("Stored %d tier assignments in DynamoDB", count)
    return count
```

---

## Step 8: Upload Results to S3

*Writes the full feature matrix and tier assignments to S3 as a Parquet file for dashboarding, longitudinal analysis, and audit purposes.*

```python
s3_client = boto3.client("s3")


def upload_results_to_s3(
    df: pd.DataFrame,
    labels: np.ndarray,
    tier_labels: dict,
    run_date: str,
) -> str:
    """
    Write the full results to S3 as a Parquet file for analytics.

    The DynamoDB table serves real-time lookups. This S3 file serves
    analytics: dashboards, tier migration tracking, equity audits,
    outcome validation. Parquet is columnar and compressed, which makes
    Athena queries fast and cheap.

    Args:
        df: Full DataFrame with features.
        labels: Tier assignments.
        tier_labels: Label mapping.
        run_date: ISO date string.

    Returns:
        S3 key where the file was written.
    """
    # Add tier columns to the DataFrame
    results_df = df.copy()
    results_df["tier_numeric"] = labels
    results_df["tier_label"] = [tier_labels[int(l)] for l in labels]
    results_df["run_date"] = run_date

    # Drop the latent group column (synthetic data artifact, not real)
    if "_latent_group" in results_df.columns:
        results_df = results_df.drop(columns=["_latent_group"])

    # Write to a local buffer, then upload to S3.
    # In production, you'd write directly from a SageMaker Processing Job
    # or Glue job that has native S3 output support.
    s3_key = f"{S3_OUTPUT_PREFIX}/{run_date}/results.parquet"

    # Convert to parquet bytes
    parquet_buffer = results_df.to_parquet(index=False)

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=parquet_buffer,
        ServerSideEncryption="aws:kms",
    )

    logger.info("Uploaded results to s3://%s/%s", S3_BUCKET, s3_key)
    return s3_key
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what you'd call from a SageMaker Processing Job, a Step Functions workflow, or a scheduled Lambda.

```python
def run_severity_stratification() -> dict:
    """
    Run the full disease severity stratification pipeline.

    Steps:
    1. Generate (or load) the patient feature matrix
    2. Preprocess and normalize features
    3. Run K-Means for multiple K values
    4. Select best K and profile tiers
    5. Assign clinical labels
    6. Compute key drivers for explainability
    7. Store results in DynamoDB
    8. Upload full results to S3

    Returns:
        Summary dict with tier distribution and quality metrics.
    """
    run_date = datetime.date.today().isoformat()

    # Step 1: Get the patient cohort with features.
    # In production, this would be a Glue job or Athena query.
    print("Step 1: Assembling patient cohort...")
    df = generate_synthetic_cohort(n_patients=2000)
    print(f"  Cohort size: {len(df)} patients")

    # Step 2: Preprocess and normalize.
    print("Step 2: Preprocessing and normalizing features...")
    normalized, scaler = preprocess_features(df)
    print(f"  Feature matrix shape: {normalized.shape}")

    # Step 3: Run clustering for each candidate K.
    print("Step 3: Running K-Means clustering...")
    clustering_results = run_clustering(normalized)
    for k, result in clustering_results.items():
        print(f"  K={k}: silhouette={result['silhouette']:.3f}")

    # Step 4: Select best K and profile tiers.
    print("Step 4: Selecting best K and profiling tiers...")
    best_k, labels, tier_profiles = select_and_profile(
        clustering_results, df, normalized
    )
    print(f"  Best K: {best_k}")

    # Step 5: Assign clinical labels.
    print("Step 5: Assigning clinical labels...")
    tier_labels = assign_tier_labels(best_k, tier_profiles)
    for idx, label in tier_labels.items():
        profile = tier_profiles[idx]
        print(
            f"  Tier {idx}: {label} "
            f"(n={profile['patient_count']}, {profile['pct_of_cohort']}%)"
        )

    # Step 6: Compute key drivers for each patient.
    print("Step 6: Computing key drivers for explainability...")
    key_drivers = compute_key_drivers(normalized, labels, df)
    print(f"  Computed drivers for {len(key_drivers)} patients")

    # Step 7: Store in DynamoDB.
    print("Step 7: Storing tier assignments in DynamoDB...")
    stored_count = store_tier_assignments(df, labels, tier_labels, key_drivers, run_date)
    print(f"  Stored {stored_count} records")

    # Step 8: Upload to S3.
    print("Step 8: Uploading results to S3...")
    s3_key = upload_results_to_s3(df, labels, tier_labels, run_date)
    print(f"  Uploaded to s3://{S3_BUCKET}/{s3_key}")

    # Build summary
    summary = {
        "run_date": run_date,
        "cohort_size": len(df),
        "disease": COHORT_CONFIG["disease"],
        "best_k": best_k,
        "silhouette_score": round(clustering_results[best_k]["silhouette"], 3),
        "tier_distribution": {
            tier_labels[idx]: tier_profiles[idx]["patient_count"]
            for idx in sorted(tier_profiles.keys())
        },
    }

    print("\n--- Summary ---")
    print(json.dumps(summary, indent=2))
    return summary


# Run the pipeline
if __name__ == "__main__":
    run_severity_stratification()
```

---

## The Gap Between This and Production

This example works. Run it locally and it will cluster a synthetic patient population into severity tiers, print profiles, and (if you have the AWS resources set up) store results in DynamoDB and S3. But there's a meaningful distance between "works in a script" and "runs quarterly against 40,000 real patients." Here's where that gap lives:

**Real data assembly.** The synthetic data generator is a placeholder. In production, Step 1 is a Glue ETL job that joins data from your EHR extract, claims feed, lab results, and screening tools. That job handles schema differences between source systems, deduplication, and temporal alignment (making sure all features reflect the same time window). It's typically the most complex and fragile part of the pipeline.

**Missing data strategy.** This example uses simple median imputation. Real clinical data has complex missingness patterns. A patient without a recent HbA1c might be non-adherent (clinically meaningful) or might have switched providers (data artifact). Production systems use multiple imputation or model-based approaches, and flag patients with excessive missingness for manual review rather than silently imputing.

**Clinical validation loop.** This example picks K based on silhouette score alone. Production requires a clinical validation step where physicians review tier profiles, examine edge cases (patients near tier boundaries), and validate against outcomes (do higher tiers actually have worse hospitalizations, costs, and mortality?). This is a human-in-the-loop process that takes weeks, not seconds.

**Tier migration tracking.** When you re-run stratification quarterly, patients move between tiers. A patient moving from Tier 1 to Tier 3 is a clinical event that should trigger a care management alert. This example doesn't compare current assignments to previous ones or generate migration notifications.

**Equity auditing.** Before deploying tier assignments, you need to check whether race, ethnicity, language, or insurance type correlates with tier assignment after controlling for clinical factors. If Black patients are systematically assigned to lower tiers despite similar clinical profiles, your features may encode access disparities rather than true severity. This audit is not optional.

**Error handling and retries.** The DynamoDB batch_writer handles some retry logic, but the overall pipeline has no error handling. If the S3 upload fails after DynamoDB writes succeed, you have inconsistent state. Production uses Step Functions or Airflow to orchestrate steps with rollback logic.

**Model versioning.** When you change the feature set, weights, or K value, all tier assignments change. You need versioning so downstream systems know which model version produced which assignments. Store the model configuration alongside results and tag DynamoDB records with a version identifier.

**Refresh orchestration.** This runs once when you call it. Production needs a scheduled pipeline (monthly or quarterly) with monitoring for data freshness, job failures, and tier distribution drift. If your source data feed is delayed, the pipeline should wait rather than run on stale data.

**IAM least-privilege.** The permissions listed in Setup are broader than necessary. Production scopes S3 access to specific bucket prefixes, DynamoDB access to the specific table, and uses separate IAM roles for the ETL job vs. the clustering job vs. the storage job.

**VPC and encryption.** Patient clinical data is PHI. In production, all compute (SageMaker Processing Jobs, Glue jobs) runs in a VPC with VPC endpoints for S3 and DynamoDB. No PHI traverses the public internet. KMS customer-managed keys encrypt all data at rest with key rotation enabled.

**DynamoDB data types.** This example already wraps numeric values in `Decimal` (DynamoDB rejects Python floats), but be aware that any new numeric fields you add must also use `Decimal`. The `boto3` DynamoDB resource layer will raise a `TypeError` on any raw float in a `put_item` call.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.4](chapter06.04-disease-severity-stratification.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
