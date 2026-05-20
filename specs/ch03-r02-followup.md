---
id: ch03-r02-followup
title: "Follow-up: address review findings for ch03-r02"
target_persona: TechWriter
tags: [chapter03, recipe, followup]
depends_on: [ch03-r02-edit]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.02-patient-no-show-pattern-detection.md]
  - type: shell
    name: no-todo-markers-for-tracked-findings
    commands:
      - python -c "import re,sys,pathlib; t=pathlib.Path('chapter03.02-patient-no-show-pattern-detection.md').read_text(encoding='utf-8'); ids=['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'S1', 'S2']; missing=[i for i in ids if re.search(r'TODO[^\\n]*'+re.escape(i)+r'\\b', t)]; sys.exit(0 if not missing else (sys.stderr.write('unresolved findings still TODO: '+', '.join(missing)+chr(10)) or 1))"
  - type: persona_review
    name: findings-resolved
    persona: TechExpertReviewer
    pass_condition: >-
      All findings listed in the Instructions section (A1, A2, A3, A4, A5, A6, S1, S2)
      are either resolved in the recipe text or explicitly closed with a
      reasoned non-action note. No new HIGH or MEDIUM findings introduced.
---

## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch03-r02 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter03.02-expert-review.md | The same selection-bias problem the recipe correctly addresses for the model retrain (`intervention_count = 0` exclusion) is missed for the patient baseline updates. Successfully intervened high-risk patients see their baselines collapse over months of operation toward the intervention-adjusted rate, degrading the deviation calculation that is the recipe's central design hypothesis. The "investigate" queue progressively loses the signal it is supposed to surface (reliable patients with anomalously elevated risk for a specific appointment). Fix: gate the baseline update on intervention status; only update the baseline when no intervention was applied; track intervened-observation count separately for analysis. |
| A2 | HIGH | chapter03.02-expert-review.md | Bayesian smoothing with a Beta-distribution prior is recommended in prose ("a Beta distribution with a population-derived prior is the usual tool; you get a baseline for every patient including brand-new ones") but not implemented in the pseudocode (which initializes to zero and uses naive EMA). The cold-start fallback in Step 3 references `MIN_BASELINE_OBSERVATIONS` as a threshold but the constant is never defined. Reader is told "Bayesian smoothing handles cold start" and then sees a hard cutoff with an undefined constant. Fix: define `MIN_BASELINE_OBSERVATIONS` (default ~8 with motivation); replace `empty_baseline()` with Bayesian-prior initialization using cohort-derived (or population) Beta prior with effective sample size ~10. |
| A3 | MEDIUM | chapter03.02-expert-review.md | EventBridge → Lambda async is at-least-once; pseudocode has no idempotency guard. A redelivered outcome event writes a duplicate label row, updates the patient baseline twice (compounding the moving-average update), and double-emits CloudWatch metrics. Same recurring trigger-idempotency pattern as Recipes 2.4-2.10 and 3.1, with a new surface (EventBridge bus → Lambda with both label-write and baseline-update being non-idempotent). Fix: deterministic event-key derivation (`appointment_id + outcome`); conditional DynamoDB write to `processed-outcomes` table before label and baseline operations. Strongly recommend a chapter-wide trigger-idempotency appendix. |
| A4 | MEDIUM | chapter03.02-expert-review.md | No Dead Letter Queue or `OnFailure` destination configured for the outcome-joiner, routing, or deviation-calc Lambdas. Lambda's default async retry behavior (two retries, then drop) silently loses outcome events that exhaust retries; the retraining pipeline runs a month later on a training set missing some of the highest-signal outcome data. Fix: add `outcome-joiner-dlq`, `routing-lambda-dlq`, `deviation-calc-dlq` SQS queues with `OnFailure` destinations configured; add a one-line Prerequisites note tying DLQ discipline to the recipe's existing label-retention discussion. |
| A5 | MEDIUM | chapter03.02-expert-review.md | Patient-stratified split prevents same-patient leakage but does not prevent temporal leakage. Recipe's prose elsewhere identifies seasonality as a failure mode ("If the training window doesn't include the current seasonal pattern, the model underperforms"), but the validation strategy doesn't enforce a time-based discipline. A model deployed from this pipeline can have undetected seasonal overfitting. Fix: time-based split first (validation = most recent 30 days), patient-stratified within each side. |
| A6 | MEDIUM | chapter03.02-expert-review.md | Sample output presents per-feature contributions as additive in probability space, summing to the predicted probability. This is technically incorrect for both modeling approaches the recipe recommends: logistic regression decomposes additively in log-odds space (not probability), and SHAP for tree models also decomposes in raw-score (log-odds) space. A non-ML reader who copies this format teaches operational stakeholders something false about how the model produces its score. Fix: reframe as `feature_importance` (normalized to sum to 1.0) or as `feature_log_odds_contributions` with explanatory comment. |
| S1 | MEDIUM | chapter03.02-expert-review.md | Recipe's PHI-minimization guidance for Pinpoint (appointment time, location, provider name) is correct for most appointments but misses high-stigma specialty disclosure: for behavioral health, addiction medicine, OB/GYN, infectious disease/sexual health, oncology clinics, the clinic name itself is a diagnostic disclosure. SMS messages traverse carrier networks, are visible on lock screens, can show in shared family-plan billing logs. Same minimum-necessary pattern as Recipes 2.7-2.10 S1 and Recipe 3.1 S1, with a new surface (patient-facing message content). Fix: add a paragraph to the "PHI handling in the outreach messages" subsection addressing high-stigma specialty disclosure; recommend per-clinic "reminder content sensitivity" flag in patient preference store; gate message-template selection on it. |
| S2 | MEDIUM | chapter03.02-expert-review.md | Recipe correctly identifies that subgroup performance evaluation requires access to protected-characteristic data and defers "what data is captured" to the health equity team, but the architectural artifacts that make subgroup monitoring binding are not specified: where data lives, who has read access, how it joins to predictions, audit trail for subgroup queries, IAM scope for the training job role's read access to demographic attributes. Race/ethnicity data has different governance from PHI in some regulatory regimes. Fix: add a Subgroup data access row to Prerequisites; restrict read access to demographic store to training-job role and dashboard role; CloudTrail data events on subgroup queries; QuickSight queries against an aggregated subgroup-metrics table rather than the raw demographic-joined prediction archive. |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
