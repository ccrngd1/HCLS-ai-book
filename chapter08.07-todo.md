# Open TODOs: Recipe 8.7: Adverse Event Detection in Clinical Text

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter08.07-architecture.md`

- **L446** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section here per RECIPE-GUIDE. Cover gaps like: expected-effects tuning required, cross-note reasoning not implemented, knowledge-base maintenance burden, human review workflow not defined, regulatory reporting integration not included.
- **L456** — TODO (TechWriter): Expert review A6 (MEDIUM). Add cross-note reasoning variation: per-patient medication timeline in DynamoDB updated from pharmacy feeds, query medications started in last 30 days when processing new notes to catch implicit AEs without explicit drug mention in current note.
