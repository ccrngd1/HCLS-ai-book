# Recipe 7.12: Cohort Matching and Case-Based Reasoning for Novel Claims

**Complexity:** Medium-Complex · **Phase:** Complement to 7.11 · **Estimated Cost:** ~$0.003 per query (vector search + retrieval)

---

## The Problem

Recipe 7.11 gave you a gradient-boosted tree model that predicts claim denials. It works great. Really great, actually, when you have dense, representative training history for the payer and procedure combination in question. But let me paint you a scenario that makes that model sweat.

You're a clearinghouse or revenue cycle middleware company. You process claims for hundreds of provider organizations across dozens of payers. Every week, new payers show up in your stream. Every month, new procedure codes appear (CMS updates codes quarterly; payers add custom codes constantly). Your system sees a claim for a payer it has 47 historical examples from. Your XGBoost model, trained on 500,000 claims, has exactly 47 datapoints for this payer. Its prediction for this claim will be... something. It will output a number between 0 and 1 with perfect confidence because that's what tree models do. They always produce a score. They never say "I have no idea."

That's the danger. Gradient-boosted trees are incapable of expressing uncertainty about inputs they've never seen. A claim with a novel payer-procedure combination gets the same confident-looking probability output as a claim with 10,000 historical precedents. The model doesn't distinguish "I've seen 5,000 claims like this and 73% were denied" from "I've never seen anything like this, but the leaf node it landed in had a 73% denial rate for completely different reasons."

Now imagine you're the middleman and a provider calls asking why you flagged their claim. "The model said 73% denial risk" isn't going to cut it. They want to know: "What comparable claims have you seen? What happened to them? Show me the evidence." Case-based reasoning: the ability to point to specific similar resolved claims and say "these five claims are the closest matches we have, and four of them were denied for reason X."

This is the problem space where k-nearest-neighbors and similarity retrieval shine:

1. **Cold start.** A new payer appears with zero training history. A supervised model can't be payer-specific yet. But you can find claims submitted to similar payers (same region, same plan type, similar formularies) and look at their outcomes.

2. **Novelty detection.** When a claim is far from anything in your history, you can measure that distance and flag it: "this claim is out of distribution; human review recommended." XGBoost has no built-in mechanism for this.

3. **Case-based explanation.** "Here are the 5 most similar claims we've processed. 4 were denied, 1 was paid. The denied ones all lacked prior authorization." That's an explanation that makes intuitive sense to anyone, regardless of their statistical background.

4. **Heterogeneous streams.** When you process claims across wildly different payers with different rules, a single global model smooths over payer-specific quirks. Similarity search lets you find relevant precedents within the same payer cohort, even with limited data.

Here's how this relates to 7.11. The gradient-boosted model from 7.11 is your primary predictor. It's more accurate, faster to score, and better calibrated when you have representative training data. This recipe is the safety net, the confidence layer, and the explanation engine that wraps around it. You're not replacing the tree model. You're giving it self-awareness about what it doesn't know.

---

## The Technology: Instance-Based Learning, Similarity Retrieval, and Clustering

### Two Distinct Techniques (Don't Confuse Them)

People often blur two related but fundamentally different approaches. Let's separate them cleanly:

**k-Nearest Neighbors / Similarity Retrieval:** Given a new claim, find the k most similar resolved claims in your history and look at their outcomes. This is retrieval. You're asking: "What happened when we saw claims like this before?" The answer is a set of specific historical cases with known outcomes, distances, and attributes. This is the core of case-based reasoning: reasoning by analogy to past cases.

**Clustering (k-means, DBSCAN, etc.):** Partition your entire claim population into groups that share structural similarity. This is segmentation. You're asking: "What are the natural groupings in my denial landscape?" The answer is a set of cluster labels: "denial archetype A (missing PA), archetype B (bundling errors), archetype C (timely filing)." Clustering is useful for operational routing and for discovering denial patterns, but it's not a predictor in the same sense.

Both are useful. This recipe focuses primarily on the similarity retrieval / kNN approach because that's what gives you novelty detection and case-based explanation. Clustering enters as an operational layer for routing and segmentation.

### How Similarity Search Actually Works

The fundamental idea is dead simple. You represent each claim as a vector (a list of numbers). You compute distances between vectors. Claims with small distances are "similar." Claims with large distances are "different."

The devil is in the details of that vector representation and that distance computation.

**Feature-based similarity (traditional).** Take the same features you'd feed to XGBoost (procedure code, diagnosis codes, payer, provider type, claim amount, modifiers) and encode them into a fixed-length numeric vector. Categorical features get one-hot encoded or target-encoded. Numeric features get normalized. Then you compute Euclidean distance, cosine similarity, or some other metric between vectors.

The problem: high-cardinality categoricals (10,000 CPT codes, 70,000 ICD-10 codes) create enormous sparse vectors. With one-hot encoding, two claims that differ by a single diagnosis code might look maximally different because they share zero non-zero positions in those dimensions. This is the curse of dimensionality: in very high-dimensional spaces, all points become roughly equidistant, and the concept of "nearest neighbor" becomes meaningless.

**Learned embeddings (modern).** Train a neural network to map claims into a lower-dimensional dense vector space (say, 128 or 256 dimensions) where similar claims are close together. "Similar" here means "had similar adjudication outcomes" or "share clinical and administrative characteristics." The embedding network learns which features matter for similarity and which are noise. Two claims with different-but-related diagnosis codes (say, E11.9 Type 2 diabetes unspecified vs. E11.65 Type 2 diabetes with hyperglycemia) will have similar embeddings even though their one-hot encodings share nothing.

In practice, you often use a hybrid: encode categorical features using pre-trained embeddings (from the XGBoost feature pipeline or a dedicated embedding model), concatenate with normalized numeric features, and optionally pass through a dimensionality reduction step (PCA, autoencoders) to get a compact vector.

### Distance Metrics Matter

The choice of distance metric determines what "similar" means:

**Euclidean distance** works well when features are normalized to similar scales. It treats all dimensions equally. A claim that's 0.3 away in the "payer" dimension and 0.3 away in the "procedure" dimension is equidistant from one that's 0.42 away in only the "procedure" dimension.

**Cosine similarity** measures the angle between vectors, ignoring magnitude. Good when you care about the pattern of features rather than their absolute values. Often better for sparse, high-dimensional spaces.

**Weighted distance** applies different importance weights to different feature dimensions. The payer dimension might matter more than the place-of-service dimension for denial prediction. You can learn these weights from data (metric learning).

**Mahalanobis distance** accounts for correlations between features. If procedure code and claim amount are correlated (complex procedures cost more), Mahalanobis distance won't double-count that signal.

For claims data specifically, a common practical approach is cosine similarity on learned embeddings. The embedding network implicitly handles feature weighting and correlation, so you can use a simple metric on the output vectors.

### Distance as a Confidence Signal

Here's the key insight that makes this whole recipe worth building: the distance to the nearest neighbors gives you a free out-of-distribution detector.

If a claim's nearest neighbor is distance 0.05 away in your embedding space, you have a close match. The historical outcomes of that neighbor (and its other close neighbors) are likely relevant. Your prediction for this claim is well-supported by precedent.

If a claim's nearest neighbor is distance 0.95 away, you're in uncharted territory. Nothing in your history looks like this. Any prediction (from kNN or from XGBoost) should be treated with skepticism. This is the novelty signal.

You can threshold on this: if `min_distance > threshold`, route to human review. If `min_distance <= threshold`, trust the model. The threshold is calibrated empirically: look at historical predictions where the nearest-neighbor distance was high and see if accuracy degrades (it will).

XGBoost has no equivalent signal. It always outputs a probability, and that probability has no built-in measure of "how confident are we that this probability is well-calibrated for this input?" Prediction intervals from conformal prediction are one approach, but nearest-neighbor distance is simpler and more interpretable.

### Cold Start: When You Have No History for a Payer

New payer shows up. Zero historical claims. Your supervised model has never seen this payer ID in training. What do you do?

Option 1: Use the global model (ignoring payer-specific features). This loses the most important signal, since payer identity is typically the strongest predictor of denial patterns.

Option 2: Similarity search across all payers. Find claims from other payers with similar characteristics: same plan type (commercial HMO vs. PPO), same region, same procedure code, similar patient demographics. The outcomes of those similar claims from other payers give you a rough prior for how this new payer might behave.

This is case-based reasoning at its most powerful. On day one with a new payer, you can say: "We've never seen claims from Payer X before, but based on 200 similar claims from other regional commercial HMOs, the denial rate for this procedure code is approximately 18%, driven primarily by missing documentation rather than medical necessity."

As claims for the new payer accumulate and adjudicate, you gradually transition from cross-payer similarity (low confidence, broad precedent) to within-payer similarity (higher confidence, direct precedent) to a trained payer-specific model (highest confidence). The similarity system provides a graceful on-ramp.

### Clustering for Denial Archetype Segmentation

While kNN handles individual claim prediction and explanation, clustering serves a different operational purpose: discovering denial archetypes.

Run k-means or DBSCAN on your denied claims' feature vectors. The resulting clusters often correspond to distinct denial patterns:

- Cluster A: Missing prior authorization (mostly surgical, specific payers)
- Cluster B: Bundling/unbundling issues (multi-procedure claims, incorrect modifiers)
- Cluster C: Timely filing (claims submitted >30 days post-service)
- Cluster D: Medical necessity challenges (specific diagnosis-procedure mismatches)

These archetypes let you route denied claims to specialized rework teams (your PA team handles Cluster A, your coding team handles Cluster B) and let you build targeted interventions (if most of your denials fall in Cluster A, your biggest ROI is fixing the PA workflow, not improving coding accuracy).

### The Hybrid Pattern

The production architecture combines all three approaches:

1. **Primary score:** XGBoost/LightGBM from Recipe 7.11 outputs a denial probability.
2. **Confidence layer:** kNN distance check determines whether the primary score is trustworthy for this input.
3. **Explanation layer:** Retrieve k-nearest resolved claims and present them as case-based evidence supporting or contradicting the primary score.
4. **Cold start fallback:** When the primary model has insufficient payer-specific data, use cross-payer similarity as the predictor.
5. **Operational segmentation:** Clustering assigns denied claims to archetype groups for routing and pattern discovery.

The decision logic:
- If nearest-neighbor distance is low (claim is well-represented in history) AND primary model has confident score: use the primary model's prediction.
- If nearest-neighbor distance is high (novel claim) OR primary model lacks payer-specific data: flag for human review and provide the k-nearest cases as evidence.
- If the kNN outcome disagrees with the primary model (neighbors say "likely denied" but XGBoost says "likely paid" or vice versa): flag the disagreement and present both signals to the reviewer.

---

## General Architecture Pattern

```text
[Claims Stream] → [Embedding Pipeline] → [Vector Store / Index]
                                        → [Similarity Query Service]
                                        → [Novelty Scoring Service]
                                        → [Case Retrieval API]
                                        → [Cluster Assignment Service]
                                        → [Hybrid Decision Engine (combines with 7.11 model)]
```

Logical stages:

1. **Embedding pipeline.** For each resolved claim, compute a feature vector (or learned embedding). Store this vector alongside the claim's metadata and outcome (paid/denied, denial reason, appeal outcome). Run batch for historical backfill; run incrementally as new claims adjudicate.

2. **Vector index.** An approximate nearest-neighbor index over the claim embeddings. Supports fast similarity queries: "give me the 20 nearest claims to this input, with their distances." Refreshed as new resolved claims enter the system. New embeddings become searchable after OpenSearch's refresh interval (default: 1 second for standard indexing, longer for bulk operations). For HNSW indexes, newly indexed vectors join the graph during the next segment merge. In practice, expect 1-5 minutes between indexing a new claim and it being retrievable as a neighbor. For the cold-start use case, this latency is acceptable since you're searching historical context, not real-time results.

3. **Similarity query service.** Given a new (unresolved) claim, compute its embedding, query the index, and return the k nearest resolved claims with distances. Used at scoring time and at explanation time.

4. **Novelty scoring.** Compute the distance to the k-th nearest neighbor. If above threshold, flag the claim as out-of-distribution. This signal feeds into the hybrid decision engine.

5. **Case retrieval API.** Downstream consumers (billing worklists, provider portals) can request "show me similar resolved claims" for any given claim. Returns enriched records with outcome, denial reason, and similarity score.

<!-- TODO (TechWriter): Expert review SEC-3 (MEDIUM). Add access control guidance for the case retrieval API: provider portals should only surface cases from the same provider organization (or de-identified cases); internal billing worklists can see broader comparisons. Implement row-level filtering in the OpenSearch query by provider_org_id for provider-facing use cases, or strip identifiable metadata for cross-organization comparisons. -->

6. **Cluster assignment.** Periodically re-cluster the denied claims population. Assign incoming denied claims to their nearest archetype cluster for routing.

<!-- TODO (TechWriter): Expert review ARCH-3 (MEDIUM). Add operational detail: re-cluster monthly (or when denial volume exceeds threshold since last run). Store cluster labels with a cluster_version field in DynamoDB. Downstream routing queries by current cluster version. Alert when cluster composition shifts significantly between runs. -->

7. **Hybrid decision engine.** Combines the primary XGBoost score from 7.11 with the novelty score and kNN outcome distribution to produce a final recommendation: {prediction, confidence, supporting_cases, novelty_flag, recommended_action}.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.12-architecture). The Python example is linked from there.

## The Honest Take

Let's be real about what this approach can and can't do.

**The curse of dimensionality is real.** If your embedding is 256 dimensions but you only have 100,000 claims, every point is roughly equidistant from every other point in that space. Your "nearest neighbor" might not be meaningfully near at all. Keep embedding dimensions conservative (64-128 for claim volumes under a million) and validate that nearest-neighbor distances are actually discriminative (plot the distribution and confirm there's a meaningful gap between "truly similar" and "just the closest thing we have").

**"Similar inputs" does not guarantee "same payer decision."** Two claims with identical procedure codes, similar diagnosis codes, and the same payer can have different outcomes because of details not captured in your feature set: clinical notes content, specific policy version in effect, reviewer discretion, time-of-year budget pressure. The kNN prediction is a population-level signal, not a guarantee. A 75% denial rate among neighbors means "claims like this usually get denied," not "this specific claim will be denied."

**Index freshness is critical.** Your vector index contains resolved claims. A claim takes 2-6 weeks to adjudicate. That means your index is always at least 2 weeks stale relative to the newest payer policy changes. If a payer changes coverage rules on January 1st, claims submitted in January won't have outcomes until February or March. Your index won't reflect the new rules until then. Monitor for sudden accuracy drops (which often signal payer rule changes) and add manual override capability for known policy changes.

**Feature scaling makes or breaks it.** If your billed amount ranges from $10 to $500,000 and you don't normalize it, the distance metric will be dominated by dollar differences. Two $500,000 knee replacements with different payers will look more similar than a $500,000 knee replacement and a $5,000 knee replacement from the same payer. Normalize everything. Or use learned embeddings that handle scaling implicitly.

**Fairness and bias carry forward.** If your historical data encodes biased payer decisions (certain demographic groups denied at higher rates for non-clinical reasons), your similarity system will reproduce those patterns. A claim from a demographically similar patient will retrieve biased historical outcomes as "similar precedent." The same fairness monitoring and bias mitigation from Recipe 7.11 applies here. Monitor outcomes by demographic subgroup and flag disparities in the kNN predictions.

**Don't assume embeddings are anonymized.** Dense embeddings can potentially be inverted to recover approximate input features. If an attacker gains read access to your vector index, they could reconstruct diagnosis codes, procedure codes, and demographic signals from the numeric vectors alone. Apply the same access controls to your vector index that you apply to the source claims data. Don't grant broader read access to the OpenSearch domain than you would to the claims database just because "it's just vectors."

**This complements the supervised model. It does not replace it.** For well-represented payer-procedure combinations (where you have thousands of training examples), XGBoost will outperform kNN every time. The gradient-boosted model can learn complex non-linear decision boundaries that kNN with Euclidean/cosine distance cannot represent. Use kNN where the tree model is weak: novelty, explanation, cold start. Not everywhere.

**Approximate nearest-neighbor is approximate.** HNSW and IVF indexes trade recall for speed. Your "nearest 20" might not actually be the 20 nearest in exact distance. For large indexes, expect 95-98% recall at typical query parameters. This is fine for this use case (you don't need the exact nearest; you need a representative neighborhood), but be aware that edge cases exist where the true nearest neighbor is missed.

---

## Related Recipes

- **Recipe 7.11 (Claim Denial / Prior-Auth Determination Prediction):** The primary supervised classifier this recipe complements. Use 7.11 as the workhorse predictor; use 7.12 for confidence estimation, novelty detection, and case-based explanation.
- **Recipe 6.x (Cohort Analysis / Clustering):** The clustering techniques for denial archetype segmentation draw from the same algorithmic foundations as the patient clustering recipes in Chapter 6. If you're building denial archetype clusters, the infrastructure patterns from Chapter 6 apply directly.
- **Recipe 5.x (Entity Resolution / Record Linkage):** The similarity search and distance-metric concepts here are cousins of the record-matching techniques in Chapter 5. Both involve computing feature vectors for healthcare records and finding the closest matches. The difference is intent: Chapter 5 asks "is this the same entity?"; this recipe asks "did similar entities have similar outcomes?"

---

## Tags

`predictive-analytics` `claims` `denial-prediction` `k-nearest-neighbors` `similarity-search` `case-based-reasoning` `novelty-detection` `cold-start` `vector-search` `opensearch` `embeddings` `revenue-cycle` `prior-authorization`

---

[← Recipe 7.11: Claim Denial / Prior-Auth Determination Prediction](chapter07.11-claim-denial-prediction) | [Chapter 7 Index](chapter07-preface) | [Chapter 8: NLP →](chapter08-preface)
