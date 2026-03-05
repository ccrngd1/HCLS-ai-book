# Category 10: Speech / Voice AI

**Healthcare Use Cases — Simple → Complex**

---

## 10.1 IVR Call Routing Enhancement (Simple)

**What:** Improve automated phone system routing by understanding natural language intent ("I need to refill my prescription") instead of requiring menu selections.

**Why simple:** Bounded intent vocabulary. Routing errors recoverable (transfer to agent). Abundant training data from call logs. Low clinical risk.

---

## 10.2 Voicemail Transcription and Classification (Simple)

**What:** Transcribe patient voicemails and classify by urgency/type (medication question, appointment request, clinical concern) for staff routing.

**Why simple:** Async processing acceptable. Classification aids triage, not clinical decisions. Transcription quality is good for clear recordings. Human review follows.

---

## 10.3 Voice-to-Text for EHR Navigation (Simple-Medium)

**What:** Enable voice commands for EHR navigation and simple data entry ("Open patient John Smith," "Show last labs").

**Why this complexity:** Must integrate with specific EHR. Command vocabulary must be learned. Ambient noise in clinical settings. User training required. Hands-free efficiency gain.

---

## 10.4 Medical Transcription (Dictation) (Medium)

**What:** Convert physician dictation into formatted clinical notes with medical terminology accuracy.

**Why medium:** Specialty-specific vocabulary. Must handle accents and speaking styles. Formatting templates vary. Established market with accuracy benchmarks. Integration with documentation workflow.

---

## 10.5 Patient-Facing Voice Assistant (Medium)

**What:** Voice-enabled assistant for patients to check appointments, request refills, get directions, or answer common questions.

**Why medium:** Must be accessible across ages and abilities. Handle diverse accents and speech patterns. Scope containment important. Telephony integration for non-app users.

---

## 10.6 Speech-to-Text for Telehealth Documentation (Medium)

**What:** Transcribe telehealth visits in real-time for documentation support and visit summarization.

**Why medium:** Two-party conversation requires diarization. Video call audio quality varies. Real-time display for review. Must handle interruptions and crosstalk.

---

## 10.7 Ambient Clinical Documentation (Complex)

**What:** Passively capture in-person clinical conversations and generate structured documentation (HPI, assessment, plan).

**Why complex:** Multi-speaker diarization with movement. Must distinguish clinical content from small talk. Real-time or near-real-time. Privacy considerations (who consented?). Workflow integration critical. Emerging competitive market.

---

## 10.8 Voice Biomarker Detection (Complex)

**What:** Analyze voice characteristics to detect or monitor health conditions (respiratory issues, neurological changes, mental health).

**Why complex:** Requires clinical validation for each indication. Biomarker science still developing. Regulatory pathway unclear for most uses. Must distinguish signal from normal variation.

---

## 10.9 Speech Therapy Assessment and Monitoring (Complex)

**What:** Analyze patient speech for therapy assessment — articulation, fluency, voice quality metrics for diagnosis and progress tracking.

**Why complex:** Clinical-grade accuracy required. Must work with impaired speech (the target population). Therapist workflow integration. Longitudinal comparison for progress. Pediatric and adult variations.

---

## 10.10 Multilingual Real-Time Medical Interpretation (Complex)

**What:** Provide real-time spoken language interpretation for clinical encounters, with medical terminology accuracy.

**Why complex:** Must handle medical vocabulary in multiple languages. Real-time latency constraints. Liability for interpretation errors. Must preserve clinical nuance. Competes with human interpreters.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Real-time requirements | Latency constraints are hard |
| Speaker diarization | Multi-party audio adds complexity |
| Medical vocabulary | Domain-specific language models needed |
| Accent/dialect coverage | Must work for diverse populations |
| Clinical validation | Biomarkers need rigorous evidence |
| Regulatory exposure | Diagnostic claims trigger FDA |

---

*Category 10 complete. Next: Category 11 (Conversational AI / Virtual Assistants)*
