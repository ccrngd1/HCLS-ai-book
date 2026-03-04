# Category 6: Cohort Analysis / Clustering / Similarity

**Healthcare Use Cases — Simple → Complex**

---

## 6.1 Geographic Patient Clustering (Simple)

**What:** Group patients by geographic region for service area analysis, facility planning, and community health assessment.

**Why simple:** Clear clustering dimension (geography). Well-understood techniques. Results easily interpretable. Supports strategic decisions, not clinical ones.

---

## 6.2 Utilization Pattern Segmentation (Simple)

**What:** Segment patients by healthcare utilization patterns (high utilizers, episodic users, preventive-only, disengaged) for population health management.

**Why simple:** Behavioral data is objective. Segments are actionable for outreach strategies. Doesn't require clinical nuance. Standard clustering techniques work well.

---

## 6.3 Payer Mix / Financial Risk Clustering (Simple-Medium)

**What:** Group patient populations by financial risk profiles for revenue cycle management and charity care planning.

**Why this complexity:** Must integrate multiple financial signals. Sensitive topic requiring careful use. Results inform resource allocation. May surface equity concerns.

---

## 6.4 Disease Severity Stratification (Medium)

**What:** Cluster patients with chronic diseases into severity tiers based on clinical markers, complications, and functional status.

**Why medium:** Clinical interpretation required. Must validate against outcomes. Different diseases have different markers. Supports care management prioritization.

---

## 6.5 Provider Practice Pattern Analysis (Medium)

**What:** Cluster providers by practice patterns (ordering behavior, referral patterns, treatment choices) for peer comparison and variation reduction.

**Why medium:** Must account for case mix differences. Sensitive data — provider pushback likely. Requires clinical credibility. Variation isn't always bad.

---

## 6.6 Patient Similarity for Care Planning (Medium-Complex)

**What:** Find "patients like this one" who had good outcomes to inform care planning and set expectations for similar patients.

**Why this complexity:** Feature selection is critical and requires clinical input. Similarity measure choice affects results. Must validate that similar patients have similar trajectories. Risk of bias if training data reflects disparities.

---

## 6.7 Clinical Trial Patient Matching (Medium-Complex)

**What:** Identify patients who are similar to trial inclusion criteria and likely to be eligible for open clinical trials.

**Why this complexity:** Eligibility criteria are complex and often buried in notes. Must balance precision (don't waste investigator time) with recall (don't miss eligible patients). Regulatory and consent considerations.

---

## 6.8 Disease Subtype Discovery (Complex)

**What:** Use unsupervised clustering to discover clinically meaningful disease subtypes that may have different prognoses or treatment responses.

**Why complex:** No ground truth labels. Must validate discovered clusters clinically. Publication/research-grade rigor required. May challenge existing disease taxonomy.

---

## 6.9 Social Determinant Phenotyping (Complex)

**What:** Cluster patients by social determinant profiles (housing instability, food insecurity, social isolation patterns) from clinical notes and structured data.

**Why complex:** SDOH data is sparse and inconsistent. NLP extraction required. Sensitive categorizations. Must be actionable — connect to resources. Equity implications.

---

## 6.10 Multi-Morbidity Pattern Discovery (Complex)

**What:** Identify clusters of conditions that co-occur in clinically meaningful patterns that aren't captured by existing comorbidity indices.

**Why complex:** High-dimensional condition space. Temporal patterns matter (what develops first?). Must distinguish causal from coincidental. Results should inform care models. Requires large populations.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Clinical interpretation need | Non-clinical clusters are easier |
| Ground truth availability | Supervised > unsupervised |
| Feature selection | Domain expertise required |
| Actionability | Clusters must drive decisions |
| Sensitivity | Provider/patient data requires care |
| Validation requirements | Clinical validation is expensive |

---

*Category 6 complete. Next: Category 7 (Predictive Analytics / Risk Scoring)*
