<!-- Removed from chapter06.01-geographic-patient-clustering.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Geographic clustering is one of those problems that feels like it should be a weekend project. Plot the dots, find the dense areas, done. And honestly, for a first pass, it kind of is. You can get a useful "here's where our patients are" map in a day.

The complexity creeps in when people start making decisions based on it. The moment someone says "let's build a $40 million clinic based on cluster 7," you need to answer questions like: How stable is this cluster over time? What happens if the new housing development on the east side fills up? Are we counting the nursing home as 400 patients or one location? Did we miss the 15% of patients with PO Boxes who might actually live in the gap between clusters?

The parameter tuning is where I've seen teams get stuck. DBSCAN's epsilon and min_samples feel arbitrary, and they are. There's no objectively correct answer. A 2km epsilon gives you tight neighborhood-level clusters. A 10km epsilon gives you regional market areas. Both are "right" depending on the question. The mistake is picking parameters once and treating the output as ground truth. Run it multiple times with different parameters. Show stakeholders the sensitivity. "At tight clustering, we see 47 micro-clusters. At loose clustering, we see 8 regional markets. Which view is useful for your decision?"

The geocoding quality issue surprised me more than I expected. In one project, 22% of addresses failed to geocode at high confidence. Most were rural routes, PO Boxes, and addresses with typos. That 22% wasn't randomly distributed. It was concentrated in exactly the underserved areas we were trying to analyze. The analysis was systematically blind to the populations that needed it most. We ended up running a separate process to estimate locations for failed geocodes using ZIP code centroids, which is imprecise but better than exclusion.

One more thing: don't forget that clusters change. Run this quarterly, not once. Patient populations shift, new developments open, employers relocate. A cluster analysis from January that drives a facility decision in December is working with stale data.

The incremental refresh pattern that actually works in production looks like this: maintain a "last processed" snapshot of patient addresses alongside the geocoded output. On each pipeline run, diff the current EHR extract against that snapshot to identify three categories: new patients (never geocoded), changed addresses (geocode again), and unchanged (carry forward the previous coordinates). Only send the new and changed addresses through the geocoding step. Merge the fresh geocoding results with the carried-forward coordinates, then run clustering on the full merged set. This approach reduces geocoding costs from ~$100/run to ~$5-10/run for typical monthly patient churn (2-5% address changes). The merge step is the part teams underestimate. You need a reliable patient identifier that persists across extracts, a consistent output schema so old and new coordinates interleave cleanly, and a "staleness" flag so you can periodically re-geocode even unchanged addresses (postal service renumberings happen, geocoder accuracy improves over time). Without these, you'll accumulate drift between your cached coordinates and reality.

---

