---
id: ch08-r02-python
title: 'Python Companion: Patient Sentiment Analysis'
target_persona: TechWriter
tags:
- chapter08
- recipe
- python
depends_on:
- ch08-r02-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter08.02-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter08.02-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion for Patient Sentiment Analysis.

## Instructions
Write a Python example demonstrating the core technique for Patient Sentiment Analysis. Include synthetic healthcare data, implementation of the key algorithm, and interpretation of results.
