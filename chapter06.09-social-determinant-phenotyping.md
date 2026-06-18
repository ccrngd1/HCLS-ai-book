# Recipe 6.9: Social Determinant Phenotyping

**Complexity:** Complex · **Phase:** Research/Production · **Estimated Cost:** ~$0.15–$0.40 per patient profile

---

## The Problem

A 62-year-old woman with diabetes shows up in the ED for the third time this quarter with uncontrolled blood sugar. Her A1C is climbing. Her care team is frustrated. They've adjusted her insulin regimen twice. They've referred her to a diabetes educator. Nothing sticks.

What nobody documented in a structured field: she lost her housing six months ago. She's couch-surfing between her daughter's apartment and a friend's place. She can't refrigerate insulin reliably. She can't maintain a consistent meal schedule. The diabetes isn't the problem. The diabetes is a symptom of the problem.

This is the social determinants of health (SDOH) gap. Clinicians know intuitively that housing, food access, transportation, social isolation, and economic instability drive health outcomes. The research is overwhelming: zip code predicts life expectancy better than genetic code. But healthcare systems are terrible at capturing this information in a structured, actionable way.

Here's why. SDOH data lives in three places, and none of them talk to each other well:

1. **Clinical notes.** A social worker writes "patient reports difficulty affording medications" in a progress note. A physician documents "lives alone, no family support nearby." This information is trapped in free text, invisible to analytics.

2. **Screening tools.** Some organizations use structured SDOH screeners (PRAPARE, AHC HRSN, Protocol for Responding to and Assessing Patients' Assets, Risks, and Experiences). But screening rates are low, patients don't always disclose, and the data goes stale fast.

3. **External data.** Census tract poverty rates, food desert maps, Area Deprivation Index scores. These are population-level proxies, not individual-level truths. A wealthy person can live in a poor zip code and vice versa.

The result: health systems make clinical decisions without understanding the social context that determines whether those decisions will actually work. They cluster patients by disease, by utilization, by cost. But they rarely cluster by the social circumstances that explain why some patients thrive and others spiral.

Social determinant phenotyping is the practice of building composite profiles of patients' social circumstances by combining NLP extraction from clinical notes, structured screening data, and community-level indicators into coherent, actionable clusters. Not just "this patient has food insecurity" but "this patient belongs to a phenotype characterized by housing instability, transportation barriers, and social isolation, and patients in this phenotype respond best to community health worker outreach rather than phone-based care management."

That's what we're building.

---

## The Technology: Clustering on Sparse, Sensitive, Multi-Modal Data

### Why This Is Harder Than Standard Clustering

Standard patient clustering (Recipe 6.1 through 6.4) works on relatively clean, structured data: diagnosis codes, lab values, utilization counts. The features are numeric, complete (mostly), and well-understood. You pick a distance metric, run k-means or hierarchical clustering, and interpret the results.

Social determinant phenotyping breaks every one of those assumptions:

**Sparsity.** Most patients don't have structured SDOH data. Screening rates at even progressive health systems hover around 20-40% of encounters. For the remaining 60-80%, you're inferring from notes, or you have nothing at all. Your feature matrix is mostly zeros and nulls, and you can't tell the difference between "screened negative for food insecurity" and "never asked about food insecurity."

**Multi-modality.** Your signal comes from at least three different data types: free-text clinical notes (unstructured), screening questionnaire responses (structured categorical), and geographic/community indicators (continuous numeric). Combining these into a single feature space requires careful engineering.

**Temporal instability.** Social circumstances change. A patient who was stably housed last year may be homeless today. A patient who had reliable transportation lost it when their car broke down. SDOH phenotypes are not static labels; they're snapshots that decay in relevance over time.

**Sensitivity and bias.** Clustering patients by social vulnerability creates categories that correlate with race, ethnicity, and socioeconomic status. If you're not careful, you build a system that effectively redlines patients. The clusters must be used to direct resources toward vulnerable populations, never to deny care or justify disparities.

### NLP Extraction: Getting Signal from Notes

The first technical challenge is extracting SDOH mentions from clinical text. This is a specialized NLP problem because:

- SDOH language is indirect. Clinicians rarely write "patient is food insecure." They write "patient reports skipping meals to afford medications" or "difficulty maintaining diet due to limited grocery access."
- Negation matters enormously. "Patient denies housing instability" is the opposite of "patient reports housing instability." Your NLP must handle negation correctly.
- Context windows matter. The relevant sentence might be buried in a 3-page social work assessment, a brief aside in a physician note, or a nursing intake form.

The standard approach uses a combination of:

1. **Named Entity Recognition (NER)** trained on SDOH-specific ontologies. The most common taxonomy is the Gravity Project's SDOH Clinical Care standard, which defines categories like housing instability, food insecurity, transportation insecurity, financial strain, social isolation, and interpersonal violence.

2. **Assertion classification** to determine whether a detected mention is affirmed, negated, or hypothetical. "Patient has housing instability" (affirmed) vs. "patient denies housing instability" (negated) vs. "if patient loses housing" (hypothetical).

3. **Temporal reasoning** to determine when the social circumstance was active. "Patient was homeless in 2019 but is now stably housed" should not be coded as current homelessness.

Pre-trained clinical NLP models (trained on clinical text corpora) provide a starting point, but SDOH-specific fine-tuning is almost always necessary. The vocabulary of social determinants is different from the vocabulary of clinical findings, and general clinical NER models miss most SDOH mentions.

### Feature Engineering: Building the Phenotype Vector

Once you have extracted SDOH signals from notes and combined them with structured screening data and community indicators, you need to represent each patient as a feature vector suitable for clustering. The typical feature space includes:

**NLP-derived features (per SDOH domain):**
- Binary presence/absence of each SDOH category (housing, food, transport, financial, social, safety)
- Mention frequency (more mentions may indicate severity or persistence)
- Recency of most recent mention
- Assertion polarity (affirmed vs. negated)

**Structured screening features:**
- Screening tool responses (often Likert scales or yes/no)
- Screening completion rate (itself informative: patients who refuse screening may differ systematically)

**Community-level features:**
- Area Deprivation Index (ADI) for patient's census tract
- Food desert indicator (USDA Food Access Research Atlas)
- Transportation access score
- Social vulnerability index (CDC SVI)

**Derived features:**
- SDOH burden score (count of active domains)
- Temporal trajectory (improving, stable, worsening)
- Concordance between self-report and NLP extraction

### Clustering Approaches for Sparse, Mixed Data

Standard k-means assumes continuous features and Euclidean distance. That's a poor fit here. Better options:

**K-prototypes** handles mixed categorical and continuous features natively. It uses Hamming distance for categorical features and Euclidean for continuous ones, with a weighting parameter to balance the two.

**Gower distance with hierarchical clustering** computes pairwise distances that handle mixed types (binary, categorical, continuous) and missing values gracefully. Hierarchical clustering then builds a dendrogram you can cut at different levels to explore different granularities.

**Latent class analysis (LCA)** is a model-based approach that assumes patients belong to unobserved latent classes, each with its own probability distribution over the observed features. LCA handles categorical data naturally and provides probabilistic cluster membership rather than hard assignments.

**Autoencoders for dimensionality reduction** can learn a compressed representation of the sparse, high-dimensional feature space, and you cluster in the latent space. This works well when you have enough data to train the encoder, but interpretability suffers.

For SDOH phenotyping specifically, LCA and Gower-distance hierarchical clustering tend to work best because they handle the mixed data types and sparsity patterns without requiring imputation gymnastics.

### Validation: The Hard Part

Unlike supervised learning, there's no ground truth for "correct" SDOH phenotypes. Validation requires:

1. **Clinical face validity.** Do the clusters make intuitive sense to social workers and care managers? Can they describe the "typical patient" in each cluster?

2. **Predictive validity.** Do the phenotypes predict outcomes that matter? Patients in the "housing instability + social isolation" cluster should have different utilization patterns, different intervention response rates, and different health trajectories than patients in the "transportation barrier only" cluster.

3. **Stability.** If you re-run the clustering on a different time window or a different patient sample, do you get similar phenotypes? Unstable clusters aren't useful for operational decision-making.

4. **Equity audit.** Do the clusters correlate with race/ethnicity in ways that could enable discrimination? If cluster 3 is 90% Black patients, you need to understand why and ensure the cluster is used to direct resources, not to justify disparities.

---

## General Architecture Pattern

```
[Clinical Notes] ──→ [NLP Extraction] ──→ [SDOH Feature Store]
                                                    ↑
[Screening Data] ──────────────────────────────────→│
                                                    ↑
[Community Data] ──→ [Geocoding + Linkage] ────────→│
                                                    ↓
                                          [Feature Assembly] ──→ [Clustering Engine]
                                                                        ↓
                                                              [Phenotype Assignment]
                                                                        ↓
                                                              [Validation + Audit]
                                                                        ↓
                                                              [Intervention Matching]
```

**Stage 1: NLP Extraction.** Process clinical notes through an SDOH-specific NLP pipeline. Extract mentions, classify assertions, resolve temporality. Output: per-patient, per-encounter SDOH mention records with domain, polarity, and timestamp.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Add 2-3 sentences on error handling: failed extractions should go to a dead-letter queue, feature assembly should distinguish "no extractions found" from "extraction never attempted," and a monitoring alarm should fire when DLQ depth exceeds a threshold. Silent NLP failures create ambiguous gaps indistinguishable from legitimate absence of SDOH mentions. -->

**Stage 2: Feature Assembly.** Combine NLP extractions, structured screening responses, and geocoded community indicators into a unified patient feature vector. Handle missingness explicitly (distinguish "screened negative" from "never screened"). Apply temporal weighting (recent signals matter more than old ones).

**Stage 3: Clustering.** Apply an appropriate clustering algorithm to the assembled feature matrix. Determine optimal cluster count through a combination of statistical criteria (silhouette score, BIC for LCA) and clinical interpretability. Assign each patient a phenotype label and a membership probability.

**Stage 4: Validation and Audit.** Assess clinical face validity with domain experts. Test predictive validity against outcomes. Run equity analysis. Document cluster characteristics and intended use.

**Stage 5: Intervention Matching.** Map phenotypes to recommended intervention strategies. The "housing instability + food insecurity" phenotype gets connected to housing navigators and food assistance programs. The "transportation barrier" phenotype gets connected to ride services and telehealth options. This is where the clustering becomes actionable.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.09-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you when you build this:

The biggest cluster is always "we don't know." In every health system I've seen attempt SDOH phenotyping, the largest group (often 40-60% of patients) has insufficient data to assign a meaningful phenotype. They weren't screened, their notes don't mention social factors, and community-level indicators are too coarse to differentiate. Your first instinct will be to treat this as a failure. It's not. It's an honest signal that your organization needs to improve SDOH documentation and screening rates before the clustering can be maximally useful.

NLP extraction quality varies wildly by note type. Social work assessments are gold mines. Physician progress notes occasionally mention social factors in passing. Nursing intake forms sometimes capture transportation and housing. Specialist notes almost never mention SDOH. If you're only processing one note type, you're missing signal.

The equity audit is not optional. I've seen SDOH phenotyping projects produce clusters that are effectively racial categories with extra steps. If your "multi-domain social complexity" cluster is 85% patients of color, you need to ask hard questions about whether you're measuring social determinants or measuring structural racism. Both are real, but the interventions are different, and the risk of misuse is high.

Staleness is a real operational problem. Social circumstances change. A phenotype assigned 18 months ago based on a note from a crisis period may not reflect a patient's current situation. Build re-evaluation triggers: new screening data, new social work notes, address changes, or simple time-based expiration.

The intervention matching is where the value lives, and it's where most projects stall. Phenotyping without a clear "so what" is an academic exercise. Before you build the clustering, make sure you have community resources to connect patients to. A phenotype of "food insecurity" is only useful if you have a food assistance referral pathway ready.

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Add a recommendation for re-clustering cadence. Common pattern: weekly incremental assignment (new patients to existing centroids) with monthly full re-clustering and equity audit. Note that cadence should be driven by rate of new SDOH data accumulation, not calendar alone. -->

---

## Related Recipes

- **Recipe 6.1 (Geographic Patient Clustering):** Provides the geographic foundation; community indicators from 6.1 feed into SDOH feature assembly
- **Recipe 6.4 (Disease Severity Stratification):** Combines with SDOH phenotypes for a complete patient complexity picture (clinical + social)
- **Recipe 6.6 (Patient Similarity for Care Planning):** Uses SDOH phenotype as a feature in broader patient similarity calculations
- **Recipe 8.3 (Social Determinant Extraction from Clinical Notes):** The NLP extraction component used in Step 1 of this recipe; see 8.3 for detailed NLP architecture
- **Recipe 7.2 (Hospital Readmission Risk):** SDOH phenotype as a predictive feature for readmission models

---

## Tags

`cohort-analysis` · `clustering` · `sdoh` · `social-determinants` · `nlp` · `phenotyping` · `comprehend-medical` · `sagemaker` · `glue` · `complex` · `equity` · `population-health` · `hipaa`

---

*← [Recipe 6.8: Disease Subtype Discovery](chapter06.08-disease-subtype-discovery) · [Chapter 6 Index](chapter06-preface) · [Next: Recipe 6.10: Multi-Morbidity Pattern Discovery →](chapter06.10-multi-morbidity-pattern-discovery)*
