---
id: ch05-r04-python
title: 'Python Companion: Insurance Eligibility Matching'
target_persona: TechWriter
tags:
- chapter05
- recipe
- python
depends_on:
- ch05-r04-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.04-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter05.04-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Insurance Eligibility Matching.

## Instructions
Write a Python example demonstrating the core pattern for insurance eligibility matching. Include working code with comments explaining healthcare-specific considerations.
