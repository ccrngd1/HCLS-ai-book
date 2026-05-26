---
id: ch02-r07-followup
title: "Follow-up: address review findings for ch02-r07"
target_persona: TechWriter
tags: [chapter02, recipe, followup]
depends_on: [ch02-r07-edit]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.07-literature-search-evidence-synthesis.md]
  - type: shell
    name: no-todo-markers-for-tracked-findings
    commands:
      - python -c "import re,sys,pathlib; t=pathlib.Path('chapter02.07-literature-search-evidence-synthesis.md').read_text(encoding='utf-8'); ids=['A1', 'A2', 'A3', 'A4', 'A5', 'S1', 'S2']; missing=[i for i in ids if re.search(r'TODO[^\\n]*'+re.escape(i)+r'\\b', t)]; sys.exit(0 if not missing else (sys.stderr.write('unresolved findings still TODO: '+', '.join(missing)+chr(10)) or 1))"
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
review for ch02-r07 that the TechEditor pass left as TODO markers.

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
| A1 | HIGH | chapter02.07-expert-review.md | Source tier applied as a hard filter; for questions where only observational evidence exists, pipeline excludes it entirely and produces "insufficient evidence" where evidence is available. Recipe's own teaching says "tag and weight," not "filter and drop" |
| A2 | HIGH | chapter02.07-expert-review.md | Corpus-ingestion pipeline has no idempotency guard; duplicate EventBridge deliveries drive duplicate Step Functions runs, duplicate embedding cost ($200-$2,000 per rebuild), and duplicate OpenSearch chunks |
| A3 | MEDIUM | chapter02.07-expert-review.md | Diagram shows infinite retry loop; pseudocode correctly routes to `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` but diagram lacks the exit node |
| A4 | MEDIUM | chapter02.07-expert-review.md | Sign/direction validation identified as "catastrophic" in prose but not implemented; verbatim-numeric check passes for "20% increase" vs "20% reduction"; semantic-similarity at 0.65 likely also passes |
| A5 | MEDIUM | chapter02.07-expert-review.md | Fake Bedrock model IDs (`anthropic.claude-haiku-4`, `anthropic.claude-sonnet-4`, `amazon.titan-embed-text-v2`); copy-paste fails Bedrock validation; Python companion uses correct versioned IDs so the two files disagree |
| S1 | MEDIUM | chapter02.07-expert-review.md | `patient_context` passed to Comprehend Medical and to Bedrock generation without minimum-necessary scoping; MRN, DOB, address, payer IDs not needed for literature synthesis |
| S2 | MEDIUM | chapter02.07-expert-review.md | Retrieved chunks are an input-side prompt-injection surface; Guardrails input-side prompt-attack filters not discussed alongside the output-side grounding check |

## Notes
This task was generated automatically from the expert and code review
files listed above. If you believe a finding is mis-tagged or should be
deferred to a later task, mark it `<!-- deferred: <finding_id>: <task_id>
-->` in the recipe and create the deferred task explicitly.
