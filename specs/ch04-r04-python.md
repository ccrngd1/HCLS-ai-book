---
id: ch04-r04-python
title: 'Python Companion: Wellness Program Recommendations'
target_persona: TechWriter
tags:
- chapter04
- recipe
- python
depends_on:
- ch04-r04-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.04-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter04.04-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Wellness Program Recommendations.

## Instructions
Write a Python example demonstrating the core pattern for wellness program recommendations. Include working code with comments explaining healthcare-specific considerations.
