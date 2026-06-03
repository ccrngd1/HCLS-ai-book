---
id: ch02-r01-edit
title: 'Final Edit: Patient Message Response Drafting'
target_persona: TechEditor
tags:
- chapter02
- recipe
- edit
depends_on:
- ch02-r01-code-review
- ch02-r01-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.01-patient-message-response-drafting.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter02.01-patient-message-response-drafting.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Patient Message Response Drafting.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
