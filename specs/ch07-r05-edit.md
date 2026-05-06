---
id: ch07-r05-edit
title: "Final Edit: 30-Day Readmission Risk"
target_persona: TechEditor
tags: [chapter07, recipe, edit]
depends_on: [ch07-r05-code-review, ch07-r05-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter07.05-30-day-readmission-risk.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of 30-Day Readmission Risk.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
