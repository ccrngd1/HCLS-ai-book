---
id: ch11-r03-python
title: 'Python Companion: Prescription Refill Request Bot'
target_persona: TechWriter
tags:
- chapter11
- recipe
- python
depends_on:
- ch11-r03-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter11.03-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter11.03-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create Python companion code for recipe 11.3 Prescription Refill Request Bot.

## Instructions
Write a Python example demonstrating prescription refill request bot. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
