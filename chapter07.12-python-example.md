# Recipe 7.12: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the cohort matching and case-based reasoning pipeline from Recipe 7.12. It demonstrates the core concepts (synthetic claims with novelty scenarios, feature embedding, k-nearest-neighbors retrieval, distance-based confidence scoring, denial archetype clustering, and OpenSearch k-NN integration via boto3) using synthetic data. It is not production-ready. Real case-based reasoning systems require validated embedding models trained on actual adjudication outcomes, continuously refreshed vector indexes, and careful calibration of novelty thresholds against your actual payer landscape. Think of this as the whiteboard sketch that shows you the shape of each piece, not the deployment blueprint.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy pandas scikit-learn matplotlib
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpGet` (for OpenSearch k-NN index operations)
- `sagemaker:InvokeEndpoint` (for the embedding model endpoint, if using SageMaker)
- `s3:GetObject`, `s3:PutObject` (for embedding storage and batch outputs)
- `dynamodb:PutItem`, `dynamodb:GetItem` (for hybrid prediction results)

For this example, we build everything locally with scikit-learn first (kNN retrieval, clustering, novelty scoring), then show how you'd wire the vector search into Amazon OpenSearch Service via boto3. The local version lets you see the full pipeline without incurring AWS costs.

---

## Config and Constants

These control the synthetic data generation, embedding pipeline, and decision thresholds. In production, these would come from your actual claims history and be calibrated empirically against holdout sets.

```python
import logging
from decimal import Decimal

# Structured logging. Never log PHI (patient names, MRNs, specific diagnosis
# details in combination with identifying info). Log claim_id for tracing.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Novelty and confidence thresholds ---
# These define when a claim is "too far" from known history to trust the
# primary model. Calibrate against your holdout set: find the distance
# where prediction accuracy drops below acceptable levels.
NOVELTY_THRESHOLD = 0.4          # Mean distance to top-5 neighbors above this = novel
DISAGREEMENT_THRESHOLD = 0.25    # |primary_score - knn_score| above this = conflicting
COLD_START_MIN_CLAIMS = 50       # Minimum payer history to trust primary model

# --- kNN retrieval parameters ---
K_NEIGHBORS = 20                 # Retrieve this many neighbors from the index
K_VOTE = 10                      # Use top-k for the weighted vote prediction

# --- Clustering parameters ---
N_DENIAL_CLUSTERS = 5            # Number of denial archetype clusters

# --- Synthetic data parameters ---
NUM_HISTORICAL_CLAIMS = 10000    # Resolved claims in our "history"
NUM_NOVEL_CLAIMS = 50            # Deliberately novel test claims

# --- Payer definitions (same as 7.11 for consistency) ---
KNOWN_PAYERS = ["BCBS", "UnitedHealthcare", "Aetna", "Cigna", "Humana",
                "Medicare", "Medicaid", "Tricare"]
# Novel payers that won't appear in training history
NOVEL_PAYERS = ["RegionalHealth_New", "StartupPayer_X", "MicroPlan_Z"]

# --- CPT codes with rough denial-risk weights ---
CPT_CODES = {
    "99213": 0.5, "99214": 0.6, "99215": 0.9, "27447": 1.8,
    "29881": 1.6, "43239": 1.4, "70553": 1.5, "72148": 1.3,
    "90837": 0.7, "99283": 0.4, "99285": 0.6, "20610": 0.8,
    "64483": 1.5, "77067": 0.3, "36415": 0.2,
}

# --- Place of service ---
PLACE_OF_SERVICE = ["11", "21", "22", "23", "24", "31", "81"]

# --- Provider types ---
PROVIDER_TYPES = ["MD", "DO", "NP", "PA", "Facility"]

# --- Common modifiers ---
MODIFIERS = ["25", "26", "59", "76", "LT", "RT"]

# --- ICD-10 codes (simplified subset) ---
ICD10_CODES = [
    "M17.11", "M54.5", "I10", "E11.9", "J06.9", "K21.0",
    "G43.909", "F32.1", "M79.3", "R10.9", "Z00.00", "Z12.31",
    "S82.001A", "M25.511", "J18.9",
]

# --- Denial reason codes for clustering ---
DENIAL_REASONS = [
    "no_prior_auth", "medical_necessity", "timely_filing",
    "bundling_error", "coding_error", "duplicate", "not_covered",
]

# --- OpenSearch configuration ---
OPENSEARCH_ENDPOINT = "https://my-claims-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_INDEX = "claim-vectors"
EMBEDDING_DIM = 64  # Dimensions for our claim embedding vector
```

---

## Step 1: Generate Synthetic Claims Data (Including Novel Cases)

*The main recipe's embedding pipeline operates on real resolved claims. Here we generate synthetic claims with realistic feature distributions, deliberate payer-procedure denial patterns, and a set of "novel" claims whose payer-procedure combinations are absent from the training history. This lets us demonstrate the novelty detection signal.*

```python
import numpy as np
import pandas as pd

def generate_claims_history(n_claims: int = NUM_HISTORICAL_CLAIMS,
                            seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic resolved claims with known outcomes.

    Key design choices:
    - Denial probability depends on payer + procedure + PA status interactions
    - Only KNOWN_PAYERS appear here (novel payers are reserved for test set)
    - Each claim gets a denial_reason if denied, which we use for clustering
    """
    rng = np.random.default_rng(seed)

    cpt_list = list(CPT_CODES.keys())
    payer_denial_rates = {
        "BCBS": 0.09, "UnitedHealthcare": 0.14, "Aetna": 0.11,
        "Cigna": 0.10, "Humana": 0.13, "Medicare": 0.07,
        "Medicaid": 0.16, "Tricare": 0.08,
    }

    data = {
        "claim_id": [f"HIST-{i:07d}" for i in range(n_claims)],
        "payer": rng.choice(KNOWN_PAYERS, n_claims),
        "cpt_code": rng.choice(cpt_list, n_claims),
        "icd10_primary": rng.choice(ICD10_CODES, n_claims),
        "place_of_service": rng.choice(PLACE_OF_SERVICE, n_claims),
        "provider_type": rng.choice(PROVIDER_TYPES, n_claims),
        "claim_amount": np.round(rng.lognormal(6.0, 1.2, n_claims), 2),
        "patient_age": rng.integers(18, 90, n_claims),
        "num_modifiers": rng.integers(0, 4, n_claims),
        "has_modifier_25": rng.choice([0, 1], n_claims, p=[0.8, 0.2]),
        "has_modifier_59": rng.choice([0, 1], n_claims, p=[0.85, 0.15]),
    }
    df = pd.DataFrame(data)

    # Prior auth logic: high-risk procedures more likely to require PA
    pa_required_prob = df["cpt_code"].map(
        lambda c: 0.7 if CPT_CODES.get(c, 1.0) > 1.3 else 0.1
    )
    df["pa_required"] = rng.binomial(1, pa_required_prob)
    df["pa_on_file"] = np.where(
        df["pa_required"] == 1, rng.binomial(1, 0.70, n_claims), 0
    )

    # Compute denial probability from feature interactions
    denial_prob = df["payer"].map(payer_denial_rates).values.astype(float)
    cpt_mult = df["cpt_code"].map(CPT_CODES).fillna(1.0).values
    denial_prob = denial_prob * cpt_mult

    # PA missing = near-guarantee of denial
    pa_missing = (df["pa_required"] == 1) & (df["pa_on_file"] == 0)
    denial_prob = np.where(pa_missing, np.clip(denial_prob + 0.55, 0, 0.95), denial_prob)

    # High claim amounts get more scrutiny
    denial_prob = np.where(df["claim_amount"] > 5000, denial_prob * 1.15, denial_prob)

    # Add noise, clip, generate binary outcome
    denial_prob = np.clip(denial_prob + rng.normal(0, 0.03, n_claims), 0.01, 0.95)
    df["denied"] = rng.binomial(1, denial_prob)

    # Assign denial reasons (only for denied claims)
    # Weight reasons based on features for realistic clustering patterns
    denied_mask = df["denied"] == 1
    n_denied = denied_mask.sum()

    # PA-missing claims get "no_prior_auth" reason
    reasons = np.full(n_claims, "", dtype=object)
    pa_denial_mask = denied_mask & pa_missing
    reasons[pa_denial_mask] = "no_prior_auth"

    # Remaining denied claims get other reasons
    remaining_denied = denied_mask & ~pa_denial_mask
    n_remaining = remaining_denied.sum()
    other_reasons = ["medical_necessity", "timely_filing", "bundling_error",
                     "coding_error", "not_covered"]
    reasons[remaining_denied] = rng.choice(other_reasons, n_remaining)
    df["denial_reason"] = reasons

    logger.info(
        "Generated %d historical claims. Denial rate: %.1f%%",
        n_claims, df["denied"].mean() * 100
    )
    return df


def generate_novel_claims(n_claims: int = NUM_NOVEL_CLAIMS,
                          seed: int = 99) -> pd.DataFrame:
    """
    Generate claims that are deliberately OUT OF DISTRIBUTION.

    These use novel payers (not in training history) and unusual
    payer-procedure combinations. This is the cold-start scenario
    the novelty detector should catch.
    """
    rng = np.random.default_rng(seed)

    cpt_list = list(CPT_CODES.keys())

    data = {
        "claim_id": [f"NOVEL-{i:05d}" for i in range(n_claims)],
        # Mix of novel payers and known payers with unusual combos
        "payer": rng.choice(NOVEL_PAYERS + ["Medicare"], n_claims, p=[0.3, 0.3, 0.3, 0.1]),
        "cpt_code": rng.choice(cpt_list, n_claims),
        "icd10_primary": rng.choice(ICD10_CODES, n_claims),
        "place_of_service": rng.choice(PLACE_OF_SERVICE, n_claims),
        "provider_type": rng.choice(PROVIDER_TYPES, n_claims),
        "claim_amount": np.round(rng.lognormal(7.0, 1.5, n_claims), 2),
        "patient_age": rng.integers(18, 90, n_claims),
        "num_modifiers": rng.integers(0, 4, n_claims),
        "has_modifier_25": rng.choice([0, 1], n_claims, p=[0.7, 0.3]),
        "has_modifier_59": rng.choice([0, 1], n_claims, p=[0.75, 0.25]),
        "pa_required": rng.choice([0, 1], n_claims, p=[0.4, 0.6]),
        "pa_on_file": rng.choice([0, 1], n_claims, p=[0.5, 0.5]),
    }
    df = pd.DataFrame(data)

    # Novel claims don't have outcomes yet (they're new, unresolved)
    # But for evaluation, we assign ground truth so we can measure accuracy
    df["denied"] = rng.choice([0, 1], n_claims, p=[0.4, 0.6])
    df["denial_reason"] = np.where(
        df["denied"] == 1,
        rng.choice(DENIAL_REASONS, n_claims),
        ""
    )

    logger.info("Generated %d novel/OOD claims for testing", n_claims)
    return df
```

---

## Step 2: Build Feature Vectors with Proper Encoding and Scaling

*The main recipe's Step 1 describes computing claim embeddings. kNN is notoriously scale-sensitive: if billed amount ranges from $10 to $500,000 and categorical features are 0/1, the distance metric is dominated by dollar differences. Here we handle categorical encoding (one-hot for low-cardinality, frequency encoding for high-cardinality) and standard scaling so all features contribute proportionally.*

```python
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

# Feature columns grouped by type
CATEGORICAL_FEATURES = ["payer", "cpt_code", "icd10_primary",
                        "place_of_service", "provider_type"]
NUMERIC_FEATURES = ["claim_amount", "patient_age", "num_modifiers",
                    "has_modifier_25", "has_modifier_59",
                    "pa_required", "pa_on_file"]


def build_embedding_pipeline() -> ColumnTransformer:
    """
    Build a sklearn ColumnTransformer that encodes claims into fixed-length
    numeric vectors suitable for distance computation.

    For kNN, feature scaling matters enormously. Without it, high-magnitude
    features (claim_amount) dominate the distance metric and low-magnitude
    features (binary flags) become irrelevant.

    We use:
    - OneHotEncoder for categoricals (creates sparse binary columns)
    - StandardScaler for numerics (mean=0, std=1)

    The output is a dense matrix where all features are on comparable scales.
    """
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             CATEGORICAL_FEATURES),
            ("num", StandardScaler(), NUMERIC_FEATURES),
        ],
        remainder="drop"
    )
    return preprocessor


def compute_embeddings(df: pd.DataFrame, preprocessor: ColumnTransformer,
                       fit: bool = False) -> np.ndarray:
    """
    Transform a claims DataFrame into a numeric embedding matrix.

    Args:
        df: Claims data with the expected feature columns
        preprocessor: Fitted (or to-be-fitted) ColumnTransformer
        fit: If True, fit the transformer on this data first

    Returns:
        numpy array of shape (n_claims, embedding_dim)
    """
    if fit:
        embeddings = preprocessor.fit_transform(df)
    else:
        embeddings = preprocessor.transform(df)

    logger.info(
        "Computed embeddings: %d claims x %d dimensions",
        embeddings.shape[0], embeddings.shape[1]
    )
    return embeddings
```

---

## Step 3: k-Nearest Neighbors Retrieval and Prediction

*The main recipe's Step 3 queries the vector index for neighbors. Here we implement the full kNN retrieval locally using scikit-learn's NearestNeighbors (which uses a ball tree or KD-tree for efficient search). For each new claim, we find the k most similar resolved claims, derive a weighted-vote prediction from their outcomes, and compute distance-based confidence.*

```python
from sklearn.neighbors import NearestNeighbors

def build_knn_index(history_embeddings: np.ndarray,
                    n_neighbors: int = K_NEIGHBORS) -> NearestNeighbors:
    """
    Build a k-NN index over historical claim embeddings.

    We use cosine distance (metric="cosine") because it handles the mix of
    one-hot encoded categoricals and scaled numerics well. Cosine measures
    the angle between vectors, not the magnitude, so a high-dollar claim
    and a low-dollar claim with the same feature pattern will still be
    "close" in cosine space.

    In production, this index lives in OpenSearch. Here we use sklearn
    for demonstration.
    """
    knn = NearestNeighbors(
        n_neighbors=n_neighbors,
        metric="cosine",
        algorithm="brute",  # brute-force is fine for <100k vectors
    )
    knn.fit(history_embeddings)
    logger.info("Built kNN index over %d vectors", history_embeddings.shape[0])
    return knn


def retrieve_neighbors(knn_index: NearestNeighbors,
                       query_embedding: np.ndarray,
                       history_df: pd.DataFrame,
                       k: int = K_NEIGHBORS) -> list:
    """
    For a single new claim embedding, find the k nearest resolved claims.

    Returns a list of dicts with neighbor metadata, outcome, and distance.
    Distance here is cosine distance (0 = identical, 1 = orthogonal).
    """
    # query_embedding should be shape (1, n_features)
    if query_embedding.ndim == 1:
        query_embedding = query_embedding.reshape(1, -1)

    distances, indices = knn_index.kneighbors(query_embedding, n_neighbors=k)

    neighbors = []
    for dist, idx in zip(distances[0], indices[0]):
        row = history_df.iloc[idx]
        neighbors.append({
            "claim_id": row["claim_id"],
            "distance": float(dist),          # cosine distance
            "similarity": 1.0 - float(dist),  # convert to similarity
            "outcome": "denied" if row["denied"] == 1 else "paid",
            "denial_reason": row["denial_reason"],
            "payer": row["payer"],
            "cpt_code": row["cpt_code"],
            "claim_amount": float(row["claim_amount"]),
        })

    return neighbors


def compute_knn_prediction(neighbors: list,
                           k_vote: int = K_VOTE) -> dict:
    """
    From retrieved neighbors, compute:
    1. kNN denial probability (similarity-weighted vote)
    2. Novelty score (mean distance to top-5 neighbors)
    3. Top denial reasons from the neighborhood

    The novelty score is the key insight: if even the closest neighbors
    are far away, this claim is out of distribution.
    """
    # Novelty: mean cosine distance to top-5 neighbors
    # Higher = more novel (nothing in history looks like this)
    top_5_distances = [n["distance"] for n in neighbors[:5]]
    novelty_score = float(np.mean(top_5_distances))

    # Weighted vote: closer neighbors get more influence
    # Use similarity (1 - distance) as weight
    voting_neighbors = neighbors[:k_vote]
    denied_weight = 0.0
    total_weight = 0.0
    for n in voting_neighbors:
        weight = n["similarity"]
        if n["outcome"] == "denied":
            denied_weight += weight
        total_weight += weight

    knn_denial_prob = denied_weight / total_weight if total_weight > 0 else 0.5

    # Denial reason distribution among denied neighbors
    denied_neighbors = [n for n in voting_neighbors if n["outcome"] == "denied"]
    reason_counts = {}
    for n in denied_neighbors:
        r = n["denial_reason"]
        if r:
            reason_counts[r] = reason_counts.get(r, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])[:3]

    return {
        "knn_denial_probability": knn_denial_prob,
        "novelty_score": novelty_score,
        "nearest_distance": neighbors[0]["distance"] if neighbors else 1.0,
        "top_denial_reasons": [{"reason": r, "count": c} for r, c in top_reasons],
        "supporting_cases": neighbors[:5],
    }
```

---

## Step 4: Novelty Detection and Human Review Routing

*The main recipe's Step 4 describes using distance as a confidence signal. Here we implement the decision logic: claims with high novelty scores (far from any historical precedent) get routed to human review rather than auto-processed. This is the safety net that catches cold-start payers and out-of-distribution procedure combinations.*

```python
def route_claim(novelty_result: dict,
                primary_model_score: float,
                payer_claim_count: int) -> dict:
    """
    Hybrid decision engine combining the primary XGBoost score (from Recipe 7.11)
    with the similarity-based novelty signal.

    Logic:
    - Novel claim (high distance)? Route to human review.
    - Cold-start payer (<50 claims)? Use kNN as predictor, flag for review.
    - Primary model and kNN disagree? Flag the disagreement.
    - Everything agrees? Trust the primary model.

    Args:
        novelty_result: Output from compute_knn_prediction()
        primary_model_score: Denial probability from XGBoost (Recipe 7.11)
        payer_claim_count: Number of historical claims for this payer

    Returns:
        Final hybrid decision with confidence, recommendation, and explanation.
    """
    novelty_score = novelty_result["novelty_score"]
    knn_prob = novelty_result["knn_denial_probability"]

    if novelty_score > NOVELTY_THRESHOLD:
        # Novel claim: primary model is unreliable for this input
        return {
            "final_denial_probability": knn_prob,
            "confidence": "low",
            "recommendation": "human_review",
            "explanation": (
                f"This claim is unlike anything in our history "
                f"(novelty score: {novelty_score:.3f}). "
                f"Nearest resolved cases shown for reference."
            ),
            "primary_model_score": primary_model_score,
            "knn_score": knn_prob,
            "novelty_score": novelty_score,
            "supporting_cases": novelty_result["supporting_cases"],
            "top_denial_reasons": novelty_result["top_denial_reasons"],
        }

    elif payer_claim_count < COLD_START_MIN_CLAIMS:
        # Cold start: limited payer-specific data
        return {
            "final_denial_probability": knn_prob,
            "confidence": "medium",
            "recommendation": "review_suggested",
            "explanation": (
                f"Limited history for this payer ({payer_claim_count} claims). "
                f"Prediction based on similar claims from comparable payers."
            ),
            "primary_model_score": primary_model_score,
            "knn_score": knn_prob,
            "novelty_score": novelty_score,
            "supporting_cases": novelty_result["supporting_cases"],
            "top_denial_reasons": novelty_result["top_denial_reasons"],
        }

    elif abs(primary_model_score - knn_prob) > DISAGREEMENT_THRESHOLD:
        # Disagreement between primary model and neighbor evidence
        avg_score = (primary_model_score + knn_prob) / 2.0
        return {
            "final_denial_probability": avg_score,
            "confidence": "medium",
            "recommendation": "review_suggested",
            "explanation": (
                f"Model prediction ({primary_model_score:.0%}) and historical "
                f"precedent ({knn_prob:.0%}) diverge. Averaging as compromise."
            ),
            "primary_model_score": primary_model_score,
            "knn_score": knn_prob,
            "novelty_score": novelty_score,
            "supporting_cases": novelty_result["supporting_cases"],
            "top_denial_reasons": novelty_result["top_denial_reasons"],
        }

    else:
        # Concordant, well-supported prediction
        action = "auto_flag" if primary_model_score > 0.6 else "pass"
        return {
            "final_denial_probability": primary_model_score,
            "confidence": "high",
            "recommendation": action,
            "explanation": (
                f"Prediction well-supported by "
                f"{len(novelty_result['supporting_cases'])} similar resolved cases."
            ),
            "primary_model_score": primary_model_score,
            "knn_score": knn_prob,
            "novelty_score": novelty_score,
            "supporting_cases": novelty_result["supporting_cases"],
            "top_denial_reasons": novelty_result["top_denial_reasons"],
        }
```

---

## Step 5: Denial Archetype Clustering (k-Means)

*The main recipe contrasts kNN retrieval (per-claim prediction) with clustering (population segmentation). Here we run k-means on the denied claims to discover denial archetypes: natural groupings that correspond to distinct root causes. This is operationally useful for routing denied claims to specialized rework teams.*

```python
from sklearn.cluster import KMeans

def cluster_denial_archetypes(denied_embeddings: np.ndarray,
                              denied_df: pd.DataFrame,
                              n_clusters: int = N_DENIAL_CLUSTERS) -> dict:
    """
    Segment denied claims into archetype clusters.

    Unlike kNN (which answers "what happened to similar claims?"), clustering
    answers "what are the major denial patterns in our data?"

    Each cluster ideally corresponds to a distinct denial root cause:
    - Cluster 0: Missing prior auth (surgical, specific payers)
    - Cluster 1: Coding/bundling issues (multi-modifier claims)
    - Cluster 2: Medical necessity challenges (imaging, high-cost)
    - etc.

    Returns cluster labels and a summary of each cluster's characteristics.
    """
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = kmeans.fit_predict(denied_embeddings)

    # Analyze each cluster's composition
    denied_with_clusters = denied_df.copy()
    denied_with_clusters["cluster"] = cluster_labels

    cluster_summary = {}
    for c in range(n_clusters):
        cluster_mask = denied_with_clusters["cluster"] == c
        cluster_data = denied_with_clusters[cluster_mask]

        # Top denial reasons in this cluster
        reason_dist = cluster_data["denial_reason"].value_counts().head(3)
        # Top payers
        payer_dist = cluster_data["payer"].value_counts().head(3)
        # Top CPT codes
        cpt_dist = cluster_data["cpt_code"].value_counts().head(3)

        cluster_summary[c] = {
            "size": int(cluster_mask.sum()),
            "pct_of_denials": float(cluster_mask.sum() / len(denied_with_clusters) * 100),
            "top_reasons": reason_dist.to_dict(),
            "top_payers": payer_dist.to_dict(),
            "top_cpt_codes": cpt_dist.to_dict(),
            "avg_amount": float(cluster_data["claim_amount"].mean()),
        }

    logger.info("Clustered %d denied claims into %d archetypes",
                len(denied_embeddings), n_clusters)
    return {
        "labels": cluster_labels,
        "centroids": kmeans.cluster_centers_,
        "summary": cluster_summary,
    }
```

---

## Step 6: AWS Implementation with OpenSearch k-NN (boto3)

*The main recipe uses Amazon OpenSearch Service with the k-NN plugin for production vector search. Here we show the boto3 calls to create a k-NN index, bulk-index claim embeddings, and query for nearest neighbors. In production, this replaces the sklearn NearestNeighbors from Step 3 with a managed, scalable vector store.*

```python
import boto3
import json
from botocore.config import Config

# Retry config for OpenSearch API calls. Adaptive mode handles throttling
# with exponential backoff and jitter.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})


def get_opensearch_client():
    """
    Create a boto3 client for OpenSearch HTTP operations.

    In production, you'd sign requests using SigV4 (AWS request signing)
    rather than using the basic REST client. The opensearchpy library with
    AWSV4SignerAuth is the standard approach. Here we show the raw HTTP
    structure so you understand what's happening at the API level.
    """
    # For production, use the opensearch-py library with IAM auth:
    #   from opensearchpy import OpenSearch, RequestsHttpConnection
    #   from requests_aws4auth import AWS4Auth
    #
    #   credentials = boto3.Session().get_credentials()
    #   auth = AWS4Auth(credentials.access_key, credentials.secret_key,
    #                   region, 'es', session_token=credentials.token)
    #   client = OpenSearch(hosts=[{'host': endpoint, 'port': 443}],
    #                       http_auth=auth, use_ssl=True,
    #                       connection_class=RequestsHttpConnection)
    #
    # For this example, we show the index/query JSON structures.
    session = boto3.Session()
    return session.client("opensearch", config=BOTO3_RETRY_CONFIG)


def create_knn_index_mapping() -> dict:
    """
    Returns the OpenSearch index mapping for a k-NN vector index.

    Key decisions:
    - HNSW algorithm: best latency for sub-100ms queries at scale
    - cosinesimil space: matches our embedding design (direction > magnitude)
    - ef_construction=256: higher = better recall during indexing, slower builds
    - m=16: connections per node in the HNSW graph (16 is a good default)

    The mapping also includes keyword fields for claim metadata so we can
    return full case details without a separate lookup.
    """
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,  # query-time recall parameter
                "number_of_shards": 2,
                "number_of_replicas": 1,
            }
        },
        "mappings": {
            "properties": {
                "claim_embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIM,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 256,
                            "m": 16
                        }
                    }
                },
                "claim_id": {"type": "keyword"},
                "payer": {"type": "keyword"},
                "cpt_code": {"type": "keyword"},
                "outcome": {"type": "keyword"},
                "denial_reason": {"type": "keyword"},
                "claim_amount": {"type": "float"},
                "place_of_service": {"type": "keyword"},
                "provider_type": {"type": "keyword"},
            }
        }
    }


def bulk_index_embeddings(embeddings: np.ndarray,
                          claims_df: pd.DataFrame,
                          index_name: str = OPENSEARCH_INDEX) -> None:
    """
    Bulk-load claim embeddings into OpenSearch.

    In production, you'd use the opensearch-py bulk helper for efficient
    batch indexing. This shows the document structure for each claim.

    Each document contains:
    - The embedding vector (for kNN search)
    - Claim metadata (returned with search results for case-based reasoning)
    - Outcome and denial reason (the "answer" we're retrieving)
    """
    # Build bulk request body (NDJSON format for OpenSearch _bulk API)
    bulk_body = []
    for i, row in claims_df.iterrows():
        # Action line
        bulk_body.append(json.dumps({"index": {"_index": index_name}}))
        # Document line
        doc = {
            "claim_embedding": embeddings[i].tolist(),
            "claim_id": row["claim_id"],
            "payer": row["payer"],
            "cpt_code": row["cpt_code"],
            "outcome": "denied" if row["denied"] == 1 else "paid",
            "denial_reason": row.get("denial_reason", ""),
            "claim_amount": float(row["claim_amount"]),
            "place_of_service": row["place_of_service"],
            "provider_type": row["provider_type"],
        }
        bulk_body.append(json.dumps(doc))

    # In production, send this to OpenSearch via:
    #   response = os_client.bulk(body="\n".join(bulk_body) + "\n",
    #                             index=index_name)
    #   if response["errors"]:
    #       # Handle failed documents (log and retry)
    #       ...

    logger.info(
        "Prepared %d documents for bulk indexing into '%s'",
        len(claims_df), index_name
    )
    print(f"  [OpenSearch] Would index {len(claims_df)} documents")
    print(f"  [OpenSearch] Embedding dimension: {embeddings.shape[1]}")
    print(f"  [OpenSearch] Index: {index_name}")


def query_opensearch_knn(query_vector: np.ndarray,
                         k: int = K_NEIGHBORS,
                         index_name: str = OPENSEARCH_INDEX) -> dict:
    """
    Query OpenSearch k-NN index for nearest neighbors to a claim vector.

    The kNN query returns the top-k most similar documents by cosine
    similarity. Each hit includes the full document (metadata + outcome)
    plus a _score (the similarity value).

    For payer-filtered search (Variation 1 from the main recipe), wrap
    this query in a bool filter:
        "query": {
            "bool": {
                "filter": {"term": {"payer": "BCBS"}},
                "must": {"knn": {...}}
            }
        }
    """
    query_body = {
        "size": k,
        "query": {
            "knn": {
                "claim_embedding": {
                    "vector": query_vector.tolist(),
                    "k": k
                }
            }
        },
        "_source": ["claim_id", "payer", "cpt_code", "outcome",
                    "denial_reason", "claim_amount"]
    }

    # In production:
    #   response = os_client.search(index=index_name, body=query_body)
    #   hits = response["hits"]["hits"]
    #   neighbors = [{"claim_id": h["_source"]["claim_id"],
    #                 "similarity": h["_score"],
    #                 "outcome": h["_source"]["outcome"],
    #                 ...} for h in hits]

    logger.info("kNN query: k=%d, vector_dim=%d", k, len(query_vector))
    print(f"  [OpenSearch] kNN query for {k} neighbors")
    print(f"  [OpenSearch] Query vector shape: ({len(query_vector)},)")

    # Return the query structure for inspection
    return query_body


def query_opensearch_knn_with_payer_filter(query_vector: np.ndarray,
                                           payer_id: str,
                                           k: int = K_NEIGHBORS,
                                           index_name: str = OPENSEARCH_INDEX) -> dict:
    """
    Payer-filtered kNN search (Variation 1 from the main recipe).

    Restricts the neighbor search to claims from the same payer. This is
    far more relevant for prediction (same payer = same rules) but requires
    sufficient within-payer volume. Fall back to unfiltered search if the
    payer has fewer than k indexed documents.
    """
    query_body = {
        "size": k,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"payer": payer_id}}
                ],
                "must": [
                    {
                        "knn": {
                            "claim_embedding": {
                                "vector": query_vector.tolist(),
                                "k": k
                            }
                        }
                    }
                ]
            }
        },
        "_source": ["claim_id", "payer", "cpt_code", "outcome",
                    "denial_reason", "claim_amount"]
    }

    logger.info("Payer-filtered kNN: payer=%s, k=%d", payer_id, k)
    return query_body
```

---

## Step 7: Hybrid Integration with Recipe 7.11 XGBoost Score

*The main recipe describes the hybrid pattern: primary XGBoost prediction plus similarity-based novelty flag and case-based explanation. Here we show how the two systems integrate. The XGBoost score from 7.11 is your primary predictor; this recipe's kNN layer adds self-awareness about what the primary model doesn't know.*

```python
def simulate_primary_model_score(claim: pd.Series, rng=None) -> float:
    """
    Simulates the XGBoost denial probability from Recipe 7.11.

    In production, you'd call the SageMaker endpoint:
        sagemaker_client = boto3.client("sagemaker-runtime")
        response = sagemaker_client.invoke_endpoint(
            EndpointName="denial-prediction-endpoint",
            ContentType="text/csv",
            Body=claim_features_as_csv
        )
        score = float(response["Body"].read())

    Here we simulate a reasonable score based on claim features.
    """
    if rng is None:
        rng = np.random.default_rng(0)

    # Simulate: primary model gives a score based on features
    # Novel payers get a "confident but potentially wrong" score
    base = 0.3
    if claim.get("pa_required", 0) == 1 and claim.get("pa_on_file", 0) == 0:
        base += 0.4
    cpt_risk = CPT_CODES.get(claim.get("cpt_code", ""), 1.0)
    if cpt_risk > 1.3:
        base += 0.15
    # Add noise to simulate model uncertainty
    score = np.clip(base + rng.normal(0, 0.1), 0.05, 0.95)
    return float(score)


def score_claim_hybrid(claim: pd.Series,
                       claim_embedding: np.ndarray,
                       knn_index: NearestNeighbors,
                       history_df: pd.DataFrame,
                       payer_counts: dict) -> dict:
    """
    Full hybrid scoring pipeline for a single claim.

    Combines:
    1. Primary model score (XGBoost from 7.11)
    2. kNN neighbor retrieval and weighted vote
    3. Novelty detection from neighbor distances
    4. Routing decision based on confidence

    This is what runs for every incoming claim in production.
    """
    # Step A: Get primary model prediction
    primary_score = simulate_primary_model_score(claim)

    # Step B: Retrieve nearest neighbors
    neighbors = retrieve_neighbors(knn_index, claim_embedding, history_df)

    # Step C: Compute kNN prediction and novelty
    novelty_result = compute_knn_prediction(neighbors)

    # Step D: Get payer history count for cold-start detection
    payer = claim.get("payer", "unknown")
    payer_count = payer_counts.get(payer, 0)

    # Step E: Route based on confidence
    decision = route_claim(novelty_result, primary_score, payer_count)

    return decision
```

---

## Full Pipeline: Putting It All Together

```python
def run_full_pipeline():
    """
    End-to-end demonstration of cohort matching and case-based reasoning.

    Runs through:
    1. Generate synthetic historical claims and novel test claims
    2. Build embeddings and kNN index
    3. Score novel claims with hybrid pipeline
    4. Show novelty detection catching OOD claims
    5. Run denial archetype clustering
    6. Show OpenSearch integration patterns
    """
    print("=" * 70)
    print("RECIPE 7.12: Cohort Matching and Case-Based Reasoning")
    print("=" * 70)

    # --- Step 1: Generate data ---
    print("\n[Step 1] Generating synthetic claims data...")
    history_df = generate_claims_history()
    novel_df = generate_novel_claims()
    print(f"  Historical claims: {len(history_df)} "
          f"(denial rate: {history_df['denied'].mean():.1%})")
    print(f"  Novel test claims: {len(novel_df)}")

    # Payer claim counts (for cold-start detection)
    payer_counts = history_df["payer"].value_counts().to_dict()
    # Novel payers have 0 history by definition
    for p in NOVEL_PAYERS:
        payer_counts[p] = 0

    # --- Step 2: Build embeddings ---
    print("\n[Step 2] Building claim embeddings...")
    preprocessor = build_embedding_pipeline()
    history_embeddings = compute_embeddings(history_df, preprocessor, fit=True)
    novel_embeddings = compute_embeddings(novel_df, preprocessor, fit=False)
    print(f"  Embedding dimension: {history_embeddings.shape[1]}")

    # --- Step 3: Build kNN index ---
    print("\n[Step 3] Building kNN index over historical claims...")
    knn_index = build_knn_index(history_embeddings)

    # --- Step 4: Score novel claims with hybrid pipeline ---
    print("\n[Step 4] Scoring novel claims with hybrid pipeline...")
    print("-" * 50)

    results = []
    rng = np.random.default_rng(123)
    for i in range(min(10, len(novel_df))): # Show first 10
        claim = novel_df.iloc[i]
        embedding = novel_embeddings[i]
        decision = score_claim_hybrid(
            claim, embedding, knn_index, history_df, payer_counts
        )
        results.append(decision)

        print(f"\n  Claim {claim['claim_id']} | Payer: {claim['payer']} | "
              f"CPT: {claim['cpt_code']}")
        print(f"    Primary model: {decision['primary_model_score']:.3f} | "
              f"kNN: {decision['knn_score']:.3f} | "
              f"Novelty: {decision['novelty_score']:.3f}")
        print(f"    Confidence: {decision['confidence']} | "
              f"Action: {decision['recommendation']}")
        print(f"    Reason: {decision['explanation']}")
        if decision["top_denial_reasons"]:
            top_reason = decision["top_denial_reasons"][0]
            print(f"    Top denial pattern: {top_reason['reason']} "
                  f"({top_reason['count']} of top-{K_VOTE} neighbors)")

    # --- Step 5: Novelty detection summary ---
    print("\n" + "-" * 50)
    print("\n[Step 5] Novelty detection summary...")
    # Score all novel claims
    all_decisions = []
    for i in range(len(novel_df)):
        claim = novel_df.iloc[i]
        embedding = novel_embeddings[i]
        decision = score_claim_hybrid(
            claim, embedding, knn_index, history_df, payer_counts
        )
        all_decisions.append(decision)

    n_human_review = sum(1 for d in all_decisions if d["recommendation"] == "human_review")
    n_review_suggested = sum(1 for d in all_decisions if d["recommendation"] == "review_suggested")
    n_auto = sum(1 for d in all_decisions
                 if d["recommendation"] in ("auto_flag", "pass"))

    print(f"  Novel claims routed to human review: {n_human_review}/{len(novel_df)}")
    print(f"  Novel claims with review suggested: {n_review_suggested}/{len(novel_df)}")
    print(f"  Novel claims auto-processed: {n_auto}/{len(novel_df)}")
    print(f"  Novelty detection catch rate: "
          f"{(n_human_review + n_review_suggested) / len(novel_df):.0%}")

    # --- Step 6: Denial archetype clustering ---
    print("\n[Step 6] Clustering denied claims into archetypes...")
    denied_mask = history_df["denied"] == 1
    denied_embeddings = history_embeddings[denied_mask]
    denied_df = history_df[denied_mask].reset_index(drop=True)

    cluster_result = cluster_denial_archetypes(denied_embeddings, denied_df)

    print(f"\n  Denial archetype clusters ({N_DENIAL_CLUSTERS} clusters, "
          f"{len(denied_df)} denied claims):")
    for c, info in cluster_result["summary"].items():
        print(f"\n    Cluster {c}: {info['size']} claims "
              f"({info['pct_of_denials']:.1f}% of denials)")
        print(f"      Top reasons: {info['top_reasons']}")
        print(f"      Top payers: {info['top_payers']}")
        print(f"      Avg amount: ${info['avg_amount']:,.0f}")

    # --- Step 7: Contrast kNN vs. clustering ---
    print("\n" + "-" * 50)
    print("\n[Step 7] kNN vs. Clustering: when to use which")
    print("""
    kNN Retrieval (per-claim):
      - "What happened when we saw claims like this?"
      - Returns specific historical cases with outcomes
      - Best for: prediction, explanation, novelty detection
      - Answers: "Will THIS claim be denied? Show me evidence."

    Clustering (population-level):
      - "What are the major denial patterns?"
      - Returns group labels and archetypes
      - Best for: operational routing, pattern discovery, team assignment
      - Answers: "What types of denials do we have? Route this to the right team."

    They complement each other. Use kNN for individual claim decisions.
    Use clustering for operational workflow design and denial reduction strategy.
    """)

    # --- Step 8: Show OpenSearch integration ---
    print("[Step 8] OpenSearch k-NN integration (API structures)...")
    print("\n  Index mapping:")
    mapping = create_knn_index_mapping()
    print(f"    Dimension: {mapping['mappings']['properties']['claim_embedding']['dimension']}")
    print(f"    Algorithm: HNSW")
    print(f"    Space: cosinesimil")

    # Show a sample query
    sample_vector = novel_embeddings[0]
    # Trim to EMBEDDING_DIM if the actual embedding is larger
    if len(sample_vector) > EMBEDDING_DIM:
        sample_vector = sample_vector[:EMBEDDING_DIM]
    query = query_opensearch_knn(sample_vector, k=20)
    print(f"\n  Sample kNN query structure:")
    print(f"    size: {query['size']}")
    print(f"    vector dimensions: {len(query['query']['knn']['claim_embedding']['vector'])}")

    # Show payer-filtered query
    filtered_query = query_opensearch_knn_with_payer_filter(
        sample_vector, payer_id="BCBS", k=20
    )
    print(f"\n  Payer-filtered query (BCBS):")
    print(f"    Filter: payer=BCBS")
    print(f"    Falls back to unfiltered if <k results for this payer")

    # Show batch vs real-time note
    print("\n  Batch vs. Real-time retrieval:")
    print("    Real-time: Score at claim creation (Lambda + OpenSearch query)")
    print("      Latency: ~80-120ms end-to-end")
    print("      Use for: prior-auth determinations, real-time worklist flags")
    print("    Batch: Score nightly (Glue job + bulk OpenSearch queries)")
    print("      Throughput: ~10,000 claims/minute")
    print("      Use for: next-day worklist population, trend analysis")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Historical index: {len(history_df)} resolved claims")
    print(f"  Embedding dimensions: {history_embeddings.shape[1]}")
    print(f"  Novel claims tested: {len(novel_df)}")
    print(f"  Caught as OOD: {n_human_review + n_review_suggested} "
          f"({(n_human_review + n_review_suggested) / len(novel_df):.0%})")
    print(f"  Denial clusters: {N_DENIAL_CLUSTERS} archetypes identified")
    print(f"\n  This system complements Recipe 7.11 (XGBoost denial prediction).")
    print(f"  Use 7.11 as the primary predictor. Use 7.12 for:")
    print(f"    - Novelty detection (is this claim out of distribution?)")
    print(f"    - Case-based explanation (show me similar resolved claims)")
    print(f"    - Cold-start handling (new payer with no training history)")
    print(f"    - Operational routing (which denial archetype is this?)")


if __name__ == "__main__":
    run_full_pipeline()
```

---

## Gap to Production

This example demonstrates the core algorithms, but deploying a case-based reasoning system over claims requires substantial additional engineering. Here's the distance between this sketch and something you'd run in production.

**Learned embeddings instead of one-hot encoding.** The example uses OneHotEncoder + StandardScaler, which produces high-dimensional sparse vectors (hundreds of dimensions from cardinality of CPT codes, payers, ICD-10). In production, train a neural embedding model (autoencoder or contrastive learning on adjudication pairs) that maps claims into a dense 64-128 dimensional space. The embedding model learns which feature interactions matter for similarity and handles the curse of dimensionality.

**OpenSearch operational concerns.** HNSW indexes consume significant RAM (roughly 4 bytes per dimension per vector plus graph overhead). For 1M claims at 128 dimensions, plan for ~1-2GB of dedicated k-NN memory. Use dedicated master nodes, configure `knn.memory.circuit_breaker.limit` appropriately, and monitor JVM heap pressure. Force-merge indexes after bulk loads (HNSW performance degrades with many segments).

**Index freshness pipeline.** Claims adjudicate 2-6 weeks after submission. Your vector index is always stale by this lag. Build an incremental pipeline: as adjudication results arrive (EventBridge events from your claims system), compute embeddings for newly resolved claims and append to the index. Schedule full re-indexes monthly to account for embedding model updates.

**Threshold calibration.** The novelty threshold (0.4) and disagreement threshold (0.25) in this example are illustrative. Production calibration requires: (1) score a holdout set, (2) plot accuracy vs. novelty score, (3) find the novelty level where accuracy drops below your acceptable floor, (4) set threshold there. Re-calibrate monthly as your claim population shifts.

**Embedding drift monitoring.** As your claim population changes (new procedure codes from CMS updates, new payer contracts, demographic shifts), old embeddings become less representative. Monitor the distribution of nearest-neighbor distances over time. If the average distance is increasing (everything looks more "novel"), your embeddings are drifting and need retraining.

**Error handling and retries.** Every OpenSearch query, SageMaker endpoint call, and DynamoDB write needs retry logic with exponential backoff. Use `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})`. Handle OpenSearch circuit breaker exceptions (index under memory pressure) by falling back gracefully (use the primary model alone, flag as "similarity unavailable").

**PHI treatment of embeddings.** Claim embeddings encode information derived from diagnosis codes, procedure codes, and patient demographics. Treat embedding vectors as PHI. Encrypt at rest (KMS), encrypt in transit (TLS), store in BAA-covered services only, and audit access via CloudTrail. This applies to the OpenSearch domain, S3 embedding storage, and any caching layers.

**VPC and network isolation.** OpenSearch domain must be VPC-only (no public endpoint). Lambda functions accessing OpenSearch must be in the same VPC. Use VPC endpoints for S3, DynamoDB, SageMaker Runtime, and KMS. Security groups should restrict OpenSearch access to only the specific Lambda and Glue resources that need it.

**IAM least-privilege.** Separate roles: (1) Glue ETL role with S3 and OpenSearch bulk-write access, (2) Lambda hybrid-engine role with OpenSearch query, SageMaker InvokeEndpoint, and DynamoDB write, (3) SageMaker training role with S3 access for model artifacts. Each scoped to specific resource ARNs, not wildcards.

**DynamoDB numeric types.** Same as Recipe 7.11: DynamoDB does not accept Python floats. Convert all prediction scores, novelty values, and dollar amounts to `Decimal(str(value))` before `put_item`. The `Decimal` import at the top of this file is there for this reason.

**Testing.** Unit tests for embedding consistency (same claim always produces same vector). Integration tests that index a known set, query a known vector, and verify the expected neighbors are returned. Regression tests for novelty calibration (known novel claims should exceed the threshold). Load tests for concurrent OpenSearch queries under production throughput.

**Cluster stability.** K-means cluster assignments can shift dramatically between runs (a claim in cluster 2 today might be in cluster 4 tomorrow after re-clustering). Use cluster alignment techniques (Hungarian algorithm matching between old and new assignments) or switch to incremental clustering. Your operational teams need stable archetype labels, not arbitrary numbers that shuffle weekly.

**Fairness monitoring.** If your historical data encodes biased payer decisions (certain demographic groups denied at higher rates for non-clinical reasons), your similarity system reproduces those biases. Monitor kNN prediction outcomes by demographic subgroup. If the system disproportionately flags claims from certain populations as "novel" (because they're underrepresented in history), that's a bias signal requiring intervention.

---

*← [Recipe 7.12: Cohort Matching and Case-Based Reasoning for Novel Claims](chapter07.12-claim-cohort-matching) · [Chapter 7 Index](chapter07-preface)*
