---
id: ch05-r02-edit
title: "Final Edit: Provider NPI Matching"
target_persona: TechEditor
tags: [chapter05, recipe, edit]
depends_on: [ch05-r02-code-review, ch05-r02-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter05.02-provider-npi-matching.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Provider NPI Matching.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
