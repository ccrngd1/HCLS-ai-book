# Recipe 13.5: Clinical Pathway / Protocol Modeling

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.10 to $0.50 per pathway query (graph traversal + reasoning)

---

## The Problem

A hospitalist admits a patient with community-acquired pneumonia. The hospital has a clinical pathway for this: a sequence of assessments, lab orders, antibiotic choices, escalation criteria, and discharge readiness checks. It lives in a 14-page PDF on the intranet. Maybe there's a laminated card somewhere in the nursing station. The pathway was updated six months ago, but the laminated card still shows the old antibiotic recommendations.

This is the state of clinical pathway management at most health systems. Pathways exist as static documents. They encode complex decision logic ("if CURB-65 score >= 3, consider ICU admission; if penicillin allergy documented, substitute with respiratory fluoroquinolone") but that logic is trapped in prose. It can't be queried. It can't be traversed programmatically. It can't tell you whether a specific patient is on-pathway or has deviated. It can't alert you when a new step becomes relevant based on a lab result that just came back.

The scale of this problem is significant. A typical academic medical center maintains 200-400 active clinical pathways covering everything from sepsis management to elective joint replacement recovery. Each pathway has decision branches, time-dependent steps, conditional orders, and escalation criteria. Keeping them current requires clinical committee review. Keeping clinicians aware of them requires training. Measuring adherence requires manual chart review.

Order sets help, but they're flat. They give you a menu of things to order at a point in time. They don't model the temporal flow: "do this first, then wait for this result, then decide between these two branches." Clinical pathways are inherently graph-shaped: nodes are clinical states or actions, edges are transitions triggered by conditions. The moment you recognize that, the solution becomes obvious. Model them as graphs. Traverse them computationally. Use the graph to drive decision support, compliance tracking, and variance analysis.

Let's build it.

---

## The Technology: Graphs for Clinical Logic

### Why Graphs Fit Clinical Pathways

A clinical pathway is a directed graph. Not metaphorically. Literally. Consider a simplified pneumonia pathway:

1. Patient presents with suspected pneumonia
2. Order chest X-ray and blood cultures
3. Calculate severity score (CURB-65 or PSI)
4. **Decision point:** If mild (CURB-65 0-1), outpatient treatment. If moderate (2), admit to ward. If severe (3+), consider ICU.
5. For ward admission: start empiric antibiotics within 4 hours
6. Reassess at 48 hours: if improving, step down to oral. If not improving, escalate.
7. Discharge criteria: afebrile 24h, tolerating oral meds, oxygen saturation stable

Each numbered item is a node. The transitions between them have conditions attached. Some transitions are time-gated ("reassess at 48 hours"). Some are event-driven ("lab result returns"). Some are conditional on patient state ("if penicillin allergy"). This is a directed acyclic graph (mostly; some pathways have loops for reassessment cycles) with typed edges.

Relational databases can store this, but querying it is painful. "Given this patient's current state, what are the next valid steps?" becomes a recursive SQL query with multiple joins against condition tables. Graph databases make this query natural: start at the patient's current node, traverse outgoing edges where conditions are satisfied, return the reachable next nodes.

### Knowledge Graph Fundamentals for Pathways

A knowledge graph for clinical pathways needs several entity types:

**Pathway nodes** represent clinical states or actions. Each node has a type: assessment, order, decision point, milestone, or discharge criterion. Nodes carry metadata: responsible role (physician, nurse, pharmacist), expected duration, required documentation.

**Edges** represent transitions. Each edge has conditions that must be satisfied for the transition to be valid. Conditions reference patient data: lab values, vital signs, elapsed time, documented assessments, allergy status. Edges also have a type: sequential (must happen in order), parallel (can happen simultaneously), conditional (only one branch taken), or time-gated (available after a delay).

**Condition nodes** represent the logic attached to edges. A condition might be simple ("CURB-65 >= 3") or compound ("temperature < 38.0 AND oral intake adequate AND oxygen saturation > 92% on room air"). Modeling conditions as first-class graph entities (rather than edge properties) lets you reuse them across pathways and reason about them independently.

**Evidence nodes** link pathway decisions to their clinical evidence base. Why is the antibiotic window 4 hours? Because studies showed mortality benefit. Attaching evidence provenance to pathway nodes supports clinical governance and makes pathway updates traceable to their justification.

### The Traversal Problem

The core computational operation is: given a patient's current clinical state, which pathway nodes are active, which transitions are available, and which next actions are recommended?

This requires:

1. **State mapping:** Determine which pathway node(s) the patient currently occupies. A patient can be at multiple nodes simultaneously (parallel branches). This requires matching the patient's documented actions and results against node completion criteria.

2. **Condition evaluation:** For each outgoing edge from active nodes, evaluate whether the transition conditions are met given current patient data. This means pulling real-time data from the EHR: latest labs, vitals, documented assessments, active orders.

3. **Traversal:** Follow satisfied edges to identify recommended next actions. Handle parallel paths (multiple next steps available simultaneously) and exclusive branches (only one path should be taken).

4. **Variance detection:** Identify when a patient's actual care deviates from the pathway. An order placed that isn't on the pathway. A pathway step that should have happened by now but hasn't. A branch taken that doesn't match the patient's condition data.

### Temporal Reasoning

Clinical pathways are deeply temporal. "Start antibiotics within 4 hours of presentation." "Reassess at 48 hours." "If no improvement after 72 hours, consider CT pulmonary angiography." The graph needs a time dimension.

This means edges can have temporal constraints: minimum elapsed time before a transition is valid, maximum elapsed time before a transition becomes overdue (triggering an alert), and absolute time windows (e.g., "blood cultures before first antibiotic dose" is a sequencing constraint, not a clock constraint).

Temporal reasoning in graphs is harder than it sounds. You need to track when each node was entered, compute elapsed time relative to pathway entry or node entry, and handle clock resets (patient transferred to ICU resets certain timers). Most graph databases don't have native temporal operators, so you'll implement this in your traversal logic layer.

### Ontology Integration

Pathways don't exist in isolation. They reference clinical concepts: diagnoses (ICD-10), procedures (CPT), medications (RxNorm), lab tests (LOINC). Your pathway graph needs to connect to these standard ontologies so that conditions like "if creatinine > 2.0" can be evaluated against actual LOINC-coded lab results from the EHR.

This is where knowledge graphs shine over simpler representations. The pathway graph can link to a drug ontology for allergy cross-referencing, a diagnosis hierarchy for pathway applicability rules, and a lab ontology for result interpretation. These connections enable reasoning that would be impossible with a flat pathway document: "this patient is on the pneumonia pathway, but they also have CKD stage 4, which means the standard antibiotic dosing needs renal adjustment."

### The General Architecture Pattern

```text
[Pathway Authoring] → [Graph Store] ← [Patient State Engine]
                                     ↓
                          [Traversal / Reasoning Engine]
                                     ↓
                    [CDS Alerts] + [Compliance Dashboard] + [Variance Reports]
```

**Pathway Authoring:** Clinical informaticists model pathways as graphs using a structured editor. The editor enforces graph validity: no orphan nodes, all decision points have at least two outgoing edges, all terminal nodes are marked as endpoints.

**Graph Store:** A graph database holds the pathway definitions. Separate from patient data. The pathway graph is the "knowledge" layer; patient state is the "data" layer.

**Patient State Engine:** Continuously maps each patient's current clinical state to their position(s) on applicable pathways. Consumes EHR events (orders placed, results received, assessments documented) and updates the patient's pathway position.

**Traversal / Reasoning Engine:** Given a patient's current position and clinical data, traverses the graph to determine next recommended actions, overdue steps, and available transitions. This is the query engine that powers all downstream use cases.

**Downstream consumers:** Clinical decision support (alerts at point of care), compliance dashboards (what percentage of patients are on-pathway), and variance reports (which deviations are most common, and do they correlate with outcomes).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.05-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you about this project: the technology is the easy part. Graph databases handle traversal queries beautifully. Serverless compute scales fine. Key-value stores are fast. The hard part is getting clinical pathways out of people's heads and into a structured graph format.

Most clinical pathways exist as Word documents or PDFs written by committee. They contain ambiguous language ("consider escalation if not improving"), implicit knowledge ("experienced clinicians know to check lactate here even though it's not written down"), and institutional variation ("we do it this way because Dr. Martinez prefers it"). Converting that into a formal graph with explicit conditions requires clinical informaticists who understand both the medicine and the data model. Budget more time for pathway modeling than for engineering.

The versioning problem is real. When the pneumonia pathway gets updated (new antibiotic recommendations from IDSA), patients currently on version 2 need to complete under version 2. New admissions get version 3. Your system needs to handle multiple active versions simultaneously. This isn't hard technically (version is a property on every node and edge, and every traversal query filters by the patient's enrolled version), but it's operationally complex: who decides when to sunset old versions? What if a patient is on a pathway for 30 days and it gets updated twice? A migration function can optionally re-enroll patients on the new version if the clinical committee approves mid-pathway transitions, but that's a policy decision, not a technical one.

Variance detection sounds great in theory. In practice, you'll discover that 40-60% of patients deviate from pathways for clinically appropriate reasons. The pathway says "start antibiotics within 4 hours" but the patient refused, or had an anaphylaxis history that required allergy testing first, or was in radiology for an urgent CT. Your variance reports will be noisy until you build a "justified variance" mechanism where clinicians can document why they deviated. Without it, the compliance dashboard becomes meaningless noise that everyone ignores.

The condition evaluation layer is where performance problems hide. If evaluating a transition condition requires calling an EHR API to get the latest lab result, and that API takes 800ms, your "real-time CDS" is suddenly not real-time. Cache aggressively. Pre-fetch patient data when you know a CDS query is likely (patient chart opened). Accept that some conditions will be evaluated against slightly stale data and design your alerts accordingly.

---

## Related Recipes

- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** The allergy and drug interaction checks referenced in pathway conditions can pull from this recipe's interaction graph.
- **Recipe 13.6 (Care Gap Reasoning Engine):** Uses similar ontological reasoning patterns but focused on preventive care guidelines rather than acute treatment pathways.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Pathway applicability rules often reference diagnosis hierarchies modeled in this recipe.
- **Recipe 7.5 (30-Day Readmission Risk):** Pathway compliance data can feed readmission risk models as a feature.

---

## Tags

`knowledge-graph` · `clinical-pathways` · `decision-support` · `neptune` · `graph-database` · `protocol-modeling` · `compliance` · `cds` · `medium` · `eventbridge` · `dynamodb` · `hipaa`

---

*← [Recipe 13.4: Drug-Drug Interaction Knowledge Base](chapter13.04-drug-drug-interaction-knowledge-base) · [Chapter 13 Index](chapter13-preface) · [Next: Recipe 13.6: Care Gap Reasoning Engine →](chapter13.06-care-gap-reasoning-engine)*
