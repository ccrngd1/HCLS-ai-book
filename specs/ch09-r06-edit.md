---
id: ch09-r06-edit
title: "Final Edit: Diabetic Retinopathy Screening"
target_persona: TechEditor
tags: [chapter09, recipe, edit]
depends_on: [ch09-r06-code-review, ch09-r06-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter09.06-diabetic-retinopathy-screening.md]
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
Produce the final edited version of Diabetic Retinopathy Screening.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
