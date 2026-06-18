<!-- EDITED: TechEditor post-split polish 2026-06-17. Verified transition seams after
     mechanical split: General Architecture and The Honest Take contain zero AWS references,
     architecture callout correctly placed between General Architecture and The Honest Take,
     architecture companion opens with clean backlink. Added missing Tags section and
     navigation footer per RECIPE-GUIDE. Zero em/en dashes confirmed. All code blocks tagged.
     Deferred TODOs (A1, S1) remain in architecture companion for TechWriter. -->

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

```text
[Feature Store] → [Similarity Engine] → [Outcome Aggregation] → [Care Plan Recommendations]
```
**Feature Store.** A curated, versioned repository of patient features. Not raw EHR data. Engineered features: computed comorbidity scores, normalized lab values, medication categories, utilization summaries. Updated on a schedule (daily or weekly) as new clinical data arrives. The feature store is the foundation; garbage features produce garbage similarity.

**Similarity Engine.** Takes a query patient's feature vector, computes distance to the historical cohort, and returns the k most similar patients. For scale, this uses an approximate nearest neighbor index rather than brute-force search. The index is rebuilt periodically as the feature store updates.

**Outcome Aggregation.** For the k similar patients, aggregate their outcomes: What interventions did they receive? What were their trajectories at 3, 6, 12 months? What percentage achieved target goals? What adverse events occurred? This is where raw similarity becomes actionable intelligence.

**Care Plan Recommendations.** Present the aggregated outcomes to the care manager in a format that supports decision-making. Not "do this." Rather: "Among 15 patients similar to yours, 11 achieved A1C < 7 within 6 months. 9 of those were on metformin plus a GLP-1 agonist. 3 had hypoglycemic events in the first month." The care manager decides. The system informs.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.06-architecture). The Python example is linked from there.

## The Honest Take

Patient similarity is one of those ideas that sounds obviously useful and is genuinely hard to get right. The first time I built one of these, I spent two weeks tuning the distance metric before realizing my feature set was the actual problem. I was optimizing the wrong thing entirely. The concept is intuitive: find patients like this one, see what worked. The execution is full of subtle traps.

The biggest trap is the assumption that "similar features" implies "similar outcomes." It often does. But sometimes two patients look identical on paper and have wildly different trajectories because of factors you didn't capture: social support, health literacy, genetic variation, provider quality. Your similarity metric is only as good as your features, and your features are only as good as your data capture.

The second trap is sample size. For common conditions in large health systems, you'll find plenty of similar patients. For rare conditions, complex multi-morbidity patterns, or small health systems, the cohort might be 3 patients. Presenting aggregated outcomes from 3 patients as if they're statistically meaningful is dangerous. The system must communicate uncertainty honestly.

The thing that surprised me most: clinicians don't want a black box that says "do this." They want a tool that says "here's what happened to patients like yours, here's what was tried, here's what worked and what didn't." The decision remains theirs. The system provides evidence. That framing (decision support, not decision making) is both ethically correct and practically necessary for adoption.

Start with a single condition (diabetes is the classic choice: large population, well-defined outcomes, measurable goals). Validate that your similarity metric actually predicts outcome similarity before expanding. And involve clinicians in feature selection from day one. The features that matter are not always the features that are easy to compute.

---

## Related Recipes

- **Recipe 6.4 (Disease Severity Stratification):** Provides the severity tiers that can serve as a pre-filter before similarity search (only compare within the same severity tier)
- **Recipe 6.7 (Clinical Trial Patient Matching):** Uses similar feature-matching techniques but optimizes for eligibility criteria rather than outcome similarity
- **Recipe 7.1 (Readmission Risk Scoring):** Predictive models that can be informed by outcomes of similar patients
- **Recipe 4.9 (Personalized Care Plan Generation):** Consumes similarity-based evidence to generate tailored care plans
- **Recipe 13.1 (Medical Ontology Mapping):** Knowledge graphs can enrich feature engineering by providing semantic relationships between diagnoses and medications

---

## Tags

`cohort-analysis` · `patient-similarity` · `knn` · `nearest-neighbor` · `care-planning` · `feature-engineering` · `clinical-decision-support` · `embeddings`

---

*← [Recipe 6.5: Provider Practice Pattern Analysis](chapter06.05-provider-practice-pattern-analysis) · [Chapter 6 Index](chapter06-preface) · [Recipe 6.7: Clinical Trial Patient Matching →](chapter06.07-clinical-trial-patient-matching)*
