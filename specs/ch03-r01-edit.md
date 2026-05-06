---
id: ch03-r01-edit
title: "Final Edit: Duplicate Claim Detection"
target_persona: TechEditor
tags: [chapter03, recipe, edit]
depends_on: [ch03-r01-code-review, ch03-r01-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.01-duplicate-claim-detection.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Duplicate Claim Detection.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
