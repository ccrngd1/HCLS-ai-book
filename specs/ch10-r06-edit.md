---
id: ch10-r06-edit
title: "Final Edit: Speech-to-Text for Telehealth Documentation"
target_persona: TechEditor
tags: [chapter10, recipe, edit]
depends_on: [ch10-r06-code-review, ch10-r06-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter10.06-speech-to-text-telehealth-documentation.md]
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
Perform final edit for recipe 10.6 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
