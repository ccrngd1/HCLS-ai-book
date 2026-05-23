# Recipe 10.4: Medical Transcription (Dictation) ⭐⭐

**Complexity:** Medium · **Phase:** Production-track · **Estimated Cost:** ~$0.02-0.10 per dictated note (depends on note length, choice of general-purpose vs medical-domain ASR, optional LLM post-processing for formatting, and whether human QA review is in the loop)

---

## The Problem

It is 6:47 PM. The clinic schedule said the day ended at 5:00. The last patient left forty-five minutes ago. The lights in the empty waiting room are off. There is a physician in a back office who has not had dinner, has not called home to say she is running late again, and is sitting in front of a computer typing the day's notes. Her schedule had twenty-two patients today. She finished about thirty percent of her documentation between visits. The other seventy percent is now, in this office, after hours, on her own time.

The note she is currently typing is for a patient she saw at 2:15 PM. She is trying to remember the patient's exact words about a new symptom. She is trying to remember whether the patient said the pain started "two weeks ago" or "about two weeks ago, give or take." She is trying to remember which side. She is trying to reconstruct the physical exam she did four hours ago for a patient she has not seen since. The note will be technically correct. It will be far less rich than the actual encounter was. The patient said something interesting at the end of the visit that would have changed the differential, and she cannot remember it now, so it is not in the note, so the next clinician who reads this chart in three months will not know it happened.

This is not a story about one bad day. This is the median experience of clinical documentation in the United States in the late 2020s. A widely-cited 2017 study found that for every hour of direct patient care, ambulatory physicians spent close to two hours on documentation and EHR work, much of it after hours. <!-- TODO: verify; the most-cited study here is Sinsky et al. 2016 in Annals of Internal Medicine, with various follow-up studies showing the ratio has not improved meaningfully and in some specialties has gotten worse --> The colloquial term clinicians use for this is "pajama time," the documentation-after-bedtime that is so universal it has its own name. Pajama time correlates with clinician burnout, clinician attrition, reduced empathy in clinical encounters, missed clinical signals, and (in the cumulative aggregate) the slow-motion collapse of primary care as a viable career path for newly-trained physicians. <!-- TODO: verify; physician-burnout literature has strong correlation findings between EHR-documentation burden and burnout, with notable contributors including the National Academy of Medicine, AMA STEPS Forward, and Mayo Clinic Proceedings -->

The interesting thing is that the documentation problem is not new. Physicians have been struggling with the volume of clinical writing required for as long as there have been clinical records. What is new is the operational acceptance of "pajama time" as a normal feature of medical practice, the legal and billing requirements that have made the notes longer than they used to be, and the EHR interfaces that turn the act of writing a note into a click-and-type ordeal that takes substantially longer than dictation onto a tape would have taken in 1985.

Dictation is the original solution. The doctor talks; the words are transcribed; the transcription becomes the note. For decades the workflow was: doctor speaks into a handheld dictation recorder; the audio is sent to a transcription service (often offshore); a human transcriptionist types it up; the transcribed text comes back hours or days later; the doctor edits and signs. The market for medical transcription services was, at its peak in the late 2000s, substantial: thousands of transcription companies, tens of thousands of medical transcriptionists, billions of dollars in annual revenue. The workflow was slow, but it worked, and it kept the doctor's hands and eyes off the keyboard.

The 2010s and 2020s gradually replaced human transcriptionists with automated speech recognition. Nuance Dragon Medical and a handful of competitors built ASR models tuned specifically for clinical vocabulary, integrated them with the EHR, and offered front-end dictation: the doctor speaks; the words appear on screen in near-real time; the doctor edits and signs in a single workflow. This is what most clinicians today think of when they hear "medical transcription" or "medical dictation." Roughly a million U.S. physicians use some form of speech-driven documentation. <!-- TODO: verify; specific U.S. clinician dictation adoption figures continue to evolve and are difficult to pin down precisely; vendor-reported numbers tend to be inflated, but the technology is mainstream in radiology, pathology, surgery, emergency medicine, and large fractions of internal medicine and primary care -->

The dream is still the same as it was in 1985. The doctor talks. The note appears. Time spent typing approaches zero. The clinician spends more time looking at patients and less time looking at screens. What has changed is who is doing the transcription (a model, not a human), how fast the turnaround is (real-time, not overnight), and how the workflow integrates with the rest of the EHR (deeply, in modern systems, rather than as a separate dictation step).

This is recipe 10.4. It sits at the medium-complexity tier of this chapter not because medical transcription is technically novel (it is, frankly, the most established voice product category in healthcare), but because building a transcription system that is genuinely good (high accuracy on specialty vocabulary, robust to accents and speaking styles, well-integrated with documentation workflows, with the right post-processing for formatting and the right human-review safeguards) requires more careful engineering than people typically expect. The accuracy benchmarks are well-established. The vendor landscape is mature. The build-versus-buy economics for most institutions favor buying. But there is real value in understanding what is actually happening inside these products: how the ASR is tuned for clinical vocabulary, how the formatting layer turns "next paragraph history of present illness comma the patient is a fifty four year old male" into "**History of Present Illness:**\n\nThe patient is a 54-year-old male...", how the voice commands are distinguished from dictation content, and where the failure modes live.

A few specific failure modes this recipe takes seriously.

The radiologist who dictates ten reports an hour, all day, and discovers two weeks later that the dictation system has been silently mistranscribing the laterality marker (right vs left) in roughly 0.5% of reports. Two weeks of reports times ten per hour times eight hours per day times five days per week times two is four thousand reports, of which twenty have the wrong laterality marker. Twenty radiology reports with the wrong laterality is twenty potentially clinically catastrophic errors. The mistranscription of "left" as "right" is a single phoneme. The clinical consequence is enormous. <!-- TODO: verify; the laterality-mistranscription failure mode is well-documented in radiology informatics literature, with multiple studies showing left-right transcription errors in dictated radiology reports as a persistent quality and patient-safety concern -->

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

**Accuracy expectations are very high.** Productivity-driven dictation tolerates a small amount of error because the clinician reads through and corrects before signing. But the threshold for "usable" is much higher than in conversational ASR: word error rates above roughly five percent on dictated clinical text feel painful to clinicians (too many corrections per note), and word error rates above ten percent typically push clinicians off the system entirely. The vendor benchmarks for clinical-domain ASR on prepared dictation typically report word error rates in the low single digits in best-case conditions; real-world deployment numbers are usually somewhat higher. <!-- TODO: verify; medical-domain ASR vendor accuracy claims and independent benchmarks have a wide range; published academic comparisons often show production word error rates in the 4-10% range for clinical dictation depending on speaker, specialty, and acoustic conditions -->

**Safety-critical word substitutions matter more than overall WER.** A 3% word error rate distributed across function words (the, a, of, with) is fine. A 1% word error rate that systematically substitutes "no" for "not" or "left" for "right" or "hemoptysis" for "hematemesis" is dangerous. The metric that matters is not just WER but the rate and severity of clinically-meaningful errors. Vendors and academic benchmarks have started reporting "critical error rate" or "clinically significant error rate" alongside WER, and the gap between the two is a useful proxy for product quality. <!-- TODO: verify; clinically-significant-error metrics are emerging in academic and vendor benchmarks but standardization is still in progress; commonly cited frameworks include error categorization by clinical impact tier -->

**Real-time, near-real-time, or batch.** Different dictation workflows have different latency requirements. Front-end dictation, where the words appear on screen as the doctor speaks, requires sub-second streaming ASR. Back-end dictation, where the doctor speaks and the transcript is delivered later for review, can use batch ASR with potentially better accuracy. Most modern products offer both modes; the architectural trade-off is real.

**Voice commands embedded in dictation.** The clinician dictates content, but also issues commands: "new paragraph," "next field," "insert template normal physical exam," "delete that sentence," "select last sentence," "go to assessment and plan." The system has to distinguish dictated content from voice commands, which is an interesting boundary problem because some commands sound exactly like content the clinician might dictate. ("Period" can be the word "period" in a sentence about menstruation, or it can be the command to insert a punctuation mark.) Most products handle this with a combination of acoustic cues (commands often have distinct prosody), context (commands are more likely after pauses or at the end of utterances), and explicit command markers ("computer, new paragraph" or a button-press while saying the command).

**Per-clinician adaptation is essential.** Dictation users use the system every day, often for hours. The system has the opportunity (and the data) to adapt to each clinician's voice, vocabulary preferences, common phrasing, and personal templates. Modern dictation products do per-clinician acoustic adaptation, per-clinician vocabulary additions, and per-clinician custom commands. A clinician's first month on the system tends to show steadily improving accuracy as the personal model takes shape; after a few months the system is meaningfully more accurate for that clinician than a fresh deployment would be.

**Integration with the EHR documentation workflow.** Pure transcription is "audio in, text out." Deployed dictation is "audio in, structured note in the EHR." The integration layer handles inserting the transcribed text into the right field of the right note template, formatting it appropriately (bold headers, paragraph breaks, bulleted lists), populating structured fields where possible (the medication list, the problem list), and saving the note in a state that the clinician can review and sign. Most of the practical engineering effort in deploying dictation goes into this integration layer, not into the ASR itself.

These properties combine to make medical dictation a recognizably distinct technology problem from the other voice recipes in this chapter. The pieces are familiar (ASR, language modeling, formatting). The combination, and the operational rigor required for deployment, is specific.

### Domain-Adapted ASR: How It Actually Works

The first stage of any dictation pipeline is automatic speech recognition adapted for clinical vocabulary. There are several approaches, and the field has evolved substantially over the past decade.

**Hybrid HMM-DNN systems with domain-adapted language models.** The classical architecture, dominant from roughly 2010 to 2020. An acoustic model (originally Gaussian mixtures, later deep neural networks) maps audio frames to phoneme states. A pronunciation dictionary maps phonemes to words. A language model scores word sequences by plausibility. The components are separately trained and decoded jointly via weighted finite-state transducers. The "medical" adaptation typically came from a domain-specific pronunciation dictionary (with explicit pronunciations for drug names and anatomical terms) and a domain-specific language model (trained on clinical text corpora). Nuance Dragon Medical and most enterprise medical-dictation products through the late 2010s used variants of this architecture. It is still in production at large scale; the architecture is mature, the components are interpretable, and the per-clinician adaptation hooks are well-established. <!-- TODO: verify; specific Nuance Dragon Medical architecture details are vendor-internal; the hybrid HMM-DNN-with-medical-LM characterization reflects publicly-discussed industry patterns -->

**End-to-end neural systems trained on clinical audio.** The new wave, gaining traction since roughly 2020. A single neural model (encoder-decoder transformer, RNN-Transducer, CTC-based variant) trained directly on paired audio-transcript data. No explicit phoneme dictionary. No separate language model component. Domain adaptation comes from training data composition: include enough clinical audio in the training set, and the model learns clinical vocabulary as a side effect. Whisper-derivatives, custom vendor models, and recent versions of major-vendor offerings work this way. The architecture is simpler, the training pipeline is cleaner, and the accuracy ceiling on clinical dictation has gone up. The trade-off is that domain adaptation now requires retraining or fine-tuning the entire model, which is more expensive than swapping a language model component.

**Hybrid approaches with neural acoustic models and LLM-driven post-processing.** A common 2026 pattern: a strong neural ASR (general-domain or moderately clinical) produces a verbatim transcript. A clinical large language model post-processes the transcript for medical-vocabulary correction, formatting, and structured-field extraction. The ASR is responsible for getting most words right; the LLM is responsible for fixing the medical-specific errors and producing the formatted note. This pattern is computationally heavier than pure ASR but produces excellent results when tuned well, and it lets the institution mix and match best-of-breed components. It is also the pattern most aligned with where the open-source ecosystem has moved (Whisper for audio-to-text, then a domain-tuned LLM for everything downstream).

**Vendor cloud APIs for medical ASR.** AWS Transcribe Medical, Google Cloud Healthcare's speech APIs, Microsoft Azure's healthcare-tuned speech services, Nuance Dragon Medical Cloud, and several specialized vendors offer cloud-hosted ASR specifically tuned for clinical vocabulary. These are the pragmatic choice for most institutional deployments: the model is maintained by the vendor, the accuracy is competitive with the best on-premise alternatives, the BAAs are in place, and the integration is handled through standard APIs. The trade-off is per-minute cost, network dependence, and vendor lock-in. <!-- TODO: verify; cloud-hosted clinical ASR vendor lineup continues to evolve, and feature parity across vendors shifts quarterly -->

For the rest of this recipe, we will treat the ASR layer as a domain-adapted speech recognizer with the following properties: it transcribes long-form clinical dictation with WER in the low single digits in good conditions, it returns per-word confidence scores, it supports custom vocabulary biasing, it supports speaker adaptation when given enough audio per clinician, and it is HIPAA-eligible under the relevant business associate agreement. The architectural pattern works regardless of whether the underlying implementation is a vendor's cloud API, a self-hosted Whisper variant, or a custom-trained model.

### Custom Vocabulary, Pronunciation, and Per-Clinician Adaptation

ASR accuracy on clinical vocabulary is the single highest-leverage knob in this recipe. Several techniques work, and most production deployments combine them.

**Custom vocabulary and biasing lists.** Most cloud ASR APIs accept a list of words or phrases the recognizer should be biased toward. For clinical dictation, this list includes the institution's formulary, the common procedure names for the practiced specialties, the names of providers and facilities, and any specialty-specific terminology that might be unusual. The biasing dramatically improves recognition of these terms; without it, even a clinically-tuned model will sometimes fall back to the closest non-medical word ("Wolff-Parkinson-White" might transcribe as "wolf parking white" if the model has not seen the eponymous syndrome enough times in training). <!-- TODO: verify; custom-vocabulary biasing is a well-established feature across cloud ASR providers, with implementation details varying -->

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

**LLM-driven formatting and structuring.** The 2024-2026 evolution: rather than rule-based formatters, run the verbatim transcript through a clinical LLM with a prompt that asks for the formatted note. The LLM handles punctuation, number formatting, header structuring, and even high-level reorganization (moving a sentence the clinician dictated out of order into the right section). The advantages: dramatically more flexible than rules, handles edge cases gracefully, can populate structured fields (medications, problems, allergies) into the right EHR slots while leaving narrative text for the human-readable note. The disadvantages: per-call cost, latency, and the standard LLM concern that the output may be a fluent reformulation rather than a faithful transcription. Production systems mitigate by treating the LLM output as a draft for clinician review, never as the final signed note. <!-- TODO: verify; LLM-driven post-processing of dictation transcripts is an active product area in 2024-2026 with multiple vendor implementations and ongoing accuracy and faithfulness research -->

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

```
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

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote critical-error
detection from prose into the architecture pattern. Add an explicit
critical-error-detection stage to the eight-stage decomposition (between
formatting and read-edit-sign, or as a parallel pass invoked from
read-edit-sign). Specify per-specialty high-risk-substitution catalogs
(laterality, negation, drug-name confusables, dose-by-order-of-magnitude)
as version-controlled clinical-safety documents owned by the
clinical-quality officer. Specify detection thresholds, severity tiers,
and the high-severity disposition (explicit clinician confirmation
required before signature). Add an aggregate detection-rate metric to
CloudWatch with named ownership and review cadence. The recipe's own
prose names this as "the single most important production gap"; the
architecture should match the prose. -->

**Voice commands and dictation content require unambiguous separation.** The boundary between content and commands is one of the highest-stakes design decisions in the recipe. Ambiguous decisions produce notes with command artifacts in them ("new paragraph" appearing as text in the note) or commands silently ignored (the clinician said "delete that sentence" but the system treated it as content). The recipes that handle this well use explicit modal switching (push-to-command, or a clear command prefix); the recipes that struggle use heuristic disambiguation that occasionally gets it wrong in obvious ways.

**Structured-field extraction is a draft, never a fact.** Extracting a medication-list update from a dictation and silently applying it to the patient's structured chart is dangerous. The clinician must explicitly confirm each structured-field change. The architecture treats extracted entities as suggestions, never as durable updates.

**Audit retention has to span the legal record's lifetime.** The note is part of the medical record and is retained for the longer of HIPAA's six-year minimum, the state's medical-records-retention floor, and the institution's policy. The audit trail (who dictated, who signed, what corrections were made between draft and signature) is part of the durable record.

**Failure has to degrade to a usable fallback.** When the ASR is unavailable, when the LLM post-processor is unavailable, when the EHR API is unreachable, the clinician must be able to fall back to typing or to a delayed-batch dictation workflow. A dictation system that completely blocks documentation when one component fails is one that gets uninstalled.

**Specialty differences are first-class.** A radiology dictation flow, a primary care visit-note flow, and an emergency department flow have different templates, different vocabulary distributions, different formatting conventions, and different clinician expectations. The architecture must support per-specialty configuration without forking the entire stack.

**Adoption depends on training and workflow integration as much as accuracy.** The metric that determines whether the system succeeds is sustained adoption at the three-month and six-month mark. Vendors and institutional teams that invest in clinician training, on-call support during early use, and per-specialty workflow tuning consistently see better adoption than vendors and teams that ship the technology and assume clinicians will figure it out.

---

## The AWS Implementation

### Why These Services

**Amazon Transcribe Medical for clinical-domain ASR.** Transcribe Medical is AWS's purpose-built clinical speech recognition service. It is trained on clinical audio with vocabulary distributions appropriate for medical dictation, supports streaming and batch modes, supports custom vocabularies for institutional formulary and specialty terms, and is HIPAA-eligible under BAA. For dictation specifically, it is the right default. The general-purpose Amazon Transcribe with a custom medical vocabulary is a viable alternative for institutions whose dictation patterns are heavily templated and lower in clinical-vocabulary density, but Transcribe Medical's specialty support (primary care, cardiology, neurology, oncology, radiology, urology) and its accuracy on medication and procedure terminology generally make it the better starting point. <!-- TODO: verify; the Transcribe Medical specialty list and BAA-eligibility coverage may have changed; confirm against the current Transcribe Medical documentation at build time -->

**Amazon Bedrock for LLM-driven formatting and structuring.** Bedrock-hosted foundation models provide the post-processing layer that turns verbatim Transcribe Medical output into a formatted, sectioned clinical note. The same Bedrock layer can extract structured-field suggestions (medications, problems, allergies) for clinician review. Choose a model with healthcare instruction tuning where available, validate against held-out reference notes for faithfulness (the formatted note must not paraphrase clinical content in ways that change meaning), and treat the LLM output as a draft for clinician review.

**Amazon Comprehend Medical for structured-entity extraction.** Comprehend Medical extracts medications (with RxNorm linking), conditions (with ICD-10 linking), anatomy, protected health information, and other clinical entities from text. It complements the LLM layer: the LLM handles general restructuring and formatting, Comprehend Medical handles canonical-coded entity extraction. For structured-field suggestions, Comprehend Medical's coded outputs are easier to integrate with EHR structured fields than free-form LLM output.

**AWS Lambda for orchestration.** The pipeline orchestration (initiate dictation session, route audio to Transcribe Medical, post-process with Bedrock and Comprehend Medical, hand off to EHR integration, capture user corrections, update adaptation telemetry) runs in Lambda functions. Per-stage isolation matches the pipeline structure and the per-stage retry semantics.

**Amazon API Gateway for the client-facing endpoint.** The dictation client (browser-based EHR plugin, native desktop app, mobile app) communicates with the back end through API Gateway. WebSocket APIs handle the streaming-audio path; REST APIs handle batch dictation submission and final note submission.

<!-- TODO (TechWriter): Networking review N1 (LOW). Add a WebSocket
Audio Streaming paragraph specifying connection-time authentication
(Lambda authorizer with the clinician's Cognito token), account-level
concurrent-connection limits with quota-increase as a deployment-time
activity, idle-timeout interaction with long-form dictation (consider
extending the idle timeout or implementing a keep-alive ping so a
clinician's pause does not drop the connection mid-dictation), and
the binary-message-type frame format. -->

<!-- TODO (TechWriter): Networking review N3 (LOW). Add a Device-to-
Cloud Transport Posture paragraph for the activation and audio capture
stage: TLS-encrypted WebSocket with institutional certificate pinning,
clinical-device VLAN network segmentation, and device-identity
authentication via mutual TLS or device certificates. Reference
institutional clinical-device-management ownership for per-device-fleet
certificate provisioning. -->

**Amazon Cognito (or institutional IdP via OIDC/SAML) for authentication.** Clinician identity is the audit-and-permissions backbone. The dictation session must be tied to an authenticated clinician, and the audit trail must reflect that identity through every stage.

**Amazon S3 for audio storage and audit archive.** Dictation audio is stored in S3 with SSE-KMS encryption using customer-managed keys. The retention policy is institutional and explicit: retain briefly for QA and adaptation, retain longer with consent for model retraining, or discard immediately after transcription. Audit archive (signed notes, correction streams, full dictation lifecycle records) lives in a separate S3 bucket with Object Lock in compliance mode for the legally-required retention window.

**Amazon DynamoDB for session state, dictation metadata, and per-clinician configuration.** A session-state table tracks active dictation sessions. A dictation-metadata table records the lifecycle of each dictation (started, transcribed, formatted, structured-fields-extracted, reviewed, signed). A per-clinician-config table holds custom vocabulary, preferred templates, macro definitions, and adaptation parameters. All tables encrypted with customer-managed KMS.

**Amazon ElastiCache or DynamoDB for per-clinician custom vocabulary lookup at session start.** Loading the per-clinician vocabulary biasing into the streaming Transcribe Medical session at the start of each dictation requires low-latency access to the clinician's current vocabulary configuration. Either ElastiCache (Redis) or DynamoDB with adequate provisioned capacity meets this need.

**AWS KMS for cryptographic-key custody.** Customer-managed KMS keys for the audio bucket, the audit bucket, the DynamoDB tables, and Secrets Manager. Different keys per data class (audio, transcripts, signed notes, configuration) for blast-radius containment.

**AWS Secrets Manager for EHR integration credentials.** The Lambda that hands the signed note off to the EHR needs credentials (SMART on FHIR backend-services signing keys, vendor-specific tokens). Secrets Manager stores them with rotation per the institutional cadence.

**Amazon CloudWatch for operational metrics and alarms.** Per-stage latency distributions, ASR confidence histograms, structured-field extraction acceptance rates, time-to-sign distributions, per-clinician adoption metrics, critical-error-detection alerts. Alarms on per-clinician error-rate spikes (a sudden change in correction rate for one clinician suggests an acoustic-condition change), aggregate ASR latency regressions, and EHR-integration failures.

**AWS CloudTrail for API-level audit.** All access to PHI-bearing resources (the audio bucket, the DynamoDB dictation tables, the audit archive, KMS keys, Secrets Manager) is logged. Lambda invocations, Bedrock invocations, Transcribe Medical streaming session starts and stops, Comprehend Medical inference calls all flow into CloudTrail.

**Amazon EventBridge for cross-system events.** Dictation lifecycle events (started, transcribed, signed, errored) flow through EventBridge. Downstream consumers (operational dashboards, the analytics layer, the per-clinician adaptation pipeline, the EHR integration) react to events without coupling to the orchestration Lambdas.

**AWS Step Functions for the dictation-to-signed-note workflow.** A typical dictation has multiple async stages between submission and signature. Step Functions orchestrate: ASR completion, LLM post-processing, structured-field extraction, hand-off to the EHR for clinician review, signature capture, and audit-archive write. The orchestration is durable and observable, with built-in retry and error-handling semantics.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena for analytics.** Audit and telemetry flow to S3 via Firehose. Glue catalogs the data. Athena provides SQL access for operational analytics (dictations per clinician per day, per-specialty accuracy trends, structured-field acceptance rates, time-to-sign distribution). Amazon QuickSight (optional) renders the dashboards.

**Amazon SageMaker (optional) for custom adaptation.** When per-clinician adaptation requires more than vocabulary-list updates (e.g., fine-tuning a custom acoustic model on a specific clinician's audio), SageMaker training jobs handle the model-training pipeline. SageMaker endpoints can serve per-clinician custom models if needed. For most institutions, the vocabulary-and-template adaptation handled within Transcribe Medical's customization features is sufficient and SageMaker is not required.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Client_Device
      MIC[Dictation microphone<br/>headset / handheld / mounted]
      PTD[Push-to-dictate]
      UI[EHR dictation plugin<br/>or desktop client]
    end

    subgraph Auth
      COGNITO[Amazon Cognito<br/>+ Institutional IdP]
      SOF[SMART on FHIR<br/>launch context]
    end

    subgraph Edge
      APIGW[API Gateway<br/>WebSocket + REST]
    end

    subgraph ASR_and_NLP
      TRANSMED[Amazon<br/>Transcribe Medical<br/>streaming + custom vocab]
      BEDROCK[Amazon Bedrock<br/>LLM formatter / structurer]
      COMPMED[Amazon<br/>Comprehend Medical<br/>structured entities]
    end

    subgraph Orchestration
      ORCH[Lambda<br/>session orchestrator]
      SF[Step Functions<br/>dictation workflow]
    end

    subgraph EHR_Integration
      EHR_HANDOFF[Lambda<br/>EHR handoff]
      FHIR[EHR FHIR API]
      VENDOR[Vendor-specific<br/>extension platform]
    end

    subgraph State_and_Audit
      DDB_SESS[(DynamoDB<br/>session state)]
      DDB_META[(DynamoDB<br/>dictation metadata)]
      DDB_CFG[(DynamoDB<br/>per-clinician config<br/>vocab + macros)]
      S3_AUDIO[(S3<br/>audio recordings<br/>SSE-KMS)]
      S3_AUDIT[(S3<br/>audit archive<br/>Object Lock)]
    end

    subgraph Events
      EB[EventBridge<br/>dictation-events bus]
    end

    subgraph Observability
      KIN[Kinesis Data<br/>Firehose]
      GLUE[Glue Data<br/>Catalog]
      ATH[Athena]
      QS[QuickSight]
      CW[CloudWatch<br/>metrics + alarms]
      CT[CloudTrail<br/>audit logs]
    end

    subgraph Adaptation
      SM_TRAIN[SageMaker<br/>per-clinician<br/>adaptation<br/>optional]
    end

    subgraph Secrets_and_Keys
      SM_SEC[(Secrets Manager<br/>EHR creds)]
      KMS[(AWS KMS<br/>customer-managed keys)]
    end

    MIC --> UI
    PTD --> UI
    UI --> COGNITO
    COGNITO --> APIGW
    UI --> SOF
    SOF --> APIGW
    UI --> APIGW
    APIGW --> ORCH
    ORCH --> SF
    ORCH --> DDB_SESS
    ORCH --> DDB_CFG
    SF --> TRANSMED
    TRANSMED --> S3_AUDIO
    SF --> BEDROCK
    SF --> COMPMED
    SF --> DDB_META
    SF --> EHR_HANDOFF
    EHR_HANDOFF --> SM_SEC
    EHR_HANDOFF --> FHIR
    EHR_HANDOFF --> VENDOR
    SF --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    SF --> CW
    TRANSMED --> CW
    BEDROCK --> CW
    COMPMED --> CW
    SF --> CT
    APIGW --> CT
    EB --> SM_TRAIN
    SM_TRAIN --> DDB_CFG
    KMS --> S3_AUDIO
    KMS --> S3_AUDIT
    KMS --> DDB_SESS
    KMS --> DDB_META
    KMS --> DDB_CFG
    KMS --> SM_SEC

    style TRANSMED fill:#fcf,stroke:#333
    style BEDROCK fill:#fcf,stroke:#333
    style COMPMED fill:#fcf,stroke:#333
    style DDB_SESS fill:#9ff,stroke:#333
    style DDB_META fill:#9ff,stroke:#333
    style DDB_CFG fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Transcribe Medical (streaming and batch), Amazon Bedrock, Amazon Comprehend Medical, AWS Lambda, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon EventBridge, AWS Step Functions, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally: Amazon SageMaker (for custom adaptation), Amazon QuickSight (for dashboards), Amazon ElastiCache (for low-latency vocabulary lookup). |
| **External Inputs** | EHR integration surface: SMART on FHIR app launch context (preferred), vendor-specific extension platform (Epic App Orchard, Cerner Code Console, etc.) for note creation and signing. Per-specialty note templates, reviewed by clinical operations. Institutional formulary, provider directory, and specialty-specific term lists for custom vocabulary. Per-clinician baseline configuration (specialty, default templates, initial macro library). Microphone hardware (headset, handheld dictation mic, or workstation mounted), procured and supported by IT operations. Validation set of dictated notes with reference transcripts for accuracy benchmarking, ideally per specialty. <!-- TODO: verify validation-set sourcing options; commercial dictation vendors typically have proprietary benchmarks, while open-source healthcare-speech datasets remain limited; check current sources at build time --> |
| **IAM Permissions** | Per-Lambda least-privilege roles. The session-orchestrator Lambda has scoped permissions for Transcribe Medical streaming session creation, Bedrock model invocation (specific model and inference profile), Comprehend Medical inference, the specific DynamoDB tables, and the EventBridge events bus. The EHR-handoff Lambda has scoped permissions for Secrets Manager (specific secret only), the EHR FHIR API endpoints, and the dictation-metadata table updates. API Gateway-to-Lambda integration with Cognito authorizer pinned to the clinician identity scope. Avoid wildcard actions and resources in production. <!-- TODO (TechWriter): Expert review S3 (MEDIUM). Specify the orchestrator Lambda's resource-based policy: pin the invoking principal to the production API Gateway stage ARN; reject invocations from any other API Gateway, stage, or principal; add a defense-in-depth event-payload validation that verifies requestContext.apiId against the production constant. --> |
| **BAA and Compliance** | AWS BAA signed. Transcribe Medical, Bedrock (verify the specific models and regions covered), Comprehend Medical, Lambda, API Gateway, Cognito, DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, CloudTrail, EventBridge, Step Functions, Kinesis Firehose, Athena, SageMaker are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference). <!-- TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continue to evolve --> <!-- TODO (TechWriter): Expert review A12 (LOW). Add a default-model recommendation for Bedrock (Claude family typical for healthcare due to longer-standing HIPAA-eligible-on-Bedrock track record) with the verify-at-build-time hedge; reference the AWS HIPAA Eligible Services Reference URL. --> EHR vendor agreements: confirm the EHR vendor's terms permit the dictation integration pattern (note creation, draft management, signature capture) with the appropriate scopes. Audio retention policy must be reviewed by the privacy officer; the institutional default should be conservative (retain briefly for QA only, then discard) unless there is explicit consent and operational need for longer retention. |
| **Encryption** | Audio recordings: SSE-KMS with customer-managed keys, retention bound to the QA review window (typically a few days to a few weeks for institutional adaptation feedback) then automatic deletion via lifecycle policy. <!-- TODO (TechWriter): Expert review A8 (MEDIUM). Specify the audio-retention configuration mechanism explicitly: retain-briefly with a 7-30-day window (KMS-encrypted, lifecycle-policy-deletion, access-logged through CloudTrail) as the recommended default; discard-immediately as the conservative alternative for institutions with strict PHI-minimization requirements; retain-longer requires explicit clinician consent at onboarding and a documented retention purpose. Reference the audit log (per Finding S1) as the long-term forensic-reconstruction substrate; audio retention is short-term QA-and-adaptation. --> Signed notes: stored in the EHR per its native encryption policy; if archived in S3 for backup, SSE-KMS with customer-managed keys. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institutional regulatory floor. DynamoDB tables: customer-managed KMS at rest. Lambda environment variables: KMS-encrypted. Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all AWS API calls and all EHR API calls (default). |
| **VPC** | Production: Lambdas that call back-office APIs (the EHR integration in particular) run in VPC with subnets that have controlled egress to the EHR's network (often a private peering connection or VPN to the on-premise EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, Comprehend Medical, and Transcribe Medical so the Lambdas do not need NAT for AWS-internal calls. Endpoint policies pin access to the specific resources the pipeline uses. For SMART on FHIR-based integrations against a cloud-hosted EHR, the integration may not require on-premise network connectivity; for on-premise EHRs, the network topology is typically the longest-lead-time portion of the deployment. <!-- TODO (TechWriter): Networking review N2 (LOW). Add PrivateLink-preferred-for-EHR-vendor-APIs framing; egress hierarchy is PrivateLink (preferred where available) > private peering / Direct Connect / Transit Gateway > VPN > public-Internet-with-TLS. --> |
| **CloudTrail** | Enabled with data events on the audio S3 bucket, the audit-archive S3 bucket, the DynamoDB dictation tables, the Secrets Manager secrets, and the customer-managed KMS keys. Lambda invocations logged. API Gateway access logs enabled. Step Functions execution logs enabled. Transcribe Medical streaming session starts and stops logged. Bedrock invocations logged with input and output captured per institutional policy (be cautious about input/output capture if the prompts or responses include PHI; many institutions choose to log metadata only). CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. Audit retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor. <!-- TODO (TechWriter): Expert review S4 (MEDIUM). Name the dictation-specific audit-log retention floor as the longest of HIPAA's six-year minimum, state-specific medical-records-retention rules (which for certain patient populations such as pediatric records can extend to age-of-majority-plus-multiple-years), the EHR vendor's audit-retention floor, the longest-retained signed note's retention period (the audit trail must outlive the signed note it documents), and the institutional regulatory floor. --> |
| **Sample Data** | Synthetic dictated audio for development. Text-to-speech generation of realistic clinical-text prompts produces audio with known ground truth. Synthea-generated patient context for the SMART on FHIR integration. Public clinical-vocabulary lists (RxNorm, ICD-10, SNOMED, LOINC) for custom-vocabulary seeding. Never use real clinician audio or real patient names in development; voice samples are biometric and PHI-bearing data with non-trivial governance implications. <!-- TODO: verify; public-domain dictated-clinical-text audio corpora are limited; common sources include the MIMIC-III dataset (text only) and select academic datasets, but most production benchmarks use proprietary data --> <!-- TODO (TechWriter): Expert review S5 (LOW). Add a Voice Biometric Data Governance paragraph specifying clinician consent at onboarding, separation of biometric retention from general dictation retention, per-clinician right-to-deletion, and cross-jurisdictional considerations (BIPA in Illinois, GIPA in Texas, similar state laws). Reference the institutional employment-and-compliance team for the per-jurisdiction policy. --> |
| **Cost Estimate** | At a mid-sized practice scale (200 clinicians, average 8 dictations per day per clinician, average 90 seconds of audio per dictation, 22 working days per month): Transcribe Medical streaming at typically $0.075 per minute totals approximately $4,000-5,000 per month. Bedrock LLM post-processing at typically $0.001-0.01 per dictation totals approximately $400-3,500 per month depending on model choice and prompt size. Comprehend Medical at typically $0.0014 per Unit (100 characters) totals approximately $200-500 per month. Lambda, Step Functions, API Gateway, DynamoDB, S3, CloudWatch, KMS, Secrets Manager total approximately $500-1,500 per month combined. Total AWS infrastructure typically $5,000-10,000 per month at this scale, dominated by Transcribe Medical. The infrastructure cost is comparable to or slightly cheaper than per-clinician licensing of major commercial dictation products at the same scale, though the engineering and operational overhead of operating a custom build is non-trivial and usually tilts the build-versus-buy economics toward buying for institutions of this size. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator. Specific costs depend on per-minute Transcribe Medical pricing in the chosen region and the chosen Bedrock model -->|

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Transcribe Medical** | Clinical-domain ASR with specialty support, custom vocabulary biasing, per-word confidence, streaming and batch modes |
| **Amazon Bedrock** | LLM-driven formatting, structuring, and section-aware reorganization of verbatim transcripts; faithfulness-checked draft note generation |
| **Amazon Comprehend Medical** | Coded clinical-entity extraction (RxNorm medications, ICD-10 conditions, anatomy, PHI) for structured-field suggestions |
| **AWS Lambda** | Per-stage processing: session orchestrator, ASR result handler, formatter wrapper, structured-field extractor wrapper, EHR handoff |
| **AWS Step Functions** | Durable orchestration of the dictation-to-signed-note workflow with retry and error-handling semantics |
| **Amazon API Gateway** | Client-facing endpoints for streaming audio (WebSocket) and dictation lifecycle (REST) with Cognito authorization |
| **Amazon Cognito** | Clinician authentication federated to the institutional identity provider |
| **Amazon DynamoDB** | session-state (active dictation per clinician); dictation-metadata (per-dictation lifecycle: started, transcribed, formatted, signed); per-clinician-config (custom vocabulary, macros, preferred templates, adaptation parameters) |
| **Amazon S3** | Audio recording storage with brief-retention lifecycle; audit archive with Object Lock |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing data stores |
| **AWS Secrets Manager** | EHR API credentials, SMART on FHIR backend-services signing keys |
| **Amazon CloudWatch** | Operational metrics (per-stage latency, ASR confidence distributions, correction rates, structured-field acceptance, time-to-sign); alarms (per-clinician error-rate spikes, latency regressions, EHR-integration failures, critical-error detections) |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing resources and AI/ML service invocations |
| **Amazon EventBridge** | dictation-events bus for cross-system event flow and downstream consumption |
| **Amazon Kinesis Data Firehose** | Streaming audit and telemetry delivery into S3 for long-term retention and analytics |
| **AWS Glue Data Catalog + Amazon Athena** | SQL access to audit and telemetry for operational analytics |
| **Amazon QuickSight (optional)** | Dashboards for clinical operations and IT operations |
| **Amazon SageMaker (optional)** | Per-clinician acoustic-model adaptation when vocabulary and template adaptation are insufficient |

---

### Code

#### Walkthrough

**Step 1: Open the dictation session and load per-clinician configuration.** The clinician initiates a dictation session from inside the EHR (or from a desktop dictation client). The system authenticates the clinician, loads the per-clinician custom vocabulary, the active note template, and the patient context (if any), and prepares a streaming Transcribe Medical session with the right specialty configuration. Skip the per-clinician vocabulary load and the ASR runs without the institutional formulary biasing, which immediately drops accuracy on the medications the clinician most commonly prescribes.

```
ON dictation_start_request(clinician_session, note_context):
    // Step 1A: validate the clinician session is current
    // and the SMART on FHIR launch context (if present) is
    // fresh.
    // TODO (TechWriter): Expert review A7 (MEDIUM). Specify the
    // SMART on FHIR token lifecycle for hours-long dictation
    // sessions: pre-emptive refresh window, refresh-failure handling
    // (graceful prompt for re-authentication on signature
    // submission), token storage in Secrets Manager with a short-
    // TTL cache rather than DynamoDB, and audit events on token-
    // lifecycle transitions. Dictation lifecycles can span hours
    // from start to EHR submission, so the architecture must handle
    // mid-workflow token expiry without losing dictated audio.
    IF NOT clinician_session.is_valid():
        RETURN error("re-authenticate")

    // Step 1B: load per-clinician configuration. This
    // includes the custom vocabulary list, the specialty,
    // the preferred template for this note type, and the
    // per-clinician macro library.
    clinician_config = clinician_config_table.get(
        clinician_id: clinician_session.clinician_id)

    // Step 1C: build the session-specific custom
    // vocabulary. Combine the institutional formulary, the
    // specialty-specific term list, the per-clinician
    // additions, and the patient-specific terms (current
    // medications, recent procedures) where the patient
    // context is known.
    custom_vocabulary = build_session_vocabulary(
        institutional: INSTITUTIONAL_FORMULARY,
        specialty: clinician_config.specialty_terms,
        per_clinician: clinician_config.custom_terms,
        patient_specific: load_patient_terms(
            note_context.patient_id) if note_context.patient_id else [])

    // Step 1D: select the note template. The template
    // determines the section structure of the formatted
    // note and the structured-field hooks.
    template = select_template(
        note_type: note_context.note_type,
        specialty: clinician_config.specialty,
        clinician_preference: clinician_config.preferred_templates)

    // Step 1E: open the streaming Transcribe Medical
    // session.
    transcribe_session = transcribe_medical.start_streaming(
        language_code: "en-US",
        media_sample_rate_hertz: 16000,
        specialty: clinician_config.specialty,
        // PRIMARYCARE | CARDIOLOGY | NEUROLOGY |
        // ONCOLOGY | RADIOLOGY | UROLOGY
        type: "DICTATION",
        // CONVERSATION for ambient (recipe 10.7);
        // DICTATION for this recipe
        vocabulary_name: custom_vocabulary.name,
        show_speaker_labels: false,
        // dictation is single-speaker; speaker labels
        // are off
        enable_partial_results_stabilization: true)

    // Step 1F: persist the session state.
    session_id = generate_uuid()
    session_state_table.put({
        session_id: session_id,
        clinician_id: clinician_session.clinician_id,
        note_context: note_context,
        template: template.id,
        custom_vocabulary: custom_vocabulary.name,
        transcribe_session: transcribe_session.id,
        started_at: now(),
        status: "active"
    })

    RETURN {
        session_id: session_id,
        websocket_endpoint: build_audio_websocket_url(
            session_id),
        template: template
    }
```

**Step 2: Stream audio to Transcribe Medical and capture the verbatim transcript.** The clinician dictates. Audio frames stream from the client over WebSocket through API Gateway into the Transcribe Medical streaming session. Partial transcripts emit as audio is processed; the final transcript emits at end-of-dictation. Capture per-word confidence for downstream review-pane highlighting. Skip the per-word confidence and the read-back view loses its single most useful affordance for catching ASR errors.

```
FUNCTION stream_audio_to_asr(session_id, audio_stream):
    session = session_state_table.get(session_id)
    transcribe_session = session.transcribe_session

    transcript_segments = []
    word_level_results = []

    // Step 2A: pump audio frames into Transcribe Medical
    // and emit partial transcripts back to the client
    // for live display.
    WHILE audio_stream.is_active():
        audio_frame = audio_stream.read_frame()
        IF audio_frame.is_end_of_stream:
            transcribe_session.end_stream()
            BREAK

        transcribe_session.send_audio_frame(audio_frame)

        partial = transcribe_session.next_partial_result()
        IF partial:
            client.emit_partial_to_client(
                session_id: session_id,
                text: partial.transcript,
                is_final: false)

        IF partial AND partial.is_final:
            transcript_segments.append(partial.transcript)
            // Per-word confidence and timing arrive on the
            // finalized segments.
            FOR word IN partial.words:
                word_level_results.append({
                    word: word.content,
                    start_time: word.start_time,
                    end_time: word.end_time,
                    confidence: word.confidence,
                    segment_index:
                        len(transcript_segments) - 1
                })
            client.emit_partial_to_client(
                session_id: session_id,
                text: partial.transcript,
                is_final: true)

    // Step 2B: combine segments into the full verbatim
    // transcript.
    verbatim_transcript = " ".join(transcript_segments)

    avg_confidence = mean([w.confidence for w in word_level_results]) if word_level_results else 0.0

    // Step 2C: persist the verbatim transcript and the
    // per-word details for the formatting and review
    // stages.
    // TODO (TechWriter): Expert review S1 (HIGH). Rewrite Step 2C
    // and Step 7C so PHI content (verbatim transcript, word-level
    // results, EHR API responses) lives in a secure transcript
    // archive (S3 with KMS, same governance as the audio bucket)
    // and only references, hashes, and structural metadata land in
    // dictation_metadata. The audit record at Step 8A already uses
    // archive references; the upstream working store must adopt the
    // same discipline. Add a cross-cutting design point on
    // references-not-content for all PHI-handling stages.
    dictation_metadata_table.put({
        session_id: session_id,
        verbatim_transcript: verbatim_transcript,
        word_level_results: word_level_results,
        avg_confidence: avg_confidence,
        transcribed_at: now(),
        status: "transcribed"
    })

    EventBridge.PutEvents([{
        source: "dictation",
        detail_type: "dictation_transcribed",
        detail: {
            session_id: session_id,
            avg_confidence: avg_confidence,
            duration_seconds:
                audio_stream.elapsed_seconds(),
            word_count: len(word_level_results)
        }
    }])

    RETURN {
        verbatim_transcript: verbatim_transcript,
        word_level_results: word_level_results,
        avg_confidence: avg_confidence
    }
```

**Step 3: Disambiguate commands from content and apply structural events.** Walk through the verbatim transcript and the timing-aligned word stream. Identify command phrases (the explicit prefix, or the configured command vocabulary) and route them to the system action handler; everything else is content. Apply navigation commands ("new paragraph," "next field," "go to assessment") to a structural-event log that the formatter will replay. Skip this step and command phrases either appear as literal text in the formatted note or get silently dropped without acting on the system, depending on which way the heuristic falls.

```
FUNCTION disambiguate_commands(verbatim_transcript, word_level_results, template):
    // Step 3A: tokenize the transcript into segments
    // separated by significant pauses (using word
    // start/end timing as the prosodic cue) or by
    // explicit punctuation.
    segments = segment_by_pauses(
        word_level_results,
        pause_threshold_seconds: COMMAND_PAUSE_THRESHOLD)

    content_segments = []
    structural_events = []

    FOR segment IN segments:
        segment_text = " ".join([w.word for w in segment])

        // Step 3B: check for explicit command prefix.
        IF segment_text.startswith(COMMAND_PREFIX):
            command_text = segment_text[len(COMMAND_PREFIX):]
            command = parse_command(command_text)
            structural_events.append({
                type: "command",
                command: command,
                segment_start: segment[0].start_time
            })
            CONTINUE

        // Step 3C: check for implicit command match
        // against the configured command vocabulary.
        // Only apply when the segment is the entire
        // segment (avoid matching command-like phrases
        // embedded in longer dictation).
        IF segment_text IN COMMAND_VOCABULARY:
            command = COMMAND_VOCABULARY[segment_text]
            structural_events.append({
                type: "command",
                command: command,
                segment_start: segment[0].start_time
            })
            CONTINUE

        // Step 3D: everything else is dictation content.
        content_segments.append({
            text: segment_text,
            words: segment,
            segment_start: segment[0].start_time
        })

    RETURN {
        content_segments: content_segments,
        structural_events: structural_events
    }
```

**Step 4: Format the verbatim content into the note template.** Apply punctuation inference, capitalization, number-and-date canonicalization, and section-header formatting. Optionally invoke a Bedrock LLM with a prompt that asks for the formatted note while preserving clinical content faithfulness. Render the formatted text into the note template, with each command-driven structural event directing content into the corresponding template field. Skip the faithfulness check on LLM output and the formatted note may paraphrase clinical content in ways that change meaning, which is the worst class of failure for this recipe.

```
FUNCTION format_and_structure(content_segments, structural_events, template, verbatim_transcript):
    // Step 4A: rule-based formatting pass. Punctuation
    // inference, capitalization, number-and-date
    // canonicalization. This pass handles the
    // mechanical conversions that LLMs are overkill
    // for and lower-latency is preferred.
    formatted_content = []
    FOR segment IN content_segments:
        formatted_text = apply_punctuation_inference(segment.text)
        formatted_text = apply_capitalization(formatted_text)
        formatted_text = canonicalize_numbers_and_dates(
            formatted_text)
        formatted_content.append({
            text: formatted_text,
            words: segment.words,
            segment_start: segment.segment_start
        })

    // Step 4B: apply structural events to direct content
    // into template sections. The cursor moves between
    // sections based on navigation commands; content
    // dictated between commands fills the section the
    // cursor is currently in.
    template_with_content = apply_structural_events(
        template: template,
        content: formatted_content,
        events: structural_events)

    // Step 4C: optional LLM post-processing for higher-
    // quality formatting and reorganization. The LLM
    // sees the verbatim transcript and the rule-based
    // draft; it returns a refined draft and a set of
    // structured-field suggestions. Treat the output
    // as a draft, never as authoritative.
    // TODO (TechWriter): Expert review S2 (MEDIUM). Specify
    // prompt-injection mitigation for the LLM formatter: wrap the
    // verbatim transcript in explicit delimiters
    // (e.g., <verbatim_transcript>...</verbatim_transcript>),
    // instruct the model to treat the transcript as untrusted user
    // data and not as instructions, request strict structured output
    // (JSON schema or XML tag boundaries) that the orchestrator
    // validates before accepting, and add prompt-injection
    // monitoring that flags structural divergence between the
    // LLM draft and the rule-based draft for operational review.
    // TODO (TechWriter): Expert review A6 (MEDIUM). Specify a
    // foundation-model-and-prompt versioning pattern: versioned
    // model identifiers, prompt versions, rule-catalog versions,
    // and per-specialty configuration versions in source control;
    // canary inference profile with traffic-shift; rollback-on-
    // regression gated by a held-out evaluation set with specialty,
    // accent, and high-risk-substitution coverage; version stamps
    // on every dictation audit record so a forensic review can
    // reconstruct which calibration produced a given note.
    IF LLM_POST_PROCESSING_ENABLED:
        llm_response = bedrock.invoke_model(
            model_id: CLINICAL_FORMATTER_MODEL,
            prompt: build_formatter_prompt(
                verbatim_transcript: verbatim_transcript,
                rule_based_draft: template_with_content,
                template_schema: template.schema,
                specialty: template.specialty),
            max_tokens: 4000)

        // Step 4D: faithfulness check. The LLM-formatted
        // note must contain the same clinical claims
        // as the verbatim transcript. Use a separate
        // model invocation (or a deterministic check)
        // to flag content drift. Discrepancies are
        // surfaced for clinician review; the LLM output
        // is never silently substituted for the rule-
        // based draft when faithfulness is suspect.
        // TODO (TechWriter): Expert review A3 (MEDIUM). Specify the
        // faithfulness-check architecture concretely: claim
        // extraction over verbatim transcript and LLM draft, claim-
        // by-claim semantic-equivalence comparison, severity-tier
        // classification of warnings (clinical-claim addition,
        // negation flip, dose change, hedging removal on a clinical
        // assertion as high-severity; minor stylistic divergence as
        // low-severity), high-severity-triggers-rule-based-fallback
        // disposition, and a paired offline Faithfulness Program
        // (held-out evaluation set per specialty, regression gate on
        // model updates, named ownership at the clinical-quality
        // officer). Cross-reference the critical-error-detection
        // primitive (Finding A1) and the prompt-injection mitigation
        // (Finding S2) as the recipe's combined LLM-clinical-safety
        // substrate.
        faithfulness_check = check_faithfulness(
            verbatim_transcript: verbatim_transcript,
            llm_draft: llm_response.formatted_note)

        IF faithfulness_check.passes:
            template_with_content = llm_response.formatted_note
        ELSE:
            // Fall back to the rule-based draft and
            // attach the LLM draft as a "suggested"
            // alternative for clinician comparison.
            template_with_content.llm_alternative =
                llm_response.formatted_note
            template_with_content.faithfulness_warnings =
                faithfulness_check.warnings

    RETURN template_with_content
```

**Step 5: Extract structured-field suggestions from the dictation.** Run Amazon Comprehend Medical (and optionally a Bedrock model with a structured-extraction prompt) over the verbatim transcript and the formatted note. Extract medications, problems, allergies, vitals, and procedures with coded references. Cross-check against the patient's structured chart and surface discrepancies. Skip this step and the dictation produces narrative text that never makes it into the structured chart, which is the entire reason the clinician was tempted to type it directly into the structured fields in the first place.

```
FUNCTION extract_structured_fields(verbatim_transcript, formatted_note, patient_context):
    // Step 5A: run Comprehend Medical to extract
    // coded clinical entities.
    // TODO (TechWriter): Expert review A11 (MEDIUM). The Comprehend
    // Medical API surface is split: detect_entities_v2 returns
    // categorized entities without ontology codes; infer_rx_norm,
    // infer_icd10_cm, and (where the institution stores SNOMED)
    // infer_snomed_ct return ontology-linked entities. Specify the
    // multi-call pattern explicitly with merge-by-character-offset
    // and update the cost estimate to reflect the multi-call
    // overhead. The pseudocode's lookup_rxnorm and lookup_icd10
    // helpers should be implemented as infer_rx_norm and
    // infer_icd10_cm calls in production.
    comp_med_result = comprehend_medical.detect_entities_v2(
        text: verbatim_transcript)

    // Comprehend Medical returns entities like:
    // { Type: "MEDICATION", Text: "lisinopril",
    //   Attributes: [{ Type: "DOSAGE", Text: "10 mg" },
    //                { Type: "FREQUENCY", Text: "daily" }],
    //   ... }
    // Plus RxNorm codes when InferRxNorm is called.

    medications = []
    conditions = []
    allergies = []

    FOR entity IN comp_med_result.entities:
        IF entity.category == "MEDICATION":
            // RxNorm linking via InferRxNorm or a
            // separate normalization step.
            rxnorm_code = lookup_rxnorm(entity.text)
            medications.append({
                source_text: entity.text,
                rxnorm_code: rxnorm_code,
                dosage: extract_attribute(entity, "DOSAGE"),
                frequency:
                    extract_attribute(entity, "FREQUENCY"),
                source_span: (entity.begin_offset,
                              entity.end_offset),
                confidence: entity.score
            })
        ELIF entity.category == "MEDICAL_CONDITION":
            icd10_code = lookup_icd10(entity.text)
            conditions.append({
                source_text: entity.text,
                icd10_code: icd10_code,
                negated:
                    has_negation_trait(entity),
                source_span: (entity.begin_offset,
                              entity.end_offset),
                confidence: entity.score
            })
        // Similarly for allergies, procedures, vitals.

    // Step 5B: cross-check against the patient's
    // structured chart. Highlight discrepancies.
    chart_meds = patient_context.medication_list
    chart_conditions = patient_context.problem_list
    chart_allergies = patient_context.allergy_list

    discrepancies = []

    FOR med IN medications:
        IF med.rxnorm_code NOT IN chart_meds_codes(
            chart_meds):
            discrepancies.append({
                type: "medication_mentioned_not_in_chart",
                source: med,
                action_suggested: "add_to_med_list"
            })

    FOR cond IN conditions:
        IF cond.negated:
            CONTINUE
        IF cond.icd10_code NOT IN chart_conditions_codes(
            chart_conditions):
            discrepancies.append({
                type: "condition_mentioned_not_in_chart",
                source: cond,
                action_suggested: "add_to_problem_list"
            })

    // Note: in a real deployment the cross-check is
    // more nuanced (medications discussed but not
    // prescribed, conditions ruled out vs newly
    // diagnosed). Treat the suggestions as draft
    // with explicit clinician confirmation.

    RETURN {
        medications: medications,
        conditions: conditions,
        allergies: allergies,
        discrepancies: discrepancies
    }
```

**Step 6: Render the read-edit-sign view and capture clinician corrections.** Show the formatted note to the clinician with low-confidence words highlighted, the LLM's tracked changes (when used) visible, structured-field suggestions in a side panel, and cross-check warnings flagged. The clinician edits, accepts or rejects structured-field suggestions, and signs. Capture every correction as an adaptation signal. Skip the correction-capture and the system never improves; clinicians see the same recurring errors month after month.

```
FUNCTION render_review_view(session_id, formatted_note, structured_suggestions, word_level_results):
    // Step 6A: build the review payload. Each word
    // tagged with its confidence; suggestions tagged
    // with their source span and provenance (rule-based
    // vs LLM vs Comprehend Medical).
    review_payload = {
        session_id: session_id,
        formatted_note: formatted_note,
        word_confidence_overlay:
            build_confidence_overlay(
                formatted_note,
                word_level_results),
        structured_suggestions: structured_suggestions,
        cross_check_warnings:
            structured_suggestions.discrepancies,
        llm_changes:
            formatted_note.llm_alternative_diff
                if formatted_note.has("llm_alternative_diff")
                else None
    }

    client.render_review(review_payload)

    // Step 6B: capture clinician corrections as they
    // happen. Each correction is an event with the
    // before/after text, the position, and any
    // structured-field accept/reject events.
    corrections = []
    structured_decisions = []

    WHILE NOT client.signature_received():
        event = client.next_review_event()
        IF event.type == "text_edit":
            corrections.append({
                before: event.before_text,
                after: event.after_text,
                position: event.position,
                timestamp: event.timestamp,
                source_word_confidences:
                    confidence_at_position(
                        event.position,
                        word_level_results)
            })
        ELIF event.type == "structured_suggestion_decision":
            structured_decisions.append({
                suggestion_id: event.suggestion_id,
                decision: event.decision,
                // accept | reject | modify
                modified_value:
                    event.modified_value
                        if event.decision == "modify"
                        else None
            })
        ELIF event.type == "voice_correction":
            // The clinician issued a voice correction
            // ("change last sentence to ..."). Run
            // through the disambiguation and formatting
            // layers.
            apply_voice_correction(event, formatted_note)
        ELIF event.type == "abandon":
            RETURN {
                signed: false,
                disposition: "abandoned",
                corrections: corrections,
                structured_decisions: structured_decisions
            }

    // Step 6C: signature event captured.
    signature = client.get_signature()

    RETURN {
        signed: true,
        signed_note: formatted_note,
        signature: signature,
        corrections: corrections,
        structured_decisions: structured_decisions
    }
```

**Step 7: Hand off the signed note to the EHR and apply confirmed structured updates.** Push the signed note into the EHR's note repository, apply the structured-field updates the clinician confirmed, capture the EHR's response (note ID, document ID), and update the dictation-metadata record with the final state. Treat structured-field updates with the same idempotency and audit rigor as any other clinical write. Skip the explicit confirmation handling and structured updates execute silently, which is the same anti-pattern as the read-write boundary in recipe 10.3 and produces the same class of harm.

```
FUNCTION handoff_to_ehr(session_id, signed_note, structured_decisions, patient_context, clinician_session):
    // Step 7A: create the note in the EHR.
    // TODO (TechWriter): Expert review A5 (MEDIUM). Specify the
    // idempotency-key composition for dictation submission:
    // (clinician_id, session_id, encounter_id, signature_timestamp).
    // The dictation-metadata table holds the recently-submitted-
    // notes list; on submission, the architecture checks for a
    // prior submission with the same key and returns the prior
    // note_id on match. Also prefer the FHIR API's idempotency
    // headers where the EHR vendor's API supports them. On
    // duplicate-detection, record both the original submission and
    // the duplicate-detection event in the audit.
    note_creation_response = fhir_client.create_note(
        patient_id: patient_context.patient_id,
        encounter_id: patient_context.encounter_id,
        author_id: clinician_session.clinician_id,
        note_type: signed_note.template.note_type,
        content: signed_note.formatted_text,
        signature: signed_note.signature,
        clinician_token: clinician_session.access_token)

    note_id = note_creation_response.note_id

    // Step 7B: apply confirmed structured updates.
    // Each accepted suggestion becomes a write to the
    // appropriate FHIR resource. Reject decisions are
    // logged but do not produce writes.
    structured_results = []
    FOR decision IN structured_decisions:
        IF decision.decision == "accept":
            IF decision.suggestion_type == "medication":
                result = fhir_client.add_medication(
                    patient_id: patient_context.patient_id,
                    medication_code: decision.rxnorm_code,
                    dosage: decision.dosage,
                    frequency: decision.frequency,
                    source_note_id: note_id,
                    clinician_token:
                        clinician_session.access_token)
                structured_results.append(result)
            ELIF decision.suggestion_type == "condition":
                result = fhir_client.add_condition(
                    patient_id: patient_context.patient_id,
                    condition_code: decision.icd10_code,
                    onset_date: decision.onset_date,
                    source_note_id: note_id,
                    clinician_token:
                        clinician_session.access_token)
                structured_results.append(result)
            // Similarly for allergies, procedures.
        ELIF decision.decision == "modify":
            // The clinician modified the suggestion
            // before accepting. Apply the modified value.
            ...

    // Step 7C: update the dictation-metadata record.
    dictation_metadata_table.put({
        session_id: session_id,
        ...
        note_id: note_id,
        structured_results: structured_results,
        signed_at: signed_note.signature.timestamp,
        status: "signed_and_handed_off"
    })

    RETURN {
        note_id: note_id,
        structured_results: structured_results
    }
```

**Step 8: Audit, archive, and feed adaptation.** Capture the full lifecycle of the dictation in the audit archive: the audio reference (under the institution's retention policy), the verbatim transcript reference, the formatted note, the structured-field suggestions and decisions, the corrections stream, the signature, and the EHR handoff result. Emit operational telemetry for the dashboards and per-clinician adaptation signals for the next dictation. Skip the audit and the institution cannot reconstruct what the system did during a clinical-quality review or during litigation.

```
FUNCTION audit_archive_and_adapt(session_id, signed_note, corrections, structured_decisions, ehr_handoff_result):
    metadata = dictation_metadata_table.get(session_id)

    // Step 8A: write the durable audit record. References
    // (not contents) for the audio and the verbatim
    // transcript; structural metadata captured for
    // forensic queries.
    audit_record = {
        session_id: session_id,
        clinician_id: metadata.clinician_id,
        patient_id:
            metadata.note_context.patient_id,
        encounter_id:
            metadata.note_context.encounter_id,
        note_id: ehr_handoff_result.note_id,
        dictation_started_at: metadata.started_at,
        signed_at: signed_note.signature.timestamp,
        audio_archive_ref: metadata.audio_s3_uri,
        verbatim_transcript_archive_ref:
            metadata.verbatim_archive_ref,
        verbatim_transcript_length_chars:
            len(metadata.verbatim_transcript),
        verbatim_avg_confidence:
            metadata.avg_confidence,
        formatted_note_archive_ref:
            metadata.formatted_archive_ref,
        formatted_note_length_chars:
            len(signed_note.formatted_text),
        asr_version: metadata.transcribe_medical_version,
        formatter_version: metadata.formatter_version,
        llm_model_id: metadata.llm_model_id_if_used,
        comprehend_medical_version:
            metadata.comprehend_medical_version,
        template_id: metadata.template,
        corrections_count: len(corrections),
        structured_suggestions_count:
            metadata.structured_suggestions_count,
        structured_accepted_count: count(
            structured_decisions,
            where: decision == "accept"),
        structured_rejected_count: count(
            structured_decisions,
            where: decision == "reject"),
        signature: signed_note.signature
    }

    audit_archive_kinesis_firehose.put(audit_record)

    // Step 8B: emit lifecycle event for downstream
    // consumers.
    EventBridge.PutEvents([{
        source: "dictation",
        detail_type: "dictation_signed",
        detail: {
            session_id: session_id,
            clinician_id: audit_record.clinician_id,
            specialty: metadata.specialty,
            note_id: audit_record.note_id,
            time_to_sign_seconds:
                (signed_note.signature.timestamp -
                 metadata.started_at).total_seconds(),
            corrections_count: len(corrections)
        }
    }])

    // Step 8C: feed corrections into the per-clinician
    // adaptation pipeline. Each correction (verbatim
    // word -> corrected word) is a training signal for
    // the per-clinician custom vocabulary and, when
    // applicable, for the per-clinician acoustic model
    // adaptation.
    // TODO (TechWriter): Expert review A4 (MEDIUM). Architect the
    // per-clinician adaptation pipeline beyond event publication:
    // default cadence (weekly batch for vocabulary, quarterly batch
    // for acoustic), default scope (vocabulary-only as institutional
    // default; acoustic adaptation as opt-in via SageMaker), held-
    // out per-clinician validation set with regression gate (5%
    // deterioration on per-clinician corrections-per-note or ASR
    // confidence triggers automatic rollback), per-clinician model
    // versioning, and a privacy-preserving aggregation pattern
    // (federated learning or differentially private aggregation)
    // for institution-wide vocabulary improvements that does not
    // leak per-clinician corrections.
    FOR correction IN corrections:
        adaptation_event = {
            clinician_id: audit_record.clinician_id,
            session_id: session_id,
            correction: correction,
            audio_segment_ref:
                build_audio_segment_ref(
                    audit_record.audio_archive_ref,
                    correction.position,
                    metadata.word_level_results)
        }
        adaptation_events_topic.publish(adaptation_event)

    // Step 8D: operational metrics.
    cloudwatch.put_metric(
        namespace: "Dictation",
        metric_name: "TimeToSignSeconds",
        value: audit_record.signed_at -
               metadata.started_at,
        dimensions: {
            specialty: metadata.specialty,
            note_type: metadata.note_context.note_type
        })
    cloudwatch.put_metric(
        namespace: "Dictation",
        metric_name: "CorrectionsPerNote",
        value: len(corrections),
        dimensions: {
            clinician_id: audit_record.clinician_id,
            specialty: metadata.specialty
        })
    cloudwatch.put_metric(
        namespace: "Dictation",
        metric_name: "ASRAvgConfidence",
        value: metadata.avg_confidence,
        dimensions: { specialty: metadata.specialty })
    // TODO (TechWriter): Expert review A2 (HIGH). Promote
    // cohort-stratified accuracy monitoring from prose into the
    // architecture pattern. Specify the cohort-dimensions allow-list
    // (per-clinician identifier as load-bearing axis, plus opt-in
    // language background, inferred accent group, specialty,
    // experience level, deployment site), per-cohort metrics
    // (corrections-per-note, time-to-sign, adoption rate,
    // abandonment rate, critical-error rate), per-cohort sample-size
    // minimums, and disparity-alert thresholds. Name ownership at
    // the equity-monitoring committee with monthly review cadence
    // and at the clinical-quality officer for critical-error-rate
    // cohort disparities. Use cohort-axis-hash labels for sensitive
    // dimensions in CloudWatch metrics; route demographic-stratified
    // analytics through Athena over the audit archive.
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.04-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample formatted note (illustrative):**

Verbatim ASR output:

> chief complaint comma chest pain period new paragraph history of present illness colon the patient is a fifty four year old male with a history of hypertension and hyperlipidemia who presents to the clinic today complaining of intermittent chest pain over the last two weeks period the pain is described as pressure like comma located in the substernal area comma rated five out of ten in severity comma and lasting approximately ten to fifteen minutes per episode period the pain is associated with exertion and relieved with rest period the patient denies shortness of breath comma diaphoresis comma nausea comma or radiation to the arm or jaw period new paragraph past medical history colon hypertension comma hyperlipidemia period new paragraph medications colon lisinopril ten milligrams po daily comma atorvastatin forty milligrams po nightly period

After rule-based and LLM-driven formatting:

```
**Chief Complaint:** Chest pain.

**History of Present Illness:**

The patient is a 54-year-old male with a history of
hypertension and hyperlipidemia who presents to the clinic
today complaining of intermittent chest pain over the last
two weeks. The pain is described as pressure-like, located
in the substernal area, rated 5/10 in severity, and lasting
approximately 10-15 minutes per episode. The pain is
associated with exertion and relieved with rest. The patient
denies shortness of breath, diaphoresis, nausea, or
radiation to the arm or jaw.

**Past Medical History:**

- Hypertension
- Hyperlipidemia

**Medications:**

- Lisinopril 10 mg PO daily
- Atorvastatin 40 mg PO nightly
```

**Sample structured-field suggestion (illustrative):**

```json
{
  "session_id": "dict-7e8f9a0b-1c2d-3e4f",
  "suggestions": [
    {
      "suggestion_id": "sug-1a2b3c4d",
      "type": "medication",
      "source_text": "lisinopril ten milligrams po daily",
      "source_span": [412, 446],
      "rxnorm_code": "29046",
      "rxnorm_display": "Lisinopril 10 MG Oral Tablet",
      "dosage": "10 mg",
      "route": "oral",
      "frequency": "daily",
      "extraction_confidence": 0.97,
      "in_chart": true,
      "action": "no_change_needed"
    },
    {
      "suggestion_id": "sug-2b3c4d5e",
      "type": "medication",
      "source_text": "atorvastatin forty milligrams po nightly",
      "source_span": [448, 488],
      "rxnorm_code": "83367",
      "rxnorm_display": "Atorvastatin 40 MG Oral Tablet",
      "dosage": "40 mg",
      "route": "oral",
      "frequency": "at bedtime",
      "extraction_confidence": 0.95,
      "in_chart": false,
      "action": "add_to_med_list"
    },
    {
      "suggestion_id": "sug-3c4d5e6f",
      "type": "condition",
      "source_text": "intermittent chest pain over the last two weeks",
      "source_span": [180, 227],
      "icd10_code": "R07.9",
      "icd10_display": "Chest pain, unspecified",
      "extraction_confidence": 0.84,
      "negated": false,
      "in_chart": false,
      "action": "review_for_problem_list"
    }
  ]
}
```

**Sample audit record (illustrative):**

```json
{
  "session_id": "dict-7e8f9a0b-1c2d-3e4f",
  "clinician_id": "user-jdoe",
  "patient_id": "pt-44219-3c",
  "encounter_id": "enc-2026-05-23-1422",
  "note_id": "doc-99b8a7c6",
  "dictation_started_at": "2026-05-23T14:22:08Z",
  "signed_at": "2026-05-23T14:25:47Z",
  "audio_archive_ref": "s3://dictation-audio-bucket/2026/05/23/dict-7e8f9a0b.flac",
  "verbatim_transcript_archive_ref": "s3://dictation-archive-bucket/transcripts/2026/05/23/dict-7e8f9a0b.txt",
  "verbatim_transcript_length_chars": 1247,
  "verbatim_avg_confidence": 0.93,
  "formatted_note_archive_ref": "s3://dictation-archive-bucket/notes/2026/05/23/dict-7e8f9a0b.md",
  "formatted_note_length_chars": 1389,
  "asr_version": "transcribe-medical-2026-q1",
  "formatter_version": "rule-formatter-v3.2 + bedrock-claude-3-haiku-20240307",
  "comprehend_medical_version": "comprehend-medical-2024-12",
  "template_id": "primary-care-followup-v2",
  "corrections_count": 3,
  "structured_suggestions_count": 5,
  "structured_accepted_count": 3,
  "structured_rejected_count": 2,
  "time_to_sign_seconds": 219,
  "signature": {
    "type": "electronic",
    "method": "password",
    "timestamp": "2026-05-23T14:25:47Z"
  }
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Typing baseline | Voice dictation |
|--------|-----------------|-----------------|
| Median time per note (primary care visit) | 8-15 minutes | 3-5 minutes |
| Median time per note (radiology read) | 4-8 minutes | 1-2 minutes |
| Median time per note (operative note) | 20-40 minutes | 8-15 minutes |
| Median time per note (emergency department) | 12-20 minutes | 5-8 minutes |
| Word error rate, prepared dictation, quiet environment | n/a | 2-5% |
| Word error rate, on-the-fly dictation, busy environment | n/a | 5-10% |
| Critical error rate (laterality, negation, drug-name) | n/a | 0.05-0.5% |
| Median per-note correction count | n/a | 3-12 |
| Per-note AWS infrastructure cost | n/a | $0.02-0.10 |
| Sustained adoption at six months among trained clinicians | n/a | 50-90% (highly variable by specialty and rollout quality) |

<!-- TODO: replace illustrative figures with measured results from the deployment. The ranges above are typical for medical-dictation deployments but vary substantially with vendor choice, specialty, clinician training, and integration depth -->

**Where it struggles:**

- **Underrepresented accents and speech patterns.** Clinicians whose accents are not well-represented in the ASR's training data see meaningfully higher word error rates than their colleagues. Mitigations: per-clinician acoustic adaptation (the system improves over time as the clinician uses it), per-clinician custom vocabulary, vendor evaluation across the institution's clinician demographics, subgroup-stratified accuracy monitoring with alerts on disparities.
- **Drug names and rare clinical terms.** Even with custom vocabulary biasing, eponymous syndromes and rare drugs are recognized inconsistently. Mitigations: aggressive vocabulary expansion based on production transcripts, per-specialty term lists curated by clinical operations, and faithfulness checking on LLM post-processing to catch the rare-term mistranscriptions the LLM might gracefully paper over.
- **Sound-alike substitutions in safety-critical terms.** "Hypertension" vs "hypotension," "left" vs "right," "no" vs "not," "with" vs "without," "increase" vs "decrease," "morphine" vs "naloxone." These pairs are acoustically close enough that ASR systems sometimes confuse them; the clinical impact of the confusion is large. Mitigations: critical-error detection (rule-based or model-based) flags the highest-risk substitutions for explicit clinician confirmation; review-pane highlighting draws clinician attention to terms in the configured high-risk list.
- **Long, run-on dictations.** When a clinician dictates for several minutes without pausing, the punctuation-and-paragraph inference is more error-prone, and the LLM post-processor has more material to potentially paraphrase incorrectly. Mitigations: encourage natural pauses (clinician training), explicit dictation of section transitions ("new paragraph"), and faithfulness checks scaled to dictation length.
- **Voice commands embedded in clinical content.** "Period" can be a punctuation command or content (in obstetric or gynecologic notes). "New paragraph" can be content (in a description of a published article structure). Mitigations: explicit command prefix or push-to-command modal switching, context-aware command parsing, and clinician-visible feedback when a phrase was interpreted as a command.
- **Acoustic environments.** A radiology reading room is a controlled, quiet environment optimized for dictation. An emergency department is the opposite. The same dictation system performs differently in each. Mitigations: environment-appropriate microphones (close-talking headsets in noisy environments), noise-robust ASR variants where available, per-environment acoustic-condition monitoring with alerts when audio quality drops below configured thresholds.
- **Faithfulness drift in LLM post-processing.** The LLM may "improve" a clinician's awkward phrasing in ways that subtly change clinical meaning. The clinician dictates "the patient may have had a small stroke," and the LLM produces "the patient had a small stroke." The hedging is removed; the clinical claim is now stronger than what the clinician said. Mitigations: faithfulness checks against the verbatim transcript, conservative LLM prompts that explicitly preserve hedging and uncertainty, clinician review-pane diff visualization showing the LLM's changes against the verbatim source.
- **Structured-field extraction errors.** Comprehend Medical and similar tools occasionally misidentify entities, miss negation, or extract dosages incorrectly. Mitigations: explicit clinician confirmation for every structured-field update, conservative cross-check thresholds, no silent updates to the structured chart, and explicit display of the source span for each suggestion so the clinician can verify the dictated origin.
- **Co-signature and amendment workflows.** Trainee dictations co-signed by attendings, late addenda after a note is signed, and corrections to signed notes are workflows that require careful design. Mitigations: explicit support for multi-signer workflows in the integration layer, dedicated addendum dictation entry points, and audit trails that capture the full chain of authorship and revision.
- **Vendor lock-in and switching cost.** Per-clinician custom vocabulary, personal macros, and accumulated adaptation are valuable assets that are typically not portable between dictation vendors. Mitigations: institutional ownership of the custom-vocabulary lists where possible, periodic export of clinician-customized assets to institutionally-controlled storage, and contractual provisions requiring data portability.
- **Adoption decay.** Even successful pilots can see declining sustained adoption if the system has rough edges that compound over time. Mitigations: ongoing monitoring of per-clinician usage trends, on-call support during the early weeks of broader deployment, scheduled refresh training, and rapid response to clinician-reported issues.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Critical-error detection with named ownership.** The single most important production gap is explicit detection of clinically-significant errors: laterality flips (left vs right), negation flips (no vs not, denies vs endorses, with vs without), drug-name confusions (look-alike sound-alike pairs), and dose-by-order-of-magnitude errors (5 mg vs 50 mg). Build the detection as a rule-based or model-based filter over the verbatim transcript and the formatted note. Surface detections in the review pane with explicit clinician confirmation required. Track aggregate detection rates and drift over time. Assign named ownership to the clinical-quality officer or equivalent role; the detection list is a living clinical safety document, not an engineering configuration.

**Per-clinician adaptation pipeline.** The user-correction events from the read-edit-sign workflow are the training signal that improves accuracy over time. Build the pipeline that captures corrections, attributes them, and feeds them into per-clinician custom-vocabulary updates. Decide explicitly whether per-clinician acoustic-model adaptation (via SageMaker training jobs) is in scope; for most institutions, vocabulary-only adaptation is sufficient and acoustic adaptation is a later phase. Document the adaptation cadence (continuous, daily batch, weekly batch) and the validation steps that prevent a single clinician's idiosyncratic corrections from degrading their personal model.

**Subgroup-stratified accuracy monitoring with disparity alerts.** Voice ASR systematically underperforms for some speaker demographics. Per-clinician accuracy metrics (verbatim ASR confidence, correction rate, time-to-sign) should be visible to the equity-monitoring committee or the clinical-quality officer. Disparities exceeding configured thresholds should alert. The monitoring is not optional analytics; it is the mechanism by which the institution detects whether the system is silently underserving specific clinicians (and, by extension, their patients). Cohort dimensions should include per-clinician identifier, per-clinician language background (where opt-in declared at onboarding), inferred accent group, specialty, experience level, and deployment site.

**LLM post-processor faithfulness program.** When the LLM is in the formatting path, faithfulness drift is a structural risk. Build an ongoing program that: maintains a held-out evaluation set of verbatim-and-faithful-formatted note pairs across specialties; runs the post-processor against the evaluation set on every model update; flags regressions with clinical-impact tier classification; gates production model updates on regression results. The faithfulness check at runtime (Step 4D in the pseudocode) is necessary but not sufficient; the offline program is the second line of defense.

**Voice-command vocabulary review and versioning.** The set of voice commands the system recognizes is a clinical-safety artifact. Treat it with version control, change review by clinical operations (not by the engineering team unilaterally), scheduled refresh cadence, and a documented escalation path when a misexecution surfaces. Track command-execution telemetry (which commands are used, which fail, which produce unintended actions) and feed it into the review.

**Specialty-specific tuning programs.** A radiology dictation flow, an emergency-medicine flow, and a primary-care flow have different vocabulary distributions, different formatting conventions, and different clinician expectations. Build the configuration so per-specialty tuning is first-class: specialty-specific custom vocabularies, specialty-specific note templates, specialty-specific LLM prompts, specialty-specific critical-error rules. Pilot per specialty rather than across the institution, and pilot before broader rollout.

**EHR integration depth and breadth.** The pseudocode handles note creation and structured-field updates. Production deployments typically need more: co-signature workflows for trainees, late-addendum support, integration with order entry (so a dictated medication suggestion can be drafted as a CPOE order for the clinician to review and sign separately), and integration with billing-code suggestion engines. Each integration point requires the same explicit-confirmation rigor as the structured-field updates above.

**Audio retention policy with privacy-officer review.** The default architecture retains audio briefly for QA and adaptation. Production deployment requires explicit privacy-officer review of the retention duration, the access controls on retained audio, the consent disclosure to clinicians (whose voice biometric data is being retained), and the deletion verification. Some institutions choose discard-immediately; some keep audio longer for model retraining. The choice should be documented and reviewed annually.

**Disaster recovery and partial-failure handling.** When Transcribe Medical is unavailable, when Bedrock is unavailable, when the EHR API is unreachable, the dictation system must degrade gracefully. Test the failure modes in a staging environment. Document the fallback behavior the clinician should expect in each failure mode (e.g., "if real-time transcription fails, the system will offer batch transcription on retry; you can also fall back to typing"). The clinician should never lose dictated audio because of a downstream component failure.

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Promote disaster
recovery from production-gaps prose into the architecture pattern: a
Disaster Recovery Topology subsection with per-stage failover policy
(Transcribe Medical regional outage with cross-region failover or
batch-mode fallback, Bedrock model unavailability with rule-based
formatter fallback, Comprehend Medical unavailability with manual
structured-field-entry fallback, EHR API unreachable with signed-note-
queue-for-retry that preserves the signed note), failover-detection
and failover-back triggers, and quarterly DR-test cadence. -->

**Idempotency and retry semantics.** A dictation submitted twice (because of a network blip, or because the clinician thought the system did not receive it) must not produce two notes in the EHR. Idempotency keys per dictation session, conditional writes on the EHR side where supported, and explicit duplicate-detection logging are required.

**Performance under load and burst.** The latency budget for streaming dictation is tight; the system must hold the budget under load. Transcribe Medical streaming session limits, Bedrock invocation throughput, EHR API rate limits, all need provisioning headroom. Load test before launch; reserve concurrency where the latency-sensitive Lambdas would otherwise be starved.

**Specialty-specific training and rollout playbook.** The single best predictor of whether a dictation deployment succeeds is the quality of clinician training and rollout. Build the per-specialty playbook: who attends training, what the training covers (system mechanics, custom-vocabulary management, macro authoring, voice-command vocabulary), who provides on-call support during the first weeks, what the success criteria are at one month and three months, what the rollback criteria are if the metrics do not move. The playbook is operational scope, not engineering scope, but the engineering team has to support it (training environments, sandbox dictations, telemetry visibility for the on-call team).

**Vendor evaluation rigor for build-vs-buy decisions.** Most institutions deploying medical dictation should be buying a commercial product, not building one. The recipe describes the architecture for the buy-and-integrate path or the careful-custom-build path. Either way, the institution needs a rigorous vendor evaluation program: per-specialty accuracy benchmarking against held-out audio, evaluation of the read-edit-sign workflow, evaluation of the custom-vocabulary management, evaluation of the EHR integration depth, evaluation of the per-clinician adaptation behavior, and reference checks with comparable institutions running the same product. A custom build that cannot match the major commercial vendors on these axes is the wrong call.

**Audit log retention and legal hold.** The dictation audit log is the durable record of voice-driven note creation. Retention must meet HIPAA's six-year minimum, state medical-records-retention rules, and the EHR vendor's audit-retention floor (so the two records can be cross-referenced during forensic reconstruction). Legal hold capabilities (the ability to suspend deletion for specific clinicians or patients during litigation) must be configurable.

**Cost monitoring per clinician and per specialty.** Different clinicians use the system at very different rates; different specialties have very different per-note costs (a radiologist dictating fifty reports a day is structurally different from a primary-care physician dictating fifteen). Per-clinician and per-specialty cost dashboards let operations identify outliers and tune accordingly.

**Operational ownership.** The system sits at the intersection of clinical operations (custom vocabulary, templates, command vocabulary, training), IT (infrastructure, EHR integration), clinical informatics (mapping dictation patterns to EHR structures), and compliance (audit retention, BAA scope, audio retention policy). Establish clear ownership at the start. Without it, the system drifts and the metrics are not reviewed.

---

## The Honest Take

Medical dictation is the most established voice product category in healthcare. The technology works. Clinicians have been using it for decades. The vendor landscape is mature. The accuracy benchmarks are well-understood. And, having said all of that, building a dictation system that genuinely improves the clinician's day, with the rigor that the clinical-safety implications demand, is harder than the maturity of the field suggests.

The first trap is treating dictation as a solved problem and skipping the investment in deployment quality. The technology is mature. The deployment quality is not. A dictation deployment that ships with an out-of-the-box vendor configuration, an hour of clinician training, and no per-specialty tuning will see modest adoption, mediocre accuracy, and disappointing time savings. A dictation deployment that ships with curated custom vocabulary, per-specialty templates, named clinician champions, structured training, and on-call support during the first weeks will see substantially better outcomes. The difference between the two deployments is engineering and operational investment, not technology choice. The institutions that succeed treat dictation as a workflow project that uses speech recognition; the institutions that struggle treat it as a speech-recognition project that has some workflow.

The second trap is over-relying on overall accuracy metrics. A 96% word accuracy sounds excellent until you realize that 96% accuracy on a thousand-word note means forty errors, some of which are in clinically-meaningful terms. The metric that matters is critical-error rate, not WER. A dictation system with 92% WER and a tightly-managed critical-error rate is safer than one with 97% WER and no critical-error tracking. The vendor benchmarks usually report WER; the institutional benchmarks should add critical-error rate as a primary axis. The dictation systems that have been deployed for years and never had a serious clinical-safety incident are the ones with explicit critical-error detection; the ones that have had incidents typically did not.

A third trap is assuming the LLM post-processing is an unmitigated good. LLM-driven formatting is genuinely useful. It is also a faithfulness risk that the architecture has to actively manage. The clinician dictates "may have," and the LLM produces "had." The clinician dictates "intermittent," and the LLM smooths it to "occasional." The clinical claim is now subtly different. In aggregate, these small drifts accumulate into a class of failure that is invisible at the individual-note level but real at scale. The faithfulness check (Step 4D in the pseudocode) is not an optional optimization; it is a structural requirement. Run the verbatim transcript and the LLM-formatted note through a faithfulness-comparison pass before treating the LLM output as the canonical draft. When in doubt, fall back to the rule-based draft and surface the LLM version as a "suggested alternative." This is not paranoia; it is the design discipline that distinguishes careful clinical software from confident-but-occasionally-hallucinating consumer software. The faithfulness program is one of the highest-leverage investments in this recipe and the easiest to underweight.

A fourth trap is underinvesting in disambiguation between voice commands and dictation content. The boundary between "delete that sentence" as a command and "delete that sentence" as content is real, and the systems that handle it badly produce notes with command artifacts in them ("new paragraph" appearing literally) or commands silently ignored. Modern systems with explicit command prefixes (or push-to-command modal switches) handle this reasonably well; legacy systems that rely on phrase-matching heuristics still occasionally surprise people. When evaluating vendor products or building custom, this is a question to interrogate explicitly: how does the system distinguish commands from content, and what is the failure mode when it gets it wrong? "It mostly works" is not a satisfactory answer.

A fifth trap is failing to plan for the per-specialty tuning that mature deployments require. The dictation patterns of a primary care physician, a radiologist, and an emergency medicine physician are dramatically different. A single institution-wide configuration optimized for one specialty produces mediocre results for the others. The configuration architecture must support per-specialty templates, per-specialty custom vocabularies, per-specialty LLM prompts, and per-specialty critical-error rules. Pilot per specialty. Roll out per specialty. Monitor per specialty. The institutions that try to ship a single configuration across the entire clinical staff routinely see one or two specialties succeed wildly and the rest underperform.

A sixth trap is skipping the build-vs-buy analysis. Most institutions should be buying a commercial dictation product, not building a custom one. The recipe describes the architecture either way; the recipe does not endorse the build path for institutions that have not done the analysis carefully. Commercial vendors (Nuance Dragon Medical, M-Modal/3M, Dolbey, vendor-bundled offerings from Epic and Cerner) have absorbed an enormous engineering investment over decades, including custom acoustic models, deep EHR integration, per-specialty optimization, and per-clinician adaptation pipelines. Matching that investment from scratch is a multi-year effort. Custom builds make sense in specific niches: unusual specialty use cases poorly served by commercial products, languages with no commercial offering, on-premise-only deployments where the network architecture forbids cloud ASR, research contexts where the model and the data flow are research artifacts in their own right. For a typical institutional deployment serving a typical clinical staff, buy.

The thing that surprises engineers coming from consumer-voice-assistant backgrounds is how much of the engineering value is in formatting and template integration, not in speech recognition. Good ASR is table stakes; the differentiated value is in turning the ASR output into a formatted clinical note with the right section structure, the right vocabulary normalization, the right structured-field suggestions, and the right read-edit-sign workflow. The engineering team that obsesses over ASR accuracy and ships a mediocre formatting layer ships a product clinicians do not adopt. The engineering team that ships solid-but-not-state-of-the-art ASR with a great formatting and review experience ships a product clinicians use every day.

The thing that surprises engineers coming from EHR-integration backgrounds is how acoustic considerations dominate the deployed accuracy. The microphone hardware, the room acoustics, the clinician's speaking habits, all matter as much as the ASR model. A poor microphone in a noisy environment with a tired clinician produces bad audio that produces bad ASR that produces bad formatting that produces a note the clinician spends ten minutes correcting. Investing in good microphone hardware (close-talking headsets for power users, beamforming workstation mics for general use, handheld dictation mics for radiologists and pathologists who prefer them) and the room conditions where dictation happens yields more accuracy improvement than the same investment in the model layer.

The thing about Amazon Transcribe Medical specifically: it is a competent baseline for clinical-domain ASR. The specialty-specific tuning (PRIMARYCARE, CARDIOLOGY, NEUROLOGY, ONCOLOGY, RADIOLOGY, UROLOGY) covers the largest deployment volumes; specialties outside that list use the closest specialty configuration plus aggressive custom vocabulary. The streaming variant hits the latency budget for front-end dictation reliably. The accuracy on prepared dictation in good conditions is genuinely strong; the accuracy under field conditions varies more, as it does for every cloud ASR vendor. <!-- TODO: verify; the Transcribe Medical specialty list and accuracy characteristics continue to evolve -->

The thing about Amazon Bedrock specifically: the LLM-driven formatting and structuring is genuinely valuable, with the faithfulness caveats already covered. Choose a model with healthcare instruction tuning where available; validate against held-out reference notes; treat output as draft. The cost of LLM post-processing is meaningful but small compared to the per-clinician productivity gain when it works.

The thing about Amazon Comprehend Medical specifically: it is the right tool for coded clinical-entity extraction. The RxNorm linking, the ICD-10 linking, the negation detection are all solid. The accuracy varies with the kind of clinical text; performance on dictated narrative is generally good but not perfect, and the structured-field suggestions should always be presented for clinician confirmation rather than applied silently.

The thing about per-clinician adaptation: it is the highest-leverage long-term investment in the deployment. A clinician who has used the system for six months sees substantially better accuracy than a fresh deployment. The adaptation pipeline that captures user corrections and feeds them back into the per-clinician vocabulary and acoustic profile is what transforms "dictation that mostly works" into "dictation the clinician relies on." Build the pipeline early; the longer the system runs without adaptation, the longer the per-clinician accuracy stays at the day-one baseline.

The thing about audio retention: this is the single most contentious privacy decision in the architecture. The privacy officer wants discard-immediately. The ML engineering team wants retain-for-model-improvement. The clinical-quality team wants retain-briefly-for-QA-review. Each has legitimate points. The default in this recipe is brief retention (seven to thirty days) with KMS-encrypted storage, access logged through CloudTrail, and a lifecycle policy for automatic deletion. Longer retention requires explicit clinician consent at onboarding and a documented purpose for retention. The decision is institutional and should be revisited annually.

The thing I would do differently the second time: budget more, earlier, for clinician training and on-call support during early use. Every successful dictation deployment I have seen has invested heavily in this. Per-specialty rollouts, named clinician champions, on-call engineering support during the first weeks, scheduled refresh training at three months, and a feedback channel that clinicians actually use. The deployments that skip this investment and assume the system will sell itself through pure productivity gain consistently underperform. The system is good. Clinicians using the system effectively is a different thing.

The last thing, because it is the easiest one to get wrong: medical dictation produces clinical documentation that becomes the legal record. A misrecognized word in a signed note is a clinical-safety event, a billing-compliance event, and potentially a litigation event. The system's job is not just to make dictation fast; it is to make sure the signed note accurately reflects the clinical encounter. The critical-error detection, the faithfulness checking, the explicit-confirmation rigor for structured-field updates, the read-edit-sign workflow that makes errors easy to catch, all serve this purpose. A dictation system that optimizes for speed at the expense of accuracy ships a product that produces unreliable clinical records at scale. A dictation system that takes the safety rigor seriously ships a product that clinicians and institutions can stand behind.

---

## Variations and Extensions

**Specialty-specific subdialect tuning.** Beyond Transcribe Medical's built-in specialty types, deeper tuning is possible: a custom-trained acoustic model for an underserved specialty (e.g., dermatology, ophthalmology, vascular surgery), specialty-specific vocabulary lists curated by domain experts, specialty-specific note templates with embedded macros, and specialty-specific LLM prompts. The architectural extension is the per-specialty configuration management and the per-specialty validation pipeline.

**Multilingual dictation.** Add support for Spanish, French, Mandarin, or other languages relevant to the institution's clinician demographics. Per-language Transcribe Medical configurations (where supported), per-language custom vocabularies, per-language LLM prompts, per-language formatting and structuring rules. Even within a single language, regional variants matter (US English vs UK English vs Indian English clinical vocabulary differs in non-trivial ways). <!-- TODO (TechWriter): Expert review A10 (MEDIUM). Specify the per-language pipeline pattern as build-for-day-one even when shipping English-first: per-clinician language declared at onboarding; per-language Transcribe Medical configuration and custom vocabulary; per-language LLM-formatter prompts; per-language formatting rules. The configuration scaffolding should not assume a single language at the architecture level. -->

**Front-end versus back-end dictation modes.** The architecture above defaults to front-end (real-time streaming with the words appearing as the clinician dictates). Some clinicians prefer back-end (dictate the full note, then review the transcript later, with possible human QA in between). The architecture supports both modes through the same Transcribe Medical service (streaming and batch), with different orchestration paths through Step Functions and different review-pane UX.

**Voice-driven order entry, with explicit non-voice confirmation.** A natural extension is using dictation patterns to draft CPOE orders for clinician review. The clinician dictates "I want to order a CBC and a basic metabolic panel and a chest x-ray two views"; the system extracts the orders, presents them for explicit non-voice confirmation, and (on confirmation) drafts the orders in the EHR for the clinician to sign separately. The architectural extension is the order-extraction prompt, the EHR's order-entry API integration, and the explicit-confirmation flow that mirrors the structured-field-update pattern. The same caveats from recipe 10.3 about the read-write boundary apply here: voice-driven order draft creation is acceptable; voice-driven order signature is not.

**Ambient-and-dictation hybrid workflow.** When ambient documentation (recipe 10.7) is also deployed, clinicians can use ambient during the encounter and dictation afterward for supplementary detail (the assessment and plan that the ambient system did not capture cleanly). The architectural extension is the inter-product context-sharing API and the unified review-and-sign workflow that combines ambient-generated content and dictation content into a single signed note.

**Real-time clinical-decision-support hooks during dictation.** As the clinician dictates clinical content, the system can fire CDS alerts in real time: "you are dictating about chest pain; here are the relevant clinical-decision-support suggestions"; "you are dictating about a medication that interacts with the patient's current medications; here is the interaction warning." The architectural extension is the CDS Hooks integration and the careful UX that surfaces alerts without disrupting the dictation flow.

**Voice-driven note correction after signing.** A clinician sometimes wants to correct or amend a previously-signed note. The amendment workflow is a distinct dictation type that produces an addendum (a new, dated, signed document linked to the original); the original signed note is never modified. The architectural extension is the addendum dictation workflow and the audit trail that captures the chain of original-and-addendum.

**Per-clinician acoustic-model adaptation.** Beyond per-clinician custom vocabulary, full per-clinician acoustic-model adaptation can be implemented via SageMaker training jobs that fine-tune a base acoustic model on the clinician's accumulated audio. This is a substantial engineering investment but produces meaningful accuracy gains for clinicians whose accents are underrepresented in the vendor's general training data. Most institutions can defer this until the broader deployment is mature.

**LLM-driven note quality scoring.** Beyond formatting, an LLM can evaluate the dictated note for documentation quality (completeness against the encounter type, billing-code support, regulatory compliance for the specialty's standards) and surface gaps for the clinician to address before signing. The architectural extension is the quality-scoring prompt and the review-pane UX that integrates the scoring with the existing review affordances.

**Voice biomarker overlay.** As an experimental extension, the dictation audio can be analyzed for voice biomarkers (clinician fatigue, stress indicators) for institutional wellness monitoring. The privacy implications are substantial; the deployment must be opt-in, anonymized, and reviewed by clinical operations and the privacy officer. This is in the far end of variations, listed for completeness but not recommended for default deployment.

**Dictation-driven documentation auto-completion.** As the clinician dictates, the system can predict the rest of common phrases and offer auto-completion. "The patient is a fifty-four-year-old male with a history of..." prompts a list of likely continuations from the clinician's previous notes for similar patients. The architectural extension is the per-clinician phrasing model and the careful UX that suggests without disrupting flow.

**Cross-institutional anonymized model improvement.** With appropriate consent and de-identification, dictation transcripts and corrections can contribute to industry-wide model improvement. The architectural extension is the privacy-preserving aggregation pipeline (differential privacy or federated learning) and the institutional governance that authorizes the data sharing. This is rarely the right starting point but is a long-term direction for the field.

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

## Additional Resources

**AWS Documentation:**
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Transcribe Medical Specialty Types](https://docs.aws.amazon.com/transcribe/latest/dg/specialty.html)
- [Amazon Transcribe Streaming Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html)
- [Amazon Transcribe Custom Vocabulary](https://docs.aws.amazon.com/transcribe/latest/dg/custom-vocabulary.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon Comprehend Medical InferRxNorm](https://docs.aws.amazon.com/comprehend-medical/latest/dev/ontology-rxnorm.html)
- [Amazon Comprehend Medical InferICD10CM](https://docs.aws.amazon.com/comprehend-medical/latest/dev/ontology-icd10.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon API Gateway WebSocket APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api.html)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-transcribe-streaming-app`](https://github.com/aws-samples/amazon-transcribe-streaming-app): streaming Transcribe integration patterns useful for dictation audio capture
- [`aws-samples/amazon-transcribe-streaming-medical-python-clients`](https://github.com/aws-samples/amazon-transcribe-streaming-medical-python-clients): Python streaming client patterns for Transcribe Medical
- [`aws-samples/amazon-comprehend-medical-samples`](https://github.com/aws-samples/amazon-comprehend-medical-samples): medical-entity extraction patterns including RxNorm and ICD-10 linking
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including structured-output extraction and prompt engineering
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): broader healthcare AI/ML sample notebooks; check for relevant clinical-text and speech examples
<!-- TODO: confirm the current names and locations of these repos at time of build; the AWS sample repo organization changes over time -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences plus AI/ML): browse for healthcare-voice and clinical-documentation reference architectures
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "Transcribe Medical," "clinical documentation," "EHR integration" for relevant case studies and deep dives
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "Transcribe Medical," "Comprehend Medical," "Bedrock healthcare" for relevant pattern posts
<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs -->

**External References (Standards and Frameworks):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model and API substrate for modern EHR integration
- [SMART on FHIR](https://docs.smarthealthit.org/): the launch-context and authorization specification for clinically-aware EHR apps
- [FHIR DocumentReference Resource](https://www.hl7.org/fhir/documentreference.html): the canonical FHIR resource for clinical-document references including signed notes
- [FHIR Composition Resource](https://www.hl7.org/fhir/composition.html): the canonical FHIR resource for composed clinical documents
- [FHIR Provenance Resource](https://www.hl7.org/fhir/provenance.html): the canonical FHIR resource for capturing authorship and revision history
- [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/index.html): the standard medication terminology used by Comprehend Medical's RxNorm linking
- [ICD-10-CM](https://www.cdc.gov/nchs/icd/icd10cm.htm): the standard diagnosis terminology used by Comprehend Medical's ICD-10 linking
- [SNOMED CT](https://www.snomed.org/): the standard clinical terminology often used in modern EHR structured fields
- [LOINC](https://loinc.org/): the standard for laboratory and clinical observation codes
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in dictation audio, transcripts, and signed notes
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards for ePHI access channels
- [Joint Commission documentation standards](https://www.jointcommission.org/): clinical-documentation requirements relevant to dictated notes <!-- TODO: confirm specific URL at time of build -->

**Industry Resources:**
- [AMA STEPS Forward: Reducing the Documentation Burden](https://edhub.ama-assn.org/steps-forward): industry-association content on the EHR-documentation-burden problem that this recipe addresses <!-- TODO: confirm specific URL at time of build -->
- [JAMIA (Journal of the American Medical Informatics Association)](https://academic.oup.com/jamia): peer-reviewed research on speech recognition in clinical workflows, dictation accuracy, and clinical-documentation quality <!-- TODO: confirm current URL at time of build -->
- [HIMSS resources on clinical documentation and EHR usability](https://www.himss.org/): industry-association content on clinical-documentation systems <!-- TODO: confirm specific URL at time of build -->

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single-EHR integration (one vendor's FHIR API, SMART on FHIR launch), single-language (English), single specialty (e.g., primary care or radiology), Transcribe Medical streaming with built-in specialty configuration, basic custom vocabulary, simple rule-based formatting (no LLM post-processing), no structured-field extraction, basic read-edit-sign workflow, single-device pilot with 5-10 clinicians | 3-5 months |
| Production-ready | Multi-specialty support with per-specialty templates and custom vocabularies, full Transcribe Medical streaming and batch modes, LLM post-processing with faithfulness checking, Comprehend Medical structured-field extraction with explicit clinician confirmation, full read-edit-sign workflow with low-confidence highlighting and tracked changes, critical-error detection with named ownership, per-clinician custom vocabulary and adaptation pipeline, full HIPAA-grade audit with EHR-side audit-overlay integration, subgroup-stratified accuracy monitoring, structured clinician training and rollout playbook, on-call support for the first weeks of broader deployment | 9-15 months |
| With variations | Per-clinician acoustic-model adaptation via SageMaker, voice-driven order-draft creation with explicit non-voice confirmation, multi-language support, ambient-and-dictation hybrid workflow integration, real-time CDS Hooks integration during dictation, multi-EHR-vendor support, addendum and co-signature workflows, LLM-driven note quality scoring | 6-12 months beyond production-ready |

---

## Tags

`speech-voice-ai` · `medical-dictation` · `medical-transcription` · `front-end-dictation` · `back-end-dictation` · `clinical-documentation` · `domain-adapted-asr` · `transcribe-medical` · `streaming-asr` · `batch-asr` · `custom-vocabulary` · `per-clinician-adaptation` · `voice-commands` · `note-template` · `formatting` · `structured-field-extraction` · `comprehend-medical` · `rxnorm-linking` · `icd10-linking` · `bedrock-formatting` · `faithfulness-check` · `critical-error-detection` · `read-edit-sign` · `clinician-signature` · `ehr-integration` · `smart-on-fhir` · `specialty-tuning` · `radiology-dictation` · `pathology-dictation` · `ed-dictation` · `bedrock` · `lambda` · `step-functions` · `api-gateway` · `cognito` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `quicksight` · `sagemaker` · `medium` · `production-track` · `hipaa` · `phi-handling` · `audit-trail` · `equity-monitoring` · `clinician-burden-reduction` · `pajama-time`

---

*← [Recipe 10.3: Voice-to-Text for EHR Navigation](chapter10.03-voice-to-text-ehr-navigation) · [Chapter 10 Index](chapter10-index) · [Recipe 10.5: Patient-Facing Voice Assistant](chapter10.05-patient-facing-voice-assistant) →*
