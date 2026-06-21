# Open TODOs: Recipe 6.8: Disease Subtype Discovery

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter06.08-disease-subtype-discovery.md`

- **L21** — TODO (TechWriter): Expert review A2 (HIGH). Add paragraph on IRB/ethics review requirements: research vs. QI classification, IRB timeline (4-12 weeks), and implication for the "Basic" implementation estimate. Disease subtype discovery using patient data typically requires IRB review before accessing real patient data.

## architecture — `chapter06.08-architecture.md`

- **L13** — TODO (TechWriter): Expert review S2 (MEDIUM). Add note on SageMaker notebook hardening for research workloads: recommend SageMaker Studio with domain-level VPC config, disable root access on notebook instances, use lifecycle configurations to restrict pip/conda to approved package mirrors, and enable notebook audit logging. Research workflows with interactive PHI access have higher risk than automated pipelines.
- **L17** — TODO (TechWriter): Expert review S3 (MEDIUM). Add note on data retention: implement S3 lifecycle policies for experiment artifacts (transition to Glacier after retention period, delete after maximum retention). Maintain a manifest of patient IDs per experiment to support HIPAA amendment and accounting-of-disclosures requests.
- **L307** — TODO (TechWriter): Expert review A1 (HIGH). Add subsection or expanded intro before Step 7 addressing the research-to-production transition: (1) prospective validation on a temporal holdout cohort, (2) FDA CDS considerations under 21st Century Cures Act, (3) clinical governance approval workflow, (4) drift monitoring strategy for deployed subtype classifier.
- **L419** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" H2 section between Expected Results and Variations. The "Where it struggles" paragraph above covers some of this, but the RECIPE-GUIDE expects a standalone section addressing production gaps (model governance, drift monitoring, clinical workflow integration, etc.).
