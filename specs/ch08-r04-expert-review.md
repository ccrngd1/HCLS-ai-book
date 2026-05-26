---
id: ch08-r04-expert-review
title: "Expert Review: Medication Extraction and Normalization"
target_persona: TechExpertReviewer
tags: [chapter08, recipe, expert-review]
depends_on: [ch08-r04-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter08.04-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Medication Extraction and Normalization recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the approach is appropriate for healthcare, limitations are acknowledged, and the recipe provides actionable guidance.
