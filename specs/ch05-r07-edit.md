---
id: ch05-r07-edit
title: "Final Edit: Longitudinal Patient Matching Across Name Changes"
target_persona: TechEditor
tags: [chapter05, recipe, edit]
depends_on: [ch05-r07-code-review, ch05-r07-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter05.07-longitudinal-patient-matching-name-changes.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      No style guide violations, no em dashes, correct header hierarchy,
      all code blocks have language tags, voice consistent with
      STYLE-GUIDE.md. HIGH/MEDIUM technical findings from reviews are
      either incorporated or explicitly flagged as TODO markers for the
      TechWriter.
---

## Objective
Produce the final edited version of Longitudinal Patient Matching Across Name Changes.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
