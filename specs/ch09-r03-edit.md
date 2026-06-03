---
id: ch09-r03-edit
title: 'Final Edit: Wound Photography Measurement'
target_persona: TechEditor
tags:
- chapter09
- recipe
- edit
depends_on:
- ch09-r03-code-review
- ch09-r03-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter09.03-wound-photography-measurement.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter09.03-wound-photography-measurement.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Wound Photography Measurement.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
