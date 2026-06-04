# Edit Status: Recipe 14.4 - Nurse Staffing Optimization

**Editor:** TechEditor
**Date:** 2026-06-04
**Status:** COMPLETE - Publication-ready

---

## Editorial Checklist Results

| Check | Status | Notes |
|-------|--------|-------|
| Grammar and mechanics | ✓ PASS | No errors found |
| Code formatting | ✓ PASS | All fenced blocks have language tags (text, mermaid, pseudocode, json); inline code for service names |
| Link verification | ✓ PASS | All URLs are well-formed AWS docs, Google developers, or highs.dev |
| Header hierarchy | ✓ PASS | H1 title, H2 major sections, H3 subsections, H4 walkthrough; no skipped levels |
| Readability | ✓ PASS | Short paragraphs, active voice, no run-on sentences |
| Voice drift check | ✓ PASS | No documentation-voice, no feature-list formatting, no announcements, zero em dashes, zero en dashes, no LinkedIn tone |
| Code block language tags | ✓ PASS | All 8 opening fences have language tags (text, mermaid, pseudocode x5, json) |
| RECIPE-GUIDE compliance | ✓ PASS | All required sections present in correct order |
| Vendor balance | ✓ PASS | ~70% vendor-agnostic (Problem, Technology, General Architecture) / ~30% AWS-specific (Implementation) |

---

## Changes Made This Pass

1. **En dash replaced** (line 3): `$100–200/month` changed to `$100-200/month`
2. **Language tag added** (line 99): Bare ``` for pipeline diagram changed to ```text
3. **Language tags added** (lines 197, 254, 331, 386, 442): Five bare ``` pseudocode blocks changed to ```pseudocode

---

## Review Findings Disposition

### Expert Review Findings

| Finding | Severity | Status | Action Taken |
|---------|----------|--------|--------------|
| A1: No concurrency control on real-time mutations | HIGH | ADDRESSED | DynamoDB conditional writes discussed in architecture, General Architecture, and Step 4 pseudocode |
| A2: SageMaker cold start for real-time path | HIGH | ADDRESSED | Min instance count of 1 specified; Lambda alternative discussed in "Why These Services" |
| S1: SNS notification content may contain PHI | HIGH | ADDRESSED | Notification sanitization guidance in Step 5; SMS content restrictions explicit; push notification recommendation present |
| S2: Staff preference data access control | MEDIUM | ADDRESSED | Note in Step 1 pseudocode about treating preferences as ephemeral; delete after solve |
| S3: IAM permissions not least-privilege | MEDIUM | ADDRESSED | Prerequisites table includes scoping note per function with separate IAM roles |
| S4: Audit trail missing manual overrides | MEDIUM | ADDRESSED | Step 5 and General Architecture include manual override event type with who/what/why |
| A3: Demand forecast cold start fallback | MEDIUM | ADDRESSED | Static staffing matrix fallback in Step 1 pseudocode and General Architecture |
| A4: Solver infeasibility recovery path | MEDIUM | ADDRESSED | IIS analysis explanation with concrete example in Step 3 |
| N1: VPC endpoint list incomplete | MEDIUM | ADDRESSED | Full endpoint list in Prerequisites with cost note (~$35-50/month) |
| V1: "voluntold" colloquialism | LOW | KEPT | Fits voice; vivid and appropriate for style |
| V2: TODO items in Additional Resources | LOW | DEFERRED | Existing TODO marker properly formatted for TechWriter follow-up |
| N2: No egress control for solver container | LOW | NOT ADDRESSED | Low severity; would add length without proportional value |

### Code Review Findings

| Finding | Severity | Status | Notes |
|---------|----------|--------|-------|
| Finding 4: Sample data infeasibility | ERROR | N/A | Applies to Python companion, not main recipe |
| Finding 2: Coverage rate metric | WARNING | N/A | Applies to Python companion |
| Finding 5: Overtime check period assumption | WARNING | N/A | Applies to Python companion |
| Finding 1: Redundant constraint | NOTE | N/A | Applies to Python companion |

---

## Remaining TODOs in Recipe

1. `<!-- TODO (TechWriter): Expert review V2 (LOW). Verify and add URLs for Burke et al. "The State of the Art of Nurse Rostering" survey paper and INFORMS Healthcare conference proceedings, or remove this subsection if links cannot be verified. -->` (Additional Resources section)

---

## Summary

Recipe 14.4 is publication-ready. All HIGH and MEDIUM expert review findings were already incorporated in the prior editing pass. This final pass fixed one en dash (line 3) and added language tags to six bare code fences. Zero em dashes, zero en dashes, zero bare code fences remain. Voice is consistent throughout. The single remaining TODO (V2, LOW) defers academic link verification to the TechWriter.
