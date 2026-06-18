# Recipe 6.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the disease subtype discovery pipeline from Recipe 6.8. It demonstrates the core workflow (synthetic patient data generation, preprocessing, multi-algorithm clustering, consensus analysis, and clinical validation) using scikit-learn and boto3. It is not production-ready. Real subtype discovery requires clinical collaboration, rigorous statistical validation, and months of iterative refinement. Think of this as the sketch that helps you understand the shape of the problem, not something you'd publish in The Lancet.

---

## Setup

You'll need the AWS SDK for Python and standard ML libraries:

```bash
pip install boto3 numpy pandas scikit-learn scipy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`, `s3:PutObject` (feature matrix and results storage)
- `sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint` (if deploying the classifier)
- `dynamodb:PutItem`, `dynamodb:GetItem` (subtype assignment storage)

For this example, we'll run clustering locally using scikit-learn. In production, you'd use SageMaker training jobs for larger cohorts. The concepts are identical; only the compute substrate changes.

---

## Config and Constants

```python
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split

import boto3
from botocore.config import Config

# Structured logging. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Configuration
RESULTS_BUCKET = "subtype-discovery-results"
FEATURE_MATRIX_KEY = "features/heart-failure-cohort.csv"
SUBTYPE_TABLE = "patient-subtypes"

# Clustering parameters
K_RANGE = range(2, 11)  # Explore 2 through 10 clusters
VARIANCE_THRESHOLD = 0.90  # Keep PCA components explaining 90% of variance
CONSENSUS_ITERATIONS = 100  # Number of bootstrap resamples for consensus
SUBSAMPLE_FRACTION = 0.80  # Fraction of patients to sample each iteration
RANDOM_SEED = 42  # Reproducibility
```

---

## Step 1: Generate Synthetic Patient Cohort

*The main recipe's Step 1 defines the cohort and Step 2 extracts features. Here we generate synthetic data that mimics what you'd get from a real EHR feature extraction pipeline. The synthetic data has four embedded subtypes with different clinical profiles, so we can verify the clustering recovers them.*

```python
def generate_synthetic_cohort(n_patients=2000, random_state=42):
    """
    Generate a synthetic heart failure cohort with embedded subtypes.

    This creates four distinct patient phenotypes:
    - Metabolic HFpEF: high BMI, diabetes, preserved EF
    - Ischemic progressive: low EF, prior MI, CAD history
    - Elderly multimorbid: old, CKD, anemia, many comorbidities
    - Young idiopathic: young, low EF, few comorbidities

    In real life, you'd never have these labels. That's the whole point of
    unsupervised clustering. We include them here only so we can verify
    the algorithm recovers meaningful structure.
    """
    rng = np.random.default_rng(random_state)

    # Allocate patients to subtypes (unequal sizes, like reality)
    subtype_sizes = [600, 640, 400, 360]  # roughly 30%, 32%, 20%, 18%
    assert sum(subtype_sizes) == n_patients

    records = []

    # Subtype 0: Metabolic HFpEF
    for _ in range(subtype_sizes[0]):
        records.append({
            "age": rng.normal(62, 8),
            "bmi": rng.normal(35, 5),
            "ejection_fraction": rng.normal(52, 8),  # preserved
            "bnp": rng.normal(450, 150),
            "creatinine": rng.normal(1.2, 0.3),
            "hemoglobin": rng.normal(13.0, 1.5),
            "hba1c": rng.normal(7.8, 1.2),  # diabetic
            "sodium": rng.normal(138, 3),
            "potassium": rng.normal(4.3, 0.4),
            "heart_rate": rng.normal(78, 12),
            "systolic_bp": rng.normal(142, 18),
            "has_diabetes": 1,
            "has_hypertension": rng.choice([0, 1], p=[0.15, 0.85]),
            "has_cad": rng.choice([0, 1], p=[0.7, 0.3]),
            "has_ckd": rng.choice([0, 1], p=[0.6, 0.4]),
            "has_afib": rng.choice([0, 1], p=[0.6, 0.4]),
            "has_copd": rng.choice([0, 1], p=[0.8, 0.2]),
            "prior_mi": 0,
            "comorbidity_count": rng.poisson(3) + 2,
            "true_subtype": 0,
        })

    # Subtype 1: Ischemic progressive
    for _ in range(subtype_sizes[1]):
        records.append({
            "age": rng.normal(67, 10),
            "bmi": rng.normal(28, 4),
            "ejection_fraction": rng.normal(30, 8),  # reduced
            "bnp": rng.normal(1200, 400),  # elevated
            "creatinine": rng.normal(1.4, 0.4),
            "hemoglobin": rng.normal(12.5, 1.8),
            "hba1c": rng.normal(6.2, 0.8),
            "sodium": rng.normal(136, 4),
            "potassium": rng.normal(4.5, 0.5),
            "heart_rate": rng.normal(82, 14),
            "systolic_bp": rng.normal(125, 15),
            "has_diabetes": rng.choice([0, 1], p=[0.55, 0.45]),
            "has_hypertension": rng.choice([0, 1], p=[0.3, 0.7]),
            "has_cad": 1,
            "has_ckd": rng.choice([0, 1], p=[0.6, 0.4]),
            "has_afib": rng.choice([0, 1], p=[0.5, 0.5]),
            "has_copd": rng.choice([0, 1], p=[0.75, 0.25]),
            "prior_mi": 1,
            "comorbidity_count": rng.poisson(2) + 2,
            "true_subtype": 1,
        })

    # Subtype 2: Elderly multimorbid
    for _ in range(subtype_sizes[2]):
        records.append({
            "age": rng.normal(81, 5),  # elderly
            "bmi": rng.normal(26, 4),
            "ejection_fraction": rng.normal(40, 12),
            "bnp": rng.normal(900, 350),
            "creatinine": rng.normal(2.1, 0.6),  # CKD
            "hemoglobin": rng.normal(10.5, 1.5),  # anemic
            "hba1c": rng.normal(6.8, 1.0),
            "sodium": rng.normal(134, 4),  # slightly low
            "potassium": rng.normal(4.8, 0.6),
            "heart_rate": rng.normal(72, 10),
            "systolic_bp": rng.normal(130, 20),
            "has_diabetes": rng.choice([0, 1], p=[0.4, 0.6]),
            "has_hypertension": rng.choice([0, 1], p=[0.15, 0.85]),
            "has_cad": rng.choice([0, 1], p=[0.4, 0.6]),
            "has_ckd": 1,
            "has_afib": rng.choice([0, 1], p=[0.3, 0.7]),
            "has_copd": rng.choice([0, 1], p=[0.5, 0.5]),
            "prior_mi": rng.choice([0, 1], p=[0.6, 0.4]),
            "comorbidity_count": rng.poisson(4) + 3,  # high burden
            "true_subtype": 2,
        })

    # Subtype 3: Young idiopathic
    for _ in range(subtype_sizes[3]):
        records.append({
            "age": rng.normal(44, 8),  # young
            "bmi": rng.normal(27, 4),
            "ejection_fraction": rng.normal(28, 7),  # reduced
            "bnp": rng.normal(800, 300),
            "creatinine": rng.normal(0.9, 0.2),  # normal kidneys
            "hemoglobin": rng.normal(14.0, 1.2),  # normal
            "hba1c": rng.normal(5.5, 0.4),  # not diabetic
            "sodium": rng.normal(139, 2),
            "potassium": rng.normal(4.2, 0.3),
            "heart_rate": rng.normal(85, 15),
            "systolic_bp": rng.normal(118, 12),
            "has_diabetes": 0,
            "has_hypertension": rng.choice([0, 1], p=[0.75, 0.25]),
            "has_cad": 0,
            "has_ckd": 0,
            "has_afib": rng.choice([0, 1], p=[0.7, 0.3]),
            "has_copd": 0,
            "prior_mi": 0,
            "comorbidity_count": rng.poisson(1),
            "true_subtype": 3,
        })

    df = pd.DataFrame(records)

    # Clip physiologically implausible values
    df["ejection_fraction"] = df["ejection_fraction"].clip(5, 75)
    df["bmi"] = df["bmi"].clip(15, 60)
    df["creatinine"] = df["creatinine"].clip(0.3, 8.0)
    df["hemoglobin"] = df["hemoglobin"].clip(6.0, 18.0)
    df["age"] = df["age"].clip(18, 100)

    logger.info("Generated synthetic cohort: %d patients, %d features", len(df), len(df.columns) - 1)
    return df
```

---

## Step 2: Preprocess and Reduce Dimensions

*Maps to pseudocode Steps 2-3. Standardize features so clustering isn't dominated by high-magnitude variables, then apply PCA to reduce dimensionality while preserving meaningful variance.*

```python
def preprocess_and_reduce(df, variance_threshold=VARIANCE_THRESHOLD):
    """
    Standardize features and apply PCA for dimensionality reduction.

    Why standardize? BNP ranges from 0 to 5000+. Ejection fraction ranges
    from 5 to 75. Without scaling, BNP would dominate every distance
    calculation and you'd find "BNP subtypes" rather than meaningful phenotypes.

    Why PCA? With 18 features, clustering works fine directly. But in a real
    scenario with 50-100 features, the curse of dimensionality makes distance
    metrics unreliable. PCA compresses to the directions of maximum variance.
    """
    # Separate features from the ground truth label (which we won't use for clustering)
    feature_cols = [c for c in df.columns if c != "true_subtype"]
    X = df[feature_cols].values

    # Standardize: zero mean, unit variance for each feature
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # PCA: find how many components capture the target variance
    # Note: PCA with the default full SVD solver is deterministic (no random_state needed).
    pca = PCA()
    pca.fit(X_scaled)

    cumulative_variance = np.cumsum(pca.explained_variance_ratio_)
    n_components = np.searchsorted(cumulative_variance, variance_threshold) + 1

    logger.info(
        "PCA: %d components capture %.1f%% of variance (from %d original features)",
        n_components, cumulative_variance[n_components - 1] * 100, X_scaled.shape[1]
    )

    # Transform to reduced space (full SVD is deterministic; no random_state needed)
    pca_reduced = PCA(n_components=n_components)
    X_reduced = pca_reduced.fit_transform(X_scaled)

    return X_scaled, X_reduced, scaler, pca_reduced, feature_cols
```

---

## Step 3: Multi-Algorithm Clustering

*Maps to pseudocode Step 4. Run K-means, GMM, and hierarchical clustering across a range of K values. Record internal validation metrics for each. The goal is to find values of K where multiple algorithms agree.*

```python
def run_multi_algorithm_clustering(X_reduced, k_range=K_RANGE):
    """
    Run three clustering algorithms across a range of K values.

    Why multiple algorithms? Each makes different assumptions about cluster shape.
    K-means assumes spherical clusters. GMM allows elliptical. Hierarchical
    builds a tree. If all three find similar groupings at K=4, that's stronger
    evidence than any single algorithm alone.

    Returns a list of result dicts, one per K value, with labels and metrics
    for each algorithm.
    """
    results = []

    for k in k_range:
        k_result = {"k": k, "algorithms": {}}

        # K-means: fast, spherical cluster assumption
        kmeans = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10)
        kmeans_labels = kmeans.fit_predict(X_reduced)
        kmeans_sil = silhouette_score(X_reduced, kmeans_labels)

        k_result["algorithms"]["kmeans"] = {
            "labels": kmeans_labels,
            "silhouette": kmeans_sil,
        }

        # Gaussian Mixture Model: elliptical clusters, probabilistic assignments
        gmm = GaussianMixture(n_components=k, random_state=RANDOM_SEED, n_init=3)
        gmm_labels = gmm.fit_predict(X_reduced)
        gmm_sil = silhouette_score(X_reduced, gmm_labels)
        gmm_bic = gmm.bic(X_reduced)  # lower BIC = better fit/complexity tradeoff

        k_result["algorithms"]["gmm"] = {
            "labels": gmm_labels,
            "silhouette": gmm_sil,
            "bic": gmm_bic,
        }

        # Hierarchical (Ward linkage): builds dendrogram, cut at K
        hier = AgglomerativeClustering(n_clusters=k, linkage="ward")
        hier_labels = hier.fit_predict(X_reduced)
        hier_sil = silhouette_score(X_reduced, hier_labels)

        k_result["algorithms"]["hierarchical"] = {
            "labels": hier_labels,
            "silhouette": hier_sil,
        }

        results.append(k_result)
        logger.info(
            "K=%d | Silhouette: KMeans=%.3f, GMM=%.3f, Hier=%.3f | GMM BIC=%.0f",
            k, kmeans_sil, gmm_sil, hier_sil, gmm_bic
        )

    return results
```

---

## Step 4: Consensus Clustering

*Maps to pseudocode Step 5. This is the gold standard for disease subtype discovery. Run clustering 100 times on bootstrap resamples and track which patients consistently end up together. Stable co-clustering across resamples is evidence of genuine structure.*

```python
def consensus_clustering(X_scaled, k, n_iterations=CONSENSUS_ITERATIONS,
                         subsample_fraction=SUBSAMPLE_FRACTION):
    """
    Build a consensus matrix by repeatedly clustering bootstrap subsamples.

    The consensus matrix entry (i, j) represents the fraction of times
    patient i and patient j ended up in the same cluster across all iterations
    where both were sampled. Values near 1.0 mean "always together." Values
    near 0.0 mean "never together." Values near 0.5 mean "unstable" (boundary
    patients who bounce between clusters depending on who else is in the sample).

    We then cluster the consensus matrix itself to get final assignments.
    """
    n_patients = X_scaled.shape[0]
    co_cluster_count = np.zeros((n_patients, n_patients))
    co_occurrence_count = np.zeros((n_patients, n_patients))

    rng = np.random.default_rng(RANDOM_SEED)

    for iteration in range(n_iterations):
        # Bootstrap: sample 80% of patients
        n_sample = int(n_patients * subsample_fraction)
        indices = rng.choice(n_patients, size=n_sample, replace=False)
        indices.sort()

        # Cluster the subsample
        subsample = X_scaled[indices]
        kmeans = KMeans(n_clusters=k, random_state=iteration, n_init=5)
        labels = kmeans.fit_predict(subsample)

        # Update co-clustering counts for all pairs in this subsample
        for i_idx in range(n_sample):
            for j_idx in range(i_idx + 1, n_sample):
                pi, pj = indices[i_idx], indices[j_idx]
                co_occurrence_count[pi, pj] += 1
                co_occurrence_count[pj, pi] += 1
                if labels[i_idx] == labels[j_idx]:
                    co_cluster_count[pi, pj] += 1
                    co_cluster_count[pj, pi] += 1

    # Compute consensus matrix (avoid division by zero)
    with np.errstate(divide="ignore", invalid="ignore"):
        consensus_matrix = np.divide(co_cluster_count, co_occurrence_count)
        consensus_matrix = np.nan_to_num(consensus_matrix, nan=0.0)

    # Set diagonal to 1 (a patient always co-clusters with itself)
    np.fill_diagonal(consensus_matrix, 1.0)

    # Cluster the consensus matrix using hierarchical clustering
    # Distance = 1 - consensus (patients always together have distance 0)
    distance_matrix = 1.0 - consensus_matrix
    final_clustering = AgglomerativeClustering(
        n_clusters=k, metric="precomputed", linkage="average"
    )
    final_labels = final_clustering.fit_predict(distance_matrix)

    # Compute PAC (Proportion of Ambiguous Clustering)
    # PAC = fraction of off-diagonal consensus values between 0.1 and 0.9
    off_diag = consensus_matrix[np.triu_indices_from(consensus_matrix, k=1)]
    pac = np.mean((off_diag > 0.1) & (off_diag < 0.9))

    logger.info(
        "Consensus clustering (K=%d, %d iterations): PAC=%.3f (lower is more stable)",
        k, n_iterations, pac
    )

    return final_labels, consensus_matrix, pac
```

---

## Step 5: Clinical Validation and Characterization

*Maps to pseudocode Step 6. For each discovered cluster, compute the feature profile and compare to the overall population. In a real scenario, you'd also compare outcomes (mortality, readmission). Here we characterize by feature means and effect sizes.*

```python
def characterize_clusters(df, feature_cols, labels):
    """
    Generate interpretable profiles for each discovered cluster.

    For each cluster, compute the mean of every feature and the effect size
    (how many standard deviations the cluster mean differs from the population
    mean). Large positive effect sizes indicate defining characteristics.

    This is what you'd present to a clinician: "Cluster 2 is characterized by
    age 81 (+2.1 SD), creatinine 2.1 (+1.8 SD), hemoglobin 10.5 (-1.5 SD)."
    """
    X = df[feature_cols].values
    overall_means = X.mean(axis=0)
    overall_stds = X.std(axis=0)

    n_clusters = len(np.unique(labels))
    characterization = {}

    for cluster_id in range(n_clusters):
        mask = labels == cluster_id
        cluster_data = X[mask]
        cluster_means = cluster_data.mean(axis=0)

        # Effect size: how far is this cluster's mean from the population mean,
        # measured in population standard deviations
        effect_sizes = (cluster_means - overall_means) / (overall_stds + 1e-8)

        # Top distinguishing features (largest absolute effect sizes)
        top_indices = np.argsort(np.abs(effect_sizes))[::-1][:5]
        top_features = [
            {"feature": feature_cols[i], "effect_size": round(float(effect_sizes[i]), 2)}
            for i in top_indices
        ]

        characterization[cluster_id] = {
            "size": int(mask.sum()),
            "fraction": round(float(mask.mean()), 3),
            "top_features": top_features,
        }

        logger.info(
            "Cluster %d: n=%d (%.1f%%) | Top features: %s",
            cluster_id, mask.sum(), mask.mean() * 100,
            ", ".join(f"{f['feature']}({f['effect_size']:+.1f})" for f in top_features)
        )

    return characterization
```

---

## Step 6: Train Subtype Classifier

*Maps to pseudocode Step 7. Once you've validated the subtypes, train a supervised classifier so new patients can be assigned to a subtype without re-running the full clustering pipeline.*

```python
def train_subtype_classifier(X_scaled, labels, feature_cols):
    """
    Train a gradient boosting classifier to assign new patients to subtypes.

    Why gradient boosting? It handles mixed feature types well, provides
    feature importance rankings, and is robust to the moderate class imbalance
    typical in subtype discovery. The trained model can be deployed as a
    SageMaker endpoint for real-time assignment.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, labels, test_size=0.2, random_state=RANDOM_SEED, stratify=labels
    )

    clf = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        random_state=RANDOM_SEED,
    )
    clf.fit(X_train, y_train)

    accuracy = clf.score(X_test, y_test)
    logger.info("Classifier accuracy: %.3f", accuracy)

    # Feature importance: which measurements drive subtype assignment?
    importance = sorted(
        zip(feature_cols, clf.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    logger.info("Top 5 features for classification: %s",
                ", ".join(f"{name}({imp:.3f})" for name, imp in importance[:5]))

    return clf, accuracy, importance
```

---

## Step 7: Store Subtype Assignments

*Writes validated subtype assignments to DynamoDB so downstream systems (care management, clinical decision support) can look up a patient's subtype in real time.*

```python
def store_subtype_assignments(patient_ids, labels, characterization, table_name=SUBTYPE_TABLE):
    """
    Write patient subtype assignments to DynamoDB.

    Each record contains the patient ID, their assigned subtype, the
    characterization of that subtype, and a timestamp for audit purposes.

    In production, you'd batch these writes using batch_write_item for
    efficiency. Here we write one at a time for clarity.
    """
    table = dynamodb.Table(table_name)
    timestamp = datetime.now(timezone.utc).isoformat()

    for patient_id, label in zip(patient_ids, labels):
        record = {
            "patient_id": str(patient_id),
            "subtype_id": int(label),
            # Serialize to JSON string; DynamoDB rejects Python floats (requires Decimal)
            "subtype_characterization": json.dumps(characterization[int(label)]),
            "assignment_timestamp": timestamp,
            "model_version": "consensus-v1",
        }
        table.put_item(Item=record)

    logger.info("Stored %d subtype assignments to DynamoDB", len(patient_ids))
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function.

```python
def run_subtype_discovery_pipeline():
    """
    Execute the complete disease subtype discovery pipeline.

    In production, each step would be a separate stage in a Step Functions
    state machine, with intermediate results stored in S3 between stages.
    Here we run everything in-memory for demonstration.
    """

    # Step 1: Generate (or load) the patient cohort with clinical features
    logger.info("=" * 60)
    logger.info("STEP 1: Generating synthetic heart failure cohort")
    logger.info("=" * 60)
    df = generate_synthetic_cohort(n_patients=2000)
    true_labels = df["true_subtype"].values

    # Step 2: Preprocess and reduce dimensions
    logger.info("=" * 60)
    logger.info("STEP 2: Preprocessing and dimensionality reduction")
    logger.info("=" * 60)
    X_scaled, X_reduced, scaler, pca_model, feature_cols = preprocess_and_reduce(df)

    # Step 3: Multi-algorithm clustering sweep
    logger.info("=" * 60)
    logger.info("STEP 3: Multi-algorithm clustering (K=2 through K=10)")
    logger.info("=" * 60)
    clustering_results = run_multi_algorithm_clustering(X_reduced)

    # Find the K with best average silhouette across algorithms
    best_k = max(
        clustering_results,
        key=lambda r: np.mean([
            r["algorithms"][alg]["silhouette"]
            for alg in r["algorithms"]
        ])
    )["k"]
    logger.info("Best K by average silhouette: %d", best_k)

    # Step 4: Consensus clustering at the best K
    # We use the full scaled feature space (X_scaled) rather than PCA-reduced space here.
    # Bootstrap resampling provides implicit regularization against dimensionality issues,
    # and retaining all features ensures the consensus matrix captures full phenotypic similarity.
    logger.info("=" * 60)
    logger.info("STEP 4: Consensus clustering (K=%d, %d iterations)", best_k, CONSENSUS_ITERATIONS)
    logger.info("=" * 60)
    final_labels, consensus_matrix, pac = consensus_clustering(X_scaled, k=best_k)

    # Step 5: Characterize the discovered clusters
    logger.info("=" * 60)
    logger.info("STEP 5: Clinical characterization of discovered subtypes")
    logger.info("=" * 60)
    characterization = characterize_clusters(df, feature_cols, final_labels)

    # Step 6: Train a classifier for assigning new patients
    logger.info("=" * 60)
    logger.info("STEP 6: Training subtype classifier")
    logger.info("=" * 60)
    classifier, accuracy, importance = train_subtype_classifier(
        X_scaled, final_labels, feature_cols
    )

    # Step 7: Store assignments (commented out since we don't have a real table)
    # store_subtype_assignments(range(len(df)), final_labels, characterization)

    # Summary
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info("Cohort size: %d patients", len(df))
    logger.info("Features: %d (reduced to %d PCA components)", len(feature_cols), X_reduced.shape[1])
    logger.info("Optimal K: %d", best_k)
    logger.info("Consensus PAC: %.3f", pac)
    logger.info("Classifier accuracy: %.3f", accuracy)

    # Return results for inspection
    return {
        "cohort_size": len(df),
        "n_features": len(feature_cols),
        "n_pca_components": X_reduced.shape[1],
        "optimal_k": best_k,
        "consensus_pac": pac,
        "classifier_accuracy": accuracy,
        "characterization": characterization,
        "top_features": importance[:5],
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = run_subtype_discovery_pipeline()
    print("\n" + json.dumps(results, indent=2, default=str))
```

---

## The Gap Between This and Production

This example runs end-to-end on synthetic data and demonstrates the core workflow. But there's a significant distance between "runs on my laptop" and "produces publishable, clinically validated disease subtypes." Here's where that gap lives:

**Real data is messy.** This synthetic data has no missing values, no outliers from data entry errors, no temporal inconsistencies. Real EHR data has 20-40% missingness in lab values, vitals recorded at inconsistent intervals, and diagnosis codes that reflect billing incentives as much as clinical reality. You'll need a robust imputation strategy (MICE, or multiple imputation with sensitivity analysis) and explicit handling of informative missingness (a missing BNP might mean "not ordered because the patient looked fine," which is itself informative).

**Feature selection requires clinical expertise.** We used 18 features here because they're the obvious ones. A real subtype discovery project starts with 50-200 candidate features and requires iterative refinement with domain experts. Which lab value matters? At what time point? Should you use the baseline value, the trajectory, or the response to treatment? These choices determine what subtypes you can find. Budget significant time for clinical collaboration on feature engineering.

**Consensus clustering at scale.** With 2,000 patients, the O(n^2) consensus matrix fits in memory. With 50,000 patients, it's 50,000 x 50,000 = 2.5 billion entries. You'll need either sparse representations, block-wise computation on SageMaker training instances, or approximate consensus methods. The SageMaker distributed training infrastructure handles this, but the code needs restructuring.

**Clinical validation is a human process.** The characterization step here computes feature profiles. In reality, you'd present these profiles to cardiologists, run survival analyses per cluster, check for treatment response differences, and iterate. This takes months, not minutes. The algorithm is the easy part; convincing clinicians that the clusters are real and actionable is the hard part.

**Stability across time.** Subtypes discovered on 2024 data should still be valid on 2025 data. You need temporal validation: train on one time period, validate on another. If the clusters shift dramatically, they may reflect data collection changes rather than biology.

**SageMaker deployment.** The classifier here is a local scikit-learn model. In production, you'd serialize it, upload to S3, and deploy as a SageMaker endpoint. The endpoint receives a patient's feature vector and returns the predicted subtype with a confidence score. SageMaker handles auto-scaling, A/B testing, and model monitoring for drift detection.

**Error handling and retries.** No try/except blocks here. A production pipeline wraps every AWS call in error handling with exponential backoff. Glue ETL jobs fail. SageMaker training jobs get preempted. S3 uploads timeout. Each failure mode needs specific handling.

**IAM least-privilege.** The IAM role for this pipeline should have exactly the permissions listed in Setup and nothing else. Scope S3 access to the specific bucket and prefix. Scope DynamoDB access to the specific table. Never use broad wildcards in production.

**VPC and encryption.** Patient clinical data is PHI. The SageMaker notebook, training jobs, and endpoints all run in a VPC with no internet egress. VPC endpoints for S3, DynamoDB, and SageMaker API keep traffic on the AWS backbone. KMS customer-managed keys encrypt all data at rest with rotation enabled.

**Experiment tracking.** This example doesn't track which parameters produced which results. SageMaker Experiments logs every training run with its hyperparameters, metrics, and artifacts. When you've run 50 clustering experiments with different feature sets and K values, you'll be grateful for systematic tracking.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.8](chapter06.08-disease-subtype-discovery.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
