# Healthcare AI/ML Cookbook — Phase 1: Category Framework

**Status:** In Progress  
**Last Updated:** 2026-02-23

## AI/ML Categories for Healthcare

Below are the core AI/ML pattern categories applicable to healthcare use cases. Each category includes a brief description, typical healthcare applications, and key considerations.

---

### 1. Document Intelligence / OCR

**What it is:** Extracting structured data from unstructured documents — scanned forms, faxes, handwritten notes, PDFs.

**Healthcare relevance:** Healthcare runs on paper. Faxes are still the #1 interoperability mechanism. Every system integration eventually hits a document extraction problem.

**Typical applications:**
- Prescription/Rx ingestion
- Patient intake form digitization
- Prior authorization document processing
- Medical records migration (legacy paper → EHR)
- Insurance claim document extraction
- Handwritten clinical notes transcription

**Key considerations:**
- PHI everywhere — every document likely contains it
- Handwriting recognition accuracy varies wildly by provider
- Multi-page documents with mixed formats (tables, checkboxes, free text)
- Confidence scoring critical for human-in-the-loop workflows

---

### 2. LLM / Generative AI

**What it is:** Large language models for text generation, summarization, Q&A, reasoning, and conversation.

**Healthcare relevance:** Clinical documentation is drowning providers. LLMs offer the first real hope for reducing documentation burden while improving quality.

**Typical applications:**
- Clinical documentation assistance (ambient listening → notes)
- Patient communication (portal messages, appointment reminders)
- Medical literature summarization
- Prior authorization letter generation
- Clinical decision support (evidence retrieval)
- Patient education content generation

**Key considerations:**
- Hallucination risk is life-safety critical in healthcare
- Must cite sources / ground in evidence
- PHI in prompts requires careful architecture
- Regulatory uncertainty (FDA, liability)
- Model freshness vs. medical knowledge cutoff dates

---

### 3. Anomaly Detection

**What it is:** Identifying outliers, unusual patterns, or deviations from expected behavior in data streams.

**Healthcare relevance:** Early detection saves lives. Whether it's a patient deteriorating, a billing anomaly indicating fraud, or a supply chain disruption.

**Typical applications:**
- Patient deterioration early warning (vitals, labs)
- Fraud/waste/abuse detection in claims
- Medication error detection
- Readmission risk flagging
- Equipment failure prediction (IoT/biomed)
- Outbreak/epidemic detection

**Key considerations:**
- False positive fatigue is real (alert overload)
- Baseline establishment requires clean historical data
- Seasonality and population drift affect thresholds
- Real-time vs. batch detection trade-offs

---

### 4. Personalization / Recommendation

**What it is:** Tailoring content, actions, or suggestions to individual users based on their characteristics and behavior.

**Healthcare relevance:** Every patient is different. One-size-fits-all care plans, communications, and interventions leave value on the table.

**Typical applications:**
- Care plan recommendations
- Patient engagement optimization (channel, timing, content)
- Provider matching (specialty, location, availability)
- Medication therapy optimization
- Wellness program recommendations
- Content personalization (education, reminders)

**Key considerations:**
- Cold start problem (new patients)
- Bias in historical data → biased recommendations
- Explainability requirements for clinical recommendations
- A/B testing in healthcare has ethical constraints

---

### 5. Entity Resolution / Record Linkage

**What it is:** Determining when two records refer to the same real-world entity (person, provider, organization) despite variations in how they're recorded.

**Healthcare relevance:** Fragmented data is healthcare's original sin. Patients exist across dozens of systems with different IDs, name spellings, addresses.

**Typical applications:**
- Master Patient Index (MPI) matching
- Provider identity resolution (NPI, credentialing)
- Duplicate record detection and merge
- Cross-system patient matching (HIE, TEFCA)
- Family/household linkage
- Claims-to-clinical data linkage

**Key considerations:**
- False matches can be catastrophic (wrong patient's meds)
- False non-matches fragment care
- Name variations, typos, demographic changes over time
- Probabilistic vs. deterministic matching trade-offs
- Privacy-preserving matching (can't always share PII)

---

### 6. Cohort Analysis / Clustering / Similarity

**What it is:** Grouping entities (patients, providers, facilities) based on shared characteristics to enable population-level insights and personalized approaches.

**Healthcare relevance:** Understanding "patients like this one" unlocks evidence-based care, risk stratification, and resource allocation.

**Typical applications:**
- Patient risk stratification (rising risk, high utilizers)
- Treatment response prediction (patients similar to this one)
- Provider peer comparison (quality, efficiency)
- Disease subtype discovery
- Clinical trial patient matching
- Resource allocation (staffing, beds, equipment)

**Key considerations:**
- Feature selection drives everything — domain expertise required
- Cluster interpretation requires clinical validation
- Population drift over time
- Small N problems in rare conditions

---

### 7. Predictive Analytics / Risk Scoring

**What it is:** Using historical data to predict future outcomes — events, costs, behaviors, clinical trajectories.

**Healthcare relevance:** Proactive > reactive. Knowing who's likely to deteriorate, readmit, or disengage allows intervention before it's too late.

**Typical applications:**
- Readmission risk prediction
- No-show prediction
- Length of stay estimation
- Disease progression modeling
- Cost forecasting
- Mortality risk (acuity scoring)
- Churn/disenrollment prediction

**Key considerations:**
- Model drift as care patterns change
- Fairness/bias auditing critical (disparate impact)
- Clinical actionability — predictions without interventions are useless
- Calibration matters as much as discrimination (AUC isn't everything)

---

### 8. Natural Language Processing (non-LLM)

**What it is:** Traditional NLP techniques — NER, classification, sentiment, extraction — without generative models.

**Healthcare relevance:** Clinical text is dense with entities, relationships, and signals. Structured extraction enables downstream analytics.

**Typical applications:**
- Clinical entity extraction (medications, diagnoses, procedures)
- ICD/CPT code suggestion
- Sentiment analysis (patient feedback, reviews)
- Social determinants extraction from notes
- Adverse event detection in clinical text
- Problem list reconciliation

**Key considerations:**
- Medical terminology and abbreviations are domain-specific
- Negation detection is critical ("no chest pain")
- Context matters (historical vs. current, patient vs. family)
- Pre-trained models need healthcare fine-tuning

---

### 9. Computer Vision / Medical Imaging

**What it is:** Analyzing images and video to detect, classify, segment, or measure visual features.

**Healthcare relevance:** Radiology, pathology, dermatology, ophthalmology — imaging is core to diagnosis. AI augments (doesn't replace) expert interpretation.

**Typical applications:**
- Radiology triage (stroke, PE, pneumothorax)
- Pathology slide analysis
- Dermatology lesion classification
- Retinal disease screening (diabetic retinopathy)
- Surgical video analysis
- Wound assessment

**Key considerations:**
- FDA regulatory pathway (510(k), De Novo, PMA)
- Integration with PACS/imaging workflows
- Edge vs. cloud processing (latency, bandwidth)
- Explainability (where did the model look?)
- Training data diversity (demographics, equipment variations)

---

### 10. Speech / Voice AI

**What it is:** Converting speech to text, understanding spoken commands, analyzing voice characteristics.

**Healthcare relevance:** Hands-free documentation, accessibility, and voice biomarkers for health assessment.

**Typical applications:**
- Ambient clinical documentation
- Voice-enabled EHR navigation
- Patient IVR / voice assistants
- Speech therapy assessment
- Voice biomarkers (depression, Parkinson's, respiratory)
- Accessibility accommodations

**Key considerations:**
- Accuracy with medical terminology
- Accents, dialects, multilingual support
- Background noise in clinical environments
- Speaker diarization (who said what)
- Real-time vs. batch processing

---

### 11. Conversational AI / Virtual Assistants

**What it is:** Multi-turn dialog systems that understand intent, maintain context, and complete tasks through conversation.

**Healthcare relevance:** Patient access, triage, scheduling, and FAQ handling at scale without adding staff.

**Typical applications:**
- Symptom checkers / triage bots
- Appointment scheduling
- Prescription refill requests
- Benefits/eligibility inquiries
- Chronic disease management coaching
- Mental health support (with appropriate guardrails)

**Key considerations:**
- Escalation to humans must be seamless
- Scope containment (don't let it give medical advice it shouldn't)
- Multilingual support
- Integration with backend systems (EHR, scheduling)
- Conversation logging and PHI handling

---

### 12. Time Series Analysis / Forecasting

**What it is:** Analyzing sequential data points over time to detect patterns, forecast future values, or identify regime changes.

**Healthcare relevance:** Vital signs, lab trends, disease progression, operational metrics — healthcare generates continuous streams of time-indexed data.

**Typical applications:**
- Patient monitoring (ICU, remote patient monitoring)
- Demand forecasting (ED volume, bed census)
- Lab trend analysis
- Medication response tracking
- Epidemic curve modeling
- Revenue cycle forecasting

**Key considerations:**
- Irregular sampling (vitals not taken at fixed intervals)
- Missing data handling
- Seasonality (flu season, day-of-week patterns)
- Real-time alerting thresholds

---

### 13. Knowledge Graphs / Ontology

**What it is:** Representing entities and relationships as interconnected nodes and edges, enabling semantic queries and reasoning.

**Healthcare relevance:** Medicine is fundamentally about relationships — drugs interact, diseases relate, anatomies connect. Graphs make these explicit.

**Typical applications:**
- Drug-drug interaction checking
- Clinical pathway navigation
- Diagnosis differential generation
- Care gap identification
- Clinical trial matching
- Provider/facility network analysis

**Key considerations:**
- Ontology maintenance is ongoing work
- Integration with standard terminologies (SNOMED, RxNorm, LOINC)
- Query performance at scale
- Versioning and provenance

---

### 14. Optimization / Operations Research

**What it is:** Mathematical optimization of resource allocation, scheduling, routing, and planning under constraints.

**Healthcare relevance:** Healthcare operations are constrained optimization problems — staff, rooms, equipment, time slots, all with complex dependencies.

**Typical applications:**
- OR/procedure scheduling
- Staff scheduling and shift optimization
- Patient flow optimization
- Supply chain / inventory optimization
- Ambulance routing
- Appointment slot optimization

**Key considerations:**
- Constraint complexity (union rules, certifications, preferences)
- Uncertainty handling (emergencies disrupt plans)
- Multi-objective trade-offs (cost vs. access vs. quality)
- Human override and fairness perceptions

---

### 15. Reinforcement Learning

**What it is:** Learning optimal actions through trial-and-error interaction with an environment, maximizing cumulative reward.

**Healthcare relevance:** Treatment is sequential decision-making under uncertainty. RL offers a framework for optimizing dynamic treatment regimens.

**Typical applications:**
- Dynamic treatment regimens (sepsis, diabetes)
- Personalized dosing (chemotherapy, warfarin)
- Clinical trial adaptive designs
- Resource allocation under uncertainty
- Patient engagement optimization

**Key considerations:**
- Safety constraints (can't explore recklessly with patients)
- Simulation environments for offline learning
- Reward function design is critical and hard
- Regulatory acceptance is nascent

---

## Categories Considered but Excluded

- **Robotics / Surgical Automation** — Important but highly specialized; outside cookbook scope
- **Genomics / Precision Medicine** — Deserves its own deep treatment; may add as advanced section
- **Blockchain / Distributed Ledger** — Not ML/AI; occasionally adjacent but not core

---

## Next Steps

1. ✅ Complete category framework (this document)
2. ⏳ Generate 5-10 use cases per category (simple → complex)
3. ⏳ Select initial batch for detailed architecture write-ups
4. ⏳ Review with CC before deep-diving

---

*Last updated: 2026-02-23 by techwriter-researcher*
