---
id: ch02-r06-python
title: 'Python Companion: Clinical Note Summarization'
target_persona: TechWriter
tags:
- chapter02
- recipe
- python
depends_on:
- ch02-r06-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.06-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter02.06-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion code for Clinical Note Summarization.

## Instructions
Write a Python example demonstrating the core pattern for clinical note summarization. Include working code with comments explaining healthcare-specific considerations.
