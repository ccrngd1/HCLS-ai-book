---
id: ch15-r04-expert-review
title: "Expert Review: Sepsis Treatment Optimization"
target_persona: TechExpertReviewer
tags: [chapter15, recipe, expert-review]
depends_on: [ch15-r04-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter15.04-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Sepsis Treatment Optimization recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the RL formulation is clinically appropriate, safety constraints are sufficient, that offline evaluation methodology is sound, and that regulatory considerations (FDA) are adequately addressed.
