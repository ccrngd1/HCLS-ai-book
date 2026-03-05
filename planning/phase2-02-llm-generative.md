# Category 2: LLM / Generative AI

**Healthcare Use Cases — Simple → Complex**

---

## 2.1 Patient Message Response Drafting (Simple)

**What:** Draft responses to routine patient portal messages (appointment questions, medication refill requests, general inquiries) for staff review before sending.

**Why simple:** Low clinical risk for routine messages. Human always reviews before send. Narrow scope per message. Easy to constrain tone/length.

---

## 2.2 Medical Terminology Simplification (Simple)

**What:** Rewrite clinical text (discharge instructions, lab results, procedure descriptions) into patient-friendly language at appropriate reading level.

**Why simple:** Transformation task, not generation. Source text provides guardrails. Output is educational, not clinical decision. Easy to validate with readability scores.

---

## 2.3 Clinical Documentation Improvement (CDI) Suggestions (Simple-Medium)

**What:** Analyze physician notes and suggest clarifications, specificity improvements, or missing documentation for accurate coding.

**Why this complexity:** Must understand coding rules and clinical context. Suggestions only — humans decide. Lower risk since it's about documentation, not care. Requires integration with coding workflows.

---

## 2.4 Prior Authorization Letter Generation (Medium)

**What:** Generate medical necessity letters for prior auth submissions using patient clinical data, payer requirements, and clinical guidelines.

**Why medium:** Must synthesize multiple data sources. Output must be persuasive and clinically accurate. Payer-specific requirements vary. Stakes are coverage approval, not direct patient harm.

---

## 2.5 After-Visit Summary Generation (Medium)

**What:** Generate personalized, readable summaries of clinical encounters including diagnoses discussed, medications changed, follow-up instructions, and next steps.

**Why medium:** Must accurately reflect encounter content. Patient-facing output. Requires grounding in actual documentation. Errors could cause confusion about care plan.

---

## 2.6 Clinical Note Summarization (Medium)

**What:** Summarize lengthy clinical notes, hospital courses, or multi-visit histories into concise overviews for busy clinicians.

**Why medium:** Must preserve clinically relevant details. Omission risks are real. Different specialties need different emphasis. Requires understanding of what's "important."

---

## 2.7 Literature Search and Evidence Synthesis (Medium-Complex)

**What:** Answer clinical questions by searching medical literature, synthesizing findings, and presenting evidence with citations and strength ratings.

**Why this complexity:** Must cite sources accurately. Hallucination risk high without RAG architecture. Evidence grading requires nuance. Clinicians may act on output.

---

## 2.8 Ambient Clinical Documentation (Complex)

**What:** Listen to patient-provider conversations and generate structured clinical notes (HPI, exam, assessment, plan) in real-time or near-real-time.

**Why complex:** Speech recognition + speaker diarization + clinical understanding + note formatting. Must capture clinical nuance. Real-time constraints. Provider must review but attention is limited. Workflow integration critical.

---

## 2.9 Clinical Decision Support Synthesis (Complex)

**What:** Given patient context, synthesize relevant guidelines, drug interactions, contraindications, and evidence into actionable recommendations.

**Why complex:** Direct impact on clinical decisions. Must be grounded in authoritative sources. Liability and regulatory implications. Must handle uncertainty appropriately. Alert fatigue if poorly calibrated.

---

## 2.10 Multi-Modal Clinical Reasoning (Complex)

**What:** Combine clinical notes, lab trends, imaging findings, and patient history to generate differential diagnoses or care recommendations.

**Why complex:** Multiple data modalities. Reasoning must be transparent/explainable. Highest clinical risk tier. Regulatory uncertainty (FDA). Requires extensive validation before deployment.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Human review before action | Reduces risk |
| Grounding requirements | RAG/citation needs add complexity |
| Clinical decision impact | Higher stakes = more validation |
| Real-time requirements | Latency constraints compound difficulty |
| Multi-modal inputs | Each modality adds integration work |
| Regulatory exposure | FDA/liability concerns for clinical tools |

---

*Category 2 complete. Next: Category 3 (Anomaly Detection)*
