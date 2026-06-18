# Recipe 10.9: Speech Therapy Assessment and Monitoring ⭐⭐⭐

**Complexity:** Complex · **Phase:** Production-track for established assessment workflows; pilot-track for autonomous scoring and pediatric expansions · **Estimated Cost:** ~$0.10-0.50 per assessment session analyzed (varies with session length, number of tasks, model count, and whether linguistic-feature pipelines run alongside acoustic analysis)

---

## The Problem

A six-year-old girl named Maya sits across from a speech-language pathologist (SLP) in a small therapy room. The SLP is holding a flipbook of pictures and asking Maya to name them. "Rabbit." Maya says "wabbit." "Sheep." Maya says "seep." "Thumb." Maya says "fum." The SLP is making notes, sometimes circling sounds on a printed articulation inventory, sometimes pausing to write a quick observation in the margin. Forty-five minutes later, Maya leaves with her mom, and the SLP has roughly twenty minutes between this session and the next to convert what she just observed into a structured assessment: which phonemes Maya can produce, which she substitutes, which she omits entirely, what the patterns are (final consonant deletion? cluster reduction? fronting?), how Maya's intelligibility compares to age norms, what the goals for the next twelve weeks should be, and what the home-practice activities look like. The SLP is good at this. She has done it ten thousand times. She also has thirty-two more patients on her caseload, eight more sessions today, and a documentation backlog that follows her home most evenings.

Twelve weeks later Maya is back. The SLP wants to know whether Maya is making progress. Has the final consonant deletion gotten better since the last assessment? Is the /r/ approximation closer to the target now? Is Maya generalizing from the practiced words to spontaneous speech? The clinical question is fundamentally a comparison: Maya now versus Maya twelve weeks ago, against a backdrop of where typically-developing six-year-olds sit on the developmental curve. The data the SLP needs to answer this question lives, in fragments, across her notes from twelve weeks ago, her notes from today, the parent's report of how home practice is going, and her ear's memory of how Maya sounded last time. The comparison is approximate. It is also the foundation of every clinical decision the SLP will make about Maya's care over the next year.

This is the world that speech-therapy assessment and monitoring AI is trying to land in. The goal is not to replace the SLP. The goal, when it is framed honestly, is to give the SLP back the time she spends transcribing her own observations after the session, to make the longitudinal comparison more reliable than human auditory memory allows, and to extend the reach of the SLP into between-session monitoring (home practice with feedback, parent-led drills with quality scoring, telepractice sessions where the SLP cannot watch every utterance) without adding more humans the clinic does not have. Done well, this is a category of healthcare AI where the labor savings are real, the clinical signal is genuinely useful, and the patient outcomes can improve because the SLP gets to spend more of her time on the parts of speech therapy that require a human.

Done poorly, it is one of the easier categories of healthcare AI to fail in. The target population for speech therapy is, by definition, people whose speech is impaired in ways that confuse off-the-shelf speech recognition, off-the-shelf voice biomarker pipelines, and off-the-shelf acoustic feature extractors. A child with childhood apraxia of speech produces utterances that an automatic speech recognizer trained on typical adult speech transcribes incorrectly in ways that look, to the system, like ordinary recognition errors but that are, clinically, the entire point of what the SLP is measuring. An adult recovering from a stroke produces dysarthric speech with phonetic patterns that violate the assumptions every off-the-shelf speech model was built on. An older adult with Parkinson's-related dysarthria produces speech that the system might dismiss as low-quality audio when it is in fact the clinical signal the system is meant to score. The systems that work in this category are the ones that explicitly model impaired speech as the target, not as a degraded version of typical speech.

Beyond the population challenge, there is a clinical-evidence challenge. Speech-language pathology has decades of established assessment instruments (the Goldman-Fristoe Test of Articulation, the Hodson Assessment of Phonological Patterns, the Khan-Lewis Phonological Analysis, the Stuttering Severity Instrument, the Voice Handicap Index, the Frenchay Dysarthria Assessment, and a long list of others), each with its own scoring rubric, age norms, and reliability evidence. <!-- TODO: verify; the specific assessment-instrument landscape evolves and varies by region and clinical specialty --> A speech-therapy AI that produces a score without grounding in these established instruments is a number floating in space; SLPs reasonably ignore it. A speech-therapy AI that produces scores aligned with established instruments has to demonstrate, with appropriate validation studies, that its automatic scoring is consistent with expert SLP scoring on the populations it will be deployed against. This is a real evidence package, not a marketing claim.

There is also a workflow integration challenge that is harder than it sounds. SLPs work in school settings, hospital outpatient clinics, inpatient acute-care settings, skilled nursing facilities, early-intervention home visits, telepractice from a home office, and private-practice offices that range from solo practitioners to multi-site groups. The documentation systems range from full EHRs (Epic, Cerner, MEDITECH) to school-district student information systems (PowerSchool, Infinite Campus) to private-practice billing-and-documentation tools (SimplePractice, TheraNest, ClinicSource) to spiral notebooks. <!-- TODO: verify the current SLP documentation tooling landscape; this market evolves --> An AI tool that integrates well with one of these contexts often integrates poorly with the others. The SLP is the customer, not the IT department; if the tool does not fit her workflow, it does not get used.

And there is a regulatory question that the field is still working through. Some speech-therapy AI tools (autonomous fluency scoring for stuttering, autonomous articulation scoring for pediatric speech disorders) are diagnostic-adjacent enough to potentially fall under FDA's Software as a Medical Device framework. Other tools (between-session practice apps, parent-coaching tools, SLP productivity tools) are clearly outside the regulatory perimeter. The line between the two depends on the specific clinical claims the tool makes and the workflow placement. <!-- TODO: verify; the FDA's posture on speech-therapy AI tools continues to evolve --> Vendors that market themselves aggressively into the diagnostic-adjacent zone without an FDA strategy are building toward a regulatory cliff; vendors that stay clearly on the practice-and-monitoring side avoid the regulatory exposure but limit their clinical claims. The architectural choices interact with this strategic choice.

If you read recipe 10.4 (Medical Transcription), recipe 10.6 (Speech-to-Text for Telehealth Documentation), and recipe 10.8 (Voice Biomarker Detection), the audio infrastructure overlaps. The clinical question is fundamentally different. Speech-to-text recipes care about converting speech to accurate text and treat phonetic errors as errors. Voice biomarker recipes care about acoustic features that correlate with disease state. Speech-therapy assessment cares about what the patient is producing at the phonetic, prosodic, and fluency levels, against established clinical scoring rubrics, with the impaired speech as the explicit target. The same audio pipeline can in principle serve all three, but the downstream processing diverges substantially. Sharing the audio pipeline saves work on capture and storage; the analysis pipelines need their own design and validation per use case.

Let's get into how this actually works.

---

## The Technology: Speech as Clinical Data

### What Speech-Language Pathology Actually Measures

Before any AI enters the picture, it helps to understand what an SLP is measuring when she does an assessment. The categories matter because each category has a different set of acoustic and linguistic correlates, a different set of established assessment instruments, and a different shape of automation problem.

**Articulation.** The accuracy of phoneme production. A speaker producing /r/ as a /w/ has an articulation error; a speaker substituting /f/ for /θ/ ("fum" for "thumb") has an articulation error; a speaker omitting final consonants ("ca" for "cat") has an articulation pattern. Articulation assessment lists out the consonant and vowel inventory, marks each phoneme as produced correctly, substituted (and noted with what substitution), distorted, or omitted, and computes percent-consonants-correct or related summary metrics. Age norms tell the SLP whether a six-year-old saying "wabbit" for "rabbit" is within typical developmental variation (it is for most ages) or warrants intervention.

**Phonological patterns.** Errors in articulation often show patterns: final consonant deletion, cluster reduction (saying "top" for "stop"), fronting (saying "tat" for "cat"), backing, stopping, gliding. Phonological-pattern assessment categorizes the speaker's errors into these patterns and computes the percent-occurrence per pattern. Children with phonological disorders typically show systematic patterns rather than random errors; the patterns inform the therapy goals.

**Fluency.** The smoothness and rate of speech production. Disfluencies include repetitions (sound, syllable, word, phrase), prolongations (extending a sound), blocks (silent struggle), and secondary behaviors (visible tension, eye-blinks, head movements). The clinical question is whether a speaker's disfluencies meet criteria for stuttering or cluttering and, if so, how severe. The Stuttering Severity Instrument (SSI-4) and similar instruments give a structured scoring approach.

**Voice quality.** The acoustic and perceptual qualities of the voice itself: hoarseness, breathiness, strain, glottal-fry, pitch deviation, loudness deviation. The Voice Handicap Index (VHI) and the Consensus Auditory-Perceptual Evaluation of Voice (CAPE-V) are commonly used voice-assessment instruments. Voice-quality assessment is relevant for laryngeal pathologies, for post-radiation head-and-neck patients, for transgender voice training, and for occupational voice users (teachers, performers, clergy).

**Resonance.** The balance of nasal versus oral airflow. Hypernasality (excessive nasal airflow on non-nasal sounds, common in cleft-palate patients), hyponasality (insufficient nasal airflow on nasal sounds, common in nasal congestion or velopharyngeal insufficiency), and mixed-resonance patterns. Assessment uses both perceptual rating scales and instrumental measures (nasometry, where available).

**Prosody.** The rhythm, stress, and intonation of speech. Atypical prosody can be a feature of autism spectrum disorder, traumatic brain injury, right-hemisphere stroke, and other neurological conditions. Prosody assessment is more impressionistic than the categories above; structured assessment instruments exist but are less universally adopted.

**Language.** The content of what the speaker says, separately from how they produce sounds. Language assessment covers receptive language (what the speaker understands), expressive language (what the speaker can produce in terms of vocabulary, syntax, narrative structure), and pragmatic language (the social use of language). Children with developmental language disorder, adults with aphasia, and individuals on the autism spectrum are typical referral populations. Language assessment is heavier on transcript analysis and lighter on acoustic analysis.

**Motor speech disorders.** A category that crosses several of the above. Apraxia of speech (a motor-planning disorder, typically pediatric or post-stroke) and dysarthria (a motor-execution disorder, with multiple subtypes by underlying cause) require structured motor-speech assessment that examines articulatory precision, prosodic control, breath support, and the coordination across these systems.

**Cognitive-communication.** The interaction between cognition and communication: attention, working memory, executive function as they affect language production. Stroke patients, traumatic-brain-injury patients, and dementia patients often have cognitive-communication impairments that an SLP assesses and treats.

**Swallowing.** SLPs also assess and treat swallowing disorders (dysphagia), which is a different clinical domain from the speech-and-language work above and is out of scope for this recipe. Voice-and-speech assessment AI typically does not extend into dysphagia, which has its own instrumentation (modified barium swallow studies, fiberoptic endoscopic evaluation of swallowing).

The clinical question of "what is the SLP measuring" is, in practice, a combination of several of these categories per patient. A child with a phonological disorder may also have language delays. A stroke patient may have dysarthria, aphasia, and cognitive-communication impairment all at once. The assessment instruments combine and are interpreted together. The AI system that wants to be useful here has to be useful for the particular sub-questions the SLP is asking, not pretend to be useful for the broad question of "evaluate this person's speech."

### The Acoustic and Linguistic Feature Pipeline for SLP Work

The feature pipeline for speech-therapy assessment is similar in shape to the voice-biomarker pipeline (recipe 10.8), with substantially different feature emphasis.

**Phoneme-level alignment.** The most important primitive for articulation assessment is forced alignment: matching the audio to the expected phoneme sequence (which the system knows because the SLP has prompted the patient with a known stimulus word) and producing per-phoneme acoustic boundaries. The alignment lets the system score each phoneme against the expected target. Forced alignment on impaired speech is harder than on typical speech because the acoustic realization deviates from the expected target; the alignment algorithm has to be tolerant of the deviations the system is meant to be measuring. Pretrained acoustic models (often based on self-supervised speech representations like wav2vec 2.0 or HuBERT) provide the acoustic substrate; SLP-specific fine-tuning on labeled disordered-speech corpora produces alignment systems that handle impaired speech better than off-the-shelf alternatives.

**Phoneme classification with substitution and omission detection.** Once the system has per-phoneme alignment, the next step is classifying what the speaker actually produced versus the expected target. The system can identify substitutions (the speaker produced /w/ when /r/ was expected), omissions (the expected phoneme was not produced at all), and distortions (the phoneme is approximately correct but acoustically deviant from the typical realization). The classification is grounded in the established phonetic-feature framework: place, manner, voicing for consonants; height, backness, rounding for vowels. The output looks like an automatic version of the SLP's articulation inventory.

**Fluency event detection.** The fluency-assessment primitive is event detection: identifying repetitions, prolongations, and blocks in continuous speech. Repetition detection is acoustic-and-linguistic (the same syllable repeats; the same word repeats). Prolongation detection is acoustic (the duration of a sound exceeds the typical realization). Block detection is acoustic (a silent or strained pause within or between words at locations where fluent speech would not have one). Each event type has its own detection challenges; combined across event types, the system can compute disfluency rates and severity-instrument-aligned scores.

**Voice-quality acoustic analysis.** Voice-quality assessment uses the same acoustic features as voice biomarker pipelines (jitter, shimmer, harmonic-to-noise ratio, spectral tilt, formant analysis), with different downstream interpretation. The features feed into voice-quality scores aligned with established instruments (CAPE-V dimensions, VHI subscales) rather than into disease-specific biomarker scores.

**Speech-rate and prosodic analysis.** Articulation rate (syllables per second of articulated speech), speech rate (syllables per second including pauses), pause duration distributions, and pitch-contour features. These provide the prosodic signal for fluency assessment, dysarthria assessment, and motor-speech assessment broadly.

**Linguistic-feature extraction from transcripts.** When the patient is producing connected speech (a story-retell task, a picture-description task, a conversation), the transcript itself becomes a feature source. Lexical diversity, mean length of utterance, syntactic complexity, narrative coherence, idea density, and word-finding patterns all come from the transcript and are relevant for language-assessment work. The transcription primitive (recipe 10.4 or 10.6) feeds the linguistic-feature extractor.

**Comparison to age and population norms.** Raw feature values (percent-consonants-correct, articulation rate, lexical diversity) are interpreted against developmental and population norms. A six-year-old saying "wabbit" is within typical variation; a ten-year-old saying "wabbit" is not. A speech rate of 4.0 syllables per second is normal for an adult; it is slow for a child reading aloud. The normative reference data is part of the assessment infrastructure; the system needs population-appropriate norms for the patient being assessed, including pediatric-by-age norms, adult-by-age norms, and norms for specific clinical populations where they exist.

**Within-patient longitudinal comparison.** The clinically richest signal is often the patient's own change over time. Maya twelve weeks ago versus Maya today is a more reliable measure of progress than Maya today against the population norm. The system maintains per-patient longitudinal feature histories and surfaces deltas that exceed within-patient typical session-to-session variation.

### The Disordered-Speech Modeling Problem

The defining technical challenge for this recipe is that the target population produces speech that off-the-shelf speech models do not handle well. The mitigations are several, and combining them is more effective than any single one.

**Disordered-speech corpora for training and validation.** Public corpora exist for some categories of disordered speech: the TORGO database for dysarthric speech, the UASpeech corpus for cerebral-palsy-related speech impairment, the AphasiaBank corpus for post-stroke aphasia, the FluencyBank corpus for stuttering, and several others. <!-- TODO: verify; specific disordered-speech corpora and access terms evolve --> These corpora have known limitations (small populations, specific language coverage, specific severity distributions), and they are not sufficient on their own for production-grade systems, but they are the starting point. Institutional partnerships with academic medical centers and SLP graduate programs can extend the corpora with consented patient data over time.

**Disordered-speech-specific fine-tuning.** A speech model fine-tuned on disordered speech performs meaningfully better on disordered speech than the same architecture trained only on typical speech. The fine-tuning is per-disorder-category (a dysarthria model is different from an apraxia model, which is different from a fluency model), and ideally per-severity-band within disorder category. The architectural pattern is a shared base model with disorder-specific adaptation layers, deployed as separate inference paths per disorder type.

**Speaker-adaptive modeling.** Many disordered speakers have idiosyncratic acoustic patterns; a model that adapts to the speaker (using a few minutes of the speaker's speech to calibrate) outperforms a speaker-independent model. The speaker-adaptation infrastructure, where the system maintains a per-patient acoustic profile that improves over multiple sessions, is part of the longitudinal-monitoring story and one of the reasons this recipe benefits from the longitudinal architecture in particular.

**Multi-task and multi-instrument scoring.** A speech-therapy assessment system that scores multiple instruments simultaneously (articulation inventory, phonological-pattern analysis, intelligibility rating) from the same audio sample gets more value from the audio than a single-instrument scorer. The multi-task models share representations across instruments and are typically more robust than single-instrument equivalents.

**Confidence-aware scoring with explicit indeterminate outputs.** When the model is uncertain (because the acoustic input is ambiguous, because the patient's profile is outside the model's validation envelope, because the audio quality is insufficient), it produces an explicit "needs SLP review" output rather than a confident-looking score. This is the same pattern as voice biomarker scoring (recipe 10.8) and is essential for SLP trust.

**SLP-in-the-loop training data.** The most reliable training data for speech-therapy AI is data scored by SLPs against established assessment instruments. The infrastructure for capturing SLP scoring (within the system's normal workflow, with the SLP scoring assessments as part of clinical care and the scores feeding back as labeled data) is part of the long-term improvement story. This is analogous to the clinician-in-the-loop training data patterns common in radiology AI.

### Where the Field Has Moved

A few practical updates worth knowing.

**Self-supervised speech representations have improved disordered-speech modeling.** Models like wav2vec 2.0, HuBERT, and WavLM, fine-tuned on disordered-speech corpora, produce phoneme-alignment and acoustic-feature representations that handle disordered speech better than the older HMM-GMM-DNN pipelines. <!-- TODO: verify; the dominant pretrained-speech-model families continue to evolve --> Many production speech-therapy tools are built on top of these representations now.

**Pediatric-specific acoustic models are catching up.** Pediatric speech is acoustically different from adult speech (different fundamental frequencies, different formant frequencies, different articulation development), and pediatric-specific acoustic models perform better on pediatric assessment than adult-trained models. The available pediatric training data has grown, and pediatric model performance has improved correspondingly.

**FDA has taken interest in some speech-therapy AI tools.** A handful of speech-therapy AI products have engaged with the FDA's regulatory framework, including for stuttering assessment and some pediatric articulation tools. <!-- TODO: verify; specific recent clearances should be checked against FDA's current device databases --> The regulatory pathway is reachable but not common; most current speech-therapy AI products position themselves as practice-and-monitoring tools rather than diagnostic instruments to stay outside the regulatory perimeter.

**Telepractice has driven adoption.** The shift to telepractice during and after the COVID-19 pandemic created sustained demand for speech-therapy tools that can extend the SLP's reach across the camera. Asynchronous-practice apps, parent-coaching tools, and between-session monitoring tools all benefited. The clinical workflow has not fully reverted; many SLPs maintain a hybrid practice with both in-person and telepractice patients.

**Workflow integration with school SLP systems is an active area.** School-based SLPs handle a large share of pediatric speech-therapy caseloads. Integration with school-district student information systems and IEP management tools is an area where speech-therapy AI tools are improving but remain uneven. The school context has specific privacy and consent considerations under FERPA in addition to HIPAA when applicable.

**Multilingual speech-therapy tools are emerging slowly.** Most speech-therapy AI tools are English-first. Bilingual and multilingual tools that handle code-switching, English-Spanish bilingual articulation assessment, and language-specific phonological patterns are an active area of development but not yet mature. <!-- TODO: verify; the multilingual speech-therapy AI landscape is evolving -->

**Outcome-tracking integration with payer reimbursement is increasing.** Speech-therapy reimbursement is increasingly tied to outcomes data; AI-assisted documentation that produces structured outcomes data is becoming a competitive advantage for SLP practices that bill commercial insurance and Medicare. The structured-outcomes integration is part of the workflow value proposition, not just the clinical value proposition.

---

## General Architecture Pattern

A speech-therapy assessment and monitoring system decomposes into eight logical stages: SLP-driven session setup with stimulus selection and consent capture, audio capture with task-segmented acquisition, preprocessing and disordered-speech-tolerant feature extraction, per-instrument scoring with confidence assessment, longitudinal comparison against the patient's own baseline and against population norms, SLP review with edit-and-acknowledge workflow, documentation generation aligned with billing and outcome-tracking requirements, and longitudinal storage with progress-tracking analytics.

```text
┌─────── SESSION SETUP & CONSENT ──────────────────────────┐
│                                                           │
│   [SLP selects assessment instrument(s) and stimuli]      │
│    - Articulation inventory (Goldman-Fristoe-aligned,    │
│      Hodson-aligned, etc.)                                │
│    - Phonological-pattern analysis                        │
│    - Stuttering Severity Instrument (SSI-4)               │
│    - Voice Handicap Index (VHI), CAPE-V                   │
│    - Connected-speech tasks (story retell, picture        │
│      description, conversation)                           │
│    - Patient-specific stimulus customization              │
│   [Patient context capture]                               │
│    - Age, sex, primary language(s)                        │
│    - Prior assessment history (linked)                    │
│    - Current goals and target sounds                      │
│   [Consent capture]                                       │
│    - HIPAA authorization                                  │
│    - Voice-as-biometric disclosure where applicable       │
│    - Pediatric assent (developmentally appropriate)       │
│    - Parent/guardian consent for minors                   │
│    - FERPA considerations for school deployments          │
│           │                                               │
│           ▼                                               │
│   [Output: assessment session record with selected        │
│    instruments, stimulus list, patient context,           │
│    consent metadata]                                      │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── AUDIO CAPTURE WITH TASK SEGMENTATION ─────────────┐
│                                                           │
│   [Per-task audio capture]                                │
│    - Per-stimulus capture for articulation inventory      │
│    - Continuous capture for connected-speech tasks        │
│    - Per-trial capture for fluency probes                 │
│    - Sustained-vowel capture for voice quality            │
│   [Task-aware quality assessment]                         │
│    - Per-task SNR threshold                               │
│    - Per-task expected duration                           │
│    - Per-task speaker-only verification                   │
│   [Real-time recapture prompts on quality failure]        │
│   [Capture-device class identification]                   │
│    - In-clinic dedicated microphone                       │
│    - Telepractice video-call audio                        │
│    - Home-practice mobile-app capture                     │
│           │                                               │
│           ▼                                               │
│   [Output: task-segmented audio with per-task quality     │
│    scores and capture-device metadata]                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── PREPROCESSING & FEATURE EXTRACTION ───────────────┐
│                                                           │
│   [Voice activity detection per task segment]             │
│   [Forced alignment of audio to expected stimulus]        │
│    - Disordered-speech-tolerant alignment                 │
│    - Per-phoneme acoustic boundaries                      │
│    - Confidence per alignment decision                    │
│   [Phoneme classification and substitution detection]     │
│    - Substitution patterns identified                     │
│    - Omission detection                                   │
│    - Distortion characterization                          │
│   [Acoustic feature extraction]                           │
│    - Voice-quality features (jitter, shimmer, HNR)        │
│    - Prosodic features (rate, pause distribution, F0)     │
│    - Articulation features (formant trajectories,         │
│      voice-onset time, articulation rate)                 │
│   [Fluency event detection]                               │
│    - Repetitions (sound, syllable, word, phrase)          │
│    - Prolongations                                        │
│    - Blocks                                               │
│   [Linguistic feature extraction (connected speech)]      │
│    - Transcript via speech-to-text                        │
│    - Lexical diversity, MLU, syntactic complexity         │
│    - Narrative coherence, idea density                    │
│           │                                               │
│           ▼                                               │
│   [Output: per-task feature vectors with per-feature      │
│    confidence and disordered-speech tolerance metadata]   │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── PER-INSTRUMENT SCORING ───────────────────────────┐
│                                                           │
│   [Instrument-specific scoring engines]                   │
│    - Articulation: percent-consonants-correct, by         │
│      phoneme, by phonological pattern                     │
│    - Fluency: %SS (percent syllables stuttered),          │
│      severity-instrument-aligned scores                   │
│    - Voice: CAPE-V dimensions, VHI score estimation       │
│    - Language: norm-referenced lexical and syntactic      │
│      metrics                                              │
│    - Motor speech: dysarthria-subtype-aligned features    │
│   [Eligibility gate per instrument]                       │
│    - Patient profile within instrument validation envelope│
│    - Audio captured under expected conditions             │
│    - Sufficient task completion                           │
│   [Confidence and indeterminate handling]                 │
│    - Per-item confidence scoring                          │
│    - Items below confidence threshold flagged for SLP     │
│      review rather than auto-scored                       │
│    - Aggregate confidence on summary scores               │
│   [Population-norm comparison]                            │
│    - Age-and-sex-stratified norms applied                 │
│    - Severity classification per established cutoffs      │
│    - Norm provenance disclosed in output                  │
│           │                                               │
│           ▼                                               │
│   [Output: per-instrument scores with SLP-review flags    │
│    on uncertain items, normative-comparison context]      │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── LONGITUDINAL COMPARISON ──────────────────────────┐
│                                                           │
│   [Within-patient comparison to prior sessions]           │
│    - Per-instrument score deltas                          │
│    - Per-target-sound progress on therapy goals           │
│    - Generalization tracking (carryover from elicited     │
│      to spontaneous speech)                               │
│    - Within-patient typical variation accounted for       │
│   [Goal-tracking integration]                             │
│    - Progress on each active therapy goal                 │
│    - Goal-attainment-scaling alignment                    │
│    - Goal modifications suggested where indicated         │
│   [Cross-session pattern detection]                       │
│    - Plateau detection                                    │
│    - Regression detection                                 │
│    - Acceleration detection                               │
│           │                                               │
│           ▼                                               │
│   [Output: progress summary with goal-by-goal status,     │
│    flagged trajectory patterns]                           │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── SLP REVIEW & EDIT ────────────────────────────────┐
│                                                           │
│   [SLP-facing review interface]                           │
│    - Per-item scoring shown with confidence               │
│    - Items flagged for review highlighted                 │
│    - Audio playback for any item                          │
│    - Side-by-side comparison with prior sessions          │
│   [SLP edit workflow]                                     │
│    - Per-item override with reasoning capture             │
│    - Bulk acceptance for high-confidence items            │
│    - Free-text clinical observations                      │
│   [Clinical interpretation aided by SLP]                  │
│    - Diagnosis or working hypothesis                      │
│    - Goal modifications                                   │
│    - Recommended therapy frequency and modality           │
│    - Discharge-readiness assessment if applicable         │
│           │                                               │
│           ▼                                               │
│   [Output: SLP-validated assessment with edit history,    │
│    clinical interpretation, and feedback signal for       │
│    model improvement]                                     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── DOCUMENTATION GENERATION ─────────────────────────┐
│                                                           │
│   [Assessment-report generation]                          │
│    - Standard SLP assessment-report structure             │
│    - Instrument-specific results sections                 │
│    - Comparison to prior sessions                         │
│    - Clinical interpretation                              │
│    - Goals and recommendations                            │
│   [Billing-aligned outcome documentation]                 │
│    - CPT-code-specific documentation requirements         │
│    - Outcome-measure documentation for value-based        │
│      contracts                                            │
│    - IEP-aligned documentation for school SLPs            │
│   [Plain-language patient/parent summary]                 │
│    - Reading-level appropriate                            │
│    - Action-oriented home practice recommendations        │
│   [EHR/SIS write-back]                                    │
│    - FHIR Observation resources                           │
│    - PDF assessment report                                │
│    - Discrete data elements per documentation system      │
│           │                                               │
│           ▼                                               │
│   [Output: clinically and operationally complete          │
│    documentation package]                                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── LONGITUDINAL STORAGE & PROGRESS ANALYTICS ────────┐
│                                                           │
│   [Per-patient longitudinal record]                       │
│    - Session-by-session feature history                   │
│    - Goal-attainment trajectory                           │
│    - Therapy-modality and frequency history               │
│   [Caseload-level analytics for SLP]                      │
│    - Patients on caseload with progress patterns          │
│    - Patients flagged for goal modification               │
│    - Patients ready for discharge consideration           │
│   [Practice-level analytics for clinical leadership]      │
│    - Outcomes by therapist                                │
│    - Outcomes by diagnosis category                       │
│    - Outcomes by therapy modality                         │
│   [Audio retention per consent and policy]                │
│   [Post-deployment surveillance]                          │
│    - Per-population accuracy vs. SLP gold-standard        │
│    - Drift detection over time                            │
│    - Re-validation triggers                               │
│           │                                               │
│           ▼                                               │
│   [Output: longitudinal record, analytics dashboards,     │
│    surveillance metrics]                                  │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points the architecture has to bake in.

**The SLP is the customer.** The system does not replace the SLP; it augments her workflow. Every architectural choice that adds friction to the SLP's work for the system's convenience is a choice that gets the system not used. The SLP-review interface, the edit-and-override workflow, and the documentation generation that follows the SLP's preferred report structure are not nice-to-haves; they are the system's reason for existing.

**Disordered speech is the explicit target, not a degraded edge case.** The acoustic models, the alignment algorithms, the phoneme classifiers, and the linguistic-feature extractors all need to be built and validated against disordered speech. Off-the-shelf speech recognition tuned on typical speech is a starting point at best; production systems require disordered-speech fine-tuning, disordered-speech validation cohorts, and explicit per-population performance evidence.

**Pediatric and adult populations are different products.** Pediatric speech assessment, adult speech assessment, and elderly speech assessment have meaningfully different acoustic profiles, different normative references, different assessment instruments, different consent considerations, and different workflow contexts. A system that covers all three covers them as separate validated profiles rather than as a single model with parameters tweaked.

**Established assessment instruments anchor clinical credibility.** A score that does not align with an established instrument is a number floating in space; SLPs reasonably ignore it. The system's outputs map to established instruments (Goldman-Fristoe-aligned, Hodson-aligned, SSI-4-aligned, CAPE-V-aligned, VHI-aligned, and so on) with explicit disclosure of the alignment method and validation evidence per instrument. <!-- TODO: verify the specific instruments and current versions in clinical use; the assessment-instrument landscape evolves -->

**Per-item confidence scoring with SLP-review flags is essential.** The system scores each test item with a confidence value. Items below the threshold are flagged for SLP review rather than auto-scored. The aggregate score reflects the auto-scored items plus the SLP-reviewed items. Pretending the system is confidently right about every item, when it is not, breaks SLP trust and produces clinical errors.

**Longitudinal trajectory often beats single-session assessment.** Within-patient progress is the clinically richest signal. The architecture maintains per-patient feature histories, computes within-patient deltas appropriately calibrated to within-patient typical variation, and surfaces the trajectory alongside the single-session score.

**Workflow placement determines regulatory exposure.** A tool that produces autonomous diagnostic claims is in a different regulatory category from a tool that supports SLP workflow with SLP-in-the-loop scoring. The architecture supports both placements, with explicit configuration per deployment context. The institution and the vendor are clear about which regulatory category they are operating in.

**School-context deployments have specific privacy considerations.** School-based SLP work falls under FERPA in addition to HIPAA where applicable. Consent for minors requires parent or guardian authorization, and the school's existing processes for educational records apply. The architecture supports school-context configurations with appropriate consent and storage segregation.

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Add a "Pediatric, FERPA, COPPA, and School-Context Profile" subsection specifying four overlapping deployment contexts (clinic-based pediatric, school-based pediatric, direct-to-child interface, adult speech-therapy) with per-profile differences in consent flow (FERPA-aligned with per-state educational-records retention; COPPA-aligned verifiable parental consent; HIPAA-aligned), access control (FERPA-aligned with school-employee-legitimate-educational-interest plus parent-access-by-default; HIPAA-aligned with treating-provider plus patient/legal-representative; dual-jurisdiction handling for billed school services), documentation generation (IEP-aligned for school deployments; HIPAA-aligned standard for clinic deployments), age-of-majority handoff (per-state age detection, notice generation, consent-authority transition from parent-on-behalf to patient-on-own-behalf), and the pediatric-assent-versus-parent-consent gradient for older pediatric patients. Update Step 1C consent capture and audit_record at Step 8 with deployment-context flags. -->


**Telepractice audio differs from in-clinic audio.** Telepractice introduces video-call codec compression, network packet loss, ambient home noise, and microphone variability. The acoustic models, the quality assessment, and the eligibility gating all need telepractice-specific configuration. The system either constrains the telepractice capture (specific recommended apps, microphone guidance) or validates broadly across realistic telepractice conditions.

<!-- TODO (TechWriter): Expert review N1 (MEDIUM). Add a "Per-Device-Pattern Audio Path Authentication and Encryption" paragraph specifying per-device-pattern data-in-transit posture (TLS-in-transit minimum; mTLS preferred for in-clinic dedicated microphones; per-encounter session tokens; device-attestation for mobile-app and home-practice patterns; verifiable parental consent for pediatric direct-to-child interfaces per Finding S3; parent-co-presence verification for pediatric telepractice; per-session patient-pairing under FERPA-aligned access controls for school-based shared equipment), per-device-pattern BAA scope, per-device-class certification (HITRUST, SOC 2 Type II, FDA SaMD where applicable), and audit-record propagation of the device-attestation context. -->

**Home-practice and parent-coaching applications are different products from clinical assessment.** A child practicing target sounds at home with a mobile app, with the system providing immediate feedback, is a different product context from an SLP performing an annual reassessment. The architecture supports both with shared infrastructure but distinct workflow surfaces and distinct clinical-action mappings.

**Multilingual speakers warrant language-aware pipelines, not just translated stimuli.** A bilingual Spanish-English child has phonological-pattern profiles that differ from monolingual English children. Articulation assessment in bilingual populations requires bilingual-aware norms, language-specific phoneme models, and explicit handling of code-switching during assessment. Translating the stimulus list is not enough.

**Audio retention policy is bounded by consent and protected by encryption.** Voice samples from speech-therapy assessment are biometric data. Retention is bounded to what consent supports and what clinical and regulatory needs require. Audio retention beyond the immediate scoring window benefits the longitudinal-comparison and model-improvement workflows; the institution's privacy officer reviews the retention policy explicitly.

<!-- TODO (TechWriter): Expert review S1 (HIGH). Promote voice-as-biometric-data governance from passing reference to architectural primitive. Add a "Voice-as-Biometric-Data Governance Scaffolding with Pediatric-Records, FERPA, and COPPA Layering" subsection specifying: per-jurisdiction biometric-data consent at collection (BIPA, CUBI, Washington biometric-data law, GDPR Article 9 for EU patients) with parent-on-behalf authority for minors and patient-on-own-behalf handoff at age of majority; disclosure-accounting log per use; right-to-deletion workflow with deletion-propagation across audio, feature vectors, per-item scores, longitudinal trajectory, goal-attainment data, and disclosure-accounting log entries; per-jurisdiction key-management with cryptographic erasure as deletion primitive; feature-vector biometric classification; pediatric-records-extending-to-age-of-majority-plus-X retention as architectural primitive (per-state variation); synthetic-voice-detection / voice-cloning defense with pediatric-amplification; FERPA-aligned access controls for school deployments; COPPA-aligned verifiable parental consent for direct-to-child interfaces. Update Step 1C consent capture and subsequent steps to append disclosure-accounting log entries. Add a Step 9 deletion-propagation pseudocode pattern with parent-on-behalf-to-patient-on-own-behalf authority handoff. Add a Production-Gaps subsection naming privacy officer plus institutional-records-management plus FERPA records-officer as canonical owners. -->


---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter10.09-architecture). The Python example is linked from there.

## The Honest Take

Speech-therapy assessment and monitoring is the recipe in this chapter where the workflow integration challenge is largest, where the SLP-as-customer framing matters most, and where the difference between "useful clinical tool" and "annoying productivity drag" is determined more by interface and workflow choices than by the underlying AI accuracy. The technology works. The question is whether the institution builds the system in ways that the SLPs actually want to use.

The first trap is treating SLPs as a cost center to be automated rather than as the customer to be served. The most-criticized speech-therapy AI products of the last five years have been the ones positioned as replacing the SLP rather than augmenting her. SLPs have professional expertise, advanced degrees, and clinical-licensure obligations that an AI system cannot replicate. They also have caseloads that would be smaller and outcomes that would be better if they could spend less time transcribing their own observations and more time delivering therapy. The AI tools that succeed in this space are the ones SLPs choose to use because they save time and make the work more clinically rewarding; the ones that fail are the ones that try to take the work away rather than make it easier.

The second trap is underweighting how different disordered speech is from typical speech. Off-the-shelf speech recognition was not built for dysarthric speech, apraxic speech, or stuttering. The same off-the-shelf models, applied without disordered-speech-specific fine-tuning and validation, produce confidently-wrong scoring on the population the system is meant to serve. The mitigations are not subtle: disordered-speech corpora for training, per-population fine-tuning, per-severity-band validation, and conservative auto-scoring with explicit SLP-review flags for ambiguous items. Skipping the disordered-speech-specific work and hoping that off-the-shelf models will handle the population is a recurring failure mode.

The third trap is treating pediatric and adult populations as variations on the same problem. Pediatric speech is acoustically different (different fundamental frequencies, different formant frequencies, different developmental trajectories), pediatric assessment instruments are different (developmental-stage-appropriate stimuli, age-graded norms), pediatric consent is different (parent consent plus age-appropriate assent, FERPA in school settings, COPPA for direct-to-child interfaces, long-horizon record retention), and pediatric workflow contexts are different (school-based SLP work has its own documentation systems and reimbursement models that differ from clinic-based work). A system that pretends to handle both populations with one configuration handles both populations badly.

The fourth trap is underweighting the per-instrument and per-population validation work. A model that is accurate on the GFTA-3 stimulus list at age 6 is not necessarily accurate on the same stimulus list at age 4 or at age 10, on a different articulation instrument, or on a connected-speech task. Each combination of instrument and population deserves its own validation. The institution that ships a single model across many combinations and assumes the validation evidence transfers will discover the gaps the hard way.

The fifth trap is underweighting cross-dialect generalization. The most common training data for English speech-therapy AI is General American English. Speakers of African American English, Spanish-influenced English, regional dialects, and other variations are systematically underserved. The dialect issue is especially acute because what constitutes a "substitution error" in one dialect is the typical realization in another; a system that does not handle the dialect distinction will misclassify typical dialect features as articulation errors. The mitigations require explicit dialect identification at session setup, dialect-aware norm references, and ongoing investment in dialect-coverage expansion.

The sixth trap is underweighting the workflow heterogeneity across deployment contexts. Hospital outpatient, school-based, private practice, early intervention, telepractice, and inpatient acute care are different products that share infrastructure. The documentation system targets, the consent requirements, the reimbursement models, the population profiles, and the clinical-workflow patterns differ substantially. A single deployment that pretends to fit all contexts fits none well. The successful path is per-context configuration and validation, with explicit positioning per context.

The seventh trap is underweighting per-item confidence-based SLP-review flagging. The system that auto-scores every item with apparent confidence (regardless of the actual model uncertainty) breaks SLP trust the first time the SLP catches a confident-looking error. The system that explicitly flags low-confidence items for SLP review, accepts the SLP's overrides as the gold standard, and uses the override data to improve the model over time builds the trust that supports adoption. The architectural choice between these two patterns is the choice between a system that SLPs work around and a system that SLPs work with.

The eighth trap is underweighting longitudinal context. Single-session scoring is the weakest version of what the system can offer; longitudinal trajectory analysis (this child's articulation has improved meaningfully on the targeted sounds since the last assessment, this adult's dysarthria severity is stable but not improving despite three months of therapy, this fluency disorder is showing the post-intervention pattern that suggests the therapy approach is working) is where the clinical signal is richest. The architecture that supports longitudinal analysis from day one gets to use the more reliable signal; the system that ships single-session scoring with no longitudinal layer ships the less useful version.

The ninth trap is the autonomous-scoring temptation. The most attractive product framing is full-autonomous scoring (the SLP records audio, a complete report drops out the other end, the SLP barely has to look at it). The clinically-defensible framing is SLP-in-the-loop with confidence-based review flags. The autonomous framing fails for the same reasons it fails in voice biomarkers and in radiology AI: the cases where the model is wrong are the cases the workflow most needs to catch, and removing the human reviewer removes the safety net that catches the systematic errors. Most of the speech-therapy AI products that have shipped responsibly are positioned as SLP augmentation; the products that pursued autonomous-scoring positioning have either struggled in market or generated enough clinical-quality concerns to walk back the positioning.

The tenth trap is treating the LLM-generated report as ground truth. Bedrock can generate beautifully-formatted SLP reports and parent-friendly summaries from the structured scoring data, and the temptation is to ship them with minimal review. The reports are LLM-generated artifacts and need faithfulness checks: schema validation, citation grounding to source data, secondary checks against the structured scoring, and explicit human review for high-stakes reports. The same goes for family summaries: reading-level validation, Guardrails coverage, and explicit framing as practice-and-progress communication rather than diagnostic communication.

The eleventh trap is shipping speech-therapy AI without home-practice and parent-coaching applications when those are the place the technology often delivers the most clinical value. A patient who attends one 45-minute therapy session per week and does no home practice is dependent on the SLP for all skill-building work; a patient with effective home-practice support extends the SLP's reach by an order of magnitude. The home-practice app is a different product context with different scoring rubrics and different clinical positioning, but it is often the part of the technology stack that makes the biggest patient-outcome difference. Build the home-practice infrastructure as a first-class deployment context, not as an afterthought.

The twelfth trap is underweighting reimbursement-and-outcome documentation. SLP practices that bill commercial insurance, Medicare, or school-district funding all have specific outcome-documentation requirements that drive the reimbursement. AI tools that produce reimbursement-aligned documentation for free are highly attractive; AI tools that produce clinical-grade scoring without the reimbursement-aligned wrapper add work for the SLP rather than save it. Build the outcome-tracking integration as part of the productivity value proposition, not as a tangential extension.

The thing that surprises engineers coming from medical-imaging AI backgrounds is how much of the value is in the workflow integration rather than in the AI itself. A radiology AI tool can be valuable as a workstation plugin that surfaces detection candidates; the radiologist still does the reading, but the candidates are useful. A speech-therapy AI tool that surfaces phoneme-level scoring without integrating with the SLP's documentation, billing, and goal-tracking workflows is a tool the SLP has to reconcile with her existing workflow rather than a tool that fits into it. The workflow integration work is harder than the AI work, in many cases, and it is the work that determines adoption.

The thing that surprises engineers coming from voice biomarker backgrounds is how much more accessible the clinical evidence pathway is. Voice biomarker work for novel disease detection requires multi-year clinical-research validation studies, FDA SaMD pathways, and rigorous clinical-evidence packages. Speech-therapy AI work that aligns with established assessment instruments has a much shorter evidence-to-deployment path because the clinical-credibility infrastructure already exists; the work is demonstrating that the AI scoring is consistent with SLP scoring on the established instruments. This is still real validation work, but it is closer to "instrument calibration" than to "novel biomarker discovery."

The thing about Amazon SageMaker specifically: it is the right substrate for hosting the disordered-speech-aware acoustic models because the models are typically not catalog services, they need per-population endpoints, and they benefit from the cost-management options for asynchronous batch scoring. The integration with the rest of the AWS data and security stack (KMS, VPC, IAM, CloudTrail) is the same maturity story as voice biomarker work in recipe 10.8, and the architectural patterns transfer directly.

The thing about Amazon Bedrock specifically: it is genuinely useful for the report-generation and family-summary parts of the work, where the AI is converting structured scoring data into well-formatted prose. The faithfulness and grounding work is non-trivial; ship the report-generation pipeline with explicit verification, not as a trust-the-LLM black box.

The thing about Amazon HealthLake specifically: it works well for the FHIR-based clinical-deployment context. School-based SLP deployments often need different documentation system integration (school SIS systems rather than FHIR-based EHRs); the institutional integration layer translates between FHIR and the school SIS format as needed.

The thing about consent specifically: the pediatric consent workflow is more substantial than the adult consent workflow, with parent or guardian consent, age-appropriate assent, FERPA alignment for school deployments, COPPA alignment for direct-to-child interfaces, and long-horizon retention. Build the pediatric consent infrastructure as a first-class capability, not as a footnote to the adult-only consent flow.

The thing about the field's velocity: speech-therapy AI has been on a meaningful improvement trajectory over the past five years, particularly with the rise of self-supervised speech models that handle disordered speech better than older HMM-based approaches. The pace of improvement is likely to continue. The institution's deployment posture should support staged onboarding of new models, new instruments, and new populations as their evidence matures: a stable architectural pattern, validation gates that new models must clear, clinical-action-mapping processes that scale to new instruments, and post-deployment surveillance that monitors all deployed configurations.

The thing I would do differently the second time: invest more in the SLP-review interface and less in the autonomous-scoring accuracy chase. The largest determinant of adoption is whether the SLPs find the system valuable enough to use willingly and consistently. The largest determinant of clinical safety is whether the SLP-in-the-loop catches the items where the model is wrong. Both factors point at the SLP-review interface as the place where the system either succeeds or fails. Invest accordingly.

The last thing, because it is the one most often misunderstood: speech-therapy AI is not a substitute for SLP expertise; it is a multiplier on SLP capacity. The SLPs who adopt these tools effectively spend more of their time on the parts of speech therapy that require human expertise (clinical-judgment-driven goal-setting, motivational therapy interactions, parent coaching, complex differential-diagnosis reasoning) and less on the parts that the AI can handle (per-item articulation scoring, fluency-event counting, structured documentation generation). The institutions that frame the deployment this way realize the productivity benefit and the clinical-quality benefit; the institutions that frame the deployment as SLP replacement attract resistance from the SLP community and miss the productivity benefit they were trying to capture.

Speech-therapy assessment and monitoring, done well, is one of the more rewarding healthcare AI use cases. The clinical evidence pathway is more tractable than novel biomarker discovery, the workflow integration challenge is the genuine engineering work, the SLPs become enthusiastic users when the system fits their workflow, and the patient outcomes (more therapy hours per SLP, more home-practice support per patient, better longitudinal tracking) are real. The architectural pattern in this recipe supports doing it well; doing it well requires the SLP-as-customer framing, the disordered-speech-specific modeling, the per-population validation, the per-deployment-context configuration, and the workflow integration that turn an interesting technical capability into a clinically-useful product.

---

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, simplest analog. The audio capture and speech-recognition primitives appear here at much lower clinical stakes.
- **Recipe 10.2 (Voicemail Transcription and Classification):** Same chapter, asynchronous single-speaker analog. The async-audio-processing pattern is the closest pattern to the asynchronous speech-therapy scoring path.
- **Recipe 10.3 (Voice-to-Text for EHR Navigation):** Same chapter, single-speaker voice-input analog. Different goal but same audio-capture infrastructure foundation.
- **Recipe 10.4 (Medical Transcription / Dictation):** Same chapter, single-speaker high-quality-capture analog. The custom-vocabulary patterns from 10.4 inform the linguistic-feature pipelines for connected-speech analysis.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Same chapter, patient-facing voice-interaction analog. The patient-acceptance and consent patterns from 10.5 inform patient-facing home-practice deployments.
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Same chapter, telehealth-audio analog. The per-cohort accuracy discipline from 10.6 transfers directly to per-population speech-therapy validation discipline.
- **Recipe 10.7 (Ambient Clinical Documentation):** Same chapter, in-room conversational-audio analog. The shared in-room audio infrastructure and the SLP-augmentation workflow patterns are closely related.
- **Recipe 10.8 (Voice Biomarker Detection):** Same chapter, acoustic-feature-pipeline analog. Many of the architectural patterns (per-population validated models, eligibility gates, indeterminate-result handling, per-cohort calibration, post-deployment surveillance) transfer directly. The clinical question is different: voice biomarkers measure disease state from voice acoustics; speech-therapy assessment measures the speech production itself against established assessment instruments.
- **Recipe 10.10 (Multilingual Real-Time Medical Interpretation):** Same chapter, multilingual analog. The per-language pipeline patterns are shared with the multilingual speech-therapy variations.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2, LLM-driven patient-facing summary generation. The patient-and-parent-facing summary patterns from 2.5 apply directly to family-summary generation.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2, LLM-driven structured-data-to-prose generation. The SLP-report generation patterns are closely related.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4, personalization patterns. Home-practice prompt scheduling and parent-coaching content selection use related personalization patterns.
- **Recipe 7.x (Predictive Analytics chapter):** Chapter 7, risk scoring and trajectory analysis. Speech-therapy progress prediction and discharge-readiness scoring are predictive-analytics extensions of the longitudinal data.
- **Recipe 8.x (NLP chapter):** Chapter 8, traditional NLP. Linguistic-feature extraction from connected-speech transcripts uses traditional NLP primitives in addition to the LLM-driven extraction.

---

## Tags

`speech-voice-ai` · `speech-therapy` · `slp-augmentation` · `articulation-assessment` · `phonological-pattern-analysis` · `fluency-assessment` · `stuttering-severity-instrument` · `voice-quality-assessment` · `cape-v` · `vhi` · `dysarthria-assessment` · `aphasia-assessment` · `motor-speech-disorders` · `cleft-palate-resonance` · `pediatric-speech-disorders` · `disordered-speech-modeling` · `forced-alignment-disordered-speech` · `phoneme-classification` · `goldman-fristoe-aligned` · `hodson-aligned` · `slp-in-the-loop` · `confidence-based-review-flags` · `per-population-validation` · `cross-dialect-generalization` · `pediatric-norms` · `longitudinal-trajectory` · `goal-attainment-tracking` · `iep-integration` · `school-based-slp` · `telepractice` · `home-practice-app` · `parent-coaching` · `outcome-tracking` · `value-based-care` · `multilingual-articulation-assessment` · `bilingual-spanish-english` · `transgender-voice-training` · `samd` · `fda-clearance-considerations` · `post-deployment-surveillance` · `clinical-validation` · `biometric-data` · `bipa` · `ferpa` · `coppa` · `pediatric-consent` · `voice-as-pii` · `consent-management` · `slp-workflow-integration` · `documentation-generation` · `family-friendly-summary` · `sagemaker-endpoints` · `sagemaker-async-inference` · `sagemaker-model-monitor` · `sagemaker-clarify` · `transcribe-medical` · `bedrock` · `bedrock-guardrails` · `healthlake` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `complex` · `production-track` · `hipaa` · `phi-handling` · `audit-trail`

---

*← [Recipe 10.8: Voice Biomarker Detection](chapter10.08-voice-biomarker-detection) · [Chapter 10 Index](chapter10-preface) · [Recipe 10.10: Multilingual Real-Time Medical Interpretation](chapter10.10-multilingual-realtime-medical-interpretation) →*
