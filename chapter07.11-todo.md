# Open TODOs: Recipe 7.11: Claim Denial and Prior-Auth Determination Prediction

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.11-claim-denial-prediction.md`

- **L127** — TODO (TechWriter): Expert review A-1 (HIGH). Add architectural implementation of counterfactual tracking: store pre-correction feature snapshot alongside corrected claims, tag claims as {intervention: NONE|CORRECTED|ESCALATED}, and document retraining strategy (exclude corrected claims from training, or use pre-correction features with predicted-denial pseudo-labels, or train on corrected features but validate against pre-correction features to monitor signal loss). This should be in the architecture section (step 6 feedback loop), not only here.
- **L135** — TODO (TechWriter): Expert review R-1 (HIGH). Add paragraph covering state gold-carding laws (TX HB 3459, LA, WV, others) and CMS prior-auth reform (CMS-0057-F, effective 2026). Discuss how gold-carding exemptions should suppress PA flags for qualifying provider-service pairs, and how the CMS FHIR API mandate will change the feature landscape for PA prediction models.
- **L137** — TODO (TechWriter): Expert review R-2 (HIGH). Add architectural implementation of fairness monitoring: SageMaker Clarify bias detection job running weekly (DPPL and DI metrics across patient_age_group, coverage_type, place_of_service, procedure category), CloudWatch alarms when subgroup precision/recall diverges >10pp from population average, quarterly fairness report for compliance review. Add these to the architecture diagram and CloudWatch monitoring section.

## architecture — `chapter07.11-architecture.md`

- **L509** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section here per RECIPE-GUIDE. Should cover gaps a production deployment must close (model governance, A/B testing framework, integration testing with billing system, DR/failover for the scoring endpoint, etc.).
