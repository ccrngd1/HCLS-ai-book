---
id: ch04-r03-python
title: 'Python Companion: Provider Directory Search Optimization'
target_persona: TechWriter
tags:
- chapter04
- recipe
- python
depends_on:
- ch04-r03-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.03-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter04.03-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Provider Directory Search Optimization.

## Instructions
Write a Python example demonstrating the core pattern for provider directory search optimization. Include working code with comments explaining healthcare-specific considerations.
