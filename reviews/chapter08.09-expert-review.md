# Expert Review: Recipe 8.9 - Temporal Relationship Extraction

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.09-temporal-relationship-extraction.md`

---

## Overall Assessment

This is an outstanding recipe. The problem statement is among the best in the entire cookbook: the opening discharge summary example methodically demonstrates explicit dates, derived dates, relative expressions, domain-specific anchors, and implicit ordering in a single paragraph, then unpacks why each is hard for machines. The technology section is genuinely educational, covering the full spectrum from rule-based parsers through neural approaches to constraint propagation, with honest performance numbers (F1 0.75-0.80 on THYME) and frank discussion of why this problem remains unsolved. The clinical temporal vocabulary table is an excellent reference.

The architecture pattern is sound: the six-stage pipeline (preprocess, temporal expression recognition, event detection, candidate pair generation, relation classification, graph construction) is well-motivated and each stage is explained with clear business justification. The pseudocode is detailed, well-commented, and accessible to non-developers while maintaining technical rigor.

The "Honest Take" section is superb, acknowledging the gap between benchmark F1 (0.75) and real-world performance (0.60), the dominance of rule-based approaches for the easy 70%, and the practical recommendation about human-in-the-loop requirements.

However: there are unresolved URLs in Additional Resources (TODO items), the Lambda pipeline lacks DLQ/error handling, no data retention policy is specified for PHI stored in DynamoDB, and the VPC endpoint list is incomplete. Two HIGH findings, zero CRITICAL. Verdict: PASS.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### Strengths

Strong HIPAA foundation: BAA explicitly required, SSE-KMS on S3, DynamoDB encryption at rest, Neptune encryption at rest, all API calls over TLS. CloudTrail enabled for Comprehend Medical API auditing. VPC deployment specified for production with VPC endpoints for S3, Comprehend Medical, DynamoDB, and CloudWatch Logs. IAM permissions listed per-action and appropriately scoped. The Prerequisites table is one of the most thorough in Chapter 8.

#### Issue S1: No Data Retention or Lifecycle Policy for PHI in DynamoDB/Neptune (HIGH)

**Location:** Prerequisites table; Architecture Diagram; Step 6 pseudocode (`generate_timeline`)

**Problem:** The recipe stores patient timelines in DynamoDB (and optionally Neptune) containing patient_id, document_id, event text excerpts from clinical notes, timestamps, and temporal relationships. No TTL, retention period, or lifecycle policy is specified. The `temporal_relations` array and timeline entries contain clinical event text that constitutes PHI.

At scale (1000 patients, 20 notes/patient/year, 5 timeline events/note), this accumulates 100,000 PHI-containing records per year with no automated cleanup. HIPAA requires documented retention and disposal policies.

**Fix:** Add to Prerequisites table: "Data Lifecycle: DynamoDB TTL configured per institutional records retention policy (typically 7-10 years adult, longer for minors). Neptune graph data lifecycle managed via scheduled deletion jobs. S3 lifecycle policy for processed clinical notes." Add a note to Step 6 pseudocode: "Configure TTL on timeline records. Align retention with source document retention policy."

#### Issue S2: Temporal Graph Evidence Field Stores Unbounded Clinical Context (MEDIUM)

**Location:** Step 4 pseudocode, `evidence: context_window` field in classified_relations

**Problem:** Each classified relation stores the full `context_window` (3 sentences on each side of entity pairs) as evidence for audit trail. This context contains arbitrary clinical narrative from the source note, expanding PHI surface area beyond what downstream consumers need. A system querying "timeline events for patient X" receives temporal ordering (needed) plus raw clinical narrative snippets (not needed for timeline display, increases breach exposure).

**Fix:** Add guidance: "Store evidence context in a separate audit table with restricted access. Downstream timeline APIs should return only event_text, event_type, timestamp, and confidence. Consumers needing full context should retrieve from the source note with access logging."

#### Issue S3: Training Corpus Storage Lacks Specific Access Control Guidance (MEDIUM)

**Location:** Prerequisites table, Training Data row; "Why These Services" S3 paragraph

**Problem:** The recipe mentions "temporal relation annotated clinical corpus (minimum 500-1000 annotated documents)" stored in S3 but provides no guidance on access control for this corpus. Annotated clinical documents contain PHI. The corpus is a high-value target: it contains both clinical text and human-annotated temporal relationships (making it easier to extract structured information from the PHI).

**Fix:** Add: "Training corpus S3 bucket: separate from inference pipeline bucket. Bucket policy restricts access to ML training roles only. Enable S3 access logging. Versioning enabled for annotation provenance. Consider de-identification of training corpus if institutional policy permits."

#### Issue S4: IAM Permission for Comprehend Custom Classification Not Resource-Scoped (LOW)

**Location:** Prerequisites table, IAM Permissions row

**Problem:** `comprehend:ClassifyDocument` without resource scoping allows the Lambda to call any Comprehend custom classification endpoint in the account.

**Fix:** Scope to specific endpoint ARN: `arn:aws:comprehend:{region}:{account}:document-classifier-endpoint/temporal-relation-*`.

---

### Architecture Expert Review

#### Strengths

The six-stage pipeline is well-architected: each stage has clear responsibility boundaries, stateless processing enables horizontal scaling, and the design correctly separates temporal expression recognition (rule-based, fast, deterministic) from relation classification (ML-based, slower, probabilistic). The candidate pair generation heuristics (same-sentence, adjacent-sentence, signal-connected, nearest-anchor) are the right approach to managing quadratic pair explosion. The temporal constraint propagation with cycle detection and lowest-confidence-edge removal is a sophisticated and correct approach to graph consistency. The optional Neptune for graph querying vs. DynamoDB for flat timeline storage gives appropriate architecture choices for different use cases.

The cost estimate (~$0.03/note) is realistic for the described architecture. The throughput estimate (10-20 notes/second with Lambda concurrency) is achievable.

#### Issue A1: No Error Handling, DLQ, or Partial-Completion Logic in Pipeline (HIGH)

**Location:** Architecture Diagram; "Why These Services" Lambda/Step Functions paragraphs

**Problem:** The recipe mentions Step Functions for orchestration but the architecture diagram shows a linear flow with no error paths. If Comprehend Medical throttles, Comprehend Custom Classification times out (cold endpoint), or DynamoDB write fails (throughput exceeded), the pipeline has no documented recovery path.

The recipe processes clinical notes that need temporal extraction for downstream systems (medication reconciliation, clinical trial screening, pharmacovigilance). A silently dropped note means a patient's timeline has a gap. With 200 notes/hour and 2% transient failure rate: 4 notes/hour lost with no alerting.

Step Functions is mentioned but never shown in the diagram or pseudocode. Its retry logic and error handling capabilities are referenced but not designed.

**Fix:** Add to Architecture Diagram: error paths to an SQS DLQ for failed notes. Add to "Why These Services" Step Functions paragraph: "Step Functions Retry configuration: MaxAttempts=3 with exponential backoff for Comprehend throttling. Catch block routes to DLQ after retries exhausted. CloudWatch alarm on DLQ depth > 10. Failed notes are reprocessed on next pipeline run or escalated for manual review." Add brief error handling guidance to pseudocode Step 4 (the most failure-prone step due to multiple classification calls per note).

#### Issue A2: Candidate Pair Generation Heuristics May Miss Clinically Important Long-Range Relations (MEDIUM)

**Location:** Step 3 pseudocode, `generate_candidate_pairs` function

**Problem:** The heuristics filter to same-sentence, adjacent-sentence, signal-connected, and nearest-temporal pairs. The recipe claims this "reduces workload by 80-90% without meaningful recall loss." However, clinical discharge summaries commonly have important temporal relations spanning multiple paragraphs:

- HPI mentions "admitted March 3 with cholecystitis" (paragraph 1)
- Hospital Course mentions "POD#1 afebrile" (paragraph 4)
- These have an important temporal relationship but are neither same-sentence, adjacent-sentence, nor signal-connected

The recipe acknowledges this in "Where it struggles" but doesn't provide an architectural solution for the high-value cross-section pairs.

**Fix:** Add a fifth heuristic: "Section-anchored pairs: events in different sections that share a temporal expression or are both anchored to the same clinical episode (same admission, same procedure). This captures cross-section relationships like HPI events linked to Hospital Course events." Alternatively, add a note: "For discharge summaries, consider a 'same-admission' heuristic that pairs all events within a single hospitalization regardless of section distance."

#### Issue A3: Neptune as Optional but No Guidance on When It's Needed (LOW)

**Location:** "Why These Services" Neptune paragraph; Architecture Diagram

**Problem:** Neptune is listed as optional but the recipe doesn't clearly articulate the decision criteria. A reader doesn't know when to use DynamoDB-only vs. DynamoDB+Neptune.

**Fix:** Add decision criteria: "Use DynamoDB alone when: downstream consumers only need the flattened timeline (chronological event list). Add Neptune when: you need to query temporal graph structure (e.g., 'find all events that overlap with the hospitalization,' 'what happened between medication start and adverse event'), traverse multi-hop temporal paths, or run temporal pattern queries across patients."

---

### Networking Expert Review

#### Strengths

VPC deployment recommended for production. VPC endpoints specified for S3, Comprehend Medical, DynamoDB, and CloudWatch Logs. All API calls over TLS (standard for AWS SDK). Neptune, when used, runs within the VPC by design (it has no public endpoint option), so PHI in the graph database never traverses the public internet.

#### Issue N1: Missing VPC Endpoint for Comprehend Custom Classification (MEDIUM)

**Location:** Prerequisites table, VPC row

**Problem:** The VPC row specifies endpoints for "S3, Comprehend Medical, DynamoDB, CloudWatch Logs." However, the architecture uses Amazon Comprehend Custom Classification (a different service endpoint from Comprehend Medical). Without a VPC endpoint for `com.amazonaws.{region}.comprehend`, relation classification calls (Step 4) would route through a NAT gateway or IGW, sending clinical text context windows over the public internet path.

The recipe makes ~50 classification calls per note (one per candidate pair). Each call sends a context window containing clinical narrative excerpts. This is PHI traversing outside the VPC unless the Comprehend VPC endpoint is configured.

**Fix:** Update VPC row to: "VPC endpoints for S3, Comprehend Medical, Comprehend, DynamoDB, CloudWatch Logs, Step Functions." Add note: "Comprehend Medical and Comprehend (custom classification) use different VPC endpoint configurations."

#### Issue N2: No Mention of Neptune VPC Security Group Configuration (LOW)

**Location:** Prerequisites table; "Why These Services" Neptune paragraph

**Problem:** Neptune requires a VPC security group that restricts inbound access to port 8182. The recipe doesn't mention security group configuration for Neptune. A misconfigured security group (0.0.0.0/0 inbound on 8182) would expose the temporal graph to any resource in the VPC.

**Fix:** Add to Prerequisites: "Neptune security group: inbound TCP 8182 restricted to Lambda security group only. No public access (Neptune has no public endpoint, but security group still matters for VPC-internal isolation)."

---

### Voice Reviewer

#### Strengths

This recipe is one of the strongest in the book for voice consistency. The opening paragraph immediately pulls the reader in with a concrete clinical scenario, then systematically dismantles the assumption that "just extracting dates" is sufficient. The technology section maintains the "engineer explaining something fascinating" tone throughout. Phrases like "Oh, and the discharge date? Nowhere explicitly. You have to calculate it" and "the story is the diagnosis" nail the voice perfectly.

The "Honest Take" is exceptional: "Then you deploy it and realize that 0.75 F1 on curated benchmark data translates to maybe 0.60 on your institution's actual clinical notes" is exactly the kind of self-deprecating expertise that characterizes this book's voice. The practical wisdom ("spend less time on the relation classifier and more time on the candidate pair generation") is the kind of non-obvious insight that distinguishes this from a textbook.

The 70/30 vendor balance is well-maintained: the Technology section (~3500 words) is entirely vendor-agnostic, the General Architecture Pattern section is vendor-agnostic, and only the AWS Implementation section introduces service names. Comfortably within the target ratio.

#### Issue V1: "TODO" Items in Additional Resources Break Reader Trust (MEDIUM)

**Location:** Additional Resources section, "Research and Standards" and "Clinical NLP Resources" subsections

**Problem:** Four "TODO: Verify current URL" entries appear in the published recipe:
- "TODO: Verify current URL for THYME corpus access"
- "TODO: Verify current URL for i2b2 2012 Temporal Relations shared task dataset access"
- "TODO: Verify current URL for HeidelTime temporal expression recognition tool"
- "TODO: Verify current URL for Apache cTAKES temporal module documentation"

These are editorial artifacts that should never appear in a published recipe. They undermine the recipe's authority and the reader's trust.

**Fix:** Either verify and add the correct URLs, or replace with descriptive text: "THYME corpus: available through the University of Colorado / Mayo Clinic collaboration. Contact the THYME project team for access." "i2b2 datasets: access through n2c2 (successor to i2b2 challenges) at [portal URL]." "HeidelTime: available on GitHub under the HeidelTime project." "Apache cTAKES: temporal module documentation available at the Apache cTAKES project site."

#### Issue V2: One Instance of Em Dash Usage (LOW)

**Location:** Technology section, "Why This Is Genuinely Hard" subsection

**Problem:** The text contains: "Here's why, and I'm not exaggerating the difficulty." While this specific instance doesn't contain an em dash, upon closer inspection the recipe is clean of em dashes throughout. No finding here. Retracted.

**Correction:** No em dashes found in the recipe. This is clean.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

**Security (S1) and Architecture (A1) overlap on DynamoDB:** S1 flags missing retention policy; A1 flags missing error handling. Both relate to the DynamoDB storage layer but address different concerns (data lifecycle vs. operational resilience). Both are HIGH. No conflict; both fixes are needed independently.

**Security (S2) and Architecture (A2) both involve context handling:** S2 flags that storing full context windows expands PHI surface area; A2 flags that the heuristics miss long-range relations. These don't conflict. The context window fix (S2) is about what gets stored after classification. The heuristic fix (A2) is about what gets classified in the first place.

**Networking (N1) and the overall architecture:** The missing Comprehend VPC endpoint (N1) is a straightforward fix that doesn't conflict with any other recommendations. It's significant because Step 4 makes ~50 calls per note, each carrying clinical narrative.

### Priority Resolution

The TODO items (V1) are unusual: they're a MEDIUM voice finding but they signal that the recipe was published in an incomplete state. They're easy to fix but embarrassing if shipped. Prioritized above other MEDIUM findings because they're visible to every reader immediately.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

Two HIGH findings, both architectural/security concerns with clear fixes. No CRITICAL findings. The recipe's clinical accuracy is strong, the technology explanation is genuinely educational, the architecture pattern is sound, and the voice is among the best in the book.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Prerequisites; Step 6 | No data retention/lifecycle policy for PHI in DynamoDB/Neptune | Add TTL configuration, retention policy aligned with institutional requirements, lifecycle documentation |
| 2 | HIGH | Architecture | Architecture Diagram; Step Functions | No error handling, DLQ, or retry logic for pipeline failures | Add SQS DLQ, Step Functions retry config, CloudWatch alarm on DLQ depth |
| 3 | MEDIUM | Networking | Prerequisites, VPC row | Missing VPC endpoint for Comprehend Custom Classification (separate from Comprehend Medical) | Add `com.amazonaws.{region}.comprehend` VPC endpoint to requirements |
| 4 | MEDIUM | Voice | Additional Resources | Four "TODO: Verify current URL" items in published recipe | Replace with verified URLs or descriptive access instructions |
| 5 | MEDIUM | Security | Step 4 pseudocode | Evidence field stores unbounded clinical context, expanding PHI surface | Separate audit table for context; downstream APIs return only structured fields |
| 6 | MEDIUM | Security | Prerequisites, Training Data | Training corpus lacks specific access control guidance | Separate bucket, restricted access, access logging, versioning |
| 7 | MEDIUM | Architecture | Step 3 pseudocode | Candidate pair heuristics miss clinically important cross-section relations | Add section-anchored or same-admission heuristic for discharge summaries |
| 8 | LOW | Architecture | Neptune paragraph | No decision criteria for when to add Neptune vs. DynamoDB-only | Add clear decision criteria based on query patterns |
| 9 | LOW | Security | Prerequisites, IAM | Comprehend Custom Classification not resource-scoped | Scope to specific endpoint ARN pattern |
| 10 | LOW | Networking | Prerequisites | No Neptune security group configuration guidance | Add security group recommendation restricting port 8182 to Lambda SG |

---

### Summary

This is a high-quality recipe that delivers on its promise: a reader finishes understanding temporal relationship extraction as a concept, why it's one of the hardest problems in clinical NLP, and how to build a production pipeline. The clinical accuracy is strong (correct F1 benchmarks, appropriate references to i2b2/THYME, honest acknowledgment of the gap between benchmark and real-world performance). The architecture is sound for the stated complexity level.

The two HIGH findings (missing data lifecycle policy, missing error handling) are the same infrastructure gaps that appear across multiple Chapter 8 recipes and should be addressed systematically. The TODO items in Additional Resources need resolution before publication. The missing VPC endpoint for Comprehend (distinct from Comprehend Medical) is a networking oversight that could result in PHI traversing outside the VPC.

The recipe's greatest strength is its honesty about the state of the field and its practical recommendation hierarchy: rule-based temporal expression recognition (solved), heuristic ordering (gets you 70%), ML for ambiguous cases (helps but imperfect), human-in-the-loop for high-stakes downstream use. This is exactly the kind of pragmatic guidance the book promises.
