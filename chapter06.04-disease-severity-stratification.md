# Recipe 6.4: Disease Severity Stratification

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.02 per patient per stratification run

---

## The Problem

You're a care management director at a health system with 40,000 patients carrying a diabetes diagnosis. Your team has 12 care managers. Each one can actively manage maybe 80 patients at a time. That's 960 slots for 40,000 patients. You need to decide who gets those slots.

The naive approach is to sort by HbA1c and take the top 960. But HbA1c alone misses the patient with a 7.2 who also has stage 3 CKD, peripheral neuropathy, and three ER visits in the last quarter. That patient is far more complex than the one with a 9.0 who's otherwise healthy and just needs medication titration. Severity is not a single number. It's a constellation of clinical markers, complications, functional status, and trajectory.

Most health systems today use one of two approaches: a single lab value threshold (too simplistic) or a manually maintained registry where nurses review charts and assign tiers (accurate but doesn't scale). The manual approach works for 500 patients. It collapses at 40,000. And it's inconsistent: nurse A and nurse B will tier the same patient differently depending on what they noticed in the chart.

What you actually want is a system that looks at the full clinical picture for every patient in a chronic disease cohort, identifies meaningful severity clusters, and assigns each patient to a tier that reflects their true complexity. Not a risk score (that's prediction, Chapter 7). Not a single metric. A multi-dimensional severity classification that accounts for disease burden, complications, functional decline, and healthcare utilization patterns.

This is the kind of problem where clustering shines. You're not predicting the future. You're describing the present in a way that's actionable for resource allocation.

---

## The Technology: How Severity Stratification Works

### The Core Idea

Disease severity stratification is a specific application of unsupervised clustering where the goal is to partition a patient population into clinically meaningful tiers based on multiple dimensions of disease burden. Unlike generic clustering (where you're exploring data for patterns), severity stratification has a clear clinical purpose: the tiers should correspond to different levels of care intensity, resource needs, and intervention strategies.

The fundamental insight is that severity is not a single axis. A patient with diabetes might be "severe" because of poor glycemic control, or because of accumulated complications, or because of rapid functional decline, or because of high utilization driven by social factors. These are different kinds of severity that require different interventions. A good stratification system captures this multi-dimensionality.

### Feature Engineering: The Hard Part

Before any algorithm runs, you need to decide what "severity" means for your disease cohort. This is where clinical expertise is non-negotiable. For diabetes, you might consider:

**Disease control markers:** HbA1c, fasting glucose trends, time in range (for CGM patients), blood pressure, lipid panels.

**Complication burden:** Retinopathy stage, nephropathy (eGFR, albuminuria), neuropathy diagnosis, cardiovascular events, foot ulcer history.

**Functional status:** ADL limitations, mobility assessments, cognitive screening scores, depression screening (PHQ-9).

**Utilization signals:** ER visits, hospitalizations, specialist visits, medication changes, missed appointments.

**Trajectory indicators:** Rate of HbA1c change over 12 months, eGFR slope, new complications in the last year.

Each disease has its own feature set. Heart failure uses ejection fraction, BNP levels, NYHA class, diuretic dose, and fluid weight fluctuations. COPD uses FEV1, exacerbation frequency, oxygen requirements, and exercise tolerance. The feature engineering is disease-specific and requires clinical validation.

The tricky part: these features live on different scales, have different distributions, and carry different clinical weight. HbA1c ranges from 5 to 14. ER visits range from 0 to 50. You can't just throw raw values into a distance calculation and expect meaningful clusters.

### Normalization and Weighting

Standard practice is to normalize features to a common scale (z-scores or min-max normalization) before clustering. But in clinical applications, you often want to weight certain features more heavily. A clinician might tell you that a new complication in the last 6 months is more important than a stable complication from 5 years ago. An eGFR below 30 is qualitatively different from an eGFR of 60, not just quantitatively different.

There are two approaches to handling this:

**Expert-weighted features:** Clinicians assign importance weights to each feature before clustering. This injects domain knowledge but introduces subjectivity. Different clinicians will weight differently.

**Data-driven weighting:** Let the algorithm discover which features best separate clinically meaningful groups. This is more objective but requires validation that the discovered structure matches clinical reality.

In practice, most successful implementations use a hybrid: clinicians define the feature set and provide rough importance guidance, the algorithm discovers the cluster structure, and clinicians validate that the resulting tiers make clinical sense.

### Clustering Algorithms for Stratification

Several algorithms work for severity stratification, each with tradeoffs:

**K-Means:** Fast, simple, produces spherical clusters. Works well when severity tiers are roughly evenly sized and features are continuous. The main limitation is that you must specify K (the number of tiers) in advance, and it assumes clusters are roughly the same shape and size.

**Gaussian Mixture Models (GMM):** More flexible than K-Means because clusters can be elliptical (different variances in different dimensions). Better for clinical data where some features have wider spread in certain severity tiers. Also provides soft assignments (probability of belonging to each tier), which is useful for patients near tier boundaries.

**Hierarchical clustering:** Produces a dendrogram showing how patients nest into groups at different granularities. Useful for exploring whether 3, 4, or 5 tiers is the right number. Computationally expensive for large populations (O(n^2) or worse), so often applied to a sample first.

**DBSCAN and density-based methods:** Good at finding irregularly shaped clusters and identifying outliers. Less useful for stratification because you typically want every patient assigned to a tier, and the number of tiers should be small and interpretable.

For most severity stratification use cases, K-Means or GMM with K=3 to 5 is the starting point. Three tiers (mild, moderate, severe) is the minimum for actionability. Five tiers provide more granularity but require more distinct intervention strategies to justify the complexity.

### Choosing K: How Many Tiers?

This is partly a technical question and partly an operational one.

**Technical approaches:** The elbow method (plot within-cluster sum of squares vs. K, look for the "elbow"), silhouette scores (measure how well-separated clusters are), and the gap statistic all provide quantitative guidance on the "natural" number of clusters in the data.

**Operational reality:** Your care management team can only operationalize so many tiers. If you have three intervention programs (intensive, moderate, self-management), then three tiers is the right answer regardless of what the silhouette score says. The algorithm should serve the workflow, not the other way around.

The best practice is to run the technical analysis to understand the data's natural structure, then map that to the operational tier count your organization can support. If the data naturally separates into 4 groups but you can only support 3 programs, merge the two most similar groups.

### Validation: The Critical Step

Here's where severity stratification diverges from generic clustering. In generic clustering, internal metrics (silhouette score, Davies-Bouldin index) tell you whether clusters are well-separated. In clinical stratification, you need external validation: do the tiers actually correspond to different outcomes?

**Outcome validation:** Patients in the "severe" tier should have higher hospitalization rates, higher costs, faster disease progression, and worse quality-of-life scores than patients in the "mild" tier. If they don't, your stratification isn't capturing real severity.

**Clinical face validity:** Show the tier assignments to clinicians who know the patients. Do they agree? A stratification that puts a well-controlled patient in the severe tier (or vice versa) has a feature engineering problem.

**Stability:** Run the stratification on different time windows. Do patients stay in roughly the same tier, or do assignments fluctuate wildly? Some movement is expected (patients improve or deteriorate), but wholesale reshuffling suggests the model is fitting noise.

**Equity audit:** Check whether tier assignments correlate with race, ethnicity, language, or insurance type after controlling for clinical factors. If Black patients are systematically assigned to lower-severity tiers despite similar clinical profiles, your features may be encoding access disparities rather than true severity.

---

## General Architecture Pattern

The pipeline for disease severity stratification has five logical stages:

```
[Feature Assembly] → [Preprocessing] → [Clustering] → [Validation & Labeling] → [Operationalization]
```

**Feature Assembly:** Pull clinical data from multiple source systems (EHR, claims, labs, pharmacy) and construct the feature vector for each patient in the cohort. This is typically the most time-consuming step because healthcare data is fragmented across systems with different schemas, identifiers, and update frequencies.

**Preprocessing:** Normalize features to common scales. Handle missing values (a patient without a recent HbA1c is not the same as a patient with a normal HbA1c). Apply any clinical weighting. Remove patients who don't meet cohort inclusion criteria (e.g., must have at least 12 months of continuous enrollment).

**Clustering:** Run the selected algorithm to assign patients to severity tiers. This step is computationally straightforward once features are prepared. The algorithm itself is rarely the bottleneck.

**Validation and Labeling:** Validate cluster assignments against outcomes. Label clusters with clinically meaningful names (not "Cluster 0, 1, 2" but "Well-controlled with low complication burden," "Moderate complexity with active complications," "High severity with functional decline"). This step requires clinical review and iteration.

**Operationalization:** Push tier assignments to downstream systems (care management platforms, EHR registries, population health dashboards). Set up refresh cadence (monthly or quarterly re-stratification). Build monitoring for tier migration (patients moving between tiers over time).

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.04-architecture). The Python example is linked from there.

## The Honest Take

The algorithm is the easy part. K-Means on 40,000 patients with 30 features takes seconds. The hard parts are all upstream and downstream.

Upstream: getting clinicians to agree on the feature set. Every specialist thinks their favorite metric is the most important one. Endocrinologists want HbA1c weighted heavily. Nephrologists want eGFR. Cardiologists want cardiovascular event history. You'll spend more time in consensus meetings than you will writing code.

Downstream: getting care managers to actually use the tiers. If the stratification doesn't match their clinical intuition for patients they know well, they'll ignore it. The first time a patient they consider "severe" shows up in Tier 1, you've lost credibility. Invest heavily in the validation step. Show them the profiles. Let them challenge the assignments. Iterate.

The thing that surprised me: the biggest predictor of whether a stratification system gets adopted is not accuracy. It's explainability. Care managers need to understand why a patient is in a given tier. "The algorithm said so" is not acceptable. The key_drivers field in the output is not optional. It's the difference between a system that gets used and one that gets ignored.

One more thing: tier assignments are not destiny. They're a snapshot. A patient in Tier 3 who gets intensive care management and improves should move to Tier 2 on the next run. If your tiers never change, either your interventions aren't working or your refresh cadence is too slow. Track tier migration as a program effectiveness metric.

---

## Related Recipes

- **Recipe 6.2 (Utilization Pattern Segmentation):** Segments by utilization behavior; severity stratification adds clinical dimensions on top of utilization signals
- **Recipe 6.6 (Patient Similarity for Care Planning):** Uses similar feature engineering but for finding individual patient matches rather than population-level tiers
- **Recipe 7.1 (Hospital Readmission Risk):** Predictive model that can use severity tier as an input feature for risk scoring
- **Recipe 6.8 (Disease Subtype Discovery):** Discovers new disease subtypes through unsupervised clustering; severity stratification applies known clinical dimensions

---

## Tags

`clustering` `k-means` `severity-stratification` `chronic-disease` `population-health` `care-management` `sagemaker` `glue` `cohort-analysis` `unsupervised-learning`

---

| [← 6.3: Payer Mix Financial Risk Clustering](chapter06.03-payer-mix-financial-risk-clustering) | [Chapter 6 Index](chapter06-preface) | [6.5: Provider Practice Pattern Analysis →](chapter06.05-provider-practice-pattern-analysis) |
|:---|:---:|---:|
