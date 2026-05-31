---
id: ch07-r06-code-review
title: "Code Review: Rising Risk Identification"
target_persona: TechCodeReviewer
tags: [chapter07, recipe, code-review]
depends_on: [ch07-r06-python]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter07.06-code-review.md]
  - type: persona_review
    name: quality-review
    persona: TechExpertReviewer
    pass_condition: >-
      Review verifies API correctness, identifies real issues with severity ratings, and provides specific actionable fixes with code snippets.
---

## Objective
Review the Python companion code for Rising Risk Identification.

## Instructions
Evaluate code quality, correctness, and healthcare-specific considerations. Check for proper data handling, algorithm appropriateness, and production readiness.
