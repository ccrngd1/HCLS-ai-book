# Recipe 10.4: Medical Transcription (Dictation) ⭐⭐

**Complexity:** Medium · **Phase:** Production-track · **Estimated Cost:** ~$0.02-0.10 per dictated note (depends on note length, choice of general-purpose vs medical-domain ASR, optional LLM post-processing for formatting, and whether human QA review is in the loop)

---

## The Problem

It is 6:47 PM. The clinic schedule said the day ended at 5:00. The last patient left forty-five minutes ago. The lights in the empty waiting room are off. There is a physician in a back office who has not had dinner, has not called home to say she is running late again, and is sitting in front of a computer typing the day's notes. Her schedule had twenty-two patients today. She finished about thirty percent of her documentation between visits. The other seventy percent is now, in this office, after hours, on her own time.

The note she is currently typing is for a patient she saw at 2:15 PM. She is trying to remember the patient's exact words about a new symptom. She is trying to remember whether the patient said the pain started "two weeks ago" or "about two weeks ago, give or take." She is trying to remember which side. She is trying to reconstruct the physical exam she did four hours ago for a patient she has not seen since. The note will be technically correct. It will be far less rich than the actual encounter was. The patient said something interesting at the end of the visit that would have changed the differential, and she cannot remember it now, so it is not in the note, so the next clinician who reads this chart in three months will not know it happened.

This is not a story about one bad day. This is the median experience of clinical documentation in the United States in the late 2020s. A widely-cited 2017 study found that for every hour of direct patient care, ambulatory physicians spent close to two hours on documentation and EHR work, much of it after hours.  The colloquial term clinicians use for this is "pajama time," the documentation-after-bedtime that is so universal it has its own name. Pajama time correlates with clinician burnout, clinician attrition, reduced empathy in clinical encounters, missed clinical signals, and (in the cumulative aggregate) the slow-motion collapse of primary care as a viable career path for newly-trained physicians. 

The interesting thing is that the documentation problem is not new. Physicians have been struggling with the volume of clinical writing required for as long as there have been clinical records. What is new is the operational acceptance of "pajama time" as a normal feature of medical practice, the legal and billing requirements that have made the notes longer than they used to be, and the EHR interfaces that turn the act of writing a note into a click-and-type ordeal that takes substantially longer than dictation onto a tape would have taken in 1985.

Dictation is the original solution. The doctor talks; the words are transcribed; the transcription becomes the note. For decades the workflow was: doctor speaks into a handheld dictation recorder; the audio is sent to a transcription service (often offshore); a human transcriptionist types it up; the transcribed text comes back hours or days later; the doctor edits and signs. The market for medical transcription services was, at its peak in the late 2000s, substantial: thousands of transcription companies, tens of thousands of medical transcriptionists, billions of dollars in annual revenue. The workflow was slow, but it worked, and it kept the doctor's hands and eyes off the keyboard.

The 2010s and 2020s gradually replaced human transcriptionists with automated speech recognition. Nuance Dragon Medical and a handful of competitors built ASR models tuned specifically for clinical vocabulary, integrated them with the EHR, and offered front-end dictation: the doctor speaks; the words appear on screen in near-real time; the doctor edits and signs in a single workflow. This is what most clinicians today think of when they hear "medical transcription" or "medical dictation." Roughly a million U.S. physicians use some form of speech-driven documentation. 

The dream is still the same as it was in 1985. The doctor talks. The note appears. Time spent typing approaches zero. The clinician spends more time looking at patients and less time looking at screens. What has changed is who is doing the transcription (a model, not a human), how fast the turnaround is (real-time, not overnight), and how the workflow integrates with the rest of the EHR (deeply, in modern systems, rather than as a separate dictation step).

This is recipe 10.4. It sits at the medium-complexity tier of this chapter not because medical transcription is technically novel (it is, frankly, the most established voice product category in healthcare), but because building a transcription system that is genuinely good (high accuracy on specialty vocabulary, robust to accents and speaking styles, well-integrated with documentation workflows, with the right post-processing for formatting and the right human-review safeguards) requires more careful engineering than people typically expect. The accuracy benchmarks are well-established. The vendor landscape is mature. The build-versus-buy economics for most institutions favor buying. But there is real value in understanding what is actually happening inside these products: how the ASR is tuned for clinical vocabulary, how the formatting layer turns "next paragraph history of present illness comma the patient is a fifty four year old male" into "**History of Present Illness:**\n\nThe patient is a 54-year-old male...", how the voice commands are distinguished from dictation content, and where the failure modes live.

A few specific failure modes this recipe takes seriously.

The radiologist who dictates ten reports an hour, all day, and discovers two weeks later that the dictation system has been silently mistranscribing the laterality marker (right vs left) in roughly 0.5% of reports. Two weeks of reports times ten per hour times eight hours per day times five days per week times two is four thousand reports, of which twenty have the wrong laterality marker. Twenty radiology reports with the wrong laterality is twenty potentially clinically catastrophic errors. The mistranscription of "left" as "right" is a single phoneme. The clinical consequence is enormous. 

The primary care physician whose accent is underrepresented in the ASR vendor's training data, who consistently gets a 12% word error rate on her dictations while her partner across the hall gets 3%, and who concludes after a frustrating month that "this technology does not work for me" and reverts to typing. The institution sees overall ASR adoption metrics that look fine, because they are dominated by the partner's 3% error rate, and never investigates the per-clinician disparity. The physician's daily documentation burden is substantially higher than her colleague's for reasons that have nothing to do with her competence and everything to do with how the model was trained.

The emergency medicine physician who dictates a chest pain note, says "the patient denies hemoptysis," and finds that the system has transcribed it as "the patient denies hematemesis." Both are real medical terms. Both are clinically significant. They are completely different findings. The doctor reads through her note quickly before signing, does not catch the substitution, and the chart now contains a clinical claim the patient never made. The next clinician reading this chart will assume the workup excluded vomiting blood when in fact the workup excluded coughing blood. Whether this matters clinically depends on what happens next; the failure mode itself is silent and routine.

The surgeon who uses voice commands to navigate the dictation system ("next field," "delete that sentence," "insert template appendectomy") and discovers that the system has confused a dictated phrase with a command, executing a navigation action when the surgeon meant to dictate text. Most modern systems handle this reasonably well; legacy systems, and the boundary cases at the edge of every system's command vocabulary, still surprise people.

The clinic that buys a major-vendor dictation product, deploys it, and finds two months later that the actual user adoption is forty percent of what the vendor's pilot suggested. The reason is mundane. The pilot was with three early-adopter physicians who had time to attend training, time to build their auto-text macros, and patience with the initial accuracy curve. The broader rollout dropped these physicians on the system with thirty minutes of training, no time to build personal vocabulary additions, and a mid-first-week meeting on their calendar. The technology was the same. The deployment context was different. The metric that matters is sustained adoption at three months and six months, not pilot adoption in week one.

The institution that uses a commercial dictation product without realizing the audio is being sent off-premise to the vendor's cloud for processing. This is fine in 2026 with a properly executed BAA and the vendor's appropriate security posture, but the institutional security review never asked the right question, the BAA was signed without scrutiny, and the privacy officer is now in a difficult conversation with the CISO about why ten thousand hours of physician dictation about patients is currently sitting on a vendor's cloud storage with retention policies that nobody has reviewed.

The recipe is honest about where medical transcription works well in 2026 and where the rough edges still live. The ASR accuracy on dictated clinical text by an unhurried clinician in a quiet environment is genuinely excellent. The accuracy on a tired ED physician dictating quickly in a busy department is meaningfully worse but still usable. The accuracy on conversational speech (recipe 10.7, ambient documentation) is a different problem with different metrics. The integration of dictation with the EHR's structured fields (problem list, medication list, order entry) is partial in most products and the gap is institutional engineering work. The build-versus-buy economics for most healthcare organizations favor buying a commercial product (Dragon Medical, M-Modal/3M, vendor-bundled offerings from Epic and Cerner) rather than building a custom transcription system; the recipe explains what those products are doing under the hood, why they are hard to displace, and where a custom build still makes sense (specialty-specific use cases, niche languages, on-premise-only deployments).

Let's get into it.

---

## The Technology: Long-Form Dictation with Domain-Specific Stakes

### The Shape of the Problem

Medical transcription, the dictation variant specifically (recipe 10.7 covers the ambient-documentation variant separately), is a long-form, single-speaker, domain-specific automatic speech recognition problem with several distinguishing characteristics that shape every architectural decision.

**The utterances are long.** A dictated radiology report is typically thirty seconds to two minutes of continuous speech. A dictated discharge summary is often three to ten minutes. A dictated operative note can run twenty minutes. Compared to the short commands in recipe 10.3 or even the longer voicemails in recipe 10.2, these are huge utterances. The ASR has to maintain accuracy and context across multiple sentences, sometimes across multiple paragraphs, with the language model component handling discourse-level coherence rather than just per-utterance patterns.

**The vocabulary is highly specialized and specialty-specific.** A radiologist dictates "the left upper lobe demonstrates a spiculated 1.4 centimeter mass with associated pleural tethering, concerning for primary lung neoplasm." A cardiologist dictates "echocardiogram demonstrates moderate concentric left ventricular hypertrophy with grade two diastolic dysfunction and an ejection fraction of fifty five percent." A psychiatrist dictates "the patient endorses dysphoria, anhedonia, terminal insomnia, and passive suicidal ideation without intent or plan." These are not general English. They are dense with terms that almost never appear in general training data: drug names (lisinopril, dabigatran, tisagenlecleucel), anatomical structures (acetabular labrum, lateral pterygoid, basilar artery), procedures (laparoscopic cholecystectomy, transcatheter aortic valve replacement, percutaneous coronary intervention), eponymous syndromes (Wolff-Parkinson-White, Henoch-Schönlein purpura, Mallory-Weiss tear), and a long tail of latinate terminology that follows specific morphological rules unfamiliar to general ASR.

**Specialty-specific subdialects.** Within medical vocabulary, specialties have their own subdialects. A radiology dictation has different vocabulary distributions and different formatting expectations than a psychiatry dictation. Pathology reports are highly templated. Operative notes follow specific structural conventions that vary by surgical specialty. The "medical" in "medical transcription" is not one thing; it is dozens of overlapping technical languages.

**Accuracy expectations are very high.** Productivity-driven dictation tolerates a small amount of error because the clinician reads through and corrects before signing. But the threshold for "usable" is much higher than in conversational ASR: word error rates above roughly five percent on dictated clinical text feel painful to clinicians (too many corrections per note), and word error rates above ten percent typically push clinicians off the system entirely. The vendor benchmarks for clinical-domain ASR on prepared dictation typically report word error rates in the low single digits in best-case conditions; real-world deployment numbers are usually somewhat higher. 

**Safety-critical word substitutions matter more than overall WER.** A 3% word error rate distributed across function words (the, a, of, with) is fine. A 1% word error rate that systematically substitutes "no" for "not" or "left" for "right" or "hemoptysis" for "hematemesis" is dangerous. The metric that matters is not just WER but the rate and severity of clinically-meaningful errors. Vendors and academic benchmarks have started reporting "critical error rate" or "clinically significant error rate" alongside WER, and the gap between the two is a useful proxy for product quality. 

**Real-time, near-real-time, or batch.** Different dictation workflows have different latency requirements. Front-end dictation, where the words appear on screen as the doctor speaks, requires sub-second streaming ASR. Back-end dictation, where the doctor speaks and the transcript is delivered later for review, can use batch ASR with potentially better accuracy. Most modern products offer both modes; the architectural trade-off is real.

**Voice commands embedded in dictation.** The clinician dictates content, but also issues commands: "new paragraph," "next field," "insert template normal physical exam," "delete that sentence," "select last sentence," "go to assessment and plan." The system has to distinguish dictated content from voice commands, which is an interesting boundary problem because some commands sound exactly like content the clinician might dictate. ("Period" can be the word "period" in a sentence about menstruation, or it can be the command to insert a punctuation mark.) Most products handle this with a combination of acoustic cues (commands often have distinct prosody), context (commands are more likely after pauses or at the end of utterances), and explicit command markers ("computer, new paragraph" or a button-press while saying the command).

**Per-clinician adaptation is essential.** Dictation users use the system every day, often for hours. The system has the opportunity (and the data) to adapt to each clinician's voice, vocabulary preferences, common phrasing, and personal templates. Modern dictation products do per-clinician acoustic adaptation, per-clinician vocabulary additions, and per-clinician custom commands. A clinician's first month on the system tends to show steadily improving accuracy as the personal model takes shape; after a few months the system is meaningfully more accurate for that clinician than a fresh deployment would be.

**Integration with the EHR documentation workflow.** Pure transcription is "audio in, text out." Deployed dictation is "audio in, structured note in the EHR." The integration layer handles inserting the transcribed text into the right field of the right note template, formatting it appropriately (bold headers, paragraph breaks, bulleted lists), populating structured fields where possible (the medication list, the problem list), and saving the note in a state that the clinician can review and sign. Most of the practical engineering effort in deploying dictation goes into this integration layer, not into the ASR itself.

These properties combine to make medical dictation a recognizably distinct technology problem from the other voice recipes in this chapter. The pieces are familiar (ASR, language modeling, formatting). The combination, and the operational rigor required for deployment, is specific.

### Domain-Adapted ASR: How It Actually Works

The first stage of any dictation pipeline is automatic speech recognition adapted for clinical vocabulary. There are several approaches, and the field has evolved substantially over the past decade.

**Hybrid HMM-DNN systems with domain-adapted language models.** The classical architecture, dominant from roughly 2010 to 2020. An acoustic model (originally Gaussian mixtures, later deep neural networks) maps audio frames to phoneme states. A pronunciation dictionary maps phonemes to words. A language model scores word sequences by plausibility. The components are separately trained and decoded jointly via weighted finite-state transducers. The "medical" adaptation typically came from a domain-specific pronunciation dictionary (with explicit pronunciations for drug names and anatomical terms) and a domain-specific language model (trained on clinical text corpora). Nuance Dragon Medical and most enterprise medical-dictation products through the late 2010s used variants of this architecture. It is still in production at large scale; the architecture is mature, the components are interpretable, and the per-clinician adaptation hooks are well-established. 

**End-to-end neural systems trained on clinical audio.** The new wave, gaining traction since roughly 2020. A single neural model (encoder-decoder transformer, RNN-Transducer, CTC-based variant) trained directly on paired audio-transcript data. No explicit phoneme dictionary. No separate language model component. Domain adaptation comes from training data composition: include enough clinical audio in the training set, and the model learns clinical vocabulary as a side effect. Whisper-derivatives, custom vendor models, and recent versions of major-vendor offerings work this way. The architecture is simpler, the training pipeline is cleaner, and the accuracy ceiling on clinical dictation has gone up. The trade-off is that domain adaptation now requires retraining or fine-tuning the entire model, which is more expensive than swapping a language model component.

**Hybrid approaches with neural acoustic models and LLM-driven post-processing.** A common 2026 pattern: a strong neural ASR (general-domain or moderately clinical) produces a verbatim transcript. A clinical large language model post-processes the transcript for medical-vocabulary correction, formatting, and structured-field extraction. The ASR is responsible for getting most words right; the LLM is responsible for fixing the medical-specific errors and producing the formatted note. This pattern is computationally heavier than pure ASR but produces excellent results when tuned well, and it lets the institution mix and match best-of-breed components. It is also the pattern most aligned with where the open-source ecosystem has moved (Whisper for audio-to-text, then a domain-tuned LLM for everything downstream).

**Vendor cloud APIs for medical ASR.** AWS Transcribe Medical, Google Cloud Healthcare's speech APIs, Microsoft Azure's healthcare-tuned speech services, Nuance Dragon Medical Cloud, and several specialized vendors offer cloud-hosted ASR specifically tuned for clinical vocabulary. These are the pragmatic choice for most institutional deployments: the model is maintained by the vendor, the accuracy is competitive with the best on-premise alternatives, the BAAs are in place, and the integration is handled through standard APIs. The trade-off is per-minute cost, network dependence, and vendor lock-in. 

For the rest of this recipe, we will treat the ASR layer as a domain-adapted speech recognizer with the following properties: it transcribes long-form clinical dictation with WER in the low single digits in good conditions, it returns per-word confidence scores, it supports custom vocabulary biasing, it supports speaker adaptation when given enough audio per clinician, and it is HIPAA-eligible under the relevant business associate agreement. The architectural pattern works regardless of whether the underlying implementation is a vendor's cloud API, a self-hosted Whisper variant, or a custom-trained model.

### Custom Vocabulary, Pronunciation, and Per-Clinician Adaptation

ASR accuracy on clinical vocabulary is the single highest-leverage knob in this recipe. Several techniques work, and most production deployments combine them.

**Custom vocabulary and biasing lists.** Most cloud ASR APIs accept a list of words or phrases the recognizer should be biased toward. For clinical dictation, this list includes the institution's formulary, the common procedure names for the practiced specialties, the names of providers and facilities, and any specialty-specific terminology that might be unusual. The biasing dramatically improves recognition of these terms; without it, even a clinically-tuned model will sometimes fall back to the closest non-medical word ("Wolff-Parkinson-White" might transcribe as "wolf parking white" if the model has not seen the eponymous syndrome enough times in training). 

**Custom pronunciations.** Some clinical terms have non-obvious pronunciations. "Cefepime" is pronounced something like "seff-eh-PEEM," not "see-feh-pime." Drug names with non-English origins have pronunciations that an English-trained ASR will systematically miss. Custom pronunciation dictionaries let the institution explicitly specify how a term should be recognized acoustically. This is more important for hybrid HMM-DNN systems with explicit pronunciation dictionaries; for end-to-end neural systems, the equivalent is making sure enough training examples of the term exist in the training data.

**Per-clinician acoustic adaptation.** Once a clinician has dictated several hours of audio, the system can adapt to their voice. Speaker-adaptive techniques (i-vectors, x-vectors, fine-tuning the acoustic model on the clinician's audio, or simpler approaches like maintaining per-clinician language model weights) substantially improve accuracy for that specific clinician. The accuracy gains are often the largest single lever for clinicians whose accent or speaking style is underrepresented in the vendor's general training data.

**Per-clinician custom vocabulary.** Each clinician has their own preferred terminology, commonly-used templates, names of patients on their panel, names of colleagues they refer to, and personal abbreviations. A per-clinician custom-vocabulary list captures these and biases the recognizer when that specific clinician is dictating.

**Per-clinician auto-text macros.** Beyond ASR-level adaptation, clinicians build personal libraries of canned text fragments triggered by short voice keys. "Insert macro normal cardiac exam" expands to a paragraph of formatted text. "Insert macro discharge instructions for chf" expands to a custom set of patient-friendly instructions. These macros are not strictly an ASR feature, but they live in the dictation product and can dramatically reduce the volume of dictation required.

**Specialty templates.** Beyond per-clinician macros, the institution often maintains specialty-level templates: a standard radiology report layout, a standard operative note layout, a standard psychiatric evaluation layout. The template is loaded at the start of the dictation; the clinician dictates into specific sections of the template; the formatted note follows the institutional standard. Templates interact with voice commands ("go to assessment," "next section") to let the clinician navigate the structured note while still dictating.

The cumulative effect of these techniques is that a mature dictation deployment is not running a generic medical ASR. It is running a heavily-customized speech recognition system for each clinician, using each clinician's personal vocabulary, each clinician's voice profile, each clinician's specialty's templates, and the institution's broader formulary and provider list. Setting this up takes engineering work; running it takes ongoing operational work; the payoff is the difference between "dictation system clinicians grudgingly use" and "dictation system clinicians refuse to give up."

### Voice Commands and Mode Switching

A dictation system has two primary input modes: dictation content (which becomes text in the note) and voice commands (which trigger system actions). The boundary between them is where some of the most interesting engineering decisions live.

**Explicit command prefix.** The simplest disambiguation is a wake word or command prefix. The clinician says "computer, new paragraph" and the system knows the words after "computer" are a command. Disadvantages: extra words to remember, awkward phrasing, false-fires when the prefix occurs in dictation content.

**Implicit command detection by phrasing.** The system maintains a vocabulary of command phrases ("new paragraph," "next field," "delete that sentence," "select all," "insert template X") and treats utterances matching these phrases as commands rather than content. Advantages: natural phrasing, no extra words. Disadvantages: requires the system to disambiguate when the same phrase could plausibly be content. ("Delete that sentence" issued during a clinical-decision-making note about how the patient's mother told them to delete that sentence is, plausibly, content rather than a command. This case is rare but real.)

**Push-to-command versus push-to-talk.** Some systems use the opposite of push-to-talk: the microphone is always live for dictation, and the clinician presses a button while issuing a command. This inverts the friction (the common case is frictionless; the less-common case has a button) and is the dominant pattern in mature dictation products.

**Context-aware command handling.** Some commands are only valid in certain contexts. "Sign and submit" makes sense at the end of the note, not mid-sentence. "Insert assessment template" makes sense before assessment is dictated, not after. Modern systems use note-state context to disambiguate command intent and to suggest valid commands.

**Audit and reversibility for commands.** Commands have effects on the note (paragraph breaks, deletions, template insertions). The system has to make these effects clearly visible (the note updates so the clinician can see what happened), reversible (undo support), and auditable (for the eventual review-and-sign step). Silent command execution is a recipe for clinicians signing notes that contain mistakes they did not realize the system had introduced.

### Formatting, Structuring, and the Note Template

The raw ASR output is verbatim text. The clinical note is formatted, structured, and embedded in a template. Bridging the two is the formatting and structuring layer.

**Punctuation and capitalization.** Verbatim ASR output may not include punctuation. (Some systems insert it automatically; others rely on explicit dictation of punctuation marks: "the patient is a fifty four year old male period he presents with chest pain comma which began three days ago period.") Modern systems use sentence-boundary-detection models that infer punctuation from prosody and language context, so the clinician does not have to dictate every comma and period. Capitalization at sentence starts and proper nouns is similarly automated.

**Number and date formatting.** "Fifty four year old male" becomes "54-year-old male." "Two thousand twenty four" becomes "2024." "Five milligrams twice a day" becomes "5 mg BID" (or "5 mg twice daily," depending on institutional convention). "October fourteenth" becomes "10/14" or "October 14, 2026." These canonicalizations are deterministic in the easy cases and surprisingly hard in the edge cases; most production systems use rule-based formatters with handcrafted exceptions for clinical conventions.

**Section headers and structural formatting.** A dictated phrase like "history of present illness colon" becomes a bolded header "**History of Present Illness:**" followed by a paragraph break. The mapping from dictated phrasing to formatted structure is part-template, part-rule, and part-machine-learned. Modern systems make these conversions feel natural; legacy systems require more explicit dictation of structural cues.

**Medical-vocabulary normalization.** "Lisinopril ten milligrams po daily" becomes "lisinopril 10 mg PO daily" with the abbreviations expanded and capitalized per institutional preference. The mapping from dictated forms to canonical forms is institution-specific and often clinician-specific.

**LLM-driven formatting and structuring.** The 2024-2026 evolution: rather than rule-based formatters, run the verbatim transcript through a clinical LLM with a prompt that asks for the formatted note. The LLM handles punctuation, number formatting, header structuring, and even high-level reorganization (moving a sentence the clinician dictated out of order into the right section). The advantages: dramatically more flexible than rules, handles edge cases gracefully, can populate structured fields (medications, problems, allergies) into the right EHR slots while leaving narrative text for the human-readable note. The disadvantages: per-call cost, latency, and the standard LLM concern that the output may be a fluent reformulation rather than a faithful transcription. Production systems mitigate by treating the LLM output as a draft for clinician review, never as the final signed note. 

### The Read-Edit-Sign Workflow

Dictation, unlike voice navigation, produces an artifact that requires explicit clinician review and signature before it becomes part of the medical record. The review-and-sign workflow is where the technology meets clinical safety.

**Read-back and review.** The clinician reads the formatted note before signing. Errors caught at this stage are corrected; errors missed become part of the chart. The fidelity of the read-back is the single most important user-experience element after ASR accuracy itself. A note that displays as a wall of dense text invites quick skimming rather than careful reading. A note that highlights low-confidence words, structurally formats the content, and presents corrections suggested by the LLM in a tracked-changes view invites genuine review.

**Confidence highlighting.** Words the ASR transcribed with low confidence are highlighted in the read-back view. The clinician's eye is drawn to them first. This dramatically improves error-catch rate compared to plain unmarked text.

**Spell-check and consistency-check overlays.** Beyond ASR confidence, the system can highlight: words not in the institutional medical lexicon (potentially mistranscribed), apparent contradictions in the note (the assessment says "no fever" but the vitals section dictated earlier shows a temperature of 102), entities mentioned that do not match the patient's structured chart (the dictation mentions "lisinopril" but the patient's medication list has "losartan"). These cross-checks turn the review from a pure ASR-error-catch into a broader documentation-quality-assurance step.

**Track changes between draft and final.** When the LLM has reformatted the verbatim transcript, the read-back can show a diff between what the clinician actually said and what the LLM proposes for the final note. This lets the clinician verify that the LLM did not paraphrase clinical content in ways that change meaning.

**Structured-field extraction with confirmation.** When the system has extracted structured fields (medications, problems, allergies, vitals) from the dictation, it presents them for explicit confirmation before adding them to the patient's structured chart. This is the boundary where dictation-as-narrative crosses into dictation-as-data-entry, and it deserves the same rigor as the read-write boundary in recipe 10.3.

**Co-signature workflows for trainees.** In academic settings, residents and fellows dictate notes that attendings co-sign. The dictation system has to support multi-signer workflows, with the trainee's draft visible to the attending, with the attending's edits tracked, with both signatures captured in the final note.

**Late-addendum support.** Notes that have been signed sometimes need addenda. The dictation system has to support addendum dictation as a distinct workflow that does not modify the original signed note; the addendum is a separate, dated, signed document that links to the original.

### Where the Field Has Moved

Some practical updates worth knowing.

**End-to-end neural ASR has caught up to and surpassed hybrid systems for clinical dictation.** Five years ago, the medical ASR market was dominated by hybrid HMM-DNN systems with hand-tuned clinical language models. Today, end-to-end neural systems trained on clinical audio are competitive or better on most benchmarks, and the gap continues to widen. Vendor offerings have largely transitioned, even where the product names have stayed the same.

**LLM-driven formatting has reshaped product expectations.** Clinicians who used dictation in 2020 are surprised by what 2026 products can do: structured notes generated from rambling unstructured dictation, medication-list extraction with cross-checks against the chart, billing-code suggestion based on note content, automatic problem-list updates, and visit-summary generation for after-visit summaries. Most of this "smart" behavior is LLM post-processing rather than ASR improvements.

**Per-clinician adaptation is largely automatic.** Modern dictation products no longer require explicit "voice profile training" sessions; the system continuously adapts in the background as the clinician uses it. The first day's accuracy may be a few percentage points worse than the steady-state accuracy after a few months, but the gap closes without active effort from the clinician.

**Cloud has become the dominant deployment model.** On-premise medical ASR, common in 2018, is now a niche deployment for institutions with strict data-residency requirements. Most institutions deploy cloud-hosted ASR with the audio sent to a HIPAA-eligible vendor service over a properly-secured channel. The latency, accuracy, and operational cost of cloud are now reliably better than comparable on-premise deployments.

**Specialty-specific tuning has become a vendor competition axis.** Vendors compete on specialty-specific accuracy: Dragon Medical's radiology variant, M-Modal's pathology specializations, vendor-bundled offerings with EHR-integrated specialty templates. Institutions deploying dictation typically do per-specialty evaluation rather than a single institution-wide benchmark.

**The build-versus-buy economics have shifted further toward buy.** A custom-built medical-dictation system (data acquisition, model training, vocabulary tuning, formatting layer, EHR integration, clinician adaptation pipeline) is a multi-year, multi-million-dollar engineering effort. Commercial products have absorbed that engineering investment and amortized it across many institutions. For all but the most unusual specialty use cases, buying is the right answer in 2026, and the recipe walks through what to evaluate when buying. The building path is reserved for institutions with research-level resources and unusual requirements.

**Ambient documentation has become a distinct product category.** Five years ago, dictation and ambient documentation (recipe 10.7) blurred together in product positioning. Today they are clearly distinct: dictation is single-speaker, intentional, structured; ambient is multi-speaker, conversational, requires diarization. Some vendors offer both; some specialize. The integration of dictation and ambient into a single clinician workflow (the clinician uses ambient during the encounter and dictates supplementary detail afterward) is an emerging design pattern.

**Specialty subdialect models are increasingly available.** The major vendors offer specialty-tuned variants (radiology, pathology, cardiology, emergency medicine, psychiatry, mental health). The specialty tuning improves accuracy on the high-frequency vocabulary of that specialty and adapts the formatting layer for the specialty's documentation conventions.

---

## General Architecture Pattern

A medical dictation system splits cleanly into eight logical stages: activation and audio capture (the clinician begins dictating, optionally with a push-to-talk control), streaming or batch ASR with domain adaptation (the audio becomes verbatim transcript), command-versus-content disambiguation (system actions versus dictated text are routed appropriately), formatting and structuring (raw transcript becomes formatted clinical note), template integration (the formatted text is placed into the right sections of the right note template), structured-field extraction (medications, problems, vitals are extracted as structured data), read-edit-sign (the clinician reviews, corrects, and signs), and audit-and-archive (the final note, the dictation audio, and the metadata are durably stored with the right retention).

```text
┌──────────── ACTIVATION & AUDIO CAPTURE ──────────────────┐
│                                                           │
│   [Clinician begins dictation session]                    │
│    - Push-to-dictate (button on dictation mic, on-screen  │
│      mic toggle, foot pedal)                              │
│    - Or always-listening with explicit start command      │
│   [Microphone captures audio]                             │
│    - Headset mic (gold standard for power users)          │
│    - Handheld dictation mic (radiology, pathology         │
│      reading rooms)                                       │
│    - Mounted mic on workstation (general clinical use)    │
│   [Stream or buffer audio]                                │
│    - Streaming: real-time front-end dictation             │
│    - Batch: back-end dictation, sent to ASR after end     │
│      of session                                           │
│           │                                               │
│           ▼                                               │
│   [Output: dictation session with audio stream or         │
│    audio file, plus session metadata: clinician ID,       │
│    note template, patient context, specialty]             │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── DOMAIN-ADAPTED ASR ──────────────────────────┐
│                                                           │
│   [Speech recognizer with clinical vocabulary]            │
│    - Custom vocabulary biasing (institutional formulary,  │
│      specialty terms, provider names, patient panel)      │
│    - Per-clinician adaptation (acoustic model adapted     │
│      to this clinician's voice; per-clinician vocab)      │
│    - Per-specialty model variant where available          │
│                                                           │
│   [Streaming: emit partial transcripts as audio arrives;  │
│    finalize on end-of-utterance or end-of-dictation]      │
│   [Batch: process the full audio file and return the      │
│    complete transcript with per-word timing]              │
│                                                           │
│   [Per-word and per-utterance confidence scores]          │
│    - Used downstream for review-pane highlighting         │
│           │                                               │
│           ▼                                               │
│   [Output: verbatim transcript with timing, per-word      │
│    confidence, speaker info if multi-speaker]             │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── COMMAND vs CONTENT DISAMBIGUATION ───────────┐
│                                                           │
│   [Detect command phrases in the transcript stream]       │
│    - Explicit prefix ("computer, new paragraph") OR       │
│    - Phrasing match against command vocabulary OR         │
│    - Push-to-command modal switch                         │
│                                                           │
│   [Route commands to the system action handler]           │
│    - Navigation: next field, previous section, go to      │
│      assessment                                           │
│    - Editing: delete that sentence, select last word,     │
│      capitalize that                                      │
│    - Templates: insert template X, expand macro Y         │
│    - Workflow: sign and close, save and continue          │
│                                                           │
│   [Route content to the formatting layer]                 │
│           │                                               │
│           ▼                                               │
│   [Output: tagged stream of (content | command) events    │
│    in the order they were dictated]                       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── FORMATTING & STRUCTURING ────────────────────┐
│                                                           │
│   [Punctuation and capitalization inference]              │
│    - Sentence boundaries detected from prosody and        │
│      language context                                     │
│    - Proper noun capitalization                           │
│                                                           │
│   [Number, date, and unit canonicalization]               │
│    - "fifty four year old" -> "54-year-old"               │
│    - "ten milligrams" -> "10 mg"                          │
│    - "october fourteenth" -> "October 14"                 │
│                                                           │
│   [Section header detection and formatting]               │
│    - "history of present illness colon" -> bolded         │
│      header followed by paragraph                         │
│                                                           │
│   [Optional LLM post-processing]                          │
│    - Reorganize content into the correct sections         │
│    - Fix obvious medical-term mistranscriptions           │
│    - Suggest medication-list, problem-list, allergy-list  │
│      updates from the dictated content                    │
│    - Faithfulness check: does the formatted note still    │
│      say what the clinician actually dictated?            │
│           │                                               │
│           ▼                                               │
│   [Output: formatted note text with per-word confidence,  │
│    optionally a diff between verbatim and formatted, and  │
│    optional structured-field suggestions]                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── TEMPLATE INTEGRATION ────────────────────────┐
│                                                           │
│   [Load the appropriate note template]                    │
│    - Template selected by note type, specialty, encounter │
│      type, and clinician preference                       │
│                                                           │
│   [Insert formatted text into template sections]          │
│    - Each command-driven section navigation directs       │
│      content to a specific template field                 │
│    - Free-form dictation populates the section the        │
│      cursor is currently in                               │
│                                                           │
│   [Carry forward and preserve template metadata]          │
│    - Smart phrases, auto-populated fields (vitals from    │
│      structured chart data), required field markers       │
│           │                                               │
│           ▼                                               │
│   [Output: draft note in template form, ready for         │
│    review]                                                │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── STRUCTURED-FIELD EXTRACTION ─────────────────┐
│                                                           │
│   [Extract structured entities from the dictation]        │
│    - Medications (RxNorm-coded)                           │
│    - Problems (ICD-10-coded)                              │
│    - Allergies (RxNorm or NDF-RT)                         │
│    - Vital signs                                          │
│    - Procedures (CPT-coded)                               │
│                                                           │
│   [Cross-check against the structured chart]              │
│    - Does the dictation mention a medication that is not  │
│      on the active list?                                  │
│    - Does the dictation contradict a documented allergy?  │
│    - Highlight discrepancies for clinician review         │
│                                                           │
│   [Suggest structured updates with explicit confirmation] │
│    - Never silently update structured chart fields from   │
│      dictation; always present as a suggestion            │
│           │                                               │
│           ▼                                               │
│   [Output: list of structured-field suggestions, each     │
│    with source span in the dictation, current chart       │
│    value, and confidence]                                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── READ-EDIT-SIGN ──────────────────────────────┐
│                                                           │
│   [Render the formatted note for review]                  │
│    - Low-confidence words highlighted                     │
│    - LLM-suggested edits shown as tracked changes         │
│    - Structured-field suggestions displayed alongside     │
│    - Cross-check warnings (med list, allergy contradiction│
│      etc.) flagged                                        │
│                                                           │
│   [Clinician reviews and corrects]                        │
│    - Voice-driven correction ("change last sentence to    │
│      X") or keyboard-driven                               │
│    - Each correction emits a "user-correction" event for  │
│      adaptation feedback                                  │
│                                                           │
│   [Clinician confirms structured-field updates]           │
│    - Explicit accept or reject per suggestion             │
│                                                           │
│   [Clinician signs the note]                              │
│    - Signature is the legal commitment that the note is   │
│      accurate and complete                                │
│           │                                               │
│           ▼                                               │
│   [Output: final signed note, structured updates applied  │
│    where confirmed, user-correction stream for adaptation │
│    feedback]                                              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌──────────── AUDIT, ARCHIVE & ADAPTATION ─────────────────┐
│                                                           │
│   [Durable note storage in the EHR]                       │
│    - The signed note is the legal record                  │
│                                                           │
│   [Audio retention decision]                              │
│    - Retain briefly for QA and adaptation feedback        │
│    - Or discard immediately after transcription           │
│    - Or retain longer with appropriate consent and        │
│      access controls                                      │
│                                                           │
│   [Adaptation feedback loop]                              │
│    - User corrections feed per-clinician adaptation       │
│    - Aggregate corrections feed institution-wide          │
│      vocabulary and formatting improvements               │
│                                                           │
│   [Audit log entry]                                       │
│    - Clinician identity, dictation start and end,         │
│      audio reference, ASR version, formatting version,    │
│      LLM version, structured-field suggestions and        │
│      acceptance, signature timestamp                      │
│                                                           │
│   [Operational telemetry]                                 │
│    - Dictation duration, ASR confidence distribution,     │
│      correction rate, accept rate for structured-field    │
│      suggestions, time-to-sign distribution               │
│           │                                               │
│           ▼                                               │
│   [Output: signed note in EHR, audit trail, telemetry,    │
│    adaptation signals fed into the next dictation]        │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points the architecture has to bake in.

**Audio is PHI and must be handled accordingly.** The dictation audio captures the clinician describing the patient's condition. It is, in every regulatory reading, PHI. The architecture treats it as such: encrypted at rest, encrypted in transit, access-controlled per clinician, retention bound by an explicit policy, and BAAs in place for any vendor service that processes the audio.

**The clinician's signature is the gate to the legal record.** Until the clinician signs, the note is a draft. The architecture must prevent unsigned drafts from being treated as authoritative clinical documentation; downstream systems (CDS, billing, public-health reporting) consume signed notes only.

**Per-clinician adaptation requires an adaptation pipeline.** The user-correction events from the read-edit-sign workflow are the training signal that improves the system over time. The adaptation pipeline has to capture them, attribute them correctly (this correction is from clinician C, on dictation D, of word W), and feed them into the per-clinician vocabulary and acoustic models. Skipping the pipeline means the system never improves beyond its day-one accuracy.

**Critical-error detection is not the same as overall accuracy monitoring.** Word error rate measures aggregate accuracy. Critical-error rate measures clinically-meaningful errors. The system needs explicit detection for the dangerous error classes: laterality flips, negation flips ("no" vs "not"), drug-name confusions among similar-sounding pairs, dose-by-order-of-magnitude errors, and domain-specific high-stakes substitutions. These deserve their own monitoring and their own alerts.

**Voice commands and dictation content require unambiguous separation.** The boundary between content and commands is one of the highest-stakes design decisions in the recipe. Ambiguous decisions produce notes with command artifacts in them ("new paragraph" appearing as text in the note) or commands silently ignored (the clinician said "delete that sentence" but the system treated it as content). The recipes that handle this well use explicit modal switching (push-to-command, or a clear command prefix); the recipes that struggle use heuristic disambiguation that occasionally gets it wrong in obvious ways.

**Structured-field extraction is a draft, never a fact.** Extracting a medication-list update from a dictation and silently applying it to the patient's structured chart is dangerous. The clinician must explicitly confirm each structured-field change. The architecture treats extracted entities as suggestions, never as durable updates.

**Audit retention has to span the legal record's lifetime.** The note is part of the medical record and is retained for the longer of HIPAA's six-year minimum, the state's medical-records-retention floor, and the institution's policy. The audit trail (who dictated, who signed, what corrections were made between draft and signature) is part of the durable record.

**Failure has to degrade to a usable fallback.** When the ASR is unavailable, when the LLM post-processor is unavailable, when the EHR API is unreachable, the clinician must be able to fall back to typing or to a delayed-batch dictation workflow. A dictation system that completely blocks documentation when one component fails is one that gets uninstalled.

**Specialty differences are first-class.** A radiology dictation flow, a primary care visit-note flow, and an emergency department flow have different templates, different vocabulary distributions, different formatting conventions, and different clinician expectations. The architecture must support per-specialty configuration without forking the entire stack.

**Adoption depends on training and workflow integration as much as accuracy.** The metric that determines whether the system succeeds is sustained adoption at the three-month and six-month mark. Vendors and institutional teams that invest in clinician training, on-call support during early use, and per-specialty workflow tuning consistently see better adoption than vendors and teams that ship the technology and assume clinicians will figure it out.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter10.04-architecture). The Python example is linked from there.

## The Honest Take

Medical dictation is the most established voice product category in healthcare. The technology works. Clinicians have been using it for decades. The vendor landscape is mature. The accuracy benchmarks are well-understood. And, having said all of that, building a dictation system that genuinely improves the clinician's day, with the rigor that the clinical-safety implications demand, is harder than the maturity of the field suggests.

The first trap is treating dictation as a solved problem and skipping the investment in deployment quality. The technology is mature. The deployment quality is not. A dictation deployment that ships with an out-of-the-box vendor configuration, an hour of clinician training, and no per-specialty tuning will see modest adoption, mediocre accuracy, and disappointing time savings. A dictation deployment that ships with curated custom vocabulary, per-specialty templates, named clinician champions, structured training, and on-call support during the first weeks will see substantially better outcomes. The difference between the two deployments is engineering and operational investment, not technology choice. The institutions that succeed treat dictation as a workflow project that uses speech recognition; the institutions that struggle treat it as a speech-recognition project that has some workflow.

The second trap is over-relying on overall accuracy metrics. A 96% word accuracy sounds excellent until you realize that 96% accuracy on a thousand-word note means forty errors, some of which are in clinically-meaningful terms. The metric that matters is critical-error rate, not WER. A dictation system with 92% WER and a tightly-managed critical-error rate is safer than one with 97% WER and no critical-error tracking. The vendor benchmarks usually report WER; the institutional benchmarks should add critical-error rate as a primary axis. The dictation systems that have been deployed for years and never had a serious clinical-safety incident are the ones with explicit critical-error detection; the ones that have had incidents typically did not.

A third trap is assuming the LLM post-processing is an unmitigated good. LLM-driven formatting is genuinely useful. It is also a faithfulness risk that the architecture has to actively manage. The clinician dictates "may have," and the LLM produces "had." The clinician dictates "intermittent," and the LLM smooths it to "occasional." The clinical claim is now subtly different. In aggregate, these small drifts accumulate into a class of failure that is invisible at the individual-note level but real at scale. The faithfulness check (detailed in the [architecture companion](chapter10.04-architecture)) is not an optional optimization; it is a structural requirement. Run the verbatim transcript and the LLM-formatted note through a faithfulness-comparison pass before treating the LLM output as the canonical draft. When in doubt, fall back to the rule-based draft and surface the LLM version as a "suggested alternative." This is not paranoia; it is the design discipline that distinguishes careful clinical software from confident-but-occasionally-hallucinating consumer software. The faithfulness program is one of the highest-leverage investments in this recipe and the easiest to underweight.

A fourth trap is underinvesting in disambiguation between voice commands and dictation content. The boundary between "delete that sentence" as a command and "delete that sentence" as content is real, and the systems that handle it badly produce notes with command artifacts in them ("new paragraph" appearing literally) or commands silently ignored. Modern systems with explicit command prefixes (or push-to-command modal switches) handle this reasonably well; legacy systems that rely on phrase-matching heuristics still occasionally surprise people. When evaluating vendor products or building custom, this is a question to interrogate explicitly: how does the system distinguish commands from content, and what is the failure mode when it gets it wrong? "It mostly works" is not a satisfactory answer.

A fifth trap is failing to plan for the per-specialty tuning that mature deployments require. The dictation patterns of a primary care physician, a radiologist, and an emergency medicine physician are dramatically different. A single institution-wide configuration optimized for one specialty produces mediocre results for the others. The configuration architecture must support per-specialty templates, per-specialty custom vocabularies, per-specialty LLM prompts, and per-specialty critical-error rules. Pilot per specialty. Roll out per specialty. Monitor per specialty. The institutions that try to ship a single configuration across the entire clinical staff routinely see one or two specialties succeed wildly and the rest underperform.

A sixth trap is skipping the build-vs-buy analysis. Most institutions should be buying a commercial dictation product, not building a custom one. The recipe describes the architecture either way; the recipe does not endorse the build path for institutions that have not done the analysis carefully. Commercial vendors (Nuance Dragon Medical, M-Modal/3M, Dolbey, vendor-bundled offerings from Epic and Cerner) have absorbed an enormous engineering investment over decades, including custom acoustic models, deep EHR integration, per-specialty optimization, and per-clinician adaptation pipelines. Matching that investment from scratch is a multi-year effort. Custom builds make sense in specific niches: unusual specialty use cases poorly served by commercial products, languages with no commercial offering, on-premise-only deployments where the network architecture forbids cloud ASR, research contexts where the model and the data flow are research artifacts in their own right. For a typical institutional deployment serving a typical clinical staff, buy.

The thing that surprises engineers coming from consumer-voice-assistant backgrounds is how much of the engineering value is in formatting and template integration, not in speech recognition. Good ASR is table stakes; the differentiated value is in turning the ASR output into a formatted clinical note with the right section structure, the right vocabulary normalization, the right structured-field suggestions, and the right read-edit-sign workflow. The engineering team that obsesses over ASR accuracy and ships a mediocre formatting layer ships a product clinicians do not adopt. The engineering team that ships solid-but-not-state-of-the-art ASR with a great formatting and review experience ships a product clinicians use every day.

The thing that surprises engineers coming from EHR-integration backgrounds is how acoustic considerations dominate the deployed accuracy. The microphone hardware, the room acoustics, the clinician's speaking habits, all matter as much as the ASR model. A poor microphone in a noisy environment with a tired clinician produces bad audio that produces bad ASR that produces bad formatting that produces a note the clinician spends ten minutes correcting. Investing in good microphone hardware (close-talking headsets for power users, beamforming workstation mics for general use, handheld dictation mics for radiologists and pathologists who prefer them) and the room conditions where dictation happens yields more accuracy improvement than the same investment in the model layer.

The thing about Amazon Transcribe Medical specifically: it is a competent baseline for clinical-domain ASR. The specialty-specific tuning (PRIMARYCARE, CARDIOLOGY, NEUROLOGY, ONCOLOGY, RADIOLOGY, UROLOGY) covers the largest deployment volumes; specialties outside that list use the closest specialty configuration plus aggressive custom vocabulary. The streaming variant hits the latency budget for front-end dictation reliably. The accuracy on prepared dictation in good conditions is genuinely strong; the accuracy under field conditions varies more, as it does for every cloud ASR vendor. 

The thing about Amazon Bedrock specifically: the LLM-driven formatting and structuring is genuinely valuable, with the faithfulness caveats already covered. Choose a model with healthcare instruction tuning where available; validate against held-out reference notes; treat output as draft. The cost of LLM post-processing is meaningful but small compared to the per-clinician productivity gain when it works.

The thing about Amazon Comprehend Medical specifically: it is the right tool for coded clinical-entity extraction. The RxNorm linking, the ICD-10 linking, the negation detection are all solid. The accuracy varies with the kind of clinical text; performance on dictated narrative is generally good but not perfect, and the structured-field suggestions should always be presented for clinician confirmation rather than applied silently.

The thing about per-clinician adaptation: it is the highest-leverage long-term investment in the deployment. A clinician who has used the system for six months sees substantially better accuracy than a fresh deployment. The adaptation pipeline that captures user corrections and feeds them back into the per-clinician vocabulary and acoustic profile is what transforms "dictation that mostly works" into "dictation the clinician relies on." Build the pipeline early; the longer the system runs without adaptation, the longer the per-clinician accuracy stays at the day-one baseline.

The thing about audio retention: this is the single most contentious privacy decision in the architecture. The privacy officer wants discard-immediately. The ML engineering team wants retain-for-model-improvement. The clinical-quality team wants retain-briefly-for-QA-review. Each has legitimate points. The default in this recipe is brief retention (seven to thirty days) with KMS-encrypted storage, access logged through CloudTrail, and a lifecycle policy for automatic deletion. Longer retention requires explicit clinician consent at onboarding and a documented purpose for retention. The decision is institutional and should be revisited annually.

The thing I would do differently the second time: budget more, earlier, for clinician training and on-call support during early use. Every successful dictation deployment I have seen has invested heavily in this. Per-specialty rollouts, named clinician champions, on-call engineering support during the first weeks, scheduled refresh training at three months, and a feedback channel that clinicians actually use. The deployments that skip this investment and assume the system will sell itself through pure productivity gain consistently underperform. The system is good. Clinicians using the system effectively is a different thing.

The last thing, because it is the easiest one to get wrong: medical dictation produces clinical documentation that becomes the legal record. A misrecognized word in a signed note is a clinical-safety event, a billing-compliance event, and potentially a litigation event. The system's job is not just to make dictation fast; it is to make sure the signed note accurately reflects the clinical encounter. The critical-error detection, the faithfulness checking, the explicit-confirmation rigor for structured-field updates, the read-edit-sign workflow that makes errors easy to catch, all serve this purpose. A dictation system that optimizes for speed at the expense of accuracy ships a product that produces unreliable clinical records at scale. A dictation system that takes the safety rigor seriously ships a product that clinicians and institutions can stand behind.

---

## Related Recipes

- **Recipe 10.1 (IVR Call Routing Enhancement):** Same chapter, customer-facing voice analog with a constrained-vocabulary ASR and intent classification. Different domain, different stakes, but the streaming-ASR-with-domain-adaptation pattern is shared.
- **Recipe 10.2 (Voicemail Transcription and Classification):** Same chapter, async transcription analog. Different latency requirements but similar audio-to-text-to-action pipeline.
- **Recipe 10.3 (Voice-to-Text for EHR Navigation):** Same chapter, the short-command analog of dictation. Voice navigation and voice dictation are deliberately distinct product categories; this recipe and 10.3 are companions, not alternatives.
- **Recipe 10.6 (Speech-to-Text for Telehealth Documentation):** Same chapter, multi-speaker variant with diarization. The ASR and formatting concerns overlap; the diarization concern is distinct.
- **Recipe 10.7 (Ambient Clinical Documentation):** Same chapter, the most clinically-related recipe. Ambient is the conversational, multi-speaker, passively-captured analog of intentional dictation. Many institutions deploy both; the integration patterns are an emerging engineering practice.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2, LLM-driven post-processing of clinical text. The LLM-formatting layer in this recipe shares engineering patterns with note summarization; the faithfulness concerns are similar.
- **Recipe 2.3 (Clinical Documentation Improvement):** Chapter 2, LLM-driven note quality. The dictation quality-scoring extension above draws from this pattern.
- **Recipe 8.x (Traditional NLP):** The structured-field extraction draws from the named-entity-recognition and clinical-NLP patterns covered in chapter 8.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** The voice-command vocabulary management and command-versus-content disambiguation patterns map onto the conversational-assistant patterns in chapter 11.

---

## Tags

`speech-voice-ai` · `medical-dictation` · `medical-transcription` · `front-end-dictation` · `back-end-dictation` · `clinical-documentation` · `domain-adapted-asr` · `transcribe-medical` · `streaming-asr` · `batch-asr` · `custom-vocabulary` · `per-clinician-adaptation` · `voice-commands` · `note-template` · `formatting` · `structured-field-extraction` · `comprehend-medical` · `rxnorm-linking` · `icd10-linking` · `bedrock-formatting` · `faithfulness-check` · `critical-error-detection` · `read-edit-sign` · `clinician-signature` · `ehr-integration` · `smart-on-fhir` · `specialty-tuning` · `radiology-dictation` · `pathology-dictation` · `ed-dictation` · `bedrock` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `sagemaker` · `medium` · `production-track` · `hipaa` · `phi-handling` · `audit-trail` · `equity-monitoring` · `clinician-burden-reduction` · `pajama-time`

---

*← [Recipe 10.3: Voice-to-Text for EHR Navigation](chapter10.03-voice-to-text-ehr-navigation) · [Chapter 10 Index](chapter10-preface) · [Recipe 10.5: Patient-Facing Voice Assistant](chapter10.05-patient-facing-voice-assistant) →*
