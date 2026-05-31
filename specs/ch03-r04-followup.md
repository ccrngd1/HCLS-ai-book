---
id: ch03-r04-followup
title: "Follow-up: address review findings for ch03-r04"
target_persona: TechWriter
tags: [chapter03, recipe, followup]
depends_on: [ch03-r04-edit]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.04-medication-dispensing-anomalies.md]
  - type: shell
    name: no-todo-markers-for-tracked-findings
    commands:
      - |
        python -c "import re,sys,pathlib; t=pathlib.Path('chapter03.04-medication-dispensing-anomalies.md').read_text(encoding='utf-8'); ids=['A1', 'A2', 'A3', 'A4', 'S1', 'S2', 'S5']; missing=[i for i in ids if re.search(r'TODO[^\\n]*'+re.escape(i)+r'\\b', t)]; sys.exit(0 if not missing else (sys.stderr.write('unresolved findings still TODO: '+', '.join(missing)+chr(10)) or 1))"
  - type: persona_review
    name: findings-resolved
    persona: TechExpertReviewer
    pass_condition: >-
      All findings listed in the Instructions section (A1, A2, A3, A4, S1, S2, S5)
      are either resolved in the recipe text or explicitly closed with a
      reasoned non-action note. No new HIGH or MEDIUM findings introduced.
---

## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch03-r04 that the TechEditor pass left as TODO markers.

## Instructions
This task closes out review findings the editor was not in scope to
fix. Each finding below corresponds to a `TODO (A1)`
marker (or similar) in the recipe; resolve each one by either:

1. Editing the recipe to incorporate the suggested fix, then removing
   the TODO marker, OR
2. If the finding does not apply (for example: the suggested fix is
   architecturally inconsistent with the rest of the chapter), replace
   the TODO marker with a one-line `<!-- closed: <finding_id>: <reason>
   -->` HTML comment explaining why no change was made.

The recipe must continue to satisfy STYLE-GUIDE.md, RECIPE-GUIDE.md,
and the no-em-dashes rule. Do not introduce new HIGH or MEDIUM findings
while addressing these.

### Findings to address

| ID | Severity | Source | Summary |
|----|----------|--------|---------|
| A1 | MEDIUM | chapter03.04-expert-review.md | EventBridge → Lambda async is at-least-once; pseudocode has no idempotency guard. Redelivered events double-count override metrics (which directly drive rule-retirement decisions and can produce missed-future-flags-and-missed-future-ADEs), bias the supervised classifier's training distribution, and corrupt the missed-adverse-event signal that the Honest Take identifies as the most important feedback signal. Same recurring trigger-idempotency pattern as Recipes 2.4-2.10, 3.1, 3.2, 3.3 (tenth consecutive recipe). Fix: deterministic event-key derivation (`anomaly_event_id + response` or `ade_event_id + dispense_id`); conditional DynamoDB write to `processed-feedback-events` table before OpenSearch update, label write, and metric emission. Strongly recommend a cookbook-wide trigger-idempotency appendix. |
| A2 | MEDIUM | chapter03.04-expert-review.md | No Dead Letter Queue or `OnFailure` destination configured for the real-time-anomaly-service, event-normalizer, or feedback-capture Lambdas. For a patient-safety system a dropped real-time event is a dispense without a check, which is precisely the failure mode the entire pipeline is designed to prevent. Lambda's default 2-retry-then-drop silently loses the event with only CloudWatch Logs as evidence. Fix: add `event-normalizer-dlq`, `real-time-anomaly-service-dlq`, `feedback-capture-dlq` SQS queues with `OnFailure` destinations; CloudWatch alarms on DLQ depth (alarm threshold 1 for the real-time path because a single dropped dispense event is a patient-safety event); Prerequisites note covering replay discipline including the time-bound for replayability (events older than the dispense window escalate to clinical-informatics review rather than auto-replay). |
| A3 | MEDIUM | chapter03.04-expert-review.md | The Honest Take section identifies the oncology-protocol context flag as the single highest-value feature-engineering work in the recipe, more valuable than any model improvement. The recipe's pseudocode walkthrough doesn't reflect this: no oncology / palliative-care field in the patient-context cache schema, no protocol-aware suppression in the rule-screen, no source-of-truth or audit-trail discipline for the suppression decisions. A reader who treats the pseudocode as the implementation specification builds the failure mode the Honest Take warns against (chemotherapy-dose-flagged-constantly). Fix: add the architectural specification to the Patient-context-cache subsection (source of truth: EHR care-plan or oncology-specific-EHR feeds, not diagnosis-code inference; granularity: protocol-regimen-level suppression, not patient-level; data flow: cache-attached `active_protocols` and `palliative_care_active` fields; audit trail: suppression-decision logging with end-date and source-data attribution). Update Step 2 and Step 3 pseudocode to reflect. |
| A4 | MEDIUM | chapter03.04-expert-review.md | The "almost always interrupt-severity" comment overstates the appropriate severity tier for cross-reactivity-based allergy alerts. Penicillin-cephalosporin cross-reactivity has been revised down to ~1-2% for first-generation, essentially zero for third- and fourth-generation; carbapenems <1%. Hard-stop interrupt alerts on penicillin-allergic patients receiving third-generation cephalosporins cause beta-lactam over-restriction, a documented patient-safety problem with worse infection outcomes, longer stays, more C. difficile, higher mortality. Recipe risks teaching readers to encode over-restrictive rule libraries. Fix: differentiate direct-allergen-match (interrupt is appropriate) from cross-reactivity (per-pair severity calibration; default to synchronous unless drug-pair and reaction-history specifically warrant interrupt); update prose in Interaction Anomalies subsection to acknowledge cross-reactivity calibration and ASHP/Joint Commission penicillin-allergy de-labeling guidance. |
| S1 | MEDIUM | chapter03.04-expert-review.md | The pseudocode's SNS message construction is not specified explicitly; the Python companion does the right thing (event-id + minimal context only) but the main recipe doesn't state the discipline, so a reader implementing in a different language without reading the Python companion will not know to constrain the payload. SMS/pager/Slack/mobile push notifications are visible on lock screens and in shared logs; for high-stigma drug classes (HIV antiretrovirals, methadone, buprenorphine, gender-affirming hormones, certain psychiatrics) even the drug name is a diagnostic disclosure. Same chapter-3-settled "event-id-only" convention from Recipes 3.1 and 3.3 should be stated explicitly. Fix: update Step 5 pseudocode to publish only event_id, severity, and routing_tier in the SNS payload; for high-stigma drug classes, exclude drug name from the subject line; add Why-These-Services note naming the convention. |
| S2 | MEDIUM | chapter03.04-expert-review.md | Recipe correctly identifies subgroup monitoring as not optional and correctly names the three concerning bias surfaces (training-data underrepresentation, opioid-prescribing racial disparities, override-pattern bias by physician demographics), but the architectural artifacts that make subgroup monitoring binding are not specified: where demographic data lives, who has read access, how it joins to anomaly events and override records, audit trail for subgroup queries, IAM scope for retraining and dashboard roles, and provider-demographic data's separate HR-confidentiality governance. Same finding shape as Recipes 3.2 S2 and 3.3 S2. Fix: add Subgroup data access row to Prerequisites; restrict read access to demographic store to retraining and dashboard roles; CloudTrail data events on subgroup queries; QuickSight queries against an aggregated subgroup-metrics table rather than the raw demographic-joined anomaly archive. |
| S5 | MEDIUM | chapter03.04-expert-review.md | The patient-context-cache and the medication-anomaly-events bus are shared resources accessed by multiple Lambdas; the recipe gives generic least-privilege framing but doesn't break out per-consumer roles. A compromised role with broad cache-write access could silently corrupt patient context (stale weight, wrong eGFR), propagating into wrong dose-per-kg and renal-adjustment decisions. For a patient-safety system the blast-radius minimization is more important than for the financial-stakes recipes. Fix: per-consumer IAM scope examples in Prerequisites IAM row covering the real-time anomaly Lambda (read-only on cache), cache-refresher Lambda (write-only on cache), alert-delivery Lambda (consume events from bus, no produce), feedback-capture Lambda (write-only to label store and feedback bus), diversion-pipeline roles (separate KMS keys, separate Neptune access, separate IAM boundary). |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
