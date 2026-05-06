---
id: ch02-r06-edit
title: "Final Edit: Clinical Note Summarization"
target_persona: TechEditor
tags: [chapter02, recipe, edit]
depends_on: [ch02-r06-code-review, ch02-r06-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.06-clinical-note-summarization.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Clinical Note Summarization.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
