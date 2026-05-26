---
id: ch02-r02-python
title: "Python Companion: Medical Terminology Simplification"
target_persona: TechWriter
tags: [chapter02, recipe, python]
depends_on: [ch02-r02-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.02-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion code for Medical Terminology Simplification.

## Instructions
Write a Python example demonstrating the core pattern for medical terminology simplification. Include working code with comments explaining healthcare-specific considerations.
