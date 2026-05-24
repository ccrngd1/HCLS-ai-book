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

```
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

**Telepractice audio differs from in-clinic audio.** Telepractice introduces video-call codec compression, network packet loss, ambient home noise, and microphone variability. The acoustic models, the quality assessment, and the eligibility gating all need telepractice-specific configuration. The system either constrains the telepractice capture (specific recommended apps, microphone guidance) or validates broadly across realistic telepractice conditions.

**Home-practice and parent-coaching applications are different products from clinical assessment.** A child practicing target sounds at home with a mobile app, with the system providing immediate feedback, is a different product context from an SLP performing an annual reassessment. The architecture supports both with shared infrastructure but distinct workflow surfaces and distinct clinical-action mappings.

**Multilingual speakers warrant language-aware pipelines, not just translated stimuli.** A bilingual Spanish-English child has phonological-pattern profiles that differ from monolingual English children. Articulation assessment in bilingual populations requires bilingual-aware norms, language-specific phoneme models, and explicit handling of code-switching during assessment. Translating the stimulus list is not enough.

**Audio retention policy is bounded by consent and protected by encryption.** Voice samples from speech-therapy assessment are biometric data. Retention is bounded to what consent supports and what clinical and regulatory needs require. Audio retention beyond the immediate scoring window benefits the longitudinal-comparison and model-improvement workflows; the institution's privacy officer reviews the retention policy explicitly.

---

## The AWS Implementation

### Why These Services

**Amazon S3 for audio sample storage with task-segmented organization.** Each session produces task-segmented audio clips: one per articulation-inventory stimulus, one continuous capture per connected-speech task, one per fluency probe, one per voice-quality task. S3 holds the audio with SSE-KMS encryption using customer-managed keys. The bucket structure organizes audio by session, task, and stimulus to support per-task feature extraction and SLP playback. Lifecycle rules enforce per-consent retention; a separate audit archive holds derived data for surveillance.

**Amazon SageMaker for disordered-speech-aware acoustic models.** The acoustic-model substrate for forced alignment, phoneme classification, and acoustic feature extraction is custom rather than catalog. Most production speech-therapy AI vendors ship models built on top of self-supervised speech representations (wav2vec 2.0, HuBERT, WavLM) fine-tuned on disordered-speech corpora and SLP-labeled clinical data. SageMaker hosts these models as endpoints, with per-population (pediatric, adult, dysarthric, fluent-disordered) endpoints reflecting the per-population validation. SageMaker Asynchronous Inference suits the per-session batch-scoring workload; real-time endpoints support the immediate-feedback use cases like home-practice apps.

**Amazon Transcribe Medical for connected-speech transcription where appropriate.** When the assessment includes connected-speech tasks (story retell, picture description, conversation) and the system extracts linguistic features from the transcript, Transcribe Medical produces the transcript. For typical-speech adults this works well; for severely disordered speech the off-the-shelf transcription accuracy is limited, and the system either accepts the limitation, uses a disordered-speech-fine-tuned ASR (typically deployed as a custom SageMaker endpoint), or flags transcription items for SLP review. Recipe 10.4 covers the medical-dictation transcribe pipeline; the lessons there about custom vocabulary and per-cohort accuracy apply here at lower volume but with the additional disordered-speech challenge.

**Amazon Bedrock for natural-language report generation and patient-friendly summary generation.** The SLP-facing assessment report (which combines the per-instrument scores, the longitudinal context, the clinical interpretation, and the goals and recommendations) is a natural-language artifact. Bedrock generates the prose around the structured scoring. The same model also generates the parent-and-patient-friendly summary at appropriate reading level. Recipe 2.5 (after-visit summary generation) and recipe 2.6 (clinical note summarization) cover the summarization patterns that apply here.

**Amazon Bedrock Guardrails for content filtering on patient-facing communications.** Patient and parent-facing summaries pass through Guardrails to ensure appropriate framing (this is an assessment, not a diagnosis), appropriate reading level, and absence of hallucinated content beyond what the structured scoring supports.

**AWS Lambda and AWS Step Functions for pipeline orchestration.** Per-stage Lambdas handle session setup, audio ingest, per-task feature extraction, per-instrument scoring, longitudinal comparison, SLP review handoff, documentation generation, and EHR/SIS write-back. Step Functions coordinates the stages with durable state. Per-task scoring fans out across stimulus items and fans back in for per-instrument aggregation; Step Functions Map state handles this naturally.

**AWS HealthLake for FHIR-based assessment storage.** Speech-therapy assessment results are Observation resources in FHIR terms (with per-instrument scores), DocumentReference resources for the assessment-report PDFs, and Goal resources for therapy goals. HealthLake stores the FHIR resources. For non-FHIR EHR integrations and school SIS integrations, the institutional integration layer translates the FHIR representation into the target system's format. <!-- TODO: verify HealthLake's current FHIR resource support including Goal and CarePlan resources -->

**Amazon DynamoDB for per-patient session state and longitudinal feature history.** The per-patient longitudinal store holds session-by-session feature vectors, per-goal progress trajectories, per-target-sound mastery curves, and per-instrument score histories. DynamoDB's partition-key-by-patient and sort-key-by-session-timestamp model supports the trajectory queries efficiently.

**Amazon API Gateway for SLP, patient, and parent-facing applications.** The SLP-facing assessment-and-review interface, the patient-facing or parent-facing home-practice app, and the administrative dashboards all access the system through API Gateway endpoints. Cognito or institutional IdP authentication applies, with per-role scopes (SLP, patient, parent, administrator).

**Amazon Cognito or institutional IdP via OIDC/SAML for authentication.** SLP authentication through the institutional identity provider with appropriate clinical-application scopes. Patient and parent authentication for home-practice and parent-coaching applications uses a patient-or-parent-identity flow with appropriate scopes. Pediatric users typically access the system under parent-account supervision rather than with their own credentials.

**AWS KMS for cryptographic key custody.** Customer-managed keys for the audio bucket, the feature-vector bucket, the longitudinal-store DynamoDB tables, the assessment-archive bucket, the documentation PDFs, and the audit archive. Voice samples and feature vectors use separate KMS keys for blast-radius containment.

**AWS Secrets Manager for EHR, SIS, and external-vendor API credentials.** The Lambdas that integrate with external documentation systems, with school SIS systems, and with any external speech-therapy vendor APIs hold their credentials in Secrets Manager with rotation per the institutional cadence.

**Amazon EventBridge for cross-system event flow.** Session-completed, scoring-completed, SLP-reviewed, and report-delivered events flow through EventBridge. Downstream consumers (the longitudinal-analytics pipeline, the practice-level dashboard, the home-practice prompt scheduler) react to events without coupling to the orchestration Lambdas.

**Amazon CloudWatch for operational metrics and alarms.** Per-stage latency, per-population scoring distributions, SLP-override rates per item type, indeterminate-result rates, audio-quality scores, post-deployment accuracy proxies. Alarms on per-population drift thresholds, on SLP-override-rate spikes, on indeterminate-result-rate spikes.

**AWS CloudTrail for API-level audit.** All access to PHI-bearing and biometric-bearing resources logged. SageMaker invocations logged. KMS key uses logged. CloudTrail logs in a dedicated bucket with Object Lock and lifecycle to S3 Glacier Deep Archive after 90 days.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon QuickSight (optional) for analytics and surveillance.** Audit and surveillance data streams to S3 via Firehose. Glue catalogs the data. Athena provides SQL access for the operational and post-market surveillance analytics. QuickSight renders the SLP-facing caseload dashboards and the practice-leadership outcomes dashboards.

**Amazon SageMaker Model Monitor and Clarify for ongoing model surveillance.** Model Monitor compares production inference against the training-time baseline for data-quality drift and model-quality drift. Clarify produces feature-attribution and bias reports per population on a scheduled cadence. Together, they support the per-population surveillance the clinical-quality posture requires. SLP-override data feeds back as a real-world performance signal alongside the model-monitor metrics.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Capture
      SLP[SLP or<br/>Patient Device]
      SETUP[Session Setup<br/>and Stimulus<br/>Selection]
      QA[Per-Task<br/>Audio QA]
    end

    subgraph Ingest
      APIGW_IN[API Gateway<br/>Capture API]
      L_INGEST[Lambda<br/>Session Ingest]
      S3_AUDIO[(S3 Audio<br/>Task-Segmented<br/>SSE-KMS)]
    end

    subgraph Pipeline
      SF[Step Functions<br/>Pipeline Orchestrator]
      L_FEAT[Lambda<br/>Feature Extraction]
      SM_ALIGN[(SageMaker<br/>Forced Alignment)]
      SM_PHON[(SageMaker<br/>Phoneme Classification)]
      SM_FLU[(SageMaker<br/>Fluency Detection)]
      SM_VQ[(SageMaker<br/>Voice Quality)]
      TS_MED[Transcribe Medical<br/>(connected speech)]
      L_SCORE[Lambda<br/>Per-Instrument<br/>Scoring]
      L_NORM[Lambda<br/>Norm-Referenced<br/>Comparison]
      L_LONG[Lambda<br/>Longitudinal<br/>Comparison]
      L_DOC[Lambda<br/>Documentation<br/>Generation]
      BR[Bedrock<br/>Report Generation]
      BR_GR[Bedrock<br/>Guardrails]
    end

    subgraph Storage
      S3_FEAT[(S3 Feature Vectors<br/>SSE-KMS)]
      DDB_LONG[(DynamoDB<br/>Longitudinal Store)]
      HL[HealthLake<br/>FHIR Observations<br/>and Goals]
      S3_REPORT[(S3 Report Archive<br/>SSE-KMS)]
      S3_AUDIT[(S3 Audit Archive<br/>Object Lock)]
    end

    subgraph Workflow
      APIGW_OUT[API Gateway<br/>SLP and Patient APIs]
      COGNITO[Cognito or<br/>Institutional IdP]
      EHR[EHR or SIS<br/>Integration]
      SLP_UI[SLP Review and<br/>Edit Interface]
      PATIENT_UI[Patient/Parent<br/>Home-Practice App]
      DASH[Practice<br/>Dashboard]
    end

    subgraph Surveillance
      EB[EventBridge]
      KIN[Kinesis Firehose]
      GLUE[Glue Catalog]
      ATH[Athena]
      QS[QuickSight]
      MM[SageMaker Model Monitor]
      CLAR[SageMaker Clarify]
      CW[CloudWatch]
      CT[CloudTrail]
    end

    subgraph Keys
      KMS[(AWS KMS<br/>Customer-Managed)]
      SM_SEC[(Secrets Manager<br/>EHR/SIS Creds)]
    end

    SLP --> SETUP
    SETUP --> QA
    QA --> APIGW_IN
    APIGW_IN --> L_INGEST
    L_INGEST --> S3_AUDIO
    S3_AUDIO --> SF
    SF --> L_FEAT
    L_FEAT --> SM_ALIGN
    L_FEAT --> SM_PHON
    L_FEAT --> SM_FLU
    L_FEAT --> SM_VQ
    L_FEAT --> TS_MED
    L_FEAT --> S3_FEAT
    SF --> L_SCORE
    L_SCORE --> L_NORM
    L_NORM --> L_LONG
    L_LONG --> DDB_LONG
    L_LONG --> L_DOC
    L_DOC --> BR
    BR --> BR_GR
    L_DOC --> S3_REPORT
    L_DOC --> HL
    L_DOC --> APIGW_OUT
    APIGW_OUT --> COGNITO
    APIGW_OUT --> SLP_UI
    APIGW_OUT --> PATIENT_UI
    APIGW_OUT --> DASH
    APIGW_OUT --> EHR
    EHR --> SM_SEC
    SF --> EB
    L_DOC --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    SM_ALIGN --> MM
    SM_PHON --> MM
    SM_FLU --> MM
    SM_VQ --> MM
    MM --> CLAR
    SF --> CW
    APIGW_OUT --> CT
    KMS --> S3_AUDIO
    KMS --> S3_FEAT
    KMS --> S3_REPORT
    KMS --> S3_AUDIT
    KMS --> DDB_LONG
    KMS --> SM_SEC

    style SM_ALIGN fill:#fcf,stroke:#333
    style SM_PHON fill:#fcf,stroke:#333
    style SM_FLU fill:#fcf,stroke:#333
    style SM_VQ fill:#fcf,stroke:#333
    style TS_MED fill:#fcf,stroke:#333
    style BR fill:#fcf,stroke:#333
    style BR_GR fill:#fcf,stroke:#333
    style MM fill:#fcf,stroke:#333
    style CLAR fill:#fcf,stroke:#333
    style DDB_LONG fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_FEAT fill:#cfc,stroke:#333
    style S3_REPORT fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
    style HL fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon S3, Amazon SageMaker (real-time and asynchronous endpoints, Model Monitor, Clarify), AWS Lambda, AWS Step Functions, Amazon Transcribe Medical, Amazon Bedrock (with Guardrails), AWS HealthLake, Amazon DynamoDB, Amazon API Gateway, Amazon Cognito, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally Amazon QuickSight for dashboards. |
| **Validated Models** | Disordered-speech-aware acoustic models per target population (pediatric articulation, adult dysarthria, fluency, voice quality). For most institutions this means selecting commercial vendors with appropriate validation evidence rather than building from scratch. Building requires multi-year clinical-research validation studies, IRB-approved cohort development, and SLP-graded labeled data. The architecture supports either pattern: third-party model integration through SageMaker endpoint or vendor API; institutionally-built models hosted on SageMaker endpoints. |
| **External Inputs** | Stimulus sets per assessment instrument (Goldman-Fristoe-aligned, Hodson-aligned, SSI-aligned, CAPE-V protocols, etc.); these are typically licensed from the assessment-instrument publishers. Population norms per age band, sex, and language background. SLP-labeled validation data per assessment instrument and per population. EHR or SIS write surface for assessment results. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The session-ingest Lambda has S3 write to the audio bucket only and Step Functions or EventBridge publish for the pipeline trigger. The feature-extraction Lambda has S3 read on the audio bucket and write on the feature bucket plus Transcribe Medical permissions and SageMaker invoke-endpoint for the alignment, phoneme-classification, fluency-detection, and voice-quality endpoints. The scoring Lambda has DynamoDB read access to norms tables and write access to per-session scoring tables. The documentation Lambda has Bedrock invoke-model permissions, S3 write to the report archive, and HealthLake write permissions. The EHR or SIS integration Lambda has Secrets Manager access for credentials and the system-specific egress. Avoid wildcard actions and resources in production. |
| **BAA and Compliance** | AWS BAA signed. Amazon S3, SageMaker, Lambda, Step Functions, Transcribe Medical, Bedrock (verify the specific models and regions covered), HealthLake, DynamoDB, API Gateway, Cognito, KMS, Secrets Manager, EventBridge, CloudWatch Logs, CloudTrail, Kinesis Firehose, Glue, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference). <!-- TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continue to evolve --> Voice samples are biometric data; biometric-data law (Illinois BIPA, Texas, Washington) applies in addition to HIPAA where the patient's jurisdiction triggers it. School deployments add FERPA considerations. Pediatric deployments add COPPA considerations for any direct-to-child interface elements. SaMD regulatory consideration for any model that produces autonomous diagnostic claims; pre-deployment FDA strategy review for indications where a SaMD pathway is relevant. IRB or institutional review for research-track deployments and for cohort-development data collection. |
| **Encryption** | Audio samples: SSE-KMS with customer-managed keys, retention bound to the consent terms (typically days to weeks for active therapy support, optionally longer with explicit consent). Feature vectors: SSE-KMS with separate customer-managed keys, retention as needed for longitudinal analysis and model improvement. Assessment reports and scoring records: SSE-KMS with customer-managed keys, retention aligned with medical-record retention or educational-record retention as applicable. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements, FERPA educational-record retention where applicable, state medical-records-retention rules including pediatric-extending-to-age-of-majority-plus-X, and institutional regulatory floor. DynamoDB tables, HealthLake datastore, Lambda environment variables, and Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all API calls. |
| **VPC** | Production: Lambdas that call back-office APIs (EHR FHIR, SIS systems, patient portal) run in VPC with controlled egress. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SageMaker Runtime, Transcribe Medical, Bedrock, Lambda. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where supported by the chosen container. |
| **CloudTrail** | Enabled with data events on the audio bucket, the feature bucket, the report archive bucket, the audit archive bucket, the DynamoDB tables, the Secrets Manager secrets, and the customer-managed KMS keys. SageMaker invocations logged. Bedrock invocations logged with metadata only (not full input/output, to avoid persisting biometric or PHI content in CloudTrail). Lambda invocations logged. API Gateway access logs enabled. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. |
| **Sample Data** | Public disordered-speech corpora for development and feature-pipeline validation. Examples include the TORGO database (dysarthric speech), the UASpeech corpus (cerebral-palsy-related speech), the FluencyBank corpus (stuttering), the AphasiaBank corpus (post-stroke aphasia), and the LANNA pediatric speech corpus; each has its own access terms that must be reviewed before integration. <!-- TODO: verify dataset URLs, current availability, and license terms before integration; the public disordered-speech dataset landscape evolves --> Synthetic capture-quality test signals for the audio QA pipeline. Never use uncoded production patient voice samples in development without explicit consent and IRB or institutional review. |
| **Cost Estimate** | At a mid-sized SLP practice or hospital outpatient SLP department scale (5,000 assessment sessions per year, mixed across pediatric articulation, adult dysarthria, and fluency assessments): SageMaker endpoint hosting and inference at typically $20,000-80,000 per year depending on real-time vs. asynchronous and instance class. Transcribe Medical at typically $2,000-8,000 per year. Bedrock at typically $1,000-4,000 per year for natural-language report generation. Lambda, Step Functions, S3, DynamoDB, HealthLake, CloudWatch, KMS, Secrets Manager, EventBridge, Kinesis Firehose, Glue, Athena total approximately $8,000-20,000 per year combined. Total AWS infrastructure typically $30,000-110,000 per year at this scale. The per-session cost is dominated by SageMaker model inference. The validation and clinical-evidence costs are typically much larger than the infrastructure costs at this scale. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon S3** | Task-segmented audio storage with consent-bounded retention; feature-vector storage; assessment-report PDF archive; audit archive with Object Lock |
| **Amazon SageMaker** | Per-population disordered-speech-aware model hosting (forced alignment, phoneme classification, fluency event detection, voice-quality scoring), real-time and asynchronous endpoints, post-deployment surveillance via Model Monitor and Clarify |
| **Amazon Transcribe Medical** | Connected-speech transcription for linguistic-feature extraction in language-assessment and connected-speech tasks |
| **Amazon Bedrock** | Natural-language assessment-report generation for SLP review; patient-and-parent-friendly summary generation at appropriate reading level |
| **Amazon Bedrock Guardrails** | Content filtering and contextual-grounding checks on patient-and-parent-facing communications |
| **AWS Lambda** | Per-stage orchestration for session ingest, feature extraction, per-instrument scoring, longitudinal comparison, documentation generation, EHR/SIS write |
| **AWS Step Functions** | Pipeline orchestration with Map state for per-stimulus parallel processing, durable state, retry semantics |
| **AWS HealthLake** | FHIR-based assessment Observation, Goal, and CarePlan resource storage with longitudinal-trajectory queries |
| **Amazon DynamoDB** | Per-patient longitudinal feature history, per-goal progress trajectories, per-target-sound mastery curves, per-session state |
| **Amazon API Gateway** | SLP-facing assessment-and-review API; patient-and-parent-facing home-practice API; administrative dashboard API |
| **Amazon Cognito** | SLP, patient, and parent authentication federated through institutional IdP with appropriate per-role scopes |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing and biometric-bearing data stores; separate keys per data class for blast-radius containment |
| **AWS Secrets Manager** | EHR, SIS, and external-vendor API credentials with rotation |
| **Amazon EventBridge** | Cross-system event flow for session, scoring, review, and report-delivery events |
| **Amazon CloudWatch** | Operational metrics, per-population drift alarms, SLP-override-rate alarms, indeterminate-result-rate alarms |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing and biometric-bearing resources and AI/ML service invocations |
| **Amazon Kinesis Data Firehose** | Streaming audit and surveillance data into the audit archive |
| **AWS Glue + Amazon Athena** | SQL access to audit and surveillance data for operational and clinical-quality analytics |
| **Amazon QuickSight (optional)** | SLP-facing caseload dashboards and practice-leadership outcomes dashboards |

---

### Code

#### Walkthrough

**Step 1: Set up the assessment session with the SLP-selected instruments, stimuli, and patient context.** When the SLP initiates an assessment, the system records which assessment instruments she has selected, generates the per-instrument stimulus list, captures patient context (age, language background, prior assessment history, current goals), and records the consent terms. Skip any of these and the resulting audio cannot be reliably scored: the system does not know which phonemes to expect, which norms to apply, or whether the SLP has the authorization to capture the audio.

```
ON session_initiated(slp_id, patient_id, selected_instruments,
                     deployment_context):

    // Step 1A: load patient context.
    patient_context = patient_table.get(patient_id)
    // patient_context includes age (derived from DOB),
    // primary language, dialect, prior assessment
    // history reference, current active therapy goals,
    // and patient-specific stimulus customizations.

    IF patient_context IS NULL:
        // Patient must be registered before assessment.
        RETURN { status: "PATIENT_NOT_FOUND" }

    // Step 1B: validate instrument applicability for
    // patient profile.
    applicable_instruments = []
    FOR instrument IN selected_instruments:
        instrument_def = lookup_instrument_definition(
            instrument_id: instrument)
        applicability = check_instrument_applicability(
            patient_context: patient_context,
            instrument_validation_envelope:
                instrument_def.validation_envelope)
        IF applicability.applicable:
            applicable_instruments.append({
                instrument_id: instrument,
                stimulus_list: customize_stimuli(
                    instrument_def.stimulus_list,
                    patient_context.stimulus_customizations),
                norm_reference: select_norm_reference(
                    instrument_def.available_norms,
                    patient_context.age,
                    patient_context.sex,
                    patient_context.primary_language)
            })
        ELSE:
            log_instrument_inapplicable(
                slp_id, patient_id, instrument,
                applicability.reason)

    IF len(applicable_instruments) == 0:
        RETURN { status: "NO_APPLICABLE_INSTRUMENTS" }

    // Step 1C: capture consent.
    // For minors, the parent or guardian provides
    // consent and the child provides developmentally-
    // appropriate assent. School deployments include
    // FERPA-aligned consent.
    consent_outcome = capture_consent(
        patient_id: patient_id,
        consent_type: "speech_therapy_assessment",
        deployment_context: deployment_context,
        // School deployments use FERPA-aligned consent;
        // clinic deployments use HIPAA-aligned consent;
        // both jurisdictions when applicable.
        applicable_frameworks:
            determine_consent_frameworks(
                patient_context, deployment_context),
        retention_terms: institutional_retention_policy,
        is_minor: patient_context.is_minor)

    IF NOT consent_outcome.granted:
        log_consent_decline(patient_id, consent_outcome)
        RETURN { status: "CONSENT_DECLINED" }

    // Step 1D: bootstrap the session record.
    session_id = generate_uuid()
    session_table.put({
        session_id: session_id,
        patient_id_hash: hash(patient_id),
        slp_id: slp_id,
        deployment_context: deployment_context,
        applicable_instruments: applicable_instruments,
        consent_id: consent_outcome.consent_id,
        prior_session_ref:
            lookup_most_recent_session(patient_id),
        active_goals:
            lookup_active_goals(patient_id),
        started_at: now(),
        status: "setup_complete"
    })

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_setup_complete",
        detail: {
            session_id: session_id,
            instrument_count: len(applicable_instruments)
        }
    }])

    RETURN {
        session_id: session_id,
        instruments: applicable_instruments,
        status: "READY_TO_CAPTURE"
    }
```

**Step 2: Capture audio per task with task-aware quality assessment and recapture prompts on failure.** Each instrument has its own task structure: articulation inventories elicit one stimulus at a time, fluency probes capture continuous speech segments, voice-quality tasks elicit sustained vowels. The capture system handles each task type appropriately, runs quality checks, and prompts for recapture on failure. Skip the per-task quality gating and the system silently scores low-quality audio, producing unreliable results that the SLP has to manually override.

```
FUNCTION capture_session_audio(session_id):
    state = session_table.get(session_id)
    captured_tasks = []

    FOR instrument IN state.applicable_instruments:
        FOR task IN instrument.stimulus_list:
            // Step 2A: present stimulus to patient.
            // The presentation may be a picture, a
            // recorded prompt, a written word, or an
            // SLP-spoken cue depending on instrument
            // and task.
            present_stimulus(task)

            // Step 2B: capture audio with task-aware
            // configuration.
            captured_audio =
                capture_audio_with_task_quality(
                    expected_duration_range:
                        task.expected_duration,
                    expected_speaker: "patient_only",
                    quality_thresholds:
                        task.quality_thresholds,
                    max_retries: task.max_retries,
                    recapture_prompt:
                        task.recapture_prompt_text)

            IF captured_audio.quality_score <
               task.minimum_quality:
                IF task.required:
                    log_capture_failure(
                        session_id, task, captured_audio)
                    RETURN {
                        status: "INSUFFICIENT_QUALITY",
                        failed_task: task.task_id
                    }
                ELSE:
                    // Optional task with insufficient
                    // quality is skipped; instrument
                    // scoring will mark the affected
                    // items as unscorable.
                    log_optional_task_skipped(
                        session_id, task, captured_audio)
                    CONTINUE

            captured_tasks.append({
                instrument_id: instrument.instrument_id,
                task_id: task.task_id,
                expected_target: task.expected_target,
                audio_ref: captured_audio.s3_uri,
                duration_seconds: captured_audio.duration,
                quality_score: captured_audio.quality_score,
                sample_rate: captured_audio.sample_rate,
                codec: captured_audio.codec,
                snr_db: captured_audio.snr_db,
                clipping_detected: captured_audio.clipping,
                speaker_only_verified:
                    captured_audio.speaker_only_verified
            })

    // Step 2C: persist captured tasks and emit pipeline
    // trigger.
    session_table.update(
        session_id: session_id,
        captured_tasks: captured_tasks,
        capture_completed_at: now(),
        status: "captured")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_captured",
        detail: {
            session_id: session_id,
            task_count: len(captured_tasks)
        }
    }])

    RETURN {
        session_id: session_id,
        status: "CAPTURED"
    }
```

**Step 3: Extract acoustic, phonetic, and linguistic features per task, with disordered-speech-tolerant alignment and confidence scoring.** Each task is processed through the appropriate feature pipeline: articulation tasks run through forced alignment and phoneme classification with substitution and omission detection; fluency tasks run through fluency-event detection; voice-quality tasks run through acoustic-feature extraction; connected-speech tasks add transcription and linguistic-feature extraction. Per-feature confidence is captured throughout. Skip the disordered-speech-tolerant configurations and the alignment fails on the population the system is meant to serve.

```
FUNCTION extract_features(session_id):
    state = session_table.get(session_id)
    feature_set = {
        session_id: session_id,
        per_task_features: {}
    }

    FOR captured_task IN state.captured_tasks:
        instrument_id = captured_task.instrument_id
        task_id = captured_task.task_id
        instrument_def = lookup_instrument_definition(
            instrument_id)
        task_def = lookup_task_definition(
            instrument_id, task_id)

        per_task = { task_id: task_id }

        // Step 3A: forced alignment.
        // Disordered-speech-aware alignment models are
        // selected based on patient population profile.
        alignment_endpoint = select_alignment_endpoint(
            patient_population:
                state.patient_population_profile,
            task_type: task_def.task_type)

        alignment_result = sagemaker_runtime.invoke_endpoint(
            endpoint_name: alignment_endpoint,
            content_type: "application/json",
            body: serialize({
                audio_ref: captured_task.audio_ref,
                expected_target:
                    captured_task.expected_target,
                language: state.patient_context.primary_language
            }))
        per_task.alignment = parse_alignment(
            alignment_result)

        // Step 3B: phoneme classification with
        // substitution, omission, and distortion
        // detection (for articulation tasks).
        IF task_def.task_type IN
                ["single_word_articulation",
                 "phonological_pattern_probe",
                 "diadochokinetic_rate"]:
            phoneme_endpoint =
                select_phoneme_endpoint(
                    patient_population:
                        state.patient_population_profile)
            phoneme_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: phoneme_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref,
                        alignment: per_task.alignment,
                        expected_phonemes:
                            task_def.expected_phonemes
                    }))
            per_task.phoneme_classification =
                parse_phoneme_classification(
                    phoneme_result)
            // Per-phoneme confidence captured for SLP-
            // review flagging at scoring step.

        // Step 3C: fluency event detection (for
        // fluency tasks).
        IF task_def.task_type IN
                ["fluency_probe_reading",
                 "fluency_probe_conversation",
                 "fluency_probe_picture_description"]:
            fluency_endpoint =
                select_fluency_endpoint()
            fluency_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: fluency_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref
                    }))
            per_task.fluency_events =
                parse_fluency_events(fluency_result)

        // Step 3D: voice-quality acoustic features
        // (for voice-quality tasks and any
        // sustained-vowel tasks).
        IF task_def.captures_voice_quality:
            vq_endpoint = select_voice_quality_endpoint()
            vq_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: vq_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref
                    }))
            per_task.voice_quality =
                parse_voice_quality(vq_result)

        // Step 3E: prosodic and rate features.
        per_task.prosodic =
            compute_prosodic_features(
                audio_ref: captured_task.audio_ref,
                alignment: per_task.alignment)

        // Step 3F: linguistic features for
        // connected-speech tasks.
        IF task_def.task_type IN
                ["connected_speech_story_retell",
                 "connected_speech_picture_description",
                 "connected_speech_conversation"]:
            transcript_job =
                transcribe_medical.start_job(
                    audio_ref: captured_task.audio_ref,
                    language:
                        state.patient_context.primary_language,
                    show_speaker_labels: false)
            // Note: in production, the transcribe job
            // should be handled asynchronously via
            // Step Functions wait-for-callback rather
            // than blocking inside this Lambda.
            wait_for_transcribe(transcript_job.job_name)
            transcript_text = retrieve_transcript(
                transcript_job.job_name)

            per_task.transcript = transcript_text
            per_task.linguistic_features =
                extract_linguistic_features(
                    transcript: transcript_text,
                    patient_age: state.patient_context.age,
                    requested_features:
                        task_def.linguistic_features)

        feature_set.per_task_features[task_id] = per_task

    // Step 3G: persist features.
    feature_set_archive.put(
        session_id: session_id,
        feature_set: feature_set)

    session_table.update(
        session_id: session_id,
        feature_set_archive_ref:
            f"s3://{FEATURE_BUCKET}/{session_id}/features.json",
        features_extracted_at: now(),
        status: "features_extracted")

    RETURN {
        feature_set_ref:
            session_table.get(session_id).feature_set_archive_ref
    }
```

**Step 4: Score each instrument with population-norm comparison and per-item confidence-based SLP-review flagging.** For each assessment instrument, the scoring engine combines per-task features into instrument-aligned scores (percent-consonants-correct for articulation, percent-syllables-stuttered for fluency, CAPE-V dimensions for voice quality, and so on). Items with model confidence below the threshold are flagged for SLP review rather than auto-scored. Population norms are applied to interpret the raw scores against age-and-sex-appropriate benchmarks. Skip the confidence-based flagging and the system silently misclassifies the items where it is uncertain, producing systematic errors that erode SLP trust.

```
FUNCTION score_instruments(session_id):
    state = session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    scores = {}

    FOR instrument IN state.applicable_instruments:
        instrument_def = lookup_instrument_definition(
            instrument.instrument_id)
        instrument_features = collect_features_for_instrument(
            feature_set, instrument)

        // Step 4A: per-item scoring with confidence.
        per_item_scores = []
        FOR item IN instrument_def.scoring_items:
            item_features = extract_item_features(
                instrument_features, item)
            item_score_result = score_item(
                item: item,
                features: item_features,
                scoring_rubric:
                    instrument_def.scoring_rubric)

            per_item_scores.append({
                item_id: item.item_id,
                expected_target: item.expected_target,
                observed:
                    item_score_result.observed,
                score_value:
                    item_score_result.score_value,
                model_confidence:
                    item_score_result.confidence,
                slp_review_flag:
                    item_score_result.confidence <
                    instrument_def.confidence_threshold,
                supporting_evidence:
                    item_score_result.evidence
            })

        // Step 4B: aggregate per-instrument summary
        // scores from auto-scored items and SLP-review-
        // pending items. Items pending SLP review are
        // excluded from the auto-summary; the final
        // summary is computed after SLP review.
        auto_scored_items = [
            i FOR i IN per_item_scores
            IF NOT i.slp_review_flag
        ]
        review_pending_items = [
            i FOR i IN per_item_scores
            IF i.slp_review_flag
        ]
        auto_summary = compute_instrument_summary(
            scoring_method:
                instrument_def.summary_method,
            items: auto_scored_items)

        // Step 4C: norm-referenced comparison.
        // The norm reference was selected at session
        // setup; here we apply it to the auto-summary.
        norm_comparison = apply_norms(
            instrument_id: instrument.instrument_id,
            auto_summary: auto_summary,
            norm_reference: instrument.norm_reference)

        // Step 4D: severity classification per
        // instrument-defined cutoffs.
        severity_classification = classify_severity(
            instrument_id: instrument.instrument_id,
            auto_summary: auto_summary,
            norm_comparison: norm_comparison,
            severity_cutoffs:
                instrument_def.severity_cutoffs)

        // Step 4E: phonological-pattern detection
        // (specifically for articulation instruments).
        phonological_patterns = NULL
        IF instrument_def.detects_phonological_patterns:
            phonological_patterns =
                detect_phonological_patterns(
                    per_item_scores: per_item_scores,
                    pattern_definitions:
                        instrument_def.pattern_definitions,
                    patient_age:
                        state.patient_context.age)

        scores[instrument.instrument_id] = {
            per_item_scores: per_item_scores,
            review_pending_count:
                len(review_pending_items),
            auto_summary: auto_summary,
            norm_comparison: norm_comparison,
            severity_classification:
                severity_classification,
            phonological_patterns:
                phonological_patterns,
            norm_reference_used:
                instrument.norm_reference.reference_id,
            scoring_model_versions:
                feature_set.model_versions,
            scored_at: now()
        }

    session_table.update(
        session_id: session_id,
        instrument_scores: scores,
        scoring_completed_at: now(),
        status: "scored")

    RETURN scores
```

**Step 5: Compute longitudinal comparison against the patient's prior sessions and against the active therapy goals.** Within-patient progress is the clinically richest signal. The system computes per-instrument deltas against the prior session and trend lines across all prior sessions, evaluates progress against each active therapy goal, and detects trajectory patterns (plateau, regression, acceleration). Skip the longitudinal layer and the SLP loses the comparison that is most useful for therapy-planning decisions.

```
FUNCTION compute_longitudinal(session_id):
    state = session_table.get(session_id)
    current_scores = state.instrument_scores
    longitudinal = {}

    // Step 5A: load prior sessions for this patient.
    prior_sessions = longitudinal_table.get_history(
        patient_id_hash: state.patient_id_hash,
        window_months: 24,
        limit: 20)

    // Step 5B: per-instrument longitudinal comparison.
    FOR instrument_id, current IN current_scores:
        prior_for_instrument = [
            s FOR s IN prior_sessions
            IF instrument_id IN s.instrument_scores
        ]
        IF len(prior_for_instrument) == 0:
            longitudinal[instrument_id] = {
                first_assessment: true,
                trajectory: NULL,
                most_recent_delta: NULL
            }
            CONTINUE

        most_recent = prior_for_instrument[0]
        most_recent_delta =
            compute_score_delta(
                current.auto_summary,
                most_recent.instrument_scores
                    [instrument_id].auto_summary,
                instrument_id: instrument_id)

        trajectory_analysis = analyze_trajectory(
            history: prior_for_instrument + [
                {
                    session_id: session_id,
                    timestamp: state.started_at,
                    instrument_scores: current_scores
                }
            ],
            instrument_id: instrument_id,
            within_patient_typical_variation:
                lookup_within_patient_variation(
                    state.patient_id_hash,
                    instrument_id))

        longitudinal[instrument_id] = {
            first_assessment: false,
            trajectory: trajectory_analysis,
            most_recent_delta: most_recent_delta,
            sessions_in_baseline:
                len(prior_for_instrument)
        }

    // Step 5C: per-goal progress evaluation.
    goal_progress = {}
    FOR goal IN state.active_goals:
        progress = evaluate_goal_progress(
            goal: goal,
            current_scores: current_scores,
            goal_evaluation_rubric:
                goal.evaluation_rubric)

        goal_progress[goal.goal_id] = {
            goal_text: goal.goal_text,
            target_metric: goal.target_metric,
            current_value: progress.current_value,
            baseline_value: goal.baseline_value,
            target_value: goal.target_value,
            percent_progress: progress.percent_progress,
            on_track: progress.on_track,
            recommended_action: progress.recommended_action
        }

    // Step 5D: trajectory pattern detection across
    // instruments and goals.
    trajectory_patterns = detect_trajectory_patterns(
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        pattern_thresholds: TRAJECTORY_PATTERN_THRESHOLDS)
    // trajectory_patterns may include flags such as
    // "plateau_across_multiple_instruments,"
    // "regression_in_specific_target_sounds,"
    // "acceleration_post_intervention_change," etc.

    session_table.update(
        session_id: session_id,
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        trajectory_patterns: trajectory_patterns,
        longitudinal_completed_at: now(),
        status: "longitudinal_computed")

    RETURN {
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        trajectory_patterns: trajectory_patterns
    }
```

**Step 6: Hand off to the SLP for review, override, and clinical interpretation.** The SLP-facing review interface presents the per-item scores with confidence values, highlights items flagged for review, supports audio playback for any item, and shows the longitudinal comparison alongside. The SLP can override individual item scores with a reasoning capture, accept high-confidence items in bulk, add free-text observations, and provide the clinical interpretation (working diagnosis, goal modifications, recommended therapy frequency, discharge readiness assessment). Skip the SLP-in-the-loop step and the system ships uncertain items as confident-looking auto-scores and loses the feedback signal for ongoing model improvement.

```
ON slp_review_initiated(session_id, slp_id):
    state = session_table.get(session_id)

    // Step 6A: build the SLP-facing review package.
    review_package = build_slp_review_package(
        session_id: session_id,
        instrument_scores: state.instrument_scores,
        longitudinal: state.longitudinal,
        goal_progress: state.goal_progress,
        trajectory_patterns: state.trajectory_patterns,
        captured_tasks: state.captured_tasks)

    // Per-item review prioritization: SLP-review-
    // flagged items appear first.

    session_table.update(
        session_id: session_id,
        slp_review_initiated_at: now(),
        reviewing_slp_id: slp_id,
        status: "slp_reviewing")

    RETURN review_package

ON slp_submits_review(session_id, slp_id, edits,
                      clinical_interpretation):
    state = session_table.get(session_id)

    // Step 6B: apply the SLP's per-item edits.
    edited_scores = state.instrument_scores
    edit_history = []
    FOR edit IN edits:
        original_value = lookup_item_score(
            edited_scores,
            edit.instrument_id,
            edit.item_id)
        apply_item_edit(edited_scores, edit)
        edit_history.append({
            instrument_id: edit.instrument_id,
            item_id: edit.item_id,
            original_value: original_value,
            new_value: edit.new_value,
            slp_reasoning: edit.reasoning,
            edited_by: slp_id,
            edited_at: now()
        })

    // Step 6C: recompute per-instrument summaries
    // including all items (auto-scored plus SLP-
    // edited).
    final_summaries = {}
    FOR instrument_id, scores IN edited_scores:
        instrument_def = lookup_instrument_definition(
            instrument_id)
        final_summary = compute_instrument_summary(
            scoring_method:
                instrument_def.summary_method,
            items: scores.per_item_scores)
        final_norm_comparison = apply_norms(
            instrument_id: instrument_id,
            auto_summary: final_summary,
            norm_reference: scores.norm_reference_used)
        final_severity = classify_severity(
            instrument_id: instrument_id,
            auto_summary: final_summary,
            norm_comparison: final_norm_comparison,
            severity_cutoffs:
                instrument_def.severity_cutoffs)
        final_summaries[instrument_id] = {
            final_summary: final_summary,
            final_norm_comparison: final_norm_comparison,
            final_severity: final_severity
        }

    // Step 6D: capture the clinical interpretation.
    clinical_record = {
        working_diagnosis_or_hypothesis:
            clinical_interpretation.diagnosis,
        goal_modifications:
            clinical_interpretation.goal_modifications,
        new_goals:
            clinical_interpretation.new_goals,
        recommended_therapy_frequency:
            clinical_interpretation.therapy_frequency,
        recommended_therapy_modality:
            clinical_interpretation.therapy_modality,
        discharge_readiness:
            clinical_interpretation.discharge_readiness,
        free_text_observations:
            clinical_interpretation.observations,
        finalized_by_slp: slp_id,
        finalized_at: now()
    }

    session_table.update(
        session_id: session_id,
        edited_scores: edited_scores,
        final_summaries: final_summaries,
        edit_history: edit_history,
        clinical_record: clinical_record,
        slp_review_completed_at: now(),
        status: "slp_review_complete")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "slp_review_complete",
        detail: {
            session_id: session_id,
            edit_count: len(edit_history)
        }
    }])

    RETURN { status: "REVIEW_COMPLETE" }
```

**Step 7: Generate the assessment-report documentation, the patient-and-parent-friendly summary, and the EHR or SIS write-back.** The system generates a structured assessment report from the SLP-validated scores, the clinical interpretation, and the longitudinal context. It also generates a parent-and-patient-friendly summary at appropriate reading level, with home-practice recommendations. The documentation flows to the EHR (for clinical settings) or the school SIS (for school deployments) as discrete data, FHIR resources, and PDF artifacts. Skip the structured documentation and the SLP loses the productivity benefit; skip the patient-friendly summary and parents and patients are left with clinical-jargon outputs they cannot act on.

```
FUNCTION generate_documentation(session_id):
    state = session_table.get(session_id)

    // Step 7A: SLP-facing assessment report.
    slp_report_input = {
        session_metadata: extract_metadata(state),
        instrument_results: state.final_summaries,
        per_item_detail: state.edited_scores,
        longitudinal: state.longitudinal,
        goal_progress: state.goal_progress,
        clinical_record: state.clinical_record,
        edit_history: state.edit_history
    }

    slp_report = bedrock.invoke_model(
        model_id: REPORT_GENERATION_MODEL,
        prompt: build_report_prompt(
            input: slp_report_input,
            template: SLP_REPORT_TEMPLATE,
            // Style guide: structured, profession-
            // standard SLP assessment-report format
            // (history, instruments-administered,
            // results-by-instrument, clinical-impressions,
            // goals-and-recommendations).
            ),
        guardrail_id: REPORT_GUARDRAIL_ID,
        response_format: {
            type: "json_schema",
            schema: SLP_REPORT_SCHEMA
        },
        max_tokens: 3000)

    // Step 7B: parent-and-patient-friendly summary.
    family_summary_input = {
        session_metadata: extract_metadata(state),
        instrument_results_simplified:
            simplify_for_family(state.final_summaries),
        progress_highlights:
            extract_progress_highlights(
                state.goal_progress),
        home_practice_recommendations:
            derive_home_practice(state.clinical_record),
        target_reading_level:
            determine_reading_level_for_family(
                state.patient_context)
    }

    family_summary = bedrock.invoke_model(
        model_id: SUMMARY_GENERATION_MODEL,
        prompt: build_family_summary_prompt(
            input: family_summary_input,
            template: FAMILY_SUMMARY_TEMPLATE),
        guardrail_id: FAMILY_COMMUNICATION_GUARDRAIL,
        response_format: {
            type: "json_schema",
            schema: FAMILY_SUMMARY_SCHEMA
        },
        max_tokens: 800)

    // Step 7C: assemble structured FHIR resources.
    fhir_resources = build_fhir_resources(
        observation_per_instrument:
            state.final_summaries,
        goal_resources:
            state.clinical_record.new_goals +
            state.clinical_record.goal_modifications,
        document_reference_for_report: slp_report,
        patient_id:
            lookup_patient_id(state.patient_id_hash))

    // Step 7D: persist artifacts.
    report_archive.put(
        session_id: session_id,
        slp_report: slp_report,
        family_summary: family_summary,
        fhir_resources: fhir_resources,
        archived_at: now())

    // Step 7E: write to EHR or SIS as appropriate.
    IF state.deployment_context.documentation_target ==
       "fhir_ehr":
        FOR resource IN fhir_resources:
            healthlake_client.create_resource(
                resource_type: resource.resource_type,
                resource: resource.body)
    ELIF state.deployment_context.documentation_target ==
         "school_sis":
            sis_integration.write_assessment(
                student_id: state.patient_context.student_id,
                assessment_record:
                    convert_to_sis_format(
                        slp_report, fhir_resources),
                iep_alignment:
                    state.deployment_context.iep_context)
    ELSE:
        // Standalone deployment; PDF and structured
        // export delivered through the result API.
        PASS

    session_table.update(
        session_id: session_id,
        slp_report_ref: report_archive.get_ref(
            session_id, "slp_report"),
        family_summary_ref: report_archive.get_ref(
            session_id, "family_summary"),
        documentation_completed_at: now(),
        status: "documented")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "documentation_complete",
        detail: { session_id: session_id }
    }])

    RETURN {
        slp_report_ref: state.slp_report_ref,
        family_summary_ref: state.family_summary_ref
    }
```

**Step 8: Audit, retain audio per consent, and feed post-deployment surveillance.** Every session produces a durable audit record with the SLP's edits, the per-item confidence values, the model versions used, and the linked patient outcomes where available. Audio is retained per the consent terms and then deleted; feature vectors are retained longer for model improvement and longitudinal analysis. Per-population surveillance metrics feed the dashboards that track the system's performance against SLP gold-standard scoring over time. Skip the surveillance pipeline and per-population drift surfaces only through SLP complaints.

```
FUNCTION audit_and_surveillance(session_id):
    state = session_table.get(session_id)

    audit_record = {
        session_id: session_id,
        patient_id_hash: state.patient_id_hash,
        patient_population_profile:
            state.patient_population_profile,
        slp_id: state.reviewing_slp_id,
        deployment_context: state.deployment_context,
        captured_at: state.started_at,
        slp_review_completed_at:
            state.slp_review_completed_at,
        documentation_completed_at:
            state.documentation_completed_at,
        instruments_administered:
            list(state.final_summaries.keys()),
        per_instrument_outcomes: {
            instrument_id: {
                final_severity: summary.final_severity,
                norm_reference_used:
                    state.instrument_scores
                        [instrument_id].norm_reference_used,
                review_pending_count_pre_slp:
                    state.instrument_scores
                        [instrument_id].review_pending_count,
                slp_edit_count_for_instrument:
                    count_edits_for_instrument(
                        state.edit_history, instrument_id),
                model_versions:
                    state.instrument_scores
                        [instrument_id].scoring_model_versions
            }
            FOR instrument_id, summary IN
                state.final_summaries
        },
        goal_progress_summary:
            summarize_goal_progress(state.goal_progress),
        consent_id: state.consent_id
    }

    audit_archive_kinesis_firehose.put(audit_record)

    // Step 8A: schedule audio deletion per consent
    // terms.
    schedule_audio_deletion(
        audio_refs: [
            t.audio_ref FOR t IN state.captured_tasks
        ],
        delete_after: lookup_audio_retention(
            consent_id: state.consent_id,
            deployment_context: state.deployment_context))

    // Step 8B: per-population surveillance metrics.
    FOR instrument_id, outcome IN
            audit_record.per_instrument_outcomes:
        cloudwatch.put_metric(
            namespace: "SpeechTherapyAssessment",
            metric_name: "SLPEditRate",
            value: outcome.slp_edit_count_for_instrument,
            dimensions: {
                instrument_id: instrument_id,
                population_profile:
                    audit_record.patient_population_profile,
                deployment_context:
                    audit_record.deployment_context.context_type
            })
        cloudwatch.put_metric(
            namespace: "SpeechTherapyAssessment",
            metric_name: "ReviewPendingRate",
            value: outcome.review_pending_count_pre_slp,
            dimensions: {
                instrument_id: instrument_id,
                population_profile:
                    audit_record.patient_population_profile
            })

    // Step 8C: SageMaker Model Monitor and Clarify
    // jobs run on a scheduled cadence against the
    // inference traffic. SLP edit data feeds back as
    // a real-world performance signal alongside the
    // model-monitor metrics.

    // Step 8D: longitudinal-store update with this
    // session's data.
    longitudinal_table.put({
        patient_id_hash: state.patient_id_hash,
        session_id: session_id,
        timestamp: state.started_at,
        instrument_scores: state.final_summaries,
        edited_scores_summary:
            summarize_edited_scores(state.edited_scores),
        goal_progress: state.goal_progress,
        trajectory_patterns: state.trajectory_patterns,
        capture_metadata: extract_capture_metadata(state)
    })

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_audited",
        detail: {
            session_id: session_id,
            audited_at: now()
        }
    }])
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.09-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample assessment output (illustrative, synthetic patient):**

```json
{
  "session_id": "sta-7f3c8d2a-1e4b-4a89",
  "patient_id_hash": "p_4e2c8a91...",
  "captured_at": "2026-05-23T10:15:08Z",
  "patient_context": {
    "age_years": 6,
    "sex": "female",
    "primary_language": "en-US",
    "deployment_context": "outpatient_clinic"
  },
  "instruments_administered": [
    "articulation_inventory_gfta_aligned",
    "phonological_pattern_analysis",
    "connected_speech_picture_description"
  ],
  "results": {
    "articulation_inventory_gfta_aligned": {
      "auto_summary": {
        "items_administered": 53,
        "items_correct_auto": 31,
        "items_substituted_auto": 14,
        "items_omitted_auto": 4,
        "items_distorted_auto": 2,
        "items_pending_slp_review": 2,
        "percent_consonants_correct_auto": 0.585
      },
      "post_slp_summary": {
        "items_correct": 32,
        "items_substituted": 14,
        "items_omitted": 4,
        "items_distorted": 3,
        "percent_consonants_correct": 0.604,
        "slp_edits_count": 1
      },
      "norm_comparison": {
        "norm_reference": "gfta3_age_6_0_to_6_5_female",
        "percentile_rank": 12,
        "standard_score": 82,
        "severity_classification": "mild_to_moderate"
      }
    },
    "phonological_pattern_analysis": {
      "patterns_detected": [
        {
          "pattern": "final_consonant_deletion",
          "percent_occurrence": 0.31,
          "age_appropriateness": "atypical_for_age",
          "target_for_therapy": true
        },
        {
          "pattern": "gliding_of_liquids",
          "percent_occurrence": 0.78,
          "age_appropriateness": "typical_for_age",
          "target_for_therapy": false
        },
        {
          "pattern": "stopping_of_fricatives",
          "percent_occurrence": 0.22,
          "age_appropriateness": "atypical_for_age",
          "target_for_therapy": true
        }
      ]
    },
    "connected_speech_picture_description": {
      "duration_seconds": 87,
      "transcript_word_count": 92,
      "intelligibility_estimate": 0.74,
      "linguistic_features": {
        "mean_length_of_utterance_morphemes": 4.8,
        "mean_length_of_utterance_norm_percentile": 35,
        "lexical_diversity_ttr": 0.61,
        "syntactic_complexity_index": 2.3,
        "narrative_structure_score": "complete_with_some_omissions"
      }
    }
  },
  "longitudinal": {
    "prior_session_count": 3,
    "most_recent_prior_session": "2026-02-14T11:00:00Z",
    "deltas": {
      "percent_consonants_correct": {
        "prior": 0.532,
        "current": 0.604,
        "delta": 0.072,
        "interpretation": "improvement_outside_typical_variation"
      },
      "final_consonant_deletion_percent_occurrence": {
        "prior": 0.41,
        "current": 0.31,
        "delta": -0.10,
        "interpretation": "improvement_outside_typical_variation"
      },
      "stopping_of_fricatives_percent_occurrence": {
        "prior": 0.24,
        "current": 0.22,
        "delta": -0.02,
        "interpretation": "stable_within_typical_variation"
      }
    }
  },
  "goal_progress": [
    {
      "goal_text": "Maya will produce final consonants in single words with 80% accuracy",
      "baseline_value": 0.42,
      "current_value": 0.69,
      "target_value": 0.80,
      "percent_progress": 0.71,
      "on_track": true,
      "recommended_action": "continue_current_therapy_plan"
    },
    {
      "goal_text": "Maya will produce /s/, /f/ in initial position with 80% accuracy",
      "baseline_value": 0.55,
      "current_value": 0.78,
      "target_value": 0.80,
      "percent_progress": 0.92,
      "on_track": true,
      "recommended_action": "near_target_consider_generalization_phase"
    }
  ],
  "trajectory_patterns": [
    "improvement_in_targeted_sounds",
    "near_target_attainment_for_one_active_goal"
  ],
  "clinical_record": {
    "working_diagnosis_or_hypothesis": "moderate_phonological_disorder_responding_to_intervention",
    "goal_modifications": [
      {
        "goal_id": "goal_002_initial_fricatives",
        "modification": "advance_to_generalization_phase_in_connected_speech"
      }
    ],
    "recommended_therapy_frequency": "twice_weekly_45_minutes",
    "recommended_therapy_modality": "in_clinic_with_home_practice",
    "discharge_readiness": "not_yet"
  }
}
```

**Performance benchmarks (illustrative; ranges depend heavily on instrument, population, and recording conditions; your mileage will vary):**

| Metric | Pediatric Articulation Scoring | Adult Dysarthria Severity | Stuttering Event Detection | Voice Quality (CAPE-V-aligned) | Connected-Speech Linguistic Features |
|--------|-------------------------------|---------------------------|----------------------------|--------------------------------|---------------------------------------|
| Per-item agreement with SLP gold-standard (typical-speech-trained acoustic model) | 65-75% | 55-70% | 60-72% | 60-72% | N/A (different metric structure) |
| Per-item agreement with SLP gold-standard (disordered-speech-fine-tuned model) | 80-92% | 75-88% | 78-90% | 75-88% | N/A |
| Cross-population generalization (model trained on one age band, applied to another) | 60-78% | 60-78% | 65-80% | 65-80% | 55-72% |
| SLP-review-flag rate (typical clinical population) | 8-18% | 12-22% | 10-20% | 12-22% | 15-25% |
| SLP edit rate (post-flag, indicating false-positive flags) | 25-40% of flagged items | 30-45% | 25-40% | 30-45% | 20-35% |
| Per-session latency (asynchronous endpoint) | 2-5 minutes | 3-7 minutes | 2-5 minutes | 1-3 minutes | 3-8 minutes |
| Per-session AWS infrastructure cost | $0.10-0.25 | $0.15-0.35 | $0.10-0.25 | $0.05-0.15 | $0.15-0.40 |

<!-- TODO: replace with verified figures from the deployed instruments. The ranges above reflect typical patterns for SLP-AI work but vary substantially with instrument, population, and the specific commercial or institutional model used. Cross-population generalization is consistently weaker than within-population performance. -->

**Where it struggles:**

- **Severely impaired speech.** As speech impairment severity increases, model performance decreases. The most-impaired patients (severe dysarthria, severe apraxia, severe stuttering) are exactly the population the SLP most needs help with, and they are the population where the system performs worst. Mitigations: severity-stratified validation with explicit per-severity-band performance reporting, lower confidence thresholds (more SLP-review flags) for severe-impairment patients, conservative auto-scoring with deference to the SLP for ambiguous items, no autonomous-scoring deployment for severe-impairment populations until per-severity validation supports it.

- **Cross-dialect and cross-language generalization.** A model trained on General American English does not transfer cleanly to African American English, to Spanish-influenced English, to other regional dialects, or to other languages. Articulation-pattern interpretation depends on the speaker's dialect; what is a "substitution error" in one dialect is a typical realization in another. Mitigations: per-dialect-and-per-language validation, explicit dialect identification at session setup, dialect-aware norm references, conservative classification for out-of-validated-dialect speakers, ongoing dialect coverage expansion.

- **Pediatric-specific challenges.** Pediatric speech is acoustically different from adult speech, pediatric attention spans are shorter (which limits task length), pediatric cooperation varies (the patient might rush through, get distracted, mumble), and pediatric phonology is developmental (a sound that is "wrong" at age 8 may be "developmentally typical" at age 4). Mitigations: pediatric-specific acoustic models, age-appropriate task design, age-specific norms with developmental-appropriateness flags, conservative classification for younger pediatric patients.

- **Pediatric assent and age-appropriate consent.** Older pediatric patients (typically age 7+) provide assent in addition to parent consent; younger patients are bound by parent consent alone. The consent infrastructure has to handle the developmental gradient, the dual-signature requirement for school-and-clinic dual jurisdictions, and the changing-consent-as-the-patient-ages workstream. Mitigations: developmentally-appropriate assent language, robust dual-signature handling, regular consent refresh on developmental milestones.

- **Telepractice audio quality.** Telepractice audio is captured through whatever microphone the patient or family has, in whatever environment they are in, through whatever video-call platform the practice uses. The acoustic features the system measures are sensitive to all of these variables. Mitigations: telepractice-specific recording-quality guidance, telepractice-fine-tuned acoustic models, conservative classification for poor-quality telepractice audio, recapture prompts when audio quality is below threshold.

- **Home-practice context.** Home-practice apps capture audio outside the structured assessment context. Background noise, family member speech, the patient practicing without supervision and possibly incorrectly all contaminate the audio. Mitigations: home-practice-specific quality assessment, speaker-only verification, simpler scoring rubrics for home-practice (target/not-target rather than full instrument scoring), explicit framing as practice rather than assessment.

- **Stimulus-set licensing and IP.** Established assessment instruments are often copyrighted and licensed by their publishers. Building a system that uses a specific instrument requires licensing or a clearly-distinct stimulus set with separate norm validation. Mitigations: licensing agreements with instrument publishers where the system uses copyrighted instruments, institutionally-validated alternative stimulus sets where licensing is not available, transparent disclosure of which instrument is used and any deviations from the published version.

- **Norm-reference availability and currency.** Population norms are central to the clinical interpretation. Norms vary by age band, sex, language, dialect, and clinical population, and they are updated periodically. Norms for some populations (especially non-English-speaking, multi-dialect, and rare clinical populations) may not exist or may be outdated. Mitigations: explicit norm-reference disclosure on every result, conservative classification when norms are not well-established for the patient profile, ongoing investment in norm development for underserved populations.

- **SLP workflow disruption.** A system that adds friction to the SLP's workflow gets used reluctantly or not at all. Mitigations: SLP-led workflow design, iterative deployment with SLP feedback, integration with the SLP's existing documentation system rather than as a parallel system, productivity measurement that demonstrates time savings rather than time additions.

- **Reimbursement and outcome-tracking integration.** Speech therapy reimbursement is often tied to outcomes documentation that the SLP must produce regardless of the AI tool. Mitigations: outcomes-aligned documentation generation, CPT-code-specific documentation requirements built into the report templates, IEP-aligned formats for school deployments, value-based-contract outcome-measure support.

- **Pediatric data privacy and the long retention horizon.** A six-year-old being assessed today has data that may need to be retained until age 25 or longer depending on state pediatric-records law. The biometric voice samples are part of that long-horizon data. Mitigations: explicit pediatric-records-retention policies, audit-archive infrastructure that supports the long retention floor, explicit deletion-on-request workflow that respects pediatric protections including parent-on-behalf-of-minor and patient-once-of-age requests.

- **The autonomous-scoring temptation.** The most attractive product framing is full-autonomous scoring (the SLP records audio and a complete report drops out the other end). The clinically-defensible framing is SLP-in-the-loop with confidence-based review flags. The marketing-vs-clinical-reality gap is similar to what voice biomarker products face. Mitigations: explicit positioning as SLP augmentation rather than SLP replacement, SLP-review interfaces that make the in-the-loop work efficient, clinical-quality monitoring that demonstrates the SLP-in-the-loop accuracy advantage over autonomous scoring.

- **Deployment-context heterogeneity.** Hospital outpatient SLP, school SLP, private practice SLP, early-intervention SLP, telepractice SLP, and inpatient acute-care SLP have different documentation systems, different reimbursement models, different consent requirements, different population skews, and different clinical-workflow patterns. Mitigations: per-deployment-context configuration, validation evidence per context, dedicated implementation effort per context (not a single deployment that pretends to fit everywhere).

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment for any specific instrument and population needs to close substantial gaps that are out of scope for a recipe.

**Per-instrument-and-per-population validation evidence.** This is the dominant gap. Disordered-speech-aware models for each assessment instrument and each target population (pediatric articulation, adult dysarthria, fluency, voice quality) require validation studies with appropriate cohorts, SLP-graded reference data, and per-population performance evidence. Building this evidence is a multi-year clinical-research undertaking; most institutions should be buying validated commercial models with appropriate evidence packages rather than building from scratch.

**Stimulus-set licensing and norm-reference data.** Many established assessment instruments are copyrighted; using them requires licensing agreements with the publishers. Population norms for specific instruments and populations are similarly licensed or institutionally developed. Production deployment requires the licensing arrangements, the norm reference data in machine-readable form, and the change-management process for instrument updates and norm refreshes.

**SLP-review interface design and clinical-workflow integration.** The SLP-facing review interface is the primary surface where the system either succeeds or fails. Production deployment requires extensive SLP-led design, iterative usability testing, and integration with the SLP's existing documentation tools. The interface design is the system's single biggest determinant of clinician adoption.

**Per-deployment-context configuration and integration.** Hospital-outpatient, school-based, private-practice, early-intervention, telepractice, and inpatient-acute-care contexts each have different documentation system targets, different consent requirements, different reimbursement models, and different population profiles. Production deployment in each context requires its own integration and configuration work; a single deployment does not fit all contexts.

**Pediatric-specific consent infrastructure.** Pediatric deployments require parent or guardian consent plus age-appropriate assent, with developmentally-graduated assent language, dual-signature handling, FERPA alignment for school deployments, COPPA alignment for any direct-to-child interface, and the long-horizon pediatric-records-retention infrastructure. The consent infrastructure is more substantial than typical adult HIPAA-only consent.

**Disordered-speech corpus expansion.** Public disordered-speech corpora are limited in size and population coverage. Production deployment benefits from institutional disordered-speech corpus expansion, with appropriate IRB approval, consent infrastructure, and SLP-graded labeling. Plan corpus expansion as a multi-year, named clinical-research-team workstream.

**Per-population performance gates.** Per-population performance must meet the institutional threshold for that population before deployment to that population. Populations where per-population performance is inadequate either get the system disabled or get it deployed with explicit caveats and adjusted SLP-review thresholds. Without these gates, the institution silently underserves the populations where the system performs poorly.

**FDA SaMD strategy where applicable.** Speech-therapy AI tools that produce autonomous diagnostic claims are potentially subject to FDA's SaMD framework. The strategy decision (pursue clearance, deploy as SLP-augmentation, deploy as practice-and-monitoring tool) is upstream of the technical work and varies by instrument and clinical claim. Most current speech-therapy AI products position themselves outside the regulatory perimeter; that positioning constrains the clinical claims and the workflow placement.

**Faithfulness and grounding for LLM-generated reports.** The Bedrock-generated SLP report and family summary need explicit faithfulness checks: structured-output validation against the schema, citation grounding to the underlying scoring data, secondary checks that verify the report does not invent items or scores beyond what the system measured. Family-facing summaries also need reading-level validation and Guardrails coverage.

**Clinical-quality review cadence for ongoing deployment.** Voice biomarker work in recipe 10.8 covered the post-deployment surveillance discipline; the same applies here. Per-population accuracy against SLP gold-standard scoring, drift detection over time, re-validation triggers, and clinical-quality review meetings on a regular cadence are operational requirements rather than nice-to-haves. Plan a quarterly per-instrument clinical-quality review meeting at minimum.

**Multilingual deployment.** Monolingual English deployment is the easier starting point; multilingual deployment requires per-language acoustic models, per-language norm references, per-language stimulus sets, per-language linguistic-feature extraction, per-language Bedrock prompting, and per-language clinical validation. Multilingual deployment is a substantial expansion, not a configuration toggle.

**Home-practice and parent-coaching applications.** When the system extends beyond clinical assessment into home-practice apps and parent-coaching tools, the consent, workflow, scoring rubric, and clinical-action mapping all change. A home-practice app deployed with assessment-grade scoring rubrics will produce frustrating false positives; a home-practice app with appropriate practice-grade rubrics is a different product than the assessment system, sharing infrastructure but with distinct user experience and clinical positioning.

**Outcome-tracking and value-based-care alignment.** Speech-therapy reimbursement is increasingly tied to outcomes data. Production deployment benefits from explicit alignment with the relevant outcome measures (FOTO, NOMS, school-district progress-monitoring requirements, IEP goal-attainment measures). The outcome-measure integration is part of the workflow value, not just the clinical value.

**Disaster recovery and degraded-mode operation.** When upstream services fail (SageMaker endpoint outage, Bedrock outage, HealthLake outage), the SLP must be able to continue clinical work. The system must degrade gracefully: pure manual capture and SLP-only documentation when the AI is unavailable, durable session state that survives transient failures, queued processing for delayed scoring when the inference pipeline is degraded.

---

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

## Variations and Extensions

**School-based SLP deployment with IEP integration.** A focused deployment for school SLPs, with FERPA-aligned consent, IEP-aligned documentation, school SIS integration, and progress-monitoring outputs that feed the IEP review process. School SLPs handle a large share of pediatric speech-therapy caseloads, and the school deployment context is sufficiently different from the clinical context that it warrants its own product configuration.

**Telepractice-optimized workflow.** A deployment optimized for telepractice with telepractice-specific recording-quality guidance, telepractice-fine-tuned acoustic models, parent-supported capture for pediatric telepractice, and integration with the SLP's telepractice platform of choice. The COVID-era shift to telepractice has not fully reverted; many SLPs maintain hybrid practices, and the telepractice-specific tooling is a sustained-demand product.

**Home-practice and parent-coaching app.** A patient-and-parent-facing app that supports between-session home practice with immediate feedback on target-sound production, parent-coaching prompts on how to support practice, gamification appropriate for pediatric users, and progress reporting that the SLP can review between visits. The clinical positioning is practice-and-monitoring rather than assessment, with corresponding consent and regulatory implications.

**Stuttering severity tracking with longitudinal trajectory.** A focused deployment for fluency assessment and tracking, with SSI-4-aligned scoring, longitudinal trajectory analysis, treatment-response monitoring, and integration with established stuttering-therapy programs (Lidcombe, Camperdown, fluency shaping, stuttering modification). Stuttering is a high-value indication because the assessment is structured, the longitudinal tracking is clinically meaningful, and the patient population includes both children and adults.

**Voice quality assessment for laryngeal pathology.** A focused deployment for voice-quality assessment, with CAPE-V-aligned and VHI-aligned scoring, integration with otolaryngology and voice-disorder clinics, and longitudinal tracking for post-surgical and post-radiation voice recovery. The voice-quality use case is a natural fit for the architecture and has well-established clinical pathways.

**Post-stroke aphasia and dysarthria recovery monitoring.** A deployment focused on post-stroke speech recovery, with dysarthria assessment for motor-speech recovery, aphasia-related linguistic-feature tracking, and longitudinal monitoring across the recovery trajectory. Integration with stroke-recovery clinical programs and rehabilitation hospitals. The within-patient longitudinal pattern is particularly clinically useful here because each patient's pre-stroke baseline (where available) provides a strong reference.

**Pediatric autism spectrum disorder assessment support.** Voice-and-prosody features for pediatric autism assessment, supporting the SLP and developmental-pediatrics team's diagnostic workup. The diagnostic pathway is more nuanced than articulation or fluency, the AI's role is more clearly augmentation than autonomous scoring, and the consent and family-coaching considerations are substantial.

**Cleft-palate and resonance assessment.** Resonance-focused assessment for cleft-palate-and-craniofacial patients, with hypernasality and hyponasality scoring, post-surgical recovery tracking, and integration with craniofacial team workflows. A specialty deployment with a small but high-value patient population.

**Transgender voice-training assessment.** Voice-quality and pitch-modification tracking for transgender voice training, supporting the SLP and the patient through the longitudinal voice-modification process. A growing service area with specific clinical and cultural considerations; the architectural pattern fits well with the longitudinal-tracking emphasis.

**Multilingual articulation assessment for Spanish-English bilingual children.** A multilingual deployment with Spanish phonological norms, code-switching-aware capture, dialect-aware scoring, and bilingual-clinical SLP workflow integration. Bilingual articulation assessment is a recognized gap in available tools, and a successful multilingual deployment serves an underserved population.

**Real-time SLP feedback during therapy sessions.** A real-time-during-therapy use case where the system provides the SLP with in-session feedback on target-sound production, fluency events, or voice-quality dimensions as the therapy is happening. The latency requirements are tighter than the asynchronous assessment workflow, and the SLP-facing interface is built for in-session use rather than post-session review.

**Caseload-level analytics for SLP practice management.** A practice-level dashboard that aggregates across the SLP's caseload, surfacing patients with stalled progress for goal review, patients near discharge readiness, patients with concerning trajectory patterns, and overall practice outcome metrics. The analytics are a productivity multiplier for the SLP and a quality-of-care signal for the practice leadership.

**Outcome-tracking integration for value-based-care contracts.** Explicit integration with value-based-care outcome measures (FOTO, NOMS, school-district progress measures) so that the SLP's documentation automatically populates the outcome-tracking systems that drive reimbursement. A workflow value proposition that complements the clinical value proposition.

**Integration with augmentative-and-alternative communication assessment.** For patients with severe expressive-language impairment, AAC assessment is part of the SLP's work. Voice-and-speech AI can support AAC assessment by tracking the patient's residual speech production alongside their AAC use, supporting the multi-modal communication assessment.

**Continuing education and SLP training support.** The corpus of SLP-graded assessments produced by the system supports continuing-education content, SLP-trainee feedback (where the trainee's scoring is compared with the SLP-validated AI scoring as a learning aid), and inter-rater-reliability training. This is an extension of the data the system collects, with explicit IRB and consent considerations for data use beyond direct clinical care.

**Per-population norm development for underserved populations.** The longitudinal data the system collects supports norm development for populations where established norms are limited (specific age bands, specific dialects, specific clinical populations). This is a research-track use of the data with explicit IRB approval, but it can extend the system's clinical utility for populations the off-the-shelf norms do not serve.

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

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Asynchronous Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon SageMaker Clarify](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-fairness-and-explainability.html)
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker examples including model-hosting, Model Monitor, and Clarify patterns
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including grounded generation and Guardrails
- [`aws-samples/amazon-transcribe-streaming-python`](https://github.com/aws-samples/amazon-transcribe-streaming-python): Transcribe streaming and async-job samples
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): healthcare AI/ML sample notebooks
<!-- TODO: confirm the current names and locations of these repos at time of build -->

**AWS Solutions and Blogs:**
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "speech," "audio," "SageMaker," "Transcribe Medical" for implementation deep dives
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AI/ML case studies
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for clinical-decision-support reference architectures
<!-- TODO: replace with two or three specific verified blog post URLs once confirmed to exist -->

**External References (Standards, Frameworks, and Regulatory):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model for assessment-result EHR integration
- [FHIR Observation Resource](https://www.hl7.org/fhir/observation.html): canonical FHIR resource for assessment-score write-back
- [FHIR Goal Resource](https://www.hl7.org/fhir/goal.html): canonical FHIR resource for therapy-goal representation
- [FHIR CarePlan Resource](https://www.hl7.org/fhir/careplan.html): canonical FHIR resource for therapy-plan representation
- [LOINC](https://loinc.org/): standard codes for clinical observations, including some speech-and-language assessment items
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in speech-therapy workflows
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [FERPA](https://www2.ed.gov/policy/gen/guid/fpco/ferpa/index.html): governs educational records, applicable for school-based SLP work
- [COPPA](https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa): governs online services directed at children under 13, applicable for direct-to-child interfaces
- [Illinois Biometric Information Privacy Act (BIPA)](https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004): biometric-data law applicable to voice samples in Illinois
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): regulatory framework for software medical devices, potentially applicable to autonomous-scoring speech-therapy AI

**Research and Datasets:**
- [TORGO Database](http://www.cs.toronto.edu/~complingweb/data/TORGO/torgo.html): dysarthric speech corpus for research <!-- TODO: verify URL and current access terms -->
- [UASpeech Corpus](http://www.isle.illinois.edu/sst/data/UASpeech/): cerebral-palsy-related speech impairment corpus <!-- TODO: verify URL and license -->
- [AphasiaBank](https://aphasia.talkbank.org/): research corpus for post-stroke aphasia <!-- TODO: verify access terms -->
- [FluencyBank](https://fluency.talkbank.org/): research corpus for stuttering <!-- TODO: verify access terms -->
- [LANNA / TalkBank Phon resources](https://phon.talkbank.org/): pediatric speech corpora and analysis tools <!-- TODO: verify URLs and access terms -->
- [INTERSPEECH Conference](https://www.interspeech2024.org/): primary speech-and-audio research venue; speech-therapy AI work appears regularly
- [Journal of Speech, Language, and Hearing Research](https://pubs.asha.org/journal/jslhr): peer-reviewed clinical journal for SLP research
- [American Journal of Speech-Language Pathology](https://pubs.asha.org/journal/ajslp): peer-reviewed clinical journal for SLP practice

**Industry and Clinical Resources:**
- [American Speech-Language-Hearing Association (ASHA)](https://www.asha.org/): the primary professional organization for SLPs; clinical-practice guidelines, code of ethics, and continuing education
- [ASHA Practice Portal](https://www.asha.org/practice-portal/): clinical-practice guidance covering disorders, populations, and assessment instruments
- [ASHA Clinical Topics on Telepractice](https://www.asha.org/practice-portal/professional-issues/telepractice/): telepractice-specific guidance
- [Stuttering Foundation](https://www.stutteringhelp.org/): clinical resources for fluency disorders
- [National Stuttering Association](https://westutter.org/): patient-facing resources and clinical-research support
- [Cleft Palate-Craniofacial Association](https://acpa-cpf.org/): clinical resources for craniofacial speech disorders
- [HHS Office for Civil Rights HIPAA Guidance](https://www.hhs.gov/hipaa/index.html): HIPAA Privacy and Security Rule guidance
- [Department of Education FERPA Guidance](https://studentprivacy.ed.gov/): FERPA implementation guidance for school-based deployments

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single instrument (typically pediatric articulation), single population (typical-development pediatric, age 4-8), commercial-vendor model integration through SageMaker endpoint or vendor API, single deployment context (outpatient clinic), SLP-review interface with confidence-based flagging, FHIR Observation write-back to the EHR, brief-retention audio policy, English-only, pilot with one or two clinical sites | 4-6 months |
| Production-ready | Multiple validated instruments (articulation, phonological-pattern analysis, fluency assessment, voice-quality assessment), multiple populations (pediatric typical-development, pediatric speech-disorder, adult typical, adult dysarthric), multiple deployment contexts (outpatient clinic, school-based, telepractice), full per-population validation with eligibility gates, longitudinal trajectory tracking with per-patient baselines, layered post-deployment surveillance with SageMaker Model Monitor and Clarify plus regular clinical-quality review, biometric-data consent infrastructure with right-to-deletion workflow including pediatric-records protection, full HIPAA-and-FERPA-and-COPPA compliance review, multi-context rollout with named operational owners, English plus at least one additional language (typically Spanish), SLP training and feedback program, per-jurisdiction regulatory analysis, IEP integration for school deployments, outcome-tracking integration for value-based-care contracts | 14-22 months |
| With variations | School-based deployment with full IEP integration, telepractice-optimized workflow, home-practice and parent-coaching app, stuttering severity tracking with longitudinal trajectory, voice-quality assessment for laryngeal pathology, post-stroke aphasia and dysarthria recovery monitoring, pediatric autism spectrum disorder assessment support, cleft-palate resonance assessment, transgender voice-training assessment, multilingual articulation assessment, real-time SLP feedback during therapy sessions, caseload-level analytics, AAC assessment integration, per-population norm development | 10-18 months beyond production-ready |

---

## Tags

`speech-voice-ai` · `speech-therapy` · `slp-augmentation` · `articulation-assessment` · `phonological-pattern-analysis` · `fluency-assessment` · `stuttering-severity-instrument` · `voice-quality-assessment` · `cape-v` · `vhi` · `dysarthria-assessment` · `aphasia-assessment` · `motor-speech-disorders` · `cleft-palate-resonance` · `pediatric-speech-disorders` · `disordered-speech-modeling` · `forced-alignment-disordered-speech` · `phoneme-classification` · `goldman-fristoe-aligned` · `hodson-aligned` · `slp-in-the-loop` · `confidence-based-review-flags` · `per-population-validation` · `cross-dialect-generalization` · `pediatric-pediatric-norms` · `longitudinal-trajectory` · `goal-attainment-tracking` · `iep-integration` · `school-based-slp` · `telepractice` · `home-practice-app` · `parent-coaching` · `outcome-tracking` · `value-based-care` · `multilingual-articulation-assessment` · `bilingual-spanish-english` · `transgender-voice-training` · `samd` · `fda-clearance-considerations` · `post-deployment-surveillance` · `clinical-validation` · `biometric-data` · `bipa` · `ferpa` · `coppa` · `pediatric-consent` · `voice-as-pii` · `consent-management` · `slp-workflow-integration` · `documentation-generation` · `family-friendly-summary` · `sagemaker-endpoints` · `sagemaker-async-inference` · `sagemaker-model-monitor` · `sagemaker-clarify` · `transcribe-medical` · `bedrock` · `bedrock-guardrails` · `healthlake` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `complex` · `production-track` · `hipaa` · `phi-handling` · `audit-trail`

---

*← [Recipe 10.8: Voice Biomarker Detection](chapter10.08-voice-biomarker-detection) · [Chapter 10 Index](chapter10-index) · [Recipe 10.10: Multilingual Real-Time Medical Interpretation](chapter10.10-multilingual-real-time-medical-interpretation) →*
