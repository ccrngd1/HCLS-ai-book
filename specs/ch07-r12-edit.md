---
id: ch07-r12-edit
title: 'Final Edit: Cohort Matching and Case-Based Reasoning for Novel Claims'
target_persona: TechEditor
tags:
- chapter07
- recipe
- edit
depends_on:
- ch07-r12-code-review
- ch07-r12-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.12-claim-cohort-matching.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter07.12-claim-cohort-matching.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Cohort Matching and Case-Based Reasoning
for Novel Claims.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency
with book style, technical accuracy, and completeness. Produce the final
publishable version.
