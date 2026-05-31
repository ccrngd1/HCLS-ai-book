# Edit Status: Recipe 9.2 - Patient Photo Verification

**Editor:** TechEditor
**Date:** 2026-05-31
**Status:** COMPLETE (Python companion) / BLOCKED (main recipe missing)

---

## Summary

The Python companion (`chapter09.02-python-example.md`) is editorially complete and ready for publication. The main recipe file (`chapter09.02-patient-photo-verification.md`) does not exist and must be written by the TechWriter before the full recipe can ship.

## What Was Edited

**Python companion (`chapter09.02-python-example.md`):**

- Code review Issue 1 (WARNING): `UnmatchedFaces` comment corrected to accurately describe API semantics
- Code review Issue 2 (NOTE): Similarity sentinel value comment added explaining 0.0 is not the real score
- Code review Issue 3 (NOTE): `Attributes` parameter fixed from `["QUALITY", "DEFAULT"]` to `["DEFAULT"]` with explanatory comment
- SEC-2 (HIGH): BAA requirement note added to Setup section
- SEC-1 (MEDIUM): IAM permissions separated into verification-time vs. enrollment-time with resource-scoping guidance
- Removed redundant sentence in opening callout
- All TODO markers correctly formatted with finding IDs for follow-up tracking

## Editorial Checklist Results

| Check | Status |
|-------|--------|
| Grammar and mechanics | PASS |
| Code formatting | PASS (all fenced blocks have language tags, inline code for service names) |
| Link verification | PASS (one internal cross-reference to main recipe, flagged via TODO) |
| Header hierarchy | PASS (H1 title, H2 sections, no skipped levels) |
| Readability | PASS (short paragraphs, active voice, no run-on sentences) |
| Voice drift | PASS (no documentation-voice, no em dashes, no LinkedIn tone) |
| RECIPE-GUIDE compliance | N/A for Python companion (structure requirements apply to main recipe) |
| Vendor balance | N/A for Python companion (100% AWS is expected for the code file) |

## Blocking Issues

| ID | Severity | Description |
|----|----------|-------------|
| ARCH-1 | CRITICAL | Main recipe file does not exist. Must be written per RECIPE-GUIDE.md before the recipe pipeline can complete. |

## Deferred to Main Recipe (via TODO markers in Python companion)

| ID | Severity | What's Needed |
|----|----------|---------------|
| ARCH-1 | CRITICAL | Write `chapter09.02-patient-photo-verification.md` per RECIPE-GUIDE.md |
| ARCH-2 | HIGH | Liveness detection as core architecture step |
| SEC-2 | HIGH | Prerequisites table with BAA requirements |
| SEC-1 | MEDIUM | Resource-scoped IAM examples (partially addressed in Python companion) |
| SEC-3 | MEDIUM | Biometric data access controls and retention policies |
| SEC-4 | MEDIUM | Consent withdrawal workflow with face deletion |
| ARCH-3 | MEDIUM | Fallback workflow when verification fails |

## Next Step

The TechWriter must draft `chapter09.02-patient-photo-verification.md` before this recipe can proceed through the full pipeline. The Python companion is editorially complete and ready for publication once the main recipe exists.
