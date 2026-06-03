---
id: ch12-r05-edit
title: 'Final Edit: Hospital Census Forecasting'
target_persona: TechEditor
tags:
- chapter12
- recipe
- edit
depends_on:
- ch12-r05-code-review
- ch12-r05-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter12.05-hospital-census-forecasting.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter12.05-hospital-census-forecasting.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 12.5 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
