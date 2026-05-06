---
id: ch10-r06-edit
title: "Final Edit: Speech-to-Text for Telehealth Documentation"
target_persona: TechEditor
tags: [chapter10, recipe, edit]
depends_on: [ch10-r06-code-review, ch10-r06-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter10.06-speech-to-text-telehealth-documentation.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Perform final edit for recipe 10.6 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
