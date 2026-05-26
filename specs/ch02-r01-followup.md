---
id: ch02-r01-followup
title: "Follow-up: address review findings for ch02-r01"
target_persona: TechWriter
tags: [chapter02, recipe, followup]
depends_on: [ch02-r01-edit]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.01-patient-message-response-drafting.md]
  - type: shell
    name: no-todo-markers-for-tracked-findings
    commands:
      - python -c "import re,sys,pathlib; t=pathlib.Path('chapter02.01-patient-message-response-drafting.md').read_text(encoding='utf-8'); ids=['A1', 'A2', 'A3', 'A4', 'N1', 'S1', 'S2', 'S3', 'S4', 'V2']; missing=[i for i in ids if re.search(r'TODO[^\\n]*'+re.escape(i)+r'\\b', t)]; sys.exit(0 if not missing else (sys.stderr.write('unresolved findings still TODO: '+', '.join(missing)+chr(10)) or 1))"
  - type: persona_review
    name: findings-resolved
    persona: TechExpertReviewer
    pass_condition: >-
      All findings listed in the Instructions section (A1, A2, A3, A4, N1, S1, S2, S3, S4, V2)
      are either resolved in the recipe text or explicitly closed with a
      reasoned non-action note. No new HIGH or MEDIUM findings introduced.
---

## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch02-r01 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter02.01-expert-review.md | Lambda Timeout Not Specified; Default Will Fail |
| A2 | MEDIUM | chapter02.01-expert-review.md | Keyword Intent Classifier Has No Confidence or Ambiguity Handling |
| A3 | MEDIUM | chapter02.01-expert-review.md | Provider Decision Audit Trail Not Modeled |
| A4 | MEDIUM | chapter02.01-expert-review.md | EHR Failure Mode and Circuit Breaker Not Discussed |
| N1 | MEDIUM | chapter02.01-expert-review.md | SQS VPC Endpoint Not Listed |
| S1 | HIGH | chapter02.01-expert-review.md | No Retention Policy or TTL for PHI Drafts in DynamoDB |
| S2 | MEDIUM | chapter02.01-expert-review.md | Provider Review Queue Authorization Not Discussed |
| S3 | MEDIUM | chapter02.01-expert-review.md | SQS DLQ Carries PHI, Encryption Not Explicitly Required |
| S4 | MEDIUM | chapter02.01-expert-review.md | Input-Side Guardrails and Prompt Injection Mitigation Could Be Stronger |
| V2 | MEDIUM | chapter02.01-expert-review.md | Bedrock Guardrails Blog URL Flagged TODO Should Be Resolved |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
