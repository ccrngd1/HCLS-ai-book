---
id: ch11-r07-edit
title: 'Final Edit: Chronic Disease Management Coach'
target_persona: TechEditor
tags:
- chapter11
- recipe
- edit
depends_on:
- ch11-r07-code-review
- ch11-r07-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter11.07-chronic-disease-management-coach.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter11.07-chronic-disease-management-coach.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 11.7 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
