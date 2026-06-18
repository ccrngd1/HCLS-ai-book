# Open TODOs — Recipe 8.9: Temporal Relationship Extraction

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.09-architecture.md`

- **L43** — TODO (TechWriter): Expert review A1 (HIGH). Add error handling paths to architecture: SQS DLQ for failed notes, Step Functions retry config (MaxAttempts=3, exponential backoff for Comprehend throttling), CloudWatch alarm on DLQ depth > 10. Show error paths in diagram.
- **L57** — TODO (TechWriter): Expert review S3 (MEDIUM). Add training corpus access control guidance: separate S3 bucket from inference pipeline, bucket policy restricts access to ML training roles only, S3 access logging enabled, versioning enabled for annotation provenance.
- **L60** — TODO (TechWriter): Expert review S1 (HIGH). Add data retention/lifecycle policy row to Prerequisites: DynamoDB TTL configured per institutional records retention policy (typically 7-10 years adult, longer for minors). Neptune graph data lifecycle managed via scheduled deletion jobs. S3 lifecycle policy for processed clinical notes.
- **L181** — TODO (TechWriter): Expert review A2 (MEDIUM). Add a fifth heuristic for section-anchored pairs: events in different sections that share a temporal expression or are both anchored to the same clinical episode (same admission, same procedure). This captures cross-section relationships like HPI events linked to Hospital Course events in discharge summaries.
- **L413** — TODO (TechWriter): This section is required by RECIPE-GUIDE but was not present after the split. Add 3-5 bullet points covering gaps a production deployment must close (e.g., model retraining cadence, annotation pipeline, cross-document linking, human-in-the-loop review workflows, institution-specific temporal pattern tuning).
