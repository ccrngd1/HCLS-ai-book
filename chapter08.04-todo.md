# Open TODOs — Recipe 8.4: Medication Extraction and Normalization

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.04-architecture.md`

- **L40** — TODO (TechWriter): Expert review A2 (MEDIUM). Add SQS dead letter queue to the architecture diagram and "Why These Services" section. Failed Lambda extractions (throttling, malformed notes, 20K char limit exceeded) should route to a DLQ for retry/investigation rather than being silently dropped.
- **L56** — TODO (TechWriter): Expert review N2 (LOW). Add a note on Comprehend Medical regional availability (us-east-1, us-east-2, us-west-2, eu-west-1, eu-west-2, ap-southeast-2, ca-central-1 as of 2024). Data residency requirements may constrain region selection.
- **L274** — TODO (TechWriter): Expert review A3 (MEDIUM). Add a note about idempotency/deduplication. If the same note is reprocessed (S3 at-least-once delivery, pipeline reruns), the extraction_ts sort key creates duplicates. Recommend conditional writes using note_id + medication_text + begin_offset, or using note_id as sort key to overwrite previous extractions.
- **L378** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add 3-5 bullet points covering gaps like pharmacist review workflow, handling of multi-language notes, deduplication across repeated processing, and integration testing against real clinical note diversity.
- **L408** — TODO (TechWriter): Verify all GitHub repo URLs exist and are current.
