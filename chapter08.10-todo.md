# Open TODOs: Recipe 8.10: Phenotype Extraction for Research

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter08.10-phenotype-extraction-research.md`

- **L59** — TODO (TechWriter): Expert review VOC-1 (MEDIUM). This subsection partially overlaps with the Problem section (inter-rater reliability, ambiguity). Consider consolidating overlapping points and targeting ~20% reduction. Move unique points (portability, prevalence, reproducibility) into a shorter list.

## architecture — `chapter08.10-architecture.md`

- **L21** — TODO (TechWriter): Expert review SEC-2 (MEDIUM). Add data retention/TTL policy guidance for DynamoDB evidence store. Research data governance requires defined retention schedules; intermediate NLP artifacts should have shorter retention than final classifications.
- **L154** — TODO (TechWriter): Expert review ARC-4 (MEDIUM). Add chunking logic for notes exceeding Comprehend Medical's 20,000-character limit. Split at sentence boundaries before 18,000 chars, process chunks independently, merge and deduplicate results.
- **L298** — TODO (TechWriter): Expert review ARC-5 (MEDIUM). Add temporal conflict resolution when positive and negative evidence exist for same criterion. Most recent note takes priority for current-status phenotypes; any-positive suffices for ever-had phenotypes. Document which interpretation the phenotype uses.
- **L472** — TODO (TechWriter): RECIPE-GUIDE compliance. Add "Why This Isn't Production-Ready" section between Expected Results and Variations. Cover gaps like: no drift detection for phenotype accuracy over time, no automated re-validation when NLP model versions change, lack of clinician-in-the-loop adjudication workflow, and missing cross-institution portability testing.
