# Recipe 10.8: Voice Biomarker Detection ⭐⭐⭐

**Complexity:** Complex · **Phase:** Research-and-pilot-track for most indications, production-track for narrow validated use cases · **Estimated Cost:** ~$0.05-0.40 per voice sample analyzed (varies with sample length, feature pipeline complexity, model count, and whether cloud-managed acoustic analysis services are used)

---

## The Problem

There is a thirty-second clip of a patient saying the standard pangram ("the quick brown fox jumps over the lazy dog") sitting on a hard drive somewhere. To the patient, it is unremarkable: their voice, a sentence they have read twice, a brief moment between intake and the rest of the visit. To a trained neurologist listening carefully, there are signals in that thirty seconds that tell a story. The voice has a slightly breathy quality the patient did not have at last year's visit. The pitch range has narrowed by maybe fifteen percent. The cadence has small hesitations that were not there before. The patient has not noticed any of this. The patient's family has not noticed any of this. The neurologist, if they are paying close attention and they happen to remember last year's voice, might catch one of these. The combination of all three, and the trajectory across visits, is the kind of pattern that points toward early Parkinson's disease, sometimes years before the motor symptoms become unmistakable. The clip on the hard drive contains the answer to a question no one has asked yet.

This is the premise of voice biomarkers, and it is one of the most seductive ideas in healthcare AI. Voice is everywhere. Patients produce it constantly, for free, without a needle, without a scanner, without a copay. The acoustic signal carries information about the speaker's vocal tract anatomy (which tells you about head and neck structure, weight, smoking history), the vocal tract's neuromuscular control (which tells you about cranial nerve function, basal ganglia function, and a long list of neurological conditions), the airway and respiratory effort (which tells you about pulmonary function, diaphragm strength, congestion, infection), the cognitive load required to produce fluent speech (which tells you about attention, working memory, language fluency, and early dementia), and the emotional state of the speaker (which tells you about mood, anxiety, depression, and suicidal ideation). A complete voice analysis at scale could in principle screen for Parkinson's, ALS, multiple sclerosis, stroke, dementia, depression, suicidality, COPD exacerbation, asthma exacerbation, congestive heart failure exacerbation, COVID and other respiratory infections, anesthesia recovery, post-stroke aphasia recovery, and concussion. It is not crazy to imagine a future where every patient leaves a thirty-second voice sample at every primary-care visit and the system flags the trajectory changes for the clinician's attention.

That future is not here. It is closer than it was five years ago, but the gap between the marketing pitch and the clinically deployable reality is wide, and the gap is not closing as fast as the field's enthusiasts would like. The reasons are mostly not the AI; the AI for analyzing the voice signal is, by 2025-2026 standards, a moderately mature problem. The reasons are clinical-validation reasons, regulatory reasons, demographic-equity reasons, recording-quality reasons, and reproducibility reasons.

The clinical-validation problem is the central one. A voice biomarker for any specific condition (say, Parkinson's) needs to demonstrate that the acoustic features it measures distinguish patients with the condition from patients without, in a population that looks like the population the system will be deployed in, with sensitivity and specificity that justify the clinical action the system is meant to inform. Building this evidence requires a longitudinal cohort with verified clinical outcomes (Parkinson's diagnosis confirmed by movement-disorder neurologists, ideally with imaging-confirmed dopaminergic deficit), voice samples collected from that cohort under controlled and reproducible conditions, and statistical demonstration that the biomarker performs across age groups, both sexes, multiple language backgrounds, and various recording conditions. This is a multi-year, multi-site, often multi-million-dollar evidence package. Most voice biomarker companies do not have it. The ones that do, usually have it for a narrow indication and a narrow population. Generalizing beyond the validated indication and population is exactly the trap that makes voice biomarkers feel further from production than the algorithm performance suggests.

The regulatory problem is layered on top. A voice biomarker that diagnoses, treats, prevents, or mitigates a disease, or that measures a disease state, is a medical device under FDA's authorities. The Software as a Medical Device (SaMD) framework applies. The regulatory pathway is through 510(k), De Novo, or PMA depending on novelty and risk. The pathway is not theoretical: FDA has been clearing voice and acoustic-analysis devices for narrow indications, but the bar is real, the evidence package is substantial, and the post-market surveillance obligations continue indefinitely. <!-- TODO: verify FDA's current SaMD framework and recent voice-biomarker clearances; the regulatory landscape continues to evolve --> Many voice biomarker products avoid the regulatory bar by framing themselves as wellness tools or as research instruments, which limits the clinical claims they can make and limits the workflows they can be embedded in. The ones that go for the regulatory bar take longer to ship and cost more to build.

The demographic-equity problem is the one that catches teams off guard. Voice biomarkers are sensitive to age, sex, native language, regional accent, smoking history, body habitus, denture status, hormonal status, and a list of other speaker properties that have nothing to do with the condition the biomarker is trying to measure. A model trained mostly on middle-aged white American men will perform meaningfully worse on older women, on speakers of African American English, on speakers of Spanish-influenced English, and on patients with dentures. This is not a tuning problem; it is a representation problem in the training data, and fixing it requires intentional cohort design from the start. The published literature is full of voice biomarker results from cohorts where the demographic distribution is unrepresentative of any actual clinical population, and the published performance numbers do not transfer when the system is deployed against the real population. The harder path (assemble a representative cohort, demonstrate cross-cohort performance, publish per-cohort metrics) is the path that produces clinically credible biomarkers; the easier path (use whatever data is convenient, publish the average, ship to anyone) produces biomarkers that fail in production for the patients who would benefit most.

The recording-quality problem is mostly an engineering problem with a clinical-validation tail. Voice biomarkers measure subtle acoustic features (jitter, shimmer, harmonic-to-noise ratio, formant trajectories, spectral tilts) that are sensitive to the recording chain: the microphone's frequency response, the analog front-end's noise floor, the codec's compression artifacts, the network's packet handling, the ambient noise in the recording environment. The same patient saying the same sentence into a high-quality studio microphone, into a smartphone, into a phone-call codec, and into a video-call codec produces four meaningfully different acoustic feature vectors, and the differences can swamp the disease-related signal the biomarker is trying to measure. A model trained on one recording chain does not transfer to another. The fix is either to standardize the recording chain (which limits where the biomarker can be deployed) or to engineer the feature pipeline to be invariant to the recording chain (which is genuinely hard and never fully succeeds), or both.

The reproducibility problem is the one the field is wrestling with most painfully. Many published voice biomarker results from the 2018-2022 wave of papers have not replicated when other teams have tried to reproduce them, often because the original results were fit on small datasets with subtle leakage between train and test (same speaker in both, similar recording sessions in both), or because the original results used demographic confounds as the actual predictive signal rather than the disease-specific acoustic features the paper claimed to be measuring. <!-- TODO: verify; the voice-biomarker reproducibility crisis has been documented in multiple meta-analyses and is an active area of methodological work in the field --> The methodological practices that produce reproducible voice biomarker results (speaker-disjoint train and test splits, controlled-confound experimental design, pre-registered analysis plans, open data and code) have only become standard expectations in the field in the last few years, and the community is still working through which historical results survive the more careful reanalysis.

So when an institution's clinical leadership asks, "should we be using voice biomarkers?" the honest answer is some version of "for some narrow indications, yes, with appropriate evidence, and at appropriate workflow placement; for most indications, not yet." This recipe is about how to build the architecture that makes the "yes for narrow indications" answer practical, that supports the "research-and-pilot" workflows that mature the science for the not-yet indications, and that does not over-promise on either.

The two indications where voice biomarkers have the strongest clinical evidence as of 2025-2026 are respiratory monitoring (cough analysis, vocal effort changes in COPD and asthma exacerbation, post-COVID recovery monitoring) and Parkinson's disease screening and progression monitoring. <!-- TODO: verify; the indications with the strongest published evidence continue to evolve as new research is published --> Mental health voice biomarkers (depression severity, suicidality risk) have growing but more contested evidence and are typically deployed as decision-support signals to clinicians rather than as standalone screens. Cognitive-decline voice biomarkers (early dementia detection from speech fluency and word-finding patterns) are an active research area with promising but not yet definitive evidence. Other indications (cardiovascular risk, diabetes screening, sleep disorder detection from voice) are earlier-stage and should be treated as research, not as clinical-grade tools.

If you read recipe 10.4 (Medical Transcription / Dictation), recipe 10.6 (Speech-to-Text for Telehealth Documentation), and recipe 10.7 (Ambient Clinical Documentation), the audio-capture infrastructure overlaps. The downstream processing is dramatically different. Speech-to-text recipes care about converting acoustic signal into text and discarding the rest; voice biomarker detection cares about exactly the rest. The lossy compression and aggressive noise suppression that improve speech-to-text accuracy can destroy the subtle acoustic features that voice biomarkers measure. If you are sharing audio infrastructure across speech-to-text and voice biomarker workflows, the audio retention, encoding, and processing decisions need to support both, which usually means keeping a higher-fidelity audio path for the biomarker workflows even when the speech-to-text workflows do not need it.

Let's get into how this actually works.

---

## The Technology: Voice as a Clinical Signal

### What Voice Actually Tells You About a Body

The voice signal is the product of three coupled systems: the respiratory system (lungs and diaphragm pushing air past the larynx), the laryngeal system (vocal folds vibrating at the patient's fundamental frequency, controlled by recurrent laryngeal nerve innervation), and the supralaryngeal vocal tract (mouth, tongue, soft palate, nose, lips) shaping the resulting buzz into intelligible speech sounds. Anything that affects any of these systems leaves an acoustic fingerprint. The clinical question is which fingerprints carry useful diagnostic or monitoring information, and which are just speaker-to-speaker variation that has nothing to do with disease.

A few categories worth knowing.

**Vocal fold function and laryngeal control.** When the vocal folds vibrate, small irregularities in their vibration produce measurable acoustic features. Jitter is cycle-to-cycle variation in fundamental frequency. Shimmer is cycle-to-cycle variation in amplitude. Harmonic-to-noise ratio measures how much of the vocal signal is the periodic harmonic structure of voiced speech versus aperiodic noise from incomplete vocal-fold closure. These features are sensitive to neuromuscular control of the larynx, which is innervated by the recurrent laryngeal nerve and modulated by basal-ganglia output. Parkinson's disease, ALS, post-stroke dysarthria, and laryngeal pathologies all produce characteristic patterns in these features. The features are also sensitive to age (elderly speakers have higher jitter and shimmer at baseline), sex (women have different baseline values than men), smoking status, and recent voice use; controlling for these confounds is the methodological work that separates a clinically credible biomarker from a demographic-detector dressed up as a disease-detector.

**Speech timing and rhythm.** Speech rate, pause duration, pause frequency, voice-onset time (the gap between releasing a stop consonant and the start of vocal-fold vibration), and articulation rate all reflect motor planning and execution. Slow, halting speech with prolonged pauses is a non-specific feature of many neurological conditions, of major depression, of advanced fatigue, and of cognitive load. Specific patterns in pause distribution and articulation rate distinguish some conditions: Parkinsonian speech tends toward rushed, hypophonic delivery with reduced prosodic variation; depressed speech tends toward slowed delivery with increased pause duration; aphasic speech tends toward word-finding pauses concentrated at content-word locations. These features require longer speech samples (typically thirty seconds to several minutes of continuous speech) than simple acoustic measures, because the statistical patterns only stabilize over enough utterances.

**Prosody and pitch dynamics.** Fundamental-frequency contour over an utterance carries information about prosodic control. Reduced pitch range (monotone speech) is characteristic of Parkinson's, depression, and reduced affect from a long list of causes. Inappropriate pitch contour (rising at sentence-end where falling is expected, or vice versa) can reflect specific neurological lesions or specific psychiatric states. Speech that varies appropriately with content has different fundamental-frequency statistics than speech that does not. Prosody features are language-specific, accent-specific, and culture-specific; the methodological care required to distinguish disease-related prosodic flattening from culture-or-individual baseline is substantial.

**Articulation precision.** The clarity of consonant production, the precision of vowel formant placement, and the consistency of articulatory targets reflect the integrated function of the vocal tract's motor control. Slurred consonants, vowel centralization (vowels drifting toward a central neutral position rather than the corners of the vowel space), and reduced articulatory precision distinguish many neurological conditions and intoxication states. Dysarthria is the umbrella clinical term; its acoustic signatures vary by underlying cause (spastic, flaccid, ataxic, hypokinetic, hyperkinetic, mixed) and form an active sub-discipline of speech pathology. Voice biomarkers for neurological conditions often combine articulation features with the laryngeal and timing features above to build a more reliable signal than any single feature class provides.

**Respiratory sounds and effort.** Cough has acoustic characteristics that distinguish dry from wet cough, productive from non-productive, the cough of an asthma exacerbation from the cough of a viral upper respiratory infection from the cough of pertussis from the cough of pneumonia. <!-- TODO: verify; cough acoustic classification has been studied extensively but production-grade clinical-classification accuracy varies by indication and population --> Vocal effort changes (a more breathy or strained voice quality) reflect respiratory effort and can serve as proxies for the patient's perception of dyspnea. Sleep-related respiratory sounds (snoring patterns, apneic pauses) carry information about obstructive sleep apnea severity. The respiratory acoustic class is interesting because the underlying physiology is well-understood, the sound-to-phenomenon mapping is more direct than for neurological biomarkers, and the data is plentiful (cough is a high-prevalence symptom and the acoustic events are short, making cohort assembly easier).

**Cognitive and linguistic features beyond acoustics.** When the analysis includes the transcribed text of the speech sample (which is a recipe-10.4-or-10.6-style problem that produces text from the audio), additional features become available: lexical diversity, syntactic complexity, idea density, word-finding patterns, semantic coherence. Cognitive-decline biomarkers usually combine acoustic features (timing, articulation) with linguistic features extracted from the transcript (word-finding pauses, lexical retrieval failures, repeated phrases, simplified syntax). The interaction between the acoustic feature pipeline and the speech-to-text feature pipeline is part of the architectural complexity for cognitive-focused biomarkers.

**Affect and arousal.** Emotional state has well-established acoustic correlates: arousal correlates with pitch, intensity, and speaking rate; valence correlates with prosodic contour. Voice-based affective computing has a long research tradition, and depression-screening voice biomarkers borrow heavily from this tradition. The clinical translation is harder than the basic-science work suggests. A voice that sounds depressed in a controlled research recording might sound depressed because the speaker is depressed, or because they are tired, or because they are coming off a difficult day, or because the recording environment is uncomfortable, or because they are speaking to a stranger. Disentangling state effects (transient depressive mood) from trait effects (clinical major depression) is the methodological challenge that most published affect biomarkers have not adequately solved.

The clinical interpretation of any single feature category is always probabilistic. A patient with high jitter is not a Parkinson's patient; they might be elderly, they might smoke, they might have a cold, they might have laryngeal pathology unrelated to neurology. The voice-biomarker pipeline's job is to combine many features across many categories, controlling for the confounds, to produce a probabilistic signal that correlates with the clinical condition the biomarker is targeting. The resulting signal is rarely a binary diagnosis. It is more often a continuous-valued risk score, a category (high-risk vs. low-risk vs. indeterminate), or a longitudinal trajectory metric (this patient's voice has changed in a way that suggests progression worth a clinician's review). The workflow placement of the biomarker has to match what the signal can actually support clinically.

### The Acoustic Feature Pipeline

The classical voice-biomarker pipeline is feature-engineering-heavy. The audio comes in; a feature pipeline extracts a few hundred to a few thousand acoustic features per sample (jitter, shimmer, HNR, MFCCs, formant trajectories, prosodic features, spectral features), the features go into a model (logistic regression, random forest, gradient boosted trees, more recently neural-network feature selectors on top of the engineered features), and the model produces the biomarker output. This pipeline is well-understood, tooling is mature (the openSMILE library, the eGeMAPS feature set, the Praat acoustic-analysis package, voice-quality toolkits from speech-pathology research), and the resulting features are interpretable. A clinician reviewing a flagged biomarker can drill into "this patient has elevated jitter and shimmer with reduced harmonic-to-noise ratio, plus reduced pitch range and slowed articulation," and the features map back onto vocal-fold control and prosodic control concepts that mean something clinically.

The deep-learning pipeline replaces or augments the feature-engineering stage with learned representations from large pretrained speech models. Self-supervised speech models (wav2vec 2.0, HuBERT, WavLM) trained on large unlabeled speech corpora produce learned representations that capture acoustic and linguistic structure. <!-- TODO: verify; these self-supervised speech models are the current dominant family but the field continues to evolve --> Voice-biomarker work that uses these representations either fine-tunes the pretrained model on the biomarker task or uses the frozen representations as features for a downstream classifier. The deep-learning pipeline often outperforms the feature-engineering pipeline on raw classification accuracy, especially when training data is plentiful, but the resulting models are less interpretable, harder to validate clinically, and more vulnerable to learning demographic or recording-chain confounds rather than the disease-relevant signal.

The hybrid pipeline combines both. Engineered features for the interpretable, clinically-grounded part of the signal; learned representations for the parts of the signal that are harder to capture explicitly; a downstream model that integrates both. Most production-grade voice-biomarker systems use some form of hybrid approach. The exact mix depends on the indication, the available training data, and the regulatory context (a 510(k)-cleared device often leans on engineered features because they support a more transparent validation story; a wellness-product voice biomarker can lean more on deep learning because the regulatory bar is lower).

The feature pipeline is sensitive to recording quality in ways that production teams underestimate. The same speaker producing the same utterance, with all clinical state held constant, will produce meaningfully different feature vectors when recorded through different microphones, different codecs, or different network conditions. The mitigation strategies form a discipline of their own.

**Microphone characterization and calibration.** A high-grade voice-biomarker capture path uses microphones with known frequency-response characteristics, ideally with a per-device calibration step. A consumer-device capture path (smartphone, telehealth video call, telephony call) accepts that the microphone characteristics vary widely and engineers the downstream pipeline to be tolerant. The tolerance is partial; codec-related distortion is a hard problem and the loss of fidelity at the high frequencies that telephony codecs aggressively compress is a measurable ceiling on the biomarker accuracy.

**Codec normalization.** Audio captured through a telephony call (8 kHz sample rate, narrow-band codec) carries less information than audio captured through a high-quality video call (typically 16 kHz or higher, opus codec or similar). Audio captured through a wellness-app native recording at 44.1 kHz or 48 kHz with no compression carries the most information. The biomarker pipeline either targets a single capture path and normalizes others to it, or trains and validates separately per capture path, or uses bandwidth-aware processing that gracefully degrades when the input bandwidth is limited. Each strategy has trade-offs; the choice depends on the deployment context.

**Environmental noise and reverberation.** Background noise (room HVAC, traffic, household sounds for at-home recording, clinic-environment sounds for in-clinic recording) and room reverberation (the acoustic signature of the space the recording is made in) modify the captured audio in ways that affect feature extraction. Robust feature extraction either uses noise-suppression preprocessing (which can damage the subtle features the biomarker depends on) or accepts a degree of contamination and validates the system's tolerance to realistic noise conditions. The "validate against realistic noise" approach is the more defensible one but requires substantial work in the validation cohort design.

**Speaker effort and prompt design.** What the speaker is asked to do affects what features are measurable. A sustained-vowel phonation task ("say 'ah' for as long as you can") produces clean signal for vocal-fold-function features but yields no information about articulation or prosody. A read-passage task (reading the standard "Rainbow Passage" or a similar phonetically-balanced text) yields all the feature classes but introduces reading-fluency as a confound. A spontaneous-speech task (describing a picture, telling a story, answering open-ended questions) yields the richest information but introduces task-completion variability. Most production voice-biomarker workflows use multi-task protocols (sustained vowel plus read passage plus brief spontaneous speech) to capture the full feature spectrum reliably.

**Multi-session aggregation.** Single-session voice samples are noisy. Patient-specific factors (recent voice use, hydration, time of day, current respiratory infection) introduce session-to-session variation that can swamp the disease-related signal in a single sample. Multi-session aggregation (collecting samples across multiple days, sometimes weeks, and averaging or otherwise combining the per-session features) reduces the within-speaker variance and improves the per-patient signal-to-noise ratio. This is a workflow constraint, not a technical one; the patient has to come back, or the biomarker has to be deployed in a context that produces multiple naturally-occurring samples (a telehealth-monitoring program with weekly check-ins, an ambient documentation pipeline that produces multiple in-clinic samples per year).

### Validation Discipline

The hardest part of voice biomarker work is not the algorithm; it is the validation. Several methodological practices distinguish defensible voice biomarker science from the speculative work that does not survive replication.

**Speaker-disjoint train and test splits.** Voice features are heavily speaker-specific. A model that can identify which speaker is producing a sample (which is a much easier task than diagnosing a disease) will produce inflated performance numbers if the same speaker appears in both training and testing. Speaker-disjoint splits (a speaker's data is in either train or test, never both) are the baseline expectation. Many published voice-biomarker results from the early literature did not respect this discipline and consequently overstated their accuracy.

**Confound-controlled experimental design.** When the model's training data has demographic distributions that correlate with the disease label (older speakers more likely to have Parkinson's; women more likely to have certain conditions; smokers more likely to have certain pulmonary conditions), the model can learn the demographic features rather than the disease-specific features and still appear to perform well on a similarly-distributed test set. The mitigation is some combination of stratified sampling, propensity matching, or explicit confound modeling so that the disease-specific signal is what the model is learning. The cohort design that supports this analysis is upstream of the modeling work; getting it right requires the clinical team and the data team to work together from the start of the study.

**Per-cohort performance reporting.** A single accuracy number, averaged across the entire test set, hides per-cohort failures. Defensible voice-biomarker reporting includes per-age-band, per-sex, per-language, per-recording-condition performance, with explicit attention to the cohorts where performance is weakest. This is the disclosure that lets a clinician using the biomarker know when to trust it and when to discount it. Recipe 10.6 covered the same per-cohort discipline for speech-to-text accuracy; the principle is identical for voice biomarkers, with additional cohort axes for the biomarker-specific recording conditions.

**Pre-registration and held-out validation.** The strongest evidence comes from analyses that were pre-registered (the analysis plan was specified before the data was collected or before the test set was unblinded), with held-out validation cohorts that the team could not see during model development. Pre-registration prevents the inadvertent selection of analytical choices that flatter the result. Held-out validation prevents the implicit fitting of model architecture or hyperparameters to the test set through repeated evaluation. Both practices are increasingly expected by FDA's review process for SaMD voice biomarkers.

**Prospective clinical validation, not just retrospective performance.** A retrospective analysis (apply the biomarker to a previously-collected dataset) is a starting point. A prospective clinical validation (deploy the biomarker in a clinical workflow and measure its real-world clinical impact: did using the biomarker change clinical decisions in defensible directions; did patient outcomes change as a result) is the bar that institutional adoption requires. Prospective validation is slow (often years), expensive (often hundreds of thousands of dollars per indication), and methodologically difficult. It is also the difference between a research instrument and a clinical tool.

**Continuous post-market surveillance.** A biomarker that performed well in pre-deployment validation can degrade in production for many reasons: the deployed population differs from the validation population, the recording infrastructure differs, the deployed clinical workflow induces selection biases that shift the patient mix, the underlying clinical practice patterns change. Post-market surveillance (continued monitoring of biomarker performance against ground-truth clinical outcomes, with mechanisms for re-validation and re-training when drift is detected) is part of any responsible deployment. For SaMD-cleared devices, FDA increasingly expects ongoing post-market surveillance plans as part of the original clearance.

### Where the Field Has Moved

A few practical updates worth knowing.

**Self-supervised speech models have raised the floor.** The wav2vec 2.0, HuBERT, WavLM, and related families of self-supervised speech models trained on large unlabeled speech corpora produce representations that capture much of the acoustic structure of speech without requiring labeled training data. Voice-biomarker work that uses these representations as features (frozen or fine-tuned) has typically outperformed older feature-engineering pipelines on raw classification accuracy, with the trade-offs in interpretability and confound-vulnerability noted above. <!-- TODO: verify; the dominant pretrained-speech-model families continue to evolve -->

**Cough-classification models have reached production maturity for narrow indications.** Cough analysis was an early commercial-success story for voice biomarkers. Several clinical-grade cough-classification products have shipped, with applications in COPD exacerbation monitoring, asthma management, and infection screening. The acoustic features of cough are tractable, the data is plentiful, and the clinical use case is bounded.

**FDA has cleared a handful of voice-biomarker SaMD devices.** The regulatory pathway is real, and there are 510(k) and De Novo clearances for voice-based medical devices, often for narrow indications and narrow populations. <!-- TODO: verify; specific recent voice-biomarker clearances should be checked against FDA's current device databases --> The cleared products serve as templates for what an FDA-acceptable evidence package looks like and provide reference points for institutions evaluating voice-biomarker vendors.

**Mental-health voice biomarkers have entered cautious clinical pilots.** Voice-based depression severity scoring, suicidality risk screening, and PTSD assessment have all been studied in clinical settings. The most promising deployments are decision-support signals to clinicians rather than standalone diagnoses. The methodological challenges (state vs. trait, demographic confounds, acceptability and consent) are substantial. Several institutions have run cautious pilots; broader adoption awaits stronger validation.

**Cognitive-decline voice biomarkers are an active research area.** Speech-based early-dementia detection has been a major research focus, with promising preliminary results from Alzheimer's-disease cohorts and aging populations. The clinical translation is still earlier-stage than the cough or Parkinson's biomarkers. <!-- TODO: verify; the cognitive-decline voice-biomarker literature has been growing rapidly with mixed reproducibility -->

**The reproducibility movement has reached the field.** Pre-registered studies, open data and code, speaker-disjoint validation, and per-cohort reporting are increasingly standard expectations. Older results that did not follow these practices are being re-evaluated, with mixed outcomes. The field is healthier for the methodological maturation, even if some early-promising results have not survived the more careful reanalysis.

**Privacy and biometric concerns have intensified.** Voice is a biometric identifier. The same voice sample that supports the biomarker is, by itself, an identifier of the speaker. Storage, retention, and disclosure of voice samples raise biometric-data governance issues distinct from standard PHI handling. Some jurisdictions (Illinois under BIPA, similar laws in Texas and Washington) have specific requirements for biometric-data handling; <!-- TODO: verify; the state-by-state biometric-data law landscape continues to evolve --> the institution must treat the voice sample as both PHI and biometric data, with the more restrictive requirements applying.

**Multi-modal integration is the emerging architecture.** Voice biomarkers, on their own, rarely provide the strongest possible clinical signal. Combined with other data modalities (clinical history from the EHR, wearable-device data, structured questionnaire responses, prior visit summaries), they often improve the combined signal substantially. The architectural pattern is shifting from voice-biomarker-as-isolated-tool to voice-biomarker-as-one-input-among-several.

---

## General Architecture Pattern

A voice biomarker detection system decomposes into eight logical stages: capture protocol design and consent (the speaker is asked to perform specific tasks under specific conditions, with appropriate consent), audio capture and quality assurance (the audio is captured at sufficient fidelity and quality is verified before it enters the analysis pipeline), preprocessing and feature extraction (the audio is processed into the acoustic and linguistic features the biomarker model consumes), per-indication biomarker scoring (one or more models produce indication-specific scores), confidence and confound assessment (the system evaluates whether the result is clinically interpretable for this specific sample given the demographic and recording-quality context), clinical interpretation packaging (the score is packaged with the supporting features, the per-cohort calibration context, and the clinical-action guidance the institution has approved), clinician review or patient feedback (the score informs a clinical decision, a patient communication, or a research record), and longitudinal storage with post-market monitoring (the sample's score and metadata feed the per-patient trajectory and the institution-wide validation surveillance).

```
┌─────── CAPTURE PROTOCOL & CONSENT ───────────────────────┐
│                                                           │
│   [Indication-specific protocol selection]                │
│    - Sustained-vowel task                                 │
│    - Read-passage task                                    │
│    - Spontaneous-speech task                              │
│    - Cough-collection task                                │
│    - Multi-task combinations per indication               │
│   [Recording-context guidance]                            │
│    - Quiet environment recommended                        │
│    - Microphone distance and orientation                  │
│    - Time-of-day or fasting state where applicable        │
│   [Consent capture]                                       │
│    - Voice as biometric: explicit disclosure              │
│    - Retention policy: explicit communication             │
│    - Use limitation: research vs. clinical                │
│    - Per-jurisdiction biometric-data terms (BIPA, etc.)   │
│    - Right-to-withdraw and right-to-deletion              │
│   [Patient or clinician device selection]                 │
│           │                                               │
│           ▼                                               │
│   [Output: capture session with protocol, consent,        │
│    device profile, recording-context metadata]            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── AUDIO CAPTURE & QA ───────────────────────────────┐
│                                                           │
│   [Capture audio at protocol-specified fidelity]          │
│    - Native sample rate (16 kHz minimum, often 44.1+)     │
│    - Native bit depth (16-bit minimum)                    │
│    - Lossless or minimally-compressed encoding            │
│    - Avoid aggressive noise suppression on capture        │
│   [Real-time audio quality assessment]                    │
│    - Signal-to-noise ratio                                │
│    - Clipping detection                                   │
│    - Dropout detection                                    │
│    - Adequate task duration                               │
│    - Speaker-identity verification (single speaker)       │
│   [Recapture prompt on quality failure]                   │
│    - Patient or clinician asked to retry                  │
│    - Quality threshold institutionally configured         │
│   [Per-device characterization]                           │
│    - Microphone profile lookup                            │
│    - Codec identification                                 │
│    - Bandwidth assessment                                 │
│           │                                               │
│           ▼                                               │
│   [Output: high-fidelity audio sample with recording-     │
│    chain metadata and per-task quality scores]            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── PREPROCESSING & FEATURE EXTRACTION ───────────────┐
│                                                           │
│   [Voice activity detection and segmentation]             │
│    - Trim silence from sample boundaries                  │
│    - Identify task-specific segments                      │
│    - Reject segments below quality threshold              │
│   [Per-task feature extraction]                           │
│    - Sustained-vowel: jitter, shimmer, HNR, F0 stats      │
│    - Read-passage: timing, prosody, articulation,         │
│      formant trajectories, MFCCs                          │
│    - Spontaneous-speech: lexical and syntactic features   │
│      (requires speech-to-text), discourse coherence       │
│    - Cough: acoustic-event classification features        │
│   [Pretrained-model representation extraction]            │
│    - Self-supervised speech embeddings (frozen or         │
│      fine-tuned per indication)                           │
│   [Recording-chain normalization]                         │
│    - Bandwidth-aware feature filtering                    │
│    - Per-codec calibration where supported                │
│    - Per-microphone-class adjustments                     │
│           │                                               │
│           ▼                                               │
│   [Output: per-task feature vectors and embeddings,       │
│    with per-feature confidence and per-segment quality]   │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── PER-INDICATION BIOMARKER SCORING ─────────────────┐
│                                                           │
│   [Per-indication model invocation]                       │
│    - One model per validated indication                   │
│    - Indication eligibility check (does this protocol    │
│      and patient profile meet model's validation         │
│      population?)                                         │
│   [Engineered-feature classifier]                         │
│    - Logistic regression, gradient boosting, etc.         │
│    - Outputs a score with calibration                     │
│   [Pretrained-representation classifier]                  │
│    - Self-supervised speech embedding-based model         │
│    - Outputs a score with calibration                     │
│   [Hybrid integration]                                    │
│    - Late fusion across feature classes                   │
│    - Per-cohort calibration                               │
│   [Indication-specific output]                            │
│    - Continuous risk score                                │
│    - Threshold-derived category                           │
│    - Trajectory delta if longitudinal                     │
│           │                                               │
│           ▼                                               │
│   [Output: per-indication score with calibration          │
│    context and feature contributions]                     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── CONFIDENCE & CONFOUND ASSESSMENT ─────────────────┐
│                                                           │
│   [Out-of-distribution detection]                         │
│    - Speaker demographics within validation distribution? │
│    - Recording chain within validation distribution?      │
│    - Task completion within validation expectations?      │
│   [Confound flags]                                        │
│    - Recent respiratory infection                         │
│    - Acute medication change                              │
│    - Speaker-reported fatigue                             │
│    - Out-of-language or unexpected accent                 │
│   [Uncertainty quantification]                            │
│    - Calibrated confidence interval on score              │
│    - Sub-threshold "indeterminate" output where           │
│      uncertainty exceeds clinical-action threshold        │
│   [Per-cohort calibration application]                    │
│    - Cohort-specific threshold and calibration            │
│    - Disclosure of cohort match in output                 │
│           │                                               │
│           ▼                                               │
│   [Output: clinically-interpretable score with explicit   │
│    confidence, confound flags, and indeterminate-result   │
│    handling]                                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── CLINICAL INTERPRETATION PACKAGING ────────────────┐
│                                                           │
│   [Score-to-action mapping per institutional policy]      │
│    - High-risk: clinician review prompt                   │
│    - Indeterminate: clinician review or recapture         │
│    - Low-risk: longitudinal store only                    │
│   [Supporting-evidence summary]                           │
│    - Top contributing features                            │
│    - Per-cohort calibration context                       │
│    - Trajectory context (current vs. patient baseline)    │
│   [Plain-language patient communication where applicable] │
│   [Workflow placement decision]                           │
│    - Decision-support signal to clinician                 │
│    - Direct patient communication                         │
│    - Research-only with no clinical-action mapping        │
│           │                                               │
│           ▼                                               │
│   [Output: indication-specific result package with        │
│    supporting evidence and clinical-action mapping]       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── CLINICIAN REVIEW OR PATIENT FEEDBACK ─────────────┐
│                                                           │
│   [EHR integration of result]                             │
│    - As decision-support flag                             │
│    - As discrete observation with appropriate coding      │
│    - As supporting evidence in clinician workflow         │
│   [Patient-facing display where applicable]               │
│   [Clinician acknowledgement and follow-up]               │
│   [Clinician override and feedback capture]               │
│   [Linkage to clinical action taken]                      │
│           │                                               │
│           ▼                                               │
│   [Output: result delivered to clinical workflow with     │
│    feedback loop for outcome tracking]                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌─────── LONGITUDINAL STORAGE & POST-MARKET MONITORING ────┐
│                                                           │
│   [Per-patient trajectory store]                          │
│    - Sample metadata (date, protocol, device, quality)    │
│    - Score, calibration context, confound flags           │
│    - Linked clinical outcomes where available             │
│   [Sample retention per consent and policy]               │
│    - Audio retention bound to consent terms               │
│    - Feature-vector retention typically longer            │
│    - Score retention as part of medical record            │
│   [Cohort-stratified post-market surveillance]            │
│    - Per-cohort accuracy vs. ground-truth outcomes        │
│    - Drift detection over time                            │
│    - Re-validation triggers                               │
│   [Regulatory reporting where applicable]                 │
│    - Adverse-event tracking                               │
│    - FDA post-market surveillance plan compliance         │
│           │                                               │
│           ▼                                               │
│   [Output: longitudinal record, surveillance metrics,     │
│    regulatory compliance artifacts]                       │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points the architecture has to bake in.

**Voice is biometric data, in addition to PHI.** Voice samples can identify the speaker independent of any other context. The privacy regime is the more restrictive of the applicable regimes: HIPAA at minimum, biometric-data law where applicable (Illinois BIPA, Texas, Washington and others), GDPR Article 9 special-category-data treatment for EU patients. The institution's biometric-data governance policy applies to voice samples explicitly. Audio retention is a privacy-officer-reviewed decision, not a default.

**Indication-specific validation is the architectural primitive.** A single model that produces a single biomarker output is rarely the right shape. The architecture supports multiple per-indication models, each with its own validation cohort, its own calibration, its own per-cohort threshold maps, its own indeterminate-result handling, and its own institutional approval status. Adding a new indication means adding a new validated model, not retraining an existing one to do more.

**Eligibility checking precedes scoring.** Each per-indication model has a validation population and a validation recording protocol. Before the model produces a score, the system checks whether the current sample fits the model's validation envelope: demographic fit, recording-chain fit, task-completion fit. Samples outside the envelope produce an "indication not assessable" result rather than a potentially-misleading score. This is a clinical-safety primitive, not an optimization.

**Indeterminate is a first-class output.** A clinically-defensible voice biomarker often returns an indeterminate result when the input quality is too low, the patient-specific confounds are too high, or the model's confidence is too low. The downstream workflow has to handle indeterminate gracefully: prompt for recapture, defer to clinician judgment, or note in the record without taking action. Treating every score as actionable is a clinical-safety failure mode.

**Per-cohort calibration with per-cohort thresholds.** A single threshold across a heterogeneous population produces disparate sensitivity and specificity per cohort. Per-cohort calibration with cohort-specific thresholds is the methodologically correct pattern, with the disclosure of which cohort the patient was assigned to as part of the result. The cohort axes (age, sex, language, recording context, indication-specific covariates) are part of the model's validation specification.

**Workflow placement is part of clinical safety.** A voice biomarker deployed as a decision-support signal to a clinician (with the clinician retaining diagnostic authority) is much lower-risk than the same biomarker deployed as an automated patient-facing screen. The architecture supports per-deployment-context configuration: research workflows, decision-support workflows, patient-facing workflows, automated triage workflows. Each has different safety, consent, and regulatory implications.

**Longitudinal trajectory often beats single-sample scoring.** Many voice biomarkers are more reliable as change-detectors over a patient's own baseline than as single-point classifiers against a population baseline. The architecture supports per-patient longitudinal series: a baseline established from multiple early samples, deltas computed against that baseline, trajectory analysis as a primary or secondary output. This requires the patient to produce multiple samples over time, which is a workflow constraint.

**Post-market surveillance is built in, not bolted on.** Voice biomarker performance can drift in production for many reasons. The architecture continuously monitors per-cohort accuracy against ground-truth clinical outcomes (where outcome data is available), tracks score-distribution drift, and flags re-validation triggers. For SaMD-cleared devices, the surveillance plan is a regulatory artifact; for non-regulated wellness products, it is an institutional-quality discipline. Either way, the system collects the data needed to detect performance degradation early.

**Audio is high-fidelity, retained briefly, and processed close to the source.** The biomarker pipeline benefits from full-fidelity audio. The privacy posture benefits from short audio retention. The reconciliation is a pipeline that processes the audio through feature extraction quickly (often within minutes of capture), stores the resulting feature vectors with longer retention than the audio itself, and discards the audio after the analysis is complete unless explicit consent supports longer retention.

**Failure modes degrade to clinician judgment.** When the biomarker pipeline fails (model unavailable, audio quality insufficient, eligibility check fails), the system produces an explicit "no result available" output, and the clinical workflow proceeds as it would have without the biomarker. The institution does not lose the encounter because the biomarker is unavailable.

---

## The AWS Implementation

### Why These Services

**Amazon S3 for high-fidelity audio sample storage.** The biomarker pipeline benefits from preserving the original captured audio at full fidelity. S3 holds the audio with SSE-KMS encryption using customer-managed keys, with a lifecycle policy that enforces the institutional audio-retention window (often hours to days, occasionally longer with explicit consent). A separate S3 bucket holds extracted feature vectors with longer retention; the feature vectors are derived data with substantially smaller per-sample storage cost and lower re-identification risk than the raw audio. A third bucket holds the audit archive for regulatory and clinical-quality review with Object Lock in compliance mode.

**Amazon SageMaker for per-indication model hosting and per-cohort calibration.** Voice biomarker models are typically not standard-catalog services; they are research-derived models for specific indications, often built on top of pretrained speech embeddings, with per-cohort calibration layers. SageMaker provides the model-hosting substrate. Each validated indication is hosted as a separate SageMaker endpoint or as a multi-model endpoint, with per-cohort threshold maps applied at the inference orchestration layer. SageMaker's monitoring features support post-market surveillance with model-quality monitor and data-quality monitor jobs against the inference traffic.

**Amazon SageMaker Inference Recommender and Asynchronous Inference for cost-efficient scoring.** Voice biomarker inference is not always real-time. Many use cases (longitudinal monitoring, research workflows, post-encounter analysis) tolerate near-real-time scoring (minutes rather than seconds). SageMaker Asynchronous Inference reduces cost compared to real-time endpoints for these workloads. Real-time endpoints serve the use cases where in-encounter feedback is required.

**AWS Lambda and AWS Step Functions for pipeline orchestration.** Per-stage Lambdas implement the orchestration: capture-finalization handler, audio-quality-assessment Lambda, feature-extraction Lambda, eligibility-check Lambda, scoring Lambda, interpretation-packaging Lambda. Step Functions coordinates the multi-stage pipeline with durable state, retry semantics, and observable failure handling. For real-time use cases the orchestration runs within tighter latency budgets; for asynchronous use cases the orchestration tolerates longer per-stage latencies.

**Amazon Transcribe Medical for the speech-to-text path used in cognitive and linguistic biomarkers.** When the biomarker pipeline uses linguistic features (lexical diversity, idea density, word-finding patterns) extracted from spoken samples, Transcribe Medical produces the transcript that the linguistic-feature extractor consumes. The transcript is used for biomarker feature extraction; it is not the primary output. Recipe 10.4 covers the medical-dictation transcribe pipeline; the same primitives apply here at lower volume.

**Amazon Comprehend Medical for clinical-entity extraction from spontaneous-speech samples.** Spontaneous-speech tasks (describing a picture, telling a story) sometimes include clinical content the system can use for both biomarker features (semantic coherence, topic adherence) and incidental clinical-content capture. Comprehend Medical extracts the clinical entities; the biomarker pipeline uses them as features and the orchestration layer routes any clinically actionable content (a patient describing chest pain in their spontaneous-speech sample, for instance) to the appropriate clinical workflow.

**Amazon Bedrock for natural-language interpretation packaging and clinician communication.** When the biomarker output needs to be summarized into a clinician-facing or patient-facing communication, Bedrock provides the LLM layer that converts the structured score into natural-language explanations. Bedrock is also useful for the linguistic-feature extraction in cognitive-decline biomarker pipelines, where LLM-judged semantic coherence and topic adherence are part of the feature pipeline. Recipe 2.6 (clinical note summarization) and recipe 2.5 (after-visit summary generation) cover the LLM-driven summarization patterns that apply here.

**Amazon Bedrock Guardrails for safety filtering on patient-facing communications.** When the biomarker output is communicated to the patient directly (not as a diagnosis but as patient-facing context), Guardrails apply content filters and contextual-grounding checks against the underlying biomarker output, ensuring the patient communication does not over-claim what the biomarker supports.

**AWS HealthLake for FHIR-based biomarker observation storage.** The biomarker score is an Observation resource in FHIR terms. HealthLake stores the FHIR Observations and supports the longitudinal-trajectory queries the workflow needs. For non-FHIR EHR integrations, the institutional EHR-integration layer translates the FHIR Observation into the EHR-specific representation. <!-- TODO: verify HealthLake's current FHIR resource support and Observation pattern coverage -->

**Amazon DynamoDB for per-patient longitudinal-state storage.** The per-patient trajectory data (baseline scores, score history, calibration context, confound flags per sample) is well-shaped for DynamoDB. A per-patient table with the patient hash as partition key and the sample timestamp as sort key supports the trajectory queries efficiently. KMS at rest with customer-managed keys.

**Amazon API Gateway for the capture and result APIs.** The patient-facing or clinician-facing capture experience submits audio through an API Gateway endpoint. The clinician-facing result-retrieval experience reads the structured biomarker output through API Gateway endpoints backed by Lambda. Cognito or institutional-IdP authentication applies to all endpoints.

**Amazon Cognito or institutional IdP via OIDC/SAML for authentication.** Clinician access to results uses the institutional identity provider with appropriate clinical-application scopes. Patient access (where applicable) uses a patient-identity flow with appropriate scopes.

**AWS KMS for cryptographic key custody.** Customer-managed keys for the audio bucket, the feature-vector bucket, the audit archive, the DynamoDB tables, and Secrets Manager. Voice samples and feature vectors use separate KMS keys for blast-radius containment and finer retention control. Per-state biometric-data law sometimes requires distinct cryptographic isolation; the architecture supports per-jurisdiction key management where required.

**AWS Secrets Manager for EHR integration credentials and any external-vendor API credentials.** The Lambdas that write biomarker results back to the EHR or that call external clinical-validation services hold their credentials in Secrets Manager with rotation per the institutional cadence.

**Amazon EventBridge for cross-system event flow.** Sample-capture, scoring-complete, and result-delivered events flow through EventBridge. Downstream consumers (the post-market surveillance pipeline, the operational dashboards, the patient-portal release workflow) react to events without coupling to the orchestration Lambdas.

**Amazon CloudWatch for operational metrics and alarms.** Per-stage latency, per-cohort score distributions, eligibility-check pass rates, indeterminate-result rates, audio-quality scores, post-deployment accuracy proxies. Alarms on per-cohort drift thresholds, on indeterminate-result-rate spikes, on aggregate accuracy regressions.

**AWS CloudTrail for API-level audit.** All access to PHI-bearing and biometric-data-bearing resources logged. SageMaker invocations logged. KMS key uses logged. CloudTrail logs in a dedicated bucket with Object Lock and lifecycle to S3 Glacier Deep Archive after 90 days.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon QuickSight (optional) for analytics.** Audit and telemetry flow to S3 via Firehose. Glue catalogs the data. Athena provides SQL access for the operational and post-market surveillance analytics. QuickSight renders the dashboards.

**Amazon SageMaker Model Monitor and Clarify for post-market surveillance.** Model Monitor compares production inference against the training-time baseline for data-quality drift and model-quality drift. Clarify produces feature-attribution and bias reports per cohort on a scheduled cadence. Together, they provide the per-cohort surveillance the regulatory and clinical-quality posture requires.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Capture
      PATIENT[Patient or<br/>Clinician Device]
      CONSENT[Consent and<br/>Protocol Capture]
      QA[Real-Time<br/>Audio QA]
    end

    subgraph Ingest
      APIGW_IN[API Gateway<br/>Capture API]
      L_INGEST[Lambda<br/>Sample Ingest]
      S3_AUDIO[(S3 Audio<br/>Brief Retention<br/>SSE-KMS)]
    end

    subgraph Pipeline
      SF[Step Functions<br/>Pipeline Orchestrator]
      L_FEAT[Lambda<br/>Feature Extraction]
      TS_MED[Transcribe Medical<br/>(linguistic biomarkers)]
      COMP_MED[Comprehend Medical<br/>(clinical entities)]
      L_ELIG[Lambda<br/>Eligibility Check]
      SM_PARK[(SageMaker Endpoint<br/>Parkinson's Model)]
      SM_RESP[(SageMaker Endpoint<br/>Respiratory Model)]
      SM_COG[(SageMaker Endpoint<br/>Cognitive Model)]
      L_CAL[Lambda<br/>Per-Cohort<br/>Calibration]
      L_PKG[Lambda<br/>Interpretation<br/>Packaging]
      BR[Bedrock<br/>NL Communication]
      BR_GR[Bedrock<br/>Guardrails]
    end

    subgraph Storage
      S3_FEAT[(S3 Feature Vectors<br/>SSE-KMS)]
      DDB_TRAJ[(DynamoDB<br/>Patient Trajectory)]
      HL[HealthLake<br/>FHIR Observations]
      S3_AUDIT[(S3 Audit Archive<br/>Object Lock)]
    end

    subgraph Workflow
      APIGW_OUT[API Gateway<br/>Result API]
      COGNITO[Cognito +<br/>Institutional IdP]
      EHR[EHR FHIR<br/>Integration]
      CLINICIAN[Clinician<br/>Decision-Support UI]
      PATIENT_VIEW[Patient-Facing UI<br/>(where applicable)]
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
      SM_SEC[(Secrets Manager<br/>EHR Creds)]
    end

    PATIENT --> CONSENT
    CONSENT --> QA
    QA --> APIGW_IN
    APIGW_IN --> L_INGEST
    L_INGEST --> S3_AUDIO
    S3_AUDIO --> SF
    SF --> L_FEAT
    L_FEAT --> TS_MED
    L_FEAT --> COMP_MED
    L_FEAT --> S3_FEAT
    SF --> L_ELIG
    L_ELIG --> SM_PARK
    L_ELIG --> SM_RESP
    L_ELIG --> SM_COG
    SM_PARK --> L_CAL
    SM_RESP --> L_CAL
    SM_COG --> L_CAL
    L_CAL --> L_PKG
    L_PKG --> BR
    BR --> BR_GR
    L_PKG --> DDB_TRAJ
    L_PKG --> HL
    L_PKG --> APIGW_OUT
    APIGW_OUT --> COGNITO
    APIGW_OUT --> CLINICIAN
    APIGW_OUT --> PATIENT_VIEW
    APIGW_OUT --> EHR
    EHR --> SM_SEC
    SF --> EB
    L_PKG --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    SM_PARK --> MM
    SM_RESP --> MM
    SM_COG --> MM
    MM --> CLAR
    SF --> CW
    APIGW_OUT --> CT
    KMS --> S3_AUDIO
    KMS --> S3_FEAT
    KMS --> S3_AUDIT
    KMS --> DDB_TRAJ
    KMS --> SM_SEC

    style SM_PARK fill:#fcf,stroke:#333
    style SM_RESP fill:#fcf,stroke:#333
    style SM_COG fill:#fcf,stroke:#333
    style TS_MED fill:#fcf,stroke:#333
    style COMP_MED fill:#fcf,stroke:#333
    style BR fill:#fcf,stroke:#333
    style BR_GR fill:#fcf,stroke:#333
    style MM fill:#fcf,stroke:#333
    style CLAR fill:#fcf,stroke:#333
    style DDB_TRAJ fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_FEAT fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
    style HL fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon S3, Amazon SageMaker (endpoints, Asynchronous Inference, Model Monitor, Clarify), AWS Lambda, AWS Step Functions, Amazon Transcribe Medical, Amazon Comprehend Medical, Amazon Bedrock (with Guardrails), AWS HealthLake, Amazon DynamoDB, Amazon API Gateway, Amazon Cognito, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally Amazon QuickSight for dashboards. |
| **Validated Models** | Per-indication validated voice-biomarker models. For most institutions this means selecting commercial vendors with FDA clearances or strong published evidence (cough analysis, Parkinson's screening) rather than building from scratch. Building from scratch requires a multi-year validation study with the cohort, evidence, and regulatory work that implies. The architecture supports either pattern: third-party model integration through SageMaker endpoint or vendor API; institutionally-built models hosted on SageMaker endpoints. <!-- TODO: verify; specific commercially available voice-biomarker products and their clearance status should be checked at build time --> |
| **External Inputs** | Capture-protocol scripts and prompts (per indication). Microphone characterization data for the supported capture-device classes. Per-cohort calibration data per validated model. Per-cohort threshold maps. Per-language linguistic-feature configurations where applicable. Validation cohort data for ongoing post-market surveillance. EHR FHIR write surface for biomarker Observation resources. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The capture-ingest Lambda has S3 write to the audio bucket only and SQS or EventBridge publish for the pipeline trigger. The feature-extraction Lambda has S3 read on the audio bucket and write on the feature bucket plus Transcribe and Comprehend Medical permissions. The scoring Lambda has SageMaker invoke-endpoint permissions for the validated indication endpoints only. The packaging Lambda has DynamoDB write, HealthLake write, Bedrock invoke-model, and EventBridge publish permissions. The EHR integration Lambda has Secrets Manager access for the EHR credentials and the EHR-specific egress only. Avoid wildcard actions and resources in production. |
| **BAA and Compliance** | AWS BAA signed. Amazon S3, SageMaker, Lambda, Step Functions, Transcribe (general and Medical), Comprehend Medical, Bedrock (verify the specific models and regions covered), HealthLake, DynamoDB, API Gateway, Cognito, KMS, Secrets Manager, EventBridge, CloudWatch Logs, CloudTrail, Kinesis Firehose, Glue, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference). <!-- TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continue to evolve --> Voice samples are biometric data; biometric-data law (Illinois BIPA, Texas, Washington, and similar) applies in addition to HIPAA where the patient's jurisdiction triggers it. SaMD regulatory consideration for any model that produces clinical claims; pre-deployment FDA strategy review for indications where a SaMD pathway is relevant. IRB or institutional review for research-track deployments and for cohort-development data collection. State-specific regulatory rules for any indication that intersects controlled-substance management, mental-health crisis response, or other regulated domains. |
| **Encryption** | Audio samples: SSE-KMS with customer-managed keys, retention bound to the consent terms (often hours to days, occasionally longer with explicit consent). Feature vectors: SSE-KMS with separate customer-managed keys, retention as needed for surveillance and re-validation per institutional policy. Biomarker results: SSE-KMS with customer-managed keys, retention aligned with the medical-record retention. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements (which can be longer than HIPAA's), state medical-records-retention rules, and institutional regulatory floor. DynamoDB tables, HealthLake datastore, Lambda environment variables, and Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all API calls. |
| **VPC** | Production: Lambdas that call back-office APIs (EHR FHIR, patient portal) run in VPC with controlled egress. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SageMaker Runtime, Transcribe, Comprehend Medical, Bedrock, Lambda. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where supported by the chosen container. |
| **CloudTrail** | Enabled with data events on the audio bucket, the feature bucket, the audit-archive bucket, the DynamoDB tables, the Secrets Manager secrets, and the customer-managed KMS keys. SageMaker invocations logged. Bedrock invocations logged with metadata only (not full input/output, to avoid persisting biometric or PHI content in CloudTrail). Lambda invocations logged. API Gateway access logs enabled. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. |
| **Sample Data** | Public voice-biomarker datasets for development and feature-pipeline validation. Examples include the mPower Parkinson's voice dataset, the Coswara cough dataset, and the DementiaBank speech corpora; each has its own access terms that must be reviewed before integration. <!-- TODO: verify dataset URLs, current availability, and license terms before integration; the public voice-biomarker dataset landscape evolves --> Synthetic capture-quality test signals for the audio QA pipeline (recordings of known-quality test tones, swept sines, or reference speech samples for microphone characterization). Never use uncoded production patient voice samples in development without explicit consent and IRB or institutional review; voice samples are biometric data with non-trivial governance implications. |
| **Cost Estimate** | At a mid-sized institution scale (50,000 voice samples per year, mixed across two or three indications): SageMaker endpoint hosting and inference at typically $25,000-100,000 per year depending on real-time vs. asynchronous and instance class. Transcribe Medical and Comprehend Medical at typically $5,000-15,000 per year. Bedrock at typically $1,000-5,000 per year for natural-language interpretation packaging. Lambda, Step Functions, S3, DynamoDB, HealthLake, CloudWatch, KMS, Secrets Manager, EventBridge, Kinesis Firehose, Glue, Athena total approximately $10,000-25,000 per year combined. Total AWS infrastructure typically $40,000-150,000 per year at this scale. The per-sample cost is dominated by the SageMaker model inference. The validation, regulatory, and clinical-evidence costs are typically much larger than the infrastructure costs at this scale. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon S3** | High-fidelity audio sample storage with brief-retention lifecycle; feature-vector storage with longer retention; audit archive with Object Lock |
| **Amazon SageMaker** | Per-indication validated model hosting (real-time and asynchronous endpoints), per-cohort calibration application, post-market surveillance via Model Monitor and Clarify |
| **Amazon Transcribe Medical** | Speech-to-text for linguistic-feature extraction in cognitive-decline biomarkers and other linguistic-feature pipelines |
| **Amazon Comprehend Medical** | Clinical-entity extraction from spontaneous-speech transcripts when used as biomarker features and for incidental clinical-content routing |
| **Amazon Bedrock** | Natural-language interpretation packaging for clinician communication; LLM-based linguistic-feature scoring (semantic coherence, topic adherence) where used in cognitive biomarkers |
| **Amazon Bedrock Guardrails** | Content filtering and contextual-grounding checks on patient-facing biomarker communications |
| **AWS Lambda** | Per-stage orchestration for capture-ingest, feature-extraction, eligibility-check, scoring, calibration, packaging, EHR write |
| **AWS Step Functions** | Pipeline orchestration with durable state, retry semantics, and observable failure handling |
| **AWS HealthLake** | FHIR-based biomarker Observation storage and longitudinal-trajectory queries |
| **Amazon DynamoDB** | Per-patient trajectory tables, per-sample state, per-cohort calibration lookup |
| **Amazon API Gateway** | Capture API for sample submission; result API for clinician and patient consumption |
| **Amazon Cognito** | Clinician and patient authentication federated through institutional IdP |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing and biometric-bearing data stores; separate keys per data class for blast-radius containment |
| **AWS Secrets Manager** | EHR API and external-vendor API credentials with rotation |
| **Amazon EventBridge** | Cross-system event flow for capture, scoring, and delivery events |
| **Amazon CloudWatch** | Operational metrics, per-cohort drift alarms, indeterminate-result-rate alarms |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing and biometric-bearing resources and AI/ML service invocations |
| **Amazon Kinesis Data Firehose** | Streaming audit and telemetry into the audit archive |
| **AWS Glue + Amazon Athena** | SQL access to audit and surveillance data for operational and clinical-quality analytics |
| **Amazon QuickSight (optional)** | Dashboards for clinical-quality and post-market surveillance teams |

---

### Code

#### Walkthrough

**Step 1: Capture the audio sample with the indication-specific protocol, real-time quality assessment, and explicit biometric-data consent.** When the patient or clinician initiates a capture, the system selects the indication-specific protocol, prompts the speaker through the tasks, runs real-time quality checks, and records the consent context including the biometric-data terms. Skip the per-protocol prompt design and the resulting audio cannot be reliably scored against the model's validation conditions. Skip the consent capture and the institution accumulates biometric data without proper authorization, which is a compliance and trust failure.

```
ON capture_initiated(patient_id, indication, capture_context):

    // Step 1A: select the protocol for the indication.
    // The protocol defines the tasks, expected duration,
    // recording-quality minimums, and per-task quality
    // gates.
    protocol = lookup_protocol(
        indication: indication,
        patient_language: lookup_patient_language(patient_id),
        capture_context: capture_context)
    // capture_context includes device class (smartphone,
    // dedicated mic, telehealth call), environment
    // (clinic, home), and prior-visit baseline status.

    IF protocol IS NULL:
        // No validated protocol exists for this
        // combination. The system declines to capture
        // rather than capture out-of-protocol audio.
        RETURN { status: "PROTOCOL_NOT_AVAILABLE" }

    // Step 1B: capture biometric-data consent.
    // Voice samples are biometric data; the consent
    // disclosure is more specific than generic PHI
    // consent. Per-jurisdiction biometric-data law
    // (Illinois BIPA, Texas, Washington) determines
    // the disclosure requirements.
    consent_outcome = capture_consent(
        patient_id: patient_id,
        consent_type: "voice_biomarker_collection",
        disclosure: build_disclosure(
            indication: indication,
            retention_terms: protocol.retention,
            jurisdiction: lookup_patient_jurisdiction(
                patient_id),
            third_party_disclosure: protocol.disclosures),
        require_explicit: protocol.requires_explicit_consent)

    IF NOT consent_outcome.granted:
        log_consent_decline(
            patient_id, indication, consent_outcome)
        RETURN { status: "CONSENT_DECLINED" }

    // Step 1C: bootstrap the capture session.
    session_id = generate_uuid()
    capture_session_table.put({
        session_id: session_id,
        patient_id_hash: hash(patient_id),
        indication: indication,
        protocol_version: protocol.version,
        consent_id: consent_outcome.consent_id,
        capture_context: capture_context,
        device_class: capture_context.device_class,
        started_at: now(),
        jurisdiction:
            lookup_patient_jurisdiction(patient_id)
    })

    // Step 1D: walk the speaker through the protocol
    // tasks and capture audio for each.
    captured_segments = []
    FOR task IN protocol.tasks:
        prompt_speaker(task.prompt_text)
        segment_audio = capture_audio_with_quality_assessment(
            task: task,
            quality_thresholds: task.quality_thresholds,
            max_retries: task.max_retries)

        IF segment_audio.quality_score < task.minimum_quality:
            log_capture_quality_failure(
                session_id, task, segment_audio)
            // Indication may still be assessable on
            // partial-task data; the protocol determines
            // whether to proceed or abort.
            IF task.required:
                RETURN { status: "INSUFFICIENT_QUALITY",
                         failed_task: task.task_id }

        captured_segments.append({
            task_id: task.task_id,
            audio_ref: segment_audio.s3_uri,
            duration_seconds: segment_audio.duration,
            quality_score: segment_audio.quality_score,
            sample_rate: segment_audio.sample_rate,
            codec: segment_audio.codec,
            snr_db: segment_audio.snr_db,
            clipping_detected: segment_audio.clipping
        })

    // Step 1E: persist the capture-session record and
    // emit the pipeline trigger.
    capture_session_table.update(
        session_id: session_id,
        captured_segments: captured_segments,
        capture_completed_at: now(),
        status: "captured")

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "sample_captured",
        detail: {
            session_id: session_id,
            indication: indication,
            segment_count: len(captured_segments)
        }
    }])

    RETURN { session_id: session_id, status: "CAPTURED" }
```

**Step 2: Extract acoustic and linguistic features from each task segment, with bandwidth and codec-aware processing.** Each task segment is processed through the appropriate feature pipeline: sustained-vowel segments produce vocal-fold-function features; read-passage and spontaneous-speech segments produce timing, prosody, and articulation features plus optional linguistic features from the transcript; cough-collection segments produce acoustic-event features. The feature extraction is bandwidth-aware; features that depend on frequencies the recording chain does not preserve are flagged as unmeasurable rather than computed against missing signal. Skip the bandwidth-awareness and the resulting features include garbage values from frequencies that the codec discarded.

```
FUNCTION extract_features(session_id):
    state = capture_session_table.get(session_id)
    feature_set = {
        session_id: session_id,
        indication: state.indication,
        per_segment_features: {},
        recording_chain_metadata: {
            device_class: state.device_class,
            min_codec_bandwidth_hz:
                determine_codec_bandwidth(state)
        }
    }

    // Step 2A: per-segment feature extraction.
    FOR segment IN state.captured_segments:
        task_def = lookup_task_definition(
            indication: state.indication,
            task_id: segment.task_id)

        // Bandwidth-aware feature selection. Some
        // features (high-frequency spectral tilt, for
        // instance) are not reliably measurable when the
        // codec aggressively compresses high frequencies.
        applicable_features = filter_features_by_bandwidth(
            requested_features: task_def.feature_list,
            available_bandwidth_hz:
                feature_set.recording_chain_metadata
                    .min_codec_bandwidth_hz)

        // Acoustic features.
        acoustic_features = compute_acoustic_features(
            audio_ref: segment.audio_ref,
            features: applicable_features.acoustic,
            // Per-feature confidence: features computed
            // on shorter or noisier segments get lower
            // per-feature confidence.
            return_confidence: true)

        // Pretrained-representation features (frozen
        // self-supervised speech embeddings) for the
        // downstream model's pretrained-rep inputs.
        embedding_features = compute_speech_embeddings(
            audio_ref: segment.audio_ref,
            model_id: task_def.embedding_model_id)

        // Linguistic features (if task is read-passage
        // or spontaneous-speech and indication uses
        // linguistic features, e.g., cognitive
        // biomarkers).
        linguistic_features = NULL
        IF task_def.uses_linguistic_features:
            transcript = transcribe_medical.start_job(
                audio_ref: segment.audio_ref,
                language: state.protocol.language,
                show_speaker_labels: false)
            wait_for_transcribe(transcript.job_name)
            transcript_text = retrieve_transcript(
                transcript.job_name)

            linguistic_features = extract_linguistic_features(
                transcript: transcript_text,
                requested_features:
                    applicable_features.linguistic)

            // For spontaneous-speech samples that may
            // contain incidental clinical content,
            // route through Comprehend Medical to
            // surface anything that needs clinical
            // attention regardless of the biomarker
            // result.
            IF task_def.is_spontaneous_speech:
                clinical_entities =
                    comprehend_medical.detect_entities(
                        text: transcript_text)
                IF has_actionable_clinical_content(
                       clinical_entities):
                    route_to_clinical_review(
                        session_id, clinical_entities)

        feature_set.per_segment_features[segment.task_id] = {
            acoustic: acoustic_features,
            embeddings: embedding_features,
            linguistic: linguistic_features,
            unmeasurable_features: applicable_features.excluded
        }

    // Step 2B: persist features.
    feature_set_archive.put(
        session_id: session_id,
        feature_set: feature_set)

    capture_session_table.update(
        session_id: session_id,
        feature_set_archive_ref:
            f"s3://{FEATURE_BUCKET}/{session_id}/features.json",
        features_extracted_at: now(),
        status: "features_extracted")

    RETURN { feature_set_ref: feature_set.archive_ref }
```

**Step 3: Check eligibility for each candidate biomarker model based on validation envelope.** Each per-indication model has a validation envelope: the demographic distributions, recording-chain conditions, and task-completion expectations the model was validated under. Before the model is invoked, the system checks whether the current sample fits the envelope. Out-of-envelope samples produce an "indication not assessable" result rather than a potentially-misleading score. Skip the eligibility check and the system silently produces scores on samples the model was not validated for, which is a clinical-safety failure mode.

```
FUNCTION check_eligibility(session_id, candidate_indications):
    state = capture_session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    eligibility_results = {}

    FOR indication IN candidate_indications:
        model_card = lookup_model_card(indication)

        // Step 3A: demographic eligibility.
        patient_demographics = lookup_patient_demographics(
            state.patient_id_hash)
        demographic_fit = check_demographic_envelope(
            patient_demographics,
            model_card.validation_demographics)

        // Step 3B: recording-chain eligibility.
        recording_fit = check_recording_envelope(
            recording_metadata:
                feature_set.recording_chain_metadata,
            validation_envelope:
                model_card.validation_recording_envelope)

        // Step 3C: task-completion eligibility.
        task_fit = check_task_completion(
            captured_segments: state.captured_segments,
            required_tasks: model_card.required_tasks,
            min_per_task_quality:
                model_card.min_per_task_quality)

        // Step 3D: confound-flag check.
        confound_flags = check_confounds(
            patient_id_hash: state.patient_id_hash,
            recent_clinical_events: lookup_recent_events(
                state.patient_id_hash,
                window_days: 30),
            model_confounds: model_card.confounds_to_flag)

        eligibility_results[indication] = {
            eligible:
                demographic_fit.eligible AND
                recording_fit.eligible AND
                task_fit.eligible,
            demographic_fit: demographic_fit,
            recording_fit: recording_fit,
            task_fit: task_fit,
            confound_flags: confound_flags,
            // Cohort assignment for per-cohort
            // calibration at the next step.
            assigned_cohort: assign_cohort(
                patient_demographics,
                feature_set.recording_chain_metadata,
                model_card.cohort_definitions)
        }

    capture_session_table.update(
        session_id: session_id,
        eligibility: eligibility_results,
        eligibility_assessed_at: now())

    RETURN eligibility_results
```

**Step 4: Score the eligible biomarkers, applying per-cohort calibration and producing indeterminate results when uncertainty is high.** For each indication that passed eligibility, the system invokes the validated model, applies the per-cohort calibration to the raw model output, and packages the result. When the model's confidence is below the institutional threshold, the result is marked indeterminate rather than passed through as a confident score. Skip the per-cohort calibration and the system produces uncalibrated outputs that perform inconsistently across cohorts. Skip the indeterminate handling and edge-case samples produce confident-looking scores that the clinical workflow takes at face value.

```
FUNCTION score_biomarkers(session_id):
    state = capture_session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    eligibility = state.eligibility
    scores = {}

    FOR indication, elig IN eligibility:
        IF NOT elig.eligible:
            scores[indication] = {
                status: "NOT_ASSESSABLE",
                ineligibility_reasons:
                    summarize_ineligibility(elig)
            }
            CONTINUE

        model_card = lookup_model_card(indication)
        endpoint_name = model_card.sagemaker_endpoint

        // Step 4A: assemble model inputs.
        model_input = assemble_model_input(
            feature_set: feature_set,
            model_card: model_card)

        // Step 4B: invoke the SageMaker endpoint.
        // Real-time endpoints for in-encounter use
        // cases; asynchronous endpoints for
        // longitudinal-monitoring use cases.
        IF model_card.inference_mode == "real_time":
            raw_response = sagemaker_runtime.invoke_endpoint(
                endpoint_name: endpoint_name,
                content_type: "application/json",
                body: serialize(model_input))
        ELSE:
            raw_response = sagemaker_runtime.invoke_endpoint_async(
                endpoint_name: endpoint_name,
                input_location: model_input.s3_uri)
            wait_for_async_response(raw_response.output_location)
            raw_response = retrieve_async_output(
                raw_response.output_location)

        raw_score = parse_score(raw_response)

        // Step 4C: apply per-cohort calibration.
        // The cohort was assigned at eligibility step.
        // Each cohort has its own calibration curve and
        // its own threshold map.
        calibration = lookup_cohort_calibration(
            indication: indication,
            cohort: elig.assigned_cohort)
        calibrated_score = apply_calibration(
            raw_score, calibration.curve)

        // Step 4D: indeterminate-result handling.
        // Calibrated confidence intervals beyond the
        // institutional threshold for actionable
        // results produce indeterminate output.
        confidence_interval = compute_confidence_interval(
            score: calibrated_score,
            cohort_size: calibration.cohort_size,
            calibration_uncertainty:
                calibration.calibration_uncertainty)

        IF confidence_interval.width >
           model_card.indeterminate_threshold:
            scores[indication] = {
                status: "INDETERMINATE",
                raw_score: raw_score,
                calibrated_score: calibrated_score,
                confidence_interval: confidence_interval,
                cohort: elig.assigned_cohort,
                confound_flags: elig.confound_flags,
                recommended_action: "recapture_or_clinician_review"
            }
            CONTINUE

        // Step 4E: threshold-based category assignment.
        category = assign_category(
            calibrated_score, calibration.thresholds)

        // Step 4F: feature-attribution explanation.
        // For models that support it, surface the
        // top contributing features for clinician
        // interpretation.
        feature_attribution = compute_attribution(
            model_card: model_card,
            model_input: model_input,
            raw_response: raw_response)

        scores[indication] = {
            status: "SCORED",
            raw_score: raw_score,
            calibrated_score: calibrated_score,
            confidence_interval: confidence_interval,
            category: category,
            cohort: elig.assigned_cohort,
            confound_flags: elig.confound_flags,
            top_features: feature_attribution.top_features,
            model_version: model_card.model_version,
            calibration_version: calibration.version,
            scored_at: now()
        }

    capture_session_table.update(
        session_id: session_id,
        scores: scores,
        scoring_completed_at: now(),
        status: "scored")

    RETURN scores
```

**Step 5: Compute longitudinal trajectory and package the clinical interpretation.** For patients with prior samples, the system computes the trajectory delta against the patient's baseline. The packaged interpretation includes the score, the trajectory, the supporting features, the cohort context, the confound flags, and the institutionally-approved clinical-action mapping. Skip the trajectory computation and the system loses the per-patient longitudinal context that makes voice biomarkers most reliable. Skip the institutional clinical-action mapping and individual clinicians have to infer how to act on the score, which produces inconsistent and sometimes inappropriate clinical actions.

```
FUNCTION package_interpretation(session_id):
    state = capture_session_table.get(session_id)
    scores = state.scores
    interpretations = {}

    FOR indication, score IN scores:
        IF score.status IN ["NOT_ASSESSABLE", "INDETERMINATE"]:
            interpretations[indication] = score
            CONTINUE

        // Step 5A: longitudinal trajectory.
        // Trajectory is more reliable than single-sample
        // scoring for many indications.
        prior_samples = trajectory_table.get_history(
            patient_id_hash: state.patient_id_hash,
            indication: indication,
            window_days: 730)

        trajectory = NULL
        IF len(prior_samples) >= MIN_SAMPLES_FOR_TRAJECTORY:
            baseline = compute_patient_baseline(
                prior_samples,
                exclude_recent_days: 30)
            trajectory = compute_trajectory_delta(
                current_score: score.calibrated_score,
                baseline: baseline,
                model_card: lookup_model_card(indication))

        // Step 5B: clinical-action mapping.
        // The institution-approved mapping translates
        // the score and trajectory into one of a small
        // set of clinical actions (clinician review,
        // patient communication, longitudinal store
        // only, no action).
        clinical_action = lookup_clinical_action_mapping(
            indication: indication,
            category: score.category,
            trajectory: trajectory,
            confound_flags: score.confound_flags,
            institutional_policy: INSTITUTIONAL_POLICY)

        // Step 5C: clinician-facing summary using
        // Bedrock for natural-language packaging.
        clinician_summary = bedrock.invoke_model(
            model_id: SUMMARY_MODEL,
            prompt: build_summary_prompt(
                indication: indication,
                score: score,
                trajectory: trajectory,
                clinical_action: clinical_action,
                template: CLINICIAN_SUMMARY_TEMPLATE),
            guardrail_id: BIOMARKER_GUARDRAIL_ID,
            response_format: {
                type: "json_schema",
                schema: SUMMARY_SCHEMA
            },
            max_tokens: 800)

        // Step 5D: store the trajectory record.
        trajectory_table.put({
            patient_id_hash: state.patient_id_hash,
            indication: indication,
            sample_timestamp: state.started_at,
            session_id: session_id,
            calibrated_score: score.calibrated_score,
            cohort: score.cohort,
            confound_flags: score.confound_flags,
            recording_chain:
                state.feature_set.recording_chain_metadata,
            trajectory_delta:
                (trajectory.delta if trajectory else NULL)
        })

        interpretations[indication] = {
            status: "INTERPRETED",
            score: score,
            trajectory: trajectory,
            clinical_action: clinical_action,
            clinician_summary: clinician_summary.content,
            packaged_at: now()
        }

    capture_session_table.update(
        session_id: session_id,
        interpretations: interpretations,
        packaging_completed_at: now(),
        status: "interpreted")

    RETURN interpretations
```

**Step 6: Deliver the result to the clinical workflow with explicit indeterminate handling and clinician override capture.** The clinician sees the biomarker result in their decision-support context, with the option to acknowledge, override, or request follow-up. The biomarker is decision support, not diagnosis; the clinician retains diagnostic authority. The result is also written to the EHR as a FHIR Observation for the longitudinal record. Skip the clinician override capture and the institution loses the feedback loop that supports post-market surveillance. Skip the EHR write and the result is invisible to the rest of the care team.

```
FUNCTION deliver_to_workflow(session_id):
    state = capture_session_table.get(session_id)
    interpretations = state.interpretations

    FOR indication, interpretation IN interpretations:
        // Step 6A: write the biomarker as a FHIR
        // Observation. The Observation includes the
        // score, the cohort context, the confound flags,
        // and the indeterminate-result status where
        // applicable.
        observation_resource = build_fhir_observation(
            patient_id: lookup_patient_id(
                state.patient_id_hash),
            indication: indication,
            interpretation: interpretation,
            performed_at: state.started_at)

        healthlake_client.create_resource(
            resource_type: "Observation",
            resource: observation_resource)

        // Step 6B: surface the result to the clinical
        // workflow per the institutionally-approved
        // clinical-action mapping.
        IF interpretation.clinical_action == "clinician_review":
            create_decision_support_alert(
                patient_id_hash: state.patient_id_hash,
                indication: indication,
                interpretation: interpretation,
                priority:
                    interpretation.score.category)
        ELIF interpretation.clinical_action == "patient_communication":
            // Patient-facing message goes through
            // additional Guardrails check for
            // appropriate framing.
            patient_message = generate_patient_message(
                interpretation,
                guardrail_id: PATIENT_MESSAGING_GUARDRAIL)
            schedule_patient_communication(
                patient_id_hash: state.patient_id_hash,
                message: patient_message,
                channel: lookup_patient_preference(
                    state.patient_id_hash))
        ELIF interpretation.clinical_action == "longitudinal_only":
            // Result stored, not surfaced to clinician
            // for individual review. Aggregate trajectory
            // available in clinician's longitudinal view.
            log_longitudinal_only(session_id, indication)
        ELSE:
            // No-action mapping. Result stored only.
            log_no_action(session_id, indication)

        // Step 6C: emit the delivery event for
        // surveillance and feedback loops.
        EventBridge.PutEvents([{
            source: "voice_biomarker",
            detail_type: "result_delivered",
            detail: {
                session_id: session_id,
                indication: indication,
                clinical_action:
                    interpretation.clinical_action,
                category:
                    (interpretation.score.category if
                     interpretation.status == "INTERPRETED"
                     else interpretation.status)
            }
        }])

ON clinician_acknowledges_result(session_id, clinician_id,
                                  indication, action_taken,
                                  feedback):
    // Step 6D: capture the clinician's response. This
    // is the feedback loop for post-market surveillance:
    // did the clinician agree with the biomarker, did
    // they take an action, did the action match the
    // institutional clinical-action mapping?
    clinician_feedback_table.put({
        session_id: session_id,
        indication: indication,
        clinician_id: clinician_id,
        action_taken: action_taken,
        agreement_with_biomarker:
            (action_taken == interpretation.clinical_action),
        feedback: feedback,
        responded_at: now()
    })

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "clinician_feedback_captured",
        detail: {
            session_id: session_id,
            indication: indication,
            agreement: (action_taken ==
                        interpretation.clinical_action)
        }
    }])
```

**Step 7: Audit, retain audio per consent, and feed cohort-stratified post-market surveillance.** Every sample produces a durable audit record with the score, the cohort context, the confound flags, and the clinical-action linkage. Audio is retained per the consent terms and then deleted; feature vectors are retained longer for surveillance and re-validation. Cohort-stratified metrics feed the post-market surveillance dashboards that monitor the deployed biomarker's performance against ground-truth clinical outcomes. Skip the audio retention enforcement and the institution silently accumulates biometric data beyond its consent commitment. Skip the cohort-stratified surveillance and per-cohort drift surfaces only through complaints.

```
FUNCTION audit_and_surveillance(session_id):
    state = capture_session_table.get(session_id)
    interpretations = state.interpretations

    audit_record = {
        session_id: session_id,
        patient_id_hash: state.patient_id_hash,
        captured_at: state.started_at,
        capture_completed_at: state.capture_completed_at,
        scoring_completed_at: state.scoring_completed_at,
        delivered_at: state.packaging_completed_at,
        indications_attempted:
            list(interpretations.keys()),
        per_indication_outcomes: {
            indication: {
                status: interp.status,
                category:
                    (interp.score.category
                     if interp.status == "INTERPRETED"
                     else NULL),
                cohort:
                    (interp.score.cohort
                     if interp.status == "INTERPRETED"
                     else NULL),
                clinical_action:
                    (interp.clinical_action
                     if interp.status == "INTERPRETED"
                     else NULL),
                confound_flags:
                    (interp.score.confound_flags
                     if interp.status == "INTERPRETED"
                     else NULL),
                model_version:
                    (interp.score.model_version
                     if interp.status == "INTERPRETED"
                     else NULL),
                calibration_version:
                    (interp.score.calibration_version
                     if interp.status == "INTERPRETED"
                     else NULL)
            }
            FOR indication, interp IN interpretations
        },
        recording_chain_metadata:
            state.feature_set.recording_chain_metadata,
        consent_id: state.consent_id,
        protocol_version: state.protocol_version
    }

    audit_archive_kinesis_firehose.put(audit_record)

    // Step 7A: schedule audio deletion per consent
    // terms. Feature-vector retention is configured
    // separately, typically longer than audio.
    schedule_audio_deletion(
        audio_refs:
            [seg.audio_ref for seg in state.captured_segments],
        delete_after: lookup_audio_retention(
            consent_id: state.consent_id,
            jurisdiction: state.jurisdiction))

    // Step 7B: per-cohort surveillance metrics.
    FOR indication, outcome IN audit_record.per_indication_outcomes:
        IF outcome.status == "INTERPRETED":
            cloudwatch.put_metric(
                namespace: "VoiceBiomarker",
                metric_name: "BiomarkerCategoryRate",
                value: 1,
                dimensions: {
                    indication: indication,
                    category: outcome.category,
                    cohort: outcome.cohort,
                    model_version: outcome.model_version
                })
        cloudwatch.put_metric(
            namespace: "VoiceBiomarker",
            metric_name: "PerOutcomeStatus",
            value: 1,
            dimensions: {
                indication: indication,
                outcome_status: outcome.status,
                cohort:
                    (outcome.cohort if outcome.cohort
                     else "not_eligible")
            })

    // Step 7C: SageMaker Model Monitor data-quality
    // and model-quality jobs run on a scheduled
    // cadence against the inference traffic. SageMaker
    // Clarify produces per-cohort attribution and bias
    // reports. Both feed the post-market surveillance
    // dashboard.

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "session_audited",
        detail: {
            session_id: session_id,
            audited_at: now()
        }
    }])
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample biomarker output (illustrative, synthetic patient):**

```json
{
  "session_id": "vbm-3a8c4f9b-7d2e-4f1a",
  "patient_id_hash": "p_8bf7e1c4...",
  "captured_at": "2026-05-23T14:08:11Z",
  "indications": {
    "parkinsons_screening": {
      "status": "INTERPRETED",
      "score": {
        "raw_score": 0.71,
        "calibrated_score": 0.64,
        "confidence_interval": [0.57, 0.71],
        "category": "elevated_signal",
        "cohort": "65-74_male_english_clinic_recording",
        "model_version": "parkinsons_v3.2.1",
        "calibration_version": "calibration_v3.2.1_20260301",
        "top_features": [
          {"feature": "harmonic_to_noise_ratio_sustained_a",
           "patient_value_z": -1.8,
           "cohort_baseline_mean": 21.4,
           "patient_value": 14.2},
          {"feature": "pitch_range_passage",
           "patient_value_z": -1.4,
           "cohort_baseline_mean": 78.2,
           "patient_value": 51.0},
          {"feature": "articulation_rate_passage",
           "patient_value_z": -1.1,
           "cohort_baseline_mean": 5.1,
           "patient_value": 4.3}
        ],
        "confound_flags": []
      },
      "trajectory": {
        "baseline_score": 0.41,
        "current_score": 0.64,
        "delta": 0.23,
        "delta_significance": "outside_typical_variation",
        "samples_in_baseline": 4,
        "baseline_window": "2024-09-01_to_2025-09-01"
      },
      "clinical_action": "clinician_review",
      "clinician_summary": "Voice features show acoustic patterns associated with Parkinsonian speech: reduced harmonic-to-noise ratio, narrowed pitch range, and slowed articulation rate. The patient's score has increased meaningfully relative to their own baseline over the past 12 months. This is a decision-support signal, not a diagnosis. Consider movement-disorder workup if other clinical signs warrant; the biomarker does not establish or exclude a Parkinson's diagnosis on its own."
    },
    "respiratory_monitoring": {
      "status": "NOT_ASSESSABLE",
      "ineligibility_reasons": [
        "no_cough_segment_in_protocol"
      ]
    }
  },
  "recording_chain": {
    "device_class": "clinic_dedicated_microphone",
    "sample_rate_hz": 44100,
    "codec": "PCM_16",
    "min_codec_bandwidth_hz": 16000,
    "snr_db": 28,
    "environment": "exam_room"
  }
}
```

**Performance benchmarks (illustrative; ranges depend heavily on indication, validation cohort, and recording chain; your mileage will vary):**

| Metric | Cough Classification (productive cough vs. dry vs. URI vs. asthma exacerbation) | Parkinson's Screening (single-point) | Parkinson's Trajectory Monitoring (longitudinal) | Depression Severity (decision-support score) | Cognitive-Decline Screening |
|--------|----------------------------|-------------------------------------|-------------------------------------------------|-------------------------------------|------------------------------|
| AUC on validation cohort | 0.85-0.92 | 0.75-0.88 | 0.85-0.93 | 0.65-0.78 | 0.70-0.85 |
| AUC on out-of-distribution cohort (different population) | 0.65-0.85 | 0.55-0.75 | 0.70-0.85 | 0.50-0.65 | 0.55-0.75 |
| Sensitivity at clinically-actionable threshold | 70-85% | 60-78% | 75-88% | 50-70% | 55-75% |
| Specificity at clinically-actionable threshold | 75-90% | 65-82% | 78-90% | 60-78% | 65-80% |
| Indeterminate-result rate (typical clinical population) | 5-10% | 12-25% | 8-18% | 18-30% | 15-28% |
| Per-sample latency (real-time endpoint) | 1-3 seconds | 2-5 seconds | 3-8 seconds | 2-5 seconds | 3-8 seconds |
| Per-sample latency (asynchronous endpoint) | 1-3 minutes | 2-5 minutes | 3-7 minutes | 2-5 minutes | 3-7 minutes |
| Per-sample AWS infrastructure cost | $0.05-0.15 | $0.10-0.25 | $0.15-0.35 | $0.10-0.30 | $0.15-0.40 |

<!-- TODO: replace with verified figures from the deployed indications. The ranges above are typical for published voice-biomarker results but vary substantially with cohort design, recording protocol, and the specific commercial or institutional model used. Cross-cohort generalization is consistently weaker than within-cohort performance, which is the most important caveat for institutional planning. -->

**Where it struggles:**

- **Cross-cohort generalization.** A model validated on one population (often a clinical-research cohort with specific demographic skew) frequently underperforms on a deployment population that does not match. This is the single largest gap between published voice-biomarker accuracy and real-world deployment accuracy. Mitigations: per-cohort validation before per-cohort deployment, eligibility checking that refuses out-of-envelope samples, per-cohort calibration with explicit cohort disclosure on every result, ongoing post-market surveillance with per-cohort accuracy tracking against ground-truth outcomes.

- **Recording-chain variability.** Smartphone capture, telephony capture, telehealth video-call capture, and dedicated-microphone capture produce meaningfully different feature vectors. A model trained on one recording chain often fails on another. Mitigations: per-recording-chain validation, bandwidth-aware feature extraction, per-codec calibration where supported, recording-chain disclosure on every result.

- **State vs. trait confounds.** A patient with a cold has a different voice than the same patient without a cold; the difference can be larger than the disease-specific signal the biomarker is trying to measure. Mitigations: confound flagging at the eligibility step, asking the patient about recent respiratory illness or other relevant factors as part of the protocol, longitudinal analysis that filters transient state effects from durable trait changes, indeterminate-result handling for samples with high-impact confound flags.

- **Demographic confounds masquerading as disease signal.** Without careful experimental design, models can learn to predict the demographics of the speaker rather than the disease state, and the apparent accuracy is the consequence of demographic-disease correlation in the training data. Mitigations: speaker-disjoint train/test splits, propensity-matched cohort design, explicit demographic-fairness analysis at the validation step, per-demographic-cohort performance reporting.

- **Insufficient data for rare conditions.** Many candidate voice biomarkers target conditions with too little training data to support robust models (rare neurological conditions, early-stage diseases before diagnosis). Mitigations: focus initial deployment on indications with adequate published evidence and adequate validation cohorts; treat data-poor indications as research-track only; collaborate with academic medical centers to grow validation cohorts over time.

- **The reproducibility tail.** Some commercially-promoted voice biomarkers are based on published results that have not replicated or that survive only with weaker performance than originally claimed. Mitigations: vendor due diligence including review of replication studies, preference for indications with multiple independent validation studies, explicit institutional-quality review of vendor evidence packages before clinical deployment.

- **Patient acceptance and consent.** Voice samples are biometric data; patient comfort with their voice being recorded and analyzed varies substantially by population, age, prior privacy experience, and the specific indication. Mitigations: clear consent disclosures, explicit retention terms, patient-friendly explanations of what voice biomarkers can and cannot tell, easy opt-out, attentive privacy-officer involvement in patient-facing communications.

- **Clinician trust and workflow integration.** A voice biomarker that surfaces in the EHR with little context is a likely-to-be-ignored alert. The combined information density (a number plus a category plus a confound flag plus a cohort context plus a trajectory) is more than a typical EHR alert is designed to convey. Mitigations: thoughtful decision-support interface design, per-indication clinician training, careful clinical-action mapping that makes the response to the result obvious, ongoing clinician-feedback collection and adjustment.

- **The mental-health-specific concerns.** Voice biomarkers for depression severity and suicidality risk are clinically promising but methodologically delicate. The state-vs-trait problem is acute (a patient's voice changes when they are having a bad day independent of their underlying clinical state). The clinical-action mapping is high-stakes (acting on a false-positive suicidality flag may be helpful or may damage trust). Mitigations: deploy as decision-support to clinicians rather than as automated screens, conservative thresholds with high indeterminate rates, integration with established mental-health workflows that the biomarker informs but does not replace.

- **Voice-modification and active deception.** Voice samples can be intentionally modified by the speaker (clearing throat, deliberately slowing or speeding speech, changing voice quality consciously). This is rare in cooperative patient populations but is a consideration in some workflow contexts (e.g., disability assessments, research participation). Mitigations: protocol design that makes intentional modification harder (multi-task protocols with surprise tasks), longitudinal trajectory analysis that flags abrupt within-patient changes, explicit acknowledgment that voice biomarkers can be confounded by intentional modification.

- **Regulatory drift.** A model that is FDA-cleared today may have its clearance affected by post-market findings, regulatory framework updates, or changes in the standard of care. Models that are not FDA-cleared but are deployed in clinical workflows may attract regulatory scrutiny over time. Mitigations: explicit regulatory-strategy review at the start, ongoing engagement with the regulatory affairs team, willingness to pause or modify deployments based on regulatory developments.

- **Audio-storage and biometric-data-disclosure exposure.** Voice samples are biometric and can be re-identified from the audio itself, independent of any patient metadata. Storage breaches are biometric-data breaches with potentially distinct legal implications. Mitigations: short audio retention, feature-vector-only retention beyond the QA window, encryption at rest with separate keys, access controls, breach-response plans that explicitly address biometric data.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment for any specific indication needs to close substantial gaps that are out of scope for a recipe.

**Per-indication validation evidence.** This is the dominant gap. The architecture supports per-indication models; the institution needs to either select commercial vendors with appropriate validation evidence (and the contracts to back the institution's own due-diligence) or build models with their own validation studies. Building a clinically-defensible voice biomarker for a single indication is a multi-year, multi-million-dollar undertaking requiring clinical-research staff, IRB-approved cohort development, and biostatistical expertise. Most institutions should be buying validated models, not building them.

**FDA SaMD strategy.** Any voice biomarker that produces clinical claims (diagnosis, treatment recommendation, disease-state measurement) is potentially subject to FDA's SaMD regulatory framework. The strategy decision (pursue clearance, deploy as wellness tool, deploy as research instrument, deploy as decision-support without specific claims) is upstream of the technical work. The strategy decision is also indication-specific: the same architectural component might support an FDA-cleared cough-classification model and a research-only cognitive-decline model, with different clinical-action mappings, different consent terms, and different post-market surveillance obligations per indication.

**Cohort development and ongoing cohort expansion.** Whether buying or building, the institution needs validation cohort data that matches its deployed population. Cohort expansion over time (collecting voice samples with linked clinical outcomes, with explicit IRB-approved consent for biomarker development) is the long-term workstream that determines how robust the deployed biomarkers become. Plan cohort expansion as a multi-year, named-clinical-research-team workstream.

**Per-cohort validation gates.** Per-cohort accuracy must meet the institutional threshold for that cohort before the biomarker is deployed to that cohort. Cohorts where per-cohort performance is inadequate either get the biomarker disabled, or get it deployed with explicit caveats and adjusted clinical-action mapping. Without this gate, the institution silently underserves the cohorts where the biomarker performs poorly.

**Clinical-action mapping by named clinical-quality leadership.** What clinicians and patients should do with each possible biomarker output is an institutional clinical-quality decision, not a technical decision. The mapping (high-risk score triggers what; indeterminate triggers what; trajectory delta triggers what; specific confound combinations trigger what) is owned by the clinical-quality officer or equivalent, in collaboration with the clinical-informatics team and the relevant specialty leadership. Without this ownership, the biomarker outputs are interpreted inconsistently across clinicians, and the clinical-quality outcomes are unpredictable.

**Consent infrastructure for biometric data.** The architecture captures consent at protocol initiation. Production deployment requires the privacy officer's review of the consent disclosure language, the per-jurisdiction biometric-data terms, the retention policies, and the right-to-deletion workflow. The infrastructure for honoring biometric-data deletion requests (deleting audio, feature vectors, scores, longitudinal trajectory entries upon patient request, with disclosure-accounting for any prior uses) is a substantial workstream.

**Recording-chain control or characterization.** The biomarker performance depends on the recording chain. Production deployment either standardizes the recording chain (all samples captured with the institution's specified microphone class, in specified environments, with specified protocols) or characterizes and validates against the realistic distribution of recording chains in the actual deployment context. The first is more reliable but limits where the biomarker can be deployed; the second is more flexible but requires more validation work.

**Post-market surveillance with regulatory reporting.** Voice biomarker performance changes over time in production for many reasons. The architecture collects the surveillance data; the institution needs the analytical capacity to act on it. Re-validation triggers, model retraining cadences, FDA reporting obligations (for cleared SaMD devices), and institutional-quality review meetings all need to be operational. Plan a quarterly per-indication clinical-quality review meeting at minimum.

**Layered safety review for high-stakes indications.** Mental-health voice biomarkers, in particular, deserve a more cautious deployment path: small-cohort pilots with intensive clinician feedback before broad deployment, conservative thresholds, explicit override paths for clinicians, integration with established crisis-response workflows where applicable. The same care applies to any indication where false-positive or false-negative results have direct clinical-safety implications.

**Patient-facing communication design.** When voice-biomarker results are communicated to patients (rather than only to clinicians), the messaging design is part of clinical safety. A patient receiving a biomarker score without context may misinterpret it as a diagnosis. The patient-facing interface design, the explicit framing of the biomarker as not-a-diagnosis, and the clear path to clinician follow-up are part of the deployment workstream. For SaMD-cleared devices, the patient-facing communications are part of the regulatory submission.

**Equity-focused validation that goes beyond demographic categories.** Demographic categories (age band, sex, race, ethnicity) are starting points for equity analysis, not endpoints. Voice biomarkers can fail along axes that the standard demographic categories do not capture: speakers with denture status, with smoking history, with hearing loss that affects their speech monitoring, with non-native-language English usage, with regional accents not represented in the training data. Equity validation needs to push beyond the demographic categories that are easy to measure to the speaker-property axes that actually drive performance variation.

**Integration with clinical research workflows.** Voice biomarker work in healthcare often spans the clinical-care boundary: research data can inform clinical care, and clinical-care data can inform research-track validation. The architecture for moving data between research and clinical contexts (with appropriate consent, IRB approval, and de-identification) is complex and needs explicit governance. Without it, the institution either silos the research and clinical work (limiting scientific progress and clinical improvement) or blurs the boundary improperly (creating compliance and trust risks).

**Disaster recovery and degraded-mode operation.** When upstream services fail (SageMaker endpoint outage, Bedrock outage, HealthLake outage), the system must degrade gracefully. The biomarker is decision support; its absence does not block clinical care. Document the per-mode behavior and test the failure modes in staging.

---

## The Honest Take

Voice biomarker detection is the recipe in this chapter where the marketing-vs-reality gap is widest, where the science is most uneven, and where the institutional risk of deploying poorly is most concentrated. It is also the recipe where, for the right narrow indications, the upside is genuinely attractive: cheap-to-collect, longitudinally-rich, often well-tolerated by patients, and capturing signal that is otherwise difficult to obtain. The difference between deploying voice biomarkers well and deploying them poorly is mostly not the AI; it is the indication selection, the validation rigor, the per-cohort discipline, the workflow placement, and the regulatory clarity.

The first trap is treating voice biomarkers as a single technology category. Cough analysis is a different technology problem than Parkinson's screening, which is a different problem than cognitive-decline screening, which is a different problem than depression severity scoring. The acoustic features differ, the validation cohorts differ, the regulatory pathways differ, the appropriate clinical-action mappings differ, the demographic-equity considerations differ. The architecture supports per-indication models for a reason; the institution's deployment plan should have per-indication discipline as well. Treating voice biomarkers as a generic capability that the team turns on for many indications at once is the surest path to mediocre results across the board.

The second trap is underweighting cross-cohort generalization. A model that achieves AUC 0.88 on the validation cohort and 0.65 on a different cohort is not, in any meaningful sense, an 0.88 biomarker. The 0.65 number is what the patients in the different cohort actually experience. Voice biomarkers consistently underperform the published numbers on out-of-distribution cohorts, often by margins that are clinically significant. The institution that deploys based on the validation-cohort numbers without testing cross-cohort generalization will ship a system whose actual performance disappoints. Per-cohort validation before per-cohort deployment is the discipline that makes the difference; it is more work and slows things down, and it is the right thing to do.

The third trap is underweighting recording-chain effects. The same patient saying the same words into different microphones, different codecs, and different network conditions produces feature vectors that can vary by more than the disease-related signal the biomarker is trying to measure. A model trained on clinic-grade dedicated-microphone audio does not work on smartphone audio. A model trained on smartphone audio does not work on telehealth video-call audio. A model trained on one telehealth platform's codec may not work on another's. The realistic deployment plan either constrains the recording chain or validates broadly across recording chains; the unrealistic deployment plan assumes the model will work on whatever audio shows up.

The fourth trap is underweighting demographic confounds in the validation. A model that learns to identify the speaker's age and sex (which are easy to predict from voice) and then uses those to predict the disease (because the disease is correlated with age and sex in the training data) appears to perform well in tests on similarly-distributed populations. The same model performs poorly on populations where the demographic-disease correlation differs. Confound-controlled experimental design at validation time is the methodological work that distinguishes a clinically-credible biomarker from a sophisticated demographic detector.

The fifth trap is underweighting indeterminate results. A clinically-defensible biomarker frequently returns indeterminate results: the audio quality was insufficient, the patient's confounds are too high, the model's confidence is below the actionable threshold. Treating every score as actionable, or hiding the indeterminate rate from the clinical workflow, produces a system that occasionally takes confident-looking action on samples where the model should have said "I don't know." The indeterminate-result handling is not a degradation of the biomarker; it is a feature of clinically-responsible deployment.

The sixth trap is underweighting the regulatory exposure. A voice biomarker that makes clinical claims is potentially subject to FDA's SaMD framework. Deploying without clarity about the regulatory posture is a non-trivial institutional risk. The framing as a wellness tool, a research instrument, or a decision-support signal each has different regulatory implications and different limitations on what the biomarker can do clinically. The regulatory clarity is upstream of the technical work; sort it out early.

The seventh trap is treating mental-health biomarkers like physical-health biomarkers. Voice biomarkers for depression severity, suicidality risk, and PTSD have growing but contested evidence, methodological challenges that are still being worked out, and clinical-action implications that are higher-stakes than physical-health analogs. Acting on a false-positive suicidality flag has consequences. Missing a true-positive cognitive-decline trajectory has consequences too. The mental-health voice biomarker space deserves more cautious deployment patterns, more conservative thresholds, more clinician-in-the-loop workflows, and more explicit integration with established mental-health crisis-response pathways.

The eighth trap is shipping voice biomarker capability without the longitudinal infrastructure. Single-sample voice biomarker scoring is the weakest version of what voice biomarkers can offer. Longitudinal trajectory analysis (this patient's voice is changing, and the change pattern matches what we expect for early Parkinson's) is often the more reliable clinical signal and is also more difficult to operationalize because it requires patients to produce samples over time and the system to maintain per-patient baselines correctly. Institutions that build the longitudinal infrastructure get to use the more reliable signal; institutions that ship single-sample scoring without the trajectory layer get the less reliable version.

The ninth trap is underweighting biometric-data governance. Voice samples are biometric. The privacy regime is HIPAA at minimum, but biometric-data laws (BIPA in Illinois and similar in Texas, Washington, and other jurisdictions) layer additional consent, retention, and disclosure-accounting obligations. The biometric-data deletion-on-request workflow is harder than the typical PHI deletion workflow because feature vectors derived from voice may persist after the source audio is deleted, and the question of whether the feature vectors are themselves biometric data is a privacy-officer judgment call. Plan the biometric-data governance as a distinct workstream from the standard PHI governance.

The tenth trap is shipping the biomarker without a clinical-action mapping. The score itself is rarely the clinical artifact that the workflow needs; the clinical action that the score informs is what matters. An institution that deploys a biomarker without an institutionally-approved clinical-action mapping ends up with each clinician improvising their own response to the score, which produces inconsistent and sometimes inappropriate clinical actions. The clinical-action mapping is a clinical-quality decision; it is owned by the clinical-quality officer in collaboration with specialty leadership; it is updated as the institution learns from post-market surveillance data.

The thing that surprises engineers coming from speech-to-text backgrounds is how different the audio infrastructure needs to be. Speech-to-text wants compact, intelligible-but-not-fidelity-critical audio for language modeling; voice biomarkers want full-fidelity audio with the subtle acoustic features preserved. Aggressive noise suppression, low-bitrate codecs, and bandwidth-limiting are good for speech-to-text accuracy and bad for voice-biomarker accuracy. If you are sharing audio infrastructure across both, the audio-handling discipline has to support the biomarker workflow's needs even when the speech-to-text workflow does not.

The thing that surprises engineers coming from imaging-AI backgrounds is the lack of standardized acquisition. A chest X-ray is a chest X-ray within reasonable manufacturer-and-model variation; a voice sample varies wildly across recording contexts in ways that are hard to fully normalize. The protocol design (what tasks the speaker performs, in what environment, with what device) is much closer to clinical-instrument design than to imaging-AI work. Spend time on the protocol; the protocol determines what the model gets to work with.

The thing about commercial vs. institutional models specifically: most institutions deploying voice biomarkers should be buying validated commercial models for the indications where commercial validation exists, not building from scratch. Building a validated voice biomarker is a specialized clinical-research undertaking that most healthcare institutions are not staffed for. The exceptions are academic medical centers with dedicated clinical-research and biostatistics staff, vendors building the commercial offerings, and large institutions with explicit voice-biomarker research programs. For everyone else, the rational path is vendor evaluation, contracting with appropriate due-diligence, and institutional-fit validation against the deployed population.

The thing about Amazon SageMaker specifically: it is the right substrate for hosting voice biomarker models because the models tend to be custom (per-indication, per-cohort, per-version), they need monitoring (Model Monitor, Clarify), and they benefit from the cost-management options (asynchronous inference for non-real-time use cases, multi-model endpoints for related indications). The integration with the rest of the AWS data and security stack (KMS, VPC, IAM, CloudTrail) is mature and well-documented.

The thing about post-market surveillance specifically: institutions that build it as a launch-day capability ship better biomarkers than the institutions that bolt it on later. The surveillance data is what tells the institution when the biomarker is drifting, when a particular cohort is being underserved, when re-validation is required, and when an FDA-reportable event has occurred. Without it, the institution flies blind. The architecture in this recipe collects the surveillance data; the institution still needs the team that reviews it on a regular cadence and acts on what it shows.

The thing about consent specifically: patients who feel respected through the consent process consent willingly to voice biomarker collection; patients who feel surprised by the recording or the analysis lose trust. The consent flow design (clear language, explicit retention terms, easy opt-out, accessible explanation of what voice biomarkers can and cannot tell) is part of the deployment quality, not just a compliance checkbox. Patients are increasingly aware that their voice is biometric data; the institution that treats voice samples with appropriate respect builds trust that supports more ambitious applications later.

The thing about the field's velocity: voice biomarker research is moving fast. The set of indications with strong validation evidence today is different from the set five years ago and will be different again in five years. The institution's deployment posture should support staged onboarding of new indications as their evidence matures: a stable architectural pattern, a validation gate that new indications must clear, a clinical-action-mapping process that scales to new indications, a post-market surveillance discipline that monitors all deployed indications. The institution that builds this once gets to deploy new indications relatively easily as the science develops; the institution that builds bespoke per-indication infrastructure repeats the work each time.

The thing I would do differently the second time: be even more conservative about indication selection. Most voice biomarker projects that have disappointed have done so not because the technology was bad, but because the institution selected an indication where the evidence was weaker than the team appreciated. Pick the two or three indications with the strongest evidence (cough analysis, Parkinson's monitoring in carefully-selected cohorts, perhaps respiratory-effort monitoring for COPD) and deploy those well, with the architectural infrastructure that supports adding new indications as their evidence matures. Resist the temptation to deploy mental-health biomarkers, cognitive-decline biomarkers, or other emerging-evidence indications as anything other than research-track until the evidence catches up.

The last thing, because it is the easiest one to get wrong: voice biomarkers are decision-support tools for clinicians and patients, not diagnostic instruments. A biomarker score, however well calibrated, does not establish or exclude a diagnosis. The clinician retains diagnostic authority; the biomarker provides context that informs the clinician's judgment. The institutions that ship voice biomarkers with this framing maintain clinical-quality standards and regulatory clarity; the institutions that frame voice biomarkers as diagnostic tools attract regulatory attention they did not expect and create clinical-safety risks they did not intend. The framing is upstream of everything.

Voice biomarker detection, done well for the right indications, is one of the more interesting frontiers in healthcare AI. It is also the area where the gap between marketing pitches and clinical reality is widest, where the demographic-equity stakes are clearest, and where the discipline of careful validation pays the most dividends. The architectural pattern in this recipe supports doing it well; doing it well requires the indication discipline, the validation rigor, the per-cohort gates, and the workflow placement that turn an interesting research idea into a clinically-defensible product.

---

## Variations and Extensions

**Cough-classification monitoring for COPD and asthma.** A focused deployment of cough-acoustic classification for chronic respiratory-disease management. Patients submit short cough samples through a mobile app or telehealth check-in; the system classifies cough type, tracks frequency and trajectory, and surfaces deterioration patterns to the care team. This is one of the most evidence-supported voice-biomarker indications and the easiest to deploy as a focused first capability.

**Parkinson's progression monitoring in established patients.** For patients with confirmed Parkinson's disease, voice biomarker tracking provides a non-invasive, frequent-sample method of monitoring disease progression and treatment response. The longitudinal trajectory is more clinically actionable than the single-sample score, and the deployment context (patients with established diagnosis, motivated to monitor their own condition) is more appropriate than population-level screening.

**Post-stroke aphasia recovery monitoring.** Voice and speech features track recovery from stroke-induced aphasia, supporting the speech-pathology team's assessment of progress between in-person therapy sessions. The patient's own pre-stroke voice (where available) provides a strong baseline; deltas from baseline are the primary clinical signal. Recipe 10.9 (speech therapy assessment and monitoring) covers the broader speech-pathology integration.

**ICU sedation depth and delirium monitoring.** ICU patients' voice and speech features can correlate with sedation depth and emerging delirium. The architecture is similar; the clinical-action mapping is more intensive (delirium triggers ICU-specific protocols). Validation in ICU populations is its own multi-year clinical-research undertaking.

**Anesthesia-recovery monitoring after surgery.** Voice features post-anesthesia track the patient's recovery trajectory. The clinical use case is post-operative discharge readiness assessment and identification of patients with prolonged anesthesia effects. Deployment is in PACU and recovery units with their specific workflow context.

**Suicide risk decision-support in mental-health settings.** Voice-based suicidality risk scoring as a decision-support signal to mental-health clinicians. This is one of the higher-stakes deployments and warrants the most cautious clinical-action mapping. Integration with established crisis-response workflows is essential. Most institutions deploying this are research-track or carefully-piloted clinical-research deployments rather than broad clinical deployments.

**At-home longitudinal monitoring for early-dementia detection.** Patients with mild cognitive impairment or family history of dementia perform short voice-and-speech tasks at home on a weekly cadence; the system tracks longitudinal trajectory and flags meaningful changes for clinician review. The infrastructure for at-home capture (apps, kiosks, devices) is its own engineering effort. Patient acceptance and adoption are the workflow challenges.

**Pediatric speech and developmental screening.** Voice biomarkers for pediatric populations (autism spectrum disorder screening, developmental language disorder identification) are an active research area. Pediatric cohorts require their own validation, and pediatric-specific consent and assent considerations layer on top of the standard biometric-data governance. Most current deployments are research-track.

**Language-specific deployment expansion.** Most published voice-biomarker research is in English-speaking cohorts. Deployment in other languages requires per-language validation, per-language calibration, and often per-language model retraining. The architecture supports per-language deployment; the validation work per language is its own undertaking.

**Multi-modal integration with EHR data, wearable data, and structured questionnaires.** Voice biomarkers combined with EHR data (medications, prior diagnoses, vitals trends), wearable data (movement, sleep patterns, heart rate variability), and structured questionnaire responses (PHQ-9, MoCA, ADAS-Cog) often produce stronger combined signals than voice alone. The architectural extension is the multi-modal feature combination layer and the per-modality eligibility checking.

**Voice-driven self-monitoring for chronic-disease patients.** Patients with chronic conditions (CHF, COPD, atrial fibrillation) record short voice samples on a defined cadence (daily, weekly); the system tracks trajectory and surfaces deterioration patterns to the care team for proactive outreach. The patient-empowerment framing changes the consent and workflow design from clinician-initiated to patient-initiated.

**Integration with ambient documentation pipelines (recipe 10.7).** The audio captured for ambient clinical documentation can also support voice-biomarker analysis, with appropriate consent and quality verification. The architectural extension is the shared audio infrastructure between the documentation and biomarker pipelines, with explicit governance for the dual use. Audio fidelity requirements are higher for biomarkers than for documentation, so the documentation pipeline's audio must be preserved at biomarker-grade fidelity, which is not the typical default.

**Real-time clinical-decision-support during telehealth visits.** During a telehealth encounter, voice features computed from the in-call audio surface decision-support signals to the clinician (the patient's voice acoustics suggest unusual respiratory effort, atypical articulation, or other clinically-relevant patterns). The architectural extension is the streaming-feature-extraction-and-scoring path. Clinical-action mapping during the encounter is more time-pressured than the asynchronous pattern, which raises the stakes for indeterminate handling and false-positive rates.

**Group-comparison cohort studies.** The same architecture supports retrospective cohort studies: applying validated biomarkers to a defined patient population to study disease epidemiology, treatment response, or other research questions. The research-track use of the same infrastructure as the clinical-track use requires governance for the data movement and the analytical separation, but the underlying infrastructure is the same.

**De-identified-cohort sharing for federated validation.** Multiple institutions can share de-identified cohort data (or, with privacy-preserving techniques, federated training) to build larger validation cohorts than any single institution could assemble. The architectural extension involves the privacy-preserving computation layer and the inter-institutional governance. Recipe 5.8 (privacy-preserving record linkage) covers analogous patterns.

**Linguistic-feature pipelines for cognitive assessment.** A cognitive-decline-focused deployment combines voice biomarkers with linguistic features extracted from the transcript: lexical diversity, idea density, semantic coherence, word-finding patterns. Recipe 8 (NLP) and recipe 2 (LLM) cover the linguistic-analysis primitives. The integration produces a richer cognitive-assessment signal than acoustic features alone.

**Patient-facing voice-biomarker self-tracking apps.** Some institutions offer patient-facing apps where the patient can capture voice samples themselves and see their own trajectory. This is a wellness-tool framing rather than a clinical-tool framing, with corresponding consent, regulatory, and clinical-action implications. The architectural extension is the patient-facing UI and the patient-friendly result presentation. The clinician is informed but not in the active loop for low-risk results.

---

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, simplest analog. The telephony plumbing patterns from 10.1 are the basis for telephony-captured voice-biomarker workflows.
- **Recipe 10.2 (Voicemail Transcription and Classification):** Same chapter, asynchronous single-speaker analog. The async-audio-processing pattern from 10.2 is the closest pattern to the asynchronous voice-biomarker scoring path.
- **Recipe 10.3 (Voice-to-Text for EHR Navigation):** Same chapter, in-clinic single-speaker voice-input analog. Different goal but same audio-capture infrastructure foundation.
- **Recipe 10.4 (Medical Transcription / Dictation):** Same chapter, single-speaker high-quality-capture analog. The custom-vocabulary patterns from 10.4 inform the linguistic-feature pipelines in cognitive-decline biomarkers.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Same chapter, patient-facing voice-interaction analog. The patient-acceptance and consent patterns from 10.5 inform patient-facing voice-biomarker self-tracking deployments.
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Same chapter, telehealth-audio analog. The per-cohort accuracy discipline from 10.6 transfers directly to the per-cohort voice-biomarker validation discipline.
- **Recipe 10.7 (Ambient Clinical Documentation):** Same chapter, in-room conversational-audio analog. The shared in-room audio infrastructure can serve both documentation and biomarker workflows when the audio fidelity is preserved appropriately.
- **Recipe 10.9 (Speech Therapy Assessment and Monitoring):** Same chapter, speech-quality clinical-assessment analog. The therapist-workflow integration patterns from 10.9 are closely related to the clinician-decision-support patterns in this recipe; both involve longitudinal assessment of speech-and-voice features.
- **Recipe 10.10 (Multilingual Real-Time Medical Interpretation):** Same chapter, multilingual analog. The per-language pipeline patterns are shared.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2, LLM-driven patient-facing summary generation. The patient-facing communication patterns from 2.5 apply to the patient-facing biomarker result-presentation extensions.
- **Recipe 2.10 (Multi-Modal Clinical Reasoning):** Chapter 2, multi-modal reasoning. Voice biomarkers are one input among several into multi-modal clinical reasoning architectures.
- **Recipe 3.7 (Patient Deterioration Early Warning):** Chapter 3, anomaly detection. Voice biomarker trajectory deltas can serve as one of several signals into a broader patient-deterioration-detection pipeline.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4, personalization. Voice biomarkers for medication-response monitoring (for example, dopaminergic-medication response in Parkinson's) inform medication-management interventions.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Chapter 5, privacy-preserving computation. Federated voice-biomarker validation across institutions uses analogous privacy-preserving patterns.
- **Recipe 7.x (Predictive Analytics chapter):** Chapter 7, risk scoring. Voice biomarkers are one of many signals into broader risk scores; the integration is multi-modal.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Asynchronous Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon SageMaker Clarify](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-fairness-and-explainability.html)
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker examples including model-hosting, Model Monitor, and Clarify patterns
- [`aws-samples/amazon-sagemaker-asr-and-audio-samples`](https://github.com/aws-samples/amazon-sagemaker-asr-and-audio-samples): audio-processing samples on SageMaker <!-- TODO: verify exact repo name and current location at build time -->
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including grounded generation and Guardrails
- [`aws-samples/amazon-comprehend-medical-samples`](https://github.com/aws-samples/amazon-comprehend-medical-samples): clinical-entity extraction patterns
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): healthcare AI/ML sample notebooks
<!-- TODO: confirm the current names and locations of these repos at time of build -->

**AWS Solutions and Blogs:**
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "voice," "audio," "biomarker," "SageMaker" for implementation deep dives
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AI/ML case studies
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for clinical-decision-support and post-market-surveillance reference architectures
<!-- TODO: replace with two or three specific verified blog post URLs once confirmed to exist -->

**External References (Standards, Frameworks, and Regulatory):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model for biomarker-result EHR integration
- [FHIR Observation Resource](https://www.hl7.org/fhir/observation.html): canonical FHIR resource for biomarker-result write-back
- [LOINC](https://loinc.org/): standard codes for laboratory and clinical observations, including some voice-and-speech-derived measures
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in voice biomarker workflows
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [Illinois Biometric Information Privacy Act (BIPA)](https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004): biometric-data law applicable to voice samples in Illinois
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): regulatory framework for software medical devices, including voice-based biomarkers
- [FDA Clinical Decision Support Software Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): guidance on the regulatory boundary between clinical decision support and regulated medical devices
- [FDA Pre-Cert Program (Digital Health)](https://www.fda.gov/medical-devices/digital-health-center-excellence): FDA's framework for digital-health software regulation

**Research and Datasets:**
- [mPower Parkinson's Voice Dataset](https://www.synapse.org/#!Synapse:syn4993293): public Parkinson's voice dataset for research <!-- TODO: verify dataset URL and current access terms -->
- [Coswara Cough Dataset](https://github.com/iiscleap/Coswara-Data): public cough dataset for respiratory-disease research <!-- TODO: verify dataset URL and license -->
- [DementiaBank](https://dementia.talkbank.org/): research corpus of speech samples from individuals with dementia, with appropriate access controls <!-- TODO: verify access terms -->
- [INTERSPEECH and ICASSP Conferences](https://www.interspeech2024.org/): primary speech-and-audio research venues; voice-biomarker work appears regularly
- [Journal of Voice](https://www.jvoice.org/): peer-reviewed clinical journal covering voice-and-speech research
- [npj Digital Medicine](https://www.nature.com/npjdigitalmed/): peer-reviewed journal covering digital health and biomarkers including voice

**Industry and Clinical Resources:**
- [American Speech-Language-Hearing Association](https://www.asha.org/): professional organization for speech-language pathologists, with relevant clinical-practice guidance
- [American Academy of Neurology](https://www.aan.org/): professional organization for neurologists, with guidance on Parkinson's, dementia, and related conditions where voice biomarkers may apply
- [American Psychiatric Association](https://www.psychiatry.org/): professional organization with guidance on mental-health clinical practice, relevant for mental-health voice-biomarker deployments
- [HHS Office for Civil Rights HIPAA Guidance](https://www.hhs.gov/hipaa/index.html): HIPAA Privacy and Security Rule guidance applicable to biometric voice samples
- [International Association of Privacy Professionals (IAPP)](https://iapp.org/): industry resource on biometric-data law and emerging-technology privacy

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single indication (typically cough classification or Parkinson's monitoring), commercial-vendor model integration through SageMaker endpoint or vendor API, single capture-device class (e.g., dedicated clinic microphone or specific telehealth platform), per-cohort calibration for two or three cohorts, basic clinician-facing decision-support display, FHIR Observation write-back to the EHR, brief-retention audio policy, English-only, pilot with one or two clinical sites | 3-5 months |
| Production-ready | Multiple validated indications (cough, Parkinson's, perhaps one mental-health-specific indication as decision support), multiple capture-device classes with per-class validation, full per-cohort calibration with eligibility gates, indeterminate-result handling, longitudinal trajectory tracking with per-patient baselines, layered post-market surveillance with SageMaker Model Monitor and Clarify plus regular clinical-quality review, biometric-data consent infrastructure with right-to-deletion workflow, full HIPAA-and-biometric-data-law compliance review, structured rollout with named operational owners, multi-language support (English plus at least one additional language), clinician training and feedback program, per-jurisdiction regulatory analysis | 12-18 months |
| With variations | Cough monitoring deployment in chronic respiratory-disease management workflows, Parkinson's progression monitoring in established-patient cohorts, post-stroke aphasia recovery monitoring, ICU sedation and delirium monitoring, anesthesia recovery monitoring, suicide-risk decision-support pilots, at-home longitudinal cognitive-decline monitoring, pediatric speech-and-language screening, multi-modal integration with EHR plus wearable plus questionnaire data, integration with ambient documentation pipelines, real-time decision support during telehealth, federated cohort validation across institutions | 8-15 months beyond production-ready |

---

## Tags

`speech-voice-ai` · `voice-biomarker` · `acoustic-biomarker` · `clinical-decision-support` · `parkinsons-voice-biomarker` · `cough-analysis` · `respiratory-monitoring` · `cognitive-decline-screening` · `mental-health-voice-biomarker` · `depression-severity-scoring` · `suicidality-risk-decision-support` · `speech-feature-extraction` · `acoustic-features` · `linguistic-features` · `pretrained-speech-models` · `wav2vec` · `hubert` · `recording-chain-normalization` · `bandwidth-aware-features` · `per-cohort-calibration` · `cohort-stratified-validation` · `indeterminate-result-handling` · `longitudinal-trajectory` · `samd` · `fda-clearance` · `post-market-surveillance` · `clinical-validation` · `reproducibility` · `biometric-data` · `bipa` · `voice-as-pii` · `consent-management` · `workflow-placement` · `decision-support-not-diagnosis` · `clinician-feedback-loop` · `sagemaker-endpoints` · `sagemaker-async-inference` · `sagemaker-model-monitor` · `sagemaker-clarify` · `transcribe-medical` · `comprehend-medical` · `bedrock` · `bedrock-guardrails` · `healthlake` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `complex` · `research-and-pilot-track` · `production-track-narrow-indications` · `hipaa` · `phi-handling` · `audit-trail`

---

*← [Recipe 10.7: Ambient Clinical Documentation](chapter10.07-ambient-clinical-documentation) · [Chapter 10 Index](chapter10-index) · [Recipe 10.9: Speech Therapy Assessment and Monitoring](chapter10.09-speech-therapy-assessment-monitoring) →*
