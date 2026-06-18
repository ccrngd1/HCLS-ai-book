# Recipe 6.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 6.9. It demonstrates how you might build an SDOH phenotyping pipeline using synthetic data, Gower distance, and hierarchical clustering. It is not production-ready. The NLP extraction is simulated with synthetic data, the clustering uses a small patient set, and the community indicators are fabricated. Think of it as a workbench prototype: useful for understanding the shape of the solution, not something you'd deploy against real patient populations on Monday morning.

---

## Setup

You'll need the AWS SDK for Python and a few scientific computing libraries:

```bash
pip install boto3 numpy pandas scipy scikit-learn gower
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `comprehend:DetectEntitiesV2` (for NLP extraction via Comprehend Medical)
- `sagemaker-runtime:InvokeEndpoint` (for SDOH NER model)
- `s3:GetObject`, `s3:PutObject` (for data lake access)
- `dynamodb:PutItem`, `dynamodb:GetItem` (for phenotype store)
- `geo:SearchPlaceIndexForText` (for geocoding)

---

## Config and Constants

Before we get to the pipeline steps, here's the configuration that drives the whole system. SDOH domains, confidence thresholds, and the feature schema all live up front so you can see the data structures before the functions that use them.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Adaptive mode handles burst throttling
# with exponential backoff and jitter.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# The six core SDOH domains from the Gravity Project taxonomy.
# These are the categories we extract from notes and cluster on.
SDOH_DOMAINS = [
    "housing",
    "food",
    "transportation",
    "financial",
    "social_isolation",
    "safety",
]

# Keywords and phrases that signal each SDOH domain in clinical text.
# In production, you'd use a trained NER model. This lookup table
# demonstrates the concept of domain classification from text signals.
SDOH_KEYWORD_MAP = {
    "housing": [
        "homeless", "homelessness", "shelter", "unstable housing",
        "housing instability", "eviction", "couch surfing", "unhoused",
        "living in car", "no fixed address", "doubled up",
    ],
    "food": [
        "food insecurity", "food insecure", "hungry", "skipping meals",
        "food bank", "food stamps", "snap benefits", "cannot afford food",
        "limited grocery", "food desert", "malnourished",
    ],
    "transportation": [
        "no transportation", "transportation barrier", "cannot get to appointments",
        "missed appointments due to transport", "no car", "bus route",
        "ride share", "transportation insecurity", "no reliable transport",
    ],
    "financial": [
        "financial strain", "cannot afford", "medical debt", "uninsured",
        "underinsured", "cost barrier", "financial hardship", "behind on bills",
        "utility shutoff", "bankruptcy",
    ],
    "social_isolation": [
        "lives alone", "no family support", "socially isolated", "lonely",
        "no emergency contact", "widowed recently", "no social support",
        "limited social network", "caregiver burden",
    ],
    "safety": [
        "domestic violence", "intimate partner violence", "unsafe home",
        "abuse", "neglect", "elder abuse", "feels unsafe", "gun in home",
        "neighborhood violence",
    ],
}

# Negation cues. If these appear near an SDOH keyword, the mention
# is negated (patient does NOT have this issue).
NEGATION_CUES = [
    "denies", "denied", "no", "not", "without", "negative for",
    "rules out", "ruled out", "never", "none",
]

# How far back (in months) to look for SDOH signals when building features.
LOOKBACK_MONTHS = 24

# Phenotype assignments older than this are considered stale.
STALENESS_THRESHOLD_DAYS = 180

# Clustering parameters.
MIN_CLUSTERS = 4
MAX_CLUSTERS = 8

# DynamoDB table for phenotype assignments.
PHENOTYPE_TABLE_NAME = "patient-phenotypes"
```

---

## Step 1: NLP Extraction from Clinical Notes

*The pseudocode calls this `extract_sdoh_from_note(note_text, patient_id, encounter_date)`. In production, you'd call Amazon Comprehend Medical for broad entity detection and a fine-tuned SageMaker endpoint for SDOH-specific NER. Here we demonstrate the extraction logic with a keyword-based approach that shows the structure of what the real models produce.*

```python
def extract_sdoh_from_note(
    note_text: str,
    patient_id: str,
    encounter_date: str,
) -> list[dict]:
    """
    Extract SDOH mentions from a clinical note.

    In production, this function would:
    1. Call Comprehend Medical DetectEntitiesV2 for broad entity detection
    2. Call a SageMaker endpoint hosting a fine-tuned SDOH NER model
    3. Merge and deduplicate results from both passes

    For this example, we use keyword matching with negation detection
    to demonstrate the extraction structure. The output format matches
    what the real pipeline produces.

    Args:
        note_text: The full text of the clinical note.
        patient_id: Patient identifier for linking extractions.
        encounter_date: ISO date string for temporal tracking.

    Returns:
        List of extraction dicts, each with:
        - domain: which SDOH category (housing, food, etc.)
        - text_span: the matched text from the note
        - assertion: "AFFIRMED" or "NEGATED"
        - confidence: extraction confidence score (0-1)
        - patient_id: for downstream linkage
        - encounter_date: when this was documented
    """
    extractions = []
    note_lower = note_text.lower()

    for domain, keywords in SDOH_KEYWORD_MAP.items():
        for keyword in keywords:
            if keyword in note_lower:
                # Found a mention. Now check for negation.
                # Look at the 40 characters before the keyword for negation cues.
                keyword_pos = note_lower.index(keyword)
                prefix_window = note_lower[max(0, keyword_pos - 40):keyword_pos]

                is_negated = any(cue in prefix_window for cue in NEGATION_CUES)

                extractions.append({
                    "domain": domain,
                    "text_span": keyword,
                    "assertion": "NEGATED" if is_negated else "AFFIRMED",
                    # Keyword matching gets lower confidence than a trained model.
                    # A real NER model would output calibrated confidence scores.
                    "confidence": 0.65 if is_negated else 0.80,
                    "patient_id": patient_id,
                    "encounter_date": encounter_date,
                })
                # Only take the first match per domain per note to avoid
                # double-counting when multiple keywords from the same domain appear.
                break

    return extractions
```

---

## Step 2: Feature Assembly

*The pseudocode calls this `assemble_patient_features(patient_id, lookback_months)`. This step combines NLP extractions, structured screening data, and community indicators into a single feature vector per patient. The key design decision: distinguish "screened negative" from "never screened" by encoding missingness explicitly.*

```python
def assemble_patient_features(
    patient_id: str,
    extractions: list[dict],
    screening_data: Optional[dict],
    community_data: Optional[dict],
    note_count: int,
) -> dict:
    """
    Build a unified feature vector for one patient from multiple data sources.

    This combines:
    - NLP-derived features (from clinical note extractions)
    - Structured screening responses (if available)
    - Community-level indicators (if address is geocodable)
    - Derived features (burden score, documentation density)

    The feature vector uses explicit NULL for missing data rather than
    zero-filling. This matters because "no data" and "screened negative"
    are different signals for clustering.

    Args:
        patient_id: Patient identifier.
        extractions: All SDOH extractions for this patient in the lookback window.
        screening_data: Dict of screening scores, or None if never screened.
        community_data: Dict of community indicators, or None if no address.
        note_count: Total clinical notes in the lookback window.

    Returns:
        Dict of feature_name -> value (or None for missing).
    """
    features = {"patient_id": patient_id}

    # --- NLP-derived features (one set per SDOH domain) ---
    for domain in SDOH_DOMAINS:
        # Filter to affirmed mentions in this domain.
        affirmed = [
            e for e in extractions
            if e["domain"] == domain and e["assertion"] == "AFFIRMED"
        ]
        negated = [
            e for e in extractions
            if e["domain"] == domain and e["assertion"] == "NEGATED"
        ]

        # Binary presence: was this domain ever mentioned as active?
        features[f"{domain}_present"] = 1 if len(affirmed) > 0 else 0

        # Mention frequency: more mentions suggest persistence or severity.
        features[f"{domain}_mention_count"] = len(affirmed)

        # Recency: days since most recent affirmed mention.
        if affirmed:
            most_recent = max(e["encounter_date"] for e in affirmed)
            days_since = (
                datetime.date.today()
                - datetime.date.fromisoformat(most_recent)
            ).days
            features[f"{domain}_days_since_last"] = days_since
        else:
            features[f"{domain}_days_since_last"] = None

        # Was this domain explicitly negated? (patient screened negative)
        features[f"{domain}_negated"] = 1 if len(negated) > 0 else 0

    # --- Structured screening features ---
    if screening_data is not None:
        features["screening_completed"] = 1
        features["screening_food_score"] = screening_data.get("food_score")
        features["screening_housing_score"] = screening_data.get("housing_score")
        features["screening_transport_score"] = screening_data.get("transport_score")
        features["screening_financial_score"] = screening_data.get("financial_score")
        features["screening_social_score"] = screening_data.get("social_score")
        features["screening_safety_score"] = screening_data.get("safety_score")
    else:
        features["screening_completed"] = 0
        features["screening_food_score"] = None
        features["screening_housing_score"] = None
        features["screening_transport_score"] = None
        features["screening_financial_score"] = None
        features["screening_social_score"] = None
        features["screening_safety_score"] = None

    # --- Community-level features ---
    if community_data is not None:
        features["adi_national_rank"] = community_data.get("adi_rank")
        features["food_desert_flag"] = community_data.get("food_desert")
        features["svi_overall"] = community_data.get("svi_overall")
    else:
        features["adi_national_rank"] = None
        features["food_desert_flag"] = None
        features["svi_overall"] = None

    # --- Derived features ---
    # Total SDOH burden: count of domains with affirmed mentions.
    features["sdoh_burden_count"] = sum(
        1 for d in SDOH_DOMAINS if features[f"{d}_present"] == 1
    )

    # Documentation density: how many notes does this patient have?
    # Low note counts mean NLP absence is less informative.
    features["note_count"] = note_count
    total_mentions = sum(features[f"{d}_mention_count"] for d in SDOH_DOMAINS)
    features["sdoh_mention_density"] = (
        total_mentions / note_count if note_count > 0 else 0.0
    )

    return features
```

---

## Step 3: Gower Distance and Clustering

*The pseudocode calls this `cluster_patients(feature_matrix, min_k, max_k)`. We compute Gower distance (which handles mixed binary, continuous, and missing features natively) and then apply hierarchical agglomerative clustering. The optimal cluster count is chosen by silhouette score.*

```python
import gower

def prepare_feature_matrix(patient_features_list: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """
    Convert a list of patient feature dicts into a DataFrame suitable
    for Gower distance computation.

    Gower distance needs to know which columns are categorical (binary)
    vs. continuous. We encode that through pandas dtypes:
    - Binary/categorical columns: kept as int or category
    - Continuous columns: kept as float
    - Missing values: kept as NaN (Gower handles these by excluding
      the feature from that pair's distance calculation)

    Returns:
        Tuple of (DataFrame with one row per patient where columns are
        features, list of patient_id strings in matching row order).
        The patient_id column is dropped from the DataFrame (not a
        clustering feature).
    """
    df = pd.DataFrame(patient_features_list)

    # Store patient IDs separately; they're identifiers, not features.
    patient_ids = df["patient_id"].tolist()
    df = df.drop(columns=["patient_id"])

    # Convert None to NaN for proper missing-value handling.
    df = df.where(df.notna(), other=np.nan)

    # Ensure numeric types. Gower needs float for continuous columns.
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, patient_ids

def cluster_patients(
    feature_df: pd.DataFrame,
    min_k: int = MIN_CLUSTERS,
    max_k: int = MAX_CLUSTERS,
) -> tuple[np.ndarray, int, float]:
    """
    Cluster patients using Gower distance + hierarchical agglomerative clustering.

    Gower distance handles the mixed feature types in our matrix:
    - Binary features (domain_present): simple matching coefficient
    - Continuous features (ADI rank, SVI): range-normalized absolute difference
    - Missing values: excluded from that pair's distance (computed over shared features)

    We try cluster counts from min_k to max_k and pick the one with the
    best silhouette score. Silhouette measures how well-separated clusters are:
    range -1 to 1, higher is better, above 0.25 is reasonable for social data.

    Args:
        feature_df: DataFrame of patient features (no patient_id column).
        min_k: Minimum number of clusters to try.
        max_k: Maximum number of clusters to try.

    Returns:
        Tuple of (cluster_labels, best_k, best_silhouette_score).
    """
    from sklearn.metrics import silhouette_score

    # Compute the Gower distance matrix.
    # This is the expensive step: O(n^2) pairwise comparisons.
    # For 100K patients, you'd run this as a SageMaker Processing job.
    logger.info("Computing Gower distance matrix for %d patients", len(feature_df))
    distance_matrix = gower.gower_matrix(feature_df)

    # Convert to condensed form for scipy's linkage function.
    # scipy expects the upper triangle as a flat array.
    condensed_dist = squareform(distance_matrix, checks=False)

    # Hierarchical agglomerative clustering with average linkage (UPGMA).
    # Average linkage is valid for non-Euclidean distances like Gower.
    # Ward's linkage requires Euclidean distances and would produce
    # unreliable results here.
    logger.info("Running hierarchical clustering (average linkage)")
    Z = linkage(condensed_dist, method="average")

    # Try each candidate k and evaluate with silhouette score.
    best_k = min_k
    best_score = -1.0
    best_labels = None

    for k in range(min_k, max_k + 1):
        labels = fcluster(Z, t=k, criterion="maxclust")

        # Silhouette score needs at least 2 clusters and samples in each.
        n_unique = len(set(labels))
        if n_unique < 2:
            continue

        score = silhouette_score(distance_matrix, labels, metric="precomputed")
        logger.info("  k=%d: silhouette=%.3f", k, score)

        if score > best_score:
            best_score = score
            best_k = k
            best_labels = labels

    logger.info("Best clustering: k=%d, silhouette=%.3f", best_k, best_score)
    return best_labels, best_k, best_score
```

---

## Step 4: Phenotype Characterization and Equity Audit

*The pseudocode calls this `characterize_phenotypes(feature_matrix, cluster_labels, patient_demographics)`. This step turns raw cluster IDs into interpretable phenotype profiles and checks for demographic overrepresentation that could enable discrimination.*

```python
def characterize_phenotypes(
    feature_df: pd.DataFrame,
    labels: np.ndarray,
    patient_ids: list[str],
    demographics: dict[str, dict],
) -> list[dict]:
    """
    Characterize each cluster by its dominant SDOH features and run
    an equity audit on demographic composition.

    For each cluster, we compute:
    - Size (number of patients)
    - Prevalence of each SDOH domain (what % of cluster has this domain active)
    - Dominant domains (prevalence > 50%)
    - Average community indicators (ADI, SVI)
    - Demographic composition and overrepresentation flags

    The equity audit compares each cluster's racial composition to the
    overall population. If any group is overrepresented by more than 2x,
    we flag it. This doesn't mean the clustering is wrong, but it means
    you need to examine why and ensure the phenotype is used to direct
    resources, not to justify disparities.

    Args:
        feature_df: The feature matrix used for clustering.
        labels: Cluster assignment for each patient (1-indexed from fcluster).
        patient_ids: Patient IDs in the same order as feature_df rows.
        demographics: Dict of patient_id -> {"race": ..., "ethnicity": ...}

    Returns:
        List of phenotype profile dicts.
    """
    # Compute overall demographic distribution for comparison.
    all_races = [demographics.get(pid, {}).get("race", "Unknown") for pid in patient_ids]
    overall_race_dist = pd.Series(all_races).value_counts(normalize=True).to_dict()

    phenotypes = []
    unique_labels = sorted(set(labels))

    for cluster_id in unique_labels:
        mask = labels == cluster_id
        cluster_df = feature_df[mask]
        cluster_pids = [pid for pid, m in zip(patient_ids, mask) if m]
        cluster_size = len(cluster_df)

        # Domain prevalence: what fraction of this cluster has each domain active?
        profile = {}
        for domain in SDOH_DOMAINS:
            col = f"{domain}_present"
            if col in cluster_df.columns:
                prevalence = cluster_df[col].mean()
                profile[domain] = round(prevalence, 3)
            else:
                profile[domain] = 0.0

        # Dominant domains: prevalence > 50% in this cluster.
        dominant = [d for d, p in profile.items() if p > 0.5]

        # Community indicator averages.
        avg_adi = cluster_df["adi_national_rank"].mean() if "adi_national_rank" in cluster_df else None
        avg_svi = cluster_df["svi_overall"].mean() if "svi_overall" in cluster_df else None

        # --- Equity audit ---
        cluster_races = [
            demographics.get(pid, {}).get("race", "Unknown") for pid in cluster_pids
        ]
        cluster_race_dist = pd.Series(cluster_races).value_counts(normalize=True).to_dict()

        equity_flags = []
        for race, cluster_pct in cluster_race_dist.items():
            overall_pct = overall_race_dist.get(race, 0.01)
            ratio = cluster_pct / overall_pct if overall_pct > 0 else 0
            if ratio > 2.0:
                equity_flags.append({
                    "race": race,
                    "cluster_pct": round(cluster_pct, 3),
                    "overall_pct": round(overall_pct, 3),
                    "overrepresentation_ratio": round(ratio, 2),
                })

        phenotypes.append({
            "cluster_id": int(cluster_id),
            "size": cluster_size,
            "domain_prevalence": profile,
            "dominant_domains": dominant,
            "avg_adi": round(float(avg_adi), 1) if avg_adi and not np.isnan(avg_adi) else None,
            "avg_svi": round(float(avg_svi), 3) if avg_svi and not np.isnan(avg_svi) else None,
            "equity_flags": equity_flags,
            "name": None,  # Assigned by clinical team after review
        })

    return phenotypes
```

---

## Step 5: Store Phenotype Assignments

*The pseudocode calls this `store_phenotype_assignment(patient_id, phenotype, confidence, feature_snapshot)`. This writes each patient's phenotype to DynamoDB for real-time lookup by care management systems. Includes a staleness date so downstream systems know when to trigger re-evaluation.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

def store_phenotype_assignment(
    patient_id: str,
    phenotype: dict,
    confidence: float,
    model_version: str = "v1.0",
) -> dict:
    """
    Write a patient's phenotype assignment to DynamoDB.

    The record includes everything a care management system needs:
    - Which phenotype this patient belongs to
    - How confident the assignment is
    - When it was assigned (for staleness tracking)
    - When it expires (stale_after date)
    - The model version that produced it (for reproducibility)

    Args:
        patient_id: Patient identifier (partition key).
        phenotype: The phenotype profile dict from characterize_phenotypes.
        confidence: Membership confidence (0-1). For hard clustering this
                    is derived from distance to centroid; for soft clustering
                    it's the posterior probability.
        model_version: Version string for the clustering model.

    Returns:
        The record that was written.
    """
    table = dynamodb.Table(PHENOTYPE_TABLE_NAME)

    now = datetime.datetime.now(timezone.utc)
    stale_date = (now + datetime.timedelta(days=STALENESS_THRESHOLD_DAYS)).date()

    record = {
        "patient_id": patient_id,
        "phenotype_id": phenotype["cluster_id"],
        "phenotype_name": phenotype.get("name") or f"Cluster {phenotype['cluster_id']}",
        "dominant_domains": phenotype["dominant_domains"],
        "confidence": Decimal(str(round(confidence, 3))),
        "assigned_date": now.isoformat(),
        "stale_after": stale_date.isoformat(),
        "version": model_version,
    }

    table.put_item(Item=record)
    return record
```

---

## Putting It All Together

Here's the full pipeline assembled with synthetic data so you can see the end-to-end flow. In production, the data would come from your EHR extract, screening database, and geocoded community indicators. Here we generate synthetic patients to demonstrate the mechanics.

```python
import random

def generate_synthetic_patients(n_patients: int = 200) -> tuple[list, list, dict]:
    """
    Generate synthetic patient data for demonstration.

    Creates patients with varying SDOH profiles:
    - Some with housing + food issues (correlated, as they often are in reality)
    - Some with transportation barriers only
    - Some with social isolation
    - Some with multi-domain complexity
    - Many with no documented SDOH (the "low information" group)

    Returns:
        Tuple of (patient_features_list, patient_ids, demographics_dict)
    """
    random.seed(42)
    np.random.seed(42)

    patient_features = []
    demographics = {}

    # Define synthetic patient archetypes with probabilities.
    # These roughly mirror what you'd see in a real health system.
    archetypes = [
        # (weight, domains_active, screening_available, community_deprived)
        (0.15, ["housing", "food", "financial"], True, True),
        (0.20, ["transportation"], False, False),
        (0.10, ["social_isolation", "safety"], True, True),
        (0.05, ["housing", "food", "transportation", "financial", "social_isolation"], True, True),
        (0.50, [], False, False),  # Low documentation / no SDOH signal
    ]

    races = ["White", "Black", "Hispanic", "Asian", "Other"]
    # Intentionally skewed to test equity audit.
    race_weights_by_archetype = [
        [0.30, 0.35, 0.20, 0.10, 0.05],  # Housing+food: overrepresents Black
        [0.50, 0.20, 0.15, 0.10, 0.05],  # Transport: roughly population
        [0.60, 0.15, 0.10, 0.10, 0.05],  # Isolation: overrepresents White (elderly)
        [0.20, 0.40, 0.25, 0.10, 0.05],  # Multi-domain: overrepresents Black
        [0.55, 0.20, 0.15, 0.07, 0.03],  # Low info: roughly population
    ]

    patient_id_counter = 0
    for arch_idx, (weight, domains, has_screening, is_deprived) in enumerate(archetypes):
        n_in_group = int(n_patients * weight)

        for _ in range(n_in_group):
            patient_id_counter += 1
            pid = f"PAT-{patient_id_counter:06d}"

            # Generate synthetic note extractions.
            extractions = []
            for domain in SDOH_DOMAINS:
                if domain in domains:
                    # Active domain: generate 1-4 affirmed mentions.
                    n_mentions = random.randint(1, 4)
                    for m in range(n_mentions):
                        days_ago = random.randint(10, 300)
                        enc_date = (
                            datetime.date.today() - datetime.timedelta(days=days_ago)
                        ).isoformat()
                        extractions.append({
                            "domain": domain,
                            "text_span": f"synthetic_{domain}_mention",
                            "assertion": "AFFIRMED",
                            "confidence": random.uniform(0.7, 0.95),
                            "patient_id": pid,
                            "encounter_date": enc_date,
                        })
                else:
                    # Inactive domain: occasionally add a negated mention.
                    if random.random() < 0.15:
                        enc_date = (
                            datetime.date.today()
                            - datetime.timedelta(days=random.randint(30, 400))
                        ).isoformat()
                        extractions.append({
                            "domain": domain,
                            "text_span": f"denies_{domain}",
                            "assertion": "NEGATED",
                            "confidence": 0.85,
                            "patient_id": pid,
                            "encounter_date": enc_date,
                        })

            # Screening data (only for some patients).
            screening = None
            if has_screening and random.random() < 0.6:
                screening = {
                    "food_score": random.randint(2, 8) if "food" in domains else random.randint(0, 2),
                    "housing_score": random.randint(2, 8) if "housing" in domains else random.randint(0, 2),
                    "transport_score": random.randint(2, 8) if "transportation" in domains else random.randint(0, 2),
                    "financial_score": random.randint(2, 8) if "financial" in domains else random.randint(0, 2),
                    "social_score": random.randint(2, 8) if "social_isolation" in domains else random.randint(0, 2),
                    "safety_score": random.randint(2, 8) if "safety" in domains else random.randint(0, 2),
                }

            # Community indicators.
            community = None
            if random.random() < 0.8:  # 80% have geocodable addresses
                if is_deprived:
                    community = {
                        "adi_rank": random.randint(60, 99),
                        "food_desert": random.choice([0, 1]),
                        "svi_overall": round(random.uniform(0.6, 0.98), 2),
                    }
                else:
                    community = {
                        "adi_rank": random.randint(10, 55),
                        "food_desert": 0,
                        "svi_overall": round(random.uniform(0.1, 0.45), 2),
                    }

            # Assemble features.
            note_count = random.randint(3, 30)
            features = assemble_patient_features(
                patient_id=pid,
                extractions=extractions,
                screening_data=screening,
                community_data=community,
                note_count=note_count,
            )
            patient_features.append(features)

            # Demographics for equity audit.
            race = random.choices(races, weights=race_weights_by_archetype[arch_idx])[0]
            demographics[pid] = {"race": race}

    return patient_features, [f["patient_id"] for f in patient_features], demographics

def run_phenotyping_pipeline():
    """
    Execute the full SDOH phenotyping pipeline on synthetic data.

    This demonstrates the end-to-end flow:
    1. Generate synthetic patient data (simulates NLP extraction + screening + community data)
    2. Assemble feature matrix
    3. Cluster patients using Gower distance + hierarchical clustering
    4. Characterize phenotypes and run equity audit
    5. Display results

    In production, Step 1 would be replaced by actual Comprehend Medical calls,
    SageMaker endpoint invocations, Glue ETL jobs, and Location Service geocoding.
    """
    print("=" * 70)
    print("SDOH Phenotyping Pipeline (Synthetic Data Demo)")
    print("=" * 70)

    # Step 1: Generate synthetic patients with known SDOH profiles.
    print("\nStep 1: Generating synthetic patient data...")
    patient_features, patient_ids, demographics = generate_synthetic_patients(n_patients=200)
    print(f"  Generated {len(patient_features)} patients")

    # Step 2: Build the feature matrix.
    print("\nStep 2: Preparing feature matrix...")
    feature_df, ordered_ids = prepare_feature_matrix(patient_features)
    print(f"  Feature matrix shape: {feature_df.shape}")
    print(f"  Features: {list(feature_df.columns)[:10]}... ({len(feature_df.columns)} total)")

    # Step 3: Cluster patients.
    print("\nStep 3: Clustering patients...")
    labels, best_k, best_silhouette = cluster_patients(feature_df)
    print(f"  Optimal clusters: {best_k}")
    print(f"  Silhouette score: {best_silhouette:.3f}")

    # Step 4: Characterize phenotypes.
    print("\nStep 4: Characterizing phenotypes...")
    phenotypes = characterize_phenotypes(feature_df, labels, ordered_ids, demographics)

    print("\n" + "=" * 70)
    print("PHENOTYPE CATALOG")
    print("=" * 70)

    for p in phenotypes:
        print(f"\n  Cluster {p['cluster_id']}: {p.get('name') or '(unnamed)'}")
        print(f"    Size: {p['size']} patients")
        print(f"    Dominant domains: {p['dominant_domains'] or ['none']}")
        print(f"    Domain prevalence:")
        for domain, prev in p["domain_prevalence"].items():
            if prev > 0.1:
                print(f"      {domain}: {prev:.1%}")
        if p["avg_adi"]:
            print(f"    Avg ADI rank: {p['avg_adi']}")
        if p["avg_svi"]:
            print(f"    Avg SVI: {p['avg_svi']}")
        if p["equity_flags"]:
            print(f"    ⚠️  EQUITY FLAGS:")
            for flag in p["equity_flags"]:
                print(
                    f"      {flag['race']}: {flag['cluster_pct']:.1%} in cluster "
                    f"vs {flag['overall_pct']:.1%} overall "
                    f"({flag['overrepresentation_ratio']}x overrepresented)"
                )

    # Step 5: Show a sample phenotype assignment (without writing to DynamoDB).
    print("\n" + "=" * 70)
    print("SAMPLE PHENOTYPE ASSIGNMENT")
    print("=" * 70)

    sample_idx = 0
    sample_pid = ordered_ids[sample_idx]
    sample_phenotype = next(p for p in phenotypes if p["cluster_id"] == labels[sample_idx])

    assignment = {
        "patient_id": sample_pid,
        "phenotype_id": sample_phenotype["cluster_id"],
        "phenotype_name": sample_phenotype.get("name") or f"Cluster {sample_phenotype['cluster_id']}",
        "dominant_domains": sample_phenotype["dominant_domains"],
        "confidence": 0.84,
        "assigned_date": datetime.datetime.now(timezone.utc).isoformat(),
        "stale_after": (
            datetime.date.today() + datetime.timedelta(days=STALENESS_THRESHOLD_DAYS)
        ).isoformat(),
        "version": "v1.0-synthetic",
    }
    print(f"\n{json.dumps(assignment, indent=2, default=str)}")

    return phenotypes

if __name__ == "__main__":
    phenotypes = run_phenotyping_pipeline()
```

---

## The Gap Between This and Production

This example runs end-to-end on synthetic data and produces interpretable SDOH phenotypes. But there's a significant distance between "works on my laptop with fake data" and "runs at a health system processing real patient notes." Here's where that gap lives:

**NLP extraction quality.** The keyword-matching approach here catches maybe 40% of what a trained NER model would find. Real clinical text uses indirect language ("patient reports difficulty maintaining diet due to limited grocery access" instead of "food insecurity"). A production system uses Amazon Comprehend Medical for broad entity detection plus a fine-tuned transformer model on SageMaker for SDOH-specific extraction. Training that model requires annotated clinical text, which requires clinical annotators, which requires IRB approval and months of work.

**Scale.** Gower distance computation is O(n^2). For 200 patients, it takes milliseconds. For 100,000 patients, it takes hours and requires distributed computation. In production, you'd run this as a SageMaker Processing job with a larger instance type (ml.m5.4xlarge or bigger), or use approximate nearest-neighbor methods to avoid the full pairwise computation.

**Error handling and retries.** Every AWS API call (Comprehend Medical, SageMaker, DynamoDB, Location Service) can fail transiently. Production code wraps each call in try/except with specific handling for throttling (exponential backoff), service errors (retry with jitter), and validation errors (log and skip). The `BOTO3_RETRY_CONFIG` handles some of this, but you need application-level retry logic for multi-step pipelines where partial failures need cleanup.

**Input validation.** This code trusts its inputs. A production system validates that note text isn't empty, that patient IDs match expected formats, that screening scores are within valid ranges, and that community indicator values are plausible. Garbage in, garbage out applies doubly when the output drives care decisions.

**Temporal handling.** The synthetic data uses simple date arithmetic. Real temporal reasoning is harder: you need to handle timezone-aware timestamps, account for documentation lag (a note written today about a conversation from last week), and implement proper lookback windows that respect encounter dates rather than note creation dates.

**DynamoDB data types.** All numeric values going into DynamoDB must be wrapped in `Decimal()`. The example does this for the confidence score, but in a full implementation every float in the feature snapshot would need the same treatment. The `boto3` DynamoDB resource layer raises a `TypeError` on raw floats.

**VPC and network isolation.** In production, the SageMaker endpoints, Glue jobs, and Lambda functions all run inside a VPC with private subnets. VPC endpoints for S3, DynamoDB, Comprehend Medical, SageMaker Runtime, and CloudWatch Logs keep all traffic on the AWS backbone. Clinical notes contain PHI and should never traverse the public internet.

**Encryption.** All S3 buckets use SSE-KMS with customer-managed keys. DynamoDB uses encryption at rest. SageMaker model artifacts and endpoint traffic are encrypted. KMS key policies restrict access to specific IAM roles. Key rotation is enabled.

**Equity audit rigor.** The equity check here uses a simple 2x overrepresentation threshold. A production system would use statistical tests (chi-squared, standardized residuals), intersectional analysis (race x gender x age), and would document the audit results as part of the model card. The audit isn't a one-time check; it runs every time the clustering is refreshed.

**Clinical validation.** The clusters this code produces are statistically valid but not clinically validated. Before deploying phenotype assignments to care management systems, you need social workers and care managers to review the cluster profiles, assign meaningful names, confirm that the groupings match their clinical intuition, and verify that the recommended interventions make sense for each phenotype. This is weeks of work with clinical stakeholders.

**Staleness and re-evaluation.** The `stale_after` date is set but nothing in this example actually checks it. A production system has a scheduled job that identifies patients with stale phenotypes and triggers re-evaluation: re-running NLP on recent notes, checking for new screening data, and re-assigning the phenotype if the patient's circumstances have changed.

**Logging and monitoring.** Production needs structured logging (JSON format for CloudWatch Logs Insights), extraction quality metrics (precision/recall tracked over time), cluster stability monitoring (are phenotype distributions shifting?), and alerting when the pipeline fails or produces anomalous results.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.9](chapter06.09-social-determinant-phenotyping.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
