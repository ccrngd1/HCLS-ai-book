---
id: ch05-r02-python
title: 'Python Companion: Provider NPI Matching'
target_persona: TechWriter
tags:
- chapter05
- recipe
- python
depends_on:
- ch05-r02-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.02-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter05.02-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Provider NPI Matching.

## Instructions
Write a Python example demonstrating the core pattern for provider npi matching. Include working code with comments explaining healthcare-specific considerations.
