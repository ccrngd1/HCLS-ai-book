---
id: ch10-r04-edit
title: 'Final Edit: Medical Transcription Dictation'
target_persona: TechEditor
tags:
- chapter10
- recipe
- edit
depends_on:
- ch10-r04-code-review
- ch10-r04-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter10.04-medical-transcription-dictation.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter10.04-medical-transcription-dictation.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Perform final edit for recipe 10.4 incorporating review feedback.

## Instructions
Integrate feedback from code review and expert review into the final version of the recipe. Ensure consistency, clarity, and technical accuracy throughout.
