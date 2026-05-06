---
id: ch15-r09-code-review
title: "Code Review: Radiation Therapy Adaptive Planning"
target_persona: TechCodeReviewer
tags: [chapter15, recipe, code-review]
depends_on: [ch15-r09-python]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter15.09-code-review.md]
---

## Objective
Review the Python companion code for Radiation Therapy Adaptive Planning.

## Instructions
Review the code for correctness, security, performance, and healthcare-specific best practices. Verify RL agent safety constraints are properly enforced, reward functions align with clinical objectives, and the implementation handles edge cases in patient state transitions.
