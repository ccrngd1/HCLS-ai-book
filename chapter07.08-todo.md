# Open TODOs: Recipe 7.8: Disease Progression Modeling

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.08-disease-progression-modeling.md`

- **L73** — TODO (TechWriter): Expert review A-5 (MEDIUM). Add a paragraph addressing the eGFR race coefficient issue (2021 CKD-EPI race-free equation) and recommend stratified model evaluation by race, sex, and age group. Reference the NKF/ASN Task Force recommendation. This is both a fairness concern and a data quality concern.

## architecture — `chapter07.08-architecture.md`

- **L95** — TODO (TechWriter): Expert review S-1 (HIGH). FHIR queries below should be scoped to clinically relevant data categories only (specific LOINC codes for eGFR, creatinine, HbA1c, albumin, hemoglobin, potassium; relevant condition categories like renal, cardiovascular, endocrine, metabolic). Querying all patient data violates the Minimum Necessary standard (45 CFR 164.502(b)) and may violate 42 CFR Part 2 if substance abuse records are returned. Add LOINC code filters and a note about consulting your privacy officer regarding consent requirements before assembling longitudinal datasets.
- **L284** — TODO (TechWriter): Expert review A-4 (MEDIUM). Add a note referencing published CKD progression models (e.g., the Kidney Failure Risk Equation by Tangri et al., which achieves C-statistics of 0.84-0.90 for 2-year and 5-year kidney failure prediction). Clarify that the recipe's benchmarks assume a general-purpose model predicting stage progression (a broader outcome than kidney failure specifically), which is inherently harder to discriminate than a binary endpoint.
- **L457** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section between Expected Results and Variations. It should summarize the gaps a production deployment must close (validation governance, causal inference for treatment effects, regulatory review, fairness testing across subgroups, etc.).
