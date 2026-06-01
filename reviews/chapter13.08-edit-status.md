# Edit Status: Recipe 13.8 — Medical Concept Normalization and Mapping

**Editor:** TechEditor
**Date:** 2026-06-01
**Verdict:** PUBLICATION-READY

---

## Changes Applied

No edits required. The recipe arrived in excellent condition with all addressable review findings already incorporated.

## Review Findings Disposition

### Addressed Inline (no TODO needed)

| Finding | Severity | Resolution |
|---------|----------|------------|
| A-2 | HIGH | Confidence values corrected to 0.95/0.80/0.80/0.60 with explanatory comments. 1.0 reserved for curated mappings. |
| S-1 | HIGH | PHI boundary design principle added as a dedicated paragraph in "Why These Services" section. |
| S-2 | MEDIUM | IAM permissions scoped with resource ARN patterns in Prerequisites table. |
| S-3 | MEDIUM | IAM authorization (SigV4) and private API deployment specified in Lambda + API Gateway paragraph. |
| A-3 | MEDIUM | `max_results` parameter (default 10,000) added to `expand_value_set` with truncation flag. |
| N-1 | MEDIUM | Security group requirements specified in Prerequisites VPC row. |
| N-2 | MEDIUM | Bulk loader data flow clarified: Glue writes to S3, Neptune reads from S3 via its own IAM role. S3 Gateway endpoint requirement noted. |

### Deferred with TODO Markers

| Finding | Severity | Location | Reason |
|---------|----------|----------|--------|
| A-1 | HIGH | Line 486 | Requires new Step 7 pseudocode block for cache invalidation. TechWriter content addition. |
| A-4 | MEDIUM | Line 164 | Requires Neptune sizing recommendation update and cost estimate revision. TechWriter content addition. |
| A-5 | MEDIUM | Line 166 | Requires fallback strategy description. TechWriter content addition. |

### Not Applicable to Main Recipe

| Finding | Source | Notes |
|---------|--------|-------|
| Code review Finding 1 | Python companion | Double-serialization comment. Applies to `chapter13.08-python-example.md`. |
| Code review Finding 2 | Python companion | Batch ordering. Applies to `chapter13.08-python-example.md`. |
| Code review Finding 3 | Python companion | Parse dedup ordering. Applies to `chapter13.08-python-example.md`. |
| Code review Finding 4 | Python companion | Version parameter omission. Applies to `chapter13.08-python-example.md`. |

## Editorial Checklist

| Check | Status |
|-------|--------|
| Grammar and mechanics | ✅ Pass |
| Code formatting (language tags, indentation) | ✅ Pass |
| Link verification (no fabricated URLs) | ✅ Pass |
| Header hierarchy (H1→H2→H3→H4, no skips) | ✅ Pass |
| Readability (short paragraphs, active voice) | ✅ Pass |
| Voice drift (no anti-patterns) | ✅ Pass |
| Em dashes | ✅ Zero found |
| RECIPE-GUIDE compliance (all sections, correct order) | ✅ Pass |
| Vendor balance (~60/40 general/AWS) | ✅ Acceptable |
| TODO markers properly formatted | ✅ All use rich form with finding ID and severity |
