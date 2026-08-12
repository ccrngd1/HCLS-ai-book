<!-- Removed from chapter13.02-provider-directory-knowledge-graph.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The graph model is genuinely the right abstraction for provider directories. The moment you try to answer "find me a provider who..." questions with more than two constraints, the graph approach wins decisively over relational joins. The query code reads like the question you're asking, which makes it maintainable and extensible.

The part that will surprise you: the graph database is the easy part. Neptune, Neo4j, or any mature graph DB handles the storage and traversal beautifully. The hard part is the data pipeline. Getting clean, reconciled, current provider data into the graph is 80% of the engineering effort. Provider data is messy, contradictory, and constantly changing. You'll spend more time on the ETL jobs than on the graph queries.

The other surprise: you'll want a full-text search engine alongside your graph database, not instead of it. Patients don't search by NPI or NUCC code. They search by name fragments, partial addresses, and colloquial specialty names ("heart doctor" not "207RC0000X"). A text search engine handles the fuzzy text matching and geospatial filtering; the graph database handles the relationship traversal. The two together are more powerful than either alone.

One more thing: don't underestimate the specialty hierarchy. "Cardiology" means different things to different people. A patient searching for a "heart doctor" might need a general cardiologist, an interventional cardiologist, a cardiac electrophysiologist, or a cardiothoracic surgeon. Getting the taxonomy traversal right (and making it configurable per search context) is worth investing in early.

---

