---
id: ch08-r02-edit
title: 'Final Edit: Patient Sentiment Analysis'
target_persona: TechEditor
tags:
- chapter08
- recipe
- edit
depends_on:
- ch08-r02-code-review
- ch08-r02-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter08.02-patient-sentiment-analysis.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter08.02-patient-sentiment-analysis.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Patient Sentiment Analysis.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
