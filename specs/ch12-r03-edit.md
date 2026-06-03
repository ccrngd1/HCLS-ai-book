---
id: ch12-r03-edit
title: 'Final Edit: ED Arrival Forecasting'
target_persona: TechEditor
tags:
- chapter12
- recipe
- edit
depends_on:
- ch12-r03-code-review
- ch12-r03-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter12.03-ed-arrival-forecasting.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter12.03-ed-arrival-forecasting.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 12.3 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
