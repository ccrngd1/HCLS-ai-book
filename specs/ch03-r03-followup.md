---
id: ch03-r03-followup
title: "Follow-up: address review findings for ch03-r03"
target_persona: TechWriter
tags: [chapter03, recipe, followup]
depends_on: [ch03-r03-edit]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.03-billing-code-anomalies.md]
  - type: shell
    name: no-todo-markers-for-tracked-findings
    commands:
      - python -c "import re,sys,pathlib; t=pathlib.Path('chapter03.03-billing-code-anomalies.md').read_text(encoding='utf-8'); ids=['A1', 'A2', 'A3', 'A4', 'A5', 'S1', 'S2']; missing=[i for i in ids if re.search(r'TODO[^\\n]*'+re.escape(i)+r'\\b', t)]; sys.exit(0 if not missing else (sys.stderr.write('unresolved findings still TODO: '+', '.join(missing)+chr(10)) or 1))"
  - type: persona_review
    name: findings-resolved
    persona: TechExpertReviewer
    pass_condition: >-
      All findings listed in the Instructions section (A1, A2, A3, A4, A5, S1, S2)
      are either resolved in the recipe text or explicitly closed with a
      reasoned non-action note. No new HIGH or MEDIUM findings introduced.
---

## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch03-r03 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter03.03-expert-review.md | The 2021 CMS/AMA E/M documentation overhaul deleted CPT 99201, restructured documentation requirements for 99202-99215, and produced a population-wide distributional shift in the exact direction the recipe presents as canonical upcoding. The recipe addresses payer-specific policy changes but doesn't extend the discipline to industry-wide CMS/AMA changes. The pseudocode's level_1 bucket implicitly treats new-patient level 1 as a stable category; post-2021 it doesn't exist. Fix: split E&M distribution into new-patient (levels 2-5) and established-patient (levels 1-5) buckets; add an industry-wide-coding-change discipline bullet to "Where it Struggles"; add a temporal caveat to the canonical 99213→99214 upcoding example; coordinate with Python companion's `EM_CODES` update. |
| A2 | MEDIUM | chapter03.03-expert-review.md | EventBridge → Lambda async is at-least-once; pseudocode has no idempotency guard. A redelivered outcome event updates the case-registry twice (timestamp inconsistency), writes a duplicate label row to S3 (biases supervised retraining), and double-emits CloudWatch metrics (skews dollar-recovery total). Same recurring trigger-idempotency pattern as Recipes 2.4-2.10, 3.1, 3.2. Fix: deterministic event-key derivation (`case_id + disposition`); conditional DynamoDB write to `processed-outcomes` table before case update and label write. Strongly recommend cookbook-wide trigger-idempotency appendix. |
| A3 | MEDIUM | chapter03.03-expert-review.md | Pseudocode call implies a clean SHAP application that doesn't exist for Isolation Forest. SHAP's TreeExplainer doesn't directly apply (IF's prediction is path-length-based, not leaf-level). KernelSHAP works but is too slow at this volume; production patterns use path-length attribution or feature-deviation proxies. The Python companion uses the right proxy approach; the pseudocode misrepresents it. Fix: replace pseudocode call with proxy-attribution pattern matching the Python companion; expand prose to acknowledge the SHAP-IF complexity. |
| A4 | MEDIUM | chapter03.03-expert-review.md | No Dead Letter Queue or `OnFailure` destination configured for case-assembly Lambda, scoring Processing job, or outcome-joiner Lambda. Failed events silently disappear after Lambda's default 2-retry-then-drop behavior; signal payloads orphan in S3, outcome data is lost from the supervised retraining pipeline. Fix: add `case-assembly-dlq`, `outcome-joiner-dlq`, and `scoring-job-dlq` SQS queues with `OnFailure` destinations configured; CloudWatch alarms on DLQ depth. |
| A5 | MEDIUM | chapter03.03-expert-review.md | Prose-vs-pseudocode asymmetry: the recipe correctly identifies case-lineage as production-critical but the walkthrough generates a fresh case every period for any flagged provider, producing the analyst-noise pattern the prose warns against. Fix: either add Step 4.5 demonstrating the case-lineage lookup (preferred) or add a one-line comment in Step 4 naming the simplification and pointing at the production discipline. |
| S1 | MEDIUM | chapter03.03-expert-review.md | Pseudocode's SNS message includes `provider_id`, `severity`, `routing`, and `exposure` (in addition to `case_id`). Provider IDs are PHI-adjacent in combination with date ranges and patient population; dollar exposure values traverse SNS infrastructure and downstream subscribers. Recipe 3.1 settled the chapter discipline as "case-id only; analyst UI fetches the full record by id." Recipe 3.3 doesn't follow that convention. Fix: update pseudocode to publish only `case_id` and a coarse routing tier; add a one-line note to Why-These-Services for SNS naming this convention. |
| S2 | MEDIUM | chapter03.03-expert-review.md | Recipe correctly identifies that subgroup performance evaluation requires access to provider-level attributes and defers "what data is captured" to operations, but the architectural artifacts that make subgroup monitoring binding are not specified: data store location, access scope, audit trail for subgroup queries, IAM scope for the training job role's read access. Same finding shape as Recipe 3.2 S2. Fix: add Subgroup Data Access row to Prerequisites; restrict read access to training-job role and dashboard role; CloudTrail data events on subgroup queries; QuickSight queries against aggregated subgroup-metrics table. |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
