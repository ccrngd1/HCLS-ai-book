# Complexity Factors

Understanding why some healthcare AI use cases are harder than others.

## The Complexity Matrix

| Factor | Low Complexity | High Complexity |
|--------|---------------|-----------------|
| **Clinical Risk** | Administrative/operational | Direct patient care impact |
| **Human Review** | Always reviewed before action | Autonomous or time-pressured |
| **Data Sources** | Single system | Multi-system integration |
| **Real-Time Needs** | Batch/async acceptable | Sub-second latency required |
| **Regulatory Exposure** | None | FDA, state law, payer rules |
| **Output Type** | Suggestions/drafts | Decisions/actions |
| **Failure Mode** | Graceful degradation | Catastrophic if wrong |

## Factor Deep Dives

### Clinical Risk

The spectrum from "wrong answer is annoying" to "wrong answer harms patients":

- **Low:** Scheduling optimization, billing suggestions, document routing
- **Medium:** Care gap identification, medication reminders, referral suggestions
- **High:** Dosing recommendations, diagnostic support, treatment planning

### Integration Requirements

Each additional system multiplies complexity:

- **1 system:** Data quality is your problem
- **2-3 systems:** Data mapping and reconciliation
- **4+ systems:** You're building an integration platform, not an AI feature

### Real-Time Constraints

Latency requirements change architecture dramatically:

- **Hours/Days:** Batch processing, simple infrastructure
- **Minutes:** Near-real-time, message queues, monitoring
- **Seconds:** Streaming, edge compute, fallback strategies
- **Milliseconds:** Specialized infrastructure, pre-computation

### Regulatory Landscape

Know your exposure before you build:

- **FDA:** Software as Medical Device (SaMD) if it informs clinical decisions
- **HIPAA:** Always applies to PHI, but some uses have more exposure
- **State Laws:** Consent requirements, data residency, AI transparency
- **Payer Rules:** Prior auth, coding, claims have specific requirements

## Complexity Estimation Heuristic

Score each factor 1-3, sum for rough complexity estimate:

| Score | Meaning |
|-------|---------|
| 6-9 | Quick win territory |
| 10-14 | Medium complexity, plan for iteration |
| 15-18 | Complex, requires mature organization |
| 19+ | Very complex, consider phased approach |

## Red Flags

Pause if you see these:

- "We'll figure out the regulatory stuff later"
- "The data quality isn't great but AI will handle it"
- "We need this in production in 6 weeks"
- "Let's skip the pilot and go enterprise-wide"
- "The vendor said it's plug-and-play"

---

*Complexity isn't bad — it's information. Use it to set realistic expectations and plan accordingly.*
