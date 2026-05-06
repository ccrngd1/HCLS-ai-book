---
id: ch04-r09-edit
title: "Final Edit: Personalized Care Plan Generation"
target_persona: TechEditor
tags: [chapter04, recipe, edit]
depends_on: [ch04-r09-code-review, ch04-r09-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter04.09-personalized-care-plan-generation.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Personalized Care Plan Generation.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
