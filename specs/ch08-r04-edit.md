---
id: ch08-r04-edit
title: "Final Edit: Medication Extraction and Normalization"
target_persona: TechEditor
tags: [chapter08, recipe, edit]
depends_on: [ch08-r04-code-review, ch08-r04-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter08.04-medication-extraction-normalization.md]
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
Produce the final edited version of Medication Extraction and Normalization.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
