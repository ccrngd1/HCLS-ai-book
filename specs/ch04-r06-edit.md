---
id: ch04-r06-edit
title: "Final Edit: Care Gap Prioritization"
target_persona: TechEditor
tags: [chapter04, recipe, edit]
depends_on: [ch04-r06-code-review, ch04-r06-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter04.06-care-gap-prioritization.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Care Gap Prioritization.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
