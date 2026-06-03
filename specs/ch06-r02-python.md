---
id: ch06-r02-python
title: 'Python Companion: Utilization Pattern Segmentation'
target_persona: TechWriter
tags:
- chapter06
- recipe
- python
depends_on:
- ch06-r02-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter06.02-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter06.02-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion for Utilization Pattern Segmentation.

## Instructions
Write a Python example demonstrating the core technique for Utilization Pattern Segmentation. Include synthetic healthcare data, implementation of the key algorithm, and interpretation of results.
