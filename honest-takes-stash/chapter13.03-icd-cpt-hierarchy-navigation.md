<!-- Removed from chapter13.03-icd-cpt-hierarchy-navigation.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The graph model is genuinely elegant for this problem. Once you have the hierarchy loaded, questions that used to require a DBA writing recursive SQL become trivial API calls. The first time a population health analyst says "give me all diabetes codes" and gets a complete, correct answer in 20ms instead of maintaining a spreadsheet of codes they hope is complete, you'll feel good about the investment.

But here's what will surprise you: the hard part isn't the graph database. It's the ETL. CMS publishes ICD-10-CM in a format that was designed for humans reading printed books, not for machines building graphs. The "order file" encodes hierarchy through positional formatting. The annotation files (excludes, includes, code-first notes) are in a separate format with their own parsing challenges. You'll spend more time writing robust parsers for these source files than you will on the graph queries.

The CPT side is worse because it requires an AMA license, the data formats are proprietary, and the cross-walk files from different payers arrive in different formats. Budget significant time for the ingestion pipeline.

The version transition is the other gotcha. Your first annual update will reveal edge cases in your SUPERSEDED_BY logic. Codes don't always map one-to-one when they're retired. Sometimes one code splits into three. Sometimes three codes merge into one. The GEMs (General Equivalence Mappings) files handle this, but they're approximate mappings, not exact equivalences. Your analytics team will need to understand that "E11.65 in FY2024" and "E11.65 in FY2025" might not mean exactly the same clinical concept if the code definition was refined.

One more thing: Neptune's openCypher support is good but not complete. If you're coming from Neo4j, some Cypher features you're used to (like APOC procedures) don't exist. Variable-length path bounds must be literal integers, not parameters. Test your query patterns against Neptune specifically during development, not just against a local Neo4j instance.

---

