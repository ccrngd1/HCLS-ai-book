---
id: ch05-r09-python
title: 'Python Companion: National-Scale Patient Matching'
target_persona: TechWriter
tags:
- chapter05
- recipe
- python
depends_on:
- ch05-r09-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.09-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter05.09-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for National-Scale Patient Matching.

## Instructions
Write a Python example demonstrating the core pattern for national-scale patient matching. Include working code with comments explaining healthcare-specific considerations.
