# Healthcare AI/ML Cookbook

**Status:** New — Ready for research  
**Assigned:** 2026-02-23  
**From:** CC via CABAL

## Overview

Create an O'Reilly-style technical cookbook focusing on AI/ML patterns in healthcare. Architecture-focused, no code — just patterns, use cases, and practical guidance.

## Structure

### Phase 1: Category Framework
Identify and organize general AI/ML categories applicable to healthcare:
- **OCR / Document Intelligence**
- **Personalization / Recommendation**
- **Anomaly Detection**
- **LLM / Generative AI**
- **Entity Resolution**
- **Cohort Analysis / Clustering / Nearest Neighbor** (e.g., patient similarity)
- *(Add others as identified)*

### Phase 2: Use Case Ideation
For each category, brainstorm specific healthcare use cases. Examples for OCR:
- Prescription ingestion
- New patient intake form digitization
- Handwritten claim digitization

**Ordering principle:** Start with simple/easy use cases, progress to complex architectures.

### Phase 3: Architecture Patterns
For each use case, document:
1. **Architecture overview** — components, data flow, integration points
2. **Hidden challenges** — what's harder than it looks
3. **Limitations** — what this approach can't do
4. **Assumptions** — what must be true for this to work
5. **Real-world considerations** — compliance, latency, cost, edge cases

## Deliverable Format

Cookbook-style entries:
- **Problem:** What you're trying to solve
- **Solution:** The pattern/architecture
- **Discussion:** Trade-offs, alternatives, gotchas
- **Related patterns:** Cross-references

## Notes

- Healthcare context means HIPAA, PHI handling, audit trails are always in scope
- Focus on patterns that work at scale, not just POC
- CC works in healthcare at AWS — this should reflect real enterprise concerns

## Next Steps

1. ✅ Finalize category list with brief descriptions — **DONE** → `phase1-categories.md`
2. ✅ Generate 5-10 use cases per category — **DONE** → `phase2-index.md` (150 use cases across 15 categories)
3. ⏳ Select initial batch for detailed architecture write-ups
4. ⏳ Review with CC before deep-diving

---

*Handoff complete. Begin when ready.*
