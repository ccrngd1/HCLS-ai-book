# Recipe 6.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the multi-morbidity pattern discovery pipeline from Recipe 6.10. It demonstrates the core workflow (synthetic diagnosis data generation, patient-condition matrix construction, association rule mining, temporal sequence analysis, network construction with community detection, and statistical validation) using mlxtend, networkx, and boto3. It is not production-ready. Real multi-morbidity discovery requires populations of 200,000+ patients, clinical grouper mappings maintained by coding specialists, and months of iterative clinical validation. Think of this as the sketch that helps you understand the algorithmic shape of the problem, not something you'd present at a clinical governance meeting.

---

## Setup

You'll need the AWS SDK for Python and several analytics libraries:

```bash
pip install boto3 numpy pandas mlxtend networkx scipy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:GetObject`, `s3:PutObject` (diagnosis data and results storage)
- `sagemaker:CreateProcessingJob` (if running mining at scale)
- `dynamodb:PutItem`, `dynamodb:Query` (pattern storage and retrieval)

For this example, we run association mining and network analysis locally using mlxtend and networkx. In production, you'd use SageMaker Processing Jobs for the compute-intensive mining steps and Amazon Neptune for the graph database. The algorithms are identical; only the infrastructure changes.

---

## Config and Constants

```python
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from mlxtend.frequent_patterns import fpgrowth, association_rules
import networkx as nx
from networkx.algorithms.community import louvain_communities

import boto3
from botocore.config import Config

# Structured logging. Never log PHI field values (patient IDs, diagnosis details).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Configuration
RESULTS_BUCKET = "multimorbidity-discovery-results"
DIAGNOSIS_DATA_KEY = "raw/diagnosis-history.parquet"
PATTERNS_TABLE = "discovered-patterns"

# Mining parameters
MIN_PREVALENCE = 0.01          # Conditions below 1% prevalence are excluded
MIN_SUPPORT = 0.005            # Minimum 0.5% of patients must have the combination
MAX_PATTERN_SIZE = 4           # Mine up to 4-condition combinations
MIN_LIFT = 1.5                 # Only keep patterns with lift above this threshold
FDR_THRESHOLD = 0.05           # Benjamini-Hochberg false discovery rate cutoff
BOOTSTRAP_ITERATIONS = 100     # Stability testing resamples
STABILITY_THRESHOLD = 0.80     # Pattern must appear in 80%+ of resamples
MIN_TEMPORAL_PATIENTS = 50     # Minimum patients for temporal sequence analysis

RANDOM_SEED = 42
```

---

## Step 1: Generate Synthetic Diagnosis History

*The main recipe's Step 1 extracts longitudinal diagnosis data from the EHR and rolls up ICD-10 codes to clinical categories. Here we generate synthetic data that mimics what you'd get after that ETL step. The synthetic data embeds several known multi-morbidity patterns at elevated co-occurrence rates, so we can verify the mining recovers them.*

```python
def generate_synthetic_diagnoses(n_patients=5000, random_state=42):
    """
    Generate synthetic longitudinal diagnosis data with embedded multi-morbidity patterns.

    We create a population where certain condition combinations co-occur at rates
    higher than independence would predict. This lets us verify that the mining
    pipeline actually finds them.

    Embedded patterns:
    - Cardiorenal-metabolic: Diabetes + CKD + Heart Failure + Anemia (lift ~3.5)
    - Mental-physical: Depression + Chronic Pain + Substance Use (lift ~2.8)
    - Frailty triad: Osteoporosis + Falls + Cognitive Decline (lift ~3.0)

    Returns:
        DataFrame with columns: patient_id, condition, first_documented_date
    """
    rng = np.random.default_rng(random_state)

    # Define condition categories and their base prevalences in an older population.
    # These are roughly realistic for a Medicare-age cohort.
    conditions = {
        "Hypertension": 0.55,
        "Hyperlipidemia": 0.45,
        "Type 2 Diabetes": 0.28,
        "Obesity": 0.35,
        "GERD": 0.20,
        "Osteoarthritis": 0.30,
        "Depression": 0.18,
        "Chronic Pain": 0.22,
        "CKD": 0.12,
        "Heart Failure": 0.09,
        "COPD": 0.11,
        "Atrial Fibrillation": 0.08,
        "Anemia": 0.10,
        "Osteoporosis": 0.12,
        "Substance Use Disorder": 0.06,
        "Cognitive Decline": 0.07,
        "Falls History": 0.09,
        "Peripheral Neuropathy": 0.08,
        "Sleep Apnea": 0.14,
        "Anxiety": 0.15,
    }

    # Start with independent assignment based on prevalence.
    records = []
    base_date = datetime(2014, 1, 1)

    # Track which patients get which conditions for pattern injection.
    patient_conditions = {pid: set() for pid in range(n_patients)}

    # Assign conditions independently first.
    for pid in range(n_patients):
        for condition, prevalence in conditions.items():
            if rng.random() < prevalence:
                patient_conditions[pid].add(condition)
                # Random onset date within a 10-year window.
                days_offset = int(rng.integers(0, 3650))
                onset = base_date + timedelta(days=days_offset)
                records.append({
                    "patient_id": f"PAT-{pid:05d}",
                    "condition": condition,
                    "first_documented_date": onset.strftime("%Y-%m-%d"),
                })

    # Inject multi-morbidity patterns at elevated rates.
    # For patients who already have the "seed" condition, give them the
    # remaining conditions in the pattern with high probability.

    # Pattern 1: Cardiorenal-metabolic cascade
    # Diabetes → CKD → Anemia → Heart Failure (temporal ordering)
    pattern1 = ["Type 2 Diabetes", "CKD", "Anemia", "Heart Failure"]
    for pid in range(n_patients):
        if "Type 2 Diabetes" in patient_conditions[pid] and rng.random() < 0.35:
            # This patient gets the full cascade.
            cascade_start = base_date + timedelta(days=int(rng.integers(0, 1000)))
            for i, cond in enumerate(pattern1):
                if cond not in patient_conditions[pid]:
                    patient_conditions[pid].add(cond)
                    # Each subsequent condition appears 1-3 years after the previous.
                    onset = cascade_start + timedelta(days=int(365 * (i * 1.5 + rng.random())))
                    records.append({
                        "patient_id": f"PAT-{pid:05d}",
                        "condition": cond,
                        "first_documented_date": onset.strftime("%Y-%m-%d"),
                    })

    # Pattern 2: Mental-physical overlap
    pattern2 = ["Depression", "Chronic Pain", "Substance Use Disorder"]
    for pid in range(n_patients):
        if "Depression" in patient_conditions[pid] and rng.random() < 0.30:
            onset_base = base_date + timedelta(days=int(rng.integers(0, 2000)))
            for i, cond in enumerate(pattern2):
                if cond not in patient_conditions[pid]:
                    patient_conditions[pid].add(cond)
                    onset = onset_base + timedelta(days=int(365 * (i * 0.8 + rng.random())))
                    records.append({
                        "patient_id": f"PAT-{pid:05d}",
                        "condition": cond,
                        "first_documented_date": onset.strftime("%Y-%m-%d"),
                    })

    # Pattern 3: Frailty triad
    pattern3 = ["Osteoporosis", "Falls History", "Cognitive Decline"]
    for pid in range(n_patients):
        if "Osteoporosis" in patient_conditions[pid] and rng.random() < 0.32:
            onset_base = base_date + timedelta(days=int(rng.integers(1000, 3000)))
            for i, cond in enumerate(pattern3):
                if cond not in patient_conditions[pid]:
                    patient_conditions[pid].add(cond)
                    onset = onset_base + timedelta(days=int(365 * (i * 1.2 + rng.random())))
                    records.append({
                        "patient_id": f"PAT-{pid:05d}",
                        "condition": cond,
                        "first_documented_date": onset.strftime("%Y-%m-%d"),
                    })

    df = pd.DataFrame(records)

    # Deduplicate: keep earliest onset per patient-condition pair.
    df["first_documented_date"] = pd.to_datetime(df["first_documented_date"])
    df = df.sort_values("first_documented_date").drop_duplicates(
        subset=["patient_id", "condition"], keep="first"
    ).reset_index(drop=True)

    logger.info("Generated %d diagnosis records for %d patients across %d conditions",
                len(df), n_patients, df["condition"].nunique())

    return df
```

---

## Step 2: Build Patient-Condition Matrix and Compute Baselines

*The main recipe's Step 2 constructs the binary patient-condition matrix and computes individual prevalences plus expected co-occurrence rates under independence. These baselines are essential for calculating lift. Without them, you'd just find that common conditions co-occur frequently (not a discovery).*

```python
def build_patient_condition_matrix(diagnoses_df, min_prevalence=0.01):
    """
    Transform longitudinal diagnosis records into a binary patient-condition matrix.

    Also computes individual condition prevalences and filters out rare conditions
    that lack statistical power for combination analysis.

    Args:
        diagnoses_df: DataFrame with patient_id, condition, first_documented_date
        min_prevalence: Minimum fraction of patients who must have a condition
                        for it to be included in the analysis.

    Returns:
        Tuple of (binary_matrix DataFrame, prevalences dict, active_conditions list)
    """
    # Pivot to binary matrix: rows = patients, columns = conditions, values = 0/1.
    binary_matrix = diagnoses_df.pivot_table(
        index="patient_id",
        columns="condition",
        aggfunc="size",  # count occurrences
        fill_value=0
    )

    # Convert counts to binary (presence/absence).
    binary_matrix = (binary_matrix > 0).astype(int)

    n_patients = len(binary_matrix)
    logger.info("Patient-condition matrix: %d patients x %d conditions",
                n_patients, binary_matrix.shape[1])

    # Compute prevalences.
    prevalences = (binary_matrix.sum() / n_patients).to_dict()

    # Filter to conditions meeting minimum prevalence.
    active_conditions = [
        cond for cond, prev in prevalences.items()
        if prev >= min_prevalence
    ]

    filtered_matrix = binary_matrix[active_conditions]
    logger.info("After prevalence filter (>= %.1f%%): %d conditions retained",
                min_prevalence * 100, len(active_conditions))

    # Log the top conditions by prevalence for sanity checking.
    sorted_prev = sorted(prevalences.items(), key=lambda x: x[1], reverse=True)
    for cond, prev in sorted_prev[:5]:
        logger.info("  %s: %.1f%%", cond, prev * 100)

    return filtered_matrix, prevalences, active_conditions
```

---

## Step 3: Association Rule Mining with FP-Growth

*The main recipe's Step 3 applies FP-Growth to find frequent condition combinations and computes lift, confidence, and leverage. FP-Growth is preferred over Apriori for dense datasets because it avoids expensive candidate generation. The mlxtend library provides a clean implementation that works directly with our binary DataFrame.*

```python
def mine_association_rules(binary_matrix, min_support=0.005, max_len=4, min_lift=1.5):
    """
    Run FP-Growth frequent itemset mining and compute association metrics.

    FP-Growth efficiently finds all condition combinations that appear in at
    least min_support fraction of patients. Then we compute lift, confidence,
    and leverage for each combination to identify those that co-occur more
    than chance would predict.

    Args:
        binary_matrix: Binary patient-condition DataFrame (from Step 2)
        min_support: Minimum fraction of patients with the combination
        max_len: Maximum number of conditions in a pattern
        min_lift: Minimum lift to retain a pattern

    Returns:
        DataFrame of discovered patterns with association metrics
    """
    n_patients = len(binary_matrix)

    # Run FP-Growth to find frequent itemsets.
    # This is the computationally expensive step. For 200k patients and 280 conditions,
    # you'd run this on a SageMaker Processing Job. For our 5k synthetic patients,
    # it runs in seconds locally.
    logger.info("Running FP-Growth (min_support=%.3f, max_len=%d)...", min_support, max_len)
    frequent_itemsets = fpgrowth(
        binary_matrix,
        min_support=min_support,
        max_len=max_len,
        use_colnames=True  # Use condition names instead of column indices
    )

    if frequent_itemsets.empty:
        logger.warning("No frequent itemsets found. Try lowering min_support.")
        return pd.DataFrame()

    logger.info("Found %d frequent itemsets", len(frequent_itemsets))

    # Filter to multi-condition patterns (size >= 2).
    # Single conditions aren't "patterns" in the multi-morbidity sense.
    frequent_itemsets["size"] = frequent_itemsets["itemsets"].apply(len)
    multi_condition = frequent_itemsets[frequent_itemsets["size"] >= 2].copy()
    logger.info("Multi-condition itemsets (size >= 2): %d", len(multi_condition))

    # Compute association rules (lift, confidence, leverage).
    # We use lift as the primary metric because it normalizes for base rates.
    rules = association_rules(
        frequent_itemsets,
        metric="lift",
        min_threshold=min_lift
    )

    if rules.empty:
        logger.warning("No rules above min_lift=%.1f. Try lowering threshold.", min_lift)
        return pd.DataFrame()

    # Also compute metrics for the full itemsets (not just antecedent→consequent rules).
    # For multi-morbidity, we care about the full combination, not directional rules.
    patterns = []
    for _, row in multi_condition.iterrows():
        itemset = frozenset(row["itemsets"])
        support = row["support"]
        patient_count = int(support * n_patients)

        # Compute expected support under independence.
        individual_prevalences = [
            binary_matrix[cond].mean() for cond in itemset
        ]
        expected_support = np.prod(individual_prevalences)

        # Lift: how much more often does this combination appear than expected?
        lift = support / expected_support if expected_support > 0 else 0

        # Leverage: absolute difference between observed and expected.
        leverage = support - expected_support

        if lift >= min_lift:
            patterns.append({
                "conditions": sorted(list(itemset)),
                "size": len(itemset),
                "support": round(support, 4),
                "patient_count": patient_count,
                "expected_support": round(expected_support, 6),
                "lift": round(lift, 2),
                "leverage": round(leverage, 4),
            })

    patterns_df = pd.DataFrame(patterns)
    patterns_df = patterns_df.sort_values("lift", ascending=False).reset_index(drop=True)

    logger.info("Patterns with lift >= %.1f: %d", min_lift, len(patterns_df))
    # Show top 5 for sanity check.
    for _, p in patterns_df.head(5).iterrows():
        logger.info("  %s | lift=%.2f | n=%d",
                    " + ".join(p["conditions"]), p["lift"], p["patient_count"])

    return patterns_df
```

---

## Step 4: Temporal Sequence Analysis

*The main recipe's Step 4 analyzes the temporal ordering of condition acquisition within each discovered pattern. This is where multi-morbidity discovery gets genuinely interesting: knowing that diabetes typically precedes CKD by 4 years gives you a prevention window. Static co-occurrence alone doesn't tell you that.*

```python
def analyze_temporal_sequences(patterns_df, diagnoses_df, min_patients=50):
    """
    For each discovered pattern, determine the dominant temporal ordering
    of condition onset and compute inter-condition intervals.

    This transforms "these conditions co-occur" into "these conditions develop
    in this order with these time gaps," which is directly actionable for
    preventive care planning.

    Args:
        patterns_df: DataFrame of discovered patterns (from Step 3)
        diagnoses_df: Original longitudinal diagnosis data with onset dates
        min_patients: Minimum patients with the full pattern for temporal analysis

    Returns:
        List of dicts with temporal analysis results for each pattern
    """
    temporal_results = []

    for _, pattern_row in patterns_df.iterrows():
        conditions = pattern_row["conditions"]
        patient_count = pattern_row["patient_count"]

        if patient_count < min_patients:
            continue

        # Find patients who have ALL conditions in this pattern.
        pattern_diagnoses = diagnoses_df[diagnoses_df["condition"].isin(conditions)]

        # Group by patient and check who has the complete set.
        patient_cond_counts = pattern_diagnoses.groupby("patient_id")["condition"].nunique()
        complete_patients = patient_cond_counts[
            patient_cond_counts == len(conditions)
        ].index.tolist()

        if len(complete_patients) < min_patients:
            continue

        # For each complete patient, get the ordered sequence of condition onsets.
        sequences = []
        for pid in complete_patients:
            patient_data = pattern_diagnoses[pattern_diagnoses["patient_id"] == pid]
            # Sort by onset date to get temporal ordering.
            ordered = patient_data.sort_values("first_documented_date")
            sequence = ordered["condition"].tolist()
            sequences.append(sequence)

        # Find the most common ordering (dominant sequence).
        # Convert sequences to tuples for counting.
        sequence_tuples = [tuple(s) for s in sequences]
        from collections import Counter
        ordering_counts = Counter(sequence_tuples)
        dominant_ordering = ordering_counts.most_common(1)[0]
        dominant_sequence = list(dominant_ordering[0])
        dominant_fraction = dominant_ordering[1] / len(sequences)

        # Compute median inter-condition intervals for the dominant ordering.
        intervals = {}
        for i in range(len(dominant_sequence) - 1):
            cond_a = dominant_sequence[i]
            cond_b = dominant_sequence[i + 1]

            days_between = []
            for pid in complete_patients:
                patient_data = pattern_diagnoses[pattern_diagnoses["patient_id"] == pid]
                date_a = patient_data[patient_data["condition"] == cond_a][
                    "first_documented_date"
                ].iloc[0]
                date_b = patient_data[patient_data["condition"] == cond_b][
                    "first_documented_date"
                ].iloc[0]
                delta = (date_b - date_a).days
                if delta > 0:  # Only count forward progressions.
                    days_between.append(delta)

            if days_between:
                median_years = round(np.median(days_between) / 365.25, 1)
                iqr_years = round(
                    (np.percentile(days_between, 75) - np.percentile(days_between, 25)) / 365.25,
                    1
                )
                intervals[f"{cond_a} → {cond_b}"] = {
                    "median_years": median_years,
                    "iqr_years": iqr_years,
                }

        temporal_results.append({
            "conditions": conditions,
            "n_complete_patients": len(complete_patients),
            "dominant_ordering": dominant_sequence,
            "dominant_fraction": round(dominant_fraction, 2),
            "intervals": intervals,
            "n_alternative_orderings": len(ordering_counts) - 1,
        })

        logger.info("Temporal: %s | dominant order: %s (%.0f%%)",
                    " + ".join(conditions),
                    " → ".join(dominant_sequence),
                    dominant_fraction * 100)

    logger.info("Temporal analysis complete for %d patterns", len(temporal_results))
    return temporal_results
```

---

## Step 5: Comorbidity Network Construction and Community Detection

*The main recipe's Step 5 builds a graph where conditions are nodes and edges represent statistically significant co-occurrence. Community detection finds clusters of tightly connected conditions. In production, you'd store this in Amazon Neptune. Here we use networkx for the same algorithms.*

```python
def build_comorbidity_network(patterns_df, prevalences, fdr_threshold=0.05, min_lift=1.5):
    """
    Construct a comorbidity network from pairwise association patterns and
    run community detection to find multi-morbidity neighborhoods.

    Conditions become nodes. Edges connect conditions that co-occur significantly
    more than chance predicts (after FDR correction). Community detection groups
    conditions into clusters that may share underlying mechanisms.

    Args:
        patterns_df: DataFrame of discovered patterns (from Step 3)
        prevalences: Dict of condition -> prevalence (from Step 2)
        fdr_threshold: Maximum adjusted p-value for edge inclusion
        min_lift: Minimum lift for edge inclusion

    Returns:
        Tuple of (networkx Graph, dict of community assignments)
    """
    # Filter to pairwise patterns only (edges in the network).
    pairwise = patterns_df[patterns_df["size"] == 2].copy()

    if pairwise.empty:
        logger.warning("No pairwise patterns found for network construction.")
        return nx.Graph(), {}

    # Compute chi-squared p-values for each pair.
    # This tests whether the co-occurrence is statistically significant
    # beyond what prevalence alone would predict.
    p_values = []
    for _, row in pairwise.iterrows():
        # Chi-squared test of independence.
        # Observed: support * N patients have both conditions.
        # Expected: product of individual prevalences * N.
        observed = row["support"]
        expected = row["expected_support"]

        # Use a simple z-test approximation for large samples.
        # In production, you'd use the full chi-squared contingency test.
        n = row["patient_count"] / row["support"]  # total population
        se = np.sqrt(expected * (1 - expected) / n) if expected > 0 else 1
        z = (observed - expected) / se if se > 0 else 0
        p_value = 2 * (1 - stats.norm.cdf(abs(z)))  # two-tailed
        p_values.append(p_value)

    pairwise["p_value"] = p_values

    # Benjamini-Hochberg FDR correction.
    # When testing thousands of pairs, many will appear "significant" by chance.
    # FDR correction controls the expected proportion of false discoveries.
    sorted_indices = np.argsort(p_values)
    n_tests = len(p_values)
    adjusted_p = np.zeros(n_tests)

    for rank, idx in enumerate(sorted_indices, 1):
        adjusted_p[idx] = p_values[idx] * n_tests / rank

    # Enforce monotonicity (adjusted p-values should be non-decreasing).
    for i in range(n_tests - 2, -1, -1):
        adjusted_p[sorted_indices[i]] = min(
            adjusted_p[sorted_indices[i]],
            adjusted_p[sorted_indices[i + 1]] if i + 1 < n_tests else 1.0
        )

    pairwise["adjusted_p"] = np.minimum(adjusted_p, 1.0)

    # Filter to significant edges.
    significant = pairwise[
        (pairwise["adjusted_p"] < fdr_threshold) & (pairwise["lift"] >= min_lift)
    ]

    logger.info("Network edges: %d significant pairs (of %d tested)",
                len(significant), len(pairwise))

    # Build the graph.
    G = nx.Graph()

    # Add all conditions as nodes with prevalence as an attribute.
    for cond, prev in prevalences.items():
        G.add_node(cond, prevalence=prev)

    # Add significant co-occurrence relationships as weighted edges.
    for _, row in significant.iterrows():
        cond_a, cond_b = row["conditions"]
        G.add_edge(cond_a, cond_b, weight=row["lift"], support=row["support"])

    # Remove isolated nodes (conditions with no significant connections).
    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)
    logger.info("Network: %d nodes, %d edges (removed %d isolates)",
                G.number_of_nodes(), G.number_of_edges(), len(isolates))

    # Community detection using Louvain algorithm.
    # Finds groups of conditions more densely connected to each other
    # than to the rest of the network. These communities represent
    # multi-morbidity "neighborhoods."
    communities_list = louvain_communities(G, weight="weight", seed=RANDOM_SEED)

    # Convert to node -> community_id mapping.
    community_map = {}
    for comm_id, members in enumerate(communities_list):
        for node in members:
            community_map[node] = comm_id

    # Assign community labels to nodes.
    nx.set_node_attributes(G, community_map, "community")

    logger.info("Detected %d communities:", len(communities_list))
    for comm_id, members in enumerate(communities_list):
        logger.info("  Community %d: %s", comm_id, ", ".join(sorted(members)))

    return G, community_map
```

---

## Step 6: Statistical Validation and Stability Testing

*The main recipe's Step 6 applies rigorous statistical filters to separate genuine patterns from artifacts of demographics or multiple testing. Bootstrap resampling tests whether patterns are stable or just noise from a particular sample. Patterns that survive validation are genuinely surprising given the population's characteristics.*

```python
def validate_patterns(patterns_df, binary_matrix, min_lift_adjusted=1.3):
    """
    Validate discovered patterns through bootstrap stability testing.

    A pattern is "stable" if it appears consistently across random resamples
    of the patient population. Unstable patterns may be artifacts of the
    specific sample rather than genuine population-level associations.

    In production, you'd also stratify by age/sex and adjust for healthcare
    utilization (see the main recipe's Step 6 for the full validation approach).
    Here we demonstrate the bootstrap stability component.

    Args:
        patterns_df: DataFrame of discovered patterns
        binary_matrix: Binary patient-condition matrix
        min_lift_adjusted: Minimum lift threshold for validation

    Returns:
        DataFrame of validated patterns with stability scores
    """
    validated = []
    n_patients = len(binary_matrix)

    for _, pattern_row in patterns_df.iterrows():
        conditions = pattern_row["conditions"]

        # Bootstrap stability test.
        # Resample patients with replacement and recompute lift each time.
        # If the pattern's lift stays above threshold in 80%+ of resamples,
        # it's stable.
        stable_count = 0

        for i in range(BOOTSTRAP_ITERATIONS):
            # Resample patients with replacement.
            sample_indices = np.random.choice(
                n_patients, size=int(n_patients * 0.8), replace=True
            )
            sample = binary_matrix.iloc[sample_indices]

            # Compute support in this resample.
            # A patient "has the pattern" if they have ALL conditions.
            has_all = sample[conditions].all(axis=1)
            sample_support = has_all.mean()

            # Compute expected support under independence.
            individual_prevs = [sample[c].mean() for c in conditions]
            expected = np.prod(individual_prevs)

            # Compute lift.
            sample_lift = sample_support / expected if expected > 0 else 0

            if sample_lift >= min_lift_adjusted:
                stable_count += 1

        stability = stable_count / BOOTSTRAP_ITERATIONS

        if stability >= STABILITY_THRESHOLD:
            validated.append({
                **pattern_row.to_dict(),
                "stability": round(stability, 2),
            })
            logger.info("  VALIDATED: %s | lift=%.2f | stability=%.2f",
                        " + ".join(conditions), pattern_row["lift"], stability)
        else:
            logger.info("  REJECTED (unstable): %s | stability=%.2f",
                        " + ".join(conditions), stability)

    validated_df = pd.DataFrame(validated)
    logger.info("Validation complete: %d of %d patterns survived",
                len(validated_df), len(patterns_df))

    return validated_df
```

---

## Step 7: Store Results to S3 and DynamoDB

*This step persists the validated patterns and temporal analysis to S3 (for batch analytics and QuickSight dashboards) and DynamoDB (for real-time lookup by clinical applications). In production, you'd also write the network to Neptune for interactive graph exploration.*

```python
def store_results(validated_patterns, temporal_results, network_graph, community_map):
    """
    Persist discovery results to S3 and DynamoDB.

    S3 gets the full analysis output (patterns, temporal sequences, network metrics)
    for downstream analytics and visualization. DynamoDB gets individual pattern
    records for real-time lookup by clinical decision support systems.

    Args:
        validated_patterns: DataFrame of validated multi-morbidity patterns
        temporal_results: List of temporal analysis dicts
        network_graph: networkx Graph of the comorbidity network
        community_map: Dict mapping conditions to community IDs
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # --- Store full results to S3 ---
    results_payload = {
        "analysis_timestamp": timestamp,
        "n_validated_patterns": len(validated_patterns),
        "patterns": validated_patterns.to_dict(orient="records"),
        "temporal_sequences": temporal_results,
        "network_summary": {
            "n_nodes": network_graph.number_of_nodes(),
            "n_edges": network_graph.number_of_edges(),
            "n_communities": len(set(community_map.values())),
            "communities": {
                str(comm_id): [n for n, c in community_map.items() if c == comm_id]
                for comm_id in set(community_map.values())
            },
        },
    }

    results_key = f"results/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/patterns.json"
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=results_key,
        Body=json.dumps(results_payload, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        # In production, specify your KMS key ARN with SSEKMSKeyId.
    )
    logger.info("Results stored to s3://%s/%s", RESULTS_BUCKET, results_key)

    # --- Store individual patterns to DynamoDB ---
    table = dynamodb.Table(PATTERNS_TABLE)

    for idx, pattern_row in validated_patterns.iterrows():
        # Find matching temporal result if available.
        temporal_match = next(
            (t for t in temporal_results if t["conditions"] == pattern_row["conditions"]),
            None
        )

        item = {
            "pattern_id": f"MMP-{idx:04d}",
            "conditions": pattern_row["conditions"],
            "size": pattern_row["size"],
            "support": Decimal(str(pattern_row["support"])),
            "patient_count": pattern_row["patient_count"],
            "lift": Decimal(str(pattern_row["lift"])),
            "stability": Decimal(str(pattern_row["stability"])),
            "discovery_timestamp": timestamp,
            "clinical_review_status": "pending",
        }

        # Add temporal data if available.
        if temporal_match:
            item["dominant_ordering"] = temporal_match["dominant_ordering"]
            item["dominant_fraction"] = Decimal(str(temporal_match["dominant_fraction"]))
            item["intervals"] = json.dumps(temporal_match["intervals"])

        # Add community assignment.
        # A pattern's community is the community of its first condition
        # (or the most common community among its conditions).
        pattern_communities = [
            community_map.get(c, -1) for c in pattern_row["conditions"]
        ]
        if pattern_communities:
            from collections import Counter
            most_common_community = Counter(pattern_communities).most_common(1)[0][0]
            item["community_id"] = most_common_community

        # DynamoDB does not accept Python floats. All numeric values must be Decimal.
        # We've already wrapped them above. This is a common gotcha that will raise
        # TypeError if you forget.
        table.put_item(Item=item)

    logger.info("Stored %d patterns to DynamoDB table '%s'",
                len(validated_patterns), PATTERNS_TABLE)
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, each step would be a separate SageMaker Processing Job or Glue job, orchestrated by Step Functions. Here we run them sequentially for clarity.

```python
def discover_multimorbidity_patterns():
    """
    Run the full multi-morbidity pattern discovery pipeline.

    Steps:
    1. Generate (or load) longitudinal diagnosis data
    2. Build patient-condition matrix and compute baselines
    3. Mine association rules with FP-Growth
    4. Analyze temporal sequences for top patterns
    5. Build comorbidity network and detect communities
    6. Validate patterns through bootstrap stability testing
    7. Store results to S3 and DynamoDB

    Returns:
        Dict with validated patterns, temporal results, and network summary.
    """
    print("=" * 70)
    print("MULTI-MORBIDITY PATTERN DISCOVERY PIPELINE")
    print("=" * 70)

    # Step 1: Generate synthetic diagnosis data.
    # In production, this would be a Glue ETL job reading from your EHR data lake.
    print("\n[Step 1] Generating synthetic diagnosis history...")
    diagnoses_df = generate_synthetic_diagnoses(n_patients=5000)
    print(f"  Generated {len(diagnoses_df)} records for "
          f"{diagnoses_df['patient_id'].nunique()} patients")

    # Step 2: Build patient-condition matrix.
    print("\n[Step 2] Building patient-condition matrix...")
    binary_matrix, prevalences, active_conditions = build_patient_condition_matrix(
        diagnoses_df, min_prevalence=MIN_PREVALENCE
    )
    print(f"  Matrix shape: {binary_matrix.shape}")
    print(f"  Active conditions: {len(active_conditions)}")

    # Step 3: Mine association rules.
    print("\n[Step 3] Mining association rules (FP-Growth)...")
    patterns_df = mine_association_rules(
        binary_matrix,
        min_support=MIN_SUPPORT,
        max_len=MAX_PATTERN_SIZE,
        min_lift=MIN_LIFT,
    )
    print(f"  Discovered {len(patterns_df)} patterns with lift >= {MIN_LIFT}")

    if patterns_df.empty:
        print("  No patterns found. Pipeline complete (no results).")
        return {"patterns": [], "temporal": [], "network": None}

    # Step 4: Temporal sequence analysis.
    print("\n[Step 4] Analyzing temporal sequences...")
    temporal_results = analyze_temporal_sequences(
        patterns_df, diagnoses_df, min_patients=MIN_TEMPORAL_PATIENTS
    )
    print(f"  Temporal analysis complete for {len(temporal_results)} patterns")

    # Step 5: Build comorbidity network.
    print("\n[Step 5] Constructing comorbidity network...")
    network_graph, community_map = build_comorbidity_network(
        patterns_df, prevalences, fdr_threshold=FDR_THRESHOLD, min_lift=MIN_LIFT
    )
    print(f"  Network: {network_graph.number_of_nodes()} nodes, "
          f"{network_graph.number_of_edges()} edges")
    print(f"  Communities detected: {len(set(community_map.values()))}")

    # Step 6: Validate patterns.
    print("\n[Step 6] Validating patterns (bootstrap stability)...")
    np.random.seed(RANDOM_SEED)
    validated_df = validate_patterns(patterns_df, binary_matrix)
    print(f"  Validated: {len(validated_df)} of {len(patterns_df)} patterns")

    # Step 7: Store results.
    print("\n[Step 7] Storing results to S3 and DynamoDB...")
    store_results(validated_df, temporal_results, network_graph, community_map)

    # Print summary.
    print("\n" + "=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)
    print(f"\nValidated multi-morbidity patterns: {len(validated_df)}")
    print(f"Patterns with temporal analysis: {len(temporal_results)}")
    print(f"Network communities: {len(set(community_map.values()))}")

    print("\nTop validated patterns:")
    for _, p in validated_df.head(5).iterrows():
        print(f"  {' + '.join(p['conditions'])}")
        print(f"    lift={p['lift']}, stability={p['stability']}, n={p['patient_count']}")

    if temporal_results:
        print("\nTemporal sequences:")
        for t in temporal_results[:3]:
            print(f"  {' → '.join(t['dominant_ordering'])} "
                  f"({t['dominant_fraction']*100:.0f}% of patients)")
            for transition, interval in t["intervals"].items():
                print(f"    {transition}: {interval['median_years']} years "
                      f"(IQR: {interval['iqr_years']} years)")

    return {
        "patterns": validated_df.to_dict(orient="records"),
        "temporal": temporal_results,
        "network_nodes": network_graph.number_of_nodes(),
        "network_edges": network_graph.number_of_edges(),
        "communities": len(set(community_map.values())),
    }


# Run the pipeline.
if __name__ == "__main__":
    results = discover_multimorbidity_patterns()
```

---

## The Gap Between This and Production

This example demonstrates the algorithmic pipeline. Run it and you'll see discovered patterns, temporal sequences, and network communities. But there's a significant distance between "runs on synthetic data locally" and "drives clinical care model decisions at a health system." Here's where that gap lives:

**Population scale.** This example uses 5,000 synthetic patients. Real multi-morbidity discovery needs 200,000+ patients for adequate statistical power on three-way and four-way combinations. At that scale, FP-Growth on a single machine becomes memory-constrained. You'd use SageMaker Processing Jobs with ml.m5.4xlarge or larger instances, or distribute the computation across a Spark cluster via Glue.

**Clinical grouper maintenance.** We skipped the ICD-10 rollup entirely (our synthetic data already uses clinical categories). In production, maintaining the mapping from 70,000+ ICD-10 codes to 200-300 clinical categories is a significant ongoing effort. Codes change annually. New conditions get added. Your clinical informatics team needs to own this mapping and update it with each code set release.

**Confounder adjustment.** The validation step here only does bootstrap stability. The main recipe's Step 6 also adjusts for age, sex, and healthcare utilization. Without these adjustments, your "discoveries" may just be "things that happen to old people who see doctors frequently." Stratified analysis or propensity score matching is essential for credible results.

**Neptune for the graph.** We used networkx in-memory. For a production comorbidity network that gets queried interactively by clinical analysts, you'd store it in Amazon Neptune. Neptune supports Gremlin and openCypher queries, handles concurrent access, and persists the graph across sessions. The network can be updated incrementally as new data arrives without rebuilding from scratch.

**Clinical review workflow.** The pipeline produces patterns with `clinical_review_status: "pending"`. In production, you need a review interface (QuickSight dashboard or custom application) where clinicians can examine each pattern, mark it as "known," "novel and actionable," "novel but not actionable," or "artifact." Without this human-in-the-loop step, the patterns are just statistics, not clinical intelligence.

**Error handling and retries.** Every AWS API call (S3, DynamoDB, SageMaker) can fail transiently. Production code wraps each call in try/except with exponential backoff. The boto3 retry config helps, but you also need application-level retry logic for cases where a Processing Job fails mid-run and needs to be restarted from a checkpoint.

**Logging and monitoring.** The `print()` statements here are placeholders. Production uses structured JSON logging via AWS Lambda Powertools or the standard logging module with CloudWatch Logs. You want every pipeline run to produce machine-parseable log entries with: population size, conditions analyzed, patterns discovered, patterns validated, runtime per step, and any errors. CloudWatch alarms should fire if the pipeline produces zero validated patterns (something is wrong) or if runtime exceeds expected bounds.

**IAM least-privilege.** The IAM role for the SageMaker Processing Job should have exactly: `s3:GetObject` and `s3:PutObject` scoped to specific buckets, `dynamodb:PutItem` scoped to the patterns table, and `kms:Decrypt`/`kms:GenerateDataKey` for the encryption keys. Not `s3:*`. Not `AdministratorAccess`.

**VPC and encryption.** Diagnosis histories are PHI. All compute (SageMaker, Glue) runs in a VPC with VPC endpoints for S3, DynamoDB, and CloudWatch. Neptune requires VPC deployment (there's no public endpoint option). All data at rest is encrypted with KMS customer-managed keys. All transit is TLS 1.2+.

**Temporal data quality.** Our synthetic data has clean onset dates. Real EHR data has conditions documented at the same encounter (making temporal ordering ambiguous), conditions carried forward from historical records (making "first documented" unreliable), and coding practices that vary across providers. You'll need heuristics to handle these edge cases: same-day conditions might be ordered by encounter type (inpatient diagnoses likely preceded outpatient documentation), and "first documented" should exclude encounters where the condition was clearly historical.

**DynamoDB Decimal requirement.** This example already wraps numeric values in `Decimal()` (see Step 7). DynamoDB's boto3 resource layer does not accept Python floats. If you add new numeric fields to the pattern records, remember to wrap them. The `TypeError: Float types are not supported` error is one of those things that bites everyone exactly once.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.10](chapter06.10-multi-morbidity-pattern-discovery.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
