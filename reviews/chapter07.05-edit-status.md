# Edit Status: Recipe 7.5 - 30-Day Readmission Risk

**Editor:** TechEditor
**Date:** 2026-06-03
**Status:** COMPLETE

---

## Changes Applied

### From Expert Review

| Finding | Severity | Status | Action Taken |
|---------|----------|--------|--------------|
| S1 | HIGH | Addressed | IAM permissions row includes resource-level scoping guidance and separate roles |
| S2 | HIGH | Addressed | SNS section includes PHI endpoint restriction guidance in both pseudocode comments and "Why These Services" |
| A1 | HIGH | Addressed | Model versioning and rollback paragraph added after architecture diagram |
| S3 | MEDIUM | Addressed | CloudTrail row includes DynamoDB data event limitation and application-level audit note |
| S4 | MEDIUM | Deferred (TODO) | TODO marker in Step 4 pseudocode for retention policy discussion |
| A2 | MEDIUM | Deferred (TODO) | TODO marker in Ingredients section for feature store clarification |
| A3 | MEDIUM | Deferred (TODO) | TODO marker in Why These Services section for DLQ guidance |
| A4 | MEDIUM | Addressed | Cost Estimate includes HealthLake query parallelization note |
| N1 | MEDIUM | Addressed | VPC row includes Step Functions/states and SNS interface endpoints |
| A5 | LOW | Addressed | Yale/CMS URL resolved with qualitynet.cms.gov reference |
| S5 | LOW | Addressed | Sample Data row includes HIPAA-compliant validation environment note |
| N2 | LOW | Addressed | VPC row includes HealthLake regional availability caveat |
| V1 | LOW | Addressed | SageMaker "provides" changed to "gives you" |

### From Code Review

| Finding | Severity | Status | Action Taken |
|---------|----------|--------|--------------|
| W1 | WARNING | Fixed | `score_patient` comment clarified: -999 is safety fallback, callers MUST impute first, scikit-learn does not handle sentinels natively |
| W2 | WARNING | Fixed | `store_risk_score` nested `risk_drivers` numerics now wrapped in `Decimal(str(...))` with explanatory comment |
| N1 | NOTE | Accepted | `fit_platt_scaling` is pedagogically useful even without being called in `__main__` |
| N2 | NOTE | Accepted | Platt scaling on probabilities is unconventional but valid with fitted params |
| N3 | NOTE | Accepted | Global importance as proxy for per-patient explanation is fine for teaching |
| N4 | NOTE | Accepted | Synthetic encounter ID collisions are negligible for demo data |

### Editorial Fixes (Final Pass)

- Fixed 8 malformed code block closings: `\`\`\`text` (incorrectly used as closing fence) replaced with proper `\`\`\`` throughout main recipe (lines 91, 170, 248, 334, 378, 470, 525, 561)
- Verified zero em dashes (U+2014) in both files
- Verified zero en dashes (U+2013) in both files
- Verified all code fences have language tags (text, mermaid, pseudocode, json, python, bash)
- Verified no bare ``` openings exist
- Verified header hierarchy correct (H1 title, H2 major sections, H3 subsections, H4 steps)
- Verified no documentation-voice detected
- Verified RECIPE-GUIDE sections all present in correct order
- Verified vendor balance maintained (~70/30)
- Verified all TODO markers include finding IDs on same line for follow-up tracking

---

## Remaining TODOs (3 deferred to TechWriter)

1. `<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add dead letter queue guidance... -->`
2. `<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Clarify feature store architecture... -->`
3. `// TODO (TechWriter): Expert review S4 (MEDIUM). Add note about compliance retention requirements... //`

---

## Verdict

Both files are publication-ready. Three MEDIUM findings deferred to TechWriter for follow-up as they require new architectural content (DLQ design, feature store pattern, retention policy) beyond editorial scope.
