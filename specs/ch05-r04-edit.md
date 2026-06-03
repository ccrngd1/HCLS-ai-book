---
id: ch05-r04-edit
title: 'Final Edit: Insurance Eligibility Matching'
target_persona: TechEditor
tags:
- chapter05
- recipe
- edit
depends_on:
- ch05-r04-code-review
- ch05-r04-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.04-insurance-eligibility-matching.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter05.04-insurance-eligibility-matching.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Insurance Eligibility Matching.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
