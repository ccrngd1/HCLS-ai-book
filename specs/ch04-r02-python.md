---
id: ch04-r02-python
title: "Python Companion: Patient Education Content Matching"
target_persona: TechWriter
tags: [chapter04, recipe, python]
depends_on: [ch04-r02-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter04.02-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion code for Patient Education Content Matching.

## Instructions
Write a Python example demonstrating the core pattern for patient education content matching. Include working code with comments explaining healthcare-specific considerations.
