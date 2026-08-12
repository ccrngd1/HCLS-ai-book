<!-- Removed from chapter13.09-literature-derived-knowledge-graph.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you when you build this:

The NLP extraction is not the hardest part. Getting 75% precision on relation extraction is achievable with off-the-shelf models and a week of fine-tuning. The hard parts are everything around the NLP: entity normalization (the long tail of synonyms is endless), evidence grading (how do you automatically distinguish a well-powered RCT from a pilot study?), and conflict resolution (the literature genuinely contradicts itself, and both sides often have reasonable evidence).

Your graph will be noisy. Accept this early. A literature-derived knowledge graph is not a curated database. It's a probabilistic representation of what the literature says, with confidence scores and provenance. The value is in surfacing relationships that human curators haven't gotten to yet, not in replacing curated databases for high-stakes clinical decisions. Frame it as "hypothesis generation" rather than "clinical truth" and you'll set appropriate expectations.

The normalization problem is bottomless. You'll get 90% of entities normalized in the first month. The remaining 10% will take forever because they're novel compounds, non-standard gene nomenclature, or ambiguous abbreviations that could mean three different things depending on context. Build a feedback loop where unmapped entities are periodically reviewed and added to your normalization dictionaries.

Reprocessing is your secret weapon. When you improve your RE model (and you will, continuously), you can re-run the entire pipeline against your document lake. This means your graph quality improves retroactively. Design for this from day one: store raw documents, track which model version produced each extraction, and build the infrastructure to do bulk reprocessing without disrupting live queries.

The comparison to curated databases is unfair but inevitable. Stakeholders will compare your automatically extracted graph to PharmGKB or DrugBank and note the errors. The right framing: curated databases are high-precision, low-recall, and months behind the literature. Your graph is moderate-precision, higher-recall, and days behind the literature. They're complementary, not competing.

---

