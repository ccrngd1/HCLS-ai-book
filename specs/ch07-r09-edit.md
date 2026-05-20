---
id: ch07-r09-edit
title: "Final Edit: Mortality Risk Scoring ICU"
target_persona: TechEditor
tags: [chapter07, recipe, edit]
depends_on: [ch07-r09-code-review, ch07-r09-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter07.09-mortality-risk-scoring-icu.md]
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
Produce the final edited version of Mortality Risk Scoring ICU.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
