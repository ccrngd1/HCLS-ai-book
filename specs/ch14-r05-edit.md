---
id: ch14-r05-edit
title: 'Final Edit: Operating Room Block Scheduling'
target_persona: TechEditor
tags:
- chapter14
- recipe
- edit
depends_on:
- ch14-r05-code-review
- ch14-r05-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter14.05-operating-room-block-scheduling.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter14.05-operating-room-block-scheduling.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of the Operating Room Block Scheduling recipe.

## Instructions
Incorporate feedback from both code review and expert review. Ensure technical accuracy, consistent formatting, clear prose, and that all review comments have been addressed. Produce the publication-ready version.
