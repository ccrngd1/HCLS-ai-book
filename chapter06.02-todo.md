# Open TODOs: Recipe 6.2: Utilization Pattern Segmentation ⭐

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter06.02-utilization-pattern-segmentation.md`

- **L154** — TODO (TechWriter): RECIPE-GUIDE specifies "General Architecture Pattern" as an H2 section, not H3 under The Technology. Promote when convenient.

## architecture — `chapter06.02-architecture.md`

- **L435** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add content covering production gaps (monitoring, drift detection, retraining triggers, integration testing).

## python-example — `chapter06.02-python-example.md`

- **L644** — TODO (TechWriter): Code review Issue 1 (WARNING). Python uses StandardScaler while main recipe prescribes log1p + robust scaling. Add a comment in prepare_features() explaining the simplification: "The main recipe recommends log1p + robust scaling for production. We use StandardScaler with clipping here for simplicity; both approaches produce reasonable clusters on this synthetic data."
- **L645** — TODO (TechWriter): Code review Issue 2 (NOTE). Add comment in config or cluster_members(): "In production, evaluate k=4 through k=10 and select based on silhouette + minimum cluster size (see main recipe Step 4). We fix k=5 here because the synthetic data was designed with 5 archetypes."
- **L646** — TODO (TechWriter): Code review Issue 3 (NOTE). Add sentence to Step 2 prose: "With only 8 features, we skip the PCA step described in the main recipe. PCA becomes important when you have 20+ engineered features."
