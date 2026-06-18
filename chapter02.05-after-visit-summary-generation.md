# Recipe 2.5: After-Visit Summary Generation

**Complexity:** Medium · **Phase:** MVP → Production · **Estimated Cost:** ~$0.03-0.10 per summary

---

## The Problem

<!-- TODO (EXPERT REVIEW - CRITICAL, Finding S2): The anticoagulation vignette below
     is written for warfarin (greens interact, INR draw at 3 days) but the Sample Output
     in "Expected Results" shows apixaban 5 mg with a CBC/kidney check at 3 days.
     These clinical pictures are incompatible. Pick one drug and use it consistently
     across the Problem narrative and the Sample Output. The reviewer recommends
     keeping warfarin here (the specific details are strong teaching) and switching
     the Sample Output to match. See reviews/chapter02.05-expert-review.md Finding S2. -->

A 68-year-old patient with new-onset atrial fibrillation walks out of the cardiology office with a folded piece of paper. On it: the boilerplate "After-Visit Summary" the EHR auto-generated. The top half is the patient's demographic banner and the practice's phone number. The bottom half is a list of their active medications (unchanged since 2019), a generic statement that says "Continue current medications as prescribed," and a single line that reads "Follow up as needed."

What actually happened in that visit: the cardiologist started anticoagulation. She explained that the patient has a 1-in-20 risk of stroke per year without it, that the medication requires careful attention to diet (greens interact), that they need a lab draw in three days to check clotting, that they should call 911 immediately if they notice unusual bleeding or a sudden headache, and that they need to return in two weeks. None of that is on the paper.

Research on health literacy is consistent and depressing. Patients forget 40-80% of what their provider tells them within minutes of leaving the visit, and of what they do remember, roughly half is remembered incorrectly. <!-- TODO: verify specific percentages against current health literacy literature (Kessels 2003 is commonly cited but somewhat dated) --> The average American adult reads at roughly an 8th-grade level. <!-- TODO (EXPERT REVIEW - LOW, Finding V3): The "8th-grade level" shorthand traces back to NAAL 2003. Consider softening to AHRQ/CDC guidance targeting 6th-to-8th-grade for patient materials, without the "average" framing. --> The average after-visit summary is written at a 10th-to-12th-grade level. That mismatch alone (before you get to any of the clinical nuance) means a large fraction of patients can't fully decode the document they're handed.

For the patient with atrial fibrillation, the consequences of that gap are concrete. They don't go for the INR draw because the paper didn't mention it. They continue their usual salad-heavy diet because nobody wrote down the dietary interaction. They show up to the follow-up appointment confused about why they're on a new medication, or they no-show because "follow up as needed" felt optional. Six weeks later they're in the ER with a bleed that could have been caught earlier, or a clot that could have been prevented. Their chart documents everything the physician did correctly. The communication layer is where it fell apart.

Hospital discharge summaries are an even sharper version of the same problem. A patient discharged after a three-day hospitalization for heart failure leaves with five new medications, a new diagnosis, a restricted diet, a home scale and weight log instructions, and follow-up appointments with three different specialists. They're also on narcotics from the hospital stay, exhausted, and often half-listening to the discharge nurse who is running through a checklist. Readmission rates for heart failure hover around 20-25% within 30 days <!-- TODO: verify current CMS readmission statistics -->, and a meaningful chunk of those readmissions trace back to communication failures: didn't know the warning signs, didn't understand the medication, didn't realize the follow-up appointment was important.

The frustrating thing is that the source material exists. The physician wrote a detailed note. The medication changes are in the EHR. The orders and referrals are captured. The follow-up plan was discussed. Every piece of information the patient needs is somewhere in the chart. The problem is that nobody has time to synthesize it into something the patient can actually read and act on.

Historically, this was solved (poorly) in two ways. Either the clinician dictated a personalized summary, which added 10-15 minutes per visit and was unsustainable at volume, or the EHR produced a template-filled document, which was technically compliant but practically useless. Neither approach scales to the 1 billion outpatient visits per year that happen in the United States.

This is the kind of problem that LLMs are uncommonly good at. You have structured and semi-structured source documentation. You have a target audience with specific literacy needs. You have a required output structure (what was discussed, what changed, what to do, when to call). And you have a clear safety boundary: the summary must accurately reflect the source and must not invent instructions. If you get the architecture right, you can produce AVSs that are both personalized and grounded, at a cost of pennies per visit, in seconds.

---

## The Technology: Grounded Generation for Patient-Facing Prose

### What Makes After-Visit Summaries Different

Patient message drafting (Recipe 2.1) and terminology simplification (Recipe 2.2) are useful mental contrasts. Patient messages are short, one-topic, and conversational. Terminology simplification is a straight transformation: clinical text in, plain-language version out.

An after-visit summary sits in the harder middle ground. It's multi-topic (diagnoses, medications, tests, follow-up, education, warning signs), it's safety-critical (wrong medication instructions can hurt people), and it's patient-facing (no clinician sits between the output and the reader to filter errors). It's also highly structured: a good AVS follows a consistent template so patients learn where to look for specific information.

The key technical constraint: every sentence in the output must trace back to something the clinician actually documented. No invented diagnoses. No invented medications. No invented dosages. No invented follow-up dates. If the physician didn't say it, the summary can't say it. This is grounding territory, which means retrieval-augmented generation even though the "retrieval" here is scoped to a single encounter.

### The Health Literacy Problem Is a Design Constraint

Reading level isn't a nice-to-have. It's a design constraint that shapes the entire system. The CDC recommends writing patient materials at a 6th-to-8th-grade reading level. Joint Commission standards for hospitals expect similar targets. The Plain Writing Act of 2010 imposed plain-language requirements on federal health communications. AHRQ's Universal Precautions Toolkit assumes low health literacy as the default and optimizes for it.

What that means in practice:

- **Short sentences.** Usually under 15 words. One idea per sentence.
- **Common words.** "Heart specialist" instead of "cardiologist" on first mention. "High blood pressure" instead of "hypertension" (or "hypertension (high blood pressure)" as a translation pattern).
- **Active voice.** "Take this medicine" beats "This medicine should be taken."
- **Concrete instructions.** "Take one pill every morning with food" beats "Adhere to daily dosing regimen."
- **Chunked structure.** Bullets, sections, and whitespace so the eye can find its place.
- **No numbers that don't need to be there.** "About 1 in 20 people" beats "5.2% of patients."

Modern LLMs can hit these targets reliably when instructed to, and the reading level can be verified automatically using standard readability formulas (Flesch-Kincaid Grade Level, SMOG, Dale-Chall). A generated summary that scores above 8th grade can be flagged for regeneration or routed for human editing.

### Personalization That Actually Matters

"Personalization" in patient-facing content means something specific and narrow. It does not mean using the patient's name in three places. It means:

- **Language.** English, Spanish, Mandarin, Vietnamese, and whatever else the practice's patient population speaks. The summary is generated in the patient's preferred language, not translated as an afterthought.
- **Reading level.** If the patient's registration indicates limited English proficiency, target a lower reading level. If the patient is a healthcare worker themselves, allow slightly more technical language.
- **Specific context.** A diabetic who was just started on insulin needs instructions about hypoglycemia. That's not true for most patients. The summary includes the hypoglycemia warning only when the medication change warrants it.
- **Delivery channel.** A patient who uses the portal sees a formatted web page. A patient who wants a printout gets a PDF optimized for an 8.5x11 sheet. A patient who prefers SMS gets the essentials broken into a short sequence of messages.
- **Comprehension aids.** Low-literacy patients benefit from iconography and illustrations. Older patients benefit from larger type. These aren't content changes; they're rendering decisions driven by the patient profile.

The content personalization decisions are architectural. They drive what data the system needs (patient preferences, demographics, the specific clinical changes from the visit) and how it structures the generation (one prompt per section? one prompt for the whole document? per-language generation or generate-then-translate?).

### Why LLMs Are Well-Suited (Despite the Risks)

**They handle the structure-plus-flexibility balance naturally.** A rigid template produces output that reads as form-filled. A completely free-form generation produces output that's inconsistent across visits and hard for patients to navigate. LLMs sit comfortably in the middle: follow the template, but vary the language based on what actually happened in the encounter.

**They understand clinical nuance.** The physician's note might say "patient counseled on red flag symptoms for MI." An LLM can translate that into concrete patient-facing warning signs (chest pain, pain radiating to arm or jaw, shortness of breath, sweating, nausea, call 911 immediately) without the physician having to write each one out.

**They can hit specified reading levels.** With a prompt that specifies "write at 6th-grade reading level," modern models reliably produce text that scores in that range on Flesch-Kincaid. Verification with an automated readability check closes the loop.

**They can generate in the patient's language.** For the top 5-10 languages by patient population, generating directly in the target language typically produces better prose than English-then-translate. The model is writing for a Spanish-speaking patient, not translating a template written for an English-speaking patient.

**They can prioritize.** Given 15 possible items to include (every finding, every education topic discussed), they can identify the 5-7 that actually matter for this patient's next two weeks and foreground those. Human writers are often too afraid to prioritize because "what if they needed to know about X?" LLMs, properly instructed, are willing to leave out the minor findings and focus on the decisions and actions.

### The Failure Modes You Have to Design Around

**Fabricated instructions.** The model invents a follow-up date, a medication dose, a test result, or a warning sign that wasn't in the source. This is the existential risk. A generated summary that tells the patient to take "20 mg" when the physician prescribed "10 mg" is a medication error waiting to happen. Mitigation: extract structured facts first, never let the model infer dosages or dates, validate every specific claim against the source.

**Omission of critical items.** The model, trying to be concise, drops a warning sign or a follow-up requirement that matters. This is arguably the harder failure mode because it's silent. Mitigation: explicit "must-include" checks for high-risk categories (medication changes, follow-up appointments, warning symptoms, emergency instructions). The model isn't trusted to decide what's important; the architecture enforces inclusion.

**Tone errors.** The model lands on a tone that's condescending ("Don't worry, your doctor will take good care of you") or anxiety-inducing ("This condition can be fatal if untreated"). Neither tone is what the clinician would have chosen. Mitigation: prompt engineering that specifies a calm, direct, respectful tone, with examples of good and bad phrasing.

**Cultural insensitivity.** Health content that works for a white middle-class urban patient can miss for other populations. Food examples that assume a specific cuisine. Assumptions about family structure. References to health systems or practices that don't apply. Mitigation: tone guides per patient population, review by community health workers during system development, and caution about baking "universal" phrasing into prompts.

**Translation quality.** Direct generation in a non-English language requires a model that's actually strong in that language, not just multilingual on paper. The variance across languages is substantial. Medical translation in particular has its own challenges (false cognates, region-specific medical terminology, register choices). Mitigation: quality check translations against a small human-reviewed set per language, especially for safety-critical content.

**Ambiguous follow-up.** The source note says "follow up soon." The model has to produce an actionable instruction. Is "soon" one week? Two weeks? Six weeks? The wrong interpretation either over-schedules the patient or creates a care gap. Mitigation: require structured follow-up data from the ordering step (not the note), and flag ambiguous language for clinician clarification.

**Hallucinated urgency.** The model, trained on lots of WebMD content, sometimes escalates tone beyond what the clinical situation warrants. A mild finding gets "call your doctor immediately" treatment. Mitigation: the summary's urgency language should be tied to structured severity signals from the encounter, not inferred by the model.

### Grounded Generation, Encounter-Scoped Edition

The architectural pattern that makes this viable is the same grounded-generation approach used for prior auth letters (Recipe 2.4), but scoped to a single clinical encounter. The flow:

1. Pull the encounter's structured data: the visit note, medication changes, orders placed, referrals made, follow-up plan. Everything the physician produced or recorded during the visit.
2. Extract a structured "visit summary object" with discrete fields for each category of content. This is where you turn unstructured note text into structured facts.
3. Generate the summary from the structured object, section by section, with prompts that use only the provided facts.
4. Validate: every specific claim (dose, date, test name) must trace to a field in the structured object.
5. Render in the patient's preferred language, format, and reading level.
6. Optional clinician review (the higher the risk tier, the more review warranted).
7. Deliver through the patient's preferred channel.

The model is a writer, not a decision maker. Everything it says has to come from somewhere upstream in the pipeline. That constraint, enforced architecturally, is what makes the system safe enough to scale.

---

## The General Architecture Pattern

At the conceptual level, the pipeline looks like this:

```text
[Visit Ends / Note Signed]
    → [Pull Encounter Data]
    → [Extract Structured Summary Object]
    → [Apply Patient Context (language, literacy, prefs)]
    → [Generate Draft by Section]
    → [Validate Against Source]
    → [Apply Readability Check]
    → [Optional Clinician Review]
    → [Render for Delivery Channel]
    → [Deliver to Patient]
    → [Log for Audit]
```

Let's walk through each stage conceptually.

**Visit ends / note signed.** The trigger. The AVS generation shouldn't run while the clinician is still editing the note; it should fire when the note is finalized. Triggering on note signature guarantees that the source of truth is stable. For discharge summaries, the trigger is different: discharge order placed plus discharge summary completed.

**Pull encounter data.** Retrieve everything relevant from the EHR for this specific visit: the signed note, the list of medication changes (added, discontinued, dose-adjusted), orders placed (labs, imaging, procedures), referrals created, follow-up appointments scheduled, and any patient education materials selected during the visit. In FHIR terms: Encounter, DocumentReference, MedicationStatement, MedicationRequest, ServiceRequest, Appointment, Condition. The scope is intentionally narrow; you don't need the patient's full chart, only what happened today.

**Extract structured summary object.** Turn the encounter data into a fielded object that will drive generation. Discrete fields for each category:

- Diagnoses discussed (with "new today" flag)
- Medications (new, changed, stopped, continued as-was)
- Tests ordered (with instructions and when results expected)
- Procedures or treatments performed
- Referrals (specialty, reason, how to schedule)
- Follow-up plan (when, with whom, what for)
- Warning signs / when to call / when to go to ER
- Education topics discussed

This extraction is where the hardest work happens. Some of these fields come from structured EHR data directly (a new med order has a clear name, dose, frequency). Some have to be pulled from note text (the warning signs discussed, the education topics). The extraction step uses a mix of structured data reads and LLM-based extraction from the note.

**Apply patient context.** Overlay the patient's preferences onto the generation parameters. Preferred language, reading-level target, delivery channel, any special needs (visual impairment, hearing impairment, low health literacy flag). These parameters don't change what's in the summary; they change how it's written.

**Generate draft by section.** Run the LLM with a prompt that takes the structured object and produces the summary. Depending on your architecture, this is either one call that produces the whole document or several calls that produce sections that get assembled. Each approach has trade-offs: single-call is simpler and cheaper but harder to control; per-section is more complex but lets you enforce structure and handle failures at a finer grain.

**Validate against source.** Parse the generated text. Identify every specific claim (medication name, dose, date, test name, follow-up time). Check each claim against the structured object. Flag any claim that doesn't trace back. A validation failure triggers regeneration (or an escalation to human review).

**Apply readability check.** Score the generated summary for reading level using one of the standard formulas. If it exceeds the target (e.g., output is at grade 10 but target is grade 6), regenerate with a stronger simplification instruction. This is a feedback loop, not a one-shot check.

**Optional clinician review.** For low-risk visits (routine check-up, med refill), the summary can go directly to the patient. For higher-risk visits (new cancer diagnosis, significant med changes, hospital discharge), a clinician reviews and approves. The risk tiering is a policy decision that should be made deliberately, not by default.

**Render for delivery channel.** Same content, multiple output formats. Portal HTML, PDF for printing, structured SMS for text-only delivery, printed handout for patients without portal access. Rendering is a separate layer; the generation shouldn't produce HTML directly.

**Deliver to patient.** Push to the portal, send via secure email, print and hand to the patient, send via SMS. Track delivery confirmation where possible.

**Log for audit.** Every summary generated, every version, every clinician edit, every delivery. HIPAA audit requirements apply (this is PHI). Patients sometimes call later and ask "what did my doctor tell me to do?" and the AVS is the answer; you need to be able to retrieve the exact document they received.

One note on the pipeline: the structured extraction step is doing a lot of work. If the encounter is well-documented with structured orders and clear note text, extraction is straightforward. If the clinician dictated a messy free-text note with no structured orders, extraction becomes the bottleneck. This is a case where better upstream documentation hygiene pays off downstream for everyone, patient included.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.05-architecture). The Python example is linked from there.

## The Honest Take

After-visit summaries are one of the highest-leverage applications of healthcare LLMs that I've seen in practice. The source data exists. The template is stable. The task is well-bounded. The grounding constraint (say only what the note says) is architecturally enforceable. And the patient impact is real and measurable: adherence goes up, confusion goes down, readmissions drop, portal engagement rises. If you're picking a second or third healthcare LLM project after the obligatory message-drafting pilot, this is a strong candidate.

That said, I've watched this use case fail in a specific pattern, and it's worth naming. Teams ship a prototype that generates beautiful summaries on cherry-picked test cases. The leadership demo is a hit. The pilot goes well for the first two weeks. And then, quietly, the system starts producing summaries that are subtly wrong: a stopped medication still listed as active, a follow-up date that doesn't match what the physician said, a warning sign that wasn't actually discussed. The errors are small. No individual error causes a bad outcome. But cumulatively, clinician trust erodes, patients start noticing inconsistencies, and the project ends up paused while someone figures out how to instrument validation.

The lesson: build the validation step before you deploy the generation step. Not after. Not in parallel. Before. Every specific claim the model produces should have a traceable source. Every claim that doesn't trace back should trigger a known remediation (regenerate, escalate, or drop). If you ship generation without validation, you're deploying a system you can't defend when something goes wrong, and in healthcare something always eventually goes wrong.

The second lesson: don't over-automate clinician review in the name of efficiency. The time savings of AI-generated summaries come from the content production, not from eliminating review entirely. For routine visits, lightweight review (scan for obvious errors, approve) is appropriate. For high-risk visits, substantive review is essential. Clinicians will tolerate quick review much more than they'll tolerate discovering six months in that they've been co-signing summaries that contained errors. Surface the AI-generated provenance prominently in the review UI; let the clinician see at a glance what's grounded versus what's generated prose.

Third: plain language is not a prompt-engineering afterthought. It's the entire point. An AVS at grade 11 is not a useful AVS, no matter how clinically accurate it is. Invest in the readability loop. Validate with automated tools. Sample outputs and read them aloud. Have non-clinical staff read sample summaries and report what they didn't understand. This is the work.

Fourth: multilingual generation is powerful when it works and embarrassing when it doesn't. Direct generation in strong languages is often better than English-then-translate. But "strong" is language-specific. Verify by having native speakers (ideally patients) review samples. Don't assume. The failure mode here isn't that the translation is wrong; it's that it's technically correct but culturally awkward, and the patient's trust in the communication erodes without them being able to articulate why.

Finally: measure outcomes, not just outputs. Internal metrics like "summaries generated" and "average reading level" feel good but miss the point. Track portal open rates for AVSs. Track medication adherence at two-week follow-up. Track no-show rates for scheduled follow-ups. Track readmission rates (for discharge summaries). Track patient satisfaction scores for the understanding-of-plan questions. The measurement is slow and unglamorous but it's the only way to know whether the system is actually doing what you built it to do.

There's a bigger opportunity hiding in this use case, too. The AVS is the visible output, but the structured extraction step produces something valuable on its own: a clean, fielded record of what happened at the visit. That structured record can feed downstream systems (population health dashboards, care gap closure workflows, quality measure reporting) that today rely on brittle parsing of note text. Building the AVS pipeline well gives you that asset for free. Some teams realize this late. If you start with it in mind, you can design the extraction step to serve both masters.

---

## Related Recipes

- **Recipe 2.1 (Patient Message Response Drafting):** Uses similar LLM patterns but for one-off messages rather than structured document generation. The tone and reading-level considerations transfer directly.
- **Recipe 2.2 (Medical Terminology Simplification):** The transformation pattern here is a component of the AVS pipeline. A standalone simplification service can be reused inside the AVS generation step.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Same grounded-generation architecture, different audience. The structural patterns (structured extraction, prompt grounding, claim validation) are nearly identical. If you've built the PA pipeline, the AVS pipeline is largely a rebuild with a different target audience.
- **Recipe 2.6 (Clinical Note Summarization):** Summarization for clinicians rather than patients. The architectural patterns overlap but the audience-specific prompting differs substantially.
- **Recipe 2.8 (Ambient Clinical Documentation):** When ambient documentation is generating the clinical note, the note structure is often cleaner and more recent, which improves downstream AVS generation quality.
- **Recipe 11.x (Conversational AI):** A conversational follow-up agent (teach-back, reminder confirmation, question-answering) pairs well with the AVS. The AVS delivers content; the conversational layer helps the patient engage with it. <!-- TODO: verify recipe number once Chapter 11 is drafted -->

---

## Tags

`llm` · `generative-ai` · `bedrock` · `healthlake` · `comprehend-medical` · `after-visit-summary` · `patient-facing` · `grounded-generation` · `health-literacy` · `plain-language` · `multilingual` · `readability` · `guardrails` · `medium-complexity` · `hipaa` · `fhir` · `smart-on-fhir`

---

*← [Recipe 2.4: Prior Authorization Letter Generation](chapter02.04-prior-auth-letter-generation) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.6 - Clinical Note Summarization →](chapter02.06-clinical-note-summarization)*
