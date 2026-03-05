# Category 11: Conversational AI / Virtual Assistants

**Healthcare Use Cases — Simple → Complex**

---

## 11.1 FAQ Chatbot (Simple)

**What:** Answer common patient questions (hours, locations, parking, accepted insurance, appointment prep) via web chat or messaging.

**Why simple:** Curated knowledge base. No clinical content. Fallback to human for edge cases. Easy to monitor and improve. Quick wins for patient access.

---

## 11.2 Appointment Scheduling Bot (Simple)

**What:** Handle appointment scheduling, rescheduling, and cancellation through conversational interface with calendar integration.

**Why simple:** Transactional task with clear completion criteria. Integrates with scheduling APIs. Constraints are explicit (availability, provider, location). Human handoff for complex requests.

---

## 11.3 Prescription Refill Request Bot (Simple-Medium)

**What:** Process prescription refill requests via conversation — verify identity, confirm medication, submit to pharmacy queue.

**Why this complexity:** Must verify patient identity. Needs pharmacy/EHR integration. Some refills need clinical review. Must handle controlled substances appropriately.

---

## 11.4 Pre-Visit Intake Bot (Medium)

**What:** Collect pre-visit information (reason for visit, symptom details, medication updates) via conversational interface before appointments.

**Why medium:** Must adapt questions based on responses. Collects clinical information (symptoms, history). Data must flow to EHR. Patient experience matters — can't feel like interrogation.

---

## 11.5 Insurance Benefits Navigator (Medium)

**What:** Help patients understand their insurance coverage, estimate costs, and navigate authorization requirements through conversation.

**Why medium:** Benefits information is complex and plan-specific. Must integrate with eligibility data. Errors cause patient frustration and billing issues. Regulatory constraints on advice.

---

## 11.6 Symptom Checker / Triage Bot (Medium-Complex)

**What:** Guide patients through symptom assessment to recommend appropriate care level (self-care, telehealth, urgent care, ED, 911).

**Why this complexity:** Clinical content requires medical oversight. Liability considerations for triage recommendations. Must be conservative (don't miss emergencies). Clinical validation required.

---

## 11.7 Chronic Disease Management Coach (Complex)

**What:** Provide ongoing conversational support for chronic disease management — medication reminders, symptom check-ins, lifestyle coaching, care plan adherence.

**Why complex:** Long-running relationships. Must personalize over time. Connects to clinical data (glucose readings, BP). Escalation pathways for concerning trends. Engagement requires relationship-building.

---

## 11.8 Mental Health Support Bot (Complex)

**What:** Provide conversational mental health support — mood tracking, CBT techniques, crisis resource connection, therapeutic exercises.

**Why complex:** Sensitive domain requiring careful design. Must detect crisis and escalate appropriately. Ethical considerations around replacement vs. supplement to therapy. Regulatory considerations. Efficacy evidence needed.

---

## 11.9 Care Coordination Assistant (Complex)

**What:** Help patients navigate complex care journeys — coordinating between specialists, tracking referrals, managing care transitions.

**Why complex:** Must understand multi-provider care plans. Integrates with multiple systems. Long-running context across episodes. High-touch patients have high needs. Human care management backup required.

---

## 11.10 Clinical Trial Recruitment Conversationalist (Complex)

**What:** Engage potential clinical trial participants in conversation to assess interest, explain studies, screen for basic eligibility, and connect with research coordinators.

**Why complex:** Must accurately represent trial requirements. Regulatory/IRB constraints on recruitment communication. Must handle sensitive health topics. Consent considerations. Research coordinator workflow integration.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Clinical content | Medical topics need oversight |
| Integration depth | More systems = more complexity |
| Conversation length | Multi-session requires state |
| Escalation criticality | Must never miss emergencies |
| Regulatory exposure | Triage, mental health have scrutiny |
| Personalization needs | Long-term relationship harder than transactional |

---

*Category 11 complete. Next: Category 12 (Time Series Analysis / Forecasting)*
