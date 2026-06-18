# Open TODOs — Recipe 12.7: Vital Sign Trajectory Monitoring

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter12.07-architecture.md`

- **L19** — TODO (TechWriter): Expert review M6 (MEDIUM). Add ADT event listener description: on discharge, immediately delete patient state (don't rely on TTL); on admission, initialize fresh state with baseline_stable=false; on transfer, preserve state but update unit context for alert routing.
- **L25** — TODO (TechWriter): Expert review M7 (MEDIUM). Add note: if alert delivery targets external endpoints (pager vendor API), configure a NAT gateway in a controlled subnet with outbound security group rules limited to vendor IP ranges. Prefer VPC-internal integrations (PrivateLink) to avoid PHI egress to the public internet.
- **L67** — TODO (TechWriter): Expert review H2 (HIGH). Add dead-letter queue (SQS) on both Lambda functions and a side-output on the Flink application for failed events. Add CloudWatch alarms on DLQ depth > 0. In a clinical safety system, a silently dropped reading is a patient safety risk. Add brief prose and update the architecture diagram to include DLQ.
- **L491** — TODO (TechWriter): RECIPE-GUIDE compliance. Missing "Why This Isn't Production-Ready" section between Expected Results and Variations. Add content covering gaps a production deployment must close (e.g., clinical validation study, alarm committee approval, EHR integration certification). Do not duplicate content already in The Honest Take.
