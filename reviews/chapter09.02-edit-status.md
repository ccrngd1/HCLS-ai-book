# Edit Status: Recipe 9.2 - Patient Photo Verification

**Editor:** TechEditor
**Date:** 2026-05-31
**Status:** BLOCKED - Main recipe file missing

---

## Summary

The final edit for Recipe 9.2 cannot be completed. The main recipe file (`chapter09.02-patient-photo-verification.md`) was never written. Both the code review and expert review confirm this file does not exist.

## What Was Edited

**Python companion (`chapter09.02-python-example.md`):**
- Fixed title to include recipe name (was generic "Python Implementation Example")
- Addressed code review Issue 1 (WARNING): `UnmatchedFaces` comment already corrected by prior persona
- Addressed code review Issue 2 (NOTE): similarity sentinel comment already present
- Addressed code review Issue 3 (NOTE): `Attributes` parameter already corrected to `["DEFAULT"]`
- Addressed SEC-1 (MEDIUM): Separated IAM permissions into verification-time vs. enrollment-time roles with resource-scoping guidance
- Added TODO markers for all remaining expert review findings (SEC-3, SEC-4, ARCH-3) that require the main recipe to resolve
- Verified: zero em dashes, no documentation-voice, no fabricated URLs, correct header hierarchy
- BAA requirement note (SEC-2) already present in Setup section from prior persona

## Blocking Issues

| ID | Severity | Description |
|----|----------|-------------|
| ARCH-1 | CRITICAL | Main recipe file does not exist. Must be written per RECIPE-GUIDE.md before the edit pipeline can complete. |

## Deferred to Main Recipe (via TODO markers)

| ID | Severity | What's Needed |
|----|----------|---------------|
| ARCH-2 | HIGH | Liveness detection as core architecture step |
| SEC-2 | HIGH | Prerequisites table with BAA requirements |
| SEC-1 | MEDIUM | Resource-scoped IAM examples (partially addressed in Python companion) |
| SEC-3 | MEDIUM | Biometric data access controls and retention policies |
| SEC-4 | MEDIUM | Consent withdrawal workflow with face deletion |
| ARCH-3 | MEDIUM | Fallback workflow when verification fails |

## Next Step

The TechWriter must draft `chapter09.02-patient-photo-verification.md` before this recipe can proceed through the edit pipeline. All TODO markers in the Python companion reference findings that primarily belong in the main recipe.
