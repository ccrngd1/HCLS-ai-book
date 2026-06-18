# Recipe 10.5: Patient-Facing Voice Assistant ⭐⭐

**Complexity:** Medium · **Phase:** Production-track · **Estimated Cost:** ~$0.05-0.30 per completed conversation (depends on call duration, choice of ASR and TTS tier, LLM usage for intent and dialog, and whether the conversation is fulfilled in self-service or transferred to a human agent)

---

## The Problem

It is 9:14 on a Saturday morning. An 82-year-old man named Walter is sitting at his kitchen table with a paper appointment card from his cardiologist's office. The card says his next visit is on the 17th. Walter is reasonably sure that means the 17th of June, but his wife thought it was July, and now neither of them is certain. The cardiologist's office is closed on Saturdays. Walter does not have the patient portal set up. He had it set up four years ago but he changed his email address after his old provider went out of business and he never got the new email registered with the portal, and the last time he tried to log in he ended up locked out and had to wait for a paper letter. The paper letter never came. He has not tried to log in since.

He picks up the phone and calls the cardiology office's main line. The recorded message tells him the office is closed and to call back Monday between 8 and 5. Then it tells him that for medical emergencies he should call 911 or go to the nearest emergency room. Then it tells him about the patient portal. Then it ends. There is no option to check an appointment. There is no option to talk to anyone. There is, in particular, no way to say "I just want to know if my appointment is on June 17th or July 17th" and get an answer.

Walter hangs up and waits until Monday. On Monday at 8:02 he calls back. The phone tree picks up, runs through its menus, and routes him to the scheduling line. He waits on hold for twenty-two minutes. Eventually a scheduling agent picks up, takes his name and date of birth, looks up his record, and tells him his appointment is on June 17th at 2:30 pm. The whole exchange, once the agent is on the line, takes ninety seconds.

Walter has, in this scenario, used twenty-three minutes of his Monday morning, twenty-two minutes of a scheduling agent's Monday morning, one phone-tree routing event, and the institutional patience that everyone involved would prefer to spend on something more useful than confirming that an appointment is on the date the appointment card already said it was on. The call did not need a human. It did not even need a phone tree. It needed a system that could pick up the phone on Saturday morning, listen to "I'm trying to confirm my next cardiology appointment," verify Walter's identity in some manner that does not require a portal login or a perfect memory for menu navigation, look up his appointment, and tell him "your appointment is Tuesday, June 17th, at 2:30 pm." Total elapsed time: under a minute. Total human staff time: zero.

This is the patient-facing voice assistant problem. It is not a phone tree (recipe 10.1). It is not dictation for a clinician (recipe 10.4). It is the conversational entry point through which a patient can ask, in plain English (or Spanish, or Mandarin, or whatever language the institution serves), for the things that healthcare organizations get a hundred thousand calls about every year: when is my appointment, what is my copay, can you refill my prescription, where is the lab, when does the pharmacy close, did my test results come back, do I need to fast before tomorrow's visit, my insurance changed and I want to update it, can someone call me back about a billing question. None of these calls require clinical judgment. Most of them do not require a human. All of them, today, route through a phone tree and a queue and a human agent because there has not been a better front door.

The cost of having no better front door is not abstract. Walter's twenty-three minutes scale up across millions of similar calls per year, multiplied across thousands of healthcare organizations, into a staggering aggregate of patient time spent waiting for someone to confirm an appointment date. <!-- TODO: verify; healthcare contact-center industry research has shown that a substantial fraction of inbound calls are appointment-related inquiries that could be self-served by a sufficiently capable automated system, with specific percentages varying by specialty and organization --> The aggregate of staff time spent on those same calls is what call-center operations directors lose sleep over: scheduling agents spend a significant fraction of their day on calls that do not require their training, which means the calls that do require their training (the cancellation that should have been a transfer to a clinical triage nurse, the patient who is calling about an appointment but mentions chest pain in passing, the family caregiver coordinating multiple specialty visits) sit in the queue longer than they should.

There is also the equity dimension. The patient who has a portal account, a smartphone, and twenty minutes of comfort with web-form interactions handles all of this through the portal and never calls. The patient who is older, has limited tech comfort, has a shared family device, has a hearing aid that does not pair well with phones, has a vision impairment that makes the portal hard to navigate, has a primary language other than English, has a cognitive condition that makes multi-step menu navigation hard, or simply does not own a smartphone, has the phone as their primary or only access channel. <!-- TODO: verify; consumer healthcare research has consistently shown that older patients, patients with disabilities, patients in rural areas with limited broadband, and patients whose primary language is not English disproportionately rely on telephone-based access, but specific demographic figures continue to evolve --> The phone-tree-and-queue front door serves these patients meaningfully worse than it serves the digitally-comfortable cohort, in ways that are not visible in the operational dashboards that count completed appointments rather than abandoned calls.

There is the after-hours dimension. A patient who calls on Saturday morning with a question that does not need a human gets, in most healthcare organizations today, "we are closed, please call back Monday." A patient who calls Saturday morning with a question that does need a human gets the same message. The triage signal is lost; the inquiry is deferred; sometimes the patient just goes to the emergency department because they could not get an answer to a question that an automated system could have answered in thirty seconds.

There is the consumer-experience dimension. Patients who use voice assistants in the rest of their life (asking the smart speaker for a recipe, asking the phone for directions, asking the in-car system to call mom) are increasingly puzzled about why the healthcare system is so much harder to interact with than every other consumer service. The expectation gap is real and it is widening. The institutions that close it earn the loyalty of patients who would otherwise consider a competitor with a better digital experience. The institutions that ignore it lose patients quietly to retail-clinic competitors and direct-to-consumer telehealth services that figured this out years ago.

There is the cost dimension. A live agent handles roughly twenty to forty calls per hour depending on the complexity of the calls. <!-- TODO: verify; healthcare contact-center average handle time and calls-per-agent-per-hour vary substantially by specialty, organization, and call type --> The fully-loaded cost per agent-handled call (labor, infrastructure, training, attrition, occupancy, supervision) is not small. Calls that can be safely handled by an automated voice assistant cost a small fraction of that, with the cost dominated by the per-minute ASR pricing, the LLM intent-and-dialog pricing, and the telephony per-minute charges. The economics of moving the right calls into self-service are favorable enough that most large healthcare contact centers are actively investing in this category.

The trick, and the reason this recipe sits in the medium-complexity tier rather than the simple tier, is that "the right calls" is the load-bearing phrase in that sentence. A patient-facing voice assistant that handles too narrow a slice of calls is barely worth deploying. A patient-facing voice assistant that overreaches and tries to handle clinical questions is dangerous. The architectural challenge is building a system that confidently handles the operational and informational calls that should be self-served, gracefully escalates the calls that need a human, and instantaneously routes the calls that signal a clinical emergency to clinical triage. The technology to do this exists. The engineering to do it well requires more care than the simple-tier recipes in this chapter, because the failure modes are visible to patients, the safety constraints are real, and the equity constraints are non-negotiable.

The system we will build in this recipe handles the following kinds of patient interactions. Confirming and changing appointments. Requesting prescription refills (where the institution allows automated refill requests; many gate this through clinical review). Looking up basic facility information (hours, location, parking, pharmacy hours, lab hours). Requesting a callback for a topic the assistant does not handle directly. Acknowledging and routing common questions about insurance, billing, and medical records. Recognizing crisis or urgency signals ("chest pain," "I can't breathe," "I'm thinking about hurting myself") and immediately routing to clinical triage or to crisis resources, never trying to handle them in the assistant. Recognizing and routing complex or scope-out-of-bounds requests to a human agent with a warm handoff that preserves the conversation context, so the patient does not have to start over.

The system will be reachable through three channels: the institution's main phone line (telephony, where most of the volume lives, especially for older patients), the institution's mobile app (in-app voice assistant, where the engineering is easier and the demographic is younger), and the institution's smart speaker integration (Alexa skill or Google Action, where the volume is small but the patient-experience signal is strong because patients tell their friends and family about the smart-speaker thing more than any other channel). The architecture is the same across all three; the entry-point glue is different.

This is not the most technically novel recipe in the chapter. Patient-facing voice assistants have been a real product category for a few years now, with multiple commercial vendors and a growing reference architecture for institutions that build their own. The recipe takes seriously the things that go wrong in production: the older patient whose accent is underrepresented in the ASR's training data and who experiences the assistant as not understanding her, the family caregiver calling on behalf of an elderly parent with a HIPAA proxy relationship the institution has on file, the patient who mentions chest pain in passing while calling about an appointment, the shared phone where two patients call from the same number and the system has to verify identity correctly, the patient who tries to use the assistant on a flip phone and the assistant must degrade gracefully to DTMF fallback. The interesting engineering work is mostly in these edges; the happy path is straightforward.

Let's get into it.

---

## The Technology: Conversational Voice With Real Constraints

### What Makes Patient-Facing Different

A patient-facing voice assistant is, on paper, the same stack as the IVR enhancement in recipe 10.1: ASR plus NLU plus dialog management plus fulfillment plus TTS. In practice, the constraints are different in ways that change every architectural decision.

**The caller population is wide.** Recipe 10.1 routes calls; the routing decision is forgiving because if the system gets it wrong, the caller ends up at an agent who can correct the route. A patient-facing assistant that fulfills requests directly does not have that forgiveness. The system has to actually serve a 22-year-old commercial-insurance patient with a smartphone, an 82-year-old Medicare patient with a hearing aid, a Spanish-speaking patient who learned English as an adult, a patient with a speech impairment from a stroke, and a family caregiver calling on behalf of all three at various points. The accuracy floor matters more than the accuracy ceiling.

**The interaction is conversational, not navigational.** An IVR that misroutes a call is a small annoyance. An assistant that fails to understand "I want to know if my appointment is on the seventeenth" three times in a row is a deeply frustrating experience. The dialog manager has to be more flexible than the IVR equivalent: it has to handle reformulation gracefully, recognize when it is going in circles, and escalate before the patient gives up.

**The fulfillment surface is broader.** An IVR sends the call to the right queue. A voice assistant looks up the appointment, processes the refill request, retrieves the lab hours, transfers the call to nurse triage with a warm handoff that includes the conversation summary. Each of those is an integration: the EHR's appointment API, the pharmacy fulfillment system, the facility-information knowledge base, the contact center's warm-transfer protocol. The architecture has to handle them all, and handle their failure modes (the appointment API is down, the pharmacy system has not synced, the facility hours have not been updated for the holiday weekend).

**Identity verification is unavoidable for most useful interactions.** Looking up an appointment, requesting a refill, asking for test results, or anything else that touches PHI requires the system to confirm it is talking to the patient (or to an authorized proxy). Identity verification over voice is harder than it looks. Date of birth alone is famously weak. Knowledge-based authentication ("what was your last visit's copay?") is friction the patient does not want. Voice biometrics is technically promising but operationally complex and demographically uneven. The architecture has to choose, document, and defend its identity-verification posture.

**Scope containment is a clinical-safety requirement.** A patient calling about an appointment may, at any moment, ask the assistant a clinical question. "While I have you, my blood pressure has been kind of high lately, what do you think?" The assistant must not answer. It must recognize that this is a clinical question, decline politely, and offer a clinically-appropriate next step (transfer to nurse triage, schedule a visit, send a message to the clinical team through the patient portal). The boundary between "things the assistant handles" and "things the assistant defers to clinicians" is a clinical-safety document that the assistant enforces every turn, not a marketing description.

**Crisis detection is a hard requirement.** Among the calls a patient-facing assistant handles, a small but non-zero fraction will contain crisis signals: chest pain, shortness of breath, suicidal ideation, severe allergic reactions, signs of stroke, severe pain, drug overdose, suspected child or elder abuse. The assistant must recognize these signals reliably, override every other routing decision, and connect the caller to clinical triage or 988 or 911 immediately. The detection has to err strongly on the side of caution. The cost of a false positive (the patient who said "my chest hurt yesterday but it is fine now" gets routed to triage) is a brief patient inconvenience and a small operational cost. The cost of a false negative (the assistant routes the patient with active chest pain to "we will call you back about that") is a clinical-safety incident.

**The channel matters.** Phone-line audio is narrowband, prone to background noise, often comes from speakerphones in less-than-ideal acoustic environments, sometimes on cellular connections with packet loss. App-based audio is wideband, usually clearer, but the patient is often multitasking and may be in a noisier environment than they realize. Smart-speaker audio passes through a vendor pipeline that already does ASR and NLU before your code sees it; you are integrating with a vendor's voice platform rather than running your own. Each channel needs its own engineering investment, and the assistant has to behave consistently across them.

**Regulatory and compliance overlay.** A patient-facing voice system that handles refill requests is potentially making clinical-workflow decisions; the FDA has been clear that pure information retrieval is not a medical device, but the line moves when the assistant starts triaging or recommending. <!-- TODO: verify; FDA's positions on Software-as-a-Medical-Device for patient-facing automated systems continue to evolve, with guidance documents updated periodically --> HIPAA applies to every interaction that touches PHI, with the audio itself constituting PHI in addition to whatever the patient said in it. State-level recording-consent laws apply (more on this below). Telephone Consumer Protection Act (TCPA) considerations apply to outbound calls if the assistant is also used for outbound contact. The compliance review for a patient-facing voice assistant is more involved than for an IVR.

**Equity is a first-class concern, not an afterthought.** Voice ASR systematically underperforms for some speaker demographics. <!-- TODO: verify; multiple peer-reviewed studies including Koenecke et al. 2020 in PNAS have documented substantial accuracy disparities in commercial ASR systems across demographic groups --> An assistant that fails for older patients, patients with non-English first languages, patients with speech differences, or patients with regional accents has not just a usability problem but an equity problem, and the patients who are failed are often the ones who depend on the phone the most. Per-cohort accuracy monitoring is required from day one, with explicit thresholds that gate launch.

These properties combine to make the patient-facing voice assistant a recognizably distinct technology problem from the simpler voice recipes. The components are familiar; the system-level rigor is different.

### The Conversational Stack

Patient-facing voice assistants are built from a stack of pretty distinct technologies, and the architectural choices come from how they fit together.

**Streaming ASR.** Audio in, partial-and-final transcripts out. The same technology family as recipe 10.1, with the same telephony-versus-wideband tradeoffs and the same need for a model with reasonable medical-vocabulary coverage. Patient-facing assistants do not need full clinical-domain ASR (the patient is not dictating a clinical note), but they need enough medical-term coverage to handle the medication names and condition names that come up in the kind of calls they handle.

**Intent classification.** Mapping a transcript to one of a finite set of intents: "confirm appointment," "request refill," "facility hours," "billing inquiry," "request callback," "out-of-scope clinical question," "crisis signal," "transfer to agent," and however many others the institution chooses to support. Modern intent classification is increasingly LLM-driven (zero or few-shot prompting with a list of intents) rather than trained classifiers, because the LLM-driven approach handles paraphrase variation better and lets the institution add intents without retraining a model. The trade-off is per-call cost and latency. The hybrid pattern (small fast classifier as the first stage, LLM as the second-stage fallback for low-confidence cases) is a reasonable middle ground.

**Slot extraction.** Within an intent, extracting the structured parameters: the medication name for a refill, the date for an appointment confirmation, the billing-question topic. Comprehend Medical's coded entity extraction is useful here for medical entities (medications, conditions). For non-medical entities (dates, phone numbers, simple names), simpler tools are fine. The slot-extraction step is where the LLM-driven approach has been pulling significant weight in recent years; LLM extraction handles the long tail of how patients phrase things ("the blue pill I take for my pressure," "the one I started after my stroke") far better than rule-based or classifier-based extraction.

**Dialog management.** The turn-by-turn orchestration that decides what to say next. Slot-filling state machines, LLM-driven open dialog, or hybrid. Patient-facing healthcare overwhelmingly uses slot-filling state machines for the core fulfillment paths (confirm appointment, request refill, retrieve hours), with LLM augmentation for clarification and reformulation. The reasons are the same as in recipe 10.1: predictability, debuggability, compliance review, and the ability to certify that the system will not say something it should not say. Full LLM-driven dialog is more conversational and harder to constrain.

**Knowledge retrieval (RAG patterns).** For informational queries (facility hours, parking, what to bring to a visit, when to fast before a procedure), the assistant retrieves from a curated institutional knowledge base. The pattern is RAG: convert the patient's question into a retrieval query, fetch the relevant snippets from the institutional knowledge base, ground the LLM's response in the retrieved snippets, return the response. The institutional knowledge base must be curated, dated, and version-controlled; an out-of-date answer is sometimes worse than no answer (the patient who shows up at the lab at 6 pm because the knowledge base says it is open until 8 when it actually closed at 5 has a worse experience than the patient who was told "let me transfer you to someone who can confirm").

**Fulfillment integrations.** Once the assistant knows what the patient wants and has the slots filled, it executes the fulfillment. Appointment lookup against the EHR scheduling API. Refill request through the prescription-management workflow (which usually queues for clinical review rather than directly authorizing the refill). Knowledge-base lookup. Callback ticket creation. Warm transfer to a human agent with conversation summary. Each integration has its own API surface, its own authentication requirements, its own failure modes, and its own latency budget. The integrations are most of the engineering work in this recipe.

**Identity and authentication.** The architectural decision that touches every other component. The choices are roughly: knowledge-based authentication (date of birth plus a second factor, often a recent visit detail or a portion of the phone number on file), one-time-passcode (OTP) sent to the registered phone or email, voice biometrics (the system has a stored voiceprint and matches the live audio against it), portal-token-based (the patient logs in to the portal first, then dials and the call is correlated to the logged-in session through caller ID or a numeric token), and third-party identity verification services. Most institutions use a combination, with progressive identity strengthening (low-friction for low-stakes interactions, higher-friction for higher-stakes interactions like refills).

**Crisis detection.** A separate signal-extraction layer that runs in parallel with intent classification, looking for crisis phrases ("chest pain," "I can't breathe," "I want to die," "I overdosed," "my baby is not breathing"). Implementations range from a curated keyword list (high-recall, easy to audit) to a small dedicated classifier trained on labeled crisis utterances to LLM-driven detection with a structured output. The output of the detector is a hard interrupt: when crisis is detected, every other dialog state is preempted and the call is routed to clinical triage, 988, or 911 depending on the configured escalation. The detector errs strongly on the side of false positives.

**TTS for system speech.** The assistant's responses are spoken back to the caller through neural text-to-speech. Modern neural TTS (Polly's neural voices, ElevenLabs, vendor-specific offerings) is good enough that callers usually do not register that they are talking to a synthesized voice. Voice selection (one consistent voice per assistant identity), prosody (the cadence and emphasis of the response), and pronunciation (medication names, place names, the name of the institution) all matter for caller experience. Custom-pronunciation lexicons for clinical terms and institution-specific names are the high-leverage tuning step.

**Telephony plumbing.** The unglamorous but dominant piece of the engineering work for the phone channel. SIP trunking, contact center integration, call recording (with consent), warm-transfer protocols, presence and queue integration with the live-agent platform, the deeply boring work of getting audio into and out of the assistant in production telephony conditions.

**App and smart-speaker channels.** The non-phone channels have their own integration surfaces. The mobile app's voice assistant runs over a WebSocket-style audio channel and bypasses the telephony plumbing entirely. The smart-speaker integration uses the vendor's voice platform (Alexa Skill SDK, Google Actions on Google) which already does ASR and NLU before your code sees the request. Each has its own authentication model, its own latency characteristics, and its own constraints on what the assistant is allowed to say (Amazon's Alexa health-related skills have specific certification requirements, for example). <!-- TODO: verify; the certification requirements for healthcare-related Alexa skills and Google Actions continue to evolve, with both platforms maintaining specific guidelines for HIPAA-eligible deployments -->

**Audit and observability.** Every conversation produces a durable audit record: the audio reference, the transcript, the intent and slots, the fulfillment outcome, the identity-verification trail, the escalation decisions. Per-cohort accuracy monitoring (older speakers, non-native English, regional accents) requires the audit data to support cohort segmentation. Operational telemetry (intent-classification confidence distributions, dialog turn count distributions, escalation rates per intent) feeds the dashboards that operations and clinical-quality teams use.

### Identity Verification Over Voice

Identity verification deserves its own discussion because it is the first hard architectural decision and because most institutions get it wrong on the first pass.

The naive approach is to ask for date of birth and treat that as authentication. This is, on its own, weak. A motivated attacker can find a date of birth from a public source. A friend or family member often knows one. The collision rate within a large patient population is non-trivial (the probability that two different patients share a date of birth and a common-enough name is higher than you would think). Date of birth as a sole identity verification mechanism does not meet a reasonable bar for PHI access.

The better approach is a layered identity check that scales with the sensitivity of the requested action. For low-sensitivity interactions (looking up facility hours, confirming a publicly-known appointment time without disclosing the reason for the visit), no identity verification is required. For medium-sensitivity interactions (confirming a specific appointment that names the provider and reason), the system verifies the caller's identity through caller ID matching (the call came from a phone number on file for the patient) plus a date of birth or last-name confirmation. For high-sensitivity interactions (refill requests, test result inquiries, billing detail), the system requires stronger verification: a one-time passcode sent to the registered phone or email, or a portal-token-based correlation, or voice-biometric matching where deployed.

The institutional policy on identity verification is a clinical-and-compliance document that the assistant enforces. It is not an engineering preference. The chief privacy officer, the chief information security officer, and the clinical-operations leadership own the policy. The engineering team builds what they specify.

A few specific patterns worth knowing.

**Caller ID matching.** When the patient calls from the phone number on file, the institution can match the inbound caller ID against the patient registry as a soft identity signal. This is not authentication on its own (caller IDs can be spoofed), but it is a useful first signal that lets the assistant skip some friction for the calls where the signal matches. Patients calling from a different number (a friend's phone, a hospital phone, a hotel phone) get the higher-friction path. <!-- TODO: verify; caller-ID-based identification is a common pattern in healthcare voice systems but is not a strong authentication factor on its own, and FCC's STIR/SHAKEN framework continues to evolve in ways that affect the reliability of caller ID -->

**One-time passcode by SMS or email.** The patient asks for a refill; the assistant says "I will send a passcode to the phone on file ending in 1234, please read it back." The patient receives the passcode and reads it. The assistant verifies and proceeds. This is operationally simple, well-understood by patients, and provides reasonable additional assurance. The friction is meaningful but acceptable for higher-stakes transactions.

**Portal-token correlation.** The patient logs in to the portal, navigates to "talk to us by voice," gets a numeric token, calls the assistant, and reads the token. The assistant correlates the token to the logged-in portal session. Strong authentication, low call-side friction, but requires the patient to be portal-enrolled and to navigate to the right place. Useful for the patient population that uses the portal anyway.

**Voice biometrics.** A passive or active voiceprint match. Active: the patient says a specific passphrase ("My voice is my password") and the system matches against a stored voiceprint. Passive: the system matches against the natural speech of the conversation as it proceeds. The technology works reasonably well for the speakers in the population whose voices are well-represented in the training data. It works less well for speakers whose voices change (illness, age progression, cognitive change), for speakers whose voices are underrepresented in training data, and for the case of the family caregiver calling on behalf of the patient. Voice biometrics also raises the biometric-data-governance question: storing voiceprints implicates BIPA in Illinois, GIPA in Texas, and similar state laws, with explicit consent and disclosure requirements. <!-- TODO: verify; the Illinois Biometric Information Privacy Act and similar state laws impose specific consent and disclosure requirements for biometric identifiers including voiceprints, with case law continuing to develop -->

**Family caregiver and HIPAA proxy.** The institution often has an authorized caregiver designation on file (the patient has authorized their adult daughter to receive PHI on their behalf). The assistant must support these proxy relationships: the caregiver authenticates as themselves, the assistant looks up which patients the caregiver is authorized to act for, the conversation proceeds in the patient's record. The proxy designation is a structured field in the EHR; the assistant integrates with whatever the institution uses to store it.

<!-- TODO (TechWriter): Expert review S1 (HIGH). Promote caregiver-self-authentication into a distinct architectural flow rather than the current post-hoc resolution. The Step 4 pseudocode currently sends the OTP to the patient's registered destination and resolves caregiver context after successful OTP verification, which fails the boundary in the common scenario where a caregiver answers the patient's phone and reads back the OTP that was meant to authenticate the patient. Specify two distinct flows: (1) capture caller role (self or caregiver) before identity verification begins; (2) caregiver flow authenticates the caregiver with their own credential, captures and verifies the target patient, looks up the caregiver-patient authorization in the institutional registry, and only then proceeds; (3) audit trail records authenticated_party explicitly. Reference institutional caregiver-enrollment substrate as prerequisite. -->

**Step-up authentication.** A common pattern: the conversation starts at a low identity-assurance level and the assistant requests additional verification when the conversation enters higher-stakes territory. The patient calls about appointment hours (no auth), then asks about their specific appointment (caller ID match plus date of birth), then asks about a refill (OTP step-up). Each step-up adds friction; the architecture makes the friction proportional to the stakes.

**Bypass and emergency override for crisis.** When crisis is detected, identity verification is overridden. The patient who calls in crisis must not be blocked by an authentication failure. Route to triage or 988 first; sort out identity later if needed.

### Scope Containment

The single most under-engineered aspect of patient-facing voice assistants in production is scope containment. The assistant has a defined set of things it handles. Everything else, it should refuse, defer, or escalate. Getting this right is harder than the engineering teams expect, because the patients do not know what is in scope and out of scope, and the LLM components in the stack are inherently disposed to attempt answers to questions they should not be answering.

A few scope-containment patterns that work.

**Explicit out-of-scope refusal.** When the assistant's intent classifier returns "out-of-scope clinical question" or "out-of-scope financial advice" or "out-of-scope legal question," the assistant says so. "I cannot help with clinical questions, but I can transfer you to our nurse triage line. Would you like me to do that?" The refusal is explicit, the alternative is concrete, the patient knows what to do next.

**LLM constraint by system prompt and structured output.** When the intent fulfillment uses an LLM (for response generation, for retrieval-augmented answering of informational questions), the system prompt explicitly defines the scope: "you answer only questions about hours of operation, parking, what to bring, and what to expect. For any clinical question, refuse and offer a transfer to nurse triage. For any financial-advice question, refuse and offer a transfer to billing. Do not provide medication advice, dosing information, symptom interpretation, or any clinical recommendation under any circumstances." The structured output schema requires the LLM to declare whether the response is in-scope; out-of-scope responses are filtered before being spoken back to the patient.

**Allowlist for clinical-information disclosure.** The assistant can confirm that a patient has an appointment with Dr. Smith on Tuesday at 2:30. It cannot tell the patient what the appointment is for in clinical terms (cancer follow-up vs. wellness check) without higher identity assurance. The information disclosure rules are encoded in the assistant's response generation and enforced as a structured filter.

**Continuous scope-drift monitoring.** Periodically, the operations team samples conversations and reviews them for scope drift: did the assistant answer something it should have refused? Did it provide clinical advice? Did it interpret a symptom? The findings feed prompt-and-rule updates. This is operational scope, not engineering scope, but the engineering team has to support the sampling and review tooling.

**The "I don't know" path.** When the assistant is uncertain whether a question is in scope, the safer response is "I'm not sure I can help with that, let me connect you with someone who can." The assistant errs toward escalation, not toward a confidently wrong answer. The escalation rate is a key operational metric and the institutional team tunes it explicitly.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Promote the scope filter into a layered architectural primitive with named ownership, rather than a single opaque check. Specify three explicit layers: (1) a disallowed-content category catalog (clinical advice, medication dosing, symptom interpretation, prognosis discussion, financial advice, legal advice, others institution-defined) owned by the clinical-quality officer with quarterly review cadence; (2) a per-intent allowed-content allowlist (an "appointment confirmation" intent's allowed responses are constrained differently from a "facility info" intent's) owned by the patient-experience lead; (3) Bedrock Guardrails configuration covering vendor-managed harmful-content plus institutional restricted-topic categories, with both leads named for change-management. Specify which layer runs first, what each is responsible for, how the audit trail records which layer caught a violation, and how findings from offline scope-drift review feed back into the runtime filter. The recipe's own self-assessment names scope containment as "the single most under-engineered aspect"; the architecture should match that elevation. -->

### Crisis Detection

Crisis detection deserves its own treatment because it is the highest-stakes flow in the assistant.

The detector runs in parallel with intent classification and on every patient utterance. It is not gated on the conversation having reached a particular state; the patient who calls about an appointment and mentions chest pain three turns in must be detected at that turn, not when the conversation ends.

The detector's outputs are tiered by severity and by category:

**Acute medical emergencies.** Chest pain, shortness of breath, signs of stroke (facial droop, slurred speech, sudden weakness), severe allergic reactions, severe bleeding, suspected overdose, infant or child not breathing. Disposition: bypass everything else and route to 911 messaging plus immediate transfer to clinical triage if available.

**Suicidal or homicidal ideation.** Active expressions of intent to harm self or others. Disposition: bypass everything else and route to 988 (or the institution's behavioral-health crisis line) plus immediate transfer to crisis counseling if available. The system disclaims that it is not a crisis counselor and that 988 is the right resource.

**Suspected abuse or neglect.** Statements suggesting child, elder, or partner abuse. Disposition: route to a designated escalation pathway per the institution's child-protection or adult-protective-services protocol. This is institution-specific and clinically governed.

**Urgent but not immediately-emergent symptoms.** Severe pain, prolonged fever, severe headache, new severe symptoms. Disposition: route to clinical triage with a flagged-urgent note. This is the band where the assistant errs strongly on the side of caution.

The detector is implemented as a layered combination of: a curated keyword list for the most unambiguous signals (high recall, easy to audit, version-controlled by the clinical-quality team); a small classifier for paraphrase variation; an LLM-driven detector for the more subtle cases. The output of the detection is reviewed and audited per institutional policy. False-negative cases are treated as clinical-quality incidents and reviewed individually.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote per-language crisis-detection structure into the architecture pattern rather than leaving it implicit. Specify: per-language curated vocabulary list (clinically governed, version-controlled by clinical-quality team with native-speaker clinical input); per-language classifier configuration; per-language LLM-prompt; per-language detection-rate monitoring with launch gates per language; per-language false-negative review with native-speaker clinical reviewer. Languages without native-speaker-curated detection assets should route directly to human agents (over-escalation in an unsupported language is the architecturally-correct conservative default). The recipe correctly elevates multilingual-from-day-one as required and crisis detection as the highest-stakes flow; the architecture pattern needs to make per-language crisis coverage as concrete as the English path. -->

The detection list is a clinical-safety document, not an engineering configuration. The clinical-quality officer or equivalent role owns it. The engineering team implements it. Changes go through clinical review.

### Where the Field Has Moved

Some practical updates worth knowing.

**LLM-driven intent and dialog has reset the bar.** Patient-facing voice assistants in 2020 used trained intent classifiers and rigid slot-filling state machines. Modern assistants use LLM-driven intent classification (with structured output), LLM-driven slot extraction (handling the long tail of patient phrasing), and LLM-augmented dialog (with rule-based scaffolding for compliance and predictability). The improvement in caller experience is substantial. The improvement in build effort is also substantial: institutions launching today typically reach a usable assistant in months rather than the year-plus that the previous-generation toolchain required.

**RAG patterns have eaten the FAQ chatbot.** The institutional FAQ used to be a curated list of question-answer pairs that the chatbot or assistant matched against. Today the institutional knowledge base is unstructured documents (operations procedures, facility information, what-to-expect content), retrieved at query time, with the LLM grounding its response in the retrieved passages. The maintenance burden has shifted from "keep the Q&A pairs current" to "keep the source documents current," which is usually easier because the source documents already exist and are owned by the teams that produce them.

**Smart-speaker integration has matured but stayed niche.** Alexa skills and Google Actions for healthcare have grown more capable and more compliance-friendly, but the absolute volume of patient interactions through smart speakers remains small compared to phone and app. Smart speakers are a genuine accessibility win for some patients (older patients with vision impairment, patients with mobility challenges) but the institutional engineering investment is usually disproportionate to the volume served. The pattern is to ship smart-speaker integration as a deliberate equity and brand investment, not as a primary volume channel.

**Telephony has become more cloud-native.** Cloud contact-center platforms (Amazon Connect, Genesys Cloud, Twilio Flex, Five9, Cisco Webex Contact Center, NICE CXone) have absorbed a lot of the telephony plumbing that used to be on-premise. The patient-facing assistant integrates with the cloud contact-center platform rather than with raw SIP infrastructure. The integration is meaningfully simpler than it used to be, though it is still meaningfully more work than people anticipate.

**Voice biometrics has plateaued.** The technology works well enough to be useful as a step-up factor for specific cohorts, but the operational complexity (enrollment, re-enrollment when voices change, the biometric-data-governance overhead, the demographic accuracy variation) means most institutions have settled on knowledge-based authentication plus OTP as the default and have positioned voice biometrics as an opt-in feature for specific high-volume callers.

**Multilingual deployment has moved from optional to expected.** Patient populations are linguistically diverse in most U.S. healthcare markets. The assistant deployed today must be multilingual at launch or have a clear roadmap to multilingual support. English-only assistants in markets with significant non-English-speaking populations are increasingly seen as an equity gap rather than a phase-one acceptable scope.

**The build-versus-buy economics favor buy for most institutions.** Commercial vendors (Hyro, Notable, Conversa, several others) offer institutional patient-facing voice assistants that integrate with major EHRs and contact-center platforms. <!-- TODO: verify; the patient-facing voice assistant vendor landscape has been growing and consolidating since approximately 2021, with specific vendor names and capabilities continuing to evolve --> For most institutions, the buy path is faster, comes with EHR integration already built, and offloads the ongoing model and prompt maintenance. The build path is reserved for institutions with unusual scope requirements, with research interests in the technology itself, or with very large call volumes where the per-call economics tip in favor of in-house operation. The recipe walks through what the architecture looks like either way.

---

## General Architecture Pattern

A patient-facing voice assistant decomposes into nine logical stages: channel entry and audio capture (the patient connects via phone, app, or smart speaker), streaming ASR (audio becomes text), parallel crisis detection (the highest-priority signal extraction), intent classification and slot extraction (mapping speech to a structured request), identity verification (gating PHI access at the level the request requires), fulfillment (executing the request through the appropriate integration), response generation and TTS (the assistant's reply is composed and spoken back), escalation and warm handoff (when the assistant cannot or should not handle the request), and audit, archive, and learning (durable record-keeping and per-cohort accuracy monitoring).

```
┌──────────── CHANNEL ENTRY & AUDIO CAPTURE ───────────────┐
│                                                           │
│   [Patient connects through one of three channels]        │
│    - Telephony: SIP trunk -> contact center platform      │
│    - Mobile app: WebSocket audio -> backend               │
│    - Smart speaker: Alexa skill / Google Action           │
│                                                           │
│   [Recording-consent disclosure played first]             │
│    - State-law-aware: all-party-consent jurisdictions     │
│      hear an explicit recording disclosure                │
│    - One-party-consent jurisdictions hear at minimum      │
│      a notice that the call may be recorded for QA        │
│                                                           │
│   [Caller ID and channel metadata captured]               │
│    - Used as a soft identity signal downstream            │
│           │                                               │
│           ▼                                               │
│   [Output: audio stream, channel type, caller-ID hint]    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── STREAMING ASR ───────────────────────────────┐
│                                                           │
│   [Speech recognition with telephony-tuned model]         │
│    - Custom vocabulary biasing (institutional formulary,  │
│      facility names, provider names)                      │
│    - Per-language configuration (English, Spanish, etc.)  │
│                                                           │
│   [Streaming partials emit progressively]                 │
│    - Downstream consumes the latest partial for low-      │
│      latency intent and crisis classification             │
│   [Final transcripts emit on end-of-utterance]            │
│   [Per-word and per-utterance confidence scores]          │
│           │                                               │
│           ▼                                               │
│   [Output: rolling transcript stream with confidence]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── PARALLEL CRISIS DETECTION ───────────────────┐
│                                                           │
│   [Crisis detector runs on every utterance]               │
│    - Curated keyword list (highest-recall, audited)       │
│    - Small classifier for paraphrase variation            │
│    - LLM detector for subtle cases                        │
│                                                           │
│   [Severity-tier classification]                          │
│    - Acute medical emergency -> 911 + clinical triage     │
│    - Suicidal/homicidal ideation -> 988 + crisis triage   │
│    - Suspected abuse -> protective-services pathway       │
│    - Urgent symptoms -> nurse triage urgent               │
│                                                           │
│   [Hard interrupt on detection]                           │
│    - Preempts every other dialog state                    │
│    - Identity verification bypassed for crisis routing    │
│           │                                               │
│           ▼                                               │
│   [Output (when triggered): crisis disposition that       │
│    overrides the rest of the pipeline]                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── INTENT CLASSIFICATION & SLOT EXTRACTION ─────┐
│                                                           │
│   [Map utterance to structured intent]                    │
│    - LLM-driven classification with structured output     │
│    - Confidence threshold gate                            │
│    - Out-of-scope intents have explicit handlers          │
│                                                           │
│   [Extract slots within the intent]                       │
│    - Medication name (with RxNorm linking via             │
│      Comprehend Medical for refill intents)               │
│    - Date and time (for appointment intents)              │
│    - Provider name (for appointment intents)              │
│    - Location (for facility-info intents)                 │
│                                                           │
│   [Multi-turn slot completion]                            │
│    - Missing required slots trigger clarifying prompts    │
│    - Repeated low-confidence on the same slot triggers    │
│      an escalation timer                                  │
│           │                                               │
│           ▼                                               │
│   [Output: { intent, slots, confidence, turn_count }]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── IDENTITY VERIFICATION ───────────────────────┐
│                                                           │
│   [Identity-assurance level required by intent]           │
│    - Public information (hours, location): no auth        │
│    - Soft-personal (appointment confirmation): caller     │
│      ID match + DOB                                       │
│    - PHI-disclosing (refill, results): step-up auth       │
│      via OTP, portal token, or voice biometric            │
│                                                           │
│   [Step-up authentication when intent escalates]          │
│    - Conversation may begin at low assurance and          │
│      step up when the patient asks for something          │
│      higher-stakes                                        │
│                                                           │
│   [Caregiver-proxy resolution]                            │
│    - Caregiver identifies as themselves                   │
│    - System looks up authorized patient relationships     │
│    - Conversation proceeds in the named patient's record  │
│                                                           │
│   [Auth failure handling]                                 │
│    - Configured retry budget                              │
│    - Failure escalates to live agent rather than          │
│      blocking the patient                                 │
│           │                                               │
│           ▼                                               │
│   [Output: identity-assurance level granted, patient ID,  │
│    caregiver context if applicable]                       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── FULFILLMENT ─────────────────────────────────┐
│                                                           │
│   [Route the intent to the appropriate fulfillment]       │
│                                                           │
│   - Appointment lookup -> EHR scheduling API              │
│   - Refill request -> pharmacy workflow with clinical     │
│     review queue (most institutions do not auto-          │
│     authorize refills)                                    │
│   - Facility info -> RAG over knowledge base              │
│   - Billing inquiry -> billing-system lookup or           │
│     callback ticket creation                              │
│   - Test results -> portal-message creation if            │
│     institutional policy allows; otherwise transfer       │
│   - Out-of-scope -> explicit refusal with concrete        │
│     alternative offered                                   │
│                                                           │
│   [Each fulfillment captures source span and provenance]  │
│    - The eventual response cites where the answer         │
│      came from in the audit trail                         │
│                                                           │
│   [Failure modes have defined fallbacks]                  │
│    - EHR API down: callback ticket created, patient       │
│      told the institution will get back to them           │
│    - Knowledge base outdated: defer to live agent         │
│    - Pharmacy system unreachable: callback ticket         │
│           │                                               │
│           ▼                                               │
│   [Output: fulfillment result, source provenance,         │
│    confidence in the answer]                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── RESPONSE GENERATION & TTS ───────────────────┐
│                                                           │
│   [Compose the spoken response]                           │
│    - Templated for high-stakes responses (appointment     │
│      confirmation, refill submitted, identity verified)   │
│    - LLM-grounded for informational responses (RAG        │
│      output formatted as natural conversational reply)    │
│                                                           │
│   [Scope filter on every generated response]              │
│    - LLM output checked against allowed-content rules     │
│    - Out-of-scope content replaced with an explicit       │
│      refusal-and-transfer prompt                          │
│                                                           │
│   [TTS rendering]                                         │
│    - Neural TTS with consistent voice persona             │
│    - Custom-pronunciation lexicon for clinical terms,     │
│      medications, provider names, facility names          │
│    - Per-language voice selection                         │
│                                                           │
│   [Barge-in handling]                                     │
│    - Patient interrupts mid-prompt: ASR resumes,          │
│      response is interrupted, dialog continues            │
│           │                                               │
│           ▼                                               │
│   [Output: synthesized audio sent back through the        │
│    channel]                                               │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── ESCALATION & WARM HANDOFF ───────────────────┐
│                                                           │
│   [Triggers for escalation]                               │
│    - Crisis detection (hard, immediate)                   │
│    - Out-of-scope intent (soft, with confirmation)        │
│    - Repeated low confidence in slot capture              │
│    - Repeated identity-verification failure               │
│    - Patient explicitly requests a human                  │
│    - Fulfillment system unavailable                       │
│                                                           │
│   [Warm-handoff packet built]                             │
│    - Conversation summary                                 │
│    - Transcript reference                                 │
│    - Identity-verification status                         │
│    - Detected intent and slots so far                     │
│    - Crisis-detection flags if applicable                 │
│    - Patient's caller ID and channel                      │
│                                                           │
│   [Transfer to live agent or crisis line]                 │
│    - Agent receives the warm-handoff packet on screen     │
│      before they answer                                   │
│    - Patient does not have to repeat what they already    │
│      told the assistant                                   │
│           │                                               │
│           ▼                                               │
│   [Output: handoff complete, audit record updated,        │
│    conversation lifecycle event emitted]                  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── AUDIT, ARCHIVE & LEARNING ───────────────────┐
│                                                           │
│   [Durable conversation record]                           │
│    - Audio reference (under retention policy)             │
│    - Transcript (with confidence)                         │
│    - Intent and slots                                     │
│    - Identity-verification trail                          │
│    - Fulfillment outcome                                  │
│    - Escalation events                                    │
│    - Channel and caller ID metadata                       │
│                                                           │
│   [Cohort-stratified accuracy monitoring]                 │
│    - Per-language, per-age-band (where opt-in declared),  │
│      per-channel, per-region                              │
│    - Disparity alerts on configured thresholds            │
│                                                           │
│   [Operational telemetry]                                 │
│    - Containment rate (intents fulfilled in self-service) │
│    - Escalation rate per intent                           │
│    - Crisis-detection rate and review outcomes            │
│    - Identity-verification success rate per assurance     │
│      level                                                │
│    - Per-channel AHT (average handle time)                │
│                                                           │
│   [Sampled review for scope drift]                        │
│    - Operations samples conversations periodically        │
│    - Findings feed prompt and rule updates                │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals]      │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points the architecture has to bake in.

**Audio is PHI even when nothing clinical is said.** A patient calling about an appointment is identifying themselves as a patient of the institution; the audio is PHI by virtue of the patient-institution association alone. The architecture treats audio as PHI throughout: encrypted at rest, encrypted in transit, access-controlled, retention bound by an explicit policy, BAAs in place for any vendor service that processes the audio.

**Recording-consent law varies by jurisdiction.** All-party-consent states require an explicit consent disclosure before recording begins; one-party-consent states require less but most institutions still play a "this call may be recorded for quality" notice. The disclosure is the first thing the caller hears. The architecture implements it as a per-call gate that runs before audio is committed to durable storage. Cross-state callers (the caller is in California, the institution is in Texas) follow the stricter of the two regimes. <!-- TODO: verify; the United States has approximately 12 all-party-consent states with the rest one-party-consent, and HIPAA layers on additional clinical-recording requirements regardless of state law -->

**Crisis detection runs in parallel with everything else.** It is not a stage that comes after intent classification; it runs simultaneously and can preempt at any point in the conversation. The architecture wires it as a parallel pass over every utterance with a hard-interrupt callback into the dialog manager.

**Identity verification is separable from intent.** The same intent ("look up my appointment") can be served at different identity-assurance levels depending on how much information the patient asks the system to disclose. The architecture decouples the intent from the assurance requirement and handles step-up dynamically.

**Fulfillment integrations have separate failure budgets.** When the EHR scheduling API is down, appointment-confirmation intents fail; everything else continues. The architecture isolates the integrations so one failed dependency does not take the whole assistant down.

**Channels are entry points; the conversation logic is shared.** The phone-line and app-based and smart-speaker channels share the intent classifier, the dialog manager, the fulfillment integrations, and the audit pipeline. The channels differ at the edges (audio capture, response delivery, identity hints from caller ID or device authentication) and converge into a common conversation runtime.

**The escalation rate is a feature, not a bug.** Some intents should always escalate (out-of-scope clinical, complex billing, anything in the urgency band). The architecture tracks escalation rate as a telemetry metric and the operational dashboard shows it broken out by intent. A drop in escalation rate is not necessarily a win; it might mean the assistant is handling things it should not be handling.

**Audit retention has to span the legal record's lifetime.** The conversation record is, in many regulatory readings, part of the medical record. Retention is sized to HIPAA's six-year minimum, the state's medical-records-retention floor, the contact-center vendor's audit-retention floor, and the institutional regulatory floor. <!-- TODO: verify; HIPAA requires a six-year minimum retention for relevant records, with state-specific medical-records-retention rules layering on top, and the precise applicability to voice-assistant audit records is institution-specific -->

**Failure has to degrade to a live human, not to a dead end.** When the assistant cannot do its job (ASR is down, NLU is down, the patient is profoundly outside the assistant's competence), the fallback is always "let me connect you to someone." Never "we cannot help you, please call back." Patients who reach a dead end on their first attempt do not call back; they go to the ER, or they leave the practice, or they file a complaint.

**Equity monitoring is non-negotiable.** Per-cohort accuracy and containment-rate metrics are a launch gate, not an optional dashboard. The institution decides what cohorts to track (per-language, per-age-band, per-region, per-channel) and what disparity thresholds trigger alerts; the architecture supports the segmentation in the audit pipeline.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter10.05-architecture). The Python example is linked from there.

## The Honest Take

The patient-facing voice assistant is the recipe in this chapter where the technology is genuinely ready, the operational complexity is genuinely manageable, and the failure modes are genuinely visible. It is also the recipe where institutions most often ship a mediocre product because they treated voice as a technology project instead of as a patient-experience project. The technology is necessary but not sufficient. The patient experience is the thing that determines whether the assistant succeeds.

The first trap is launching with too narrow a scope. An assistant that only confirms appointments, when patients call about ten different things, is barely worth deploying. The intent vocabulary needs to cover enough of the inbound call mix that meaningful containment is possible. The right starting scope is something like: appointment confirmation and rescheduling, refill requests with clinical-review queueing, facility information through RAG over a curated knowledge base, callback ticket creation for everything else, warm transfer with conversation context for anything the assistant cannot or should not handle, and crisis detection across all of it. That is roughly the minimum viable scope for a deployment that actually moves the operational metrics. Anything narrower is a pilot.

The second trap is launching with too broad a scope. An assistant that tries to answer clinical questions, recommend whether the patient should go to the ER, interpret symptoms, or provide medication advice is not a patient-facing voice assistant; it is a malpractice incident waiting to happen. The scope-containment work is the most important operational discipline in this recipe. The LLM components in the stack are inherently disposed to attempt answers to questions they should not answer; the scope filter, the explicit out-of-scope intent handlers, the system-prompt constraints, and the offline scope-drift review program are the layered defenses. Underweighting any of them produces a system that occasionally says something dangerous, which is worse than a system that occasionally fails to say something useful.

The third trap is underweighting the crisis-detection work. Crisis detection is the smallest fraction of the assistant's traffic and the highest-stakes part of its behavior. A false-negative crisis detection (the patient who said they were thinking about suicide and got routed to "we will call you back about that") is an unrecoverable patient-safety incident. The detection vocabulary, the severity tiering, the escalation pathways, the multilingual coverage, the false-negative review program, all deserve disproportionate attention relative to their fraction of traffic. The clinical-quality officer owns this; the engineering team implements it; the operational metrics are reviewed monthly.

The fourth trap is underweighting the equity-monitoring work. Voice ASR has well-documented accuracy disparities across speaker demographics, and the patients who depend most on the phone channel are disproportionately the ones the ASR underperforms for. Per-cohort accuracy and containment metrics are not optional analytics; they are the mechanism by which the institution detects whether the assistant is silently underserving specific patient populations. The cohort axes (per-language, per-channel, per-region, per-age-band where opt-in declared) are policy-level decisions made with the equity-monitoring committee. The launch gate (every cohort must meet the minimum threshold, not just the institution-wide average) is non-negotiable. The institutions that take equity seriously discover and remediate disparities before they become PR incidents or regulatory matters; the institutions that treat equity monitoring as a checkbox discover problems through complaints.

The fifth trap is over-friction-loading the identity verification. The patient who has to recite their date of birth, then read back a six-digit code, then confirm their last visit's copay, then verify a security question, before the assistant will tell them whether their appointment is on Tuesday or Wednesday, has a worse experience than they had with the original phone tree. The policy needs to scale friction with stakes: anonymous lookup of public information requires no friction, soft-personal information confirmation requires light friction (caller ID match plus DOB), PHI disclosure requires real friction (OTP step-up). The friction at each level should be proportional and intentional, not the security team's worst-case thinking applied uniformly to every interaction.

The sixth trap is treating the knowledge base as a one-time build. The institutional knowledge base is an operational asset that decays without continuous maintenance. The lab hours change for holidays, the parking structure changes for construction, the visitor policy changes during flu season, the COVID protocols change every few months in some institutions. An out-of-date knowledge-base answer is sometimes worse than no answer. The content lifecycle (who owns each piece, what the review cadence is, how staleness is detected, when content is auto-deferred to humans) is real operational work, and it has to be staffed.

The seventh trap is shipping all three channels at the same time. The phone channel is where most of the volume is and where the equity story is strongest. The app channel is where the engineering is easiest. The smart-speaker channel is where the brand and patient-delight wins are visible but the volume is small. Most institutions ship better outcomes by sequencing: phone first, app second, smart speaker third (if at all). Shipping all three simultaneously stretches the engineering and operational team across three different integrations during the riskiest phase of deployment.

The eighth trap is assuming the LLM components are oracles. The LLM-driven intent classification handles paraphrase variation gracefully but occasionally misclassifies; the LLM-driven response generation produces conversational replies but occasionally drifts out of scope; the LLM-driven slot extraction handles long-tail patient phrasing but occasionally extracts something the patient did not say. The LLM components are useful precisely because they are flexible, and that flexibility is the source of their failure modes. The architecture treats them as drafting partners with mandatory human oversight, not as authoritative components. The structured-output validation, the scope-filter pass, the confidence thresholds for auto-fulfillment, the offline review program, all serve this discipline.

The thing that surprises engineers coming from consumer-voice-assistant backgrounds is how much of the engineering value is in the unglamorous pieces. The telephony plumbing, the warm-transfer integration, the OTP delivery, the EHR API integration, the knowledge-base content lifecycle. The conversational AI is interesting; the system that gets the call to the right place reliably and gets the answer back to the patient through the right channel is what determines whether the project ships.

The thing that surprises engineers coming from clinical-software backgrounds is how much of the patient-experience work is in the prompts and the persona. The voice selection. The response phrasing. The cadence. The empathetic phrasing for difficult moments ("I understand. Let me get you to someone who can help with that"). The patient-experience team's investment in the prompts and the persona is the difference between an assistant patients tolerate and an assistant patients prefer. This is harder to measure than ASR accuracy, and it matters more than ASR accuracy for many patient interactions.

The thing about Amazon Connect specifically: it absorbs an enormous amount of telephony plumbing that institutions used to spend years building. SIP, recording, queue management, agent desktop integration, warm-transfer protocols, Lex integration, all bundled. The trade-off is vendor lock-in (your contact-center configuration is in Connect's format) and ongoing per-minute pricing. For most institutions deploying a patient-facing voice assistant, the lock-in cost is worth the time saved.

The thing about Amazon Lex specifically: Lex V2 is the conversational scaffold that handles the boring-but-essential parts of dialog management (slot filling, multi-turn state, confirmation prompts) without requiring a custom dialog manager. The trade-off is that Lex's flexibility is bounded; complex dialog patterns that require LLM-driven open-ended interaction sit outside Lex's sweet spot and require Lambda-driven extensions. For the core fulfillment paths in this recipe, Lex is the right tool. For the LLM-augmented paths (intent fallback, RAG-grounded informational responses), the architecture extends Lex with Lambdas that call Bedrock.

The thing about Amazon Bedrock specifically: the LLM-augmented intent classification and RAG-grounded response generation are genuinely valuable. The faithfulness caveat from recipe 10.4 applies: the response generation must stay within scope, and the scope filter is the boundary that enforces this. Bedrock Guardrails adds a defense-in-depth layer for harmful or restricted content. Choose a model with healthcare instruction tuning where available; validate against held-out conversations; treat the model as a drafting partner with mandatory scope-filter oversight.

The thing about identity verification: this is the area where the recipe's "production gaps" list is longest, and the area where most institutions get it wrong on the first pass. The OTP step-up is the right default for PHI-disclosing intents in 2026, but it has friction. The voice-biometric path is operationally complex and demographically uneven. The portal-token correlation is elegant for portal-enrolled patients but useless for patients who are not. The architecture has to accept that no single identity-verification path serves every patient well, and the policy has to layer methods to cover the patient population.

The thing about scope containment: this is where the recipe's safety story lives. The boundary between "things the assistant handles" and "things the assistant defers to clinicians" is a clinical-safety document. The institutional team that takes this seriously documents the boundary explicitly, reviews it quarterly, and treats scope-violation incidents as clinical-quality events. The institutional team that treats scope as an engineering preference ships an assistant that occasionally provides clinical advice it should not be providing, and discovers this through a complaint.

The thing about crisis detection: this is the highest-stakes flow and the smallest-traffic flow. The detection vocabulary is a clinical-safety document owned by the clinical-quality officer. The false-negative review program is mandatory. The multilingual crisis vocabulary requires native-speaker clinical input. The escalation pathway (911, 988, nurse triage, protective services) is institution-specific and clinically governed. None of this is engineering scope, and all of it needs engineering support.

The thing about per-cohort equity monitoring: the institutions that build it as a launch gate ship more equitable products than the institutions that build it as a post-launch dashboard. The discipline of refusing to launch a cohort whose accuracy or containment metrics are below the threshold forces the engineering team to invest in the cohort-specific issues (accent coverage, language-specific intent vocabulary, age-band-specific friction tuning) rather than launching with the average looking fine.

The thing I would do differently the second time: invest more, earlier, in the patient-experience pass on the prompts and persona. Every successful patient-facing voice assistant deployment I have seen has had a patient-experience or content-design lead who owned the conversational language and the persona. The deployments without that lead consistently feel robotic, awkward, or off-tone. The technology floor is similar; the patient-experience floor is wildly different.

The last thing, because it is the easiest one to get wrong: a patient-facing voice assistant is a front door to the institution. Everything that is hard about the institution as a whole (the EHR integration, the operational complexity, the staff-time constraints, the equity gaps in care delivery) shows up in the assistant. The assistant is not a way to paper over institutional shortcomings; it is a way to expose them at the patient interface. The institutions that succeed treat the assistant as a partnership between the contact center, the clinical operations team, the patient-experience team, the IT team, and the compliance team, with each team owning its piece. The institutions that try to ship the assistant as an IT project alone produce something that technically works and operationally underperforms.

The patient-facing voice assistant is the recipe in this chapter where the operational impact is the largest, the patient-experience improvement is the most visible, and the technology is the most production-ready. It is also the recipe where the institutional discipline matters most. Build it carefully. Ship it incrementally. Monitor it rigorously. The patients who depend on the phone channel are exactly the patients who deserve the institutional investment that makes the assistant work for them.

---

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, the simpler analog of the patient-facing voice assistant. Recipe 10.1 routes calls based on intent; recipe 10.5 fulfills calls based on intent. The technology stack is shared; the scope of fulfillment is different. Many institutions deploy 10.1 first as a capability investment, then build 10.5 on top of the operational muscles 10.1 created.
- **Recipe 10.2 (Voicemail Transcription and Classification):** Same chapter, the asynchronous analog. Patients who leave voicemails when the assistant is unavailable (or when they prefer asynchronous) are handled by 10.2. The cross-recipe handoff (the assistant defers to leaving a message; the message classification routes the message to the right team) is an emerging integration pattern.
- **Recipe 10.4 (Medical Transcription / Dictation):** Same chapter, the clinician-facing voice analog. Recipe 10.4 is dictation by clinicians; recipe 10.5 is conversation with patients. The ASR considerations differ (single-speaker dictation vs. patient conversation); the LLM considerations are similar (faithfulness, scope, structured output validation).
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Same chapter, the multi-speaker patient-and-clinician analog. The diarization concern (who said what) is shared with the caregiver-proxy patterns in this recipe.
- **Recipe 10.10 (Multilingual Real-Time Medical Interpretation):** Same chapter, the related multilingual analog. The per-language work in this recipe shares engineering patterns with 10.10's translation pipeline.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2, LLM-driven summarization. The conversation-summary-for-warm-handoff pattern in this recipe uses similar techniques on a smaller scale.
- **Recipe 2.1 (Patient Message Response Drafting):** Chapter 2, LLM-drafted responses to patient messages. The scope-containment patterns in this recipe map closely onto the message-response-drafting patterns in 2.1, since both are patient-facing LLM-driven interactions with the same scope discipline requirements.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** Chapter 11 covers the broader conversational-AI patterns; this recipe is the voice-and-telephony specialization of that pattern.
- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Chapter 4, personalization of outbound reminders. The outbound-proactive-voice extension above draws from this pattern.

---

## Tags

`speech-voice-ai` · `patient-facing` · `voice-assistant` · `conversational-ai` · `patient-engagement` · `contact-center` · `telephony` · `mobile-app` · `smart-speaker` · `multi-channel` · `intent-classification` · `slot-filling` · `dialog-management` · `rag-pattern` · `knowledge-base` · `identity-verification` · `otp-step-up` · `caregiver-proxy` · `crisis-detection` · `scope-containment` · `warm-handoff` · `equity-monitoring` · `cohort-stratified-accuracy` · `multilingual` · `recording-consent` · `tcpa` · `bipa` · `accessibility` · `older-patients` · `connect` · `lex` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `comprehend-medical` · `transcribe` · `polly` · `pinpoint` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `medium` · `production-track` · `hipaa` · `phi-handling` · `audit-trail` · `containment-rate` · `escalation-rate`

---

*← [Recipe 10.4: Medical Transcription (Dictation)](chapter10.04-medical-transcription-dictation) · [Chapter 10 Index](chapter10-preface) · [Recipe 10.6: Speech-to-Text for Telehealth Documentation](chapter10.06-speech-to-text-telehealth-documentation) →*
