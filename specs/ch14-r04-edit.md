---
id: ch14-r04-edit
title: "Final Edit: Nurse Staffing Optimization"
target_persona: TechEditor
tags: [chapter14, recipe, edit]
depends_on: [ch14-r04-code-review, ch14-r04-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter14.04-nurse-staffing-optimization.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of the Nurse Staffing Optimization recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
