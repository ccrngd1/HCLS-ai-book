# Recipe 13.6: Care Gap Reasoning Engine

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.002 per patient evaluation

---

## The Problem

Here's a scenario that plays out every single day in population health management: a 62-year-old diabetic patient with hypertension hasn't had an HbA1c test in 14 months, is overdue for a retinal exam, and has no record of a statin prescription despite meeting every clinical guideline criterion for one. Three care gaps. Three missed opportunities. Three potential quality measure failures.

Now multiply that by 50,000 attributed lives in a health plan. The quality team is running SQL queries against claims data, cross-referencing spreadsheets of HEDIS measure specifications, and manually flagging patients who appear to be missing recommended services. It's slow, brittle, and incomplete. Every time a guideline updates (which happens annually for most quality programs), someone has to rewrite the logic. Every time a patient's condition list changes, the applicable rules change too. The combinatorial explosion of conditions, age brackets, medications, and recommended services is genuinely hard to manage with flat rule tables.

The real cost isn't just operational. Missed care gaps translate directly into worse patient outcomes, lower quality scores, reduced reimbursement under value-based contracts, and (in Medicare Advantage) lower Star Ratings that affect enrollment and revenue. CMS estimates that closing preventive care gaps could prevent hundreds of thousands of hospitalizations annually. The gap between "what guidelines recommend" and "what actually happens" is one of the most expensive problems in healthcare.

What we need is a system that can reason about which guidelines apply to a given patient based on their conditions, demographics, and medication history, and then determine which recommended actions haven't been completed. That's a reasoning problem, not a lookup problem. And knowledge graphs are exceptionally good at reasoning problems.

---

## The Technology: Ontological Reasoning for Clinical Guidelines

### What Is a Knowledge Graph?

A knowledge graph is a data structure that represents information as entities (nodes) connected by typed relationships (edges). Unlike a relational database where relationships are implicit in foreign keys, a knowledge graph makes relationships first-class citizens. You can ask questions like "what is connected to this node, and how?" without knowing the schema in advance.

In a simple example: the node "Type 2 Diabetes" connects to the node "HbA1c Test" via a relationship "requires_monitoring_with." The node "HbA1c Test" has a property "recommended_frequency: every 6 months." That's a tiny piece of clinical knowledge encoded as a graph.

### What Is Ontological Reasoning?

Ontological reasoning is the process of deriving new facts from existing facts using logical rules. If you know that "Type 2 Diabetes is-a Chronic Condition" and "All Chronic Conditions require Annual Review," you can infer that "Type 2 Diabetes requires Annual Review" without anyone explicitly stating that fact. The reasoner derives it.

This is powerful for care gaps because clinical guidelines are inherently hierarchical and conditional. A guideline might say: "For patients with diabetes AND age over 40 AND no documented cardiovascular disease, recommend statin therapy." That's a conjunction of conditions leading to a recommendation. An ontological reasoner can evaluate that conjunction against a patient's known facts and determine whether the recommendation applies.

### Why Knowledge Graphs for Care Gaps?

The alternative approaches each have significant limitations:

**Rule engines (flat if-then tables):** Work fine for simple cases but become unmanageable as the number of conditions, exceptions, and interactions grows. When you have 200 quality measures, each with 3-10 inclusion/exclusion criteria, and those criteria reference conditions that have their own hierarchies (ICD-10 codes roll up into condition groups), flat rules become a maintenance nightmare. You end up with thousands of rules that nobody can audit holistically.

**SQL-based approaches:** Claims queries can identify patients missing specific services, but they struggle with the "which guidelines apply to this patient" question. The logic for determining applicability is complex, conditional, and hierarchical. Encoding it in SQL produces queries that are hundreds of lines long, fragile to schema changes, and nearly impossible to validate against the source guideline text.

**Knowledge graphs solve both problems.** The guideline logic lives in the graph structure itself. "Diabetes requires HbA1c monitoring" is a relationship. "HbA1c monitoring has frequency every 6 months" is a property. "Patient X has condition Diabetes" is another relationship. The reasoner traverses these connections and determines: Patient X should have had an HbA1c within the last 6 months. Did they? That's a graph query, not a hand-coded rule.

The maintenance advantage is significant. When a guideline updates (say, the recommended HbA1c frequency changes from every 6 months to every 3 months for uncontrolled diabetes), you update one property on one node. Every patient evaluation automatically picks up the change. No code deployment. No SQL rewrite. No regression testing of rule logic.

### How the Reasoning Works

The reasoning engine operates in three phases:

**Phase 1: Patient context assembly.** Gather everything known about the patient: active conditions (from problem lists and claims), demographics (age, sex), current medications, recent procedures and lab results. This becomes the patient's "fact set" in the graph.

**Phase 2: Guideline applicability.** Traverse the guideline ontology to determine which recommendations apply to this patient. A recommendation applies when all of its preconditions are satisfied by the patient's fact set. This is where the hierarchical reasoning matters: if the guideline says "patients with cardiovascular disease" and the patient has "coronary artery disease," the reasoner needs to know that coronary artery disease is-a cardiovascular disease.

**Phase 3: Gap identification.** For each applicable recommendation, check whether the recommended action has been completed within the specified timeframe. If not, that's a care gap. The output is a list of gaps with their clinical justification (why this recommendation applies to this patient) and priority (based on clinical urgency and quality measure impact).

### What Makes This Hard

**Condition hierarchy mapping.** Clinical guidelines reference condition groups ("cardiovascular disease"), but patient records contain specific diagnoses (ICD-10 codes like I25.10 for atherosclerotic heart disease). You need a complete mapping from specific codes to condition groups, and those mappings aren't always clean. Some codes map to multiple groups. Some are ambiguous. SNOMED CT provides a formal ontology for this, but integrating it with ICD-10 coded claims data requires careful crosswalking.

**Temporal reasoning.** "HbA1c within the last 6 months" requires knowing when the last HbA1c was performed. Claims data has service dates. Lab results have collection dates. These don't always agree. And "within the last 6 months" from when? From today? From the measurement year end? From the patient's next scheduled visit? Different quality programs define "current" differently.

**Exclusion logic.** Guidelines have exclusions that are just as important as inclusions. "Recommend colonoscopy for patients age 45-75, EXCEPT those with a history of total colectomy." The exclusion logic can be complex: some exclusions are permanent (colectomy), some are temporary (pregnancy), some are conditional (hospice enrollment). Your reasoner must handle all three types.

**Evidence currency.** Patient data arrives with varying latency. Claims data is typically 30-90 days behind. Lab results might be same-day from an integrated system or 60 days delayed from an external lab. A care gap identified today might already be closed by a service performed last week that hasn't been reported yet. False positive gaps erode trust in the system.

**Guideline conflicts.** Different guidelines sometimes contradict each other, or a patient's comorbidities create situations where following one guideline would violate another. A patient on anticoagulation therapy might have a guideline recommending aspirin for cardiovascular prevention, but the combination increases bleeding risk. The reasoner needs to surface these conflicts, not silently pick one.

### The General Architecture Pattern

```text
[Patient Data Sources] → [Fact Assembly] → [Knowledge Graph] ← [Guideline Ontology]
                                                    ↓
                                           [Reasoning Engine]
                                                    ↓
                                        [Gap Identification]
                                                    ↓
                              [Priority Scoring] → [Care Gap Output]
```

**Patient Data Sources:** EHR problem lists, claims/encounters, lab results, medication lists, demographics. These feed the patient's fact set.

**Guideline Ontology:** The encoded clinical guidelines, condition hierarchies, and recommendation rules. This is the "knowledge" in the knowledge graph. It's maintained separately from patient data and versioned independently.

**Reasoning Engine:** The component that evaluates patient facts against guideline rules. It performs the applicability check and the completion check for each recommendation.

**Priority Scoring:** Not all gaps are equal. A missed cancer screening is more urgent than a slightly overdue wellness visit. Priority considers clinical urgency, quality measure impact, and patient-specific risk factors.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.06-architecture). The Python example is linked from there.

## The Honest Take

The knowledge graph approach to care gaps is genuinely elegant when it works. The first time you update a guideline property and watch it cascade correctly across 50,000 patient evaluations without touching a line of code, you'll feel like you've built something right.

But here's what will humble you:

The ontology authoring is the hardest part, and it's not a technology problem. It's a clinical informatics problem. Translating a 40-page HEDIS technical specification into a formal ontology requires someone who understands both the clinical intent and the logical formalism. Those people are rare. Budget significant time for ontology development and clinical validation.

The false positive problem is real and corrosive. If 10% of your identified gaps are already closed (the patient got their HbA1c last week, but the claim hasn't processed yet), care managers learn to distrust the system. You need a feedback loop where closed gaps are confirmed and the false positive rate is tracked as a system health metric. Consider supplementing claims data with real-time ADT feeds or EHR integrations to reduce lag.

Exclusion logic will consume more of your time than inclusion logic. Every quality measure has a list of valid exclusions (hospice, terminal illness, patient refusal, specific contraindications). Missing an exclusion means flagging a gap that shouldn't exist. Getting exclusions right requires encoding not just conditions but also encounter types, medication contraindications, and sometimes free-text documentation. Start with the exclusions that are reliably coded (hospice, pregnancy) and accept that some will require manual review.

The part that surprised me most: the condition hierarchy mapping is never "done." ICD-10 updates annually. New codes appear. Existing codes get refined. Your mapping from ICD-10 codes to ontology condition classes needs annual maintenance, and the maintenance is tedious but critical. One unmapped code means one patient's gaps are silently missed.

---

## Related Recipes

- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Provides the condition hierarchy foundation that this recipe's ontological reasoning depends on
- **Recipe 13.5 (Clinical Pathway Protocol Modeling):** Models treatment protocols as graphs; care gaps are the delta between the protocol and reality
- **Recipe 7.6 (Rising Risk Identification):** Identifies patients whose risk is increasing; combine with care gaps to prioritize outreach to rising-risk patients with open gaps
- **Recipe 4.6 (Care Gap Prioritization):** Complements this recipe by adding personalization to gap outreach (which channel, what time, what message)

---

## Tags

`knowledge-graph` · `ontology` · `care-gaps` · `quality-measures` · `HEDIS` · `reasoning` · `SPARQL` · `population-health` · `value-based-care` · `Neptune`

---

*← [Recipe 13.5: Clinical Pathway Protocol Modeling](chapter13.05-clinical-pathway-protocol-modeling) · [Chapter 13 Index](chapter13-preface) · [Next: Recipe 13.7: Disease-Gene-Drug Relationship Graph →](chapter13.07-disease-gene-drug-relationship-graph)*
