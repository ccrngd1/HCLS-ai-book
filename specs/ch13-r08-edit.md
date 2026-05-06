---
id: ch13-r08-edit
title: "Final Edit: Medical Concept Normalization and Mapping"
target_persona: TechEditor
tags: [chapter13, recipe, edit]
depends_on: [ch13-r08-code-review, ch13-r08-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter13.08-medical-concept-normalization-mapping.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Final version incorporates all HIGH and MEDIUM findings from code review and expert review, has no style guide violations, no em dashes, and is publication-ready.
---

## Objective
Produce the final edited version of the Medical Concept Normalization and Mapping recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
