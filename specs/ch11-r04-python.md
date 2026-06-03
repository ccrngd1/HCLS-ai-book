---
id: ch11-r04-python
title: 'Python Companion: Pre-Visit Intake Bot'
target_persona: TechWriter
tags:
- chapter11
- recipe
- python
depends_on:
- ch11-r04-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter11.04-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter11.04-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create Python companion code for recipe 11.4 Pre-Visit Intake Bot.

## Instructions
Write a Python example demonstrating pre-visit intake bot. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
