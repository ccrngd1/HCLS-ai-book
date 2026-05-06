---
id: ch03-r07-edit
title: "Final Edit: Patient Deterioration Early Warning"
target_persona: TechEditor
tags: [chapter03, recipe, edit]
depends_on: [ch03-r07-code-review, ch03-r07-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.07-patient-deterioration-early-warning.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Patient Deterioration Early Warning.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
