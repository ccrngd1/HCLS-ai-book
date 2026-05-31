# Edit Status: Recipe 7.7 - Length of Stay Prediction

**Editor:** TechEditor
**Date:** 2026-05-31
**Verdict:** COMPLETE (pending TechWriter follow-up on 4 deferred findings)

---

## Changes Applied

1. **Code formatting:** Added `text` language tags to 6 untagged fenced code blocks (1 ASCII architecture diagram, 5 pseudocode blocks). The `mermaid` and `json` blocks were already tagged.

2. **Voice fix (V4):** Confirmed the Feature Store paragraph already uses conversational phrasing ("The feature store is how you avoid training-serving skew.") rather than doc-voice. Changed "real-time predictions" to "real-time inference" to reduce repetition of "predictions" in close proximity.

3. **Voice fix (V5):** Confirmed the Problem section already ends with the improved transition ("The goal is a system that updates as reality unfolds, not one that guesses at admission and hopes for the best.") rather than the generic "Let's dig into how to build this well."

## Verified Clean

- **No em dashes** found anywhere in the recipe.
- **No doc-voice anti-patterns** ("This recipe demonstrates...", "We are excited...", "AWS architects, we need to talk...").
- **Header hierarchy** is correct: one H1 (title), H2 for major sections, H3 for subsections, one H4 (Walkthrough) appropriately nested.
- **RECIPE-GUIDE compliance:** All required sections present in correct order.
- **Vendor balance:** Problem and Technology sections (~65% of content) are entirely vendor-agnostic. AWS appears only in "The AWS Implementation" section.
- **All URLs** are plausible and well-formed (AWS docs, GitHub repos, PhysioNet, CMS, Synthea).
- **Active voice** throughout; no run-on sentences detected.
- **Short paragraphs** maintained; readability is strong.

## Deferred Findings (TODO markers preserved)

| Finding | Severity | Location | Status |
|---------|----------|----------|--------|
| S1 | HIGH | Prerequisites, IAM Permissions | TODO marker at line 166 |
| A1 | HIGH | Technology section | TODO marker at line 95 |
| S3 | MEDIUM | Why These Services, SageMaker | TODO marker at line 125 |
| A2 | MEDIUM | Step 4, inference | TODO marker at line 362 |

These require TechWriter content additions (new subsection for A1, rewritten IAM table for S1, new paragraphs for S3 and A2) and are beyond editorial scope.

## Expert Review Findings Already Incorporated

The following MEDIUM/LOW findings from the expert review are already reflected in the recipe text (incorporated during drafting or a prior pass):

- **S2:** DynamoDB access control and minimal-PHI alerts discussed in the DynamoDB paragraph
- **S4:** MIMIC-IV credentialing and Safe Harbor de-identification noted in Prerequisites
- **S5:** CloudTrail data events and SageMaker invocation logging specified in Prerequisites
- **A3:** Step Functions orchestration mentioned in Step 5 description
- **A4:** ADT event trigger for admission-time features described in Lambda paragraph
- **A5:** Real-time cost amortization assumption noted in Prerequisites
- **N1:** Full VPC endpoint list (including SNS, SageMaker API, interface types) in Prerequisites
- **N3:** QuickSight-to-DynamoDB path corrected (Athena/S3 pattern and Grafana alternative noted)

## Code Review Status

The code review passed with no ERRORs. The single WARNING (early_stopping_rounds not passed to XGBRegressor) applies to the Python companion file, not the main recipe pseudocode. No changes needed in this file.
