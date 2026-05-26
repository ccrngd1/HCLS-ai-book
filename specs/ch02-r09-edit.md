---
id: ch02-r09-edit
title: "Final Edit: Clinical Decision Support Synthesis"
target_persona: TechEditor
tags: [chapter02, recipe, edit]
depends_on: [ch02-r09-code-review, ch02-r09-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.09-clinical-decision-support-synthesis.md]
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
Produce the final edited version of Clinical Decision Support Synthesis.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
