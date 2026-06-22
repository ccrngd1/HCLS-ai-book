# Recipe 6.2: Utilization Pattern Segmentation ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.15 per 10,000 patients segmented

---

## The Problem

Every health plan and health system has a population health team. And every population health team has the same problem: they're running one-size-fits-all outreach campaigns against a population that contains wildly different types of people.

There's the 28-year-old who shows up once a year for a physical and fills one prescription. There's the 55-year-old with three chronic conditions who sees her PCP quarterly, two specialists monthly, and hits the ED twice a year when her COPD flares. There's the 40-year-old who hasn't engaged with the healthcare system in four years despite having diabetes on their problem list. And there's the 70-year-old "frequent flyer" with 47 ED visits in the last 12 months and no primary care relationship whatsoever.

These four patients require completely different interventions. Sending the disengaged diabetic a reminder about their annual wellness visit is pointless if they haven't opened a piece of mail from your organization in three years. Enrolling the well-managed chronic patient in an intensive care management program wastes expensive care manager time on someone who's already doing fine. And targeting the ED frequent flyer with a "did you know you have a PCP?" letter misses the point entirely (they know; they just can't get there, or they don't trust the system, or they have untreated behavioral health needs that drive crisis utilization).

The core problem is: how do you take a population of 100,000 (or 500,000, or 5 million) members and sort them into behaviorally distinct segments based on *how they actually use healthcare*, so you can target the right intervention to the right group?

This is utilization pattern segmentation. It's one of the most immediately actionable clustering problems in healthcare because the segments directly map to outreach strategies, care management programs, and resource allocation decisions. It doesn't require clinical expertise to interpret the results (unlike disease severity stratification in Recipe 6.4). It uses data you already have (claims and encounter data). And it produces segments that operational leaders can act on immediately.

The reason it's not already done well at most organizations: because they've been using static, rule-based tiers (high/medium/low utilizers based on cost thresholds) instead of letting the data reveal the actual behavioral patterns. A patient with $80,000 in annual spend from a single surgical episode looks nothing like a patient with $80,000 from 200 separate ED and urgent care visits. Same cost tier. Completely different patient. Completely different intervention.

Let's build the thing that actually finds these patterns.

---

## The Technology: Behavioral Clustering from Utilization Data

### What Is Utilization Pattern Segmentation?

Utilization pattern segmentation groups patients by *how they interact with the healthcare system over time*. Not by diagnosis. Not by cost. Not by demographics. By behavior: what services they use, how often, in what combination, and with what trajectory.

The output is a set of segments (typically 4-12, depending on population size and granularity needs) where each segment represents a distinct utilization archetype. The classic archetypes that tend to emerge in most populations:

- **Healthy/Preventive-Only:** Low total utilization. Annual wellness visits. Maybe one acute episode per year. Fills preventive medications. The "low-touch" group.
- **Episodic/Acute:** Moderate utilization driven by discrete events (surgery, injury, pregnancy). High spend in short bursts, then back to baseline. Not chronically ill; just had something happen.
- **Chronic/Managed:** Consistent, moderate-to-high utilization driven by ongoing chronic disease management. Regular PCP and specialist visits. Stable medication regimen. Engaged with the system.
- **Chronic/Unmanaged:** Similar conditions to the managed group but with gaps in care, medication non-adherence signals (gaps in fill patterns), and spikes of acute utilization (ED visits, hospitalizations) that suggest disease isn't well-controlled.
- **High-Utilizer/Complex:** Very high utilization across multiple care settings. Multiple chronic conditions, frequent ED visits, multiple hospitalizations. Often has behavioral health comorbidities and social determinant challenges.
- **Disengaged:** Has known conditions on the problem list but minimal recent utilization. May have fallen out of care entirely. High risk for future acute events because conditions are progressing unmonitored.

These aren't predefined categories you impose on the data. They're the patterns that *emerge* from clustering. The algorithm doesn't know what "disengaged" means. It just finds a group of patients who share the pattern of historical diagnoses combined with recent utilization near zero. You name the cluster after you see what's in it.

### Feature Engineering: Turning Claims Into Cluster-Ready Numbers

This is where the real work lives. Clustering algorithms need numeric features. Claims and encounter data is a mess of codes, dates, and dollar amounts. The translation from raw utilization data to cluster-ready features is the make-or-break step.

Here's what you typically extract from 12-24 months of claims/encounter history:

**Volume features (counts):**
- Total encounters/claims
- ED visits
- Inpatient admissions
- Outpatient visits (split by PCP vs. specialist)
- Urgent care visits
- Behavioral health encounters
- Telehealth visits
- Pharmacy fills (total, unique medications)
- Lab orders
- Imaging orders

**Intensity features (rates and ratios):**
- ED visits per 1,000 member-months
- Specialist-to-PCP visit ratio (high ratios with no PCP visits suggest fragmented care)
- Inpatient days per admission (proxy for severity)
- Readmission rate (30-day)
- Generic vs. brand medication ratio
- Medication possession ratio (MPR) across active prescriptions

**Temporal features (patterns over time):**
- Months since last encounter of any type
- Months since last PCP visit
- Trend direction (increasing, stable, decreasing utilization)
- Seasonality flags (utilization spikes in specific months)
- Gap duration (longest period without any encounter)

**Cost features (use carefully):**
- Total allowed amount
- Per-member-per-month (PMPM) cost
- Proportion of cost from ED vs. inpatient vs. outpatient vs. pharmacy
- Cost trend (increasing/decreasing over lookback period)

**Complexity proxies:**
- Unique diagnosis codes (breadth of conditions)
- Number of distinct providers seen
- Number of distinct facilities used
- HCC (Hierarchical Condition Category) score or similar risk score

A critical design decision: whether to include cost features at all. Cost correlates with utilization (obviously), but it can dominate the clustering and produce segments that are really just "expensive" vs. "cheap" rather than behaviorally distinct. In most implementations, clustering on utilization *patterns* (types of services, frequency, temporal distribution) and then analyzing cost *within* the resulting segments produces more actionable results than clustering on cost directly.

### Normalization: Why It Matters More Than You Think

Imagine two features: "total ED visits in 12 months" (range: 0-50) and "total pharmacy fills" (range: 0-300). Without normalization, the pharmacy fills feature will dominate the distance calculations simply because its numbers are bigger. The algorithm will effectively ignore ED visits because the numerical range is so much smaller.

Standard approaches:
- **Z-score normalization** (subtract mean, divide by standard deviation): good when features are roughly normally distributed. Most utilization features are not; they're heavily right-skewed.
- **Min-max scaling** (scale to 0-1 range): sensitive to outliers. A single patient with 200 ED visits will compress everyone else into a tiny range.
- **Robust scaling** (use median and IQR instead of mean and standard deviation): handles skewed distributions and outliers much better. This is usually the right choice for healthcare utilization data.
- **Log transformation before scaling**: For highly skewed count features (most utilization counts follow a power-law-like distribution), log-transform first, then scale. This prevents extreme outliers from dominating while preserving the relative ordering.

The standard recipe for healthcare utilization features: log1p transform (log(1 + x) to handle zeros), then robust scaling. It's not always perfect, but it's a strong default.

### Choosing the Algorithm

For utilization pattern segmentation specifically, here's the practical decision tree:

**K-Means** works well when:
- You have a hypothesis about how many segments you want (4-8 is common for population health use cases)
- You want segments that are easy to explain to non-technical stakeholders ("these are the five groups")
- You need to assign every patient to exactly one segment (no outliers, no "uncertain" patients)
- Your features are reasonably well-behaved after normalization

**Gaussian Mixture Models (GMM)** work better when:
- You want soft assignments ("this patient is 60% episodic, 40% chronic-managed")
- Your segments have different shapes and sizes (which they usually do in healthcare)
- You want a probability score that indicates how "typical" a patient is within their assigned segment
- You're comfortable with slightly more complex output

**HDBSCAN** works better when:
- You don't want to pre-specify the number of segments
- You want the algorithm to identify outliers (patients who don't fit any pattern) explicitly
- Your population has widely varying density (a large healthy group and small complex groups)
- You're in an exploratory phase and want to discover what's there

For a first implementation focused on population health operations, K-Means with k=5-8 and the elbow method or silhouette analysis to pick k is the pragmatic choice. It produces segments that are easy to name, easy to explain, and easy to operationalize. You can always graduate to GMMs or HDBSCAN once you've validated the basic approach.

### Dimensionality Reduction: When You Have Too Many Features

If you've engineered 30+ features (which is common once you start including all the temporal and ratio features), clustering directly in that high-dimensional space often produces poor results. The "curse of dimensionality" means that distance metrics become less meaningful as dimensions increase. Two patients who differ on 2 out of 30 features are "close" in 30-dimensional space, even if those 2 features are clinically crucial.

The standard approach: reduce to 5-15 dimensions using PCA (Principal Component Analysis) before clustering. PCA finds the directions of maximum variance in your data and projects everything onto those directions. You lose some information but gain much better cluster separation.

A useful diagnostic: run PCA, look at the explained variance per component. If the first 5 components explain 80%+ of the variance, you're in good shape. If you need 20 components to explain 80%, your features may be too noisy or too redundant (consider dropping some).

For visualization and stakeholder communication, UMAP or t-SNE can project your high-dimensional clusters down to 2D for plotting. These are visualization tools, not preprocessing steps for clustering. Don't cluster in UMAP space; cluster in PCA space and visualize in UMAP space.

### Validation: How Do You Know the Segments Are Good?

This is the unsupervised learning paradox: there's no ground truth. You can't compute accuracy because there's no "correct" answer. But you need to convince stakeholders (and yourself) that the segments are meaningful.

**Internal metrics** (mathematical quality):
- **Silhouette score** (-1 to 1): How similar is each patient to their own cluster vs. the nearest other cluster? Scores above 0.3 suggest reasonable structure; above 0.5 is strong.
- **Davies-Bouldin index** (lower is better): Ratio of within-cluster scatter to between-cluster separation.
- **Calinski-Harabasz index** (higher is better): Ratio of between-cluster variance to within-cluster variance.
- **Elbow method**: Plot within-cluster sum of squares vs. k. Look for the "elbow" where adding more clusters stops meaningfully reducing variance.

**External validation** (clinical meaningfulness):
- Do the segments have different outcomes? (Hospitalization rates, costs, mortality, quality measures)
- Can clinical and operational stakeholders name the segments after reviewing their characteristics?
- Do the segments map to different intervention strategies?
- Are the segments stable over time? (Re-run quarterly; do roughly the same segments appear?)
- Are the segments appropriately sized for action? (A segment of 12 patients isn't actionable at a population level)

The gold standard: present the segment profiles (without labels) to a population health medical director and ask "do these groups make clinical sense, and would you intervene differently for each one?" If the answer is yes, your segmentation is working.

## The General Architecture Pattern

```text
[Claims/Encounter Data] → [Feature Engineering] → [Normalize] → [Reduce Dimensions] → [Cluster] → [Profile & Validate] → [Assign & Monitor]
```

**Claims/Encounter Data:** Pull 12-24 months of utilization history from your claims data warehouse or EHR encounter records. Standardize to a per-member feature vector.

**Feature Engineering:** Compute volume, intensity, temporal, and complexity features for each member. This is the largest code surface and the most domain-specific step.

**Normalize:** Apply log transforms and robust scaling to handle skewed distributions and outliers. Healthcare utilization data is almost never normally distributed.

**Reduce Dimensions:** PCA to 5-15 components. Retains the signal, removes the noise, makes clustering more effective.

**Cluster:** Apply your chosen algorithm (K-Means for simplicity, GMM for probabilistic assignments, HDBSCAN for discovery). Evaluate multiple values of k and select based on a combination of internal metrics and domain judgment.

**Profile and Validate:** For each cluster, compute summary statistics (mean/median of key features, top diagnoses, demographic breakdown). Name the clusters. Validate with clinical stakeholders. Check for equity issues (does any segment disproportionately contain a demographic group in a way that suggests bias rather than genuine behavioral difference?).

**Assign and Monitor:** Score new/existing members into segments on a regular cadence (monthly or quarterly). Track segment migration (patients moving between segments over time). Feed segment assignments to downstream systems (care management platforms, outreach engines, reporting dashboards).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.02-architecture). The Python example is linked from there.

## The Honest Take

Utilization pattern segmentation is one of the most immediately useful things you can build in population health analytics. The segments are intuitive, the data is available, and the operational applications are obvious. A care management director who sees "11% of your members are disengaged diabetics" knows exactly what to do with that information.

That said, here's what will humble you:

**The "so what?" problem.** Producing segments is easy. Getting the organization to actually change its behavior based on them is hard. If the outreach team is going to send the same letter to every segment, you wasted your time. The segmentation only matters if it drives differentiated action. Start with the operational question ("what would we do differently for each group?") and work backward to the segmentation design.

**Segment instability around the edges.** Members near the boundaries between segments will flip back and forth between runs. A member at the border of "chronic managed" and "moderate episodic" might be in one segment in January and the other in April. This is mathematically expected but operationally annoying. Care managers hate it when their panel changes every month. Solutions: add hysteresis (require a member to meet the new segment criteria for two consecutive runs before migrating) or use GMMs and report the probability rather than a hard assignment.

**The denominator problem.** What counts as "your population"? Active members only? Include members who were active for part of the lookback but termed? Include members who enrolled mid-period (and therefore have less utilization simply because they had less time)? The denominator choice changes your segments. A member with 2 ED visits in 3 months of enrollment looks like a frequent flyer; that same member with 2 ED visits in 24 months of enrollment looks normal.

**Cost features are a trap.** If you include total cost as a clustering feature, it will dominate everything. Cost is correlated with almost every other utilization feature, and its magnitude dwarfs everything else even after normalization. You'll end up with cost quartiles, not behavioral segments. The disciplined approach: cluster on *utilization patterns* (types of services, frequencies, temporal distribution), then analyze cost *within* the resulting segments as a descriptive characteristic.

**The equity audit you can't skip.** Before you operationalize any segmentation, run demographics by segment. If your "disengaged" segment is 60% Black patients while your overall population is 25% Black, that's not a behavioral finding. That's a system access finding. "Disengaged" might really mean "historically excluded from accessible care." The intervention for that group isn't a reminder postcard; it's addressing the structural barriers. Every segmentation needs this check before deployment.

---

## Related Recipes

- **Recipe 6.1 (Geographic Patient Clustering):** Adds a geographic dimension. Combine geographic clusters with utilization segments to find "disengaged members in underserved areas" for targeted mobile health outreach.
- **Recipe 6.4 (Disease Severity Stratification):** Builds clinical severity tiers within chronic disease cohorts. Layer severity on top of utilization segments for more nuanced care management targeting.
- **Recipe 7.4 (ED Visit Prediction):** Uses the "ED-Dependent" segment as a cohort for predictive modeling. Members in this segment are candidates for ED diversion programs.
- **Recipe 7.6 (Rising Risk Identification):** Related: identifies members whose utilization trajectory suggests impending segment migration (healthy to chronic, managed to unmanaged).
- **Recipe 4.7 (Care Management Program Enrollment):** Consumes segment assignments as input features for program enrollment decisions.

---

## Tags

`cohort-analysis` · `clustering` · `k-means` · `utilization` · `population-health` · `segmentation` · `sagemaker` · `simple` · `mvp` · `batch-analytics` · `hipaa`

---

*← [Recipe 6.1: Geographic Patient Clustering](chapter06.01-geographic-patient-clustering) · [Chapter 6 Index](chapter06-preface) · [Next: Recipe 6.3 - Payer Mix Financial Risk Clustering →](chapter06.03-payer-mix-financial-risk-clustering)*
