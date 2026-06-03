---
id: ch07-r05-edit
title: 'Final Edit: 30-Day Readmission Risk'
target_persona: TechEditor
tags:
- chapter07
- recipe
- edit
depends_on:
- ch07-r05-code-review
- ch07-r05-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.05-30-day-readmission-risk.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter07.05-30-day-readmission-risk.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of 30-Day Readmission Risk.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
