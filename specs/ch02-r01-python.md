---
id: ch02-r01-python
title: "Python Companion: Patient Message Response Drafting"
target_persona: TechWriter
tags: [chapter02, recipe, python]
depends_on: [ch02-r01-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.01-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion code for Patient Message Response Drafting.

## Instructions
Write a Python example demonstrating the core pattern for patient message response drafting. Include working code with comments explaining healthcare-specific considerations.
