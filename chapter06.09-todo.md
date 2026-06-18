# Open TODOs — Recipe 6.9: Social Determinant Phenotyping

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter06.09-social-determinant-phenotyping.md`

- **L138** — TODO (TechWriter): Expert review A1 (HIGH). Add 2-3 sentences on error handling: failed extractions should go to a dead-letter queue, feature assembly should distinguish "no extractions found" from "extraction never attempted," and a monitoring alarm should fire when DLQ depth exceeds a threshold. Silent NLP failures create ambiguous gaps indistinguishable from legitimate absence of SDOH mentions.
- **L167** — TODO (TechWriter): Expert review A2 (MEDIUM). Add a recommendation for re-clustering cadence. Common pattern: weekly incremental assignment (new patients to existing centroids) with monthly full re-clustering and equity audit. Note that cadence should be driven by rate of new SDOH data accumulation, not calendar alone.

## architecture — `chapter06.09-architecture.md`

- **L134** — TODO (TechWriter): Expert review S1 (HIGH). Add guidance on geocoding PHI: recommend geocoding at zip+4 level (not full street address) when census-tract precision suffices for ADI/SVI lookup; call Location Service via VPC endpoint; cache geocode results in the feature store to avoid repeated address transmission; include geocoding calls in application-level audit logging.
- **L299** — TODO (TechWriter): Expert review S3 (MEDIUM). Add note that feature_snapshot is derived PHI subject to the same retention and access controls as source data. Consider recommending an S3 URI reference in DynamoDB rather than the full snapshot, to reduce PHI surface in the real-time lookup store.
- **L301** — TODO (TechWriter): Expert review S4 (MEDIUM). Add requirement for application-level audit logging at the care management integration point: each phenotype lookup should log requesting user/system, patient_id, timestamp, and phenotype returned (HIPAA accounting-of-disclosures control).
- **L412** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section between Expected Results and Variations. The "Where it struggles" bullets above cover some of this, but the section should be explicit per template.
