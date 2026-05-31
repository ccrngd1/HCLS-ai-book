---
id: ch09-r08-expert-review
title: "Expert Review: Pathology Slide Analysis"
target_persona: TechExpertReviewer
tags: [chapter09, recipe, expert-review]
depends_on: [ch09-r08-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter09.08-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Pathology Slide Analysis recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the approach is appropriate for healthcare, limitations are acknowledged, and the recipe provides actionable guidance.
