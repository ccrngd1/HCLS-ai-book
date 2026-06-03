---
id: ch03-r04-python
title: 'Python Companion: Medication Dispensing Anomalies'
target_persona: TechWriter
tags:
- chapter03
- recipe
- python
depends_on:
- ch03-r04-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter03.04-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter03.04-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Medication Dispensing Anomalies.

## Instructions
Write a Python example demonstrating the core pattern for medication dispensing anomalies. Include working code with comments explaining healthcare-specific considerations.
