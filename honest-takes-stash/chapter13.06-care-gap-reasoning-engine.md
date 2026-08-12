<!-- Removed from chapter13.06-care-gap-reasoning-engine.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The knowledge graph approach to care gaps is genuinely elegant when it works. The first time you update a guideline property and watch it cascade correctly across 50,000 patient evaluations without touching a line of code, you'll feel like you've built something right.

But here's what will humble you:

The ontology authoring is the hardest part, and it's not a technology problem. It's a clinical informatics problem. Translating a 40-page HEDIS technical specification into a formal ontology requires someone who understands both the clinical intent and the logical formalism. Those people are rare. Budget significant time for ontology development and clinical validation.

The false positive problem is real and corrosive. If 10% of your identified gaps are already closed (the patient got their HbA1c last week, but the claim hasn't processed yet), care managers learn to distrust the system. You need a feedback loop where closed gaps are confirmed and the false positive rate is tracked as a system health metric. Consider supplementing claims data with real-time ADT feeds or EHR integrations to reduce lag.

Exclusion logic will consume more of your time than inclusion logic. Every quality measure has a list of valid exclusions (hospice, terminal illness, patient refusal, specific contraindications). Missing an exclusion means flagging a gap that shouldn't exist. Getting exclusions right requires encoding not just conditions but also encounter types, medication contraindications, and sometimes free-text documentation. Start with the exclusions that are reliably coded (hospice, pregnancy) and accept that some will require manual review.

The part that surprised me most: the condition hierarchy mapping is never "done." ICD-10 updates annually. New codes appear. Existing codes get refined. Your mapping from ICD-10 codes to ontology condition classes needs annual maintenance, and the maintenance is tedious but critical. One unmapped code means one patient's gaps are silently missed.

---

