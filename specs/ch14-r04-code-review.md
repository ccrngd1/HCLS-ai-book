---
id: ch14-r04-code-review
title: "Code Review: Nurse Staffing Optimization"
target_persona: TechCodeReviewer
tags: [chapter14, recipe, code-review]
depends_on: [ch14-r04-python]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter14.04-code-review.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Review verifies API correctness, identifies real issues with severity ratings, and provides specific actionable fixes with code snippets.
---

## Objective
Review the Python companion code for Nurse Staffing Optimization.

## Instructions
Review the code for correctness, security, performance, and healthcare-specific best practices. Verify optimization constraints are properly formulated, solver usage is efficient, and the solution handles infeasible scenarios gracefully.
