<!-- Removed from chapter06.08-disease-subtype-discovery.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Disease subtype discovery is one of those problems that feels like it should be straightforward. You have patients, you have features, you run clustering, you get subtypes. In practice, it's one of the most intellectually demanding ML applications in healthcare because the hardest question isn't "how do I cluster?" but "are these clusters real?"

The thing that surprised me most: the number of clusters matters less than you'd think. Whether you find 3 subtypes or 6 subtypes, the clinical utility depends entirely on whether the subtypes have different outcomes and different optimal treatments. Four well-characterized subtypes with clear treatment implications are infinitely more valuable than eight subtypes that a clinician can't distinguish at the bedside.

Feature selection is where projects succeed or fail. I've seen teams spend months on sophisticated clustering algorithms only to realize their features were dominated by age and sex. Of course you'll find clusters if you include demographics. The question is whether you find clusters that persist after adjusting for demographics. Start by clustering without age and sex, then check whether the clusters you find correlate with demographics. That ordering matters.

The validation gap is real. You can have beautiful, stable, well-separated clusters with excellent internal metrics, and they can still be clinically meaningless. The only validation that matters is: does a clinician look at these clusters and say "yes, I treat these patients differently"? If the answer is no, your clusters are a statistical curiosity, not a clinical tool.

One more thing: publication bias in this space is severe. The papers that get published are the ones that found clean, interpretable subtypes. The teams that ran the same analysis and found mush don't publish. If your first attempt produces ambiguous results, that's normal. It doesn't mean the approach is wrong. It might mean your feature set needs refinement, your cohort needs better definition, or the disease genuinely doesn't have discrete subtypes (it's a continuum, and forcing it into clusters is the wrong framing).

---

