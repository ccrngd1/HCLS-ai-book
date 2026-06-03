---
id: ch11-r08-edit
title: 'Final Edit: Mental Health Support Bot'
target_persona: TechEditor
tags:
- chapter11
- recipe
- edit
depends_on:
- ch11-r08-code-review
- ch11-r08-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter11.08-mental-health-support-bot.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter11.08-mental-health-support-bot.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 11.8 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
