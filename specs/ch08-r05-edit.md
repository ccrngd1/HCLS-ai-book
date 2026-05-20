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
      No style guide violations, no em dashes, correct header hierarchy,
      all code blocks have language tags, voice consistent with
      STYLE-GUIDE.md. HIGH/MEDIUM technical findings from reviews are
      either incorporated or explicitly flagged as TODO markers for the
      TechWriter.
---

## Objective
Produce the final edited version of Problem List Extraction.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, technical accuracy, and completeness. Produce the final publishable version.
