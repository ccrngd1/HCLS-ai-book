---
id: ch14-r09-python
title: 'Python Companion: Chemotherapy Scheduling'
target_persona: TechWriter
tags:
- chapter14
- recipe
- python
depends_on:
- ch14-r09-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter14.09-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter14.09-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create a Python companion example for the Chemotherapy Scheduling recipe.

## Instructions
Develop a working Python example that demonstrates the core optimization concepts from the Chemotherapy Scheduling recipe. Include problem formulation, constraint definition, solver invocation, and solution interpretation with healthcare-specific parameters.
