---
id: ch11-r05-edit
title: "Final Edit: Insurance Benefits Navigator"
target_persona: TechEditor
tags: [chapter11, recipe, edit]
depends_on: [ch11-r05-code-review, ch11-r05-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter11.05-insurance-benefits-navigator.md]
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
Perform final edit for recipe 11.5 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
