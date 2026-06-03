---
id: ch06-r06-edit
title: 'Final Edit: Patient Similarity for Care Planning'
target_persona: TechEditor
tags:
- chapter06
- recipe
- edit
depends_on:
- ch06-r06-code-review
- ch06-r06-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter06.06-patient-similarity-care-planning.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter06.06-patient-similarity-care-planning.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Patient Similarity for Care Planning.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
