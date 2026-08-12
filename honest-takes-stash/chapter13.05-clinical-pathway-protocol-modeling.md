<!-- Removed from chapter13.05-clinical-pathway-protocol-modeling.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you about this project: the technology is the easy part. Graph databases handle traversal queries beautifully. Serverless compute scales fine. Key-value stores are fast. The hard part is getting clinical pathways out of people's heads and into a structured graph format.

Most clinical pathways exist as Word documents or PDFs written by committee. They contain ambiguous language ("consider escalation if not improving"), implicit knowledge ("experienced clinicians know to check lactate here even though it's not written down"), and institutional variation ("we do it this way because Dr. Martinez prefers it"). Converting that into a formal graph with explicit conditions requires clinical informaticists who understand both the medicine and the data model. Budget more time for pathway modeling than for engineering.

The versioning problem is real. When the pneumonia pathway gets updated (new antibiotic recommendations from IDSA), patients currently on version 2 need to complete under version 2. New admissions get version 3. Your system needs to handle multiple active versions simultaneously. This isn't hard technically (version is a property on every node and edge, and every traversal query filters by the patient's enrolled version), but it's operationally complex: who decides when to sunset old versions? What if a patient is on a pathway for 30 days and it gets updated twice? A migration function can optionally re-enroll patients on the new version if the clinical committee approves mid-pathway transitions, but that's a policy decision, not a technical one.

Variance detection sounds great in theory. In practice, you'll discover that 40-60% of patients deviate from pathways for clinically appropriate reasons. The pathway says "start antibiotics within 4 hours" but the patient refused, or had an anaphylaxis history that required allergy testing first, or was in radiology for an urgent CT. Your variance reports will be noisy until you build a "justified variance" mechanism where clinicians can document why they deviated. Without it, the compliance dashboard becomes meaningless noise that everyone ignores.

The condition evaluation layer is where performance problems hide. If evaluating a transition condition requires calling an EHR API to get the latest lab result, and that API takes 800ms, your "real-time CDS" is suddenly not real-time. Cache aggressively. Pre-fetch patient data when you know a CDS query is likely (patient chart opened). Accept that some conditions will be evaluated against slightly stale data and design your alerts accordingly.

---

