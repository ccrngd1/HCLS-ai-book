---
id: ch11-r06-python
title: "Python Companion: Symptom Checker Triage Bot"
target_persona: TechWriter
tags: [chapter11, recipe, python]
depends_on: [ch11-r06-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter11.06-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create Python companion code for recipe 11.6 Symptom Checker Triage Bot.

## Instructions
Write a Python example demonstrating symptom checker triage bot. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
