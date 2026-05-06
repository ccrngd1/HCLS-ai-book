---
id: ch07-r06-python
title: "Python Companion: Rising Risk Identification"
target_persona: TechWriter
tags: [chapter07, recipe, python]
depends_on: [ch07-r06-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter07.06-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create the Python companion for Rising Risk Identification.

## Instructions
Write a Python example demonstrating the core technique for Rising Risk Identification. Include synthetic healthcare data, implementation of the key algorithm, and interpretation of results.
