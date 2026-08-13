# Recipe 10.9: Speech Therapy Assessment and Monitoring

**Effort:** 5 of 5

---

## The Problem

A six-year-old girl named Maya sits across from a speech-language pathologist (SLP) in a small therapy room. The SLP is holding a flipbook of pictures and asking Maya to name them. "Rabbit." Maya says "wabbit." "Sheep." Maya says "seep." "Thumb." Maya says "fum." The SLP is making notes, sometimes circling sounds on a printed articulation inventory, sometimes pausing to write a quick observation in the margin. Forty-five minutes later, Maya leaves with her mom, and the SLP has roughly twenty minutes between this session and the next to convert what she just observed into a structured assessment: which phonemes Maya can produce, which she substitutes, which she omits entirely, what the patterns are (final consonant deletion? cluster reduction? fronting?), how Maya's intelligibility compares to age norms, what the goals for the next twelve weeks should be, and what the home-practice activities look like. The SLP is good at this. She has done it ten thousand times. She also has thirty-two more patients on her caseload, eight more sessions today, and a documentation backlog that follows her home most evenings.

Twelve weeks later Maya is back. The SLP wants to know whether Maya is making progress. Has the final consonant deletion gotten better since the last assessment? Is the /r/ approximation closer to the target now? Is Maya generalizing from the practiced words to spontaneous speech? The clinical question is fundamentally a comparison: Maya now versus Maya twelve weeks ago, against a backdrop of where typically-developing six-year-olds sit on the developmental curve. The data the SLP needs to answer this question lives, in fragments, across her notes from twelve weeks ago, her notes from today, the parent's report of how home practice is going, and her ear's memory of how Maya sounded last time. The comparison is approximate. It is also the foundation of every clinical decision the SLP will make about Maya's care over the next year.

This is the world that speech-therapy assessment and monitoring AI is trying to land in. The goal is not to replace the SLP. The goal, when it is framed honestly, is to give the SLP back the time she spends transcribing her own observations after the session, to make the longitudinal comparison more reliable than human auditory memory allows, and to extend the reach of the SLP into between-session monitoring (home practice with feedback, parent-led drills with quality scoring, telepractice sessions where the SLP cannot watch every utterance) without adding more humans the clinic does not have. Done well, this is a category of healthcare AI where the labor savings are real, the clinical signal is genuinely useful, and the patient outcomes can improve because the SLP gets to spend more of her time on the parts of speech therapy that require a human.

Done poorly, it is one of the easier categories of healthcare AI to fail in. The target population for speech therapy is, by definition, people whose speech is impaired in ways that confuse off-the-shelf speech recognition, off-the-shelf voice biomarker pipelines, and off-the-shelf acoustic feature extractors. A child with childhood apraxia of speech produces utterances that an automatic speech recognizer trained on typical adult speech transcribes incorrectly in ways that look, to the system, like ordinary recognition errors but that are, clinically, the entire point of what the SLP is measuring. An adult recovering from a stroke produces dysarthric speech with phonetic patterns that violate the assumptions every off-the-shelf speech model was built on. An older adult with Parkinson's-related dysarthria produces speech that the system might dismiss as low-quality audio when it is in fact the clinical signal the system is meant to score. The systems that work in this category are the ones that explicitly model impaired speech as the target, not as a degraded version of typical speech.

Beyond the population challenge, there is a clinical-evidence challenge. Speech-language pathology has decades of established assessment instruments (the Goldman-Fristoe Test of Articulation, the Hodson Assessment of Phonological Patterns, the Khan-Lewis Phonological Analysis, the Stuttering Severity Instrument, the Voice Handicap Index, the Frenchay Dysarthria Assessment, and a long list of others), each with its own scoring rubric, age norms, and reliability evidence.  A speech-therapy AI that produces a score without grounding in these established instruments is a number floating in space; SLPs reasonably ignore it. A speech-therapy AI that produces scores aligned with established instruments has to demonstrate, with appropriate validation studies, that its automatic scoring is consistent with expert SLP scoring on the populations it will be deployed against. This is a real evidence package, not a marketing claim.

There is also a workflow integration challenge that is harder than it sounds. SLPs work in school settings, hospital outpatient clinics, inpatient acute-care settings, skilled nursing facilities, early-intervention home visits, telepractice from a home office, and private-practice offices that range from solo practitioners to multi-site groups. The documentation systems range from full EHRs (Epic, Cerner, MEDITECH) to school-district student information systems (PowerSchool, Infinite Campus) to private-practice billing-and-documentation tools (SimplePractice, TheraNest, ClinicSource) to spiral notebooks.  An AI tool that integrates well with one of these contexts often integrates poorly with the others. The SLP is the customer, not the IT department; if the tool does not fit her workflow, it does not get used.

And there is a regulatory question that the field is still working through. Some speech-therapy AI tools (autonomous fluency scoring for stuttering, autonomous articulation scoring for pediatric speech disorders) are diagnostic-adjacent enough to potentially fall under FDA's Software as a Medical Device framework. Other tools (between-session practice apps, parent-coaching tools, SLP productivity tools) are clearly outside the regulatory perimeter. The line between the two depends on the specific clinical claims the tool makes and the workflow placement.  Vendors that market themselves aggressively into the diagnostic-adjacent zone without an FDA strategy are building toward a regulatory cliff; vendors that stay clearly on the practice-and-monitoring side avoid the regulatory exposure but limit their clinical claims. The architectural choices interact with this strategic choice.

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

**Disordered-speech corpora for training and validation.** Public corpora exist for some categories of disordered speech: the TORGO database for dysarthric speech, the UASpeech corpus for cerebral-palsy-related speech impairment, the AphasiaBank corpus for post-stroke aphasia, the FluencyBank corpus for stuttering, and several others.  These corpora have known limitations (small populations, specific language coverage, specific severity distributions), and they are not sufficient on their own for production-grade systems, but they are the starting point. Institutional partnerships with academic medical centers and SLP graduate programs can extend the corpora with consented patient data over time.

**Disordered-speech-specific fine-tuning.** A speech model fine-tuned on disordered speech performs meaningfully better on disordered speech than the same architecture trained only on typical speech. The fine-tuning is per-disorder-category (a dysarthria model is different from an apraxia model, which is different from a fluency model), and ideally per-severity-band within disorder category. The architectural pattern is a shared base model with disorder-specific adaptation layers, deployed as separate inference paths per disorder type.

**Speaker-adaptive modeling.** Many disordered speakers have idiosyncratic acoustic patterns; a model that adapts to the speaker (using a few minutes of the speaker's speech to calibrate) outperforms a speaker-independent model. The speaker-adaptation infrastructure, where the system maintains a per-patient acoustic profile that improves over multiple sessions, is part of the longitudinal-monitoring story and one of the reasons this recipe benefits from the longitudinal architecture in particular.

**Multi-task and multi-instrument scoring.** A speech-therapy assessment system that scores multiple instruments simultaneously (articulation inventory, phonological-pattern analysis, intelligibility rating) from the same audio sample gets more value from the audio than a single-instrument scorer. The multi-task models share representations across instruments and are typically more robust than single-instrument equivalents.

**Confidence-aware scoring with explicit indeterminate outputs.** When the model is uncertain (because the acoustic input is ambiguous, because the patient's profile is outside the model's validation envelope, because the audio quality is insufficient), it produces an explicit "needs SLP review" output rather than a confident-looking score. This is the same pattern as voice biomarker scoring (recipe 10.8) and is essential for SLP trust.

**SLP-in-the-loop training data.** The most reliable training data for speech-therapy AI is data scored by SLPs against established assessment instruments. The infrastructure for capturing SLP scoring (within the system's normal workflow, with the SLP scoring assessments as part of clinical care and the scores feeding back as labeled data) is part of the long-term improvement story. This is analogous to the clinician-in-the-loop training data patterns common in radiology AI.

### Where the Field Has Moved

A few practical updates worth knowing.

**Self-supervised speech representations have improved disordered-speech modeling.** Models like wav2vec 2.0, HuBERT, and WavLM, fine-tuned on disordered-speech corpora, produce phoneme-alignment and acoustic-feature representations that handle disordered speech better than the older HMM-GMM-DNN pipelines.  Many production speech-therapy tools are built on top of these representations now.

**Pediatric-specific acoustic models are catching up.** Pediatric speech is acoustically different from adult speech (different fundamental frequencies, different formant frequencies, different articulation development), and pediatric-specific acoustic models perform better on pediatric assessment than adult-trained models. The available pediatric training data has grown, and pediatric model performance has improved correspondingly.

**FDA has taken interest in some speech-therapy AI tools.** A handful of speech-therapy AI products have engaged with the FDA's regulatory framework, including for stuttering assessment and some pediatric articulation tools.  The regulatory pathway is reachable but not common; most current speech-therapy AI products position themselves as practice-and-monitoring tools rather than diagnostic instruments to stay outside the regulatory perimeter.

**Telepractice has driven adoption.** The shift to telepractice during and after the COVID-19 pandemic created sustained demand for speech-therapy tools that can extend the SLP's reach across the camera. Asynchronous-practice apps, parent-coaching tools, and between-session monitoring tools all benefited. The clinical workflow has not fully reverted; many SLPs maintain a hybrid practice with both in-person and telepractice patients.

**Workflow integration with school SLP systems is an active area.** School-based SLPs handle a large share of pediatric speech-therapy caseloads. Integration with school-district student information systems and IEP management tools is an area where speech-therapy AI tools are improving but remain uneven. The school context has specific privacy and consent considerations under FERPA in addition to HIPAA when applicable.

**Multilingual speech-therapy tools are emerging slowly.** Most speech-therapy AI tools are English-first. Bilingual and multilingual tools that handle code-switching, English-Spanish bilingual articulation assessment, and language-specific phonological patterns are an active area of development but not yet mature. 

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

**Established assessment instruments anchor clinical credibility.** A score that does not align with an established instrument is a number floating in space; SLPs reasonably ignore it. The system's outputs map to established instruments (Goldman-Fristoe-aligned, Hodson-aligned, SSI-4-aligned, CAPE-V-aligned, VHI-aligned, and so on) with explicit disclosure of the alignment method and validation evidence per instrument. 

**Per-item confidence scoring with SLP-review flags is essential.** The system scores each test item with a confidence value. Items below the threshold are flagged for SLP review rather than auto-scored. The aggregate score reflects the auto-scored items plus the SLP-reviewed items. Pretending the system is confidently right about every item, when it is not, breaks SLP trust and produces clinical errors.

**Longitudinal trajectory often beats single-session assessment.** Within-patient progress is the clinically richest signal. The architecture maintains per-patient feature histories, computes within-patient deltas appropriately calibrated to within-patient typical variation, and surfaces the trajectory alongside the single-session score.

**Workflow placement determines regulatory exposure.** A tool that produces autonomous diagnostic claims is in a different regulatory category from a tool that supports SLP workflow with SLP-in-the-loop scoring. The architecture supports both placements, with explicit configuration per deployment context. The institution and the vendor are clear about which regulatory category they are operating in.

**School-context deployments have specific privacy considerations.** School-based SLP work falls under FERPA in addition to HIPAA where applicable. Consent for minors requires parent or guardian authorization, and the school's existing processes for educational records apply. The architecture supports school-context configurations with appropriate consent and storage segregation.

**Telepractice audio differs from in-clinic audio.** Telepractice introduces video-call codec compression, network packet loss, ambient home noise, and microphone variability. The acoustic models, the quality assessment, and the eligibility gating all need telepractice-specific configuration. The system either constrains the telepractice capture (specific recommended apps, microphone guidance) or validates broadly across realistic telepractice conditions.

**Home-practice and parent-coaching applications are different products from clinical assessment.** A child practicing target sounds at home with a mobile app, with the system providing immediate feedback, is a different product context from an SLP performing an annual reassessment. The architecture supports both with shared infrastructure but distinct workflow surfaces and distinct clinical-action mappings.

**Multilingual speakers warrant language-aware pipelines, not just translated stimuli.** A bilingual Spanish-English child has phonological-pattern profiles that differ from monolingual English children. Articulation assessment in bilingual populations requires bilingual-aware norms, language-specific phoneme models, and explicit handling of code-switching during assessment. Translating the stimulus list is not enough.

**Audio retention policy is bounded by consent and protected by encryption.** Voice samples from speech-therapy assessment are biometric data. Retention is bounded to what consent supports and what clinical and regulatory needs require. Audio retention beyond the immediate scoring window benefits the longitudinal-comparison and model-improvement workflows; the institution's privacy officer reviews the retention policy explicitly.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter10.09-architecture). The Python example is linked from there.

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, simplest analog. The audio capture and speech-recognition primitives appear here at much lower clinical stakes.
- **Recipe 10.2 (Voicemail Transcription and Classification):** Same chapter, asynchronous single-speaker analog. The async-audio-processing pattern is the closest pattern to the asynchronous speech-therapy scoring path.
- **Recipe 10.3 (Voice-to-Text for electronic health record (EHR) Navigation):** Same chapter, single-speaker voice-input analog. Different goal but same audio-capture infrastructure foundation.
- **Recipe 10.4 (Medical Transcription / Dictation):** Same chapter, single-speaker high-quality-capture analog. The custom-vocabulary patterns from 10.4 inform the linguistic-feature pipelines for connected-speech analysis.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Same chapter, patient-facing voice-interaction analog. The patient-acceptance and consent patterns from 10.5 inform patient-facing home-practice deployments.
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Same chapter, telehealth-audio analog. The per-cohort accuracy discipline from 10.6 transfers directly to per-population speech-therapy validation discipline.
- **Recipe 10.7 (Ambient Clinical Documentation):** Same chapter, in-room conversational-audio analog. The shared in-room audio infrastructure and the SLP-augmentation workflow patterns are closely related.
- **Recipe 10.8 (Voice Biomarker Detection):** Same chapter, acoustic-feature-pipeline analog. Many of the architectural patterns (per-population validated models, eligibility gates, indeterminate-result handling, per-cohort calibration, post-deployment surveillance) transfer directly. The clinical question is different: voice biomarkers measure disease state from voice acoustics; speech-therapy assessment measures the speech production itself against established assessment instruments.
- **Recipe 10.10 (Multilingual Real-Time Medical Interpretation):** Same chapter, multilingual analog. The per-language pipeline patterns are shared with the multilingual speech-therapy variations.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2, LLM-driven patient-facing summary generation. The patient-and-parent-facing summary patterns from 2.5 apply directly to family-summary generation.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2, LLM-driven structured-data-to-prose generation. The SLP-report generation patterns are closely related.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4, personalization patterns. Home-practice prompt scheduling and parent-coaching content selection use related personalization patterns.
- **Recipe 7.x (Predictive Risk Modeling):** Chapter 7, risk scoring and trajectory analysis. Speech-therapy progress prediction and discharge-readiness scoring are predictive-analytics extensions of the longitudinal data.
- **Recipe 8.x (Clinical natural language processing (NLP) & Information Extraction):** Chapter 8, traditional NLP. Linguistic-feature extraction from connected-speech transcripts uses traditional NLP primitives in addition to the LLM-driven extraction.

---

## Tags

`speech-voice-ai` · `value-based-care` · `longitudinal` · `audit-trail` · `bipa` · `consent-management` · `fda-pathway` · `phi-handling` · `hipaa` · `privacy` · `clinical-validation` · `bedrock-guardrails` · `api-gateway` · `athena` · `bedrock` · `cloudtrail` · `cloudwatch` · `cognito` · `dynamodb` · `eventbridge` · `glue` · `healthlake` · `kinesis-firehose` · `kms` · `lambda` · `quicksight` · `s3` · `sagemaker` · `sagemaker-clarify` · `sagemaker-model-monitor` · `secrets-manager` · `step-functions` · `transcribe-medical`
