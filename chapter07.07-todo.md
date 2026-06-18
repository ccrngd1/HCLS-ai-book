# Open TODOs — Recipe 7.7: Length of Stay Prediction

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.07-length-of-stay-prediction.md`

- **L95** — TODO (TechWriter): Expert review A1 (HIGH). Add "Fairness and Equity Considerations" subsection here. LOS predictions drive resource allocation; must discuss disparate impact across demographic groups, insurance type as a protected-class proxy, and demographic-stratified evaluation metrics. See expert review for full suggested content.

## architecture — `chapter07.07-architecture.md`

- **L13** — TODO (TechWriter): Expert review S3 (MEDIUM). Add brief note on model artifact security: KMS encryption for model artifacts in S3, access control on Model Registry (restrict CreateModel/CreateEndpoint to deployment pipeline role), and model approval gate (PendingManualApproval status) before serving live predictions.
- **L54** — TODO (TechWriter): Expert review S1 (HIGH). Replace wildcard IAM permissions with role-specific, action-specific permissions per pipeline component (training role, inference role, feature engineering role, Lambda trigger role). Current sagemaker:* and healthlake:* violate least privilege.
- **L248** — TODO (TechWriter): Expert review A2 (MEDIUM). Clarify multi-model endpoint pattern: separate endpoints per service line vs. SageMaker Multi-Model Endpoints (lower cost, ~50ms model-loading overhead). Update cost estimate to reflect multiple service lines.
- **L408** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add section covering gaps (error handling, model governance, integration testing, social-feature coverage, etc.) without duplicating The Honest Take from the main recipe.
