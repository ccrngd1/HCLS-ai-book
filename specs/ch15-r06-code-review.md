---
id: ch15-r06-code-review
title: "Code Review: Glucose Control in ICU"
target_persona: TechCodeReviewer
tags: [chapter15, recipe, code-review]
depends_on: [ch15-r06-python]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter15.06-code-review.md]
---

## Objective
Review the Python companion code for Glucose Control in ICU.

## Instructions
Review the code for correctness, security, performance, and healthcare-specific best practices. Verify RL agent safety constraints are properly enforced, reward functions align with clinical objectives, and the implementation handles edge cases in patient state transitions.
