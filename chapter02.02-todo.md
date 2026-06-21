# Open TODOs: Recipe 2.2: Medical Terminology Simplification

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter02.02-medical-terminology-simplification.md`

- **L145** — TODO (TechWriter): Expert review A4 (MEDIUM). If a retry loop is added to the pseudocode, update the cost and latency estimates to account for the extra Bedrock calls on the failing segments.
- **L159** — TODO (TechWriter): Expert review V3 (LOW). Verify recipe number against final chapter 8 index in book-wide cross-reference sweep.

## architecture — `chapter02.02-architecture.md`

- **L80** — TODO (TechWriter): Expert review A5 (MEDIUM). Add an explicit cache-lookup step (Step 0) before Step 1 that computes `cache_key = hash(original_text + "|" + target_grade)` and short-circuits to a cached result if present. The cost discussion, Expected Results cache-hit-rate benchmark, and "Why These Services" narrative all assume this step exists, but the pseudocode currently starts at Step 1 and never consults the cache. A reader implementing the walkthrough as written will get zero cache hits.
- **L413** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add it to match the companion file spec.

## python-example — `chapter02.02-python-example.md`

- **L414** — TODO (TechWriter): Main recipe pseudocode shows `validate_output(simplified_segment, original_segment, must_preserve, target_grade)` with an `original_segment` parameter that isn't referenced in the pseudocode body. The Python companion drops it. Either add the unused parameter for strict pseudocode parity, or drop it from the main recipe to match this implementation.
- **L749** — TODO (TechWriter): The expert review of the main recipe flagged KMS VPC endpoint as missing. Added here for parity. Confirm that the main recipe's Prerequisites table VPC row includes KMS as well, since both documents should give the same production guidance.
