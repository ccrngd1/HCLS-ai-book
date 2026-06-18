# Recipe 1.7: Prescription Label OCR 🔶

**Complexity:** Simple · **Phase:** Phase 2 · **Estimated Cost:** ~$0.08 per label

---

After the vision-model, dual-path, A2I architecture of Recipe 1.6, this recipe is deliberately focused. Prescription labels are highly structured, printed, single-page documents where the OCR-plus-NLP pipeline is the optimal choice. The goal here is to introduce medication ontology mapping (RxNorm, NDC) before the complexity returns for EOB processing in Recipe 1.8.

## The Problem

Someone just got out of the hospital. They're home, they're managing a new medication, and their care coordinator needs to know exactly what they're taking. The member opens their health plan's app and sees a prompt: "Upload a photo of your prescription label." They point their phone at the pill bottle, take a picture, and tap submit.

Now it's your problem.

The pill bottle is a cylinder. The label wraps around it. The photo has a slight curve. The lighting in their kitchen is uneven. They've already taken three pills from the bottle, so one corner of the label is a little worn. And the label itself reads something like: "Take 1 tab PO BID x 14d. Refills: 3. NDC: 0071-0155-23."

You need to turn that into this:

```json
{
  "drug_name": "Amoxicillin",
  "dosage": "500mg",
  "directions_decoded": "Take 1 tablet by mouth twice daily for 14 days",
  "rxnorm_id": "723",
  "ndc": "0071-0155-23",
  "refills_remaining": 3
}
```

Medication reconciliation sits at the heart of care transitions. When a patient moves from hospital to home, from primary care to specialist, from one plan year to the next, the handoff between care settings creates risk. A 2019 study published in JAMA found that adverse drug events were among the most common preventable patient safety incidents after hospital discharge. A significant portion of those trace back to incomplete or inaccurate medication information: the wrong dosage transcribed, the discontinued medication that stayed on the active list, the new prescription that nobody captured.

Health plans need accurate medication data to support medication management programs, identify adherence gaps, flag drug-drug interactions, and coordinate care across providers. But members don't think in NDC codes. They have a bottle in their hand. The gap between "bottle in hand" and "structured medication record" is where this recipe lives.

Prescription labels are, on the surface, simpler than many documents you'll encounter in healthcare. They're standardized by state pharmacy regulations. They're printed, not handwritten. They come from a constrained set of pharmacy chains (which helps with layout prediction). And they carry a finite set of fields.

But they are deceptively tricky to extract, for a handful of reasons that will cost you time if you don't plan for them. Let's get into why, before we talk about how to solve it.

---

## The Technology

### OCR on Curved Surfaces

If you've read Recipe 1.1 (Insurance Card Scanning), you already understand how modern OCR works at a conceptual level. Convolutional neural networks trained on millions of document images, character-region detection, bounding box coordinates that encode spatial relationships. All of that applies here.

What's different about prescription labels is the geometry.

An insurance card is flat. A prescription bottle is a cylinder. When you photograph a flat card, the text lies in a single plane relative to the camera. When you photograph a bottle, the text follows the curve of the cylinder. Characters near the edges of the label are at an angle relative to the camera lens, and this introduces geometric distortion that can make the edges of the label harder to read.

(For tightly printed labels, this matters a lot. For labels with generous font sizes, it matters less. The reality is that consumer medication bottle labels tend to use 8-10 point type to pack a lot of content into a small surface, so the curved-edge problem shows up more than you'd expect.)

There are a few ways to handle this in practice. The first is to accept the distortion and rely on modern OCR's robustness. State-of-the-art OCR models have seen enough real-world document photos that they handle moderate curvature reasonably well. The second is image preprocessing: undistortion algorithms can attempt to dewarp a cylindrical surface projection back to a flat plane before OCR runs. The third, most practical for a mobile app, is UX guidance: tell the member to lay the bottle on its side on a flat surface so the label faces the camera flat-on, and capture the front-facing portion of the label only. For most use cases, UX guidance is the highest-leverage improvement, and it costs you nothing in the OCR pipeline.

### Semi-Structured Documents with Constrained Vocabulary

Prescription labels are semi-structured. Every label has a drug name, a dosage, directions, a prescriber, a pharmacy, an Rx number, a fill date, and a refills count. The fields are consistent across labels. The layout varies by pharmacy chain, and the label text varies by how each pharmacy software system formats the same data.

CVS Pharmacy might print "Directions: Take 1 tablet by mouth twice daily." Walgreens might print "SIG: 1 TAB PO BID." A regional independent might print "Instructions: Take 1 cap 2x/day." All three say the same thing. Your extraction system needs to handle all three and normalize them to the same canonical representation.

This is the key-value problem from Recipe 1.1, applied to a pharmacy domain. The challenge here is narrower than insurance cards (there are fewer unique pharmacy chains than payers), but the directions field introduces a wrinkle: pharmacy abbreviations.

### Pharmacy Abbreviations and SIG Codes

The "SIG" field on a prescription label is the patient instruction line. SIG comes from the Latin "signa," meaning "label." Pharmacists have been using Latin abbreviation systems for drug instructions since before modern medicine. The system never really went away.

Here is what you will encounter:

| Abbreviation | Latin Origin | Meaning |
|---|---|---|
| QD or QDay* | quaque die | once daily |
| BID | bis in die | twice daily |
| TID | ter in die | three times daily |
| QID | quater in die | four times daily |
| PRN | pro re nata | as needed |
| PO | per os | by mouth |
| SL | sub lingua | under the tongue |
| AC | ante cibum | before meals |
| PC | post cibum | after meals |
| QHS | quaque hora somni | at bedtime |
| Q4H, Q6H, Q8H | quaque 4/6/8 hora | every 4/6/8 hours |
| TAB | tabella | tablet |
| CAP | capsula | capsule |
| GTT | gutta | drop |
| UD | ut dictum | as directed |

> *ISMP recommends against using "QD" in clinical documentation because it is frequently misread as "QID" (four times daily), a potentially dangerous dosing error. Included here because it still appears on older labels and in legacy pharmacy systems. When building patient-facing output, use "daily" instead of "QD."

A line like "Take 1 TAB PO BID x 14d PRN pain" is perfectly clear to a pharmacist and completely opaque to any downstream system that doesn't know the codebook. Parsing these abbreviations into human-readable, machine-processable text is a necessary step.

The good news: the SIG codebook is finite and well-established. There are about 150 common abbreviations that cover the vast majority of real-world prescriptions. Building a lookup table is straightforward. The tricky part is handling the abbreviations that have overlapping meanings in context: "QD" means "once daily" as a frequency, but some pharmacies use it inconsistently, and the similar-looking "QID" means "four times daily." Case-insensitive parsing with word-boundary matching handles most of the edge cases.

### Medical Ontologies: What RxNorm and NDC Actually Are

Here is where this recipe goes beyond what Recipe 1.1 covered, because prescription labels connect to two critical healthcare standards that are worth understanding before you try to map to them.

**NDC codes** are the National Drug Code, a unique identifier assigned by the FDA to every drug product sold in the United States. The FDA originally defined NDC codes in a 10-digit format with several possible segment structures (5-3-2, 5-4-1, or 4-4-2). HIPAA-mandated electronic transactions standardized the format to 11 digits using a zero-padded 5-4-2 structure: a 5-digit labeler code (the manufacturer), a 4-digit product code (the specific drug and strength), and a 2-digit package code (the package size and type). Labels typically use the FDA format (often 10 digits); downstream interoperability systems generally expect the 11-digit HIPAA-standardized form. The conversion is padding, not transformation. The NDC for "Amoxicillin 500mg capsules, 100 count from a specific manufacturer" is different from the NDC for "Amoxicillin 500mg capsules, 500 count from the same manufacturer," which is different from the NDC for the same drug from a different manufacturer. NDC codes are on every prescription label by law (in most states) and in most pharmacy dispensing systems. They are the most precise drug identifier available.

The problem with NDC codes for interoperability is that they identify the specific physical package dispensed. If you want to ask "is this the same drug as the one on the patient's existing medication list," you need to handle the fact that a fill at a different pharmacy, or a different package size, or a generic substitution, will have a different NDC. This is where RxNorm comes in.

**RxNorm** is a standardized drug nomenclature maintained by the National Library of Medicine. Where NDC identifies a specific packaged product, RxNorm identifies the clinical drug at an abstract level. The RxNorm concept ID for "Lisinopril 10mg oral tablet" is the same regardless of which manufacturer made it, which pharmacy dispensed it, or how it was packaged. Every NDC can be mapped to one or more RxNorm concept IDs via the NLM's RxNorm database.

For medication reconciliation, interoperability, and clinical decision support, RxNorm is the right identifier to work with. The pipeline in this recipe extracts the NDC directly from the label (it's printed there), then uses medical NLP to map the drug name and dosage to the corresponding RxNorm concept, giving downstream systems both the specific-product identifier and the clinical-equivalence identifier.

### Medical NLP for Entity and Concept Extraction

OCR turns an image into text. Medical NLP turns that text into structured clinical knowledge. The two are different problems, and you need both.

Once you have the raw text from a prescription label, you have things like "Lisinopril 10mg" and "Take 1 tablet by mouth once daily." Medical NLP systems are trained on clinical text to identify the named entities in those strings: the medication name, the dosage, the route of administration, the frequency. Beyond entity recognition, specialized systems can then link those entities to standard clinical ontologies: this detected medication entity maps to RxNorm concept 314076 ("lisinopril 10 MG Oral Tablet").

This entity extraction and ontology linking is what makes the pipeline interoperable. A downstream FHIR MedicationStatement resource, a pharmacy benefit system, a clinical decision support tool: all of them speak RxNorm. Giving them a raw string like "Lisinopril 10mg" forces them to do their own normalization, inconsistently. Giving them a RxNorm concept ID means everyone is speaking the same language.

### The General Architecture Pattern

The pipeline for prescription label OCR looks like this:

```text
[Capture] → [OCR / KVP Extraction] → [Field Normalization + SIG Parsing]
         → [Medical NLP (Medication Entities + RxNorm)] → [Store] → [Expose via API]
```

**Capture:** A mobile photo of the pill bottle, a portal upload, or a scanned label from a point-of-care device. Quality guidance at capture time (lay the bottle flat, ensure good lighting) is the highest-leverage quality improvement and has no computational cost.

**OCR / KVP Extraction:** Pass the image to a document intelligence service that returns key-value pairs, not just raw text. For single-page structured labels, synchronous processing is appropriate. Results come back in under 3 seconds.

**Field Normalization and SIG Parsing:** Map the extracted labels to canonical field names across pharmacy chains. Decode SIG abbreviations from the directions field into human-readable text.

**Medical NLP:** Pass the extracted medication name and dosage through a clinical entity extraction model that identifies MEDICATION entities and links them to RxNorm concept IDs. This step bridges the raw OCR output to the clinical ontology layer.

**Store:** Write the structured medication record to a queryable store with appropriate PHI controls. The record should carry both the raw extracted values and the normalized/linked values for auditability.

**Expose via API:** Downstream systems consume the structured medication record. In a member-facing app, this can be synchronous (return the structured record immediately). In bulk processing, async is fine.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.07-architecture). The Python example is linked from there.

## The Honest Take

This one is in the "sounds easy, has real edge cases" category. The first 80% of labels you test will process beautifully. Then you'll hit a compounding pharmacy label, or a bottle photographed by a member who tilted their phone 30 degrees, or a label where the NDC field was reprinted over the original and the text overlaps.

The curved label problem is the one that catches most teams off-guard. It's not catastrophic: modern OCR handles moderate curvature surprisingly well. But "surprisingly well" is not the same as "correctly." The characters at the far edges of a wrapped label can have 10-15% higher error rates than the center of the label, and the fields most likely to live at the edges are the ones with the most characters: the drug name and the directions. Budget for it.

The SIG codebook is the part that requires the most ongoing maintenance. Latin pharmacy abbreviations are standardized in principle and inconsistent in practice. Individual pharmacies and pharmacy software systems add their own shorthand. "Inject 0.5 mL SubQ QW" and "Inject 0.5 mL SC every week" are the same instruction from different systems. Build the unrecognized-token logging on day one: you'll need it.

The RxNorm confidence cutoff is a tradeoff to calibrate for your use case. A 70% threshold is a reasonable starting point, not a gospel number. For medication reconciliation in a clinical program, you might want 85%+: a wrong RxNorm mapping in a drug interaction checker produces a false safety signal that a clinician has to investigate. For a member-facing informational display, 70% might be fine. Know your downstream use case before you pick the threshold.

The thing I didn't anticipate building the first version of this: days supply is sometimes absent from the label. State regulations on what must appear on a prescription label vary, and some states don't require days supply to be printed. Your refill metrics logic needs to handle missing fields gracefully rather than throwing an exception when the field isn't found.

---

## Related Recipes

- **Recipe 1.1 (Insurance Card Scanning):** The structural twin: same synchronous Textract FORMS pattern, same confidence gating, same DynamoDB storage model. If you've built 1.1, the Textract layer of this recipe will feel familiar.
- **Recipe 1.3 (Lab Requisition Form Extraction):** Uses the same Comprehend Medical NLP layer for entity extraction, but maps to ICD-10 and SNOMED rather than RxNorm. Good context for how DetectEntitiesV2 handles different clinical entity categories.
- **Recipe 3.3 (Medication Reconciliation):** Consumes the structured medication records this recipe produces and builds a full reconciliation pipeline: deduplication, FHIR MedicationStatement generation, and care gap identification.

---

## Tags

`document-intelligence` · `ocr` · `textract` · `comprehend-medical` · `rxnorm` · `ndc` · `prescription` · `medication` · `pharmacy` · `sig-codes` · `simple` · `phase-2` · `lambda` · `s3` · `dynamodb` · `hipaa`

---

*← [Chapter 1 Index](chapter01-preface) · ← [Recipe 1.6: Handwritten Clinical Note Digitization](chapter01.06-handwritten-clinical-note-digitization) · [Recipe 1.8: EOB Processing →](chapter01.08-eob-processing)*
