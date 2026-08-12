<!-- Removed from chapter13.01-drug-formulary-navigation.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This recipe is one of the cleaner knowledge graph applications because the source data is already structured. You're not doing NLP extraction or entity resolution. The formulary file tells you exactly which drugs are on which tier. The graph just makes it navigable in ways a flat file can't support.

The part that will surprise you: building the graph is maybe 20% of the work. Keeping it current is 80%. Formularies change quarterly, but the real headache is mid-quarter amendments. A new drug gets FDA approval and the P&T committee adds it in week 6 of the quarter. A safety signal causes a drug to be removed. A manufacturer rebate deal changes tier placement for a single drug. Each of these is a targeted graph update that needs to happen within days, not wait for the next quarterly reload.

The therapeutic alternative relationships are where the real value lives, and they're also the hardest to get right. The formulary file might list alternatives, but those lists are often incomplete or based on class membership rather than true clinical equivalence. A statin is not always interchangeable with another statin for a specific patient (dose equivalence tables matter, contraindications matter, prior adverse reactions matter). The graph can tell you what's formulary-preferred, but clinical judgment still determines what's appropriate. Make sure your UI communicates "formulary alternatives" not "recommended substitutions."

The cache hit rate makes or breaks your cost model. Managed graph databases are not cheap (see the architecture companion for specific pricing). If 90% of queries hit your cache layer, your effective cost per query is trivial. If your cache hit rate drops (because you have many plans with different formularies, or because you're not normalizing drug identifiers consistently in cache keys), graph query volume spikes and you need a larger instance.

One more thing: the gap between "what the formulary file says" and "what the PBM actually adjudicates" is real and frustrating. I've seen cases where a drug is listed as Tier 2 in the formulary file but consistently adjudicates at Tier 3 due to a system override that nobody documented. Your graph reflects the published formulary, not necessarily the operational reality. Build feedback loops from claims adjudication data to validate your graph against actual tier assignments.

---

