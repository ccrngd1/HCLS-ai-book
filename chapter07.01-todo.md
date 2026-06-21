# Open TODOs: Recipe 7.1: Appointment No-Show Prediction ⭐

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter07.01-architecture.md`

- **L216** — TODO (TechWriter): Expert review A3 (MEDIUM). Add conditional write guidance to prevent overwriting predictions already acted upon. Use condition expression `attribute_not_exists(acted_at)` or append a pipeline_run_id for audit consistency between predictions and actions.
- **L286** — TODO (TechWriter): Expert review A1 (HIGH). Add Step 6: Ground truth collection and model monitoring. Needs a nightly Lambda that joins predictions with actual outcomes after the appointment date, computes rolling AUC, publishes to CloudWatch, and triggers retraining when AUC drops below threshold (e.g., 0.72). Add feedback loop to architecture diagram from scheduling system back to training pipeline.
- **L332** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add section covering gaps a production deployment must close (monitoring, ground truth collection, fairness auditing, etc.).
- **L364** — TODO (TechWriter): Verify all URLs above are current and accessible before publication. Check aws-healthcare-lifescience-ai-ml repo still exists on GitHub.
