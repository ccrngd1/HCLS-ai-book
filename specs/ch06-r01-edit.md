---
id: ch06-r01-edit
title: "Final Edit: Geographic Patient Clustering"
target_persona: TechEditor
tags: [chapter06, recipe, edit]
depends_on: [ch06-r01-code-review, ch06-r01-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter06.01-geographic-patient-clustering.md]
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
Produce the final edited version of Geographic Patient Clustering.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
