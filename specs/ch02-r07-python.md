---
id: ch02-r07-python
title: "Python Companion: Literature Search and Evidence Synthesis"
target_persona: TechWriter
tags: [chapter02, recipe, python]
depends_on: [ch02-r07-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter02.07-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion code for Literature Search and Evidence Synthesis.

## Instructions
Write a Python example demonstrating the core pattern for literature search and evidence synthesis. Include working code with comments explaining healthcare-specific considerations.
