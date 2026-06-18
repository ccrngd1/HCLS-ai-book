<!--
Editorial pass 4 (TechEditor, 2026-06-17):
- Post-split polish. Verified architecture callout is well placed at end of General Architecture Pattern.
- Confirmed The Honest Take contains zero AWS service references (no dangling pointers to moved content).
- Added `text` language tag to the pipeline-flow code block (bare ``` violation).
- Final sweep: zero em dashes, zero en dashes, zero bare code block openings, header hierarchy intact,
  all existing TODO markers preserved with finding IDs on same line.

Editorial pass 3 (TechEditor, 2026-05-31):
- Softened "embarrassingly good" to "unusually strong" in The Honest Take opening per voice review finding V3. The original was borderline hyperbole for a technical cookbook; the replacement keeps the same point in a register consistent with the measured tone of the surrounding paragraphs.
- Final verification: zero em dashes (U+2014, U+2013), header hierarchy intact (H1 title only, H2 major sections, H3 subsections), RECIPE-GUIDE section order preserved, all TODO markers from prior passes intact and properly formatted with finding IDs on the same line, vendor balance holds (~70/30), no documentation-voice or announcement-voice patterns, no fabricated URLs, Python companion callout present, navigation footer intact.
- All HIGH/MEDIUM review findings remain as TODO markers for TechWriter follow-up (A1, N1, S1, S2, S3, S4, A2, A3, A4, N2). LOW findings V1a/V1b/V1c also remain as TODOs. V2 (model ID) was addressed in pass 1 with an inline comment. V4 (afterthought metaphor) was addressed in pass 1. S5 (synthetic label) was addressed in pass 1.
- Recipe is editorially complete pending TechWriter resolution of deferred findings.

Editorial pass (TechEditor, 2026-05-11):
- Removed a documentation-voice opening sentence at the end of The Problem ("This recipe is about the generation side of prior auth.") that duplicated the next sentence's framing ("This one is about being the provider..."). The second sentence already carries the contrast with Recipe 1.4 in CC voice; the first was redundant and leaned into the anti-pattern flagged in STYLE-GUIDE.md.
- Preserved all TODO markers inserted by TechWriter, TechCodeReviewer, and TechExpertReviewer, including the three HIGH findings from expert review (cost estimate A1, VPC endpoint list N1, IAM ARN scoping S1), the six MEDIUM findings (S2 minimum-necessary, S3 model-invocation-logging PHI, S4 input-side prompt injection, A2 Step Functions task-token pattern, A3 regeneration retry cap, A4 idempotency fingerprint, N2 EHR connectivity), and the LOW findings (V1 three unverified items, the "PAO" acronym correction, the Recipe 5.x cross-reference). Per persona rules, structural additions that introduce new architectural or clinical content are left for the TechWriter rather than rewritten here.
- Verified: zero em dashes (U+2014 and U+2013 full-file scans), header hierarchy intact (H1 title, H2 major sections, H3 subsections, H4 Walkthrough), RECIPE-GUIDE section order preserved, vendor balance holds (AWS names first appear at "The AWS Implementation"), all external URLs well-formed (AWS docs, CMS-0057-F fact sheet, HL7 DaVinci PAS IG, AMA PA resources, ACR guidelines), fenced pseudocode blocks match the unlabeled convention established in Chapter 1 and Recipe 2.3, JSON and Mermaid blocks carry language tags, no LinkedIn-influencer or announcement-voice patterns present.

Editorial pass 2 (TechEditor, 2026-05-11):
- Resolved the self-flagged "PAO" acronym TODO in "Finalize and submit" (General Architecture Pattern) by removing the "or PAO FHIR profiles" clause. The recognized HL7 DaVinci prior-authorization IGs are PAS (Prior Authorization Support), CRD (Coverage Requirements Discovery), and DTR (Documentation Templates and Rules); "PAO" is not a real IG name. Removing the unverified acronym is in-scope for the editor per STYLE-GUIDE.md's "only verified" rule (no fake links, no fake abbreviations) and introduces no new technical content; the retained "DaVinci PAS" reference is factually correct and already accompanied by the verified HL7 link in Additional Resources. Adding a new acronym (CRD, DTR) would be new technical content and is out of editor scope, so I removed rather than corrected.
- Final checklist sweep against both reviews. No further fixable issues at the editing layer.
- Re-verified: zero em dashes (U+2014) and zero en dashes (U+2013) on full-file scan, header hierarchy unchanged, RECIPE-GUIDE section order intact, vendor balance holds at approximately 70/30, all external URLs in Additional Resources well-formed (8 AWS docs, 3 AWS samples/blogs, 4 industry resources), Python companion callout present and matches the RECIPE-GUIDE template, navigation footer filenames verified against the repo (chapter02.03, chapter02-index, chapter02.05 all exist).
- TODOs preserved for TechWriter handoff: cost recomputation against multi-call pipeline (A1, header + Prerequisites + Performance table), VPC endpoint expansion (N1), IAM ARN scoping (S1), minimum-necessary paragraph in Step 3 (S2), model-invocation-logging PHI note in Encryption row (S3), input-side prompt-injection paragraph in Failure Modes (S4), Step Functions task-token pattern in the Step Functions subsection (A2), regeneration retry bounds in Step 7 (A3), idempotency fingerprint in Step 1 (A4), EHR connectivity paragraph in the Production-Ready section (N2), AMA statistics verification (V1a), payer approval rate benchmark removal (V1b), and Recipe 5.x cross-reference resolution (V1c). Per persona rules, each of these introduces new architectural, clinical, or operational prose rather than an in-place correction and is deferred to the TechWriter.
-->

# Recipe 2.4: Prior Authorization Letter Generation

**Complexity:** Medium · **Phase:** MVP → Production · **Estimated Cost:** ~$0.10-0.30 per letter <!-- TODO: recompute cost against actual multi-call pipeline (Step 2 extraction, Step 3 per-criterion fact extraction, Step 4 per-criterion mapping, Step 6 generation). Expert review flagged the current range as ~5-10x optimistic for a typical 10-criterion PA on Claude Sonnet 4. -->

---

## The Problem

A rheumatologist needs to prescribe a biologic for a patient with rheumatoid arthritis. The patient has failed methotrexate, has documented disease activity, and meets every clinical criterion the payer has published for approval. This should be a fifteen-minute decision. Instead, it becomes a four-hour project.

Someone on the practice's staff (usually a medical assistant, a nurse, or a dedicated prior authorization coordinator) has to write a letter of medical necessity. They pull the patient's chart. They find the DAS28 scores. They locate the methotrexate trial notes. They dig up the ACR guidelines that support the switch to a biologic. They track down the payer's specific coverage policy for adalimumab, which is a 14-page PDF buried three clicks deep on the payer's provider portal. They read it, identify the six criteria the payer requires, and then they start writing.

The letter has to be persuasive but factual. It has to tie specific patient findings to specific payer criteria. It has to cite supporting evidence. It has to be signed by the physician. It has to be faxed or uploaded through the payer's portal (which has its own upload quirks and sometimes breaks). Then everyone waits.

The American Medical Association's annual prior authorization survey reports that practices handle roughly 45 prior authorizations per physician per week, that physicians and staff spend an average of 14 hours per week on prior authorization work, and that 94% of physicians report care delays attributable to prior authorization. <!-- TODO: verify specific statistics against the latest AMA Prior Authorization Physician Survey -->

The letter itself typically takes 20 to 30 minutes to write, and that's assuming the writer is experienced and has the source documents at hand. New staff take longer. Complex cases (oncology, rare diseases, off-label requests) can take hours. A practice with 15 physicians processes roughly 600 to 700 prior authorizations per week. That's the equivalent of 2-3 full-time employees writing letters, which is exactly what many practices do: staff whose only job is composing prior auth narratives all day.

Here's the thing that makes this problem particularly interesting for AI: the writing is highly templated. Every letter for rheumatoid arthritis biologics looks roughly the same. Every letter for bariatric surgery looks roughly the same. The patient details vary, the payer criteria vary, but the structure of the argument is consistent: here is the patient, here is the condition, here is what they've tried, here is why the requested service is medically necessary, here is the supporting evidence. This is the kind of structured synthesis task that LLMs are genuinely good at.

The economic impact of getting this right is substantial. If you can reduce letter composition time from 25 minutes to 5 minutes of physician review, you recover roughly 13 hours per physician per week. For a mid-sized practice, that's the equivalent of eliminating a full staff position dedicated to prior auth writing, or redeploying that person to higher-value work. For the patient, it's the difference between starting therapy next Monday and starting therapy next month.

Recipe 1.4 covered the flip side of this problem: ingesting and processing prior auth submissions as a payer. This one is about being the provider who has to send those submissions in, and using an LLM to write the narrative letter rather than typing it by hand.

---

## The Technology: Grounded Generation for Structured Persuasion

### What a Prior Auth Letter Actually Is

Before we talk about how to generate these with an LLM, it's worth dissecting what a good prior auth letter actually contains. The structure is remarkably consistent across specialties and payers:

1. **Patient identification.** Name, date of birth, member ID, diagnosis codes. This is purely administrative.
2. **Clinical background.** The patient's diagnosis, how it was established, relevant history. This is where you establish the medical context.
3. **Treatment history.** What's been tried, what worked, what didn't, and why. This is the most important section for payer review. Step therapy requirements live here.
4. **Clinical rationale for the requested service.** Why this specific service, why now, why this patient. This is where the letter has to be persuasive without overreaching factually.
5. **Reference to payer criteria.** A direct mapping from the patient's facts to the payer's published coverage criteria. Good letters explicitly say "the patient meets criterion X because of finding Y."
6. **Supporting evidence.** Clinical guidelines, peer-reviewed studies, professional society recommendations. This anchors the request in the medical literature.
7. **Signature and credentials.** Provider name, NPI, specialty, license. This establishes the prescribing authority.

Every one of those sections draws from a different source. The patient identification and clinical background come from the EHR. The treatment history requires parsing clinical notes. The payer criteria come from the payer's medical policy (typically a PDF on their provider portal). The supporting evidence comes from published guidelines and literature. The signature is provider-specific metadata.

A human writer synthesizes all of this from memory, from the chart, and from open browser tabs. An AI system has to do it from retrieval. Which is what makes this problem an archetypal RAG application.

### Why LLMs Are Genuinely Good at This

LLMs are excellent at taking a set of facts and weaving them into structured prose that follows a specific rhetorical pattern. This is a task that pre-LLM NLP could not do well. Template-based letter generation (mail merge, essentially) produced output that read as mechanical and missed the nuance of tying specific findings to specific criteria. Rule-based systems couldn't handle the variability in how clinical information is expressed.

Modern LLMs handle this well because:

**They understand medical language natively.** A model that has been trained on clinical text understands that "DAS28 score of 5.8" indicates high disease activity in rheumatoid arthritis, that "methotrexate 25mg weekly for 16 weeks with inadequate response" satisfies a typical step therapy requirement, and that "ACR guidelines recommend biologic therapy after inadequate DMARD response" is the right citation to anchor the request.

**They can follow structured rhetorical patterns.** Given an explicit letter template and a set of facts, an LLM can produce output that fits the template while sounding natural. The failure mode of earlier systems (formulaic, obviously auto-generated prose) is largely solved.

**They can map between sources.** Given the patient's clinical facts on one side and the payer's coverage criteria on the other side, an LLM can produce text that explicitly connects them. "Criterion 3 requires documented disease activity. The patient's DAS28 score of 5.8, documented on 2026-03-15, satisfies this criterion." This explicit mapping is what makes a letter persuasive to a reviewer working through a checklist.

**They handle payer-specific voice.** Different payers favor different tones. Some want formal clinical language. Some want concise bullet-pointed structures. Some want narrative prose that reads like a consult note. An LLM can be instructed to produce any of these styles with prompt engineering alone, without retraining.

### The Failure Modes You Have to Design Around

**Hallucinated clinical facts.** The model confabulates a lab value, a date, or a trial duration that isn't actually in the patient's record. In prior auth, this isn't just embarrassing; it's potentially fraudulent. A letter that asserts the patient had a 16-week methotrexate trial when the chart shows 8 weeks is a false claim. If the payer audits and the discrepancy surfaces, your practice has a problem.

The mitigation: never let the model generate clinical facts from its prior knowledge. Extract structured facts from the patient record first, validate them, and then provide them to the model as authoritative input. Instruct the model to only use provided facts and to explicitly refuse to generate claims that aren't supported by the input.

**Payer criteria drift.** Payer medical policies change. Sometimes quarterly. Sometimes in response to new evidence. Sometimes because the payer changed their PBM contract. A letter that cites criteria from last year's policy will fail current review. This is a retrieval freshness problem. Your policy repository has to be maintained, which means someone (or some automated process) has to pull updated policies from every payer you work with.

**Over-confident tone.** LLMs, by default, produce confident prose. A prior auth letter needs to be assertive about the medical need, but it also needs to acknowledge legitimate clinical uncertainty where it exists. A letter that says "the patient will definitely respond to adalimumab" is both clinically wrong and rhetorically counterproductive. A letter that says "the clinical evidence supports adalimumab as the appropriate next-line therapy given the patient's inadequate response to first-line DMARDs" is factually grounded and persuasively framed.

**Citation fabrication.** Ask an LLM to cite supporting literature and it will happily generate plausible-looking journal citations that don't exist. The model confabulates author names, journal titles, and DOIs with high confidence. The mitigation: use retrieval for citations. Pull from a vetted literature corpus or a guideline repository. Never let the model generate citations from its training data alone.

<!-- TODO: expert review (S4) recommended adding a short paragraph here on input-side prompt-injection risk. When clinical note content originates from weakly controlled channels (patient portal messages, OCR of faxed outside records, external referrals), an adversarial string in a note field could attempt to override the grounding constraint and instruct the model to fabricate claims or cite nonexistent literature. The suggested mitigation is configuring Bedrock Guardrails with input-side prompt-attack filters in addition to output filters, and treating EHR-sourced structured data and free-text narrative content as different trust tiers. -->

**Payer-specific formatting.** Most payers accept letters in PDF format submitted through a portal. Some require specific fields in specific places. Some want structured JSON submitted via API (the HL7 DaVinci project is pushing toward this, and CMS-0057-F is accelerating it). Your generation pipeline has to produce the right output format for each payer, which means the architecture has to support multiple output modalities from a common content core.

**Physician sign-off friction.** A generated letter is only valuable if the physician signs it. If the review workflow is cumbersome (print, read, sign, scan, upload), the time savings evaporate. The integration with clinical workflows matters as much as the letter quality.

### Grounded Generation: The Architectural Answer

The pattern that makes prior auth letter generation viable is grounded generation, which is a specific flavor of Retrieval-Augmented Generation adapted for letter composition. The idea:

1. Before generating anything, retrieve the authoritative source materials: patient facts, payer criteria, clinical guidelines.
2. Extract the specific facts that will be referenced in the letter. Validate them against the source documents. Store them as structured data.
3. Generate the letter with explicit instructions to use only the provided facts and citations, and to map each claim in the letter back to a source.
4. Verify the generated letter: every factual claim should trace to a source document; every citation should match a real reference.
5. Present the letter to the physician for review with the source provenance visible, so they can audit the claims quickly.

The key architectural principle: the model is a prose composer, not a fact source. Facts come from retrieval. Claims come from extraction. Citations come from a vetted corpus. The model's job is to weave these elements into a coherent, persuasive narrative that fits the payer's expected structure. This separation is what makes the output auditable and the system safe enough to deploy.

### Where This Differs From Simpler LLM Applications

Recipe 2.1 (patient message drafting) works with a single input (the inbound message) and produces a single output (the draft reply). Recipe 2.2 (terminology simplification) works with a single input (the clinical text) and produces a transformed output. Recipe 2.3 (CDI suggestions) analyzes a single note against a set of guidelines.

Prior auth letter generation is different because it's fundamentally a synthesis task across multiple disparate sources. You need:

- Patient clinical data (from the EHR, possibly across multiple encounters)
- Payer-specific coverage criteria (from the payer's medical policy)
- Clinical guidelines (from professional societies, published literature)
- The requested service details (from the order or referral)
- Provider credentials (from practice metadata)

Each of these lives in a different system, has a different update cadence, and requires different extraction approaches. The architecture has to orchestrate retrieval across all of them before generation can begin. That orchestration is where most of the engineering work lives. The LLM call itself is the smallest engineering problem in the pipeline.

---

## The General Architecture Pattern

At the conceptual level, the pipeline looks like this:

```text
[Prior Auth Request Submitted] 
    → [Identify Payer + Requested Service] 
    → [Retrieve Payer Coverage Policy] 
    → [Extract Criteria Checklist from Policy] 
    → [Retrieve Patient Clinical Data] 
    → [Extract Relevant Clinical Facts] 
    → [Map Facts to Criteria] 
    → [Retrieve Supporting Evidence] 
    → [Generate Letter Narrative] 
    → [Validate Claims Against Sources] 
    → [Present for Physician Review] 
    → [Finalize and Submit]
```

Let's walk through each stage conceptually.

**Identify payer and requested service.** The trigger for the whole pipeline. Comes from the provider's workflow: a clinician orders a procedure, a medication, or a referral that requires prior auth. The system needs to know which payer covers this patient and what service is being requested. This is typically an integration problem with the EHR or the practice management system.

**Retrieve payer coverage policy.** Every payer publishes coverage policies for services that require prior auth. These are typically PDFs on the payer's provider portal. Retrieving them programmatically is harder than it sounds: most payers don't offer APIs. You may be pulling PDFs from portals, parsing them, and caching the extracted content. This is a recurring maintenance burden.

**Extract criteria checklist from policy.** Once you have the policy, you need to extract the specific criteria the payer will check. A coverage policy for a biologic might include criteria like "documented diagnosis of rheumatoid arthritis," "inadequate response to at least one non-biologic DMARD for at least 12 weeks," "negative tuberculosis screening within 6 months." These criteria become the rubric against which the patient's clinical facts will be mapped.

**Retrieve patient clinical data.** From the EHR, pull everything relevant: diagnoses, medication history, lab values, clinical notes, prior treatments. The scope of "relevant" depends on the requested service. For a biologic, you need disease activity measures, prior DMARD trials, TB screening, and relevant labs. For bariatric surgery, you need BMI history, prior weight loss attempts, and comorbidity documentation.

**Extract relevant clinical facts.** Raw clinical data is unstructured. You need to parse it into discrete facts that can be mapped to criteria. "Methotrexate 25mg weekly from 2025-07-01 to 2025-10-15" is a fact. "DAS28 score of 5.8 on 2026-03-10" is a fact. "Negative QuantiFERON-TB on 2026-02-15" is a fact. This is typically done with a combination of structured data queries (for coded data in the EHR) and LLM-based extraction (for information that lives only in free-text notes).

**Map facts to criteria.** For each criterion in the payer's checklist, identify the patient facts that satisfy it. This mapping is the substance of the prior auth argument. Done well, the mapping is explicit and traceable: criterion X is satisfied by fact Y, documented on date Z. Done poorly, the mapping is hand-wavy and the letter is weak.

**Retrieve supporting evidence.** Clinical guidelines and literature that support the request. For rheumatoid arthritis biologics, that's the ACR treatment guidelines. For bariatric surgery, the ASMBS guidelines. This evidence is retrieved from a vetted corpus (never generated by the LLM from its training data) and gets cited in the letter.

**Generate letter narrative.** Finally, the LLM call. Inputs: the letter template, the extracted patient facts, the criteria-to-fact mapping, the supporting evidence, the payer-specific tone requirements. Output: a draft letter that weaves these elements into structured, persuasive prose. The prompt enforces grounding: use only the provided facts, cite only the provided evidence, explicitly map each claim to a source.

**Validate claims against sources.** Every factual claim in the letter should trace back to a source document. A validation layer parses the generated letter, identifies factual assertions, and checks that each one appears in the input facts. Claims that can't be traced get flagged for physician review.

**Present for physician review.** The generated letter is shown to the prescribing physician along with source provenance: each claim links to the source fact, each citation links to the retrieved evidence. The physician reviews quickly, edits if needed, and signs. This is where the time savings live: reducing a 25-minute composition task to a 3-5 minute review task.

**Finalize and submit.** The signed letter is formatted for the payer's submission mechanism: PDF for portal upload, structured data for API submission (for payers supporting the DaVinci PAS FHIR profile), or fax for legacy payers. Submission status is tracked for follow-up.

This is a lot of machinery. The LLM call is one step in a pipeline of ten or twelve, and most of the engineering complexity lives in the non-LLM steps. Retrieval, extraction, mapping, and validation are where the system lives or dies. The generation is almost easy once you've done the rest correctly.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.04-architecture). The Python example is linked from there.

## The Honest Take

Prior auth letter generation is one of those use cases where the ROI math is unusually strong. Practices spend millions of dollars per year on staff time composing these letters. A system that reduces composition time by 80% pays for itself almost immediately. The payback period can be measured in weeks, not years. This is rare in healthcare AI.

That said, I've watched this use case fail more than once, and the failure modes are consistent. The AI part works. The integration part is where things break.

The single biggest lesson: do not underestimate the policy ingestion problem. Teams start this project thinking the hard part is the LLM. They build a great pipeline, they demo it on a hand-selected case, and then they discover that keeping policies current across 40 payer contracts is a grind that nobody wants to own. The system starts producing letters that cite outdated criteria. The denial rate climbs. The physicians lose trust. The project quietly dies.

Solve the policy ingestion problem first. Before building the LLM pipeline, demonstrate that you can reliably keep current policies from your top 10 payers in your knowledge base. If you can't do that operationally, the rest of the architecture is moot.

The second lesson: invest heavily in the physician review UI. This is where I've seen more time savings evaporate than anywhere else. A technically perfect letter that takes 10 minutes to review because the UI is clunky is worse than a slightly weaker letter that takes 3 minutes to review in-workflow. The UI is not a "polish later" concern; it's central to whether the system saves time.

Third: measure approval rates, not just letter quality. Internal metrics like "physician acceptance without edits" feel good but don't tell you if the letters actually work. Track payer approval rates for letters generated by the system vs. hand-composed letters. If generated letters get approved at a lower rate, you have a problem, regardless of how good the prose looks. The payer is the customer; their decisions are the ground truth.

Fourth, and this is something that surprised me: generated letters sometimes get approved at higher rates than hand-composed letters. Not always, but sometimes. The reason is that the generation process forces explicit mapping from facts to criteria, which is exactly what the payer's reviewer is looking for. Hand-composed letters often bury the criteria mapping in narrative prose. The structured approach the LLM takes (with explicit "this fact satisfies this criterion" framing) can actually outperform human writers who are working from memory under time pressure. This is a nice surprise when it happens.

Finally: don't try to automate the whole thing. The physician signature is load-bearing for legal and clinical reasons. The review is not a nuisance to be minimized; it's an essential safety and quality step. Frame the system as "AI-assisted letter composition with physician sign-off" rather than "automated letter generation." The framing matters for how physicians engage with it, how compliance teams evaluate it, and how malpractice insurers view it. Your lawyers will be happier and your physicians will be more willing to use it.

---

## Related Recipes

- **Recipe 1.4 (Prior Auth Document Processing):** The flip side of this recipe. That one processes inbound PA submissions from the payer's perspective; this one generates outbound submissions from the provider's perspective. They use complementary architectural patterns.
- **Recipe 2.3 (Clinical Documentation Improvement):** CDI suggestions improve the clinical documentation that this recipe depends on. Better notes produce better fact extraction and stronger PA letters.
- **Recipe 2.7 (Literature Search and Evidence Synthesis):** The evidence retrieval in this recipe is a simplified form of the RAG pattern in 2.7. For complex PA cases where standard citations don't apply, the literature search pattern becomes relevant.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** Similar synthesis architecture but higher-stakes output. The grounding patterns used here are essential there.
- **Recipe 5.x (Entity Resolution):** Linking patient records across EHR, practice management, and payer systems is a prerequisite for reliable PA automation. <!-- TODO: verify the specific Chapter 5 recipe number once Chapter 5 planning resolves; update the cross-reference or remove this bullet if no matching recipe exists. -->

---

## Tags

`llm` · `generative-ai` · `bedrock` · `rag` · `prior-authorization` · `medical-necessity` · `grounded-generation` · `knowledge-bases` · `healthlake` · `step-functions` · `medium-complexity` · `hipaa` · `fhir` · `davinci-pas`

---

*← [Recipe 2.3: Clinical Documentation Improvement](chapter02.03-clinical-documentation-improvement) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.5 - After-Visit Summary Generation →](chapter02.05-after-visit-summary-generation)*
