# Recipe 6.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 6.6. It shows one way you could build a patient similarity engine using synthetic data and scikit-learn for the core algorithm, with boto3 for the AWS integration pieces. It is not production-ready. The feature engineering is minimal, the cohort is tiny, and the distance metric is a starting point. Think of it as a workbench prototype: useful for understanding the mechanics, not something you'd plug into a care planning system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy pandas scikit-learn
```

Your environment needs AWS credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject` and `s3:PutObject` on your feature store bucket
- `dynamodb:GetItem` and `dynamodb:PutItem` on the similarity cache table
- `sagemaker:InvokeEndpoint` if using a SageMaker-hosted model (this example uses local scikit-learn instead for simplicity)

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the similarity engine. Feature weights encode clinical judgment about what matters for diabetes patient similarity. These should come from your clinical SMEs, not from the data.

```python
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timezone
import json
import logging
import boto3
from decimal import Decimal

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Feature Configuration ---
# These are the features we use for diabetes patient similarity.
# Each feature has a weight that encodes clinical importance.
# Higher weight = more influence on similarity score.
#
# These weights are NOT learned from data. They come from clinical SMEs
# who understand which factors drive diabetes outcomes. Treat this as
# a living document that gets refined as you validate the model.

FEATURE_WEIGHTS = {
    "age": 1.0,
    "bmi": 1.5,
    "a1c": 3.0,              # A1C is the primary diabetes marker
    "systolic_bp": 1.0,
    "years_since_diagnosis": 2.0,
    "medication_count": 1.0,
    "on_insulin": 2.0,       # insulin status changes trajectory significantly
    "on_metformin": 1.5,
    "on_glp1": 1.5,
    "heart_failure": 2.5,    # comorbidities that change the game
    "ckd": 2.5,
    "depression": 1.5,
    "hypertension": 1.0,
    "ed_visits_12mo": 1.5,
    "hospitalizations_12mo": 2.0,
}

# How many similar patients to retrieve per query.
K_NEIGHBORS = 20

# Maximum distance threshold. Neighbors beyond this are "not similar enough"
# and should not be presented to the care manager.
# This value depends on your feature scaling; tune it empirically.
MAX_DISTANCE_THRESHOLD = 3.0

# DynamoDB table for caching similarity results.
CACHE_TABLE_NAME = "patient-similarity-cache"

# S3 bucket and prefix for the feature store.
FEATURE_STORE_BUCKET = "my-health-system-features"
FEATURE_STORE_PREFIX = "patient-features/diabetes/v2026-03/"

# Cache TTL in seconds (24 hours). Results expire when the feature store refreshes.
CACHE_TTL_SECONDS = 86400
```

---

## Step 1: Generate Synthetic Patient Cohort

*The main recipe's Step 1 covers feature engineering from raw EHR data. Here we generate a synthetic cohort to demonstrate the similarity mechanics without needing real clinical data. In production, this step is replaced by your Glue ETL pipeline.*

```python
def generate_synthetic_cohort(n_patients: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    Generate a synthetic patient cohort with realistic feature distributions.

    This creates fake-but-plausible patient data for demonstrating the
    similarity algorithm. The distributions are loosely based on published
    Type 2 diabetes population statistics, but they're synthetic.
    Do NOT use this for clinical validation.

    Args:
        n_patients: Number of synthetic patients to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with one row per patient, columns matching FEATURE_WEIGHTS keys.
    """
    rng = np.random.default_rng(seed)

    patients = pd.DataFrame({
        "patient_id": [f"PAT-{i:05d}" for i in range(n_patients)],

        # Age: Type 2 diabetes population skews older. Mean ~58, std ~12.
        "age": rng.normal(58, 12, n_patients).clip(30, 90).astype(int),

        # BMI: overweight/obese population. Mean ~32, std ~6.
        "bmi": rng.normal(32, 6, n_patients).clip(18, 55).round(1),

        # A1C: the primary diabetes marker. Mean ~7.8, std ~1.5.
        # Values below 5.7 are non-diabetic; we clip to realistic range.
        "a1c": rng.normal(7.8, 1.5, n_patients).clip(5.7, 14.0).round(1),

        # Systolic blood pressure. Mean ~138, std ~18.
        "systolic_bp": rng.normal(138, 18, n_patients).clip(90, 200).astype(int),

        # Years since diabetes diagnosis. Exponential-ish distribution.
        "years_since_diagnosis": rng.exponential(5, n_patients).clip(0, 30).round(1),

        # Medication count (all medications, not just diabetes).
        "medication_count": rng.poisson(5, n_patients).clip(0, 20),

        # Binary flags for specific drug classes.
        "on_insulin": rng.binomial(1, 0.3, n_patients),
        "on_metformin": rng.binomial(1, 0.75, n_patients),
        "on_glp1": rng.binomial(1, 0.2, n_patients),

        # Comorbidity flags.
        "heart_failure": rng.binomial(1, 0.15, n_patients),
        "ckd": rng.binomial(1, 0.2, n_patients),
        "depression": rng.binomial(1, 0.25, n_patients),
        "hypertension": rng.binomial(1, 0.7, n_patients),

        # Utilization in the past 12 months.
        "ed_visits_12mo": rng.poisson(0.8, n_patients).clip(0, 10),
        "hospitalizations_12mo": rng.poisson(0.3, n_patients).clip(0, 5),
    })

    # Generate synthetic outcomes for the cohort.
    # Goal: A1C < 7.0 within 6 months. Probability depends on features.
    # This is a simplified outcome model for demonstration purposes.
    goal_probability = (
        0.5
        - 0.05 * (patients["a1c"] - 7.0)       # higher baseline A1C = harder
        + 0.1 * patients["on_metformin"]         # metformin helps
        + 0.15 * patients["on_glp1"]             # GLP-1 helps more
        - 0.1 * patients["heart_failure"]        # comorbidities make it harder
        - 0.08 * patients["ckd"]
        - 0.03 * patients["years_since_diagnosis"] / 10
    ).clip(0.1, 0.95)

    patients["goal_achieved"] = rng.binomial(1, goal_probability)

    # Time to goal (months) for those who achieved it. Faster for less severe cases.
    base_time = 3.0 + 0.5 * (patients["a1c"] - 6.5)
    patients["time_to_goal_months"] = np.where(
        patients["goal_achieved"] == 1,
        (base_time + rng.normal(0, 1, n_patients)).clip(1, 12).round(1),
        np.nan
    )

    # Interventions received (simplified: assign based on features).
    patients["intervention_metformin"] = patients["on_metformin"]
    patients["intervention_glp1"] = patients["on_glp1"]
    patients["intervention_lifestyle"] = rng.binomial(1, 0.6, n_patients)
    patients["intervention_insulin_titration"] = patients["on_insulin"]

    # Adverse events (simplified).
    patients["adverse_gi_intolerance"] = (
        patients["on_metformin"] * rng.binomial(1, 0.15, n_patients)
    )
    patients["adverse_hypoglycemia"] = (
        patients["on_insulin"] * rng.binomial(1, 0.1, n_patients)
    )

    return patients
```

---

## Step 2: Build the Similarity Index

*The pseudocode calls this `build_similarity_index`. We use scikit-learn's NearestNeighbors with weighted Euclidean distance. In production, you'd use SageMaker's built-in kNN algorithm or OpenSearch's kNN plugin for scale.*

```python
def build_similarity_index(
    cohort: pd.DataFrame,
    feature_weights: dict,
) -> tuple:
    """
    Build a nearest-neighbor index from the patient cohort.

    This applies feature weights, scales the features, and fits a
    NearestNeighbors model for fast similarity queries.

    Args:
        cohort: DataFrame with patient features (one row per patient).
        feature_weights: Dict mapping feature names to importance weights.

    Returns:
        Tuple of (fitted NearestNeighbors model, fitted StandardScaler, feature column list).
    """
    feature_cols = list(feature_weights.keys())

    # Extract the feature matrix. Each row is a patient, each column is a feature.
    X = cohort[feature_cols].values.astype(float)

    # Standardize features to zero mean, unit variance.
    # Without this, features with large ranges (age: 30-90) would dominate
    # features with small ranges (on_insulin: 0-1) in distance calculations.
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Apply clinical weights. Multiply each feature column by its weight.
    # This makes high-weight features (A1C: 3.0) contribute more to distance
    # than low-weight features (age: 1.0).
    weights = np.array([feature_weights[col] for col in feature_cols])
    X_weighted = X_scaled * weights

    # Fit the nearest-neighbor index.
    # algorithm="ball_tree" works well for moderate dimensions (<50 features).
    # For very high dimensions or very large cohorts, use "brute" or switch
    # to an ANN library like FAISS or Annoy.
    nn_model = NearestNeighbors(
        n_neighbors=K_NEIGHBORS + 1,  # +1 because the patient is their own neighbor
        metric="euclidean",
        algorithm="ball_tree",
    )
    nn_model.fit(X_weighted)

    logger.info(
        "Built similarity index: %d patients, %d features",
        X_weighted.shape[0],
        X_weighted.shape[1],
    )

    return nn_model, scaler, feature_cols
```

---

## Step 3: Query for Similar Patients

*The pseudocode calls this `find_similar_patients`. Given a query patient's features, find the k nearest neighbors in the index and return them with distance scores.*

```python
def find_similar_patients(
    query_patient_id: str,
    cohort: pd.DataFrame,
    nn_model: NearestNeighbors,
    scaler: StandardScaler,
    feature_cols: list,
    feature_weights: dict,
    k: int = K_NEIGHBORS,
    max_distance: float = MAX_DISTANCE_THRESHOLD,
) -> list:
    """
    Find the k most similar patients to a query patient.

    Args:
        query_patient_id: The patient ID to find neighbors for.
        cohort: Full patient cohort DataFrame.
        nn_model: Fitted NearestNeighbors model.
        scaler: Fitted StandardScaler (same one used during index build).
        feature_cols: List of feature column names in order.
        feature_weights: Dict of feature weights.
        k: Number of neighbors to return.
        max_distance: Maximum distance threshold; farther neighbors are excluded.

    Returns:
        List of dicts with patient_id, distance, and similarity score.
    """
    # Look up the query patient's features.
    query_row = cohort[cohort["patient_id"] == query_patient_id]
    if query_row.empty:
        logger.warning("Patient %s not found in cohort", query_patient_id)
        return []

    # Extract, scale, and weight the query vector (same transforms as index build).
    query_features = query_row[feature_cols].values.astype(float)
    query_scaled = scaler.transform(query_features)
    weights = np.array([feature_weights[col] for col in feature_cols])
    query_weighted = query_scaled * weights

    # Query the index. Returns distances and indices of nearest neighbors.
    distances, indices = nn_model.kneighbors(query_weighted, n_neighbors=k + 1)

    # Flatten (kneighbors returns 2D arrays even for single queries).
    distances = distances[0]
    indices = indices[0]

    # Build results, skipping the query patient and filtering by max distance.
    results = []
    for dist, idx in zip(distances, indices):
        neighbor_id = cohort.iloc[idx]["patient_id"]

        # Skip self-match.
        if neighbor_id == query_patient_id:
            continue

        # Stop if we've exceeded the distance threshold.
        # kneighbors() returns results sorted by distance ascending, so once
        # we exceed the threshold, all remaining neighbors are also too far.
        # Note: if using approximate NN libraries (FAISS, Annoy), verify sort
        # order before relying on this early-exit pattern.
        if dist > max_distance:
            break

        results.append({
            "patient_id": neighbor_id,
            "distance": round(float(dist), 4),
            "similarity": round(1.0 / (1.0 + float(dist)), 4),
        })

        if len(results) >= k:
            break

    logger.info(
        "Found %d similar patients for %s (closest distance: %.3f)",
        len(results),
        query_patient_id,
        results[0]["distance"] if results else float("inf"),
    )

    return results
```

---

## Step 4: Aggregate Outcomes

*The pseudocode calls this `aggregate_outcomes`. For the matched similar patients, pull their outcome data and compute actionable summaries.*

```python
def aggregate_outcomes(
    similar_patients: list,
    cohort: pd.DataFrame,
) -> dict:
    """
    Aggregate outcomes for a set of similar patients.

    Computes goal achievement rates, common interventions, adverse events,
    and a confidence indicator based on cohort size.

    Args:
        similar_patients: List of dicts from find_similar_patients.
        cohort: Full cohort DataFrame (includes outcome columns).

    Returns:
        Dict with aggregated outcome summary.
    """
    if not similar_patients:
        return {"cohort_size": 0, "confidence": "insufficient"}

    # Get the patient IDs of similar patients.
    neighbor_ids = [p["patient_id"] for p in similar_patients]

    # Filter the cohort to just the similar patients.
    neighbors_df = cohort[cohort["patient_id"].isin(neighbor_ids)]

    cohort_size = len(neighbors_df)

    # Goal achievement rate.
    goal_rate = neighbors_df["goal_achieved"].mean()

    # Median time to goal (only for those who achieved it).
    achievers = neighbors_df[neighbors_df["goal_achieved"] == 1]
    median_time = (
        float(achievers["time_to_goal_months"].median())
        if not achievers.empty
        else None
    )

    # Intervention frequency among successful patients.
    intervention_cols = [
        "intervention_metformin",
        "intervention_glp1",
        "intervention_lifestyle",
        "intervention_insulin_titration",
    ]
    if not achievers.empty:
        intervention_freq = {
            col.replace("intervention_", ""): round(float(achievers[col].mean()), 2)
            for col in intervention_cols
        }
    else:
        intervention_freq = {}

    # Sort interventions by frequency (most common first).
    intervention_freq = dict(
        sorted(intervention_freq.items(), key=lambda x: x[1], reverse=True)
    )

    # Adverse event rates.
    adverse_cols = ["adverse_gi_intolerance", "adverse_hypoglycemia"]
    adverse_rates = {
        col.replace("adverse_", ""): round(float(neighbors_df[col].mean()), 3)
        for col in adverse_cols
        if neighbors_df[col].sum() > 0
    }

    # Confidence based on cohort size.
    if cohort_size >= 20:
        confidence = "high"
    elif cohort_size >= 10:
        confidence = "moderate"
    elif cohort_size >= 5:
        confidence = "low"
    else:
        confidence = "insufficient"

    summary = {
        "cohort_size": cohort_size,
        "confidence": confidence,
        "goal_achievement_rate": round(float(goal_rate), 3),
        "median_time_to_goal_months": median_time,
        "intervention_frequency": intervention_freq,
        "adverse_event_rates": adverse_rates,
    }

    logger.info(
        "Outcome summary: %d patients, %.0f%% goal achievement, confidence=%s",
        cohort_size,
        goal_rate * 100,
        confidence,
    )

    return summary
```

---

## Step 5: Cache Results in DynamoDB

*The pseudocode calls this `store_and_present`. We cache similarity results so repeated queries for the same patient don't recompute. Results expire when the feature store refreshes.*

```python
def cache_similarity_results(
    query_patient_id: str,
    similar_patients: list,
    outcome_summary: dict,
    feature_version: str = "v2026-03-15",
) -> dict:
    """
    Cache similarity results in DynamoDB with TTL-based expiration.

    Args:
        query_patient_id: The patient we queried for.
        similar_patients: List of similar patient matches.
        outcome_summary: Aggregated outcome data.
        feature_version: Version tag of the feature store used.

    Returns:
        The cached record (for confirmation).
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(CACHE_TABLE_NAME)

    now = int(datetime.now(timezone.utc).timestamp())

    # DynamoDB requires Decimal for numeric types, not float.
    # This helper converts floats in nested structures.
    record = {
        "patient_id": query_patient_id,
        "feature_version": feature_version,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "ttl": now + CACHE_TTL_SECONDS,
        "similar_patients": json.loads(
            json.dumps(similar_patients), parse_float=Decimal
        ),
        "outcome_summary": json.loads(
            json.dumps(outcome_summary), parse_float=Decimal
        ),
    }

    table.put_item(Item=record)

    logger.info(
        "Cached similarity results for %s (expires in %d seconds)",
        query_patient_id,
        CACHE_TTL_SECONDS,
    )

    return record

def check_cache(query_patient_id: str, feature_version: str) -> dict | None:
    """
    Check if we have cached similarity results for this patient.

    Returns the cached record if found and not expired, None otherwise.
    DynamoDB TTL handles expiration, but items may linger briefly after TTL.
    We check the feature_version to ensure results match current features.
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(CACHE_TABLE_NAME)

    response = table.get_item(
        Key={"patient_id": query_patient_id}
    )

    item = response.get("Item")
    if item and item.get("feature_version") == feature_version:
        logger.info("Cache hit for %s", query_patient_id)
        return item

    logger.info("Cache miss for %s", query_patient_id)
    return None
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda orchestrator would call (minus the DynamoDB caching if you're just experimenting locally).

```python
def run_patient_similarity_pipeline(
    query_patient_id: str,
    use_cache: bool = True,
    feature_version: str = "v2026-03-15",
) -> dict:
    """
    Run the full patient similarity pipeline for one patient.

    Generates a synthetic cohort (in production, this loads from S3),
    builds the similarity index, finds neighbors, aggregates outcomes,
    and returns a care-planning-ready summary.

    Args:
        query_patient_id: Patient ID to find similar patients for.
        use_cache: Whether to check/write DynamoDB cache.
        feature_version: Feature store version tag.

    Returns:
        Dict with similar patients and outcome summary.
    """

    # In production, check cache first to avoid redundant computation.
    # Commented out for local testing (requires DynamoDB table to exist).
    # if use_cache:
    #     cached = check_cache(query_patient_id, feature_version)
    #     if cached:
    #         return cached

    # Step 1: Load the patient cohort.
    # In production: load from S3 feature store (Parquet files).
    # Here: generate synthetic data for demonstration.
    print("Step 1: Loading patient cohort...")
    cohort = generate_synthetic_cohort(n_patients=500)
    print(f"  Loaded {len(cohort)} patients with {len(FEATURE_WEIGHTS)} features each")

    # Step 2: Build the similarity index.
    # In production: this is pre-built and loaded from a model artifact.
    # Here: we build it fresh each time (fast enough for 500 patients).
    print("Step 2: Building similarity index...")
    nn_model, scaler, feature_cols = build_similarity_index(cohort, FEATURE_WEIGHTS)
    print(f"  Index built with algorithm={nn_model.algorithm}")

    # Step 3: Find similar patients.
    print(f"Step 3: Finding patients similar to {query_patient_id}...")
    similar = find_similar_patients(
        query_patient_id=query_patient_id,
        cohort=cohort,
        nn_model=nn_model,
        scaler=scaler,
        feature_cols=feature_cols,
        feature_weights=FEATURE_WEIGHTS,
        k=K_NEIGHBORS,
        max_distance=MAX_DISTANCE_THRESHOLD,
    )
    print(f"  Found {len(similar)} similar patients")

    if not similar:
        print("  No similar patients found within distance threshold.")
        return {"query_patient_id": query_patient_id, "similar_patients": [], "outcome_summary": {}}

    # Print the top 5 matches for visibility.
    print("  Top 5 matches:")
    for match in similar[:5]:
        print(f"    {match['patient_id']}: similarity={match['similarity']}, distance={match['distance']}")

    # Step 4: Aggregate outcomes for the similar cohort.
    print("Step 4: Aggregating outcomes...")
    outcome_summary = aggregate_outcomes(similar, cohort)
    print(f"  Goal achievement rate: {outcome_summary['goal_achievement_rate']:.0%}")
    print(f"  Confidence: {outcome_summary['confidence']}")
    print(f"  Top interventions: {outcome_summary['intervention_frequency']}")

    # Step 5: Cache results (uncomment for production with DynamoDB).
    # if use_cache:
    #     cache_similarity_results(query_patient_id, similar, outcome_summary, feature_version)

    # Assemble the final result.
    # NOTE: similar_patients contains individual patient IDs. This is the
    # internal API response used for caching and audit logging. The care
    # planning UI should display only the aggregated outcome_summary by default.
    # If your organization permits drill-down into individual similar patient
    # records, gate that access behind break-the-glass authorization and log
    # each access as a HIPAA disclosure event.
    result = {
        "query_patient_id": query_patient_id,
        "feature_version": feature_version,
        "similar_patients": similar[:5],  # top 5 for display; outcome_summary uses all k neighbors
        "outcome_summary": outcome_summary,
    }

    print("\nDone. Result:")
    print(json.dumps(result, indent=2, default=str))

    return result

# --- Run it ---
if __name__ == "__main__":
    # Pick a patient from our synthetic cohort to query.
    # PAT-00042 is arbitrary; any valid patient_id works.
    result = run_patient_similarity_pipeline(query_patient_id="PAT-00042")
```

---

## Bonus: Explaining Why Patients Are Similar

Care managers need to understand why two patients are considered similar. "The algorithm says so" doesn't cut it in clinical decision support. This function provides feature-level explanations.

```python
def explain_similarity(
    query_patient_id: str,
    neighbor_patient_id: str,
    cohort: pd.DataFrame,
    feature_cols: list,
    feature_weights: dict,
) -> list:
    """
    Explain which features make two patients similar (or different).

    Returns a ranked list of features by their contribution to the
    distance between the two patients. Features with small differences
    (high agreement) are what makes them similar. Features with large
    differences are where they diverge.

    Args:
        query_patient_id: The query patient.
        neighbor_patient_id: A similar patient to explain.
        cohort: Full cohort DataFrame.
        feature_cols: Feature column names.
        feature_weights: Feature importance weights.

    Returns:
        List of dicts with feature name, query value, neighbor value,
        and weighted contribution to distance.
    """
    query_row = cohort[cohort["patient_id"] == query_patient_id][feature_cols].iloc[0]
    neighbor_row = cohort[cohort["patient_id"] == neighbor_patient_id][feature_cols].iloc[0]

    explanations = []
    for col in feature_cols:
        q_val = float(query_row[col])
        n_val = float(neighbor_row[col])
        weight = feature_weights[col]
        # Weighted absolute difference on RAW (unscaled) values.
        # Note: the actual similarity model uses StandardScaler-transformed
        # values before applying weights, so this explanation is an
        # approximation. The ranking of contributions here may differ from
        # the true distance decomposition. For precise explanations, pass
        # the fitted scaler and compute contributions on scaled values.
        contribution = abs(q_val - n_val) * weight

        explanations.append({
            "feature": col,
            "query_value": q_val,
            "neighbor_value": n_val,
            "weight": weight,
            "distance_contribution": round(contribution, 3),
        })

    # Sort by contribution: smallest first (most similar features at top).
    explanations.sort(key=lambda x: x["distance_contribution"])

    return explanations
```

Usage:

```python
# After running the pipeline, explain why the top match is similar.
if __name__ == "__main__":
    cohort = generate_synthetic_cohort(n_patients=500)
    _, _, feature_cols = build_similarity_index(cohort, FEATURE_WEIGHTS)

    explanation = explain_similarity(
        query_patient_id="PAT-00042",
        neighbor_patient_id="PAT-00187",  # replace with actual top match
        cohort=cohort,
        feature_cols=feature_cols,
        feature_weights=FEATURE_WEIGHTS,
    )

    print("\nSimilarity explanation (most similar features first):")
    for item in explanation[:5]:
        print(f"  {item['feature']}: query={item['query_value']}, "
              f"neighbor={item['neighbor_value']} (contribution={item['distance_contribution']})")

    print("\nBiggest differences:")
    for item in explanation[-3:]:
        print(f"  {item['feature']}: query={item['query_value']}, "
              f"neighbor={item['neighbor_value']} (contribution={item['distance_contribution']})")
```

---

## The Gap Between This and Production

This example works. Run it and you'll get a ranked list of similar patients with outcome summaries. But there's a meaningful distance between "works in a script with synthetic data" and "runs in a care planning system with real patients." Here's where that gap lives:

**Real feature engineering.** This example generates synthetic features. A production system runs a Glue ETL pipeline that extracts features from EHR data (Epic, Cerner, claims feeds), handles missing values (patients without recent labs), resolves temporal issues (which A1C value do you use if there are three in the past year?), and produces versioned feature snapshots. That pipeline is 80% of the work.

**Feature validation.** Before trusting any similarity metric, you need to validate that "similar features" actually predicts "similar outcomes" in your population. Split your cohort temporally: use historical patients to build the index, then check whether the nearest neighbors of recent patients actually had similar outcomes. If they didn't, your features aren't capturing what matters.

**Scale.** scikit-learn's NearestNeighbors works fine for 500 patients. For 500,000 patients (a typical health system's diabetes population over several years), you need approximate nearest neighbor algorithms. SageMaker's built-in kNN uses FAISS under the hood, which handles millions of vectors efficiently. OpenSearch's kNN plugin is another option if you want sub-second queries without managing a SageMaker endpoint.

**Feature drift monitoring.** Clinical practice changes. New drug classes emerge. Guidelines shift. A feature set designed today may not capture what matters in two years. You need automated monitoring that detects when the similarity metric's predictive power degrades, and a process for clinical review of features on a regular cadence.

**Bias auditing.** If your historical data reflects disparities (certain populations received less aggressive treatment), the similarity engine will reproduce those patterns. You need to audit outcomes by demographic subgroups and ensure the system doesn't systematically recommend less effective care for underserved populations. This is not optional.

**Explainability in the UI.** The `explain_similarity` function above is a starting point. A production system needs to present explanations in clinician-friendly language ("These patients are similar because they share A1C range, medication profile, and comorbidity pattern") rather than raw feature values.

**Error handling and retries.** This example has no error handling. A production system handles missing patients gracefully, retries failed S3 reads, validates that the feature store is fresh (not stale from a failed ETL run), and degrades gracefully when the similarity endpoint is unavailable.

**IAM least-privilege.** The Lambda orchestrator needs exactly: `s3:GetObject` on the feature store prefix, `dynamodb:GetItem` and `dynamodb:PutItem` on the cache table, and `sagemaker:InvokeEndpoint` on the specific similarity endpoint. Not `s3:*`. Not `AmazonSageMakerFullAccess`.

**VPC and encryption.** Patient features are PHI. The Lambda, SageMaker endpoint, and DynamoDB table should all be in a VPC with VPC endpoints. S3 uses SSE-KMS with a customer-managed key. DynamoDB encryption at rest is enabled by default but should use a CMK for key rotation control. All API calls are TLS (boto3 handles this automatically).

**DynamoDB Decimal handling.** This example already uses `json.loads(..., parse_float=Decimal)` for the cache write. Any numeric value going into DynamoDB must be a `Decimal`, not a Python `float`. boto3 will raise a `TypeError` on raw floats. The pattern shown here (serialize to JSON, then parse back with Decimal) is the standard workaround.

**Testing.** There are no tests here. A production system has unit tests for the feature engineering logic (with known inputs and expected outputs), integration tests for the similarity index (verify that known-similar patients are returned as neighbors), and regression tests that catch when model updates change results unexpectedly.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.6](chapter06.06-patient-similarity-care-planning.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
