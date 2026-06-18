# Recipe 10.2: Voicemail Transcription and Classification ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.03-0.12 per voicemail (depending on length, ASR usage, and whether classification uses a managed service or a foundation model)

---

## The Problem

It is 4:50 p.m. on a Friday at a mid-sized internal medicine practice. The clinical-support phone line has been forwarded to voicemail since the front desk left for the day. Over the next sixty-four hours, until someone arrives Monday morning, the practice's voicemail box accumulates forty-seven new messages.

Most of those messages are routine. Mrs. Petrosian wants to confirm her Wednesday appointment. A pharmacy is calling about a prior-authorization fax that the practice already sent. Mr. Davis would like to know whether his blood-test results came back. A vendor wants to schedule a sales call. The IT contractor left a voicemail wishing the office a nice weekend.

Three of those forty-seven messages are not routine. One is from an 82-year-old woman with congestive heart failure who has gained six pounds since Tuesday and is short of breath walking to the bathroom. One is from the spouse of a chemotherapy patient who has been running a 102 fever since Saturday afternoon and is asking whether they should go to the emergency room. One is from a 24-year-old who took a friend's prescription opioid for a tooth pain after running out of his own ibuprofen and is now experiencing what he describes as "weird breathing" and a heaviness in his chest. 

Monday morning, a nurse arrives, sits down with a notepad, and starts working through the box. She listens to each message in order. The first one is the IT contractor. The second is Mrs. Petrosian. The third is the pharmacy. By the time she gets to message twelve (the one about the chemotherapy patient with the fever), it has been forty-six hours since the call was placed, and it takes her another two minutes of listening before she identifies it as urgent. The patient is no longer febrile by then, because they went to the emergency room on Sunday afternoon, which is, technically, a successful outcome from the system's perspective. The bill, several thousand dollars in ER charges that an earlier triage call could have avoided, is not.

Message thirty-one is the heart-failure patient. By the time the nurse calls back, the patient has gained another two pounds and is now too winded to finish a sentence. An ambulance is dispatched. Hospital admission for acute decompensation follows. The hospital readmission counts against the practice's quality scores, the patient suffers a clinical event that an earlier outreach could plausibly have prevented, and the cost to the system runs into the tens of thousands of dollars. The voicemail had been sitting in the box, unattended, for the entire weekend.

Message thirty-eight is the young man with the borrowed opioid. By Monday morning he is asleep on his bathroom floor and his roommate is calling 911. Naloxone, ER, hospital admission, the whole cascade. The voicemail he left on Friday night, in which he plainly described chest tightness after taking an opioid he was not prescribed, sat in the queue for sixty-four hours.

This is not a hypothetical. Some version of this story plays out in healthcare practices across the United States every week. The voicemail box is a queue, and the queue is FIFO by accident rather than by clinical priority. The nurse triaging the queue is doing her job competently and conscientiously. The system she is working inside, by being a flat list of audio recordings with no metadata beyond the caller's phone number and the time of the call, makes it nearly impossible for her to do that job well at scale.

The cost of this is not abstract. Multiply across thousands of practices and tens of thousands of voicemail boxes:

The patient who left a voicemail Friday afternoon describing a new severe headache, the worst of her life, who waits three days for a callback while a sentinel-event subarachnoid bleed sits unaddressed.

The medication-side-effect call from the patient who started a new statin and is reporting muscle pain, which sits in the box long enough that the patient stops the medication on her own and never starts another one, leading to a cardiac event eighteen months later that the original prescriber's nurse line could have prevented.

The mental-health call from a patient who is plainly suicidal, who specifically chose the medical-practice voicemail because she trusted her doctor, whose call goes through normal triage instead of being escalated to crisis lines, and who is dead before her primary care nurse listens to message twenty-two on Monday morning.

The denial of access disguised as administrative routine: the Spanish-speaking caller whose voicemails consistently go uncalled-back because the front desk speaks English, who eventually stops calling, whose chronic disease management quietly degrades, who is silently lost from the panel.

The legitimate refill request that the patient has now left voicemails about three times across two weeks because the first two went unreturned, which has now produced a frustrated patient, a confused pharmacist, and three voicemails that all need to be triaged when the nurse finally gets to them.

The voicemail box at most healthcare practices is, candidly, a liability. It is the place where time-sensitive clinical signal goes to wait alongside vendor solicitations and confirmation calls. The good practices have built operational discipline around it: a designated triage role, defined service-level agreements, escalation paths to clinicians for urgent calls. The not-so-good practices treat it as the IT system that handles voicemail. Both sets of practices are working with the wrong substrate. The voicemail box, as a clinical workflow, has been the same since the 1980s.

The opportunity is fairly direct: take the audio, transcribe it, classify it for clinical urgency and intent, sort the queue by priority, and surface the urgent calls before the routine ones. Add medical-entity extraction to surface the medication name, the symptom, the appointment date, so the staff member returning the call has context before they pick up the phone. Add a confidence-aware human review path so low-confidence transcriptions get listened to before they get acted on. Add subgroup-stratified accuracy monitoring so the practice notices if the system is silently underserving Spanish-speaking or older patients. Build the analytics layer that lets the practice see, for the first time, what its voicemail box actually contains.

None of this requires real-time speech recognition. None of it requires the multi-turn dialog management that makes IVR engineering complicated (recipe 10.1). The voicemail comes in, sits in a queue for at most a few minutes, gets processed, and gets routed. The async nature of the workload makes most of the engineering decisions easier. The hard parts that remain are the parts you cannot avoid: the medical vocabulary in ASR, the clinical-urgency lexicon, the equity-monitoring discipline, the human review queue, and the integration with the practice's existing telephone system. Those are the things this recipe spends most of its time on.

Let's get into it.

---

## The Technology: Async Voice, Decoupled

### How Voicemail Differs from Live Calls

The IVR recipe (10.1) cared about latency. Streaming ASR, partial transcripts, sub-second dialog turns, endpointing tuned to a hundred-millisecond budget. Voicemail does not care about any of that. By the time the audio reaches the transcription pipeline, the caller has already hung up. There is no caller waiting on the other end of the line for a response. The pipeline can take ten seconds, or thirty seconds, or two minutes (within reason), and nobody experiences the latency directly.

This single architectural difference reshapes the engineering. Streaming becomes optional. Endpointing becomes irrelevant (the recording has a defined start and end). Dialog management disappears entirely (one utterance per voicemail). Confidence-aware turn handling collapses into a simpler decision: fully process the message, or queue it for human review.

What replaces those concerns? Different ones, and some of them are harder.

**Audio quality variance is wider.** The IVR audio comes from an active call leg through a contact-center platform with reasonably consistent telephony characteristics. Voicemail audio comes from whatever device the caller used (cell phone in a moving car, landline in a quiet kitchen, speakerphone in a noisy break room, hands-free Bluetooth in a parking garage), passes through whatever carrier path connected the call, and lands in whatever voicemail system the practice uses (legacy on-prem PBX, hosted UCaaS, embedded telephony in the EHR, the carrier's own voicemail-to-email service). The variance in audio quality is substantially wider than in a live IVR call.

**Recording length varies wildly.** Some voicemails are eight seconds. Some are four minutes. Some begin with a long pause as the caller hesitates before the beep ends; some end mid-sentence because the practice's voicemail system has a 90-second cap. The pipeline has to handle the full distribution gracefully.

**Recordings include silence and noise that nobody triages live.** The voicemail box accumulates spam-call hangups, pocket-dials with no speech, fax-machine tones from misdirected fax senders, and the occasional five-minute recording of someone's car radio because their phone redialed the practice from inside their pocket. The pipeline has to detect and route those without burning ASR budget on them.

**Voicemails are signed, in a sense.** The caller chose, deliberately, to leave a message. They thought about what they wanted to say. They held the phone up to their face for thirty to ninety seconds. The intent in a voicemail is, on average, more deliberate than the intent in an IVR utterance. That makes classification a little easier than the equivalent task in IVR. (The downside is that voicemails are also longer and more rambling, which makes intent extraction take a little more work.)

**The clinical-urgency stakes are higher.** A misrouted IVR call usually ends with a brief annoyance and a transfer. A misrouted voicemail can sit unread for days. The downside risk on a missed urgency signal is materially worse for voicemail than for IVR.

These differences compound into a different architectural shape, with different priorities, even though the building blocks (ASR, classification, entity extraction, human review) are the same.

### Batch Speech Recognition

The first stage of the pipeline is automatic speech recognition (ASR), this time in batch mode. The pipeline submits the full audio file to the ASR system and receives, after some processing time, a complete transcript with per-word and per-utterance confidence scores.

A few specifics that matter for voicemail-class workloads.

**Async APIs and retrieval-by-job-id.** Most cloud ASR vendors offer two API modes: synchronous (call returns when transcription is done; works for short clips of perhaps thirty seconds or less) and asynchronous (you submit a job, get back a job ID, and poll or receive a callback when the result is ready; works for arbitrary length audio). For voicemail, async is the default choice because the message length distribution has a long tail and you do not want a Lambda function blocked for two minutes waiting on a synchronous transcription. The pipeline submits the job, hands off, and processes the result when it arrives. Job-completion notifications can be wired through SNS or EventBridge so the pipeline does not have to poll.

**Speaker diarization is usually unnecessary.** A voicemail typically has one speaker (the caller). Some have two (the caller plus a family member who chimes in), and rarely more. Unlike telehealth or ambient documentation, you do not need rigorous diarization. You need accurate transcription of whoever is speaking. If multiple speakers are present, treating their combined utterances as one transcript is usually fine for routing and triage purposes; the human reviewer can disambiguate when needed.

**Domain-adapted language models pay off.** A voicemail saying "I am calling about my furosemide refill" needs to transcribe the drug name correctly to support routing as a medication intent. General-purpose ASR will sometimes get it; medical-domain ASR (Transcribe Medical, Nuance, fine-tuned Whisper variants, vendor-specific clinical models) is dramatically more reliable on the medication names that drive the most common voicemail intents. For a healthcare voicemail pipeline, you want the medical-domain model, not the general-purpose one. The cost difference is small. The accuracy difference is large.

**Telephony codec awareness.** Voicemail audio often arrives compressed. WAV files at 8 kHz mono are common. MP3 is common. Vendor-specific codecs (G.711, G.729, GSM) appear in legacy systems. The transcription pipeline has to either handle the formats natively or transcode upstream. Transcoding is mostly mechanical (FFmpeg-class tooling) but introduces failure modes and quality loss; native handling is preferable when the ASR vendor supports it.

**Length-aware processing.** Very short audio (under a few seconds) is often spam, hangups, or pocket-dials, and is not worth running ASR on. Very long audio (more than the practice's voicemail cap) can sometimes appear as the result of system bugs or unusual capture paths, and may indicate a recording-error condition rather than a legitimate message. Length-based filtering at the front of the pipeline (drop the under-three-second clips, flag the over-five-minute clips for special handling) saves cost and improves the signal-to-noise ratio of the downstream classification.

**Confidence is the gate, not the answer.** ASR confidence scores feed the downstream confidence-aware logic in the same way they do for IVR. A high-confidence transcript with clear medical entities can be auto-classified and auto-routed. A medium-confidence transcript can be classified, with the result flagged for human verification before action. A low-confidence transcript ("this audio is ninety seconds of street noise and the model is guessing") should not be acted on at all; route to a human listener.

### Voice Activity Detection and Pre-processing

Before the audio reaches the ASR system, a small pre-processing layer earns its keep.

**Voice activity detection (VAD).** A simple model that distinguishes speech from non-speech regions of the audio. Useful for two reasons. First, you can detect "no speech detected" voicemails (pocket-dials, silent hangups, fax-tone-only, music-only) and route them to a "no transcription needed" disposition without spending ASR cost. Second, you can trim leading or trailing silence before submitting to ASR, which marginally reduces transcription cost and slightly improves accuracy at the boundaries.

**Background noise classification.** Some recordings are dominated by non-speech audio (a baby crying, a TV in the background, music, traffic, mechanical noise). A simple acoustic classifier can flag these as "noisy environment" so the downstream confidence interpretation can be adjusted. The pipeline does not need to separate the signal from the noise; it needs to know that this recording is likely to produce a less reliable transcript.

**Loudness normalization.** Voicemails come in at vastly different loudness levels. Normalizing the input audio's loudness (RMS or peak) before transcription is a low-cost intervention that improves ASR consistency.

**DTMF tone detection.** Some "voicemails" are actually fax tones or DTMF sequences left by automated systems. Detecting DTMF in the audio is mechanical and lets you route those recordings appropriately rather than sending them to ASR.

You do not need elaborate audio engineering. You need enough pre-processing to filter the obvious non-speech inputs and to marginally improve the speech inputs. Modern ASR systems are robust enough that aggressive pre-processing can actually hurt; light-touch is the right posture.

### Text Classification: Intent and Urgency

Once you have a transcript, the next stage is classification. There are typically two parallel classification axes and one entity-extraction layer that feed the routing decision.

**Intent classification.** What is this voicemail about? Common categories for a healthcare practice voicemail box: medication question or refill request; appointment-related (schedule, reschedule, cancel, confirm); test-result inquiry; clinical-symptom report; billing question; insurance or prior-authorization question; vendor or business-related; spam or wrong-number; unclear. The exact taxonomy is institutional; most practices end up with eight to fifteen categories.

**Urgency classification.** Independent from intent, how time-sensitive is this voicemail? A common scheme: emergent (caller is reporting symptoms that suggest a medical emergency, or expressing suicidality); urgent (clinically time-sensitive but not emergency-room-now: medication side effects, worsening symptoms, fever in a high-risk patient); routine (medication refill, appointment confirmation, results inquiry, billing); low-priority (vendor solicitations, wrong numbers, spam). Urgency is partly inferable from intent, but not entirely; a "medication refill" intent for a routine antihypertensive is routine, while a "medication refill" intent for a chemotherapy adjunct in a patient who is now days late on the dose is more time-sensitive.

**Medical entity extraction.** What specific clinical entities does this voicemail mention? Drug names. Symptoms. Body parts. Conditions. Procedures. Lab tests. Dates. Phone numbers. Names of clinicians. The entity layer surfaces the actionable specifics in the message: "the patient mentioned methotrexate, the symptom mouth sores, and the lab thyroid panel." The entities feed both the urgency classifier (some entities raise the urgency on their own; "chest pain" is one of those) and the routing decision (the medication-related voicemails go to the pharmacy queue with the medication name pre-populated).

You can implement these layers in several ways.

**Rule-based classifiers.** Define keyword and regex patterns for each intent and urgency level. "If the transcript contains 'refill' or 'prescription' or 'pharmacy', classify as medication intent. If the transcript contains 'chest pain' or 'can't breathe' or 'shortness of breath' or 'suicide', classify as emergent urgency, regardless of other classification." Easy to build, transparent, and (especially for the urgency-keyword layer) actually the right approach. The clinical urgency lexicon should be a rule layer on top of any ML classifier, because the cost of missing an emergent message is much higher than the cost of over-flagging.

**Statistical text classifiers.** Train a supervised classifier on labeled transcripts. Each labeled example is a transcript and its intent (and urgency) label. Standard supervised text classification: logistic regression over TF-IDF, gradient-boosted trees over text features, or fine-tuned transformer models. The models handle paraphrase variation (every way someone might say "I want to refill my prescription") that rule-based systems struggle with.

**LLM-based classifiers.** Send the transcript to a foundation model with a prompt that lists the intents (and urgency categories) and ask the model to classify. Modern LLMs are excellent at this with few-shot prompting and minimal training data. The advantages: no per-intent training data, easy to extend, handles weird phrasings gracefully, can extract entities and rationales in the same call. The disadvantages: per-message inference cost (small but non-zero), occasional hallucinated categories that are not in your list (validate strictly), and the operational dependency on a model you do not fully control.

For voicemail specifically, in 2026, the right answer is usually a hybrid. Run the urgency-keyword rule layer first (cheap, fast, safety-critical). Run an LLM- or transformer-based classifier on the rest of the transcript for intent and refined urgency. Run a managed medical-entity-extraction service (Amazon Comprehend Medical, similar offerings from other vendors, or NLP libraries like scispaCy or MedCAT for self-hosted) to extract clinical entities. Combine the outputs into a structured triage record. 

**Domain entity extraction.** Comprehend Medical and equivalents extract medication names, conditions, anatomy, procedures, and tests as structured entities, often with mappings to standard ontologies (RxNorm for medications, ICD-10 for conditions, SNOMED for clinical concepts). The structured entities are far more useful for downstream routing than free-text mentions; "the medication is RxNorm:104491 (lisinopril)" is unambiguous in a way that "the medication is lisinopril" is not.

### The Triage Queue

Once a voicemail is transcribed and classified, the output is a triage record: the audio reference, the transcript, the intent, the urgency, the extracted entities, the per-layer confidence scores, the caller phone number, and any patient context inferred from the phone number lookup. This record goes into a triage queue.

The triage queue is not just a list. It is a priority data structure that the staff member working through the box sees, in priority order, so the urgent calls surface first. The architecture has to provide that. A simple FIFO queue defeats the entire point. The queue typically has the following properties.

**Priority-aware ordering.** Emergent urgency comes first. Within an urgency level, older messages come first (so a routine message does not sit in the queue forever just because new routine messages keep arriving). Within an urgency level and time bucket, certain intents may be prioritized (clinical-symptom intent ahead of billing intent, for instance). The ordering rules are explicit and reviewable.

**Filtering and routing.** The same queue may serve multiple staff roles. Pharmacy gets the medication-related queue. Scheduling gets the appointment-related queue. Nurse triage gets the clinical-symptom queue. Billing gets the billing queue. The architecture surfaces the right subset of messages to each role's view, not the full firehose.

**Confidence flagging.** Low-confidence classifications surface as such, so the staff member knows to listen to the audio rather than trusting the transcript. The interface presents the original audio playback alongside the transcript, with the entities highlighted in the transcript view.

**Audit trail.** Every action a staff member takes against a voicemail (listened, called back, marked resolved, escalated) is logged. The audit trail feeds the analytics layer that surfaces handle-time, time-to-callback, and outcomes by category.

**Escalation paths.** Emergent-urgency messages do not just sit at the top of the queue; they trigger an active notification (page, SMS, dashboard alert, depending on the institution's protocol) so a clinician sees them immediately rather than waiting for the next queue review.

### Where the Field Has Moved

Some practical updates worth knowing.

**Foundation-model classification has displaced custom-trained classifiers for many use cases.** Five years ago, a voicemail classification system would have required several thousand labeled examples to train a competent intent classifier. Today, an LLM with a well-designed prompt and a handful of few-shot examples can produce comparable or better classification with no training data. The operational dependency shifts (you depend on the foundation model vendor rather than on your own labeled dataset), but the time-to-launch is dramatically faster. 

**Embeddings-based retrieval over historical messages is increasingly used.** When a voicemail comes in, embed it and check whether similar voicemails have been left by the same patient in the recent past. Useful for de-duplicating callbacks (the patient has already left this same message; consolidate) and for identifying patients who are repeatedly trying to reach the practice (a possible signal of a problem the system is not surfacing well).

**Medical entity extraction has matured.** The accuracy of cloud-managed medical-entity extraction (Comprehend Medical, Google Healthcare Natural Language API, Microsoft Text Analytics for Health) has reached the point where the entity extraction is rarely the bottleneck. The bottleneck has shifted to the upstream ASR accuracy (if the medication name was transcribed wrong, the entity extractor will miss it) and the downstream interpretation (an extracted "chest pain" entity has to be interpreted in context: was the patient describing their own current symptom, asking about a past episode, or relaying something about a family member). 

**Multilingual ASR has gotten substantially better but remains uneven across languages.** Voicemail in English transcribes well. Voicemail in Spanish transcribes well. Voicemail in less-common-on-the-internet languages transcribes worse. The pipeline has to handle multilingual audio gracefully, which usually means language detection at the front of the pipeline and language-specific transcription paths downstream.

**Voicemail systems themselves have moved.** Legacy on-prem PBX voicemail still exists, but most healthcare practices have migrated to hosted UCaaS platforms (RingCentral, Zoom Phone, Microsoft Teams Phone, 8x8, Vonage, etc.) or to telephony embedded in their EHR (eClinicalWorks, athenaCommunicator, similar). Each platform has different APIs for accessing voicemail audio, different metadata fidelity, and different integration surfaces. The pipeline architecture has to be agnostic to the source system because most practices have heterogeneous environments. 

**Real-time transcription as a precursor to classification is becoming feasible.** Some platforms now transcribe voicemails as they are being recorded (streaming the audio to ASR), so by the time the caller hangs up, the transcript already exists and the classification can run within seconds. Useful when the urgency-detection latency budget matters (a chest-pain voicemail is more time-sensitive than a refill voicemail; surfacing it within thirty seconds of being left rather than within thirty minutes of the next queue review is a meaningful improvement).

---

## General Architecture Pattern

A voicemail transcription and classification pipeline splits cleanly into seven logical stages: ingestion (the voicemail audio reaches your system), pre-processing (filter noise, normalize loudness, detect speech), transcription (batch ASR), classification (intent, urgency, entity extraction), enrichment (patient context lookup), routing (to the right staff queue with the right priority), and observability (everything captured for analysis and improvement).

```text
┌──────────────────── INGESTION ───────────────────────────┐
│                                                           │
│   [Voicemail recorded by source system]                  │
│    - Hosted UCaaS, on-prem PBX, EHR-embedded telephony,  │
│      or carrier voicemail-to-email                       │
│   [Source system delivers the recording to the pipeline] │
│    - Webhook + signed URL, S3 push, SFTP drop,           │
│      IMAP-poll for voicemail-to-email, vendor API pull   │
│   [Pipeline persists the audio to a secure object store] │
│    - Encrypted at rest with customer-managed keys        │
│    - Linked to a voicemail record with ANI, DNIS,        │
│      timestamp, source-system-message-id                 │
│           │                                               │
│           ▼                                               │
│   [Output: a voicemail record with audio reference and   │
│    minimal metadata, awaiting processing]                │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── PRE-PROCESSING ──────────────────────┐
│                                                           │
│   [Length filter]                                         │
│    - Drop or specially-handle clips under threshold      │
│      (commonly 3 seconds: pocket dials, hangups)         │
│    - Flag clips over threshold (e.g., 5 minutes) for     │
│      human review without ASR                            │
│                                                           │
│   [Voice activity detection]                             │
│    - Mark "no speech detected" recordings; route to a    │
│      no-speech disposition without spending ASR budget   │
│    - Optionally trim leading and trailing silence        │
│                                                           │
│   [DTMF / fax tone detection]                            │
│    - Identify recordings that are tones rather than      │
│      speech; route to fax/automated-system queue         │
│                                                           │
│   [Loudness normalization]                               │
│    - Normalize RMS or peak loudness so ASR sees          │
│      consistently-leveled audio                          │
│                                                           │
│   [Language detection (optional, for multilingual orgs)] │
│    - Identify the primary language of the audio so the   │
│      ASR call can use the correct model                  │
│           │                                               │
│           ▼                                               │
│   [Output: voicemail record annotated with pre-          │
│    processing decisions; either continued to ASR, or     │
│    short-circuited to a non-ASR disposition]             │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── TRANSCRIPTION ───────────────────────┐
│                                                           │
│   [Submit async ASR job]                                  │
│    - Medical-domain model preferred                       │
│    - Single-speaker mode (diarization disabled by         │
│      default)                                             │
│    - Per-word and per-utterance confidence requested      │
│                                                           │
│   [Wait for job completion via callback or event]        │
│                                                           │
│   [Persist the transcript to the secure transcript       │
│    archive, alongside the audio]                         │
│    - Transcript is PHI; same governance as the audio     │
│           │                                               │
│           ▼                                               │
│   [Output: voicemail record updated with transcript,     │
│    word-level timing and confidence, and average         │
│    confidence aggregate]                                  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── CLASSIFICATION ──────────────────────┐
│                                                           │
│   [Urgency-keyword rule layer (runs first)]              │
│    - Pattern-match against the clinical urgency lexicon  │
│    - Sets urgency = emergent if a phrase matches,        │
│      regardless of downstream classifier output          │
│                                                           │
│   [Intent classifier]                                    │
│    - LLM, transformer, or trained classifier             │
│    - Returns intent + per-intent confidence              │
│    - "Out of scope" or "low confidence" returned as      │
│      explicit values, not as the absence of a result     │
│                                                           │
│   [Urgency classifier]                                   │
│    - LLM, transformer, or trained classifier             │
│    - Returns urgency level + confidence                   │
│    - Combined with rule-layer output: max(rule,          │
│      classifier); rule layer can only escalate, never    │
│      de-escalate                                          │
│                                                           │
│   [Medical entity extraction]                            │
│    - Drugs, conditions, anatomy, procedures, tests,      │
│      with ontology mappings (RxNorm, ICD-10, SNOMED)     │
│           │                                               │
│           ▼                                               │
│   [Output: structured triage record with intent, urgency,│
│    entities, all confidences, raw transcript reference,  │
│    audio reference]                                       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── ENRICHMENT ──────────────────────────┐
│                                                           │
│   [ANI-based patient lookup]                             │
│    - Match caller phone number against patient index    │
│    - Multiple matches: capture all candidates; do not    │
│      assume identity                                      │
│    - Zero matches: flag as "unmatched caller"             │
│                                                           │
│   [Patient context retrieval (when match is unique)]     │
│    - Active medication list                              │
│    - Recent appointments                                  │
│    - Active care plans and chronic conditions            │
│    - Recent voicemails from same caller (de-dupe         │
│      detection)                                          │
│                                                           │
│   [De-duplication / repeat-caller detection]             │
│    - If the same caller has left similar messages in     │
│      the last 48 hours, flag for consolidation           │
│           │                                               │
│           ▼                                               │
│   [Output: triage record enriched with patient context   │
│    and repeat-caller status]                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── ROUTING ─────────────────────────────┐
│                                                           │
│   [Queue selection based on intent and patient context]  │
│    - Pharmacy queue, scheduling queue, nurse triage      │
│      queue, billing queue, general queue                 │
│                                                           │
│   [Priority assignment based on urgency]                 │
│    - Emergent: top of queue + active notification        │
│    - Urgent: top of queue with SLA flag                  │
│    - Routine: standard ordering                           │
│    - Low-priority: deprioritized or filtered out         │
│                                                           │
│   [Active notification path for emergent items]          │
│    - Page or SMS to on-call clinician                    │
│    - Dashboard alert in the staff interface              │
│    - Audit-log every active notification                 │
│                                                           │
│   [Confidence-aware delivery]                             │
│    - High confidence: triage record presented with       │
│      transcript and entities highlighted                 │
│    - Medium confidence: same, but with a "verify before  │
│      acting" badge                                       │
│    - Low confidence: queue with a "listen to audio       │
│      before acting" badge                                │
│           │                                               │
│           ▼                                               │
│   [Output: triage record placed in the appropriate       │
│    staff queue with ordering, priority, and confidence   │
│    metadata]                                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────────────── OBSERVABILITY ───────────────────────┐
│                                                           │
│   [Per-voicemail audit record]                           │
│    - Pre-processing decisions                             │
│    - ASR job ID, model used, duration, confidence stats  │
│    - All classification outputs and confidences          │
│    - Entity extraction output                             │
│    - Routing decision and the rule that fired            │
│    - Staff actions: listened, called back, resolved,     │
│      escalated, time stamps for each                     │
│                                                           │
│   [Per-voicemail audio and transcript]                   │
│    - Encrypted at rest                                    │
│    - Retention per institutional policy                   │
│                                                           │
│   [Aggregate metrics]                                    │
│    - Volume by intent, urgency, time-of-day              │
│    - Time-to-classification, time-to-callback by         │
│      urgency tier                                         │
│    - Misclassification rate (sampled human review)       │
│    - Subgroup-stratified accuracy (language, dialect,    │
│      age cohort, geographic region)                      │
│    - Repeat-caller rate                                   │
│           │                                               │
│           ▼                                               │
│   [Output: continuous improvement signals fed back to    │
│    classifier prompts, urgency lexicon, and routing      │
│    policy]                                                │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points that the architecture has to bake in from the start.

**Async, but emergent items get real-time treatment.** Most of the pipeline is async: voicemail comes in, gets processed within a few minutes, sits in the queue. Emergent-urgency items are the exception: the moment the urgency classifier or rule layer flags one, the pipeline emits an active notification rather than waiting for the staff member to find it in the queue. This dual-mode architecture (async by default, real-time for emergent) is what lets the system serve both routine triage and clinical safety from a single pipeline.

**Transcripts are PHI; treat them accordingly.** Voicemail recordings are PHI (the recording typically contains the caller's name, phone number, and clinical content). Transcripts of those recordings are also PHI. Both are stored in encrypted object storage with customer-managed keys, with access controls that match the rest of the institution's PHI handling. Audit logs that record voicemail processing should reference the audio and transcript by ID, not embed the raw content; the raw content should live in the secure archive only.

**The urgency lexicon is a clinical safety document.** Same as in recipe 10.1: the urgency lexicon is the safety net for clinical signal that the ML classifier might miss. Treat it as a clinical safety artifact with version control, change review by clinical operations, scheduled refresh cadence, and a documented escalation path when a missed urgent voicemail surfaces.

**Confidence thresholds are per-axis and per-action.** Different actions on the triage record require different confidence floors. Auto-routing a voicemail to the pharmacy queue based on a high-confidence "medication refill" intent is a low-stakes action and can run on a moderate confidence threshold. Auto-escalating to the on-call clinician based on an emergent-urgency classification is a higher-stakes action (the consequences of a false positive are real, even if the consequences of a false negative are worse) and warrants a different threshold. Auto-resolving a voicemail without staff review is a still-different action and should require very high confidence and a narrow set of intents (and probably should not be done at all in MVP).

**Sampled human review is non-negotiable.** The pipeline cannot self-evaluate its accuracy. The institution needs a sampled audit process where a clinical reviewer listens to a random sample of voicemails per week and compares the human assessment to the pipeline's classification. The sample size is institutional but a few percent of total volume is a reasonable starting point. Without this, the pipeline drifts silently and nobody notices.

**Subgroup-stratified accuracy must be visible.** Voicemail ASR has worse accuracy on certain demographic groups (older speakers, non-native English speakers, speakers with hearing loss who modulate their voice differently). The pipeline must surface accuracy metrics stratified by language preference, age cohort, and (where data permits) accent group. Disparities exceeding configured thresholds should alert. This is not an optional analytics nice-to-have; it is the mechanism by which the institution detects whether the system is silently underserving specific patient populations.

**The pipeline degrades to "human listens to all voicemails" gracefully.** If any pipeline stage is unavailable (ASR vendor outage, classifier service down, queue infrastructure failure), the system should fall back to delivering the raw voicemail audio to the staff queue with a "automated triage unavailable, please review manually" flag. The voicemail box was reachable by humans before the pipeline existed; it must remain reachable by humans when the pipeline cannot run.

**De-duplication and repeat-caller detection are operationally important.** The same patient leaving four voicemails in two days about the same refill request should result in one consolidated triage record, not four. The repeat-caller signal is also clinically interesting: a patient who has tried to reach the practice three times in a week and not gotten through is a patient at risk of disengagement, regardless of the specific intents.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter10.02-architecture). The Python example is linked from there.

## The Honest Take

The voicemail pipeline is the cleanest application of speech-AI to a healthcare problem in this chapter, and it's the recipe where the engineering risk is lowest and the clinical impact is highest. The async nature simplifies almost every architectural decision. The audio quality, while variable, is bounded (it's a voicemail, not a live ambient capture). The downstream consumers are humans (the staff queue), so the system is fundamentally a triage aid rather than a clinical decision-maker. The failure mode of "the classifier was wrong" is recoverable (the staff member listens to the audio and reclassifies). The success mode is not abstract: a single emergent voicemail surfaced two days earlier than it would have been is a real patient with a real outcome difference.

The trap most specific to voicemail triage is treating the urgency classifier as the primary safety mechanism. It is not. The urgency-keyword rule layer is the primary safety mechanism. The classifier is the secondary refinement that catches phrases the rule layer didn't anticipate and lowers the false-positive rate on routine voicemails that happen to contain urgency-adjacent words. Build the rule layer first. Test it exhaustively. Treat it as a clinical safety document with appropriate governance. Build the classifier on top of that, with the explicit understanding that the classifier may de-prioritize a voicemail but cannot de-prioritize one that the rule layer flagged. The institutions that build this well treat the lexicon as the load-bearing safety wall and the classifier as the polish; the institutions that don't, treat the classifier as the safety wall and learn about the gaps from the missed-urgent-voicemail incident report.

The trap closely related to that one is over-trusting the ASR transcript. ASR errors propagate. A misrecognized "no" in front of a phrase ("I have no chest pain" vs "I have chest pain") inverts the clinical meaning. A misrecognized medication name causes the entity extractor to miss a drug interaction or surface a wrong drug for the staff member to confirm. The architectures that work treat the transcript as evidence, not ground truth. The audio is the source. The transcript is a cached interpretation of the audio that the staff member can falsify by listening. The interface design has to make it easy to listen to the audio at the moment in question, not require the staff member to scrub through the entire recording. Word-level timing in the transcript supports clickable playback at the relevant timestamp; build that into the UI.

A third trap is under-investing in the staff interface. The pipeline's job is to make the staff member faster and more accurate. If the interface is bad (the queue doesn't sort right, the transcript is hard to read, the playback is buried, the reclassification flow is annoying), the staff member works around the pipeline rather than with it. They go back to listening to the raw audio in the order it came in. The investment ratio that separates successful deployments from frustrating ones is, in our experience, somewhere around 60% engineering on the pipeline and 40% engineering on the staff interface, not the 90/10 split that most projects start with. The interface is not a thin client over the pipeline; it is the primary product for the user who actually uses the system.

A fourth trap is ignoring the equity dimension. Voicemail ASR systematically underperforms for non-English speakers, for older speakers, for speakers with hearing loss, for speakers from underrepresented dialect groups. If the pipeline silently routes those callers' voicemails through with lower-quality transcripts, lower-confidence classifications, and consequent default-to-human-review (which then takes longer in a busy queue), the system has built a structural delay into the responsiveness experienced by exactly the populations the practice's quality metrics most need to monitor. The mitigation is the subgroup-stratified accuracy dashboard, the conservative routing posture for low-confidence cases, and the periodic vendor evaluation. It is also, more fundamentally, the recognition that the pipeline's metrics in the aggregate can look excellent while the metrics for the underserved cohort look much worse.

The thing that surprises people coming from text-NLP backgrounds is how much of the work is in the pre-processing and the audio handling. The classifier is the most interesting piece, and it gets a few hundred words of attention in any given recipe. The audio pipeline (format detection, transcoding, VAD, length filtering, fax-tone detection, loudness normalization) is where the operational headaches actually live. A bad audio pipeline produces classification errors that look like classifier errors but are actually upstream problems. Invest in the audio handling first; the classification falls out of accurate input.

The thing that surprises people coming from telephony-engineering backgrounds is how much of the value is in the structured outputs, not in the transcription itself. A traditional voicemail-to-email service gives you the audio and a transcript and that's it. The triage pipeline gives you intent, urgency, entities with ontology mappings, patient context, repeat-caller signal, queue routing, and a structured audit trail. Each of those layers takes a small amount of additional engineering on top of the transcript and produces multiplicatively more operational value. The ratio between "transcription as a feature" and "transcription as the foundation for a triage pipeline" is something like 1:5 in operational impact for a similar 1:3 in engineering effort.

The thing about Amazon Transcribe Medical specifically: it's competent on the medical-vocabulary axis and competent on the per-word confidence axis, which are the two things that matter most for this pipeline. It's not the most accurate medical ASR on the market (Nuance and a few specialized vendors are arguably better on certain specialty vocabularies), but the integration savings (managed service, async batch, native S3 input, native KMS encryption) outweigh the accuracy difference for most healthcare practices. For specialty practices with vocabulary not well-covered by Transcribe Medical's general-medical training, custom vocabulary lists provide meaningful improvement; for practices with very specialized vocabulary (oncology with novel drug names, niche subspecialties), evaluating purpose-built vendors is worthwhile. 

The thing about Amazon Comprehend Medical specifically: it's the entity extraction layer most healthcare developers will use because it's a managed service with HIPAA eligibility and it ships with the ontology mappings (RxNorm, ICD-10-CM, SNOMED CT) that the entities need. It misses some entities that domain-specific extractors would catch, and it doesn't reason about negation or temporal context as well as some research-grade medical NLP systems. For voicemail triage, the entity-extraction quality is sufficient for routing and surface-context purposes. For higher-stakes downstream uses (auto-population of clinical fields in the EHR, billing-code suggestion), the entity extraction needs more validation than this recipe builds.

The thing about Amazon Bedrock for the classifier: foundation models are excellent at intent and urgency classification with well-designed prompts and a handful of few-shot examples. The trade-off is per-call inference cost and the operational dependency on the model vendor. For a voicemail-volume workload, the cost is modest; for very high volumes, the cost may motivate a smaller fine-tuned classifier. The right architectural posture in 2026 is to use foundation models for the launch, instrument the classifier-disagreement-with-human-review metric carefully, and revisit the build-versus-buy question at the one-year mark with real data on how often the classifier is wrong, on which intents, and what a custom-trained alternative would cost to maintain. 

The thing about per-voicemail cost: end-to-end, somewhere in the range of three to twelve cents of AWS infrastructure cost per voicemail (Transcribe Medical dominating the per-message cost, Bedrock and Comprehend Medical adding modestly, Lambda and storage rounding things out). Compare against the fully-loaded cost of a human triaging the same voicemail unaided (typically 90-180 seconds of nurse or front-desk time, often $2-5 of fully-loaded labor cost). The economic case is favorable, even before considering the clinical impact of faster emergent-call surfacing. The economic case strengthens further when you account for the secondary benefits: reduced call-back-cycle costs (the patient reaches a staff member faster, fewer follow-up voicemails), avoided unnecessary ER visits (the urgent-but-not-emergent voicemail gets a same-day clinical response instead of an ER visit because the message languished), and improved patient retention (patients who feel heard tend to stay).

The thing I would do differently the second time: invest more, earlier, in the sampled human review process. The first version of any classifier ships with the prompt and the few-shot examples and a vague intent to evaluate accuracy later. The first month of production data is the most informative dataset you'll ever have for tuning the system, and the institutions that have the sampled review process running from week one improve much faster than the ones that bolt it on in month four. Build the disagreement-capture interface before launch, recruit the clinical reviewers, define the sampling cadence, and let the production traffic flow into a system that's already prepared to learn from it.

The last thing, because it's specific to healthcare and to this recipe in particular: the voicemail box is, for many patients, the only after-hours channel they have to reach the practice. The decision to leave a voicemail is often made under stress (a symptom got worse, a medication ran out, a fever spiked, a child stopped responding well). The patient has weighed whether to call. They've spoken into a phone that may or may not be transmitting their words clearly. They've trusted that someone would listen. The pipeline's job is to honor that trust. Not to silently lose the urgent calls in the routine queue. Not to systematically deprioritize the patients whose speech the system handles less well. To listen, structure, prioritize, and route, so that the staff member calling back is calling back the right patient at the right time with the right context. Build the system that does that, and the metrics follow. Build the system that doesn't, and the patients who most needed the call back are the ones who silently leave the panel.

---

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, real-time analog of this recipe. Same speech-to-text-to-intent pipeline, same intent classification, same urgency-keyword rule layer pattern, but with streaming ASR, dialog management, and tighter latency constraints. The two systems share the urgency lexicon, the intent taxonomy, the patient-index lookup, and the back-office integrations.
- **Recipe 10.4 (Medical Transcription / Dictation):** Shares Transcribe Medical and the medical-vocabulary tuning concerns; the dictation use case has higher accuracy requirements but uses the same core ASR substrate.
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Shares the streaming-ASR-and-confidence-aware pipeline patterns; adds multi-party diarization that voicemail does not need.
- **Recipe 10.7 (Ambient Clinical Documentation):** The structured-output-from-speech pattern at a higher complexity tier; voicemail triage is the simpler analog of the ambient documentation pipeline.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** The intent and urgency classification techniques used in this recipe map directly onto the conversational AI assistants in chapter 11.
- **Recipe 8.x (Traditional NLP):** The intent and urgency classification, entity extraction, and rule-based scanning techniques draw from the broader NLP methods covered in chapter 8.
- **Recipe 4.1 (Appointment Reminder Channel Optimization):** The voicemail pipeline produces signal that feeds the channel-optimization model: patients who reliably respond to voicemail, patients who never call back, patients who consistently use after-hours voicemail.
- **Recipe 5.1 (Internal Duplicate Patient Detection):** The ANI-based patient lookup hits the same duplicate-patient problem; this recipe consumes the patient-index pipeline that recipe 5.1 produces.
- **Recipe 2.5 (After-Visit Summary Generation):** The summarization-from-conversation pattern used in the voicemail triage record's machine-generated summary draws from the LLM-summarization techniques covered in chapter 2.

---

## Tags

`speech-voice-ai` · `voicemail` · `voicemail-transcription` · `voicemail-triage` · `async-asr` · `batch-asr` · `intent-classification` · `urgency-classification` · `medical-entity-extraction` · `clinical-triage-routing` · `urgency-lexicon` · `confidence-thresholding` · `voice-activity-detection` · `pre-processing-pipeline` · `priority-queue` · `repeat-caller-detection` · `patient-context-enrichment` · `human-in-the-loop` · `sampled-review` · `subgroup-accuracy` · `equity-monitoring` · `transcribe-medical` · `comprehend-medical` · `bedrock` · `step-functions` · `lambda` · `dynamodb` · `s3` · `sns` · `eventbridge` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `opensearch` · `simple` · `mvp` · `hipaa` · `phi-handling` · `audit-trail` · `staff-triage-ui` · `multilingual-asr`

---

*← [Recipe 10.1: IVR Call Routing Enhancement](chapter10.01-ivr-call-routing-enhancement) · [Chapter 10 Index](chapter10-preface) · [Recipe 10.3: Voice-to-Text for EHR Navigation](chapter10.03-voice-to-text-ehr-navigation) →*
