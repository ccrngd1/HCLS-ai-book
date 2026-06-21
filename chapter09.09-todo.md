# Open TODOs: Recipe 9.9: Surgical Video Analysis

> Auto-extracted 2026-06-18 from inline source comments (8 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter09.09-architecture.md`

- **L15** — TODO (TechWriter): Expert review S1 (CRITICAL). Add PHI de-identification guidance for surgical video preprocessing: strip audio tracks (not needed for visual analysis but contain dense PHI), address pre-incision footage containing patient faces, sanitize video file metadata/headers, note OR monitor overlay detection for patient demographics displayed in-frame.
- **L21** — TODO (TechWriter): Expert review S5 (HIGH). Address SageMaker Batch Transform cold start (5-15 min provisioning overhead). Recommend batching strategies for medium volume (5-20 procedures/day) and real-time endpoints for high volume (>20/day). Adjust cost estimate to account for amortized cold start.
- **L65** — TODO (TechWriter): Expert review S3 (HIGH). Expand IAM permissions into role-based groupings (Step Functions execution role, Lambda execution role, SageMaker execution role) with resource ARN scoping guidance rather than a flat list.
- **L121** — TODO (TechWriter): Expert review A5 (HIGH). Add failure handling guidance: Step Functions catch-all state writing to a DLQ (SQS), CloudWatch alarm on DLQ depth, and a scheduled Lambda scanning for procedures stuck in "ingested" or "processing" status beyond a threshold for automatic retry.
- **L289** — TODO (TechWriter): Expert review S2 (CRITICAL). Add access control model for surgeon-identifiable performance data: pseudonymize surgeon_id in the general search index with a separate restricted lookup table, add role-based access control for surgeon-identified queries, note peer review protection requirements (vary by state, require legal counsel review), and add CloudTrail-based audit logging for queries that resolve surgeon identity.
- **L291** — TODO (TechWriter): Expert review S7 (MEDIUM). Define OpenSearch index mappings for procedure-phases and procedure-events indices: keyword fields for phase_name, event_type, procedure_type, surgeon_id; numeric fields for timestamps and durations; date field for procedure_date. Note that the temporal query pattern (event within a phase time range) works because events carry phase_context.
- **L439** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section here (between Expected Results and Variations) per the architecture companion template.
- **L473** — TODO: Verify all URLs above are current and accessible. Research dataset links may change as hosting institutions update their sites.
