# Open TODOs — Recipe 15.5: Ventilator Weaning Protocols

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter15.05-ventilator-weaning-protocols.md`

- **L130** — TODO (TechWriter): Expert review A2 (MEDIUM). Add model rollback strategy: shadow traffic via SageMaker production variants, agreement rate monitoring between old/new models, defined rollback trigger (e.g., clinician override rate exceeds 50% for 48 hours).
- **L132** — TODO (TechWriter): Expert review A4 (MEDIUM). Add operational monitoring guidance: feature distribution monitoring against training data stats, safety filter override rate tracking, clinician agreement rate over time as proxy for recommendation quality. Alert when features drift beyond 2 standard deviations for sustained periods.
- **L145** — TODO (TechWriter): Add Tags section and Navigation footer per RECIPE-GUIDE.

## architecture — `chapter15.05-architecture.md`

- **L43** — TODO (TechWriter): Expert review A1 (HIGH). Add DLQ/error handling for Kinesis-to-Lambda path. Configure SQS dead-letter queue with bisect-on-error, CloudWatch alarm on DLQ depth, and staleness flagging when state updates exceed 15 minutes. This is a patient safety concern: silent data loss means stale state feeding recommendations.
- **L330** — TODO (TechWriter): RECIPE-GUIDE compliance. Add "Why This Isn't Production-Ready" section between Expected Results and Variations per the recipe structure guide.
- **L352** — TODO (TechWriter): Expert review V2 (LOW). Verify and add full citations for: Komorowski et al. 2018 "The Artificial Intelligence Clinician" (Nature Medicine); Prasad et al. 2017 on RL for mechanical ventilation weaning; Kumar et al. 2020 Conservative Q-Learning. All are real papers but need verified DOI links.
