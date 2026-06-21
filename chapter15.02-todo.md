# Open TODOs: Recipe 15.2: Notification Timing Optimization

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter15.02-notification-timing-optimization.md`

- **L108** — TODO (TechWriter): Expert review ARCH-1 (HIGH). Add offline policy evaluation (OPE) subsection here: cover doubly-robust estimation for deterministic historical policies, coverage limitations, confidence intervals, and deployment gates (only deploy if OPE estimate exceeds baseline by a statistically significant margin).

## architecture — `chapter15.02-architecture.md`

- **L17** — TODO (TechWriter): Expert review SEC-1 (HIGH). Add guidance on PHI behavioral profiling: (1) Scope DynamoDB read access to the timing engine Lambda role only via IAM resource conditions. (2) Define explicit TTL of 90-180 days on engagement history items. (3) Note that behavioral engagement profiles derived from health communications may constitute PHI under HIPAA and should be included in the facility's Notice of Privacy Practices. (4) Implement a patient profile deletion endpoint for right-of-access requests.
- **L23** — TODO (TechWriter): Expert review ARCH-2 (HIGH). Address EventBridge Scheduler silent failure mode: (1) Add a time validation check ensuring the selected slot is in the future with a minimum 2-minute buffer; if not, send immediately. (2) SQS message deletion should happen after schedule creation confirmation, not after the timing decision. Use SQS visibility timeout extension during processing and only delete after CreateSchedule returns success. (3) Add a DLQ on the SQS queue for messages that fail scheduling after retries.
- **L356** — TODO: Verify if there are healthcare-specific Personalize or Pinpoint sample repos on aws-samples
