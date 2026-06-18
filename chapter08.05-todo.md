# Open TODOs — Recipe 8.5: Problem List Extraction

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.05-architecture.md`

- **L23** — TODO (TechWriter): Expert review A2 (MEDIUM). Add SQS DLQ for Lambda invocation failures and a CloudWatch alarm on DLQ depth. Show in diagram and mention in "Why These Services."
- **L123** — TODO (TechWriter): Expert review A4 (MEDIUM). Add note that Comprehend Medical DetectEntitiesV2 has a 20,000-character limit per request. Sections exceeding this need chunking at sentence boundaries with offset correction. Discharge summaries and operative notes can exceed this.
- **L237** — TODO (TechWriter): Expert review A5 (MEDIUM). Reconciliation uses only top-1 SNOMED code for matching. Should check all top-3 candidates or use SNOMED hierarchy-aware deduplication to avoid false ADD_CANDIDATE recommendations for problems already on the list under a different code.
- **L296** — TODO (TechWriter): Expert review A3 (MEDIUM). Add note about idempotent reprocessing: recommendation_id should be deterministic (note_id + snomed_code + type) with a conditional write to prevent duplicates on reprocessing.
- **L406** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section here (between Expected Results and Variations). Should cover gaps like: no clinician review UI, no feedback loop to improve assertion accuracy, no multi-note aggregation, no handling of conflicting assertions across notes, no SNOMED hierarchy-aware deduplication.
