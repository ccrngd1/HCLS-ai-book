---
id: ch10-r03-python
title: "Python Companion: Voice-to-Text for EHR Navigation"
target_persona: TechWriter
tags: [chapter10, recipe, python]
depends_on: [ch10-r03-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter10.03-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create Python companion code for recipe 10.3 Voice-to-Text for EHR Navigation.

## Instructions
Write a Python example demonstrating voice-to-text for ehr navigation. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
