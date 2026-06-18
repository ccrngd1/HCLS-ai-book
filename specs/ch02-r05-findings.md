---
id: ch02-r05-findings
title: 'Resolve open findings: Recipe 2.5 After-Visit Summary Generation'
target_persona: TechWriter
tags:
- chapter02
- recipe
- finding-resolution
depends_on: []
validation:
- type: file_exists
  name: recipe-files-exist
  paths:
  - chapter02.05-after-visit-summary-generation.md
  - chapter02.05-architecture.md
  - chapter02.05-python-example.md
- type: shell
  name: findings-guardrail
  commands:
  - python3 check_findings.py chapter02.05
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: >-
    Every open finding listed in chapter02.05-todo.md has been either (a)
    resolved in the correct source file with a technically sound,
    HIPAA-compliant, architecture-correct fix, or (b) explicitly deferred with
    a one-line '[NEEDS HUMAN]' note in the todo file and a reason (external
    citation needed, or a product decision the author must make). The
    architecture companion and the python example remain mutually consistent
    (same services, same data shapes, same security posture). No clinical or
    security regressions were introduced. Resolved items have been removed from
    chapter02.05-todo.md. No em dashes were introduced.
---


## Objective
Resolve the open expert-review and code-review findings for Recipe 2.5 (After-Visit Summary Generation), which are listed in `chapter02.05-todo.md`. This is the pilot for a book-wide finding-resolution pass, so favor a clean, repeatable approach.

## Inputs
- `chapter02.05-todo.md` — the checklist of open findings (each with a finding code like S1, S3, A1, N1 and a specified fix).
- Full reviewer context: `reviews/chapter02.05-expert-review.md` and `reviews/chapter02.05-code-review.md`.
- The recipe source files:
  - `chapter02.05-after-visit-summary-generation.md` (main / story — vendor-agnostic; edit only if a finding truly belongs here)
  - `chapter02.05-architecture.md` (AWS implementation — most findings land here)
  - `chapter02.05-python-example.md` (code)

## Instructions
1. Read `chapter02.05-todo.md` and the two review files for full context on each finding.
2. For each open finding, apply the fix it specifies to the appropriate source file. The findings are concrete (e.g., S1: pivot SMS to notification-plus-portal-link, add a consent gate, add a "SMS and PHI" subsection in "Why This Isn't Production-Ready"; S3: scope IAM to resource ARNs and add KMS actions; N1: complete the VPC interface-endpoint list; A3: add idempotency via a DynamoDB conditional write).
3. Keep the architecture companion and the python example **mutually consistent** — if you change a service, data shape, or security posture in one, reflect it in the other.
4. Do not edit the main/story file unless a finding genuinely concerns it (most do not).
5. When a finding is resolved, **remove its entry from `chapter02.05-todo.md`**.
6. If a finding requires an external citation you cannot verify, or a product decision only the author can make (for example "should direct-to-SMS clinical content remain an option at all"), do **not** guess: leave the item in `chapter02.05-todo.md` and prefix it with `[NEEDS HUMAN]` plus a one-line reason.
7. Do not reintroduce `<!-- TODO -->` comments into the source files; the `-todo.md` file is the only place open work is tracked.
8. No em dashes. Match the existing voice and RECIPE-GUIDE structure.

## Notes
Correctness matters more than completeness here: a HIPAA or architecture fix that is subtly wrong is worse than an honest `[NEEDS HUMAN]` deferral. The expert reviewer validating this task raised these findings, so fixes must actually satisfy them.
