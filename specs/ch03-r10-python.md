---
id: ch03-r10-python
title: "Python Companion: Epidemic Outbreak Detection"
target_persona: TechWriter
tags: [chapter03, recipe, python]
depends_on: [ch03-r10-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter03.10-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion code for Epidemic Outbreak Detection.

## Instructions
Write a Python example demonstrating the core pattern for epidemic outbreak detection. Include working code with comments explaining healthcare-specific considerations.
