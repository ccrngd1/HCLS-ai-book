<!--
Editor pass v1 (TechEditor, 2026-05-15):
- A1 (HIGH): Architecture diagram updated with bounded retry edge and a
  Human Review Queue terminal node (does not flow to delivery). Post-generation
  validation prose bullet in General Architecture Pattern expanded to name
  the non-delivery path. New orchestration gate added between Step 9 and
  Step 10 distinguishing VALIDATED from VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW.
  Coordinated with Python companion code-review Finding 1.
- S1 (MEDIUM): PHI minimization note added between Step 2 and Step 5; bullet
  added to "Why This Isn't Production-Ready."
- S2 (MEDIUM): Input-side prompt-attack filter prerequisite added to the
  Step 8 Guardrails comment block.
- A2 (MEDIUM): Deterministic event-key idempotency note added to Step 1;
  bullet added to "Why This Isn't Production-Ready."
- A3 (MEDIUM): Literal Bedrock model IDs in pseudocode replaced with
  placeholder constants (SMALL_MODEL_ID, EMBEDDING_MODEL_ID,
  SYNTHESIS_MODEL_ID) with family-name comments, matching Recipe 2.10's
  chapter template.
- S3 (LOW): Grounding threshold (>= 0.85) named in Step 8 Guardrails block
  and in Why These Services paragraph.
- A4 (LOW): Cost-estimate ceiling clarified for complex multi-scenario
  syntheses with validator retry.
- N1, N2, N3 (LOW): VPC interface-endpoint list now includes execute-api
  (conditional, private API Gateway), CloudWatch (monitoring), and rds-data
  (conditional, Aurora Data API path).
- V3 (LOW): Markdown links added to same-chapter Related Recipes entries.
-->

# Recipe 2.9: Clinical Decision Support Synthesis

**Complexity:** Complex · **Phase:** MVP → Production · **Estimated Cost:** ~$0.15-$1.20 per synthesized recommendation (typical); approaching $2.00 for complex multi-scenario syntheses with validator retry

---

## The Problem

It's 2:40 AM in the ICU. A hospitalist is standing over a 74-year-old man with sepsis from a presumed urinary source. The patient has chronic kidney disease (eGFR 28), atrial fibrillation on apixaban, heart failure with reduced ejection fraction, a sulfa allergy (rash, not anaphylaxis), and a history of C. diff colitis two years ago. The local antibiogram favors piperacillin-tazobactam for urinary sepsis, but the patient's renal function argues for dose adjustment. The pharmacist is at home. The infectious disease fellow is covering three other floors. The hospitalist has roughly four minutes to decide on an empiric antibiotic regimen before the next rapid response pages her.

She knows the guideline in general terms: Surviving Sepsis says broad-spectrum antibiotics within an hour, source-directed when known, renal dosing adjustments for applicable agents. She knows her institution's antibiogram. She knows apixaban has drug interactions. She doesn't remember, in this moment, whether piperacillin-tazobactam has a meaningful interaction with apixaban (it does not, but ciprofloxacin does, and she's going to swap to a fluoroquinolone if she decides the patient has a true beta-lactam concern from the sulfa history, which she also needs to reason about). She doesn't remember the exact renal dose of piperacillin-tazobactam at eGFR 28 (the answer depends on whether it's extended-infusion dosing or traditional, and on whether she's prioritizing coverage or toxicity concerns). She's going to make a good-enough decision in the next four minutes, and it's going to be based on her training, her gestalt, and whatever references she can scan quickly on her phone.

This is clinical decision support. Not the kind that pops up an alert when she writes the order. The kind that, ideally, synthesizes what's known about this specific patient, surfaces the relevant guidelines, flags the interactions and contraindications, and presents a defensible recommendation with its reasoning visible. The kind that is currently, in most hospitals, a combination of the clinician's memory, a frantic search through UpToDate, a call to pharmacy if pharmacy is reachable, and a hope that nothing important gets missed.

The chronic version of the same problem sits in primary care. A physician is seeing a 68-year-old woman with type 2 diabetes (HbA1c 8.2), hypertension (blood pressure 148/88 on lisinopril and amlodipine), mild CKD (eGFR 52), obesity (BMI 34), and recent-onset atrial fibrillation. She's on metformin and sitagliptin. She's asking about one of the GLP-1 agonists she saw advertised on TV. The physician has eleven minutes left in the visit. The relevant guidelines touch multiple specialty societies (ADA, ACC/AHA, KDIGO, ESC) with different emphases. The drug choice has to consider cardiovascular benefit, renal benefit, weight effect, cost, coverage, and the patient's specific contraindications (history of pancreatitis would be a red flag; she doesn't have one). The physician will make a good decision, probably. It will take her about six of those eleven minutes to do it well, leaving five for everything else the visit needed to cover. Most days she does not have that time, and the medication decision defaults to whatever she most recently prescribed for a similar patient.

The specialty version. An oncologist is initiating therapy for a patient with metastatic non-small-cell lung cancer. The molecular testing came back showing an EGFR exon 19 deletion and PD-L1 expression at 40%. The NCCN guideline recommends osimertinib as first-line therapy for EGFR-mutant disease; the patient has moderate baseline QTc prolongation (475 ms) and is on ondansetron and escitalopram, both of which prolong QT. The oncologist needs to decide: proceed with osimertinib and tighter cardiac monitoring, switch the ondansetron to a different antiemetic, attempt escitalopram substitution, or some combination. Each option has a rationale; the right choice depends on specifics of this patient (how critical is the SSRI to depression management, what's the nausea burden going to look like on osimertinib, what's the baseline cardiac function). The decision exists in a space the oncologist has seen before but will still spend fifteen to thirty minutes synthesizing carefully. Without that synthesis time, the default is a QT alert at order entry that the oncologist overrides because overriding is faster than resolving, and a patient begins therapy with unresolved risk.

The inpatient version that kills people. A patient on the medical floor is admitted for community-acquired pneumonia. She's started on ceftriaxone and azithromycin per the institutional protocol. On day two, she develops worsening renal function. The hospitalist on service does not notice that the patient's vancomycin, added on admission for MRSA coverage when the initial cultures were pending, is now at a trough of 34 with an AUC well into the nephrotoxic range. The pharmacy team flagged it six hours ago; the alert scrolled past in a list of other alerts the hospitalist had already dismissed (K+ 3.4, blood pressure 88/54 already addressed, a random phosphorus value). The alert was correct. The alert was also one of 180 alerts that the hospitalist saw that shift, and the cognitive load of discriminating signal from noise is the actual problem.

This is alert fatigue, and it is the single best argument for doing clinical decision support differently. CPOE alerts that fire on every order, with default thresholds not tuned to the specific patient, with no reasoning about prior decisions, with no suppression of alerts the clinician has already addressed in this patient's stay, make the clinician's life worse, not better. The response to alert fatigue has been, in most places, to override first and ask questions later. The patient who gets nephrotoxic vancomycin because a valid alert was lost in a sea of stupid ones is a real case, not a hypothetical.

What clinicians have been asking for, for about as long as there have been EHRs, is a decision support system that reasons about the whole patient, prioritizes what's actually clinically important right now, synthesizes across guidelines that have different emphases, surfaces the reasoning so the clinician can audit it, and lets the clinician disagree with an intact line of argument. Not more alerts. Smarter, fewer, better-explained, patient-specific recommendations.

Five years ago this was beyond the state of the art for anything that could run at scale in a hospital. Rule-based systems existed but scaled poorly across the combinatorics of guidelines, drugs, and patient states; every new rule added interacted with every other rule; the systems became unmaintainable above a few thousand rules. Modern LLMs, grounded in authoritative sources and wired into patient context through FHIR, change the feasibility equation. They also change the risk equation. A synthesis that the clinician acts on is a clinical decision, and a wrong synthesis is a decision-supported error. The FDA has rules about this. Your legal team has opinions. Your patients, if they knew, would have opinions too.

The architecture that actually works for this, and the guardrails that are genuinely non-negotiable rather than theater, are what this recipe is about.

---

## The Technology: Grounded Synthesis Over Authoritative Sources, Anchored in a Patient Record

### The Evolution of CDS, in One Paragraph

Clinical decision support has been around as long as computers have been in hospitals. The first generation was rule-based: hard-coded if-then statements ("if patient has penicillin allergy and penicillin is ordered, alert"). Rule-based CDS is precise, auditable, and deterministic, which makes it easy to validate and easy to reason about legally. It is also extremely labor-intensive to maintain. Every new guideline version requires rule rewrites. Every new drug requires new interaction rules. Every institutional protocol is its own rule set. A large health system ends up with twenty-thousand rules, of which nobody knows which ones are still clinically appropriate, and the system devolves into alert fatigue because rule interactions produce too many fires. The second generation introduced statistical and machine-learning methods, mostly for risk scores (sepsis early-warning, readmission risk, deterioration scores). These work in narrow domains with good training data and validate reasonably well for specific predictions. The third generation, which we're in now, combines grounded retrieval over authoritative sources with LLM synthesis. It can reason across guidelines, patient context, drug databases, and institutional protocols in ways the rule-based system couldn't, but it introduces the hallucination and faithfulness problems the earlier generations didn't have to manage.

### How CDS Synthesis Differs From Literature Search

Recipe 2.7 covered literature search and evidence synthesis. Both use RAG. Both ground generation in retrieved sources. It would be reasonable to ask how 2.9 is different, and the answer matters because the architectures diverge in several specific places.

Literature synthesis is descriptive. The user asks a question; the system retrieves relevant papers and describes what the evidence shows. The clinician draws conclusions. The system's job stops at "here's what the literature says." There is no prescription.

Decision support synthesis is patient-specific and (carefully) prescriptive. The input is not just a question; it's a question plus a patient context (age, comorbidities, medications, labs, recent events). The retrieval targets are not primary literature; they're pre-synthesized authoritative sources (guidelines, drug interaction databases, institutional protocols). The output is a recommendation, with reasoning visible, that the clinician can accept, modify, or reject. The system's job is to propose action, not just describe evidence.

Those differences ripple through the architecture:

- **Source types.** Literature RAG pulls from PubMed, Cochrane, PMC. Decision support pulls from guidelines (AHA/ACC, IDSA, NCCN, USPSTF, KDIGO, etc.), drug databases (Lexicomp, Micromedex, First Databank, or open equivalents like DDInter), institutional protocols, and formularies. Guidelines and drug databases are already synthesized; the system doesn't have to re-derive evidence from primary studies, which is both an advantage (the synthesis is already graded) and a constraint (you need licensing, which costs money).
- **Patient context is the primary retrieval driver.** In literature search, the clinician's question drives retrieval. In decision support, the patient's specific context drives retrieval. Age, weight, renal function, allergies, current medications, active problems, recent labs, recent imaging, recent admissions. Most of this comes from the EHR, typically via FHIR. Retrieval has to combine the clinician's question (or the clinical scenario) with the structured patient context.
- **Contradictions are first-class.** Guidelines disagree. ADA guidance on metformin discontinuation at eGFR thresholds evolved over the last decade; some institutions follow older thresholds. The ACC/AHA and the ESC sometimes diverge on anticoagulation in specific populations. A CDS system has to surface contradictions and explain them, not paper over them with a false consensus. Literature RAG has this problem too, but it's more acute in CDS because the output is a recommendation and one side of the contradiction has to get implicitly endorsed.
- **Regulatory posture.** Descriptive literature synthesis sits lower in regulatory risk. Decision support that proposes specific actions can cross into FDA-regulated clinical decision support software depending on how it's structured. The 21st Century Cures Act carved out an exception for CDS that a clinician can "independently review," but the boundaries of that exception are interpreted narrowly. We'll cover this in more depth below.
- **Alert fatigue is a design force, not a side effect.** A clinical decision support system that fires too often gets ignored the same way CPOE alerts get overridden. "Don't produce a recommendation unless it's worth the clinician's attention" is a product principle, not a nice-to-have. Triage and suppression are part of the architecture.

### The Authoritative Sources Layer

The quality of a CDS system is bounded by the authoritative sources in its corpus. Mediocre sources produce mediocre recommendations no matter how good the model is. The sources fall into several categories:

**Clinical guidelines from specialty societies.** The AHA/ACC cardiovascular guidelines, NCCN oncology guidelines, IDSA infectious disease guidelines, USPSTF preventive care recommendations, KDIGO nephrology guidelines, ADA diabetes guidelines, ACOG obstetric guidelines, AAP pediatric guidelines, and many others. These are typically PDFs or structured documents; some societies offer API access for licensed users. Freshness matters (guidelines update every 2-5 years, with interim statements and updates more frequently). Not all guidelines are machine-readable in a useful way; many are long prose documents that have to be chunked thoughtfully and tagged with metadata about their recommendations.

**Drug databases.** Drug-drug interactions, drug-disease interactions, dosing by renal function and weight, pregnancy categories, QT-prolongation risk, pediatric dosing. Lexicomp, Micromedex, Clinical Pharmacology, and First Databank are the commercial incumbents. DDInter (open dataset) and DrugBank (research-oriented) are open-ish alternatives. These databases are structured (explicit tables of drug pairs with severity ratings) which makes retrieval more precise than prose guidelines, but licensing for commercial databases is expensive and restricts redistribution.

**Drug reference content.** Package inserts (SPLs, structured product labels) from the FDA are freely available and describe approved indications, dosing, contraindications, and warnings. They're prose-heavy and not always easy to parse, but they're authoritative and redistributable.

**Institutional protocols.** Your hospital's sepsis protocol. Your cancer center's chemotherapy order sets. Your ED's stroke workflow. These are institution-specific and often the most clinically useful because they reflect local practice, local antibiograms, local formularies, and local constraints. They are also almost never part of commercial CDS products, which is why a generic commercial product always feels slightly wrong to the clinicians using it.

**Clinical pathways and order sets.** Standardized sequences of orders for specific conditions (DKA protocol, tPA protocol, sepsis bundle). These are often stored in the EHR as order sets and can be referenced as structured data.

**Formulary and coverage information.** Does your health plan cover this drug? What's the preferred alternative? Is prior auth required? What's the tier? Clinicians care about this because it affects whether the patient will actually fill the prescription. Sources include internal formulary tools, pharmacy benefit manager APIs, and services like Surescripts.

**Patient-safety databases.** The Beers Criteria for inappropriate medications in elderly patients, the STOPP/START criteria, the NCCN patient safety triggers, the Joint Commission's National Patient Safety Goals. These are synthesis documents that already incorporate evidence; including them in the corpus means the system can reason about "this patient is on a Beers-listed medication" directly.

The design decision: which sources, with what freshness, at what cost, with what licensing posture. A well-designed CDS system ranks sources by authority and specificity (institutional protocol outranks society guideline for institutional-specific questions; society guideline outranks drug package insert for clinical-context questions; drug database outranks guideline for interaction-specific questions).

### Patient Context Is the Primary Retrieval Input

In literature search, the clinician's free-text question drives retrieval. In CDS, the patient context drives retrieval, and the clinician's question (if any) is a secondary filter. The patient context is structured: demographics, active problems, current medications, allergies, vital signs, recent labs, recent imaging, recent procedures, admission context, advance directives.

Most of this comes from the EHR. The standard data model is FHIR (Fast Healthcare Interoperability Resources), which represents patients, conditions, medications, observations (including labs and vitals), procedures, and clinical documents as structured JSON resources with standardized terminology bindings (SNOMED for conditions, RxNorm for medications, LOINC for observations, ICD-10 for billing codes). A CDS synthesis system typically consumes a FHIR bundle representing the patient's current state.

The retrieval pattern then becomes:

1. Parse the patient context into structured facts.
2. Generate retrieval queries from the facts and the clinical question (if provided). "Patient with eGFR 28 and sepsis from urinary source" produces queries targeting renal dosing of common sepsis antibiotics, local antibiogram, guidelines on urinary sepsis, interactions with the patient's current medications.
3. Apply metadata filters to retrieval (source type, recency, clinical domain, patient population). Patient is elderly with CKD and on anticoagulation; filter toward guidelines and drug interactions relevant to those characteristics.
4. Retrieve structured items (drug interaction table rows, guideline recommendations) and prose items (guideline sections, protocol descriptions).
5. Pass the full retrieval set, together with the patient context, to the generation step.

The structured retrieval piece deserves more attention than it typically gets. Drug interaction databases are not unstructured text; they are tables of (drug A, drug B, severity, mechanism, clinical effect, management). Retrieving from them should be a table query, not a vector search. The same is true for dosing by renal function (a lookup in a dose table), for contraindication lists, for pregnancy categories. A CDS system that treats all of its authoritative sources as prose-to-be-vector-embedded loses precision where precision is available. Hybrid retrieval that combines structured queries against tabular sources with vector/keyword search against prose sources is the right architecture.

### The Generation Step, With More Rules Than Usual

The generation prompt for CDS does more specific work than for literature synthesis. It has to:

- Produce a recommendation (or explicitly decline to recommend when the evidence is insufficient or the question is out of scope).
- Cite every factual claim to a specific source chunk or structured record.
- Preserve exact values for doses, frequencies, drug names, and numerical cutoffs. No paraphrasing.
- Surface all identified drug interactions and contraindications found in the retrieval, not just those the model thinks are most important.
- Show the reasoning: "Because the patient's eGFR is 28, piperacillin-tazobactam dosing should be reduced to X (source Y)."
- Explicitly state the evidence basis for each recommendation component (guideline recommendation with level of evidence, package insert dosing, institutional protocol, patient-specific calculation).
- Frame recommendations as options for the clinician, not directives. The clinician is the final decision-maker.
- Surface uncertainty honestly. "The evidence on duration of therapy for this scenario is limited; guidelines suggest a range of 7-14 days." Not "the recommended duration is 10 days" when there isn't a clean answer.
- Handle contradictions explicitly. If two authoritative sources disagree, surface both and explain the disagreement.
- Never prescribe actions outside the clinician's scope (e.g., don't recommend surgical intervention in a CDS surface aimed at medical management).

The practical pattern is a structured output (JSON) with: overall assessment, ranked recommendations, per-recommendation reasoning with citations, flagged interactions and contraindications, items the clinician should consider asking about, and a confidence/uncertainty rating. The structured format enables programmatic post-validation and clean rendering in the UI.

### The FDA CDS Rule: Where This Becomes a Medical Device

The 21st Century Cures Act, signed in 2016, included language carving out certain clinical decision support software from FDA medical-device oversight. The FDA's subsequent guidance (finalized September 2022) interprets this exception narrowly. A CDS system is exempt from medical-device regulation if and only if it meets all four of the following criteria:

1. The software is not intended to acquire, process, or analyze a medical image or signal from an in vitro diagnostic device or pattern from a signal acquisition system.
2. The software is intended for the purpose of displaying, analyzing, or printing medical information about a patient or other medical information (such as peer-reviewed clinical studies and clinical practice guidelines).
3. The software is intended to support or provide recommendations to a health care professional about prevention, diagnosis, or treatment of a disease or condition.
4. The software is intended to enable the health care professional to independently review the basis for such recommendations so that the professional does not rely primarily on the software to make clinical decisions.

The fourth criterion is the one that does the most work. "Independently review the basis" means the clinician has to be able to see why the system is recommending what it's recommending, in enough detail that the clinician could arrive at the same conclusion themselves from the sources. A system that says "administer drug X" without showing the guideline reference, the patient-specific reasoning, and the alternatives is relying on the clinician *not* to think about it independently, and probably falls under FDA oversight as a medical device.

Concretely, for the architecture you're building:

- Every recommendation must display its sources and reasoning. Not as a footnote. Prominently. Clickable-through to the source document.
- The system should explicitly frame outputs as "suggestions based on [sources]" rather than directives.
- The UI has to invite clinician judgment, not bypass it. Single-click acceptance with the reasoning hidden is a regulatory risk.
- Documentation of how the system was built, validated, and updated needs to be comprehensive enough to produce for FDA on request. If your posture is "we're exempt," you should be able to demonstrate that posture on demand.

Interpretations of the rule are still evolving. Generative AI in CDS is new enough that FDA has not issued generative-AI-specific guidance as of this writing. <!-- TODO (TechWriter): verify current status of FDA generative-AI CDS guidance as of writing; check for recent updates to the September 2022 CDS guidance. --> The conservative posture, and the one most legal teams are recommending, is: build for exemption, but build as though you might have to defend the exemption in a regulatory conversation. That means rigorous documentation, explicit source traceability, and clinician-facing UIs that foreground reasoning.

This is a sufficiently big topic that it has its own recipe-adjacent considerations. For a deeper treatment, FDA's guidance document is reasonably readable ([linked below](#additional-resources)). Get your regulatory affairs team involved from day one. Do not build the thing and then ask whether it's a medical device.

### Alert Fatigue As a Design Principle

Rule-based CDS in EHRs is the canonical example of what not to do. Every order triggers alerts. Every lab triggers alerts. Alerts fire on default thresholds that are not tuned to the patient. Alerts fire even when the clinician already addressed the issue. Clinicians override 90% of CPOE alerts. The alerts that save lives are drowned in a sea of alerts that don't, and the survival of the important alert depends on the clinician being lucky or rigorous in that moment.

LLM-based synthesis CDS has an opportunity to do this better, if you design for it:

- **Trigger on clinical scenarios, not every order.** A fresh admission for sepsis is a clinical scenario that warrants a synthesis. A one-off medication change may not be. Most outpatient visits don't need real-time synthesis. Select the scenarios where the value clearly justifies the interruption.
- **Suppress when addressed.** If the clinician has already reviewed the synthesis for this patient in this encounter, don't re-surface it for minor changes. Version the synthesis, track whether the clinician has engaged with it, and only re-surface on material changes to the patient state.
- **Tier recommendations by clinical importance.** A critical drug interaction (QT prolongation, drug that will harm the patient) is a different tier from a minor one (suboptimal dosing that has no immediate safety impact). The UI should make the tier clear and should not give a minor recommendation the same visual weight as a major one.
- **Respect clinician rejection.** If a clinician rejects a recommendation with a reason, don't re-surface the same recommendation for this patient. Track rejection and incorporate it into future syntheses.
- **Measure engagement, not just delivery.** "We delivered 10,000 recommendations" is a vanity metric. "Clinicians acknowledged the recommendation in 85% of cases and accepted the recommendation in 40%" is a useful metric. "Patients for whom the recommendation was accepted had a 3% lower rate of adverse drug events" is the metric that matters.

The uncomfortable truth about alert fatigue is that the solution requires fewer alerts, which means making explicit decisions about what not to surface. That's politically hard; someone always wants their favorite alert in the system. But a CDS system that surfaces five high-value recommendations a day is worth more than one that surfaces fifty mixed-value ones.

### The Failure Modes You Have to Design Around

Most of these overlap with literature-RAG failure modes but hit harder because the output is action-oriented.

**Fabricated recommendations.** The model generates a recommendation that isn't supported by any retrieved source. Mitigation: constrain generation to the retrieved set; post-generation validate that each recommendation component traces to a source.

**Fabricated dose or dosing frequency.** The model plausibly-but-wrongly completes a dosing recommendation. "Ceftriaxone 2g IV daily" may or may not be right depending on indication and renal function. Mitigation: preserve verbatim dosing from source tables; pull dosing from structured drug databases, not LLM generation; validate that any dose in the output appears verbatim in a retrieved structured record.

**Missed interaction.** The patient is on drug A, the recommendation proposes drug B, and there is an interaction the system didn't surface. Mitigation: exhaustive interaction query against the full current medication list as a deterministic step before generation, not left to LLM pattern matching; make the interaction check a separate pipeline stage whose output is passed to the generation step.

**Missed contraindication.** The patient has an allergy or a condition that contraindicates the recommended drug. Mitigation: same approach as interactions; deterministic contraindication check before generation.

**Population mismatch.** A recommendation based on adult literature applied to a pediatric patient, or based on male-dominated trial populations applied to a patient in an underrepresented subgroup. Mitigation: patient-context-driven retrieval filters; explicit population tagging in retrieved chunks.

**Wrong side of equipoise.** Guidelines disagree; the model picks one side and presents it as consensus. Mitigation: contradiction surfacing in the generation prompt; structured output with explicit "competing recommendations" fields when sources disagree.

**Stale guidance.** A guideline in the corpus was updated six months ago; the system is still recommending the prior version. Mitigation: aggressive ingestion pipeline for guidelines; surface guideline date in every recommendation; flag recommendations where the guideline is older than a threshold.

**Over-confident recommendation on limited evidence.** The clinical scenario is unusual; the guidelines don't directly address it; the system synthesizes a recommendation anyway. Mitigation: explicit "evidence directly addresses this scenario vs extrapolates from related scenarios" flag; uncertainty surfacing in the UI; willingness to say "the retrieved sources don't address this specific scenario."

**Recommendation bypasses clinician judgment.** The UI nudges the clinician to accept without reviewing reasoning. Mitigation: UI design that invites engagement; measure whether clinicians read the reasoning; make single-click acceptance slightly harder than reviewing the reasoning first.

**Recommendation out of scope.** The clinician is asking about medication management; the system recommends a surgical consultation. Mitigation: scope the generation to the intended CDS surface; prompt engineering; post-generation validation that flags out-of-scope recommendations.

**Formulary mismatch.** The system recommends a drug that isn't on the patient's formulary, or requires prior auth the team hasn't initiated. Mitigation: formulary and coverage data in the retrieval set; generation prompt that considers formulary status; UI flag for non-preferred drugs.

**Regulatory drift.** The system, through prompt iteration, starts producing outputs that look more directive and less advisory. Someone on the product team thinks "users want a clearer answer" and pushes prompts toward prescriptive language. Six months later the outputs arguably fall outside the FDA exemption. Mitigation: prompt versioning with regulatory review; periodic compliance audits of output samples; a rigid "we describe options; we do not prescribe" style guide enforced in prompts and validated post-generation.

### Why This Sits Where It Does on the Complexity Curve

Recipe 2.9 is Complex, not just Medium-Complex like 2.7, because three things compound:

1. **Patient-specific reasoning.** Unlike literature synthesis, which operates on the clinician's question, CDS reasons over the full patient context. The retrieval problem is harder (you're not just matching a query to papers; you're combining a structured patient state with a clinical scenario to find the right authoritative material), and the generation problem is harder (the output has to be specific to this patient, not a generic summary).

2. **Action-oriented output.** A recommendation that the clinician acts on is a clinical decision. Wrong recommendations have patient-level consequences. The verification bar is higher. The validation layer has to do more work. The UI has to foreground reasoning, not conclusions.

3. **Regulatory posture.** FDA CDS rules, medical-device considerations, state licensure concerns. These are not blockers, but they shape the architecture. Every design decision has a compliance dimension.

Layered on top of these are the standard hard problems of RAG (corpus quality, retrieval precision, citation faithfulness) that Recipe 2.7 already covered. CDS gets all of those plus the three above.

The good news is that the architectural patterns are known. The bad news is that there are a lot of them, and skipping any one of them produces a system that fails in ways that are embarrassing at best and dangerous at worst. This is not a weekend project.

---

## The General Architecture Pattern

The overall flow looks like this:

```text
[Trigger: Clinical Scenario or Clinician Query]
    → [Fetch Patient Context from EHR (FHIR)]
    → [Normalize and Structure Patient Facts]
    → [Scope Determination: Is This a Scenario We Synthesize For?]
    → [Deterministic Safety Checks (Interactions, Contraindications, Allergies)]
    → [Scenario Classification and Retrieval Planning]
    → [Multi-Source Retrieval (Guidelines, Drug DBs, Protocols, Formulary)]
    → [Rank and Filter by Source Authority and Patient Specificity]
    → [Grounded Synthesis with Citation and Reasoning Discipline]
    → [Post-Generation Validation (Cite Check, Dose Check, Interaction Coverage)]
    → [Recommendation Tiering and Alert-Fatigue Suppression]
    → [Render with Reasoning, Sources, and Uncertainty]
    → [Log for Audit, Feedback, and Regulatory Evidence]
```

Let's walk through each stage conceptually.

**Trigger.** The synthesis is invoked either by a clinical scenario (admission, new diagnosis, significant lab abnormality, new medication order) or by an explicit clinician request. The trigger logic is product-specific; the principle is to trigger on scenarios where synthesis has clear value, not on every possible event.

**Fetch patient context.** Pull a FHIR bundle representing the current state: demographics, active conditions, current medications, allergies, recent vital signs, recent labs (especially renal and hepatic function), recent imaging, procedures, advance directives. The bundle is the input to everything downstream.

**Normalize and structure.** Map medications to RxNorm, conditions to SNOMED and ICD-10, labs to LOINC, findings to UMLS concepts where helpful. Compute derived values: eGFR from creatinine when needed, Child-Pugh from hepatic labs when relevant, pack-years from smoking history. Derived values are what many guidelines actually key on.

**Scope determination.** Not every trigger should produce a synthesis. A routine refill of a chronic medication probably doesn't. An admission with multiple active comorbidities probably does. The scope gate prevents synthesis sprawl and is a key lever against alert fatigue.

**Deterministic safety checks.** Before LLM synthesis runs, do the things that don't need LLM synthesis: query the drug interaction database for every pair in the current medication list plus any proposed medications, check allergies against any drugs under consideration, check contraindications against active problems, check dosing against renal and hepatic function. These are deterministic table lookups. Their outputs become hard-coded inputs to the generation step. If the system misses an interaction here, it's a bug in the check, not a model failure.

**Scenario classification.** Given the patient state and the trigger, classify the scenario. "Empiric antibiotic selection for septic patient with renal dysfunction and anticoagulation" is a scenario. "First-line therapy selection for EGFR-mutant NSCLC with baseline QT prolongation" is a scenario. Classification drives retrieval: which guidelines apply, which drug databases are relevant, which institutional protocols exist.

**Multi-source retrieval.** Parallel retrieval across the source types. Structured queries against drug databases (interactions, dosing, contraindications). Hybrid vector and keyword retrieval across guidelines and protocols. Formulary lookup. Local antibiogram retrieval if applicable. Metadata filters by patient population, clinical domain, recency.

**Rank and filter.** Rank retrieved items by source authority (institutional protocol outranks society guideline for institution-specific decisions; guideline outranks package insert for clinical questions; drug database trumps everything for interaction specifics). Filter for patient specificity (matching age group, comorbidities, severity tier).

**Grounded synthesis.** Construct the generation prompt with the patient context, the retrieved sources with source tiers, and the deterministic safety-check results. Instruct the model to produce a structured recommendation set: assessment summary, ranked recommendations, per-recommendation reasoning with citations, flagged interactions and contraindications (including those surfaced by the deterministic check), uncertainty flags, items for clinician to consider.

**Post-generation validation.** Every recommendation traces to a source. Every dose appears verbatim in a retrieved structured record. Every interaction surfaced by the deterministic check appears in the final output. No recommendation contradicts a contraindication that appeared in the retrieval. Numeric thresholds preserve. Validation failures retry with stricter prompting up to a bounded number of attempts. Retry-exhausted failures route to a distinct human-review queue (separate DynamoDB status and S3 archive prefix) and do NOT proceed to tier/suppress/render or flow to the clinician UI. The orchestrator must distinguish `VALIDATED` from `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW`; only `VALIDATED` (and `NO_EVIDENCE`, where the system explicitly declines) proceed to delivery.

**Tiering and suppression.** Score the recommendation set against clinician-engagement history for this patient in this encounter. If nothing new and material is present, suppress. If critical items are present, elevate visibility. If the same recommendation has been rejected for this patient, suppress or downgrade.

**Render.** Display with reasoning prominent, sources one click away, uncertainty explicit, options clearly framed as options (not directives). Use visual hierarchy to distinguish critical items from informational ones.

**Log.** Record the full provenance: trigger, patient context snapshot, retrieval trace, safety-check results, generation prompt version, generation output, validation result, final rendered recommendation, clinician interaction (viewed, expanded, accepted, modified, rejected with reason), patient outcome downstream if capturable. This is both the audit trail and the basis for ongoing quality and regulatory evidence.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.09-architecture). The Python example is linked from there.

## The Honest Take

I'll tell you the uncomfortable truth first: most clinical decision support deployments, including ones with substantial AI investment, struggle to prove ROI. The rigorous studies that do exist (sepsis early-warning systems, specific drug-alert tuning efforts) show real benefit in narrow scopes, and broader CDS deployments often show mixed effects on patient outcomes once alert fatigue and workflow disruption are accounted for. This is not because CDS is a bad idea. It is because doing it well is genuinely difficult, and shortcuts produce systems that harm rather than help.

The failure patterns are predictable.

**The first pattern is chasing breadth over depth.** A team builds CDS "for everything," targeting every scenario across every specialty. Six months in, every scenario is mediocre and no scenario is trusted. Clinicians encounter the tool on different patients with different kinds of responses, and the overall impression is "unreliable." Meanwhile, a narrower-scoped CDS (empiric antibiotic selection in hospitalized patients with renal dysfunction, say) that goes deep on one scenario builds trust, builds adoption, and earns the right to expand. Pick a beachhead. Earn trust there. Expand deliberately.

**The second pattern is under-investing in the retrieval layer.** The authoritative sources corpus is the single biggest determinant of output quality. A small corpus of current, relevant, institutionally-aligned sources outperforms a massive corpus of stale, irrelevant, or badly-chunked content. Curating takes time. Curating takes clinical domain expertise. Curating is not glamorous. Curate anyway.

**The third pattern is building safety checks as LLM prompts.** "We'll ask the model to check for drug interactions" is not a safety check. A real safety check is a deterministic query against an authoritative drug database, the result of which is passed to the model as a non-negotiable input. The model's role is to communicate the result, not to derive it. Teams that leave safety to the model ship systems that miss interactions the model happened not to know about, and the failure mode is silent.

**The fourth pattern is not measuring the right things.** Delivery counts, latency percentiles, validation pass rates: all important, all insufficient. The metrics that matter are clinician engagement (read, expanded, considered), clinician decisions (accepted, modified, rejected with documented reason), and patient outcomes where connectable. Teams that measure delivery and latency and declare victory miss the actual question of whether the system helps patients.

**The fifth pattern is deferring regulatory review.** "We'll figure out FDA later" becomes "we didn't realize this was a medical device" becomes a forced scope reduction eighteen months in. Get regulatory affairs involved in the design. Document the exemption case as you build. Build artifacts that support the exemption rather than against it.

**The sixth pattern is shipping without clinician buy-in.** A CDS system that lands on clinicians' screens without their input gets rejected. A CDS system that was shaped by clinician input from the start gets engagement. The product is partly the model, mostly the workflow, and fundamentally the relationship with the clinicians it serves. Engage domain experts early, let them shape what the system should and should not do, and pilot before scaling.

A few things that have worked:

**Start with scenarios where deterministic checks do most of the work.** Drug interaction, allergy, renal dosing: these are largely table lookups. The LLM's job is to present the findings clearly, not to derive them. This is the safest starting point, both clinically and regulatorily, and it earns trust before expanding into scenarios where the model does more of the reasoning.

**Let the UI foreground reasoning, not recommendations.** The clinician should see why the synthesis landed where it did before they see what it recommends. "These are the relevant guidelines and findings; here is how they combine for this patient" is a different UI than "here is what to do." The first invites judgment; the second bypasses it.

**Treat every synthesis as an artifact.** Log it. Version it. Make it retrievable and auditable. A clinician who asks "why did the system recommend X yesterday?" should get an answer with full provenance, including the sources, the prompt, and the model version. This has compliance and trust benefits, and it has one more: it forces you to build a pipeline that is auditable, which is harder than building one that is just functional.

**Invest in clinician feedback loops that actually do something.** Capture not just thumbs-up and thumbs-down but free-text rejection reasons. Review them weekly with a clinical reviewer. Categorize the failure modes (retrieval miss, synthesis error, irrelevance to workflow, wrong tier). Feed the categories into a prioritized improvement backlog. Without this, feedback accumulates and the system plateaus.

**Design for the 2 AM failure mode.** Your system will fail at 2 AM, during an emergency, with a patient in front of a clinician. How does it fail safely? A clear timeout with a clear "synthesis unavailable" message is better than a degraded synthesis that looks complete but is missing critical safety findings. Design the failure modes as deliberately as you design the success modes.

**Don't pretend the system replaces judgment.** The entire value proposition is "helps the clinician think about this faster and more thoroughly." It is not "decides for the clinician." The framing throughout the product, the documentation, the training, and the outputs needs to be consistent on this. The moment the framing slips toward "the system knows best," you've lost the regulatory exemption, you've lost clinician trust, and you've built something that will eventually hurt a patient.

Final thought. Clinical decision support synthesis is one of the genuinely high-impact applications of modern AI in healthcare. The clinicians who use it well describe it as "like having a really thorough pharmacist in the room with me" or "a chief resident who happens to know the guidelines cold." That framing is exactly right: a colleague who helps you think, not a replacement for your thinking. Build toward that. Everything else flows from it.

---

## Related Recipes

- **[Recipe 2.4: Prior Authorization Letter Generation](chapter02.04-prior-auth-letter-generation):** Similar grounded-generation pattern applied to payer-facing output. The authoritative-source retrieval and patient-context integration in 2.9 share infrastructure with the evidence-retrieval pieces of 2.4.
- **[Recipe 2.5: After-Visit Summary Generation](chapter02.05-after-visit-summary-generation):** Patient-facing synthesis of a single encounter. Shares the grounding, citation, and validation patterns.
- **[Recipe 2.6: Clinical Note Summarization](chapter02.06-clinical-note-summarization):** Clinician-facing synthesis of encounter content. Same pipeline skeleton.
- **[Recipe 2.7: Literature Search and Evidence Synthesis](chapter02.07-literature-search-evidence-synthesis):** Descriptive sibling of this recipe. 2.7 describes evidence; 2.9 synthesizes patient-specific recommendations. The retrieval infrastructure overlaps substantially; the regulatory posture and the generation prompt differ.
- **[Recipe 2.8: Ambient Clinical Documentation](chapter02.08-ambient-clinical-documentation):** Produces the patient context that a CDS system can then reason over. Ambient documentation and CDS are complementary; both live inside the encounter workflow.
- **[Recipe 2.10: Multi-Modal Clinical Reasoning](chapter02.10-multi-modal-clinical-reasoning):** Extends CDS into multi-modal inputs (imaging findings, ECG, pathology). The CDS synthesis pipeline here is the reasoning layer that a multi-modal system feeds into.
- **Recipe 5.x (Entity Resolution / Record Linkage):** Accurate patient record linkage is a prerequisite for pulling a complete patient context. If patient records are split across systems, the CDS synthesis is working with an incomplete picture. <!-- TODO (TechWriter): update to specific recipe number once Chapter 5 is drafted. -->
- **Recipe 13.x (Knowledge Graphs / Ontology):** Knowledge-graph representations of drug-drug relationships, disease-drug contraindications, and guideline-recommendation-condition links can augment the retrieval layer. Hybrid graph-plus-vector retrieval is a promising direction for CDS. <!-- TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted. -->
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** Risk scores (sepsis early-warning, readmission risk, fall risk) can be inputs to a CDS synthesis. "This patient's sepsis risk score is elevated; consider the following empiric workup." The score triggers the synthesis and becomes part of the context. <!-- TODO (TechWriter): update to specific recipe number once Chapter 7 is drafted. -->

---

## Tags

`llm` · `generative-ai` · `bedrock` · `knowledge-bases` · `guardrails` · `opensearch` · `aurora-pgvector` · `healthlake` · `comprehend-medical` · `rag` · `clinical-decision-support` · `cds` · `fhir` · `smart-on-fhir` · `cds-hooks` · `drug-interactions` · `guidelines` · `grounded-generation` · `citation-verification` · `fda-cds` · `alert-fatigue` · `evidence-synthesis` · `complex` · `hipaa` · `regulatory` · `provenance`

---

*← [Recipe 2.8: Ambient Clinical Documentation](chapter02.08-ambient-clinical-documentation) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.10 - Multi-Modal Clinical Reasoning →](chapter02.10-multi-modal-clinical-reasoning)*
