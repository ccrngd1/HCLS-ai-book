# Open TODOs — Recipe 15.1: Alert Threshold Optimization ⭐

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter15.01-alert-threshold-optimization.md`

- **L74** — TODO (TechWriter): Expert review A1 (HIGH). Offline policy evaluation methodology is mentioned but never described. Add a subsection describing OPE basics: the counterfactual evaluation challenge, doubly robust estimators as a practical starting point, comparison against behavior policy baseline, and validation via short online A/B test before full deployment.

## architecture — `chapter15.01-architecture.md`

- **L50** — TODO (TechWriter): Expert review A2 (MEDIUM). Expand on the DLQ pattern: failed reward calculation events go to SQS for reprocessing. Systematic reward calculation failures (e.g., EHR API down for hours) should pause online learning to avoid training on biased reward signals.
