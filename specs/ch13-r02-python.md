---
id: ch13-r02-python
title: 'Python Companion: Provider Directory as Knowledge Graph'
target_persona: TechWriter
tags:
- chapter13
- recipe
- python
depends_on:
- ch13-r02-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter13.02-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter13.02-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create a Python companion example for the Provider Directory as Knowledge Graph recipe.

## Instructions
Develop a working Python example that demonstrates the core concepts from the Provider Directory as Knowledge Graph recipe. Include graph construction, querying, and practical healthcare-specific usage patterns.
