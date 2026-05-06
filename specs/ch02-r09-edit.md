---
id: ch02-r09-edit
title: "Final Edit: Clinical Decision Support Synthesis"
target_persona: TechEditor
tags: [chapter02, recipe, edit]
depends_on: [ch02-r09-code-review, ch02-r09-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.09-clinical-decision-support-synthesis.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Clinical Decision Support Synthesis.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
