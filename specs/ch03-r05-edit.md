---
id: ch03-r05-edit
title: "Final Edit: Lab Result Outlier Detection"
target_persona: TechEditor
tags: [chapter03, recipe, edit]
depends_on: [ch03-r05-code-review, ch03-r05-expert-review]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.05-lab-result-outlier-detection.md]
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
Produce the final edited version of Lab Result Outlier Detection.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
