---
id: ch02-r09-followup
title: 'Follow-up: address review findings for ch02-r09'
target_persona: TechWriter
tags:
- chapter02
- recipe
- followup
depends_on:
- ch02-r09-edit
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.09-clinical-decision-support-synthesis.md
- type: shell
  name: no-todo-markers-for-tracked-findings
  commands:
  - 'python3 -c "import re,sys,pathlib; t=pathlib.Path(''chapter02.09-clinical-decision-support-synthesis.md'').read_text(encoding=''utf-8'');
    ids=[''A1'', ''A2'', ''A3'', ''S1'', ''S2'']; missing=[i for i in ids if re.search(r''TODO[^\\n]*''+re.escape(i)+r''\\b'',
    t)]; sys.exit(0 if not missing else (sys.stderr.write(''unresolved findings still
    TODO: ''+'', ''.join(missing)+chr(10)) or 1))"

    '
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter02.09-clinical-decision-support-synthesis.md
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: All findings listed in the Instructions section (A1, A2, A3, S1,
    S2) are either resolved in the recipe text or explicitly closed with a reasoned
    non-action note. No new HIGH or MEDIUM findings introduced.
---


## Objective
Address the HIGH and MEDIUM findings flagged in code review and expert
review for ch02-r09 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter02.09-expert-review.md | Architecture diagram's validation-retry branch loops back to generation with no retry cap and no exit to human review; pseudocode Step 9's `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` terminal state is not modeled in the orchestration walkthrough; Python companion (per code review Finding 1) implements the gap as auto-delivery of `REVIEW_REQUIRED` with `status = DELIVERED`. Same pattern as Recipe 2.6, 2.7, 2.10 expert reviews; fix template in Recipe 2.8. Highest stakes for a CDS recipe because the validator catches `safety_finding_not_represented`, `contradicts_contraindication`, `contradicts_allergy`, `dose_not_in_structured_source`, `directive_language_in_model_voice`, and `out_of_scope` failures, all of which would ship to the clinician UI as a successful delivery without the fix. |
| A2 | MEDIUM | chapter02.09-expert-review.md | Synthesis ID generated per invocation rather than deterministically from event key; EventBridge at-least-once delivery can produce duplicate synthesis runs with different synthesis_ids, bypassing scope-gate suppression if the duplicate arrives before the first run completes. Same recurring Chapter 2 trigger-idempotency pattern (2.4 through 2.10 expert reviews all raised the same class). Sixth consecutive Chapter 2 finding in this class. |
| A3 | MEDIUM | chapter02.09-expert-review.md | Bedrock model IDs in pseudocode use literal string values that are not valid Bedrock identifiers (real format includes a date and version suffix). Recipe 2.10's review explicitly named placeholder-with-comment (`SYNTHESIS_MODEL_ID // e.g., Claude Sonnet`) as the chapter template; Recipe 2.9 predates that convention. A reader copying these strings into a real implementation gets `ResourceNotFoundException` or `ValidationException`. |
| S1 | MEDIUM | chapter02.09-expert-review.md | Patient context (including potential MRN, DOB, name, address, phone, NPIs from FHIR resources) and full retrieval set serialized into the synthesis prompt without minimum-necessary scoping; Bedrock under BAA is compliant, but minimum-necessary applies inside the BAA boundary, and unnecessary identifiers expand the model-invocation-logging PHI surface. Same class as Recipe 2.7 S1, Recipe 2.8 S1, Recipe 2.10 S1. Fourth Chapter 2 recipe with this finding; chapter appendix candidate. |
| S2 | MEDIUM | chapter02.09-expert-review.md | Input-side prompt-attack filters referenced in prose but policy-level Guardrail configuration prerequisite not explicitly bound to the InvokeModel call; retrieved guideline chunks, institutional protocols, drug-database records, and patient note content are untrusted-input surfaces. Same class as Recipe 2.7 S2, Recipe 2.8 S2, Recipe 2.10 S2. Fourth Chapter 2 recipe with this finding; chapter appendix candidate. |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
