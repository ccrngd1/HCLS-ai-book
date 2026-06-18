# Recipe 2.10: Multi-Modal Clinical Reasoning

**Complexity:** Complex · **Phase:** Research → Controlled Pilot · **Estimated Cost:** ~$0.40-$4.00 per reasoning run (up to $5-$8 for worst-case comprehensive scenarios)


---

## The Problem

A 62-year-old woman shows up in the emergency department at 11:30 PM with shortness of breath that's been getting worse over three days. She has a history of breast cancer treated five years ago with anthracycline chemotherapy, chronic kidney disease (eGFR 44), type 2 diabetes, and rheumatoid arthritis on methotrexate. Her vital signs are borderline: heart rate 108, blood pressure 112/68, respiratory rate 22, oxygen saturation 93% on room air. The triage nurse orders the usual workup. The labs come back over the next hour: troponin mildly elevated at 0.08 (reference <0.04), BNP of 840, D-dimer 1,200, creatinine up from her baseline at 1.6, a mild leukocytosis, and a chest radiograph that the overnight radiologist reads as "bibasilar opacities, cannot exclude pulmonary edema vs atypical infection vs pulmonary embolism; clinical correlation recommended."

The clinician staffing the ED at 11:30 PM has four other patients to think about. This patient's story could reasonably be one of five things: a heart failure exacerbation (the anthracycline history matters; so does the BNP; her prior echo showed borderline LV function), a pulmonary embolism (elevated D-dimer, tachycardia, recent travel or immobility unknown, rheumatoid arthritis is a mild pro-thrombotic state), atypical pneumonia (the imaging is compatible, the methotrexate makes immunosuppression relevant), an acute coronary syndrome (the troponin is low-grade positive, she has diabetes), or cardiotoxicity recurrence from the remote chemotherapy (anthracycline cardiomyopathy can present years later, and the BNP fits). The clinician has to decide, in the next twenty or thirty minutes, what to image next (CT pulmonary angiography? echocardiogram? both?), what to start empirically (heparin? antibiotics? diuretics?), and where to send the patient (discharge, observation, admission to medicine, admission to a step-down, admission to the ICU).

The information to answer this question is all present somewhere. The patient's chart has the prior echocardiogram report from two years ago. The chemotherapy history is in the oncology notes. The troponin and BNP trends are in the lab system. The radiograph is in PACS, and there's a CT chest from three years ago in there too. The problem list has the relevant diagnoses. The medication list has the methotrexate and the doses. The rheumatology notes describe her joint disease activity. The endocrinology notes describe her diabetes control. The primary care notes from a month ago mention a new exertional complaint she didn't escalate. All of this exists, in different systems, in different formats (structured labs, prose notes, radiology reports, imaging pixels, vital sign time series), spanning six or seven years of care.

The clinician cannot assimilate all of it in twenty minutes. Nobody can. So she triages. She reads the triage note, scans the labs, eyeballs the radiograph herself, reviews the problem list, asks the patient a quick history, performs a focused exam, and forms a differential. She does it well, most nights. She misses things, too. The anthracycline history may not make it into her differential because it's buried in a 2020 oncology note she doesn't open. The prior echocardiogram findings may not surface because the echo report is in a different tab. The slight increase in creatinine from her baseline, which matters for contrast dye decisions and for drug clearance, may get noticed or may not. She is, in effect, running a multi-modal reasoning task on a compressed time budget with a human-sized working memory, and the outcome for this patient depends on whether the right pieces of her long longitudinal record make it into the clinician's consciousness in the next twenty minutes.

The chronic version of this problem is the primary care visit with multiple interacting conditions. A patient with diabetes, heart failure, chronic kidney disease, and a recent medication change visits her primary care doctor. The diabetes has been drifting (A1c up from 7.2 to 8.5 over six months). The heart failure is stable but she had a small weight gain logged at a nurse call last week. The kidney function has declined modestly (eGFR from 52 to 46). The last echocardiogram shows slightly worse LV function than two years ago. There are four interacting modalities here: lab trends over time, weight as a single physiologic time series, imaging-derived ejection fraction, and a pile of clinic notes. A thoughtful primary care physician synthesizes these into a coherent story: "her diabetes isn't controlled, which is worsening both her kidney function and her volume status; she needs a medication change that addresses all three." A rushed primary care physician addresses the diabetes in isolation because that's what the A1c says, and misses the interconnectedness.

The specialty version. A hepatologist is evaluating a patient for a transplant listing. The patient's labs, imaging, endoscopy findings, biopsy pathology, psychosocial evaluation, and nutritional assessment all feed into the decision. The Model for End-Stage Liver Disease (MELD) score is one number distilled from a subset of the labs, but the actual decision is multi-modal. It takes the patient a year to accumulate the data, and the decision involves a multidisciplinary committee because no single human holds all the data in their head coherently.

The bleeding-edge version. A pulmonary nodule detected on a screening chest CT has to be risk-stratified. The nodule's size, shape, and density from the CT are image features. The patient's age, smoking history, and family history are structured data. The prior imaging studies, if any, provide a time trajectory (has it grown?). The clinical context (is the patient immunocompromised? any recent infections?) is prose. Existing risk models (Mayo Clinic model, Brock model, the PanCan model) integrate some but not all of this. A reasoning system that combines all of the inputs to produce a calibrated probability and a recommended next step (observation, shorter-interval repeat imaging, PET, biopsy) is what clinicians actually need, and what current practice cobbles together manually.

What clinicians have been asking for, across all of these scenarios, is something that can reason across modalities the way a skilled consultant does: notice that the elevated BNP fits better with the heart failure hypothesis than the PE hypothesis given the prior echo, that the elevated D-dimer is less impressive given the active inflammation from rheumatoid arthritis, that the creatinine bump argues against certain contrast-requiring imaging choices. The system should surface the reasoning, not just the conclusion. It should preserve the pieces of evidence that drove the reasoning. It should flag when evidence contradicts itself. It should say "I don't know" when the picture is genuinely ambiguous.

Two years ago, this was science fiction. Today, it is barely feasible for narrow scenarios with heavy engineering investment and a willingness to keep the deployment posture conservative. The FDA has views. Your malpractice carrier has views. The radiology society has views about AI-in-imaging that apply here too. The pattern that is emerging, and the one this recipe is about, is not "let the model reason end-to-end." It is "use specialized models for each modality, combine their outputs through a reasoning layer, ground everything in the source evidence, and keep the clinician firmly in control." Multi-modal clinical reasoning is the capstone of this chapter because it is the hardest, riskiest, most regulated, and most valuable thing in the category. Done right, it helps skilled clinicians think faster and more completely. Done wrong, it is the fastest way to end up in front of the FDA explaining yourself.

---

## The Technology: Modality-Specific Encoders, a Reasoning Layer, and Visible Evidence

### What "Multi-Modal" Actually Means Here

The word "multi-modal" is used loosely in the AI literature. In this recipe, it means a specific thing: the system integrates clinical information that lives in structurally different representations. Structured lab values and vitals are numeric time series. Clinical notes are prose. Imaging reports are prose produced from pixels. Imaging studies themselves are pixel data (DICOM). ECGs are a different flavor of time series (high-frequency multi-lead waveforms). Pathology slides are also pixels but at gigapixel scale. Genomic data is a large structured record. Device data from continuous glucose monitors or wearables is streaming time series.

A single patient can have representations from several of these at once. The reasoning task is not "concatenate all of these into a single prompt." That doesn't work for two reasons. First, most modalities cannot be usefully serialized into tokens at their full fidelity. A chest CT has thousands of slices; putting them all in an LLM context is neither feasible nor productive. Second, each modality has its own domain of interpretation. A cardiologist reads an echocardiogram; a pathologist reads a biopsy; an internist synthesizes the interpretations into a plan. The reasoning system should mirror this: specialized interpretation of each modality, followed by a reasoning step that operates on the interpretations.

The practical architecture that has emerged has three layers:

1. **Modality-specific encoders** that produce either a structured interpretation (a radiology report, an ECG interpretation) or a dense embedding that can be retrieved or queried. These are often the right places to use domain-specific models: vision-language models trained on medical imaging, ECG foundation models, pathology foundation models, genomic models.
2. **A reasoning layer** that consumes the outputs of the modality encoders along with structured clinical data and prose notes. The reasoning layer is typically an LLM, prompted to produce a differential, a care recommendation, or an interpretation that ties the modality outputs together. This is where the patient-specific synthesis happens.
3. **A grounding and provenance layer** that ensures every claim in the reasoning step traces back to a specific source: this note, this lab value, this image, this ECG interpretation, this guideline. The provenance layer is what makes the output auditable and what makes the regulatory posture defensible.

The whole pipeline is expensive, slow (relative to unimodal alternatives), and risky. It is also the only approach that actually works for the kind of reasoning clinicians need help with.

### Why Not Just Put Everything in One Big Multi-Modal Model?

Research labs have released impressive multi-modal foundation models that take image and text input and produce diagnostic reasoning output. The demos are striking. The published benchmarks on curated test sets are strong. And for production deployment in healthcare, the models in their current form have several limitations that matter more than the benchmarks suggest:

- **Fidelity mismatch with clinical imaging.** A chest CT has thousands of slices at specific reconstructions. An MRI brain study has multiple sequences, each tuned for a specific purpose (T1, T2, FLAIR, DWI). Mammography has 3D tomosynthesis with specific viewing conventions. A model that accepts "an image" and produces "a finding" is usually operating on a small number of 2D images and missing most of the diagnostic signal a radiologist would use. The research publications tend to feature well-chosen 2D images that match this architecture; production clinical imaging does not.
- **Calibration and confidence.** End-to-end multi-modal models tend to be overconfident, especially on out-of-distribution inputs. A patient whose presentation doesn't match the training distribution will get a confident wrong answer rather than an uncertainty flag. This is exactly the failure mode that matters in clinical decision-making.
- **Provenance opacity.** "Why did the model say this?" is a hard question to answer for an end-to-end model. The clinician gets an output but cannot easily trace which image finding, which note passage, which lab value drove the conclusion. This is the single biggest problem for regulatory posture and clinician trust.
- **Specialty and institutional fit.** Guideline interpretations vary by specialty. Institutional protocols vary across hospitals. A generic model doesn't know your antibiogram, your formulary, your protocols. The reasoning has to happen with those in scope.
- **Regulatory status.** A model that produces a diagnostic impression from image and text is likely a medical device. A pipeline that composes already-cleared modality interpretations with an LLM reasoning layer has a more defensible path to the FDA CDS exemption, as long as the structure and transparency of the pipeline supports "independent review" by the clinician.

So the state-of-the-art research models exist and are impressive, but the production architecture that works is the compositional one: existing cleared imaging AI (or cleared vendor interpretations) producing structured outputs, existing lab and vitals data, existing note text, fed to a reasoning layer with enforced grounding and visible provenance.

### Modality Encoders

Each modality has its own set of encoders to choose from. A few notes on the landscape as it stands today.

**Medical imaging (radiology).** The field has moved in two directions. One direction is specialized narrow models cleared by the FDA: pulmonary embolism detection on CT pulmonary angiography, intracranial hemorrhage detection on CT head, pneumothorax flagging on chest radiograph, breast density estimation on mammography. These models are workflow tools, not synthesizers; they produce a specific finding with a probability. They integrate with PACS and ideally flag studies for priority reads. For a reasoning system, their outputs are structured inputs (a probability of PE, a bounding-box annotation). The other direction is vision-language models for radiology: models that take an image (or image region) and produce a textual description. MedSAM, RadFM, and various commercial offerings sit here. These are useful for producing structured descriptions that feed downstream reasoning. Very few vision-language radiology models are FDA-cleared as diagnostic devices; most are marketed as workflow or documentation assistants, which has regulatory implications.

For the reasoning pipeline here, the practical inputs from imaging are: (a) the existing radiology report, which is already a structured interpretation, and (b) optionally, FDA-cleared narrow-model outputs (the PE probability from the CT PA, the hemorrhage flag from the CT head). Direct pixel-level interpretation by a general multi-modal model, as of today, is more of a research posture than a production one.

**Electrocardiograms (ECGs).** ECG interpretation has a long history of automated algorithms shipped on the ECG machine itself (the "computer-read" at the top of every ECG report). Recent foundation models trained on large ECG datasets (at institutions like Mayo, Cedars-Sinai, and various academic centers) have shown the ability to detect subtle patterns beyond human interpretation, including LV dysfunction from a 12-lead ECG, future atrial fibrillation risk, and even age and sex estimation. Production deployment uses vendor interpretations plus, optionally, cleared foundation-model outputs where available. For a reasoning pipeline, ECG interpretation arrives as structured text plus a few derived scalars (heart rate, QTc, QRS duration).

**Pathology.** Digital pathology is moving fast. Foundation models trained on whole-slide image datasets (virtual slide archives, often by collaborations of academic medical centers) have produced models that can classify tumor tissue, predict molecular subtypes from morphology, and grade specific cancers. These are not yet broadly deployed in production pathology workflows; adoption has been strongest in high-volume tumor sites (prostate, breast) where specific cleared products exist. For a reasoning pipeline, pathology typically contributes its structured report and any cleared-model outputs.

**Laboratory data.** This is already structured. The reasoning system consumes lab values, usually with trend information (last 12 months of creatinine; last 90 days of HbA1c; last 24 hours of troponin). Trends matter more than point values for many clinical questions; a rising troponin is very different from a stable mildly-elevated troponin. Pulling and representing the trends is often the harder problem than interpreting them.

**Vital signs and continuous physiologic data.** Vital signs in outpatient care are sparse point values. In inpatient care they're continuous streams from monitors. Wearable-derived data (continuous glucose monitors, heart rate and rhythm from a wearable device, sleep metrics) is increasingly available. Interpretation ranges from simple threshold-based flags ("heart rate has been above 110 for 2 hours") to sophisticated models (early-warning scores, arrhythmia detection). For a reasoning pipeline, the practical input is summary statistics plus flagged events, not the raw waveform.

**Clinical notes.** Prose. The note-processing pipeline from Recipes 2.6 and 2.9 applies: extract entities, map to ontologies, pull out key clinical facts, preserve the raw text for grounded citation.

**Structured clinical data.** Problem lists, medication lists, allergies, procedures, and genomic data where available. Most of this comes from the EHR via FHIR. Genomic data often lives in a separate system with its own data model (VCF files, annotated variants, interpreted reports).

Each encoder produces something the reasoning layer can consume. The reasoning layer does not reinterpret the imaging pixels or the ECG waveform; it consumes the interpretations.

### The Reasoning Layer

The reasoning layer is an LLM, but with more scaffolding than the reasoning layer of a simpler RAG system. The job of the reasoning layer is to take the interpretations and structured data, consider them as a whole, and produce a coherent clinical synthesis.

Several properties matter:

- **Explicit consideration of multiple hypotheses.** A differential diagnosis is a list of hypotheses with estimated likelihoods given the evidence. The reasoning layer should enumerate these and assess each against the available data, not settle on one hypothesis prematurely.
- **Evidence-for-and-against analysis per hypothesis.** For each hypothesis, what does the data support and what does it weaken? A clinician's internal reasoning does this implicitly; the reasoning layer should do it explicitly and show it in the output.
- **Uncertainty quantification.** Some hypotheses will be well-supported by the data; others will be weakly supported; others will require more information to evaluate. The reasoning layer should distinguish among these, rather than ranking them all with similar-looking confidence scores.
- **Actionable next steps.** The reasoning output is useful when it suggests the next thing to do: image this, obtain this lab, start this empirical therapy, consult this specialty, rule out this thing before acting. Abstract differential lists are less valuable than pathway-integrated recommendations.
- **Visible provenance.** Every claim in the reasoning output should cite its source: this lab value, this note passage, this imaging finding. The output renders with claims linked to source items, so the clinician can audit the reasoning efficiently.
- **Explicit scope boundaries.** The reasoning layer should not fabricate a finding that isn't in the input. If the ECG was not available, the output should say so rather than invent an interpretation. If a guideline wasn't in the retrieval set, the output should not cite a guideline.

The practical output format is structured JSON with a narrative assessment, a ranked differential or recommendation list, per-item evidence in-favor and against citations, flagged contradictions, uncertainty tiering, and suggested next actions. This structure enables downstream validation, clean UI rendering, and audit logging.

### The Time Dimension

A lot of multi-modal reasoning in clinical practice is about change over time, not point-in-time assessment. The patient's creatinine is up from her baseline. The heart failure is worsening. The nodule has grown since the last CT. The glycemic control has drifted. The reasoning system needs to handle time explicitly: not just "what is the current value," but "how does it compare to the prior value, and what is the trend."

The common implementations:

- **Lab trends as derived features.** Compute slopes, deltas, and categorical change features (stable, rising, falling) over clinically relevant windows. Feed these as structured inputs to the reasoning layer alongside the current values.
- **Prior imaging reports as separate retrieved items.** When the current reasoning includes a new imaging study, pull the prior studies of the same anatomy and make them retrievable. Radiology reports often describe their own comparison to prior; this comparison is a high-value input.
- **Temporal event timelines.** Admissions, procedures, medication changes, specialty consults, significant labs: aggregated into a timeline that the reasoning layer can consult. A patient's story often makes sense only in the context of its sequencing.

This is where the reasoning pipeline can outperform a clinician operating under time pressure. A person working under pressure tends to anchor on recent events; a system that faithfully integrates the longitudinal record and surfaces temporally relevant context supplements the clinician's perspective exactly where they are most likely to miss things.

### Grounding and Hallucination: The Problem Scales With Modalities

Every grounding problem from earlier recipes (2.5, 2.6, 2.7, 2.9) applies here, with the additional twist that grounding targets now include imaging findings and modality outputs that aren't easily verifiable by the clinician without opening the source study. A hallucinated line like "moderate LV hypertrophy" in a reasoning output is much more damaging when the clinician doesn't re-open the echo to confirm. The trust pattern has to go further than "the model says this is in the source"; the pattern should be "the model says this, and the source link takes the clinician one click from here to exactly the sentence in the source report that supports the claim."

The additional challenges:

- **Cross-modality consistency.** The lab trend suggests volume overload; the echo shows preserved ejection fraction; the BNP is elevated. These are consistent (diastolic heart failure is compatible), but a reasoning layer that doesn't explicitly check for cross-modality consistency can write assessments that contradict the data. Validation must check every claim not just against the single source it cites, but against the broader data set.
- **Modality absence.** If one of the expected modalities is missing (no recent echo, no ECG this admission), the reasoning layer must acknowledge the absence rather than reason as if it were present. The prompt has to enforce this; the validation layer has to verify it.
- **Modality staleness.** A five-year-old echocardiogram is not the same as a current one. A three-year-old CT showing a stable nodule is different from a three-month-old CT. The reasoning layer has to consider freshness and communicate when relevant data is old.
- **Quantitative fabrication.** Numbers are particularly prone to hallucination. A model may confidently report "ejection fraction 45%" when the actual source says "ejection fraction was 55% on the 2023 echo and has not been repeated since." Numbers in the output should appear verbatim in the input; validation enforces this.
- **Grading fabrication.** Radiology reports use graded language ("mild", "moderate", "severe"). A reasoning output that upgrades or downgrades a grade is a specific and common hallucination pattern. Enforce verbatim grade preservation.

### Regulatory Posture, for Real This Time

Recipe 2.9 covered the four-part FDA CDS exemption in detail. Multi-modal reasoning sits closer to the edge of that exemption than CDS over structured data alone. The additional considerations:

- **Imaging interpretation is typically regulated.** A system that produces a diagnostic impression from pixels is a device. The CDS exemption generally does not save you. If your pipeline's output quotes or restates an imaging impression that the pipeline itself generated, you have likely created a device. If your pipeline consumes an impression generated by a cleared system or a human radiologist and uses it as input, the pipeline's output is a reasoning layer over pre-existing data.
- **Diagnostic recommendations are higher risk than management recommendations.** A reasoning output that produces a differential diagnosis is closer to diagnostic software than a reasoning output that refines a management plan given a known diagnosis. Both exist on the regulatory spectrum; their positions differ.
- **High-stakes decisions are more regulated.** Oncology treatment selection, critical care decisions, emergency triage: higher stakes and more scrutiny. The design of these systems should include additional safeguards: more clinician-in-the-loop points, more conservative uncertainty handling, more explicit "this is decision support, not diagnosis" framing.
- **Subspecialty consultation replacement is not the product.** A system framed as "replaces specialist consultation" is much more regulated than a system framed as "helps the primary clinician ask better questions before the specialist consult." The framing and the product design should match the regulatory posture you can defend.
- **Validation requirements scale with scope.** A narrow, well-scoped reasoning application (heart failure management for cardiology clinic) has a feasible validation path. A broad, general-purpose clinical reasoner has a validation surface area that is near-infinite. Most teams that succeed here start very narrow and expand deliberately, with each expansion triggering its own validation study.
- **Post-market surveillance is higher stakes.** Any deployed reasoning system should be instrumented for outcomes tracking. The regulatory framework increasingly expects evidence of real-world performance, not just pre-deployment validation on curated sets.

The conservative production posture, which is the right one for this recipe: start with a narrow, well-scoped application; build in explicit CDS-exemption-compatible design (source transparency, clinician independent review, framing as options not directives); validate rigorously; deploy in a controlled pilot; expand only after both the clinical data and the regulatory posture support it.

### The Failure Modes, Specific to Multi-Modal

All of the failure modes from earlier recipes apply. The multi-modal specific ones:

- **Cross-modality contradiction swallowed.** The echo says one thing, the lab says another, the reasoning output papers over the contradiction. Mitigation: explicit contradiction-surfacing in the prompt; post-generation validation that checks for consistency across modalities.
- **Missing modality ignored.** The ECG is not present for this patient; the reasoning proceeds as if it were. Mitigation: explicit modality-inventory step before reasoning; prompt must include an inventory of which modalities are present and which are absent.
- **Stale modality treated as current.** A three-year-old echo used to support a current assessment. Mitigation: timestamps on every modality input; the prompt must include recency and the reasoning layer must explicitly consider recency.
- **Over-reliance on one modality.** The reasoning layer anchors on the single most salient input (usually the imaging report) and underweights others. Mitigation: prompts that require evidence-for-and-against for each hypothesis, with explicit sourcing from multiple modalities.
- **Fabrication on the gap between modalities.** The reasoning layer generates a claim that sits in the gap between modality outputs ("there is likely an underlying inflammatory process") that isn't directly supported by any source. Mitigation: strict citation discipline; post-generation validation that flags uncited claims.
- **Specialty register mismatch.** A reasoning output written for a generalist audience may miss the specialist-specific nuances. Mitigation: audience-aware prompting; optional specialty-specific templates.
- **Quantitative drift.** The original report says "LVEF 50-55%," the reasoning says "LVEF 50%," downstream decisions are made on the lower number. Mitigation: verbatim-quote enforcement for all quantitative values; validation that flags any number in the output not appearing verbatim in a source.
- **Confidence miscommunication.** The reasoning layer reports high confidence because the data is internally consistent, without acknowledging that the data is incomplete. Mitigation: explicit separation of "confidence given the available data" and "completeness of the available data" in the output.
- **Scope creep.** The system trained for heart failure is used on a patient with a different primary problem; the reasoning is less applicable. Mitigation: scope-gating; explicit decline to reason when the patient's primary issue is out of scope.
- **Cumulative bias.** Each modality carries biases from its training data and its production acquisition patterns; the reasoning layer inherits and sometimes amplifies them. Mitigation: ongoing evaluation across demographic subgroups; explicit fairness monitoring in post-market surveillance.

### Why This Sits Where It Does on the Complexity Curve

Recipe 2.10 is the most complex recipe in this chapter, and arguably the most complex in the book. Three reasons compound:

1. **Data breadth.** The reasoning layer consumes inputs from several pipelines (imaging AI, ECG interpretation, lab systems, clinical notes, structured EHR data). Each is its own integration problem. Each has its own failure modes that propagate into the reasoning.
2. **Reasoning depth.** Unlike earlier recipes that describe a single kind of synthesis, this recipe requires genuine clinical reasoning across competing hypotheses with uncertainty quantification. This is closer to what expert clinicians do than what any single model alone can approximate reliably.
3. **Regulatory and liability exposure.** Every recipe in this chapter has some regulatory exposure; this one has the most. Imaging-adjacent reasoning, multi-modal diagnostic synthesis, potential direct impact on clinical decisions: the FDA, state medical boards, malpractice carriers, and institutional risk management are all stakeholders.

The payoff, when it works, is real. The cases where multi-modal reasoning helps are the cases where the clinician is under time pressure with incomplete access to the patient's longitudinal record, which is most clinical cases most of the time. The reasoning layer becomes the thing that surfaces the anthracycline history from 2020 when the patient presents with new heart failure symptoms in 2026. That is valuable. Building it safely is the point.

---

## The General Architecture Pattern

The overall flow looks like this:

```text
[Trigger: Clinical Scenario or Clinician Query]
    → [Fetch Patient Context (FHIR + Modality Inventory)]
    → [Modality-Specific Ingestion]
        → [Imaging Reports + Cleared AI Outputs]
        → [ECG Interpretations]
        → [Lab Trends and Vitals Summary]
        → [Clinical Notes]
        → [Structured EHR: Problems, Meds, Allergies]
    → [Normalize and Annotate with Timestamps and Provenance]
    → [Modality Inventory and Scope Gate]
    → [Deterministic Safety Checks (Interactions, Contraindications, Allergies)]
    → [Retrieval: Guidelines, Protocols, Prior Cases]
    → [Reasoning Layer: Multi-Hypothesis Synthesis with Grounding]
    → [Post-Generation Validation (Cite Check, Cross-Modal Consistency, Verbatim Quantities)]
    → [Tiering and Uncertainty Rendering]
    → [Render with Evidence Links to Each Modality Source]
    → [Log Full Provenance for Audit and Regulatory Evidence]
```
**Trigger.** An ED presentation, a new admission, a clinician-requested reasoning run, a planned oncology treatment-selection conversation, a multidisciplinary tumor board preparation. Scoped triggers work better than any-time-anywhere triggers for multi-modal reasoning. Start narrow.

**Fetch patient context.** Pull the FHIR bundle (as in Recipe 2.9) and also pull pointers to the imaging studies, ECG recordings, pathology reports, and other modality-specific items in their native systems. At this stage the system knows what exists; it hasn't interpreted any of it yet.

**Modality-specific ingestion.** For each modality, acquire the interpretation. For imaging, this means the radiology report (or a cleared AI output, or both). For ECG, the machine interpretation plus any cleared foundation-model output. For pathology, the reported findings. For labs, the time series with reference ranges. For vitals, summary statistics plus flagged events. For notes, the text with basic structure. For structured EHR, the problem list, medication list, allergy list. This is typically a parallel step; each modality's ingestion runs independently.

**Normalize and annotate.** Each modality's output gets timestamped, source-identified, and coded where applicable. Imaging reports get mapped to RadLex or SNOMED where useful. ECG findings get mapped to standard terminology. Labs use LOINC. Medications use RxNorm. The result is a unified patient state record with modality provenance intact.

**Modality inventory and scope gate.** Before reasoning runs, the system enumerates what is present and what is absent. The scope gate checks that the reasoning scenario is appropriate given the available modalities (you can't do a comprehensive cardiology reasoning without any cardiac imaging; either defer or scope down). The gate also suppresses reasoning when a recent reasoning run covered the same scenario without material changes.

**Deterministic safety checks.** As in Recipe 2.9: interactions, contraindications, allergies, dosing against renal and hepatic function. These run as structured queries, and their outputs become hard inputs to the reasoning layer.

**Retrieval.** Guidelines and institutional protocols relevant to the scenario. Recent case analogs from a clinical case corpus if available (a highly-curated corpus of similar cases with outcomes, useful for specific scenarios). The retrieval is similar to Recipe 2.9 but may include modality-specific retrieval (imaging findings of the same type, ECG patterns matching the current one, pathology reports with similar morphology).

**Reasoning layer.** The LLM call, with a prompt that includes the patient context, the modality inventory and interpretations, the retrieved sources, and the deterministic safety findings. The prompt enforces multi-hypothesis evaluation with evidence-for-and-against per hypothesis, verbatim preservation of quantitative values and graded terms, explicit handling of missing modalities, cross-modality consistency, citation discipline, and framing as options. The output is structured JSON.

**Post-generation validation.** Citation check (every claim traces to a source), verbatim check (numbers and graded terms match sources), cross-modality consistency check (no claim contradicts another modality's input), modality coverage check (all present modalities considered; missing modalities acknowledged), scope check (recommendations within scope). Failures retry with augmented prompting up to a cap. Retry-exhausted failures route to a distinct human-review queue with a separate DynamoDB record and S3 archive; they do NOT proceed to tier/render/archive, and do NOT flow to the clinician UI as delivered reasoning. Only a `VALIDATED` reasoning output is delivered.

**Tiering and rendering.** Recommendations tiered by clinical importance. Rendering foregrounds reasoning and evidence. Every modality source is one click away (open the imaging study in PACS, open the ECG waveform, open the original note). Uncertainty is explicit in both overall and per-recommendation form.

**Provenance logging.** The trigger, the modality inventory, each modality's interpretation, the retrieval trace, the deterministic safety findings, the prompt version, the model version, the generation output, the validation result, the rendered output, the clinician engagement. This is the regulatory evidence trail.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.10-architecture). The Python example is linked from there.

## The Honest Take

Multi-modal clinical reasoning is the use case where the gap between capability demos and deployed reality is widest. The demos are compelling. The benchmarks on curated sets are often strong. The production reality is harder than it looks, and the failure modes hurt patients in specific and occasionally subtle ways. Anyone building this should start from the assumption that they are building a medical device by another name, and that the care with which they build it matters.

A few things that are true, said plainly.

**Start with the narrowest possible scope.** The temptation to build a general reasoner is strong and wrong. The teams that have succeeded in pilot deployments have scoped to very specific clinical situations: dyspnea in the ED, oncology treatment selection for a specific cancer, heart failure readmission risk review. Narrow scope makes validation feasible, makes the UX designable, makes the regulatory posture defensible, and makes clinician engagement earnable. Breadth is a future problem.

**Build on cleared components where possible.** If your pipeline depends on imaging AI outputs, use FDA-cleared products within their cleared scope. If it depends on ECG interpretations, use the machine interpretations plus cleared models where available. The reasoning layer over cleared inputs is more defensible than a reasoning layer that also produces diagnostic impressions from pixels.

**Enforce grounding ferociously.** Every quantitative value, every graded term, every drug name, every dose in the output must appear verbatim in a cited source. Every recommendation must carry explicit citations. Every claim must be verifiable. Validation is the belt to Guardrails' suspenders. Omit either and the hallucination rate climbs to levels that will cause patient-facing harm.

**Make reasoning visible in the UI.** The clinician needs to see the evidence for and against each hypothesis with sources one click away. If the UI foregrounds conclusions with reasoning tucked behind, clinicians under time pressure will skip the reasoning and act on the conclusions. That path loses the CDS exemption and trust at the same time.

**Acknowledge missing and stale modalities explicitly.** The reasoning output should say what is absent that is relevant and what is old that may have changed. A reasoning output that presents a confident conclusion without acknowledging its data limitations is misleading in a way that looks helpful, which is the worst kind of misleading.

**Budget time for clinical validation you cannot skip.** Expert clinical review of curated scenarios is the main rate-limiter for expanding scope. Domain experts are scarce, their time is expensive, and the review is cognitively demanding. A realistic schedule reserves four to eight weeks per scenario per reviewer. Parallelize reviewers when possible; do not short-circuit the process.

**Commit to post-market surveillance.** The day you deploy is not the day you finish. Outcomes data, engagement data, override patterns, demographic subgroup performance, cross-modality consistency metrics, specific error categorizations: these are the inputs to the next iteration. Most deployments under-invest here; the ones that succeed treat it as half the work.

**Do not conflate fluency with correctness.** A well-written reasoning output looks authoritative. A well-written and wrong reasoning output is still wrong. Do not trust the model's eloquence. Trust the validation layer and the clinician's review.

**Keep the clinician the decision-maker.** The value of multi-modal reasoning is faster access to the relevant parts of a patient's record and a second pass through possible explanations, not autonomous decision-making. The product design, the framing in every piece of output, the UX at every engagement point, and the regulatory posture all have to consistently treat the clinician as the agent who decides. The moment any of these drifts toward "the system decides," the product has crossed a line that it should not cross.

One more thing, a personal note. The patients who benefit from this the most are the complicated ones: long histories across several specialties, multiple modalities of data, subtle temporal trajectories, time-pressured clinicians who cannot hold the whole picture in their head. These are exactly the patients who experience the most documentation-driven failures in the current system. Getting this right is not a technical curiosity; it is a meaningful improvement in how care is delivered. Getting it wrong, correspondingly, hurts the patients who need it most. Build like it matters.

---

## Related Recipes

- **Recipe 2.5 (After-Visit Summary Generation):** Patient-facing synthesis that can build on the same reasoning output for shared decision-making support.
- **Recipe 2.6 (Clinical Note Summarization):** Note-level synthesis that feeds the clinical-notes modality of the reasoning pipeline.
- **Recipe 2.7 (Literature Search and Evidence Synthesis):** Retrieval and citation patterns that inform the guideline and case-analog layer of the reasoning pipeline.
- **Recipe 2.8 (Ambient Clinical Documentation):** Produces the conversational-context modality that, in some variants, becomes an input to reasoning.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** The structured-data counterpart of multi-modal reasoning. Most of the architectural patterns (safety checks, retrieval, validation, provenance) are shared.
- **Recipe 9.x (Computer Vision / Medical Imaging):** Cleared imaging AI components and vision-language model patterns that produce the imaging modality inputs. <!-- TODO (TechWriter): update to specific recipe number once Chapter 9 is drafted. -->
- **Recipe 12.x (Time Series Analysis / Forecasting):** Trend and trajectory modeling for lab and vital-sign modalities. <!-- TODO (TechWriter): update to specific recipe number once Chapter 12 is drafted. -->
- **Recipe 13.x (Knowledge Graphs / Ontology):** Relationship modeling across drugs, diseases, guidelines, and anatomical structures that can augment the retrieval layer. <!-- TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted. -->
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** Risk scores as inputs to the reasoning layer and as triggers for reasoning runs. <!-- TODO (TechWriter): update to specific recipe number once Chapter 7 is drafted. -->

---

## Tags

`llm` · `generative-ai` · `multi-modal` · `clinical-reasoning` · `bedrock` · `guardrails` · `healthlake` · `healthimaging` · `comprehend-medical` · `opensearch` · `aurora-pgvector` · `sagemaker` · `fhir` · `smart-on-fhir` · `cds-hooks` · `imaging-ai` · `ecg` · `pathology` · `differential-diagnosis` · `grounded-generation` · `citation-verification` · `fda-cds` · `fda-samd` · `evidence-synthesis` · `complex` · `hipaa` · `regulatory` · `provenance`

---

*← [Recipe 2.9: Clinical Decision Support Synthesis](chapter02.09-clinical-decision-support-synthesis) · [Chapter 2 Index](chapter02-preface)*
