---
id: ch14-r04-python
title: "Python Companion: Nurse Staffing Optimization"
target_persona: TechWriter
tags: [chapter14, recipe, python]
depends_on: [ch14-r04-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter14.04-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create a Python companion example for the Nurse Staffing Optimization recipe.

## Instructions
Develop a working Python example that demonstrates the core optimization concepts from the Nurse Staffing Optimization recipe. Include problem formulation, constraint definition, solver invocation, and solution interpretation with healthcare-specific parameters.
