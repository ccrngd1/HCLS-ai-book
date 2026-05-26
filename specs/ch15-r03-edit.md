---
id: ch15-r03-edit
title: "Final Edit: Clinical Trial Adaptive Randomization"
target_persona: TechEditor
tags: [chapter15, recipe, edit]
depends_on: [ch15-r03-code-review, ch15-r03-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter15.03-clinical-trial-adaptive-randomization.md]
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
Produce the final edited version of the Clinical Trial Adaptive Randomization recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
