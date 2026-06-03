---
id: ch03-r01-followup
title: 'Follow-up: address review findings for ch03-r01'
target_persona: TechWriter
tags:
- chapter03
- recipe
- followup
depends_on:
- ch03-r01-edit
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter03.01-duplicate-claim-detection.md
- type: shell
  name: no-todo-markers-for-tracked-findings
  commands:
  - 'python3 -c "import re,sys,pathlib; t=pathlib.Path(''chapter03.01-duplicate-claim-detection.md'').read_text(encoding=''utf-8'');
    ids=[''A1'', ''A2'', ''A3'', ''A4'', ''A5'', ''S1'']; missing=[i for i in ids
    if re.search(r''TODO[^\\n]*''+re.escape(i)+r''\\b'', t)]; sys.exit(0 if not missing
    else (sys.stderr.write(''unresolved findings still TODO: ''+'', ''.join(missing)+chr(10))
    or 1))"

    '
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter03.01-duplicate-claim-detection.md
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: All findings listed in the Instructions section (A1, A2, A3, A4,
    A5, S1) are either resolved in the recipe text or explicitly closed with a reasoned
    non-action note. No new HIGH or MEDIUM findings introduced.
---


## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch03-r01 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter03.01-expert-review.md | NPIs are issued sequentially by NPPES and do not have hierarchical structure by organization; the first four digits encode roughly when the NPI was issued, not which org it belongs to. The blocking key as written does not catch the multi-NPI-organization case it claims to catch. The recipe's prose elsewhere correctly identifies the right pattern (provider-hierarchy lookup on tax_id), but the pseudocode contradicts it. Fix: drop the NPI prefix and rely on per-field NPI similarity in scoring (Option 1, smallest change), or substitute a tax-id lookup with a forward reference to Recipe 5.1 (Option 2, cleanest pedagogy). |
| A2 | MEDIUM | chapter03.01-expert-review.md | S3 ObjectCreated and asynchronous Lambda fan-out are at-least-once delivery; the pseudocode has no idempotency guard. A redelivered event produces duplicate suspension records, duplicate SQS review-queue messages, and duplicate examiner-queue entries: the duplicate-detection pipeline produces a duplicate of itself. Same recurring Chapter 2 pattern (2.4-2.10 reviews) with a new surface (S3 events + async Lambda invocations rather than EventBridge). Fix: deterministic event-key derivation; conditional DynamoDB writes (`attribute_not_exists`) on both the parser-side `claim-history` write and the detector-side decisions write. Strongly recommend a chapter-wide trigger-idempotency appendix. |
| A3 | MEDIUM | chapter03.01-expert-review.md | OpenSearch appears prominently in three places (diagram, prose, ingredients) and is described as the home of fuzzy field matching. The walkthrough never calls it. Step 3's `_field_similarity` does Levenshtein inline; Step 2's `find_candidates` does the blocking lookup against DynamoDB only. A reader has no idea when OpenSearch runs or for which fields. Fix: demote OpenSearch to Variations and Extensions (Option 1, aligns with what the walkthrough actually does), or add a Step 2.5 demonstrating the OpenSearch call (Option 2, more complete but requires pseudocode and Python-companion updates). |
| A4 | MEDIUM | chapter03.01-expert-review.md | The diagram shows the detector calling a SageMaker endpoint; Step 3's pseudocode hardcodes the rule-based scorer. The Why-These-Services prose says "the rule-based scorer runs inline in Lambda. Once you graduate to a logistic regression or gradient-boosted model, SageMaker is where it lives," which is exactly right, but the diagram doesn't depict the rule-based-inline-vs-SageMaker-endpoint progression. Fix: add a comment block in the architecture diagram noting the SageMaker endpoint replaces the inline scorer once labels accumulate, and add a one-line comment in Step 3 showing the swap. |
| A5 | MEDIUM | chapter03.01-expert-review.md | No DLQ or destination-on-failure configured for the parser Lambda. Lambda's default async retry behavior (two retries, then drop) silently loses malformed-837 processing records; the raw 837 stays in S3 but the operational state of "received but failed to parse" is not captured outside CloudWatch Logs. The recipe's own "Why This Isn't Production-Ready" calls out 837 parsing edge cases as inevitable. Fix: add `parser-dlq` SQS queue with `OnFailure` destination configured; same pattern for detector and label-writer Lambdas. |
| S1 | MEDIUM | chapter03.01-expert-review.md | Examiner free-text reasoning is "PHI-adjacent" per the comment but is written verbatim to DynamoDB and S3 (Parquet) without minimization. Free text from examiners working with patient records open in another tab routinely references identifiers and clinical context. The label store is long-lived (10-year claims retention horizon). Same minimum-necessary-inside-the-BAA pattern as Recipes 2.7-2.10 S1, with a new surface (human input rather than serialized prompt context). Fix: add a regex-or-Comprehend-Medical-based scrub before write; rely on the controlled-vocabulary `reasoning_code` for operational signal. |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
