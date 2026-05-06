---
id: ch07-r04-edit
title: "Final Edit: ED Visit Prediction"
target_persona: TechEditor
tags: [chapter07, recipe, edit]
depends_on: [ch07-r04-code-review, ch07-r04-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter07.04-ed-visit-prediction.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of ED Visit Prediction.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
