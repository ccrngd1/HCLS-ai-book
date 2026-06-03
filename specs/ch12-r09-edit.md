---
id: ch12-r09-edit
title: 'Final Edit: Epidemic Forecasting'
target_persona: TechEditor
tags:
- chapter12
- recipe
- edit
depends_on:
- ch12-r09-code-review
- ch12-r09-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter12.09-epidemic-forecasting.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter12.09-epidemic-forecasting.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 12.9 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
