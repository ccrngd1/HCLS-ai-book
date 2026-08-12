<!-- Removed from chapter07.12-claim-cohort-matching.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Let's be real about what this approach can and can't do.

**The curse of dimensionality is real.** If your embedding is 256 dimensions but you only have 100,000 claims, every point is roughly equidistant from every other point in that space. Your "nearest neighbor" might not be meaningfully near at all. Keep embedding dimensions conservative (64-128 for claim volumes under a million) and validate that nearest-neighbor distances are actually discriminative (plot the distribution and confirm there's a meaningful gap between "truly similar" and "just the closest thing we have").

**"Similar inputs" does not guarantee "same payer decision."** Two claims with identical procedure codes, similar diagnosis codes, and the same payer can have different outcomes because of details not captured in your feature set: clinical notes content, specific policy version in effect, reviewer discretion, time-of-year budget pressure. The kNN prediction is a population-level signal, not a guarantee. A 75% denial rate among neighbors means "claims like this usually get denied," not "this specific claim will be denied."

**Index freshness is critical.** Your vector index contains resolved claims. A claim takes 2-6 weeks to adjudicate. That means your index is always at least 2 weeks stale relative to the newest payer policy changes. If a payer changes coverage rules on January 1st, claims submitted in January won't have outcomes until February or March. Your index won't reflect the new rules until then. Monitor for sudden accuracy drops (which often signal payer rule changes) and add manual override capability for known policy changes.

**Feature scaling makes or breaks it.** If your billed amount ranges from $10 to $500,000 and you don't normalize it, the distance metric will be dominated by dollar differences. Two $500,000 knee replacements with different payers will look more similar than a $500,000 knee replacement and a $5,000 knee replacement from the same payer. Normalize everything. Or use learned embeddings that handle scaling implicitly.

**Fairness and bias carry forward.** If your historical data encodes biased payer decisions (certain demographic groups denied at higher rates for non-clinical reasons), your similarity system will reproduce those patterns. A claim from a demographically similar patient will retrieve biased historical outcomes as "similar precedent." The same fairness monitoring and bias mitigation from Recipe 7.11 applies here. Monitor outcomes by demographic subgroup and flag disparities in the kNN predictions.

**Don't assume embeddings are anonymized.** Dense embeddings can potentially be inverted to recover approximate input features. If an attacker gains read access to your vector index, they could reconstruct diagnosis codes, procedure codes, and demographic signals from the numeric vectors alone. Apply the same access controls to your vector index that you apply to the source claims data. Don't grant broader read access to your vector store than you would to the claims database just because "it's just vectors."

**This complements the supervised model. It does not replace it.** For well-represented payer-procedure combinations (where you have thousands of training examples), XGBoost will outperform kNN every time. The gradient-boosted model can learn complex non-linear decision boundaries that kNN with Euclidean/cosine distance cannot represent. Use kNN where the tree model is weak: novelty, explanation, cold start. Not everywhere.

**Approximate nearest-neighbor is approximate.** HNSW and IVF indexes trade recall for speed. Your "nearest 20" might not actually be the 20 nearest in exact distance. For large indexes, expect 95-98% recall at typical query parameters. This is fine for this use case (you don't need the exact nearest; you need a representative neighborhood), but be aware that edge cases exist where the true nearest neighbor is missed.

---

