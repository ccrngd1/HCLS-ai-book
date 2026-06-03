---
id: ch11-r06-code-review
title: 'Code Review: Symptom Checker Triage Bot'
target_persona: TechCodeReviewer
tags:
- chapter11
- recipe
- code-review
depends_on:
- ch11-r06-python
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter11.06-code-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py reviews/chapter11.06-code-review.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: Review verifies API correctness, identifies real issues with severity
    ratings, and provides specific actionable fixes with code snippets.
---


## Objective
Perform code review for recipe 11.6 Python companion.

## Instructions
Review the Python companion code for correctness, security, HIPAA compliance, and best practices. Verify implementation patterns are production-appropriate for healthcare environments.
