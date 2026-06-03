---
id: ch06-r04-edit
title: 'Final Edit: Disease Severity Stratification'
target_persona: TechEditor
tags:
- chapter06
- recipe
- edit
depends_on:
- ch06-r04-code-review
- ch06-r04-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter06.04-disease-severity-stratification.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter06.04-disease-severity-stratification.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Disease Severity Stratification.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
