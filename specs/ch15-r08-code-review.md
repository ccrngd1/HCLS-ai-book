---
id: ch15-r08-code-review
title: "Code Review: Chemotherapy Dose Optimization"
target_persona: TechCodeReviewer
tags: [chapter15, recipe, code-review]
depends_on: [ch15-r08-python]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter15.08-code-review.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Review verifies API correctness, identifies real issues with severity ratings, and provides specific actionable fixes with code snippets.
---

## Objective
Review the Python companion code for Chemotherapy Dose Optimization.

## Instructions
Review the code for correctness, security, performance, and healthcare-specific best practices. Verify RL agent safety constraints are properly enforced, reward functions align with clinical objectives, and the implementation handles edge cases in patient state transitions.
