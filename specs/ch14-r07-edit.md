---
id: ch14-r07-edit
title: "Final Edit: OR Case Sequencing"
target_persona: TechEditor
tags: [chapter14, recipe, edit]
depends_on: [ch14-r07-code-review, ch14-r07-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter14.07-or-case-sequencing.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of the OR Case Sequencing recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
