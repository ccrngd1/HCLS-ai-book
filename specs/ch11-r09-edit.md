---
id: ch11-r09-edit
title: "Final Edit: Care Coordination Assistant"
target_persona: TechEditor
tags: [chapter11, recipe, edit]
depends_on: [ch11-r09-code-review, ch11-r09-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter11.09-care-coordination-assistant.md]
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
Perform final edit for recipe 11.9 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
