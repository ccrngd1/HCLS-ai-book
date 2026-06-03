---
id: ch14-r04-edit
title: 'Final Edit: Nurse Staffing Optimization'
target_persona: TechEditor
tags:
- chapter14
- recipe
- edit
depends_on:
- ch14-r04-code-review
- ch14-r04-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter14.04-nurse-staffing-optimization.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter14.04-nurse-staffing-optimization.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of the Nurse Staffing Optimization recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
