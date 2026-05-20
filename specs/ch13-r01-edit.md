---
id: ch13-r01-edit
title: "Final Edit: Drug Formulary Navigation"
target_persona: TechEditor
tags: [chapter13, recipe, edit]
depends_on: [ch13-r01-code-review, ch13-r01-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter13.01-drug-formulary-navigation.md]
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
Produce the final edited version of the Drug Formulary Navigation recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
