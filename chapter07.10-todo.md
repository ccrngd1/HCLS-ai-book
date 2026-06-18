# Open TODOs — Recipe 7.10: Optimal Intervention Timing Prediction

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.10-optimal-intervention-timing-prediction.md`

- **L96** — TODO (TechWriter): Expert review SEC-1 (HIGH). Add data minimization guidance for the delivery layer: (1) row-level access control so care managers see only their assigned patients; (2) consider coded explanations with deep links to the patient chart rather than embedding full clinical detail in the worklist; (3) if full clinical detail is included, the care management platform must meet the same encryption and access logging requirements as the EHR.

## architecture — `chapter07.10-architecture.md`

- **L11** — TODO (TechWriter): Expert review ARC-1 (HIGH). Add model monitoring/drift detection to the architecture: SageMaker Model Monitor for feature distribution tracking, periodic recalibration job comparing predicted vs. observed event rates, CloudWatch alarm when C-index drops below 0.65, and a model health dashboard showing calibration curves over time.
- **L21** — TODO (TechWriter): Expert review ARC-2 (HIGH). Explicitly describe DynamoDB TTL on the expires_at field to auto-delete stale recommendations, a DynamoDB Streams trigger on TTL deletions to log "expired without action" events for model feedback, and re-scoring logic that runs when a recommendation expires to determine if a new window has opened or the risk has resolved.
- **L496** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add content covering gaps a production deployment must close (model monitoring, A/B holdout ethics, integration testing with EHR, etc.).
