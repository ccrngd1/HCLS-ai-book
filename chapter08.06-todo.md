# Open TODOs — Recipe 8.6: Social Determinants of Health (SDOH) Extraction

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.06-architecture.md`

- **L44** — TODO (TechWriter): Expert review A1 (MEDIUM). Add SQS Dead Letter Queue to architecture diagram and mention CloudWatch alarm on DLQ depth for failed note processing.
- **L329** — TODO (TechWriter): Expert review A3 (MEDIUM). Note that population-level queries ("all patients with active food insecurity") require a GSI on domain#assertion as partition key. Add 1-2 sentences here or in Prerequisites.
- **L330** — TODO (TechWriter): Expert review S1 (MEDIUM). Add note about restricting sdoh-profiles table access to care management roles; mention option to store only metadata (domain, assertion, codes) without source_text, linking to note_id for authorized reviewers.
- **L431** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add content covering gaps a production deployment must close.
- **L461** — TODO: Verify that the amazon-comprehend-medical-fhir-integration repo still exists and is maintained
- **L462** — TODO: Verify current Comprehend Medical pricing for DetectEntitiesV2
