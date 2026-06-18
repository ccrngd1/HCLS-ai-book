# Recipe 11.3: Prescription Refill Request Bot

**Complexity:** Simple-Medium · **Phase:** Quick-win to Foundational · **Estimated Cost:** ~$0.03-0.15 per completed refill conversation (depends on conversation length, model choice, identity-verification path, and pharmacy integration overhead)

---

## The Problem

Eleanor is 71. She takes seven prescription medications: lisinopril for blood pressure, metformin for type 2 diabetes, atorvastatin for cholesterol, levothyroxine for her thyroid, gabapentin for neuropathic pain, sertraline for depression, and a low-dose aspirin her cardiologist recommended after a coronary calcium scan. She has been taking most of them for years. Her primary care physician sees her every three months, her endocrinologist twice a year, and the rest of her care is the slow background labor of staying on top of seven prescriptions, three pharmacies (because her insurance moved one of them to mail-order in January), and the eternal question of whether the white oval pill or the white round pill is the one she takes in the morning.

It is the third Tuesday of the month. Eleanor has run out of metformin. She knows this because her pill organizer's Tuesday slot is empty, and the bottle she keeps in the kitchen cabinet has been empty for two days. She thought she had refills left. She does not. She tried to refill it through her pharmacy's app last week and the app said "no refills authorized, contact prescriber." She called the pharmacy. The pharmacy said the same thing and recommended she call the doctor's office. She called the doctor's office. The voicemail tree gave her the option to leave a refill request in the prescription line, which she did, on Friday at 4:42 PM. It is now Tuesday at 9:17 AM. Nobody has called her back. The voicemail tree said the typical turnaround is two business days, and three business days have passed, and her blood sugar at breakfast was 247 mg/dL because she has been off her metformin since Sunday.

She calls the doctor's office again. The phone tree puts her in the general queue because the prescription line goes straight to voicemail. She waits seventeen minutes. The receptionist who picks up is friendly but is also not the person who can authorize the refill; the receptionist puts in a fresh refill request, apologizes for the delay, and says the nurse will call her back. The nurse calls her back at 2:30 PM, asks her to confirm her name and date of birth, asks which medication, looks up her chart, sees that she is overdue for an A1c lab draw, and tells her that the doctor wants to see lab results before authorizing the next ninety-day fill. Eleanor explains that her A1c was drawn three weeks ago at a different lab. The nurse does not see the result in the chart. Eleanor asks if she can fax it. The nurse says yes, gives her the fax number, and says she will check tomorrow. Eleanor's husband faxes the lab result that evening. The nurse does not see the fax the next day. By Thursday, Eleanor has been off metformin for five days and her fasting glucose is 268. She calls again, this time with her daughter on three-way, and after another forty-five minutes of voicemail-and-callback the medication is finally e-prescribed to the pharmacy. Her daughter picks it up that evening.

The whole event consumed roughly three and a half hours of Eleanor's life, ninety minutes of her daughter's, twenty minutes of receptionist time, fifteen minutes of nurse time, and six minutes of the physician's time, distributed across multiple separate phone calls and chart-review interruptions. The clinical risk during the five days Eleanor was off her medication is a thing that does not show up in any of the operational metrics anyone tracks. The patient experience is, charitably, awful. The economics, when you multiply this story by the actual volume of refill requests a typical primary care practice processes, are catastrophic.

This is prescription refill management in healthcare, and it is the most common, most tedious, most error-prone, and most under-engineered patient-facing workflow in the entire ambulatory system. A primary care practice typically processes refill requests at a rate that overwhelms the schedulers, nurses, and physicians who handle them. Industry surveys regularly cite refill management as one of the top sources of clinician burden, with each physician handling dozens of requests per day on top of clinical work. 

The frustrating part, as with scheduling, is that most refill requests are conceptually simple. Patient takes medication X. Patient is running low. Patient asks for a refill. Prescription is current, prescriber is the same, dose is the same, no clinical issue has emerged, no monitoring is overdue. The refill is approved. The pharmacy fills it. The patient picks it up. The physician's involvement is near zero. The receptionist's, nurse's, and prescriber's time spent on this kind of routine refill is almost pure overhead. It exists because the previous-generation systems were too rigid to handle the routing automatically and not transparent enough to let the patient self-serve safely.

Some refills are not simple. The patient is asking for a controlled substance and the prescriber needs to review. The medication requires periodic monitoring (an A1c for metformin escalation, a creatinine for renally-cleared drugs, a lipid panel for statin titration) and the labs are overdue. The patient is asking for early refill of a medication that they should not be running out of yet, which suggests possible misuse or a dosing problem. The medication has been changed by another prescriber and the chart is out of date. The patient is asking for a medication that was discontinued. The patient is asking for a refill on a medication they take from a specialist who does not respond to refill requests through the primary care office. Each of these warrants different handling. The competent clinic staff knows how to triage these mentally, but the triage takes time, and the time is the bottleneck.

The previous generation of patient-facing refill tools, when they existed at all, were forms inside the patient portal: pick a medication from a dropdown, submit, wait for the practice to respond. The forms had the same failure modes as the previous-generation scheduling forms: the dropdown was either incomplete (medications the patient takes that were prescribed by other providers do not show up) or overwhelming (every medication the patient has ever been on, including discontinued ones), the submission did not actually trigger any meaningful workflow change, and the patient still ended up calling because the form-and-wait flow did not feel responsive. A frustrated patient on a critical medication does not trust that a web form has actually done anything until somebody confirms.

The modern conversational refill bot looks like this. Eleanor opens the patient portal at 9:17 AM and the chat widget says "I see you have a metformin refill request pending. Want me to check on it?" Eleanor types "yes please." The bot confirms her identity from the authenticated portal session, looks at her chart, sees the pending request, sees the lab order that is blocking the refill, sees the lab result that came in at the outside lab three weeks ago and was reconciled into her chart yesterday, runs the practice's refill protocol against the chart context, and replies "Good news, your most recent A1c is 7.1, which is in range for your metformin maintenance. I'm sending the refill to Walgreens on Main Street. You should see it ready for pickup later today; the pharmacy will text you when it's done. Anything else?" Eleanor says "thank you." The bot logs the interaction, the refill, the protocol consultation, and the lab reconciliation; the prescriber co-signs at the next chart-review pass; the encounter is documented; the loop is closed.

That ninety-second conversation replaces three and a half hours of Eleanor's time, ninety minutes of her daughter's, and the cumulative two hours of receptionist, nurse, and physician time. It is also clinically safer because the protocol consultation is consistent and auditable, the lab reconciliation is automatic, and the failure modes are visible in dashboards. This recipe is the bot that closes the loop on routine refills, escalates the non-routine ones cleanly, and (this is the part nobody talks about) makes the clinic's refill protocol explicit enough that the bot can apply it deterministically.

A few things this recipe is and is not.

It is the bot that handles routine maintenance refill requests: the patient takes a chronic medication, has refills that have been used up or have a recent prescription that needs continuation, has the necessary monitoring up to date, and is not asking for early refill. It also handles routine first-pass triage of non-routine requests so that what reaches the clinical staff is the genuinely-needs-clinical-review subset.

It is not the prescriber. The bot does not write new prescriptions. The bot does not titrate doses. The bot does not start new medications. The bot does not change therapy. The bot's authority is limited to the scope the practice's medical leadership has explicitly delegated, which in most deployments is "renew an existing medication on its existing dose if it meets the practice's protocol-approved criteria, otherwise route to clinical staff."

It is not the pharmacy. The bot's job is to package the refill request, route it through the prescriber's e-prescribing workflow, and surface the resulting state to the patient. The pharmacy fills the prescription. The bot can communicate pharmacy-side status updates to the patient when the integration supports it, but the bot is not the pharmacy's system.

It is not a controlled-substance bot. Controlled substances (Schedule II through V) carry layered regulatory and clinical requirements that this recipe explicitly does not cover for self-service. The bot can identify a controlled-substance request, route it to the appropriate clinical workflow with a transparent explanation to the patient, and never auto-approve. The clinical staff handles it.

It is not the medication-reconciliation bot. The bot can surface medication-reconciliation prompts ("we have you on lisinopril; is that still correct?") but the clinical work of reconciling the medication list against what the patient actually takes is owned by the clinical workflow.

The thing to understand before building this is that the bot's quality is bounded above by the practice's refill protocol's explicitness. A bot operating against a vaguely-documented protocol books wrong refills for half-vague reasons. A bot operating against a precisely-documented protocol takes routine work off the clinical team's plate while routing the genuinely complex cases to humans with clear reasoning attached. The pre-deployment work of writing the protocol is the single highest-leverage investment, and it is rarely scoped into the project plan because nobody owns the protocol formally.

Let's get into it.

---

## The Technology: Tool-Using Conversational AI Plus the Refill Protocol Reality

### Why Refill Workflows Have Stayed Stuck

For most of the last two decades, refill workflows in ambulatory care have been a relay race between four parties (patient, pharmacy, practice clinical staff, prescriber) with the baton being passed through fax, voicemail, and the EHR's inbox. The patient asks the pharmacy, the pharmacy faxes the practice, the practice's nurse triages the fax, the prescriber approves or denies, the prescriber's response goes back to the pharmacy, the pharmacy fills the prescription, the patient picks it up. Each handoff has variable latency. The whole loop frequently takes two to five business days, and during that time the patient may be off their medication.

The first generation of digital refill tools, roughly 2010 to 2020, replaced fax with electronic prescribing (e-prescribing) and added a patient-portal form for the patient to request refills directly. This was a meaningful improvement over fax. It did not fundamentally change the workflow shape: the patient submits a request, the request lands in the practice's queue, the nurse triages it, the prescriber acts on it, the result e-prescribes to the pharmacy. The latency improved from days to hours; the work for clinical staff stayed the same; the patient experience improved a little but still depended on the practice's queue depth.

The button-tree chatbot approach to refills, when it appeared, did not work. The reason is the same as the FAQ and scheduling cases: a button-tree chatbot is a form behind a chat veneer. The patient still picks the medication from a list, still submits, still waits. The chat surface is a slightly nicer UX than the form, but the workflow shape is identical and the latency is identical.

The thing that changed the workflow shape is the combination of three things. First, structured medication data became broadly available through FHIR APIs that expose the patient's MedicationRequest resources directly. Second, tool-using LLMs (the same architectural pattern from recipe 11.2) made it possible to build a bot that could understand "my blood pressure pill" as well as "lisinopril 10 milligrams" and call the right tools to act on either. Third, the recognition that most refills are protocol-driven means most refills can be handled by a bot operating against an explicit protocol, with clinical staff handling the exceptions.

The architectural shift is from "queue everything for human triage" to "auto-approve what the protocol says is auto-approvable, route everything else to humans with reasoning attached." The bot's value is concentrated in two places: the natural-language understanding of the patient's request (so the patient does not have to know whether to type "metformin 500" or "the diabetes pill"), and the protocol-driven first-pass triage that handles the routine majority of cases without human work.

### What Tool-Using LLMs Do for Refill Bots

The chapter preface and recipe 11.2 introduced the tool-use pattern. For a refill bot, the pattern decomposes into a set of specific tools, each with a well-defined input schema and output schema. The LLM handles conversation; the tools handle action.

**Patient identification.** Same primitive as recipe 11.2. The bot needs to know which patient it is talking to before it can do anything that touches the patient's record. Authenticated portal sessions short-circuit; unauthenticated channels need the standard graduated identity verification.

**Medication lookup.** Given a free-text medication descriptor from the patient ("my metformin," "the blood pressure pill," "the white round one I take in the morning") and the patient's current medication list, return the structured medication record (name, dose, route, frequency, last-fill date, refills-remaining, prescribing provider, dispensing pharmacy). This is the medication-resolution problem the chapter preface flagged: it is harder than it sounds because patient phrasing of medications is wildly varied. Modern LLMs handle this well when the patient's medication list is in the prompt as context, less well when it is not.

**Refill eligibility check.** Given a structured medication record and the patient's chart context, evaluate the practice's refill protocol against the request. The protocol is the institutional artifact that maps (medication class, monitoring requirements, time-since-last-fill, refills-remaining, prescriber, patient context) to one of: auto-approve, route-to-prescriber-with-context, route-with-monitoring-due, route-with-clinical-question, deny-with-reason. The eligibility check tool encapsulates the protocol as code; the LLM does not evaluate the protocol itself.

**Pharmacy lookup and selection.** The patient may have multiple pharmacies on file, may have moved a prescription to mail-order, may have changed pharmacies recently. The pharmacy-lookup tool returns the patient's pharmacies with the medication's preferred dispensing location indicated.

**E-prescribe submission.** When the protocol approves the refill, the e-prescribe tool transmits the prescription to the pharmacy through the practice's e-prescribing platform (typically Surescripts in the U.S.). This is the tool that takes the action that creates the actual refill.

**Clinical routing.** When the protocol routes the refill to clinical staff, the routing tool packages the request with the bot's reasoning (which protocol rules fired, what data the bot looked up, what the patient said) and queues it in the appropriate inbox. The clinical staff sees a structured ticket, not just a chat transcript.

**Status check.** After a refill request has been submitted, the patient often wants to check on it. The status-check tool queries the e-prescribing platform and the pharmacy integration to surface the current state (sent to pharmacy, in queue at pharmacy, ready for pickup, picked up, on hold for clarification).

**Lab reconciliation (optional).** When the protocol requires recent monitoring (an A1c for metformin, a creatinine for renally-cleared drugs), the lab-reconciliation tool checks the patient's chart for the lab result, including reconciling outside-lab results that may have come through in the last few days. This avoids the Eleanor failure mode where a recent lab exists but has not yet been reconciled into the chart at the time of triage.

**Medication-information lookup (optional).** Patients sometimes ask peripheral questions ("does this interact with the new ibuprofen my orthopedist mentioned?", "should I take this with food?"). The medication-information tool returns curated drug information from a clinical reference (RxNorm, FDB, Lexicomp, or the practice's preferred reference). The bot answers from the curated source, not from its training data.

A refill bot is, architecturally, an LLM with a system prompt that tells it what assistant it is, the patient's authenticated context, the patient's medication list, and access to those tools. The LLM does the reasoning ("the patient asked about their metformin; let me look it up, check eligibility, and either submit the refill or route it"); the tools execute the deterministic actions.

The architectural decision that matters most: the LLM does not approve refills directly. The protocol-evaluation tool approves refills; the LLM proposes; the tool decides. Every action that affects the patient's medication record goes through a tool with a well-defined contract. This separation is what makes the system safe enough to handle medication actions and trustworthy enough for the clinical leadership to allow it to e-prescribe at all.

### Why a Generic LLM Cannot Manage Refills

A naive product approach would be: take a generalist LLM, give it a chat surface, give it the patient's chart, and let it negotiate refills. This does not work for several reasons that get worse the closer you look.

**The model has no view of the patient's actual medications.** The LLM does not know what the patient takes unless the patient's medication list is in the context. If the LLM is asked to reason about "their metformin" without that data, it will guess. The guesses will be plausible and will be wrong. The medication-lookup tool provides the structured medication list and is the only reliable source of truth.

**The model cannot evaluate the protocol consistently.** The practice's refill protocol is a set of explicit rules: lisinopril maintenance refill auto-approves if the patient's blood pressure has been documented in the last twelve months and the medication has not been escalated in the last three months. Metformin auto-approves if the most recent A1c is within the practice's documented range and is dated within the last year. Statins auto-approve if the most recent lipid panel is within the last year and the LDL is at goal. Asking the LLM to evaluate these rules conversationally produces inconsistent answers because the LLM is a stochastic function. The protocol-evaluation tool is deterministic. The protocol must be encoded as code, not as prompt text.

**The model cannot transactionally e-prescribe.** E-prescribing is a transactional operation: write to the e-prescribing platform, get a confirmation, surface the confirmation to the patient. The LLM is not transactional. The e-prescribe tool provides the transactional contract.

**The model cannot enforce the regulatory layer.** Controlled substances follow Schedule II through V regulations including DEA EPCS (electronic prescribing of controlled substances) requirements and state-specific PDMP (prescription drug monitoring program) check obligations.  Asking the LLM to enforce these is asking the LLM to do regulatory compliance, which it cannot reliably do. The tool layer enforces the regulatory layer; controlled substances route to the appropriate clinical workflow rather than auto-approving.

**The model has no audit trail.** Every refill action is a clinical event that needs to be auditable: who initiated the request, when, against what protocol version, with what supporting data, with what outcome. The LLM produces conversational text; the tool layer produces transactional records. Without the tool layer, the audit trail is unstructured chat logs.

**The model cannot handle drug-drug interaction screening reliably.** A new medication added by an outside prescriber may interact with one of the patient's current medications. The interaction screening must happen against an authoritative drug-interaction database, not against the LLM's training data. The interaction-screening tool wraps the database; the LLM consumes the result.

**The model cannot enforce the prescriber's authority.** A medication initially prescribed by a specialist (a cardiologist's amiodarone, a rheumatologist's methotrexate) is generally not refillable through the primary care practice. The bot has to route these to the specialist's office or to a coordinated care pathway, not auto-approve them. The protocol-evaluation tool encodes the prescriber-authority rules; the LLM cannot.

**The model has compliance implications for medication-related conversation.** Every refill conversation is a HIPAA-relevant interaction with PHI. The conversation log is PHI. The medication list, the lab values, the chart context that the bot retrieved are PHI. The architecture must produce the durable audit pipeline that scheduling required, plus a layer of clinical-event documentation that the scheduling bot did not need.

### What the Refill Bot Has To Do That the Scheduling Bot Did Not

Recipe 11.2 (scheduling) established the patterns this recipe inherits: input safety screening, intent classification, identity verification with graduated assurance, tool-use orchestration, transactional fulfillment, output safety screening, audit logging, per-cohort monitoring. The refill bot adds five structural commitments that the scheduling bot did not have.

**Clinical protocol as code.** The scheduling bot's domain logic is the practice's scheduling rules. The refill bot's domain logic is the practice's clinical refill protocol. The protocol covers more medical-domain detail (medication classes, monitoring requirements, dosing rules, contraindications), changes more frequently (as new medications come to market, as guidelines update, as the practice refines), and has higher consequences when wrong (an incorrect scheduling action wastes time; an incorrect refill action affects therapy). The protocol-as-code commitment includes versioning, review by clinical leadership, sandbox testing, staged rollout, and audit-record stamping with the active protocol version.

**Prescriber co-signature workflow.** Even when the protocol auto-approves a refill, in many institutions the prescribing physician's name appears on the refill, and the physician needs to be in the loop. The co-signature workflow surfaces auto-approved refills to the prescriber's queue for review (within the regulatory and institutional timeline; in many practices this is asynchronous within twenty-four to seventy-two hours of the bot's action). The bot's authority is delegated by the prescriber's standing order or protocol; the co-signature confirms that the delegation was applied appropriately.

**Drug-interaction and contraindication checking.** Every refill action runs through an interaction-and-contraindication check against the patient's current medication list and the patient's documented allergies and conditions. This is not optional. The clinical-decision-support layer is a hard requirement, and the integration with the practice's clinical-decision-support system (which is typically embedded in the EHR) is part of the architecture.

**Pharmacy integration as a first-class concern.** The scheduling bot ends at the calendar; the refill bot has to follow through to the pharmacy and surface the resulting state to the patient. The patient's "is my refill ready?" question is part of the bot's scope. Pharmacy integration depth varies (some pharmacies expose APIs, some require Surescripts intermediation, some are entirely opaque to the practice), and the bot's architecture must accommodate the heterogeneity without making promises it cannot keep.

**Controlled-substance handling as a hard non-negotiable boundary.** Controlled substances do not auto-approve. Ever. The bot identifies controlled-substance requests, explains the situation to the patient transparently, and routes to the appropriate clinical workflow. The boundary is encoded in the protocol-evaluation tool, in the bot's prompt, and in the output safety screening as a triple defense.

The rest is largely the same as recipe 11.2: tool-surface contract management, identity-assurance lifecycle, transactional-failure compensation, per-cohort monitoring, conversation logging, scope filtering, crisis detection.

### The Refill Reality

A few notes on what makes refill management specifically harder than other transactional bot use cases.

**Medication-naming variability is extreme.** Patients refer to medications by brand name ("Lipitor"), generic name ("atorvastatin"), color ("the white round one"), function ("the cholesterol pill"), or position in the pill organizer ("the morning one"). The bot's medication-resolution tool needs the patient's structured medication list as ground truth. With that context, an LLM resolves the patient's reference reliably. Without it, the LLM guesses, and the guesses are sometimes wrong in dangerous ways (atenolol versus albuterol; hydroxyzine versus hydralazine).

**Medication lists are frequently out of date.** The patient's documented medication list in the chart often lags reality. The patient stopped taking a medication two months ago; the chart still shows it as active. The patient started a new medication from the cardiologist last week; the chart has not been updated yet because the cardiologist is on a different EHR. The bot has to reconcile what the patient says they take with what the chart says. When the patient says "I'm not taking the gabapentin anymore," the bot does not just accept this and discontinue; the bot surfaces it as a medication-reconciliation event for clinical follow-up while still handling the immediate refill question.

**Monitoring requirements are nuanced.** Metformin needs an A1c periodically. Statins need a lipid panel periodically. ACE inhibitors and ARBs need a creatinine and potassium periodically. Lithium needs a blood-level check on a tighter cadence. Each medication class has a documented monitoring expectation that the practice has codified, and the cadence depends on the patient's overall context (renal function, comorbidities, recent dose changes). The protocol must encode the monitoring rules, and the protocol's quality is the bot's ceiling.

**Refill timing rules vary by medication and by payer.** A 30-day supply with three refills behaves differently than a 90-day supply with one refill. A medication that the insurance has authorized a quantity-limit override on behaves differently than one without. A medication that is on the patient's mail-order benefit cannot be refilled at the retail pharmacy. The bot has to surface the relevant quantity, supply, and pharmacy correctly. Getting this wrong means the patient picks up nothing because the prescription went to the wrong pharmacy.

**Early-refill detection is a misuse signal.** A patient asking for a refill on a medication that they should not be running out of yet is a signal worth noticing. The signal is more important for some medications (controlled substances, opioids, benzodiazepines, stimulants) than others (a maintenance lisinopril). The protocol encodes the early-refill rules per medication class, and early-refill detections route to the appropriate clinical workflow with the timing analysis attached.

**The patient's adherence context matters.** A patient who reports running out because they were doubling the dose, or because they lost the bottle, or because they were taking it inconsistently, is in a different state than a patient who simply ran out on schedule. The bot can ask the question gently, surface the answer to clinical staff, and influence the disposition (a doubling-the-dose patient routes to the prescriber for review of the dosing; a lost-bottle patient gets the refill with a brief note about future planning).

**Discontinued medications come back.** A medication that the practice marked as discontinued may have been resumed by the patient outside the practice's visibility (the patient picked up an old bottle from a cabinet, the patient bought a generic over the counter in another country, the patient was advised by an outside provider to resume it). The bot has to handle "I want to refill the gabapentin" when the gabapentin shows as discontinued in the chart, by surfacing the discrepancy and routing to a clinical conversation rather than just refusing.

**Specialist medications require boundary-setting.** A primary care practice generally does not refill the specialist's medications. The specialist's amiodarone, the rheumatologist's methotrexate, the endocrinologist's insulin pen with the dose-titration plan in the specialist's chart, the oncologist's chemotherapy, the gastroenterologist's biologic. The bot's protocol-evaluation tool encodes the prescriber-authority boundaries; the bot transparently routes specialist refills to the specialist's office or to the coordinated-care pathway.

**Patients sometimes ask about discontinuation, not refill.** A patient saying "I want to stop taking the sertraline" is asking about discontinuation, not refill. The bot has to recognize this is a clinical conversation, decline to act on it as a refill question, and route to the appropriate clinical workflow with the context preserved.

### Where the Field Has Moved

A few practical updates worth knowing.

**FHIR MedicationRequest is the standard data model.** The FHIR MedicationRequest resource provides a standard representation of prescriptions, refills, and the relationship to the dispensing pharmacy.  Most major EHRs expose MedicationRequest endpoints. The bot's medication-lookup tool wraps the institution-specific implementation behind a stable internal interface.

**Surescripts is the practical e-prescribing channel.** In the U.S., Surescripts provides the routing layer between prescribers and pharmacies.  The practice's existing e-prescribing setup typically routes through Surescripts already; the bot's e-prescribe tool wraps this existing path.

**CDS Hooks are increasingly available.** The CDS Hooks specification provides a standard way for clinical-decision-support systems to be invoked at specific decision points (including order-sign hooks for medication ordering).  Where available, the bot's protocol-evaluation tool can invoke the institution's CDS layer via CDS Hooks for interaction screening, contraindication checks, and policy enforcement.

**Tool-using LLMs are the default architecture.** Same as recipe 11.2. The function-calling pattern, with the LLM proposing tool calls and the tool layer executing them, is the default architecture for transactional conversational AI as of 2024 onward.

**Standing orders and protocol delegation are mature institutional patterns.** Most ambulatory practices already have standing orders for routine refills under physician delegation.  The bot's authority is the same delegation, applied consistently rather than person-by-person. The practice's existing standing-order documentation is the starting point for the bot's protocol.

**Pharmacy-side patient apps have raised expectations.** Patients are accustomed to the experience of CVS, Walgreens, and the major mail-order pharmacies' apps, which provide refill status, pickup notifications, and medication reminders. The practice-side bot's UX needs to be at least as smooth, or patients will perceive the practice's tooling as worse than the pharmacy's even when it is doing more.

**Build-vs-buy economics favor partial-buy for many institutions.** The protocol-evaluation, audit, and orchestration layer is increasingly available from EHR vendors and from third-party patient-engagement vendors. Building all of it from scratch is rare. The practice usually buys the engine and customizes the protocol; the protocol customization is where the institutional value lives.

---

## General Architecture Pattern

A healthcare prescription refill bot decomposes into nine logical stages: channel entry, input safety screening, intent classification, identity verification, medication resolution, refill-eligibility evaluation, transactional fulfillment (e-prescribe or clinical routing), output safety screening, and audit logging. The cross-cutting concerns from recipes 11.1 and 11.2 carry forward; this recipe adds two new ones (clinical-protocol-as-code lifecycle, prescriber co-signature workflow).

```text
┌────────── CHANNEL ENTRY ─────────────────────────────────┐
│                                                           │
│   [Patient connects through one of the configured         │
│    channels: web chat widget, in-app chat, SMS,           │
│    voice (with ASR/TTS), authenticated patient-portal     │
│    embed]                                                 │
│                                                           │
│   [Greeting and disclosure]                               │
│    - Identifies as a chatbot, not a pharmacist or         │
│      clinician                                            │
│    - States the bot's scope (refills of existing          │
│      maintenance medications; not new prescriptions,      │
│      not dose changes, not controlled substances          │
│      auto-approval, not clinical advice)                  │
│    - Offers an immediate path to a human                  │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate session_id                                  │
│    - Capture channel, authentication context, and any     │
│      deep-link parameters (e.g., patient clicked a        │
│      "request refill" link from the medication-list       │
│      page in the portal)                                  │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, auth context]             │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY SCREENING ────────────────────────┐
│                                                           │
│   [Same primitive as recipes 11.1 and 11.2:]              │
│    - Crisis detection (preempts everything; a patient     │
│      who mentions overdose, suicidal ideation, or         │
│      misuse during a refill conversation is a crisis      │
│      signal that routes to the crisis pathway)            │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked-with-disposition] │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INTENT CLASSIFICATION ─────────────────────────┐
│                                                           │
│   [Map the user's request to one of the bot's intents]    │
│    - request_refill                                       │
│    - check_refill_status                                  │
│    - cancel_refill_request                                │
│    - medication_question (peripheral question, not        │
│      a refill action)                                     │
│    - medication_change (asking to start, stop, or         │
│      change therapy; out of scope)                        │
│    - clinical_question (out of scope; route to nurse      │
│      triage)                                              │
│    - controlled_substance_request (in-scope-but-          │
│      route-to-clinician; never auto-approved)             │
│    - out_of_scope (other topics; route appropriately)     │
│           │                                               │
│           ▼                                               │
│   [Output: in-scope intent | out-of-scope handoff]        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY VERIFICATION ─────────────────────────┐
│                                                           │
│   [Same graduated assurance pattern as recipe 11.2,       │
│    with a higher floor for refill-related actions]        │
│                                                           │
│   [Authenticated session path]                            │
│    - Patient is logged into the patient portal            │
│    - The session conveys an authenticated patient_id      │
│    - The bot accepts the patient_id as verified           │
│                                                           │
│   [Unauthenticated channel path]                          │
│    - Refills generally require a higher assurance         │
│      level than scheduling. Many institutions choose      │
│      to require authenticated sessions for refill         │
│      actions and to limit unauthenticated paths to        │
│      status-check intents only.                           │
│    - When unauthenticated paths are allowed, the bot      │
│      uses the same identity verification primitives       │
│      as recipe 11.2 with stronger confirmation factors    │
│      (e.g., a one-time code rather than last-four-of-     │
│      phone)                                               │
│                                                           │
│   [Step-up authentication for sensitive actions]          │
│    - Asking about a controlled-substance medication       │
│      may require step-up                                  │
│    - Requesting an early refill may require step-up       │
│           │                                               │
│           ▼                                               │
│   [Output: verified patient_id, assurance_level]          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── MEDICATION RESOLUTION ─────────────────────────┐
│                                                           │
│   [Tool: medication_list_lookup]                          │
│    - Pull the patient's structured medication list        │
│      from the EHR via FHIR MedicationRequest              │
│    - Include the active medications, their doses,         │
│      frequencies, refills-remaining, last-fill dates,     │
│      prescribing providers, dispensing pharmacies         │
│                                                           │
│   [Tool: medication_resolution]                           │
│    - Given the patient's free-text descriptor and the     │
│      medication list, identify the specific medication    │
│    - Use the LLM with the medication list as context      │
│    - When ambiguous, ask the patient to clarify           │
│      (e.g., the patient says "the heart pill" and they    │
│      take both lisinopril and atorvastatin)               │
│                                                           │
│   [Discontinued-medication handling]                      │
│    - When the patient asks for a medication that the      │
│      chart marks as discontinued, surface the             │
│      discrepancy, ask the patient to confirm what they    │
│      are actually taking, and route to clinical staff     │
│      with the context preserved                           │
│                                                           │
│   [Specialist-medication handling]                        │
│    - When the medication's prescribing provider is        │
│      outside the practice (a cardiologist's amiodarone,   │
│      a rheumatologist's methotrexate), surface the        │
│      prescriber-authority boundary and route to the       │
│      appropriate office or coordinated-care pathway       │
│           │                                               │
│           ▼                                               │
│   [Output: resolved medication record, or routing         │
│    decision]                                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── REFILL-ELIGIBILITY EVALUATION ─────────────────┐
│                                                           │
│   [Tool: protocol_evaluate]                               │
│    - Inputs: resolved medication record, patient          │
│      chart context (active diagnoses, allergies,          │
│      relevant lab values, blood pressure history,         │
│      other medications), the practice's protocol          │
│      version, and the request context (timing,            │
│      pharmacy, patient-stated context)                    │
│    - Output: a structured decision with                   │
│      - disposition (auto_approve, route_to_prescriber,    │
│        route_with_monitoring_due, route_with_clinical_    │
│        question, deny_with_reason, controlled_substance_  │
│        always_route)                                      │
│      - reasoning (which protocol rules fired and why)     │
│      - data_consulted (which chart elements the           │
│        protocol read)                                     │
│      - protocol_version (stamped on the decision)         │
│                                                           │
│   [Drug-interaction and contraindication screening]       │
│    - Run the resolved medication against the patient's    │
│      active medication list and documented allergies      │
│      and conditions                                       │
│    - Use the institution's clinical-decision-support      │
│      system (typically CDS Hooks against the EHR) or      │
│      a dedicated drug-interaction database                │
│    - Surface findings to the protocol-evaluation step     │
│                                                           │
│   [Lab reconciliation]                                    │
│    - When the protocol requires recent monitoring,        │
│      check for the lab result in the chart                │
│    - Reconcile outside-lab results that may have come     │
│      through recently (don't fail the request because     │
│      the lab is technically not in the chart yet when     │
│      the patient knows it was drawn)                      │
│           │                                               │
│           ▼                                               │
│   [Output: structured eligibility decision with full      │
│    reasoning attached]                                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── TRANSACTIONAL FULFILLMENT ─────────────────────┐
│                                                           │
│   [Auto-approve path]                                     │
│    - Tool: e_prescribe                                    │
│      - Submits the refill to the dispensing pharmacy      │
│        through the e-prescribing platform (typically      │
│        Surescripts)                                       │
│      - Returns the prescription identifier and the        │
│        transmission status                                │
│    - Tool: cosignature_queue                              │
│      - Adds the auto-approved refill to the prescriber's  │
│        co-signature queue for asynchronous review         │
│        (within the institution's SLA, typically 24-72     │
│        hours)                                             │
│    - Tool: refill_event_journal                           │
│      - Writes the durable record of the refill action     │
│        with the protocol version, reasoning, data         │
│        consulted, prescriber, dispensing pharmacy         │
│                                                           │
│   [Route-to-clinician path]                               │
│    - Tool: clinical_routing                               │
│      - Packages the request with the bot's reasoning,     │
│        the data consulted, and any patient context        │
│        (e.g., the patient said they have been doubling    │
│        the dose)                                          │
│      - Queues the structured ticket in the appropriate    │
│        inbox (nurse triage, prescriber inbox, pharmacy    │
│        coordination, depending on the disposition)       │
│      - Returns the queue position and the expected        │
│        SLA                                                │
│    - Tool: refill_event_journal                           │
│      - Writes the durable record of the routing event     │
│                                                           │
│   [Deny-with-reason path]                                 │
│    - Tool: refill_event_journal                           │
│      - Writes the durable record of the denial with       │
│        the protocol-driven reasoning                      │
│    - Conversational response explains the denial          │
│      transparently and offers next steps                  │
│                                                           │
│   [Failure handling]                                      │
│    - E-prescribe transmission error: queue for retry,     │
│      surface the issue to clinical staff, tell the        │
│      patient honestly                                     │
│    - Pharmacy unreachable: queue for retry, surface       │
│      the issue, ensure the patient is not left thinking   │
│      the refill was sent when it was not                  │
│    - Co-signature queue write error: the e-prescribe      │
│      already happened; the co-signature event is queued   │
│      for retry; the operations dashboard surfaces         │
│      pending co-signature backlog                         │
│           │                                               │
│           ▼                                               │
│   [Output: refill action result with full structured      │
│    audit data]                                            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY SCREENING ───────────────────────┐
│                                                           │
│   [Same primitive as recipes 11.1 and 11.2, with new      │
│    refill-specific checks]                                │
│    - Scope filter on generated response (no clinical      │
│      advice, no dose changes, no medication starts)       │
│    - Vendor-managed guardrail layer                       │
│    - Hallucination check: did the bot tell the patient    │
│      the refill was sent when no e_prescribe call         │
│      returned success? Did the bot mention a medication   │
│      that is not on the patient's list? Did the bot       │
│      claim a lab value that does not match the lab        │
│      tool's result?                                       │
│    - Controlled-substance guardrail: did the bot          │
│      indicate it was processing a controlled-substance    │
│      refill? Verify against the protocol-evaluate         │
│      result and replace with the routing template if      │
│      so                                                   │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, or replaced     │
│    with a refusal-and-handoff]                            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND TELEMETRY ─────────────────────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User utterances (scrubbed of inadvertent PHI)        │
│    - Tool calls with arguments and results                │
│    - Generated responses                                  │
│    - Active model and prompt versions                     │
│    - Active protocol version stamped on every             │
│      eligibility evaluation                               │
│    - Identity-verification outcome and assurance level    │
│    - Refill outcomes (auto_approved, routed, denied,      │
│      failed, abandoned)                                   │
│                                                           │
│   [Refill-event journal]                                  │
│    - Durable, separately-governed record of every         │
│      refill action: the medication, the patient, the      │
│      protocol version, the decision, the reasoning,       │
│      the data consulted, the e-prescribing identifier,    │
│      the dispensing pharmacy, the prescribing provider,   │
│      the co-signature status                              │
│    - Retention sized to the institution's medical-        │
│      record-retention floor                               │
│                                                           │
│   [Operational telemetry]                                 │
│    - Refill auto-approval rate per medication class       │
│    - Routing rate per disposition                         │
│    - Median time-to-completion (auto-approved vs          │
│      routed)                                              │
│    - Co-signature backlog                                 │
│    - Identity-verification failure rate                   │
│    - Tool-call failure rate per tool                      │
│    - Per-cohort metric slices (language, channel,         │
│      authentication path, age cohort)                     │
│                                                           │
│   [Sampled review queue]                                  │
│    - Random sample plus targeted sample of low-           │
│      confidence and escalated conversations               │
│    - Reviewers tag failure modes (medication-resolution   │
│      error, protocol-evaluation error, routing-           │
│      disposition error, etc.)                             │
│    - Clinical-leadership review of auto-approved          │
│      sample for protocol-application accuracy             │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals]      │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points specific to the refill bot.

**The protocol is a versioned governance artifact.** The clinical refill protocol, encoded as code, is the bot's most consequential institutional asset. It is owned by clinical leadership, not by engineering. Changes go through clinical-leadership review, sandbox testing, and staged rollout. Every protocol-evaluation result records the active protocol version. Every refill action records the protocol version that authorized it. The conversation log, the refill-event journal, and the operational dashboards all reference the protocol version. When the protocol changes, the institution can reconstruct exactly which decisions were made under which version. This is the load-bearing accountability that makes the bot safe enough to delegate routine refills to.

**Prescriber co-signature is not optional, but it is asynchronous.** The bot's authority comes from a delegation arrangement with the prescriber. The prescriber retains responsibility for the patient's therapy. The co-signature workflow surfaces auto-approved refills to the prescriber within a defined SLA (typically 24-72 hours). The prescriber can flag any auto-approval for retrospective clinical review. The flagged reviews feed the protocol-improvement loop. The bot's authority is delegated; the prescriber's accountability is preserved.

**Controlled-substance handling is a hard architectural floor.** Every layer of the bot has explicit logic for controlled substances: the medication-list-lookup tool returns the controlled-substance schedule, the medication-resolution step flags controlled substances, the protocol-evaluate tool returns "controlled_substance_always_route" for any controlled-substance request, the e-prescribe tool refuses to transmit controlled substances through the bot's auto-approval path, the output safety screening checks for controlled-substance language in the response. The triple defense is intentional. A bot that auto-approves a controlled substance once is a bot that gets the project canceled.

**Medication resolution against the patient's list is the safety floor.** The bot does not act on a medication unless the medication is on the patient's list. The medication-resolution tool returns a structured medication record from the list or returns "no match"; in the no-match case, the bot does not guess. This prevents the failure mode where the bot interprets "the white pill" as a medication that the patient does not take, runs the protocol against a wrong record, and produces a wrong action.

**Lab reconciliation closes the most common protocol-block escape valve.** The Eleanor failure mode (lab exists but is not yet reconciled into the chart) is so common that the bot's lab-reconciliation step is part of the architecture, not an optional extension. The institution's reconciliation pipeline (recipe 5.6 patterns) is the integration point; the bot's lab-reconciliation tool checks the latest available result, including pending-reconciliation outside-lab results.

**The refill-event journal is a separate record class with stricter governance than the conversation log.** Conversations are PHI-relevant and have audit obligations; refill events are clinical-record events and have medical-record-retention obligations. The institution's medical-records team owns the refill-event journal's retention, access, and disclosure-accounting policies, separately from the conversation-log policies.

**Per-cohort monitoring is non-negotiable, with refill-specific metric slices.** Auto-approval rate, time-to-completion, and routing-disposition mix can vary substantially by language, age cohort, channel, and medication class. Equity-relevant disparities (an auto-approval rate that is meaningfully lower for non-English-speaking patients than for English-speaking patients with the same medication and the same protocol-relevant data) is a launch-gate criterion, not a post-launch dashboard.

**Compensation operations cover medication actions specifically.** When a refill that should not have happened did happen, the operational team needs to be able to act: contact the patient, contact the pharmacy if the medication has not been picked up, document the event, surface it for clinical review. The compensation path is explicit, audited, and exercised in tabletop drills before launch.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.03-architecture). The Python example is linked from there.

## The Honest Take

The refill bot is the recipe in this chapter where the operational savings are most concrete, the clinical safety stakes are most direct, and the institutional maturity required is most underestimated.

The first trap, like with the FAQ and scheduling bots, is treating the institutional content as someone else's problem. With the FAQ bot it was the parking policy. With the scheduling bot it was the visit-type catalog. With the refill bot it is the clinical refill protocol. The single largest determinant of bot quality is the protocol's explicitness. Most practices discover, when they start the project, that their refill protocol is a one-page handout that the experienced nurses follow with appropriate clinical judgment and that the new nurses follow inconsistently. Formalizing the protocol is a clinical-leadership project, supported by engineering, and it takes three to six months of focused work. The practices that ship a refill bot well start with the protocol formalization and end up with a bot that handles routine refills correctly. The practices that ship a refill bot badly start with the LLM and end up with a bot that auto-approves things that should have been routed and routes things that should have been auto-approved, which the clinical staff has to clean up retroactively.

The second trap is underestimating the prescriber-delegation governance. The bot's authority comes from the prescriber. The prescriber is the named clinician on the e-prescription, the prescriber is liable for the medication, the prescriber's license is on the line. The delegation arrangement (which the medical staff committee approves, which the prescribers sign, which the institution renews annually) is the legal and clinical foundation for the bot's authority. Building the bot without the delegation arrangement is building on sand. Get the delegation right at the start, with named scope, named prescribers, named SLAs.

The third trap is shipping with too narrow a scope. A refill bot that only handles three medications for one prescriber is not worth deploying because the patient calls or emails for almost everything else. The right starting scope is roughly: the most common chronic-disease maintenance medications (metformin, lisinopril, statins, levothyroxine, SSRIs in stable patients, sometimes inhalers for stable asthma), with formal protocol coverage and prescriber delegation, across a single primary-care practice or a small set of clinically-coordinated practices, with explicit out-of-scope routing for everything else. Any narrower is a pilot.

The fourth trap is shipping with too broad a scope. The refill bot is not a clinical-decision-support system, not a medication-reconciliation system, not a dose-titration assistant, not a controlled-substance auto-approver. The scope-discipline work from recipes 11.1 and 11.2 is even more important here. The LLM, by default, will attempt to negotiate dose changes, recommend medication changes, and answer clinical questions. The institution does not want this. The scope filter, the protocol-evaluate guardrails, the controlled-substance triple-defense are the layered defenses, and underweighting them produces a bot that occasionally takes actions that have therapeutic consequences the institution did not authorize.

The fifth trap is treating the controlled-substance handling as a soft constraint. It is not. Controlled substances do not auto-approve. Ever. Across every layer of the bot, every medication request is checked against the controlled-substance schedule, and any controlled substance routes to the appropriate clinical workflow. The triple-defense (protocol-evaluate returns controlled_substance_always_route, e-prescribe refuses to transmit through the auto-approval path, output safety screening checks for controlled-substance language in the response) is intentional. A bot that auto-approves a controlled substance once is a bot that gets the project canceled.

The sixth trap is shipping without lab reconciliation. The Eleanor failure mode (recent lab exists at an outside facility, has not yet been reconciled into the chart, protocol incorrectly finds "monitoring overdue") is so common that the bot's lab-reconciliation step is part of the architecture, not an optional extension. Without it, the bot's auto-approval rate is artificially low, the routing rate is artificially high, the clinical-staff burden is not reduced, and the bot's value proposition is undermined. Invest in the lab-reconciliation pipeline as part of the bot's prerequisites.

The seventh trap is shipping without a plan for measuring quality across cohorts. Auto-approval rate alone is not enough. The metric mix includes: auto-approval rate per medication class, routing rate per disposition, time-to-completion per disposition, identity-verification success rate, mis-resolved-medication rate, prescriber-flagged co-signature rate, tool-call success rate per tool, handoff rate per intent, patient-feedback distribution, per-cohort metric slices. Build the dashboards before launch and review them weekly with clinical leadership.

The thing that surprises engineers coming from generic-chatbot backgrounds is how much of the engineering value is in the unglamorous integration work. The wrapper around the EHR's FHIR endpoints. The protocol-evaluation tool with the practice's protocol encoded as code. The e-prescribing tool wrapping the existing Surescripts setup. The lab-reconciliation tool integrating with the institution's reconciliation pipeline. The interaction-screening tool calling the institution's CDS layer. The co-signature workflow with the prescriber's inbox. The per-medication-class metrics. None of this is exotic technology, and all of it is critical.

The thing that surprises clinical leaders coming from clinical-software backgrounds is how much of the bot's value comes from the LLM's natural-language understanding of patient phrasing. The patient who says "the diabetes pill" or "my morning blood pressure pill" or "the round one in the gold bottle" is a parse that the bot handles trivially when the patient's medication list is in context. The bot's value to the patient is, in large part, "you can refer to your medications however you want, and the bot will figure out which one you mean." This capability did not exist five years ago. Underweighting it understates the patient-experience improvement the bot can deliver.

The thing about the AWS implementation specifically (covered in the [architecture companion](chapter11.03-architecture)): Bedrock Agents is the right level of abstraction for this recipe in most cases, same as recipe 11.2. The Agent handles the multi-step LLM-and-tool orchestration; the action groups are the bot's tool surface; Knowledge Bases provides the medication-information corpus and the protocol-language phrasings; Guardrails provides the safety filtering. The tool layer is where the institutional value lives.

The thing about cost: the per-refill infrastructure cost is small relative to the operational savings versus nurse-and-prescriber-handled refill processing. A nurse-and-prescriber refill costs the institution a meaningful fraction of clinician time (5-15 minutes distributed across receptionist, nurse, and prescriber); a bot auto-approval costs $0.03-0.15 in infrastructure plus less than a minute of prescriber time at co-signature. The bot does not handle every refill (a meaningful fraction routes to clinical staff with structured context), but the auto-approved refills are a substantial cost saving. The dominant cost is engineering and operational overhead, not the AWS infrastructure.

The thing about clinical safety: the refill bot's safety profile is bounded above by the protocol's quality and the lab-reconciliation pipeline's quality. The bot is a deterministic application of the protocol against the available chart data. When the protocol is wrong or the chart data is wrong, the bot's decision is wrong. The bot does not "judge" in the way a human nurse does. This is a feature (the decisions are consistent and auditable) and a constraint (the protocol must be right). Plan for the protocol to evolve as the bot surfaces edge cases.

The thing about scope: the refill bot is more bounded than the FAQ and scheduling bots in some ways (only chronic maintenance medications, only auto-approve or route, only the practice's existing prescribers) and more consequential in others (medication actions affect therapy, the audit trail is a clinical record, the prescriber co-signature is a regulated workflow). The right framing is "we are taking the routine refills off the clinical staff's plate while preserving the prescriber's accountability." That framing keeps everyone aligned on what the bot is and is not.

The thing I would do differently the second time: invest more, earlier, in the protocol formalization. Every successful refill bot deployment I have seen had three to six months of protocol formalization before the engineering work. The deployments that skipped this step shipped on time and then spent the following six to twelve months chasing protocol-evaluation bugs that were really protocol-definition bugs.

The last thing, because it is the easiest one to underestimate: the refill bot is the recipe where the patient-experience improvement is most tangible for the patients who need it most. Eleanor is the canonical user. She is 71, she takes seven medications, she is the patient who cannot afford to be off her metformin for five days because the voicemail-and-callback loop took too long. The patients who benefit most from this bot are the patients who currently get the worst service from the existing voicemail-and-fax workflow. Building the bot well for Eleanor is the moral case for the project. The operational savings are the business case. Both cases reinforce each other when the bot is built carefully.

The refill bot is the right third recipe in this chapter, after the FAQ bot and the scheduling bot, because it builds on the patterns those two bots established (input safety screening, identity verification with graduated assurance, tool-use orchestration, output safety screening, audit pipeline, per-cohort monitoring) and adds the patterns that the rest of the chapter will need (clinical-protocol-as-code lifecycle, prescriber delegation and co-signature workflow, controlled-substance handling). Build it carefully. Ship it incrementally. Monitor it rigorously. The Eleanors of the world deserve a better refill workflow than the previous generation of voicemail-and-fax gave them, and the institutions that build this bot well give it to them.

---

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, the foundational recipe. The refill bot inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring from the FAQ bot.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter, the previous transactional bot. The refill bot inherits the tool-use orchestration pattern, the identity-verification graduated-assurance pattern, the slot-hold-style transactional contract (here adapted to e-prescribe-and-cosignature), and the structured ticket pattern for clinical routing.
- **Recipe 11.4 (Pre-Visit Intake Bot):** Same chapter. The intake bot collects clinical information before a visit, including medication updates that feed back into the refill bot's medication list.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. The chronic-disease coach can detect adherence gaps and refer to the refill bot for the refill action; the refill bot can detect adherence concerns and refer to the chronic-disease coach for the coaching follow-up.
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter. The refill bot's controlled-substance routing for psychiatric medications, the bot's handling of misuse signals, and the bot's crisis detection all reference patterns from the mental health bot.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10. The voice channel for refills builds on the voice assistant's ASR/TTS patterns; the conversational logic from the refill bot is shared.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4. The adherence-detection logic from recipe 4.5 informs the refill bot's adherence-prompt behavior and the routing of adherence concerns to coaching workflows.
- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Chapter 4. The proactive-outreach patterns from recipe 4.1 inform the refill-reminder extension.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Chapter 2. The prior-authorization workflow integration draws on recipe 2.4's patterns.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Chapter 5. The lab-reconciliation pipeline that the refill bot depends on draws on recipe 5.6's data-linkage patterns.
- **Recipe 3.4 (Medication Dispensing Anomalies):** Chapter 3. The abuse-detection telemetry that monitors for unusual fill patterns draws on recipe 3.4's anomaly-detection patterns.
- **Recipe 8.x (RxNorm-coded medication entity extraction):** Chapter 8. The medication-resolution disambiguation supplements draws on traditional NLP patterns. 

---

## Tags

`conversational-ai` · `refill-bot` · `prescription-refill` · `medication-management` · `patient-facing` · `patient-engagement` · `digital-front-door` · `tool-using-llm` · `function-calling` · `bedrock-agents` · `transactional-bot` · `identity-verification` · `medication-resolution` · `protocol-as-code` · `prescriber-delegation` · `co-signature-workflow` · `controlled-substance-handling` · `drug-interaction-screening` · `lab-reconciliation` · `e-prescribing` · `surescripts` · `fhir-medicationrequest` · `cds-hooks` · `ehr-integration` · `intent-classification` · `scope-containment` · `crisis-detection` · `prompt-injection-defense` · `prompt-versioning` · `persona-design` · `multilingual` · `accessibility` · `equity-monitoring` · `cohort-stratified-accuracy` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `comprehend-medical` · `healthlake` · `lambda` · `api-gateway` · `waf` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `connect` · `simple-medium` · `quick-win` · `hipaa` · `phi-handling` · `audit-trail` · `refill-event-journal` · `chapter11` · `recipe-11-3`

---

*← [Recipe 11.2: Appointment Scheduling Bot](chapter11.02-appointment-scheduling-bot) · [Chapter 11 Index](chapter11-preface) · [Recipe 11.4: Pre-Visit Intake Bot](chapter11.04-pre-visit-intake-bot) →*
