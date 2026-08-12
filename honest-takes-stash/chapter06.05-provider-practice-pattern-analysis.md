<!-- Removed from chapter06.05-provider-practice-pattern-analysis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what surprised me about building these systems: the clustering is the easy part. Getting clean, case-mix-adjusted data is 60% of the work. Getting providers to trust the methodology is 30%. The actual ML is maybe 10%.

The case-mix adjustment will never be perfect, and providers know it. The surgeon who specializes in revision hip replacements (inherently more complex than primary replacements) will always have higher complication rates than peers, and no risk adjustment model fully accounts for that level of subspecialization. You need a process for handling legitimate exceptions without undermining the entire system.

The silhouette scores you'll see in practice (0.25-0.45) are lower than what textbooks show for clean datasets. Provider practice patterns exist on a spectrum, not in discrete buckets. The clusters are useful simplifications, not natural categories. Present them that way.

The most valuable output is often not the cluster assignments themselves but the individual provider reports showing exactly where they differ from peers. A provider who learns "you order 40% more MRIs than expected given your patient mix" has actionable information regardless of which cluster they're in.

Start with a non-punitive use case. Peer learning, CME targeting, or resource planning. Once providers trust the methodology and see value in the insights, you can gradually connect it to quality improvement initiatives. Leading with "we're going to measure you and compare you to your peers" guarantees resistance. Leading with "we built a tool that shows you how your practice compares, and some providers found it useful for identifying blind spots" gets curiosity.

One more thing: the clusters will reveal uncomfortable truths. You'll find that the "thorough/resource-intensive" cluster has slightly better outcomes but dramatically higher costs. Is that worth it? That's not a data science question. That's an organizational values question. The system surfaces the tradeoff. Humans decide what to do about it.

---

