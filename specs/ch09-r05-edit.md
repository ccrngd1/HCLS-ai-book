---
id: ch09-r05-edit
title: "Final Edit: Chest X-Ray Triage"
target_persona: TechEditor
tags: [chapter09, recipe, edit]
depends_on: [ch09-r05-code-review, ch09-r05-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter09.05-chest-xray-triage.md]
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
Produce the final edited version of Chest X-Ray Triage.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
