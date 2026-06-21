# Open TODOs: Recipe 8.3: ICD-10 Code Suggestion

> Auto-extracted 2026-06-18 from inline source comments (8 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter08.03-icd-10-code-suggestion.md`

- **L5** — TODO (TechWriter): Confirm cost estimate. Body text says $0.05-$0.15 section-targeted, $0.40-$1.00 full text. Original header had $0.01-$0.05 which understates.

## architecture — `chapter08.03-architecture.md`

- **L73** — TODO (TechWriter): Expert review S2 (MEDIUM). Add input validation guidance before preprocessing: verify UTF-8 encoding, enforce minimum length (e.g., 50 chars), reject binary/null bytes, validate encounter_id format. Mention API Gateway rate limiting and authentication to prevent cost-based DoS.
- **L135** — TODO (TechWriter): Expert review A1 (MEDIUM). Add error handling guidance: wrap InferICD10CM call in retry with exponential backoff (2 retries, 1s/2s delays). On persistent failure, return a valid response with suggestion_count: 0 and status: 'service_unavailable' rather than HTTP 500. For batch processing via S3 events, add an SQS DLQ for failed invocations.
- **L299** — TODO (TechWriter): Expert review S3 (LOW). Add requester_id to the stored suggestion record and response payload. For HIPAA minimum necessary compliance, capture who triggered the suggestion request (coder identity from EHR session context in API request headers).
- **L436** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add 3-5 bullets covering gaps a production deployment must close (e.g., no human-in-the-loop enforcement, no code version drift handling, no A/B framework for threshold tuning).
- **L462** — TODO (TechWriter): Verify these repo URLs still exist and are public
- **L468** — TODO (TechWriter): Verify blog URLs are current
- **L474** — TODO (TechWriter): Consider updating MIMIC-III references to MIMIC-IV (current version). Verify URL.
