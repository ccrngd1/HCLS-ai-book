---
id: ch09-r01-edit
title: 'Final Edit: Image Quality Assessment'
target_persona: TechEditor
tags:
- chapter09
- recipe
- edit
depends_on:
- ch09-r01-code-review
- ch09-r01-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter09.01-image-quality-assessment.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter09.01-image-quality-assessment.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Image Quality Assessment.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
