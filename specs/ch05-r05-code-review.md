---
id: ch05-r05-code-review
title: 'Code Review: Cross-Facility Patient Matching'
target_persona: TechCodeReviewer
tags:
- chapter05
- recipe
- code-review
depends_on:
- ch05-r05-python
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter05.05-code-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter05.05-code-review.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: Review verifies API correctness, identifies real issues with severity
    ratings, and provides specific actionable fixes with code snippets.
---


## Objective
Review the Python companion code for Cross-Facility Patient Matching.

## Instructions
Review the Python example for correctness, security, best practices, and clarity. Verify healthcare-specific requirements are properly handled.
