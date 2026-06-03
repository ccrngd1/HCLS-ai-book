---
id: ch02-r05-python
title: 'Python Companion: After-Visit Summary Generation'
target_persona: TechWriter
tags:
- chapter02
- recipe
- python
depends_on:
- ch02-r05-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.05-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter02.05-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for After-Visit Summary Generation.

## Instructions
Write a Python example demonstrating the core pattern for after-visit summary generation. Include working code with comments explaining healthcare-specific considerations.
