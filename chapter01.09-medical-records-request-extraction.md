# Recipe 1.9: Medical Records Request Extraction 🔶 

**Complexity:** Moderate · **Phase:** Phase 2 · **Estimated Cost:** ~$0.12–0.18 per request form

---

## The Problem

Here's a scenario that plays out in health plan operations every single day. A physician's office faxes over a medical records request for a patient they're about to see for the first time. They want the cardiac workup from 2023, the last two years of PCP notes, and the surgical history. The fax lands in a shared queue. Someone needs to read it, figure out who's asking for what records, check that there's a valid HIPAA authorization attached, and route it to the right fulfillment team.

Sounds manageable. Now imagine that happening 200 times before noon. Then add the legal requests from plaintiff attorneys wanting records for an injury claim. The life insurance underwriters wanting six years of medical history. The utilization management consultants reviewing a long-term disability case. And the patients themselves exercising their right of access under HIPAA. Each of these request types has different handling requirements, different turnaround windows, different fulfillment teams, and different legal exposure if something goes wrong.

The HIPAA Privacy Rule governs almost all of this. Under 45 CFR § 164.508, releasing protected health information requires either a valid patient authorization or one of the specified permissible purposes. A valid authorization is not just a signature on a page. It has required elements: a description of the information to be disclosed, who is authorized to receive it, the purpose, and a date or event that causes it to expire. Processing a records request without checking those elements is not a paperwork oversight. It is a potential HIPAA violation, the kind that can generate breach notifications and OCR investigations.

The current state at most payers is fully manual triage. A records fulfillment coordinator reads each incoming request, eyeballs the authorization form, checks the elements as best they can, and enters the request into a tracking system by hand. When the authorization is incomplete or expired, they draft a deficiency letter and the cycle restarts. At payers processing tens of thousands of records requests per year, this manual triage is a meaningful operational cost, and the HIPAA compliance posture depends entirely on the consistency of each individual coordinator's review.

The document processing challenge here has two distinct pieces. The first is familiar: form field extraction for the structured portions of the request and authorization. The second is more interesting: once you've extracted those fields and confirmed a signature exists, someone still needs to reason about whether the authorization actually makes sense. Do the dates add up? Is the scope of disclosure coherent with the stated purpose? Does the expiration date come after the signing date? A rule-based checker can confirm that required fields are present. It cannot tell you whether the information in those fields is consistent with a valid authorization.

That reasoning gap is where this recipe gets interesting.

---

## The Technology

### Semi-Structured Forms and Signature Detection

A medical records request form is messier than the prior authorization cover sheet in Recipe 1.4. There is no industry-standard template. Every hospital, every health system, every payer release-of-information department has their own version. Some look like clean typed forms. Others are clearly a Word document someone made in 2009 and has been faxing ever since.

What they almost all share: they're single-to-two-page documents with a mix of labeled fields (patient name, date of birth, medical record number, date range) and semi-free-text areas (description of records requested, purpose, any special instructions). The key-value extraction approach from Recipe 1.1 handles the structured field portion well. The semi-free-text areas are where you need to look at content rather than labels.

The authorization section requires a different kind of attention. You're looking for the same elements across varied form layouts. And crucially: you need to know whether the patient actually signed the form. OCR extracts text. A signature is not text. It's a pen stroke on paper that, after being faxed and scanned, appears as a pixelated blur.

Signature detection uses binary image classification at the region level: given a bounding box on a document, does this region contain something that looks like a handwritten signature? The training data for these classifiers consists of thousands of document images with labeled regions. What distinguishes a signature from handwritten text is mostly statistical: signatures tend to have certain ink density characteristics, stroke continuity patterns, and spatial distributions that differ from prose handwriting. Modern document AI platforms return a confidence score and bounding box for each detected signature region.

The confidence score reflects the classifier's certainty that the region contains a signature versus something else. It does not reflect any judgment about the legal validity of the signature or whether it matches a reference. For HIPAA authorization purposes, the question is much simpler: is there something here that looks like a handwritten signature? That binary question is one that a well-trained classifier can answer with 85 to 95% accuracy on real-world fax-quality authorization forms.

The failure modes are predictable. Faint signatures that degrade below the detection threshold after multi-hop faxing. Rubber stamp signatures used by some authorized representatives. Electronic signatures embedded in PDFs, which may render as text rather than ink marks. Keep these in mind when you're setting the confidence threshold and designing the human review queue.

### HIPAA Authorization Validation: The Rule-Based vs. LLM Tension

This is the most interesting problem in this recipe, and it deserves honest treatment.

The HIPAA Privacy Rule under 45 CFR § 164.508(c)(1) specifies the required elements for a valid authorization:

1. A description of the information to be used or disclosed
2. The person(s) authorized to make the disclosure
3. The person(s) who may receive the disclosed information
4. The purpose of the disclosure
5. An expiration date or event
6. The signature of the individual and the date

These are not suggestions. An authorization missing any core element is legally deficient. Processing a records release against a deficient authorization is a potential Privacy Rule violation.

The traditional approach: write a rule-based checker. For each required element, check whether the corresponding field was extracted and contains a non-empty value. Check whether the expiration date is in the future. If all checks pass, the authorization is valid. Flag and route to the deficiency queue if anything fails. This approach is deterministic, auditable, and fast. Every time you run the same authorization through it, you get the same answer, and you can point to the exact rule that triggered a failure.

So why not stop there?

Because rule-based presence checks have a visibility problem. They can confirm that required fields are populated. They cannot reason about whether the information in those fields is internally consistent or coherent as a legal authorization.

Here are the edge cases that rule-based validation misses:

**Conflicting dates.** A signing date of February 28, 2026, and an expiration date of February 15, 2026. Both fields are populated. Both pass the presence check. The authorization expired before it was signed, which is logically impossible and legally void. A rule-based checker confirms that an expiration date exists and that it's a parseable date. It does not compare the signing date to the expiration date. A human reviewer would catch this immediately.

**Ambiguous scope language.** "All records related to the incident" passes the presence check for description of information. But which incident? If the purpose field says "life insurance underwriting" and the description says "records related to the accident," there's an unresolved ambiguity that a compliance-conscious reviewer would flag for clarification. The presence check sees two populated fields and moves on.

**Missing elements not in form fields.** Some authorization forms interleave required elements in paragraph form rather than labeled fields. The description of information might appear in a sentence: "I authorize Dr. Smith to release records pertaining to my cardiac care provided between January 2023 and December 2024 to the requesting physician for the purpose of continuity of care." All the required elements are in that sentence. If the form doesn't have a labeled field for "description of information," the field extraction step returns nothing for that canonical field, and the rule-based checker incorrectly flags the authorization as deficient.

**Implicit expiration events.** "This authorization is valid for one year from the date of signing" is a valid expiration event under HIPAA. It's also a sentence, not a date field. A rule-based date parser that tries to parse this value will fail, and depending on how the validator handles parse failures, may incorrectly flag the authorization.

These are not exotic cases. They're typical of real-world authorization forms faxed from a varied population of healthcare providers, law offices, and insurance carriers. A coordinator who reviews records requests every day catches these issues because they read the authorization as a coherent document. Rule-based logic reads fields.

**Where the LLM adds value.** A language model can read the full authorization text the way a coordinator would. It can reason about whether the dates are logically consistent. It can identify scope language that's present but ambiguous relative to the stated purpose. It can find required elements embedded in paragraphs that didn't map to form fields. It understands what a HIPAA authorization is supposed to say, and it can notice when something seems off.

**Where the LLM creates risk.** HIPAA compliance validation is exactly the kind of decision where you want determinism and auditable output. If the LLM says an authorization is valid and you release the records, and a subsequent audit finds the authorization was actually deficient, probabilistic reasoning is not a legal defense. You need to know precisely why a validation decision was made, in a form you can point to during an OCR investigation. You also need consistency: the same authorization should produce the same validation outcome each time you process it. At temperature=0, LLMs are close to deterministic but not perfectly so, and model updates can shift behavior.

**The resolution: layered architecture, not a choice between approaches.** This recipe implements both, in sequence, with a clear chain of authority.

The rule-based checker runs first and remains the authoritative validation gate. If any required element is missing or any date check fails, the authorization is deficient. Full stop. The rule fires, the specific failure is recorded with the applicable regulatory citation, and the request goes to the deficiency queue. The LLM has no say in this outcome.

The LLM runs as a secondary screening layer on authorizations that pass the rule-based check. It reads the full authorization text and the extracted fields together, looking for the coherence issues the rules can't catch: conflicting dates, ambiguous scope, logical inconsistencies. If it flags a concern, the authorization enters a human review queue rather than proceeding directly to fulfillment. It does not make the authorization deficient. It flags it for a trained coordinator to look at.

This division of responsibility means:

- The audit trail for deficiency determinations is always rule-based and explicit. You can produce a log showing that a specific regulatory requirement was not met.
- The LLM adds a safety net above that layer, catching edge cases that are technically valid by the presence check but concerning in context.
- Authorizations that pass both layers proceed with high confidence. Authorizations that pass rules but concern the LLM go to human review. Authorizations that fail rules go to the deficiency queue, period.

One thing to be clear about: the LLM's observations in this recipe are the model's reasoning about the extracted content. They are not quotes from the document, and they are not statements of fact about the authorization. When you surface LLM concerns to a human reviewer, label them as such. "The LLM flagged a potential date inconsistency between the signing date and expiration date" is accurate and appropriately hedged. "The authorization contains a date inconsistency" presented as a factual finding is not, because the LLM may be wrong. The reviewer is the final decision-maker for anything the LLM flags. 

### Request Classification: A Clearer LLM Win

The HIPAA validation discussion above involves genuine tension worth working through carefully. Request classification is a more straightforward case for LLMs, and it's worth explaining why.

Medical records requests come from a variety of requestors with a variety of purposes: treating physicians requesting records for continuity of care, attorneys requesting records for litigation, insurers requesting records for underwriting, utilization review organizations, and patients exercising their right of access under HIPAA. Each category has different handling requirements, turnaround obligations, and fulfillment workflows.

The original approach: keyword scoring. Build a vocabulary for each request type. "Attorney," "litigation," and "subpoena" signal legal. "Continuity of care" and "new treating physician" signal care coordination. "Underwriting" and "disability" signal insurance. Score each document against the keyword lists and route to the highest scorer.

This works well for requests that use standard vocabulary. It fails in two ways that matter in practice.

First, free-text request descriptions are common. A patient writing their own records request might say "My mother passed away last month and I need her records to understand what happened during her final hospitalization." There are no standard category keywords in that sentence. A keyword classifier routes this to the general review queue even though the intent is clear: this is a patient access request with personal-representative authorization. A language model that understands the request contextually classifies it correctly.

Second, some requests span categories or use vocabulary that signals the wrong type. A utilization review organization might describe their purpose as "continued care management" (sounds like care coordination) while the requestor information clearly indicates an insurance company conducting a claims review. Keyword matching on the purpose field alone misses the context. An LLM that reads the full request, including the requestor information, gets to the right answer.

The model choice for classification is different from HIPAA validation. Classification is a simpler reasoning task: read the request, pick the right bucket. You don't need the deep contextual reasoning required to evaluate legal language against regulatory requirements. A smaller, faster, cheaper model handles this well. Nova Pro or Claude Haiku 4.5 are the right choices here: capable enough for the task, cost-appropriate for a relatively high-volume operation.

One practical note about classification results: present them with the model's reasoning to downstream fulfillment systems, not just the label. A routing record that says "classified as legal request: request mentions 'plaintiff's counsel' and 'civil litigation proceedings'" gives the receiving fulfillment specialist useful context. A routing record that just says "legal" gives them nothing. The reasoning is particularly valuable for ambiguous cases, where the fulfillment specialist may need to re-classify based on additional information. And always label the reasoning as LLM-generated inference in whatever interface surfaces it. The model got there by reading the request, not by verifying facts. 

### The General Architecture Pattern

```
[Request Arrives as Fax or PDF]
             |
             v
[Document Extraction: Forms + Signature Detection]
             |
             v
[Field Normalization]
             |
             v
[Rule-Based HIPAA Element Check]
  (Authoritative: presence of required elements,
   expiration date validity)
        /               \
       /                 \
[Rules Fail]         [Rules Pass]
    |                     |
    v                     v
[Deficiency Queue]   [LLM Authorization
                      Consistency Check]
                      (Screening layer only.
                       Cannot override rules.)
                          |
               /--------------------\
              /                      \
    [LLM Flags Concern]       [LLM No Concerns]
             |                        |
             v                        v
      [Human Review Queue]    [LLM Request Classification]
                                       |
                                       v
                              [Routing and Storage]
                     (Care Coordination | Legal | Underwriting |
                      Utilization Review | Patient Access | General)
```

The key architectural point: the rule-based check and the LLM check have different authorities. The rule-based check can create deficiencies. The LLM cannot. The LLM can only flag concerns that require human review before fulfillment proceeds. A human coordinator closes the loop on those flagged cases.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.09-architecture). The Python example is linked from there.

## The Honest Take

The HIPAA authorization tension is the most intellectually interesting thing about this recipe, and I want to give it one more round of honest treatment before closing.

The case for LLMs in authorization validation is genuinely strong. Human reviewers catch conflicting dates and ambiguous scope because they read documents as coherent artifacts. Rule-based systems read fields. That gap between field presence and document coherence is real, and it's where errors slip through. If your coordinator processes 200 requests before noon, "I noticed the expiration date is before the signing date" requires sustained attention that fatigues. An LLM doesn't get tired. It applies the same reading to the 200th authorization as the first.

At the same time: HIPAA compliance validation is not a context where "probably right" is the right standard. The Privacy Rule creates civil and criminal liability. If your system says an authorization is valid and you release records, and a subsequent audit determines the authorization was deficient, your compliance documentation needs to show why the system reached that conclusion. "The LLM thought it looked fine" is not that documentation. The rule-based layer provides the documentation; the LLM provides the safety net above it.

The layered architecture in this recipe reflects that honestly. The rule-based checker is the compliance gate. The LLM is the additional screening pass that catches edge cases the rules miss. Human reviewers close the loop on anything the LLM flags. Nobody in this architecture is abdicating the compliance decision to a probabilistic model.

The request classification case is cleaner. There is no regulatory requirement for classification decisions to be rule-based. A misclassification sends a request to the wrong fulfillment team, which creates operational delay but not a Privacy Rule violation. LLM classification is genuinely better at handling free-text requests and unusual vocabulary than keyword matching, the cost is negligible, and the failure modes are recoverable. This is a straightforward LLM improvement.

One operational lesson worth sharing: build the review queue carefully before you build the LLM. The value of the LLM screening layer depends entirely on what happens to the things it flags. If the review queue becomes a dumping ground that no one processes, the LLM concerns never close. The review queue needs a defined SLA, a defined escalation path, and a feedback mechanism so the operations team can tell you whether the LLM flags are accurate or noisy. That feedback is also how you tune the consistency check prompt over time.

---

## Related Recipes

- **Recipe 1.4 (Prior Authorization Document Processing):** The structural reference for this recipe. The FIELD_MAP normalization, Bedrock Converse API pattern, and model tiering concept all carry directly. If this is the first LLM recipe you're reading, start there.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** The human review queue for low-confidence signatures and LLM-flagged authorizations uses the Amazon A2I pattern detailed in that recipe. Worth reading if your review volume is high enough to need workflow management.
- **Recipe 1.8 (EOB Processing):** A parallel example of the "LLM replaces brittle rule-based configuration" pattern. Shows how the same Bedrock Converse API pattern applies to a different document type and a different category of configuration complexity.
- **Recipe 1.10 (Historical Chart Migration):** Once requests are validated and routed, fulfillment requires pulling records from legacy chart systems. Recipe 1.10 covers extraction at batch scale from heterogeneous historical documents.

---

## Tags

`document-intelligence` · `ocr` · `textract` · `forms` · `signatures` · `medical-records` · `hipaa-authorization` · `privacy` · `release-of-information` · `routing` · `bedrock` · `claude-sonnet` · `nova-pro` · `llm-screening` · `compliance-tension` · `moderate` · `phase-2` · `hipaa` · `payer`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.8: EOB Processing](chapter01.08-eob-processing) · [Next: Recipe 1.10: Historical Chart Migration →](chapter01.10-historical-chart-migration)*
