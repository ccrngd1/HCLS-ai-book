---
id: ch14-r02-python
title: "Python Companion: Patient-Provider Assignment"
target_persona: TechWriter
tags: [chapter14, recipe, python]
depends_on: [ch14-r02-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [chapter14.02-python-example.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Python code uses correct boto3 API calls, includes proper error handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder or stub implementations.
---

## Objective
Create a Python companion example for the Patient-Provider Assignment recipe.

## Instructions
Develop a working Python example that demonstrates the core optimization concepts from the Patient-Provider Assignment recipe. Include problem formulation, constraint definition, solver invocation, and solution interpretation with healthcare-specific parameters.
