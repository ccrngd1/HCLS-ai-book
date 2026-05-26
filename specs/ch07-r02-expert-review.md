---
id: ch07-r02-expert-review
title: "Expert Review: Propensity to Pay Scoring"
target_persona: TechExpertReviewer
tags: [chapter07, recipe, expert-review]
depends_on: [ch07-r02-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter07.02-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Propensity to Pay Scoring recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the approach is appropriate for healthcare, limitations are acknowledged, and the recipe provides actionable guidance.
