---
id: ch09-r01-edit
title: "Final Edit: Image Quality Assessment"
target_persona: TechEditor
tags: [chapter09, recipe, edit]
depends_on: [ch09-r01-code-review, ch09-r01-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter09.01-image-quality-assessment.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Image Quality Assessment.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
