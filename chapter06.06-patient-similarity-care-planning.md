# Recipe 6.6: Patient Similarity for Care Planning

**Complexity:** Medium-Complex · **Phase:** Growth · **Estimated Cost:** ~$0.15-$0.40 per similarity query (depending on cohort size and feature count)

---

## The Problem

A care manager is sitting with a newly diagnosed Type 2 diabetes patient. The patient is 54, has mild hypertension, works a desk job, and lives alone. The care manager needs to build a care plan. What interventions are most likely to work? What does a realistic trajectory look like? What should they watch for in the first six months?

The care manager has seen hundreds of diabetes patients. But memory is unreliable, biased toward recent cases, and terrible at pattern matching across dozens of variables simultaneously. What they really want is to ask: "Show me patients like this one who did well. What did their care plans look like? What worked?"

This is the patient similarity problem. Find historical patients who are meaningfully similar to a current patient, examine their outcomes, and use those outcomes to inform care planning for the new patient. It sounds straightforward. It is not.

The core difficulty is defining "similar." Two patients might share a diagnosis but differ in age, comorbidities, social circumstances, medication tolerance, and a dozen other factors that influence outcomes. A naive approach (match on diagnosis and age) produces cohorts so broad they're useless. An overly specific approach (match on everything) produces cohorts so small you can't draw conclusions. The art is in finding the right features, the right distance metric, and the right balance between specificity and statistical power.

When it works, patient similarity transforms care planning from "what does the average patient experience" to "what do patients like you experience." That's a fundamentally different conversation. It sets realistic expectations, identifies interventions with track records for similar populations, and surfaces risks that might not be obvious from the diagnosis alone.

When it doesn't work, it produces misleading comparisons that reinforce existing biases, ignore important differences, or suggest interventions that worked for a superficially similar but fundamentally different population. The stakes are high. A bad recommendation based on a bad similarity match is worse than no recommendation at all.

---

## The Technology: How Patient Similarity Works

### The Concept of Distance in Patient Space

Patient similarity is, at its core, a nearest-neighbor problem. You represent each patient as a point in a high-dimensional space (where each dimension is a feature: age, BMI, A1C, number of comorbidities, medication count, etc.), and then you find the points closest to your query patient.

The intuition is simple: if two patients are "close" in this feature space, they're similar. The devil is in three details: which features define the space, how you measure distance, and how you handle the fact that some features matter more than others.

### Feature Engineering: What Makes Patients "Similar"

This is where you absolutely need clinical expertise. A purely data-driven approach might discover that patients who share the same zip code have similar outcomes. That's not clinically useful similarity; it's a confound. Feature selection for patient similarity requires domain knowledge about which characteristics actually drive outcomes for the condition in question.

Typical feature categories include:

**Demographics:** Age, sex, BMI. These are baseline characteristics that influence disease trajectory.

**Clinical markers:** Lab values (A1C, creatinine, lipid panels), vital signs (blood pressure, heart rate), functional assessments. These capture current disease state.

**Comorbidity profile:** Which other conditions the patient has. A diabetic patient with heart failure has a fundamentally different trajectory than a diabetic patient without it. Comorbidity indices (like Charlson or Elixhauser) compress this into a score, but you lose granularity.

**Treatment history:** What medications they're on, what they've tried and failed, surgical history. Two patients with the same disease state but different treatment histories are not interchangeable.

**Utilization patterns:** ED visits, hospitalizations, specialist visits. These capture disease burden in a way that clinical markers alone might miss.

**Social determinants:** Living situation, employment, insurance type, transportation access. These influence adherence and outcomes but are often poorly captured in structured data.

The challenge is that not all features are equally important, and importance varies by condition. For diabetes care planning, A1C and medication history might dominate. For heart failure, ejection fraction and NYHA class matter more. A one-size-fits-all feature set produces mediocre similarity for every condition.

### Distance Metrics: How to Measure "Close"

Once you have features, you need a way to measure how far apart two patients are. The standard options:

**Euclidean distance:** Straight-line distance in feature space. Simple, intuitive, but sensitive to feature scaling. If age ranges from 0-100 and A1C ranges from 4-14, age will dominate the distance calculation unless you normalize.

**Cosine similarity:** Measures the angle between two feature vectors rather than the absolute distance. Useful when the magnitude of features matters less than their relative proportions.

**Gower distance:** Designed for mixed data types (continuous, categorical, binary). Healthcare data is almost always mixed: age is continuous, sex is binary, insurance type is categorical. Gower handles this natively without forcing everything into numeric encoding.

**Mahalanobis distance:** Accounts for correlations between features. If A1C and BMI are correlated in your population, Mahalanobis won't double-count that shared variance. More statistically rigorous but requires estimating a covariance matrix, which needs a large sample.

**Learned embeddings:** Train a neural network to map patients into a latent space where proximity corresponds to outcome similarity. This is the most powerful approach but requires labeled outcome data for training and is the hardest to explain to clinicians.

In practice, Gower distance with feature weighting is the most common starting point for healthcare applications. It handles mixed types gracefully and the weights give clinicians a lever to encode domain knowledge ("A1C matters more than zip code for diabetes similarity").

### The k-Nearest Neighbors Approach

The simplest architecture: compute the distance from your query patient to every patient in your historical cohort, sort by distance, and return the k closest. Examine their outcomes. If 8 out of 10 nearest neighbors achieved A1C control within 6 months on metformin plus lifestyle intervention, that's a strong signal for the care plan.

The problems with brute-force kNN at scale:

**Computational cost.** If your cohort is 500,000 patients with 50 features each, computing distance to every one for every query is expensive. Approximate nearest neighbor (ANN) algorithms (locality-sensitive hashing, HNSW graphs, tree-based methods) trade a small amount of accuracy for dramatic speed improvements.

**The curse of dimensionality.** In high-dimensional spaces, distances become less meaningful. All points tend to be roughly equidistant. Feature selection and dimensionality reduction (PCA, autoencoders) help, but you need to validate that reduced representations preserve clinically meaningful similarity.

**Outcome validation.** Finding similar patients is only useful if similar patients actually have similar outcomes. You need to validate this empirically: do the k nearest neighbors of a patient actually have more similar outcomes than random patients? If not, your similarity metric isn't capturing what matters.

### Beyond kNN: Embedding-Based Approaches

More sophisticated systems learn patient representations (embeddings) from data. The idea: train a model that maps each patient's feature vector into a lower-dimensional space where proximity corresponds to outcome similarity, not just feature similarity.

Approaches include:

**Autoencoders:** Compress patient features into a latent representation, then use distance in latent space as similarity. The autoencoder learns which feature combinations matter for reconstruction, which is a proxy for "which features define the patient."

**Siamese networks:** Train a network with pairs of patients labeled as "similar outcome" or "different outcome." The network learns a distance function that directly optimizes for outcome similarity rather than feature similarity.

**Graph-based embeddings:** Represent patients as nodes in a graph (connected by shared providers, shared diagnoses, temporal proximity of visits), then learn node embeddings. Patients with similar graph neighborhoods get similar embeddings.

These approaches are more powerful but require more data, more compute, and more effort to validate and explain. For most healthcare organizations starting with patient similarity, weighted kNN with Gower distance is the right first step. Graduate to embeddings when you've validated the concept and need better performance.

---

## General Architecture Pattern

```
[Feature Store] → [Similarity Engine] → [Outcome Aggregation] → [Care Plan Recommendations]
```

**Feature Store.** A curated, versioned repository of patient features. Not raw EHR data. Engineered features: computed comorbidity scores, normalized lab values, medication categories, utilization summaries. Updated on a schedule (daily or weekly) as new clinical data arrives. The feature store is the foundation; garbage features produce garbage similarity.

**Similarity Engine.** Takes a query patient's feature vector, computes distance to the historical cohort, and returns the k most similar patients. For scale, this uses an approximate nearest neighbor index rather than brute-force search. The index is rebuilt periodically as the feature store updates.

**Outcome Aggregation.** For the k similar patients, aggregate their outcomes: What interventions did they receive? What were their trajectories at 3, 6, 12 months? What percentage achieved target goals? What adverse events occurred? This is where raw similarity becomes actionable intelligence.

**Care Plan Recommendations.** Present the aggregated outcomes to the care manager in a format that supports decision-making. Not "do this." Rather: "Among 15 patients similar to yours, 11 achieved A1C < 7 within 6 months. 9 of those were on metformin plus a GLP-1 agonist. 3 had hypoglycemic events in the first month." The care manager decides. The system informs.

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for model training and hosting.** The similarity engine (whether kNN, an autoencoder, or a more complex model) needs to be trained on historical patient data and served for real-time inference. SageMaker provides the training infrastructure, model hosting, and built-in kNN algorithm. For embedding-based approaches, SageMaker's custom training containers support PyTorch or TensorFlow models. The built-in kNN algorithm supports both Euclidean and cosine distance with approximate search using FAISS under the hood.

**Amazon S3 for feature store storage.** The curated feature datasets (patient feature vectors, outcome labels, feature metadata) live in S3 as versioned Parquet files. S3 provides durable, encrypted storage with versioning for reproducibility. SageMaker Feature Store could also serve this role for organizations that want managed feature pipelines, but S3 with a well-organized prefix structure is simpler to start with and easier to debug.

**AWS Glue for feature engineering pipelines.** Transforming raw EHR data into engineered features (computing comorbidity indices, normalizing lab values, aggregating utilization) is an ETL job. Glue handles the extraction from source systems, the transformation logic, and the loading into the feature store. Spark-based processing handles the scale of multi-year patient populations.

**Amazon DynamoDB for similarity results caching.** Similarity queries for the same patient don't change until new data arrives. Caching results in DynamoDB (keyed by patient ID and feature version) avoids redundant inference calls. TTL-based expiration ensures results refresh when the feature store updates.

**Amazon OpenSearch Service for approximate nearest neighbor search (alternative).** For organizations that want sub-second similarity queries without managing a SageMaker endpoint, OpenSearch supports kNN search natively with HNSW and FAISS indices. You index patient embeddings as dense vectors and query with the target patient's vector. This is particularly attractive if you already have OpenSearch in your stack for other search use cases.

**AWS Lambda for orchestration.** The query flow (receive patient ID, look up features, check cache, call similarity engine, aggregate outcomes, return results) is a stateless orchestration task. Lambda handles the glue logic between services. The orchestrator should also emit application-level audit events (who queried which patient, when, and what was returned) to support HIPAA accounting-of-disclosures requirements.

### Architecture Diagram

```mermaid
flowchart TD
    A[EHR / Claims Data] -->|Nightly ETL| B[AWS Glue\nFeature Engineering]
    B -->|Parquet| C[S3 Feature Store\npatient-features/]
    C -->|Training Data| D[SageMaker Training\nkNN / Embedding Model]
    D -->|Model Artifact| E[SageMaker Endpoint\nSimilarity Inference]

    F[Care Manager\nQuery] -->|Patient ID| G[Lambda\nOrchestrator]
    G -->|Check Cache| H[DynamoDB\nSimilarity Cache]
    H -->|Cache Miss| G
    G -->|Feature Lookup| C
    G -->|Find Similar| E
    E -->|Top-k Patient IDs| G
    G -->|Outcome Lookup| I[S3 / RDS\nOutcome Data]
    G -->|Aggregated Results| J[Care Planning UI]

    style C fill:#f9f,stroke:#333
    style E fill:#ff9,stroke:#333
    style H fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker, Amazon S3, AWS Glue, Amazon DynamoDB, AWS Lambda, Amazon CloudWatch |
| **IAM Permissions** | `sagemaker:InvokeEndpoint` (scoped to the similarity endpoint ARN), `s3:GetObject`/`s3:PutObject` (scoped to the feature store bucket and prefix), `glue:StartJobRun`, `dynamodb:GetItem`/`dynamodb:PutItem` (scoped to the cache table ARN), `lambda:InvokeFunction`. Scope all permissions to specific resource ARNs. |
| **BAA** | AWS BAA signed (patient features and outcomes are PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest; SageMaker: KMS for model artifacts and endpoint data; all API calls over TLS |
| **VPC** | Production: Lambda and SageMaker endpoint in VPC with VPC endpoints for S3, DynamoDB, CloudWatch Logs, and SageMaker Runtime (`com.amazonaws.{region}.sagemaker.runtime`). Configure security groups to restrict egress to VPC endpoint ENIs only (no internet egress). |
| **CloudTrail** | Enabled: log all SageMaker inference calls and S3 access for HIPAA audit trail |
| **Application Audit Log** | Lambda orchestrator logs each query: requesting user, query patient ID, timestamp, result count, and confidence level. Immutable log (CloudWatch Logs with retention policy) for HIPAA accounting of disclosures. |
| **Sample Data** | Synthetic patient cohort with features and outcomes. CMS Synthetic Public Use Files provide realistic population distributions. Never use real PHI in development. |
| **Cost Estimate** | SageMaker endpoint (ml.m5.large): ~$0.12/hour. Glue ETL: ~$0.44/DPU-hour. DynamoDB on-demand: ~$1.25 per million reads. S3 storage: negligible. Total per query (with caching): $0.15-$0.40 depending on cache hit rate. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Trains similarity model; hosts real-time inference endpoint for kNN/embedding queries |
| **Amazon S3** | Stores versioned patient feature vectors and outcome datasets |
| **AWS Glue** | Runs nightly ETL to transform raw EHR/claims data into engineered features |
| **Amazon DynamoDB** | Caches similarity results to avoid redundant inference; TTL-based expiration |
| **AWS Lambda** | Orchestrates query flow: feature lookup, cache check, inference call, outcome aggregation |
| **AWS KMS** | Manages encryption keys for all data stores and model artifacts |
| **Amazon CloudWatch** | Monitors endpoint latency, cache hit rates, and feature freshness |

### Code

> **Reference implementations:** The following AWS sample repos demonstrate patterns used in this recipe:
>
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Includes kNN algorithm examples, feature engineering notebooks, and endpoint deployment patterns
> - [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): End-to-end feature store patterns including ingestion, transformation, and real-time retrieval

#### Walkthrough

**Step 1: Feature engineering pipeline.** Raw EHR data is not suitable for similarity computation. Lab values arrive at different times, diagnoses accumulate over years, medications change. This step transforms raw clinical data into a fixed-length feature vector per patient: one row, one patient, all relevant characteristics normalized and ready for distance computation. The feature engineering runs nightly (or weekly, depending on data freshness requirements) and produces a versioned snapshot. Without this step, you'd be comparing raw, sparse, temporal clinical records directly, which is computationally intractable and clinically meaningless.

```
FUNCTION engineer_patient_features(patient_id, raw_clinical_data):
    // Transform raw clinical records into a fixed-length feature vector.
    // Each patient becomes a single row with standardized, comparable values.

    features = empty map

    // Demographics: straightforward extraction
    features["age"]  = calculate_age(raw_clinical_data.date_of_birth)
    features["sex"]  = encode_binary(raw_clinical_data.sex)  // 0 or 1
    features["bmi"]  = most_recent_value(raw_clinical_data.vitals, "BMI")

    // Clinical markers: use most recent values, normalized to population z-scores.
    // Z-scoring ensures that A1C (range 4-14) and creatinine (range 0.5-5)
    // contribute equally to distance calculations.
    lab_features = ["a1c", "creatinine", "ldl", "hdl", "triglycerides",
                    "systolic_bp", "diastolic_bp"]
    FOR each lab in lab_features:
        raw_value = most_recent_value(raw_clinical_data.labs, lab)
        features[lab] = z_score_normalize(raw_value, population_mean[lab], population_std[lab])

    // Comorbidity profile: binary flags for conditions that influence trajectory.
    // These are condition-specific. For diabetes similarity, we care about
    // cardiovascular comorbidities, renal disease, and mental health conditions.
    comorbidity_flags = ["heart_failure", "ckd", "cad", "depression",
                         "obesity", "hypertension", "copd"]
    FOR each condition in comorbidity_flags:
        features[condition] = has_active_diagnosis(raw_clinical_data.problems, condition)

    // Medication complexity: count of active medications and specific drug classes.
    features["medication_count"] = count_active_medications(raw_clinical_data.medications)
    features["on_insulin"]       = is_on_drug_class(raw_clinical_data.medications, "insulin")
    features["on_metformin"]     = is_on_drug_class(raw_clinical_data.medications, "metformin")
    features["on_glp1"]          = is_on_drug_class(raw_clinical_data.medications, "GLP-1 agonist")

    // Utilization summary: captures disease burden beyond what labs show.
    features["ed_visits_12mo"]       = count_events(raw_clinical_data.encounters, "ED", months=12)
    features["hospitalizations_12mo"] = count_events(raw_clinical_data.encounters, "inpatient", months=12)

    // Disease duration: how long they've had the primary condition.
    features["years_since_diagnosis"] = years_since_first_diagnosis(
        raw_clinical_data.problems, target_condition
    )

    RETURN features  // fixed-length vector ready for similarity computation
```

**Step 2: Build the similarity index.** With feature vectors for the entire historical cohort, build an index that enables fast nearest-neighbor lookup. For cohorts under 100,000 patients, brute-force kNN is feasible. For larger populations, approximate nearest neighbor (ANN) indices provide sub-second query times at the cost of occasionally missing a true nearest neighbor. The index is rebuilt whenever the feature store updates. Skip this step and every query requires scanning the entire cohort, which is too slow for interactive care planning workflows.

A note on minimum cohort size: aim for at least 500-1,000 patients in a condition-specific index to provide meaningful diversity of neighbors. Below that threshold, consider broader condition groupings or display a warning that the comparison pool is limited.

```
FUNCTION build_similarity_index(feature_store_path, index_config):
    // Load all patient feature vectors from the feature store.
    // Each row is one patient; each column is one engineered feature.
    patient_features = load_parquet(feature_store_path)

    // Apply feature weights before indexing.
    // Weights encode clinical judgment: "A1C matters 3x more than age for diabetes similarity."
    // These weights come from clinical SMEs, not from the data.
    weighted_features = apply_weights(patient_features, index_config.feature_weights)

    // Build the ANN index. HNSW (Hierarchical Navigable Small World) graphs
    // provide excellent recall (>95%) with sub-millisecond query times.
    // The ef_construction parameter controls index quality vs. build time.
    index = build_hnsw_index(
        vectors          = weighted_features,
        distance_metric  = index_config.distance_metric,  // "euclidean" or "cosine"
        ef_construction  = 200,   // higher = better recall, slower build
        M                = 16     // connections per node; 16 is a good default
    )

    // Store the index artifact for deployment to the inference endpoint.
    save_index(index, output_path=index_config.artifact_path)

    // Also store the patient ID mapping: index position -> patient_id.
    // The index returns positions (0, 1, 2...); we need to map back to real patient IDs.
    save_id_mapping(patient_features.patient_ids, index_config.mapping_path)

    RETURN index
```

**Step 3: Query for similar patients.** When a care manager requests similarity for a specific patient, look up that patient's current feature vector, query the index for the k nearest neighbors, and return the matched patient IDs with their distance scores. The distance score is important: it tells you how confident you should be in the similarity. A nearest neighbor at distance 0.1 is much more informative than one at distance 2.5. If all neighbors are far away, the system should say "no strong matches found" rather than returning poor matches with false confidence.

```
FUNCTION find_similar_patients(query_patient_id, k=20, max_distance=None):
    // Look up the query patient's current feature vector.
    query_features = get_patient_features(query_patient_id)

    IF query_features is None:
        RETURN error("Patient not found in feature store. May need to wait for next ETL run.")

    // Apply the same feature weights used during index construction.
    weighted_query = apply_weights(query_features, feature_weights)

    // Query the ANN index for the k nearest neighbors.
    // Returns: list of (index_position, distance) pairs, sorted by distance ascending.
    neighbors = index.query(weighted_query, k=k)

    // Map index positions back to patient IDs.
    results = empty list
    FOR each (position, distance) in neighbors:
        patient_id = id_mapping[position]

        // Skip the query patient themselves (they're always their own nearest neighbor).
        IF patient_id == query_patient_id:
            CONTINUE

        // Optionally filter by maximum distance threshold.
        // If max_distance is set and this neighbor is too far, stop.
        IF max_distance is not None AND distance > max_distance:
            BREAK

        append to results: {
            patient_id: patient_id,
            distance:   distance,
            similarity: 1.0 / (1.0 + distance)  // convert distance to 0-1 similarity score
        }

    RETURN results
```

**Step 4: Aggregate outcomes for similar patients.** Finding similar patients is only half the job. The value comes from examining what happened to them. This step retrieves outcome data for the matched cohort and aggregates it into actionable summaries: what interventions were used, what percentage achieved target goals, what adverse events occurred, and what the typical timeline looked like. The aggregation must be honest about sample size. If only 3 similar patients exist, the confidence in any conclusion is low, and the system should communicate that clearly.

```
FUNCTION aggregate_outcomes(similar_patients, outcome_config):
    // Retrieve outcome records for all similar patients.
    // Outcomes include: goal achievement, interventions received, adverse events, timeline.
    outcomes = empty list
    FOR each match in similar_patients:
        patient_outcome = get_outcome_record(match.patient_id, outcome_config.condition)
        IF patient_outcome is not None:
            append to outcomes: {
                patient_id:    match.patient_id,
                distance:      match.distance,
                interventions: patient_outcome.interventions,   // list of treatments received
                goal_achieved: patient_outcome.goal_achieved,   // boolean: did they hit target?
                time_to_goal:  patient_outcome.time_to_goal,    // months to achieve target (if achieved)
                adverse_events: patient_outcome.adverse_events  // list of complications
            }

    // Aggregate into a summary the care manager can act on.
    summary = {
        cohort_size:          length(outcomes),
        goal_achievement_rate: count(o.goal_achieved == true for o in outcomes) / length(outcomes),
        median_time_to_goal:  median(o.time_to_goal for o in outcomes where o.goal_achieved),

        // Intervention frequency: which treatments were most common among successful patients?
        intervention_frequency: count_interventions(
            [o for o in outcomes where o.goal_achieved == true]
        ),

        // Adverse event rate: what complications did similar patients experience?
        adverse_event_rate: count(o.adverse_events is not empty for o in outcomes) / length(outcomes),
        common_adverse_events: most_common(flatten(o.adverse_events for o in outcomes)),

        // Confidence indicator based on cohort size.
        confidence: CASE
            WHEN length(outcomes) >= 20 THEN "high"
            WHEN length(outcomes) >= 10 THEN "moderate"
            WHEN length(outcomes) >= 5  THEN "low"
            ELSE "insufficient"
        END
    }

    RETURN summary
```

**Step 5: Store and present results.** Cache the similarity results (they don't change until the feature store updates) and format them for the care planning interface. The presentation layer is critical: raw statistics are not useful to a care manager in a 15-minute appointment. The output should be a concise narrative with supporting data, not a data dump. Note that the default presentation returns only aggregated outcome statistics; individual similar patient IDs are not exposed to the UI unless the organization's data governance policy permits drill-down with appropriate authorization controls.

The DynamoDB cache stores derived PHI (patient IDs and outcome summaries) and should be treated as a PHI data store subject to your organization's retention and amendment policies. DynamoDB TTL deletion is eventually consistent (items may persist up to 48 hours past expiration), so do not rely on TTL alone as a hard deletion guarantee for compliance purposes. If source patient data is corrected or a patient exercises amendment rights, implement an explicit cache invalidation mechanism rather than waiting for TTL expiry.

```
FUNCTION store_and_present(query_patient_id, similar_patients, outcome_summary):
    // Cache results in DynamoDB with TTL matching feature store refresh interval.
    cache_record = {
        patient_id:       query_patient_id,
        feature_version:  current_feature_store_version(),
        similar_patients: similar_patients,
        outcome_summary:  outcome_summary,
        computed_at:      current_utc_timestamp(),
        ttl:              current_utc_timestamp() + 86400  // expire after 24 hours
    }
    write_to_cache(cache_record)

    // Format for care planning UI.
    presentation = {
        headline: format_headline(outcome_summary),
        // Example: "Among 18 similar patients, 72% achieved A1C < 7 within 6 months."

        top_interventions: outcome_summary.intervention_frequency[0:3],
        // Top 3 most common interventions among successful similar patients.

        risk_factors: outcome_summary.common_adverse_events[0:3],
        // Top 3 adverse events to watch for.

        confidence_note: format_confidence(outcome_summary.confidence, outcome_summary.cohort_size),
        // Example: "Based on 18 similar patients (moderate confidence)."

        similar_patient_details: similar_patients[0:5]
        // Top 5 most similar patients for drill-down (de-identified in the UI).
    }

    RETURN presentation
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter06.06-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a newly diagnosed Type 2 diabetes patient:**

```json
{
  "query_patient_id": "PAT-2026-08842",
  "feature_version": "v2026-03-15",
  "cohort_size": 18,
  "confidence": "moderate",
  "outcome_summary": {
    "goal_achievement_rate": 0.72,
    "median_time_to_goal_months": 4.5,
    "top_interventions": [
      {"intervention": "metformin_1000mg", "frequency": 0.89},
      {"intervention": "lifestyle_counseling", "frequency": 0.78},
      {"intervention": "glp1_agonist", "frequency": 0.44}
    ],
    "adverse_event_rate": 0.22,
    "common_adverse_events": [
      {"event": "gi_intolerance_metformin", "frequency": 0.17},
      {"event": "hypoglycemia_mild", "frequency": 0.06}
    ]
  },
  "top_similar_patients": [
    {"patient_id": "PAT-2024-12091", "similarity": 0.94, "distance": 0.063},
    {"patient_id": "PAT-2023-45672", "similarity": 0.91, "distance": 0.099},
    {"patient_id": "PAT-2025-03318", "similarity": 0.89, "distance": 0.124}
  ]
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Query latency (cached) | 50-150 ms |
| Query latency (uncached, ANN) | 500-1500 ms |
| Feature engineering (per patient) | ~200 ms |
| Index rebuild (100k patients) | 5-15 minutes |
| Recall@20 (ANN vs. brute-force) | 95-98% |
| Feature store refresh | Nightly (configurable) |

**Where it struggles:** Patients with rare condition combinations (few neighbors exist). Patients early in their disease course (limited outcome data for similar early-stage patients). Populations underrepresented in historical data (the system can only find similar patients if similar patients exist in the training set). Rapidly evolving treatment landscapes (historical outcomes may not reflect current best practices).

---

## Why This Isn't Production-Ready

**Feature drift.** Clinical practice changes. A feature set designed in 2024 may not capture what matters in 2026 if new drug classes emerge or guidelines shift. You need a process for periodic feature review with clinical SMEs, not just a one-time build.

**Outcome data lag.** You can only aggregate outcomes for patients who have had enough time to demonstrate them. A 6-month outcome requires patients who were diagnosed at least 6 months ago. For new conditions or new populations, the outcome data simply doesn't exist yet.

**Bias amplification.** If your historical data reflects disparities (certain populations received less aggressive treatment and had worse outcomes), the similarity engine will faithfully reproduce those patterns. "Patients like you historically did poorly" might mean "patients like you historically received inadequate care." The system needs bias auditing and the care manager needs to understand this limitation.

**Explainability.** A care manager needs to understand why two patients are considered similar. "The algorithm says so" is not acceptable in clinical decision support. You need feature-level explanations: "These patients are similar because they share age range, A1C level, comorbidity profile, and medication history."

<!-- TODO (TechWriter): Expert review A1 (HIGH). Add data governance subsection: patient similarity uses one patient's historical data to inform another's care. Under HIPAA, this typically falls under Treatment/Payment/Operations (no individual authorization required), but organizational policies, state laws, and data use agreements may impose additional constraints. IRB review may be required if the system is used for research or outcomes are published. Patients should be informed that de-identified data contributes to care planning tools. This is a must-address governance conversation before deployment. -->

**Feature store version transitions.** When the nightly ETL produces a new feature snapshot, the ANN index must be rebuilt before queries reflect the latest data. During the rebuild window (5-15 minutes for 100k patients), queries continue against the previous index version. Cached results include a `feature_version` key, so stale entries expire naturally when the version advances. A patient diagnosed with a new condition today won't appear in similarity results for that condition until the next ETL run plus index rebuild completes. For most care planning workflows, this eventual consistency (up to 24 hours) is acceptable. If same-day freshness is required, consider a hybrid approach: serve from the pre-built index for most queries, with a real-time override path for patients whose data changed since the last build.

<!-- TODO (TechWriter): Expert review S1 (HIGH). Address cross-patient PHI exposure model. The similarity results contain patient IDs of other patients. Default recommendation: return only aggregated outcome statistics to the care planning UI (no individual patient IDs). If drill-down into individual similar patient records is needed, require break-the-glass authorization and log the access. The current sample output JSON shows patient IDs in top_similar_patients; clarify that this is the internal API response, not what the UI displays. -->

---

## The Honest Take

Patient similarity is one of those ideas that sounds obviously useful and is genuinely hard to get right. The first time I built one of these, I spent two weeks tuning the distance metric before realizing my feature set was the actual problem. The concept is intuitive: find patients like this one, see what worked. The execution is full of subtle traps.

The biggest trap is the assumption that "similar features" implies "similar outcomes." It often does. But sometimes two patients look identical on paper and have wildly different trajectories because of factors you didn't capture: social support, health literacy, genetic variation, provider quality. Your similarity metric is only as good as your features, and your features are only as good as your data capture.

The second trap is sample size. For common conditions in large health systems, you'll find plenty of similar patients. For rare conditions, complex multi-morbidity patterns, or small health systems, the cohort might be 3 patients. Presenting aggregated outcomes from 3 patients as if they're statistically meaningful is dangerous. The system must communicate uncertainty honestly.

The thing that surprised me most: clinicians don't want a black box that says "do this." They want a tool that says "here's what happened to patients like yours, here's what was tried, here's what worked and what didn't." The decision remains theirs. The system provides evidence. That framing (decision support, not decision making) is both ethically correct and practically necessary for adoption.

Start with a single condition (diabetes is the classic choice: large population, well-defined outcomes, measurable goals). Validate that your similarity metric actually predicts outcome similarity before expanding. And involve clinicians in feature selection from day one. The features that matter are not always the features that are easy to compute.

---

## Variations and Extensions

**Condition-specific similarity models.** Rather than one general similarity engine, build condition-specific models with tailored feature sets and weights. Diabetes similarity emphasizes A1C, medication history, and comorbidities. Heart failure similarity emphasizes ejection fraction, NYHA class, and diuretic response. Each model is smaller, faster, and more clinically relevant.

**Temporal trajectory matching.** Instead of matching on current state, match on trajectory shape. Find patients who had a similar disease progression pattern (not just a similar snapshot) and see where their trajectories diverged. This requires time-series features and dynamic time warping or similar sequence-matching techniques. More complex, but captures the "where is this patient headed" question better than static similarity.

**Federated similarity across institutions.** Patient similarity improves with larger cohorts, but PHI can't leave institutional boundaries. Federated learning approaches train local similarity models at each institution and share model parameters (not patient data) to build a collective model. This is technically feasible but operationally complex: data harmonization across institutions is a prerequisite, and it's a hard problem in itself.

---

## Related Recipes

- **Recipe 6.4 (Disease Severity Stratification):** Provides the severity tiers that can serve as a pre-filter before similarity search (only compare within the same severity tier)
- **Recipe 6.7 (Clinical Trial Patient Matching):** Uses similar feature-matching techniques but optimizes for eligibility criteria rather than outcome similarity
- **Recipe 7.1 (Readmission Risk Scoring):** Predictive models that can be informed by outcomes of similar patients
- **Recipe 4.9 (Personalized Care Plan Generation):** Consumes similarity-based evidence to generate tailored care plans
- **Recipe 13.1 (Medical Ontology Mapping):** Knowledge graphs can enrich feature engineering by providing semantic relationships between diagnoses and medications

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Built-in kNN Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/k-nearest-neighbors.html)
- [Amazon SageMaker Feature Store](https://docs.aws.amazon.com/sagemaker/latest/dg/feature-store.html)
- [Amazon OpenSearch Service k-NN Search](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn.html)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Comprehensive SageMaker examples including kNN, feature engineering, and model deployment patterns
- [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): Feature store patterns for ingestion, transformation, and real-time retrieval

**AWS Solutions and Blogs:**
- [Guidance for Multi-Modal Data Analysis with AWS HealthOmics](https://aws.amazon.com/solutions/guidance/multi-modal-data-analysis-with-aws-health-omics/): Reference architecture for patient data analysis pipelines
- [Machine Learning Best Practices in Healthcare and Life Sciences](https://aws.amazon.com/blogs/machine-learning/): Search for patient similarity and cohort analysis posts

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 4-6 weeks | Single-condition similarity with weighted kNN, manual feature selection, batch processing |
| **Production-ready** | 10-14 weeks | Multi-condition models, ANN indexing, real-time queries, caching, bias auditing, clinician-facing UI |
| **With variations** | 16-22 weeks | Temporal trajectory matching, condition-specific models, federated learning exploration |

---

**Tags:** `cohort-analysis` `patient-similarity` `knn` `nearest-neighbor` `care-planning` `feature-engineering` `sagemaker` `clinical-decision-support` `embeddings`

---

| [← 6.5: Provider Practice Pattern Analysis](chapter06.05-provider-practice-pattern-analysis) | [Chapter 6 Index](chapter06-index) | [6.7: Clinical Trial Patient Matching →](chapter06.07-clinical-trial-patient-matching) |
