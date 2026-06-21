---
id: ch03-r10-findings
title: 'Resolve open findings: Recipe 3.10: Epidemic / Outbreak Detection ⭐'
target_persona: TechWriter
tags:
- chapter03
- recipe
- finding-resolution
depends_on: []
validation:
- type: file_exists
  name: recipe-files-exist
  paths:
  - chapter03.10-architecture.md
  - chapter03.10-epidemic-outbreak-detection.md
  - chapter03.10-python-example.md
- type: shell
  name: findings-guardrail
  commands:
  - python3 check_findings.py chapter03.10
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: >-
    Every open finding listed in chapter03.10-todo.md has been either (a) resolved
    in the correct source file with a technically sound, HIPAA-compliant,
    architecture-correct fix, or (b) explicitly deferred with a one-line
    '[NEEDS HUMAN]' note in the todo file and a reason. The architecture
    companion and the python example remain mutually consistent. No clinical or
    security regressions. Resolved items removed from chapter03.10-todo.md. No new em dashes are introduced into the recipe source files.
---


## Objective
Resolve the open expert-review and code-review findings for Recipe 3.10: Epidemic / Outbreak Detection ⭐, listed in `chapter03.10-todo.md`.

## Inputs
- `chapter03.10-todo.md` (the open findings checklist).
- Reviewer context: `reviews/chapter03.10-expert-review.md`, `reviews/chapter03.10-code-review.md`.
- Recipe source files:
  - `chapter03.10-architecture.md`
  - `chapter03.10-epidemic-outbreak-detection.md`
  - `chapter03.10-python-example.md`

## Instructions
1. Read `chapter03.10-todo.md` (and any review files above) for full context on each finding.
2. Apply each finding's specified fix to the appropriate source file. Most land in the architecture companion or the python example; edit the main/story file only if a finding truly concerns it.
3. Keep the architecture companion and python example mutually consistent.
4. Remove each resolved entry from `chapter03.10-todo.md`.
5. If a finding needs an external citation you cannot verify, or a product decision only the author can make, leave it in `chapter03.10-todo.md` prefixed with `[NEEDS HUMAN]` and a one-line reason. Do not guess.
6. Do not reintroduce `<!-- TODO -->` comments into the source files.
7. No em dashes. Match the existing voice and RECIPE-GUIDE structure.

## Notes
Correctness over completeness: a subtly wrong HIPAA/architecture fix is worse than an honest `[NEEDS HUMAN]` deferral. The expert reviewer validating this task raised these findings; fixes must actually satisfy them.
