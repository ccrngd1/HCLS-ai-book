---
id: ch04-r06-python
title: 'Python Companion: Care Gap Prioritization'
target_persona: TechWriter
tags:
- chapter04
- recipe
- python
depends_on:
- ch04-r06-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.06-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter04.06-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Care Gap Prioritization.

## Instructions
Write a Python example demonstrating the core pattern for care gap prioritization. Include working code with comments explaining healthcare-specific considerations.
