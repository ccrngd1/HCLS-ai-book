# Recipe 6.8: Disease Subtype Discovery

**Complexity:** Complex · **Phase:** Research/Innovation · **Estimated Cost:** ~$2.00-$8.00 per patient in the analysis cohort (depending on feature dimensionality and compute requirements)

---

## The Problem

A health system has 14,000 patients with a diagnosis of heart failure. They're all coded HFrEF or HFpEF. They all get guideline-directed medical therapy. And yet: some respond beautifully to beta-blockers while others don't. Some progress to transplant evaluation within two years while others remain stable for a decade. Some have readmission rates of 40% while others never come back.

The clinical intuition is obvious: "heart failure" is not one disease. It's a collection of diseases that happen to share a final common pathway (the heart can't pump effectively). Cardiologists know this. They talk about ischemic vs. non-ischemic, about infiltrative cardiomyopathies, about hypertensive heart disease. But the current taxonomy is based on mechanism of injury and ejection fraction. It doesn't capture the full heterogeneity of how these patients actually behave.

This isn't unique to heart failure. Type 2 diabetes, COPD, depression, sepsis, asthma, Parkinson's disease: all of these are "umbrella diagnoses" that likely contain distinct biological subtypes with different trajectories and different optimal treatments. A landmark 2018 study (Ahlqvist et al., The Lancet Diabetes & Endocrinology) identified five distinct clusters within Type 2 diabetes, each with different progression patterns and complication risks. That study used unsupervised clustering on six clinical variables across 8,980 patients. The subtypes they found predicted outcomes better than the traditional classification.

The promise of disease subtype discovery is precision medicine at the population level. If you can identify that your 14,000 heart failure patients actually fall into six distinct phenotypic clusters, and that Cluster 3 responds poorly to standard beta-blocker therapy but responds well to SGLT2 inhibitors, you've just generated a hypothesis that could change treatment protocols. If Cluster 5 has a 60% readmission rate while the others average 15%, you've identified a group that needs intensive care management.

The challenge: there are no labels. Nobody has pre-defined what the subtypes are. That's the whole point. You're using unsupervised learning to discover structure that the existing taxonomy doesn't capture. And that means you have no ground truth to validate against, no accuracy metric to optimize, and no way to know if the clusters you found are clinically meaningful until a physician looks at them and says "yes, these are real."

This is research-grade work. It requires clinical collaboration from day one, rigorous statistical validation, and the intellectual honesty to admit when your clusters are artifacts of data quality rather than biology.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Add paragraph on IRB/ethics review requirements: research vs. QI classification, IRB timeline (4-12 weeks), and implication for the "Basic" implementation estimate. Disease subtype discovery using patient data typically requires IRB review before accessing real patient data. -->

---

## The Technology: How Unsupervised Clustering Discovers Disease Subtypes

### What Unsupervised Clustering Actually Does

Let's start from first principles. Supervised learning has labels: you know the answer and you're training a model to predict it. Unsupervised clustering has no labels. You're handing the algorithm a pile of patient data and asking: "Are there natural groupings here that I haven't noticed?"

The algorithm looks at each patient as a point in high-dimensional space. If you have 50 clinical features per patient (labs, vitals, medications, comorbidities, demographics), each patient is a point in 50-dimensional space. Clustering algorithms find regions of that space where patients are densely packed together and separated from other dense regions by relative emptiness.

The intuition: if patients in one region of the space share similar lab patterns, similar medication responses, and similar outcomes, they might represent a coherent biological subtype. The "might" is doing a lot of work in that sentence, and we'll come back to it.

### The Feature Engineering Problem

This is where disease subtype discovery diverges from standard clustering applications. In geographic clustering, your features are obvious (latitude, longitude). In disease subtype discovery, feature selection is the entire ballgame.

Consider heart failure. What features might distinguish subtypes?

**Clinical measurements:** Ejection fraction, BNP/NT-proBNP levels, troponin, creatinine, hemoglobin, sodium, potassium, liver function tests, thyroid function. Each measured at what time point? Baseline? Trajectory over time? Peak value? Rate of change?

**Comorbidity profiles:** Diabetes, hypertension, atrial fibrillation, chronic kidney disease, COPD, obesity, sleep apnea, anemia. Binary presence/absence? Or severity-weighted?

**Medication response:** Which drugs were tried? Which were tolerated? Which produced measurable improvement? This is retrospective observational data, not randomized trial data, so confounding is everywhere.

**Functional status:** NYHA class, 6-minute walk distance, quality of life scores. Often sparsely documented.

**Imaging features:** LV dimensions, wall motion abnormalities, valve disease, RV function. Requires structured extraction from echo reports.

**Genomic data:** If available. Usually it's not, outside of research cohorts.

The choices you make here determine what subtypes you can possibly find. If you only include lab values, you'll find lab-based subtypes. If you only include comorbidities, you'll find comorbidity-based subtypes. The subtypes are not "in the data" waiting to be discovered. They're a function of which data you choose to look at and how you represent it.

This is why you absolutely need clinical collaboration from day one. A data scientist working alone will make feature choices that seem reasonable but miss clinically important distinctions. A cardiologist will tell you that the ratio of BNP to creatinine matters more than either value alone, or that the trajectory of ejection fraction over the first 90 days after diagnosis is more informative than the baseline value.

### Choosing a Clustering Algorithm

There's no single "best" algorithm for disease subtype discovery. The choice depends on your assumptions about cluster shape, your tolerance for specifying the number of clusters in advance, and your data characteristics.

**K-means** is the simplest and most widely used. It assumes clusters are roughly spherical (equal variance in all directions) and requires you to specify K (the number of clusters) in advance. It's fast, scales well, and produces interpretable results. Its weakness: real disease subtypes are rarely spherical in feature space. If one subtype is defined by a tight range of BNP values but a wide range of ejection fractions, K-means will struggle.

**Gaussian Mixture Models (GMM)** generalize K-means by allowing elliptical clusters (different variances in different directions). They also provide soft assignments: instead of "this patient belongs to Cluster 3," you get "this patient has 72% probability of Cluster 3 and 28% probability of Cluster 1." That probabilistic assignment is clinically useful because many patients are genuinely on the boundary between subtypes.

**Hierarchical clustering** builds a tree (dendrogram) of nested clusters, from individual patients up to the entire population. You can cut the tree at different levels to get different numbers of clusters. The advantage: you can visualize the full hierarchy and see which subtypes are "close" to each other. The disadvantage: it doesn't scale well beyond a few thousand patients without approximation methods.

**DBSCAN and HDBSCAN** find clusters of arbitrary shape and automatically identify outliers (patients who don't fit any cluster). They don't require you to specify the number of clusters. The disadvantage: they're sensitive to their density parameters, and in high-dimensional clinical data, the concept of "density" becomes unreliable (the curse of dimensionality).

**Spectral clustering** works by building a similarity graph between patients and finding communities in that graph. It handles non-convex cluster shapes well. It's computationally expensive for large populations but produces excellent results when the underlying structure is complex.

**Consensus clustering** (also called ensemble clustering) runs multiple clustering algorithms (or the same algorithm with different parameters) and identifies groupings that are stable across runs. If patients consistently end up in the same cluster regardless of algorithm choice or random initialization, that's evidence the cluster is real rather than an artifact. This is the gold standard for disease subtype discovery in research settings.

For a first pass, I'd recommend: run K-means, GMM, and hierarchical clustering across a range of K values (3 through 10). Use consensus clustering to identify which groupings are stable. Then validate the stable clusters clinically.

### Dimensionality Reduction

If you have 50 or 100 clinical features, clustering directly in that space is problematic. The curse of dimensionality means that distance metrics become less meaningful as dimensions increase. Points that are "close" in 100-dimensional space may not be meaningfully similar.

**PCA (Principal Component Analysis)** projects the data onto the directions of maximum variance. If 90% of the variance in your 50 features can be captured by 8 principal components, you can cluster in 8 dimensions instead of 50. The downside: principal components are linear combinations of original features, which makes them hard to interpret clinically. "PC3 = 0.4 * BNP + 0.3 * creatinine - 0.2 * ejection fraction" is not something a cardiologist can act on.

**UMAP (Uniform Manifold Approximation and Projection)** is a non-linear dimensionality reduction technique that preserves local structure. It's excellent for visualization (projecting patients into 2D for plotting) and can reveal cluster structure that PCA misses. But it's stochastic (different runs produce different layouts) and the distances in UMAP space are not directly interpretable.

**Autoencoders** (neural network-based dimensionality reduction) learn a compressed representation of the patient data. They can capture non-linear relationships that PCA misses. The latent space of an autoencoder can be used as input to clustering. The downside: they're black boxes, and explaining why two patients ended up in the same cluster becomes harder.

For disease subtype discovery, I'd recommend: use PCA for initial exploration and to determine how many dimensions carry meaningful variance. Use UMAP for visualization. Cluster in the PCA-reduced space (or the original space if dimensionality is manageable). Use the UMAP visualization to sanity-check whether the clusters look coherent.

### Validation: The Hard Part

Here's the fundamental challenge of unsupervised disease subtype discovery: how do you know the clusters are real?

**Internal validation metrics** tell you whether your clusters are well-formed, without needing external labels to compare against:
- Silhouette score: How similar is each patient to their own cluster vs. the nearest other cluster? Ranges from -1 to 1; higher is better.
- Calinski-Harabasz index: Ratio of between-cluster variance to within-cluster variance. Higher means more separated clusters.
- Davies-Bouldin index: Average similarity between each cluster and its most similar cluster. Lower is better.

These tell you whether the clusters are well-separated in feature space. They do not tell you whether the clusters are clinically meaningful. A clustering that perfectly separates patients by age and sex will have excellent internal metrics but zero clinical novelty.

**Stability validation** tests whether the clusters are robust:
- Bootstrap resampling: Resample patients with replacement, re-cluster, and measure how often the same patients end up together. Stable clusters survive resampling.
- Feature perturbation: Add noise to features or drop features and re-cluster. Robust clusters survive perturbation.
- Algorithm variation: Do different algorithms find the same groupings? Consensus clustering formalizes this.

**Clinical validation** is the only validation that ultimately matters:
- Do the clusters have different outcomes (mortality, readmission, progression)?
- Do the clusters have different treatment responses?
- Can a clinician look at the cluster profiles and say "yes, I recognize these patients"?
- Do the clusters suggest actionable differences in care?

If your clusters have beautiful silhouette scores but identical outcomes across groups, they're not clinically useful subtypes. If they have mediocre silhouette scores but dramatically different 5-year mortality rates, they might be the most important finding in your dataset.

## General Architecture Pattern

```text
[Cohort Definition] → [Feature Extraction] → [Preprocessing] → [Dimensionality Reduction]
    → [Multi-Algorithm Clustering] → [Consensus/Stability Analysis]
    → [Clinical Validation] → [Subtype Characterization] → [Deployment/Monitoring]
```

**Cohort definition:** Select the patient population. All patients with a specific diagnosis code? Only those with sufficient data completeness? Only those with a minimum follow-up period? These choices affect what subtypes you can find.

**Feature extraction:** Pull clinical features from EHR data. This requires joining across multiple data domains (labs, medications, diagnoses, procedures, notes). Handle missingness explicitly: impute, exclude, or use algorithms that handle missing data natively.

**Preprocessing:** Normalize features to comparable scales. Handle outliers. Encode categorical variables. This step has outsized impact on results because clustering algorithms are sensitive to feature scaling.

**Dimensionality reduction:** Reduce feature space to a manageable number of dimensions while preserving meaningful variance.

**Multi-algorithm clustering:** Run multiple algorithms across multiple K values. Don't commit to a single algorithm or a single K.

**Consensus/stability analysis:** Identify which groupings are robust across algorithms, initializations, and resampling.

**Clinical validation:** Evaluate discovered clusters against outcomes, treatment responses, and clinical interpretability. This is a human-in-the-loop step that cannot be automated.

**Subtype characterization:** For validated clusters, describe the defining features in clinically actionable terms. "Cluster 3 is characterized by preserved ejection fraction, elevated BNP, high comorbidity burden (diabetes + CKD), and poor response to beta-blockers" is actionable. "Cluster 3 has high values on PC2" is not.

**Deployment/monitoring:** If subtypes are validated and actionable, build a classifier that assigns new patients to discovered subtypes. Monitor for drift as the patient population changes over time.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.08-architecture). The Python example is linked from there.

## The Honest Take

Disease subtype discovery is one of those problems that feels like it should be straightforward. You have patients, you have features, you run clustering, you get subtypes. In practice, it's one of the most intellectually demanding ML applications in healthcare because the hardest question isn't "how do I cluster?" but "are these clusters real?"

The thing that surprised me most: the number of clusters matters less than you'd think. Whether you find 3 subtypes or 6 subtypes, the clinical utility depends entirely on whether the subtypes have different outcomes and different optimal treatments. Four well-characterized subtypes with clear treatment implications are infinitely more valuable than eight subtypes that a clinician can't distinguish at the bedside.

Feature selection is where projects succeed or fail. I've seen teams spend months on sophisticated clustering algorithms only to realize their features were dominated by age and sex. Of course you'll find clusters if you include demographics. The question is whether you find clusters that persist after adjusting for demographics. Start by clustering without age and sex, then check whether the clusters you find correlate with demographics. That ordering matters.

The validation gap is real. You can have beautiful, stable, well-separated clusters with excellent internal metrics, and they can still be clinically meaningless. The only validation that matters is: does a clinician look at these clusters and say "yes, I treat these patients differently"? If the answer is no, your clusters are a statistical curiosity, not a clinical tool.

One more thing: publication bias in this space is severe. The papers that get published are the ones that found clean, interpretable subtypes. The teams that ran the same analysis and found mush don't publish. If your first attempt produces ambiguous results, that's normal. It doesn't mean the approach is wrong. It might mean your feature set needs refinement, your cohort needs better definition, or the disease genuinely doesn't have discrete subtypes (it's a continuum, and forcing it into clusters is the wrong framing).

---

## Related Recipes

- **Recipe 6.4 (Disease Severity Stratification):** Stratifies within a known disease by severity; subtype discovery finds qualitatively different groups rather than a severity gradient
- **Recipe 6.6 (Patient Similarity for Care Planning):** Uses similarity metrics that subtype discovery also relies on; subtypes provide a higher-level grouping that similarity search operates within
- **Recipe 6.10 (Multi-Morbidity Pattern Discovery):** Discovers co-occurrence patterns across conditions; subtype discovery operates within a single condition
- **Recipe 7.3 (Disease Progression Modeling):** Subtypes often have different progression trajectories; progression models can be built per-subtype for better accuracy
- **Recipe 12.8 (Disease Progression Trajectory Modeling):** Temporal trajectory analysis that complements static subtype discovery

---

## Tags

`cohort-analysis` · `clustering` · `unsupervised-learning` · `disease-subtype` · `precision-medicine` · `sagemaker` · `pca` · `consensus-clustering` · `clinical-validation` · `research` · `complex` · `hipaa`

---

*← [Recipe 6.7: Clinical Trial Patient Matching](chapter06.07-clinical-trial-patient-matching) · [Chapter 6 Index](chapter06-preface) · [Next: Recipe 6.9: Social Determinant Phenotyping →](chapter06.09-social-determinant-phenotyping)*
