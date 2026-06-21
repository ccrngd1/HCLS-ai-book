# Open TODOs: Recipe 15.7: Chronic Disease Treatment Personalization

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter15.07-architecture.md`

- **L230** — TODO (TechWriter): Expert review finding 3 (HIGH). The Python companion's evaluate_policy_offline docstring claims "weighted importance sampling" but the implementation only computes concordance metrics (agreement rate and average treatment levels). Either add actual importance sampling to the pseudocode here, or clarify that this is concordance-based evaluation with a note that full OPE would use IS/DR estimators. The current pseudocode below uses concordance metrics, which matches the Python implementation.
- **L410** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add production gap analysis (model validation, regulatory pathway, clinician trust, prospective trial requirements).
