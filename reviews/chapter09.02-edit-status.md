# Edit Status: Recipe 9.2 - Patient Photo Verification

**Editor:** TechEditor
**Date:** 2026-05-31
**Status:** BLOCKED - Main recipe file missing

---

## Summary

The final edit for Recipe 9.2 cannot be fully completed. The main recipe file (`chapter09.02-patient-photo-verification.md`) was never written. Both the code review and expert review confirm this file does not exist.

## What Was Edited

**Python companion (`chapter09.02-python-example.md`):**
- Verified all code review findings addressed (Issue 1: `UnmatchedFaces` comment corrected; Issue 2: similarity sentinel comment added; Issue 3: `Attributes` parameter fixed to `["DEFAULT"]`)
- Verified SEC-2 (HIGH): BAA requirement note present in Setup section
- Verified SEC-1 (MEDIUM): IAM permissions separated into verification-time vs. enrollment-time with resource-scoping guidance
- Removed redundant sentence in opening callout ("Consider it a starting point, not a destination" duplicated the preceding sentence)
- Confirmed: zero em dashes, no documentation-voice, no fabricated URLs, correct header hierarchy (H1 title, H2 for sections)
- Confirmed: all code blocks have language tags (`python`, `bash`)
- Confirmed: voice is consistent with STYLE-GUIDE.md throughout (engineer-to-engineer, conversational, honest)
- Confirmed: all TODO markers correctly formatted with finding IDs for follow-up tracking
- Confirmed: vendor balance is 100% AWS-specific (acceptable for Python companion; the 70/30 balance applies to the main recipe)

## Editorial Checklist Results

| Check | Status |
|-------|--------|
| Grammar and mechanics | PASS |
| Code formatting | PASS (all fenced blocks have language tags, inline code for service names) |
| Link verification | PASS (only internal cross-reference to main recipe, which is flagged via TODO) |
| Header hierarchy | PASS (H1 title, H2 sections, no skipped levels) |
| Readability | PASS (short paragraphs, active voice, no run-on sentences) |
| Voice drift | PASS (no documentation-voice, no em dashes, no LinkedIn tone) |
| RECIPE-GUIDE compliance | N/A for Python companion (main recipe structure requirements apply to the missing file) |
| Vendor balance | N/A for Python companion (100% AWS is expected for the code file) |

## Blocking Issues

| ID | Severity | Description |
|----|----------|-------------|
| ARCH-1 | CRITICAL | Main recipe file does not exist. Must be written per RECIPE-GUIDE.md before the edit pipeline can complete. |

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

The TechWriter must draft `chapter09.02-patient-photo-verification.md` before this recipe can proceed through the full edit pipeline. The Python companion is editorially complete and ready for publication once the main recipe exists.
