---
id: ch10-r05-python
title: "Python Companion: Patient-Facing Voice Assistant"
target_persona: TechWriter
tags: [chapter10, recipe, python]
depends_on: [ch10-r05-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter10.05-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create Python companion code for recipe 10.5 Patient-Facing Voice Assistant.

## Instructions
Write a Python example demonstrating patient-facing voice assistant. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
