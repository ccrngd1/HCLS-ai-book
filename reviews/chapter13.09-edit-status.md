# Edit Status: Recipe 13.9 — Literature-Derived Knowledge Graph

**Editor:** TechEditor
**Date:** 2026-06-01
**Task:** ch13-r09-edit

---

## Changes Applied

### From Expert Review

1. **S-1 (HIGH) — BAA analysis:** Updated Prerequisites BAA row from "Required if..." to "Required." with explicit guidance about case reports and clinical trial PHI in provenance sentences. *Deferred PHI screening step to TechWriter via TODO marker.*

2. **S-2 (MEDIUM) — IAM permissions:** Replaced `neptune-db:*` with role-specific permissions (ingestion Lambdas get Read+Write, query API gets Read only, separate admin role noted).

3. **S-3 (MEDIUM) — SQS encryption:** Added SQS SSE-KMS to the Encryption row in Prerequisites.

4. **N-1 (MEDIUM) — VPC endpoint correction:** Replaced incorrect "VPC endpoints for S3 and Comprehend Medical" with correct networking: NAT Gateway for Comprehend Medical, VPC endpoint for S3 and CloudWatch Logs, SageMaker PrivateLink option noted.

5. **A-6 (MEDIUM) — Cost estimate:** Updated SageMaker cost from "$200-800/month" to "$800-2,400/month" with auto-scaling and batch transform note. Added data transfer line (N-2).

6. **A-4 (MEDIUM) — Deduplication:** Added sentence to Step 1 walkthrough noting to process only full-text version when both PubMed abstract and PMC full-text exist.

7. **S-4 (LOW) — NCBI rate limiting:** Added `api_key` parameter and rate limit comment to Step 1 pseudocode.

### Deferred to TechWriter (TODO markers placed)

| Finding | Severity | Location | Reason |
|---------|----------|----------|--------|
| A-1 | HIGH | After Step Functions paragraph | Requires new DLQ component + Mermaid diagram update |
| A-2 | HIGH | Before Step 4 pseudocode | Requires new validation_status field design + query guidance |
| A-3 | HIGH | After "Where it struggles" | Requires new retraction monitoring component + pseudocode |
| S-1 | HIGH | After Step 1 walkthrough | Requires new PHI screening pipeline step |

### From Code Review

All code review findings (1-8) apply to the Python companion file (`chapter13.09-python-example.md`), not the main recipe. No changes needed here.

### Editorial Checklist

| Check | Status |
|-------|--------|
| Grammar and mechanics | ✅ Clean |
| Code formatting | ✅ All fenced blocks have language tags or are plain pseudocode |
| Link verification | ⚠️ Two existing TODO markers flag unverified URLs (repos, blogs) |
| Header hierarchy | ✅ H1 → H2 → H3 → H4, no skipped levels |
| Readability | ✅ Short paragraphs, active voice, no run-ons |
| Voice drift | ✅ No documentation-voice, no em dashes, no LinkedIn tone |
| RECIPE-GUIDE compliance | ✅ All required sections present in correct order |
| Vendor balance | ✅ ~46% vendor-agnostic / ~54% AWS (acceptable per expert review; driven by pseudocode length) |

---

## Summary

The recipe was already well-written with excellent voice and structure. Edits focused on security/networking accuracy in the Prerequisites table (IAM scoping, BAA strengthening, VPC correction, cost update) and placing TODO markers for the four HIGH findings that require new architectural content from the TechWriter.
