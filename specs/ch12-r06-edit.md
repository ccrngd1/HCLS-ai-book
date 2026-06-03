---
id: ch12-r06-edit
title: 'Final Edit: Revenue Cycle Cash Flow Forecasting'
target_persona: TechEditor
tags:
- chapter12
- recipe
- edit
depends_on:
- ch12-r06-code-review
- ch12-r06-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter12.06-revenue-cycle-cash-flow-forecasting.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter12.06-revenue-cycle-cash-flow-forecasting.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 12.6 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
