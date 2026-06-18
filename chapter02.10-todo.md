# Open TODOs — Recipe 2.10: Multi-Modal Clinical Reasoning

> Auto-extracted 2026-06-18 from inline source comments (10 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter02.10-multi-modal-clinical-reasoning.md`

- **L243** — TODO (TechWriter): update to specific recipe number once Chapter 9 is drafted.
- **L244** — TODO (TechWriter): update to specific recipe number once Chapter 12 is drafted.
- **L245** — TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted.
- **L246** — TODO (TechWriter): update to specific recipe number once Chapter 7 is drafted.

## architecture — `chapter02.10-architecture.md`

- **L162** — TODO (TechWriter, from expert review A3): EventBridge is at-least-once
     delivery. The UUID approach here produces a new run on every duplicate
     delivery. Consider deriving run_id from a deterministic event-key hash
     (for example `f"{patient_id}:{encounter_id}:{scenario}"`) and using a
     DynamoDB conditional write (`attribute_not_exists(run_id)`) plus a
     Step Functions deterministic execution name so duplicates are rejected
     at the orchestration layer rather than running the full pipeline twice.
     This pattern has recurred across multiple Chapter 2 recipes and is a
     candidate for a chapter-wide appendix.
- **L437** — TODO (TechWriter, from expert review A2): each ingestion function currently
     returns a bare list. Expert review A2 recommends distinguishing "failed to
     retrieve" (HealthImaging timeout, Comprehend throttle, vendor AI 500) from
     "genuinely absent" (the patient does not have this modality). Consider
     returning a status-annotated record per modality (`status: "retrieved" |
     "empty" | "failed" | "scoped_out"`) and building the inventory from status
     rather than cardinality. The scope gate's defer path should then route
     `failed` to retry rather than defer.
- **L445** — TODO (TechWriter, from expert review S1): add a PHI-minimization step
     between Step 3 and Step 7 that strips MRN, DOB, name, address, phone,
     email, and payer or NPI identifiers from the serialized state before the
     reasoning prompt is constructed. Bedrock under BAA is compliant for PHI,
     but minimum-necessary applies inside the BAA boundary as well. The
     rendered output re-associates reasoning to the patient via run_id plus
     patient_id; identifiers do not need to round-trip through the prompt.
- **L511** — TODO (TechWriter, from expert review A4): the "scoped_to" rewrite for
     missing recommended modalities fires only when scenario ==
     "comprehensive_reasoning". For any other scenario (including
     "ed_dyspnea_workup"), a recommended-but-missing modality currently has
     no architectural handler; the recipe depends on the reasoning layer
     obeying the prompt's hard requirements rather than a scope-gate
     guarantee. Consider expanding this branch so every scenario has one of
     three handlers for a missing recommended modality: (a) narrow the scope
     to a sub-scenario, (b) proceed with a completeness_cap of "low", or (c)
     defer when the recommended modality is effectively required for that
     sub-scenario (for example ECG for ACS-inclusive reasoning).
- **L1371** — TODO (TechWriter): verify current status and URL of HealthBench.
- **L1372** — TODO (TechWriter): verify current URL and status.
