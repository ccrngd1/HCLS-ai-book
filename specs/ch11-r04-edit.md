---
id: ch11-r04-edit
title: "Final Edit: Pre-Visit Intake Bot"
target_persona: TechEditor
tags: [chapter11, recipe, edit]
depends_on: [ch11-r04-code-review, ch11-r04-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter11.04-pre-visit-intake-bot.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Perform final edit for recipe 11.4 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
