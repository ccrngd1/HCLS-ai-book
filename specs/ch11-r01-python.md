---
id: ch11-r01-python
title: "Python Companion: FAQ Chatbot"
target_persona: TechWriter
tags: [chapter11, recipe, python]
depends_on: [ch11-r01-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter11.01-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create Python companion code for recipe 11.1 FAQ Chatbot.

## Instructions
Write a Python example demonstrating faq chatbot. Include sample code with healthcare-appropriate patterns, error handling, and HIPAA-compliant data processing.
