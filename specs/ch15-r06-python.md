---
id: ch15-r06-python
title: "Python Companion: Glucose Control in ICU"
target_persona: TechWriter
tags: [chapter15, recipe, python]
depends_on: [ch15-r06-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter15.06-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create a Python companion example for the Glucose Control in ICU recipe.

## Instructions
Develop a working Python example that demonstrates the core RL concepts from the Glucose Control in ICU recipe. Include environment definition, agent implementation, reward shaping, and safety constraint enforcement with healthcare-specific parameters.
