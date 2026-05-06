---
id: ch08-r05-edit
title: "Final Edit: Problem List Extraction"
target_persona: TechEditor
tags: [chapter08, recipe, edit]
depends_on: [ch08-r05-code-review, ch08-r05-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter08.05-problem-list-extraction.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of Problem List Extraction.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
