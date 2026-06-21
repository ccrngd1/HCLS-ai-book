# Open TODOs: Recipe 14.1: Appointment Slot Optimization

> Auto-extracted 2026-06-18 from inline source comments (1 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter14.01-appointment-slot-optimization.md`

- **L117** — TODO (TechWriter): Expert review A1 (HIGH). Add a dedicated paragraph describing the post-deployment monitoring feedback loop: compare actual throughput, wait times, and overtime against simulation predictions for 1-2 weeks after go-live. If actual performance deviates beyond a threshold (e.g., wait times 50% higher than predicted), alert operations and trigger rollback to the previous template version. Keep vendor-agnostic here; place AWS-specific rollback mechanism (e.g., DynamoDB versioning) in the architecture companion.
