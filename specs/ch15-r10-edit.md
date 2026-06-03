---
id: ch15-r10-edit
title: 'Final Edit: Hospital Resource Allocation Under Uncertainty'
target_persona: TechEditor
tags:
- chapter15
- recipe
- edit
depends_on:
- ch15-r10-code-review
- ch15-r10-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter15.10-hospital-resource-allocation-uncertainty.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter15.10-hospital-resource-allocation-uncertainty.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of the Hospital Resource Allocation Under Uncertainty recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
