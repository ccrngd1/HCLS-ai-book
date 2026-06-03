---
id: ch14-r05-python
title: 'Python Companion: Operating Room Block Scheduling'
target_persona: TechWriter
tags:
- chapter14
- recipe
- python
depends_on:
- ch14-r05-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter14.05-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter14.05-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create a Python companion example for the Operating Room Block Scheduling recipe.

## Instructions
Develop a working Python example that demonstrates the core optimization concepts from the Operating Room Block Scheduling recipe. Include problem formulation, constraint definition, solver invocation, and solution interpretation with healthcare-specific parameters.
