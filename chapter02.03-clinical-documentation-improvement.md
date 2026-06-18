<!--
Editorial pass (TechEditor, 2026-05-11):
- Tightened Prerequisites: scoped IAM permissions to resource ARNs, promoted DynamoDB encryption to customer-managed KMS key, split the Bedrock VPC endpoint into its two real endpoints (bedrock-runtime and bedrock-agent-runtime), and added a Lambda Runtime row with an explicit timeout floor (expert review H2-HIGH Lambda timeout, M2 IAM scoping, M3 DynamoDB CMK, M9 bedrock-agent-runtime endpoint).
- Softened one hyperbolic word in the "Why LLMs Work Here" discussion (dramatically -> substantially) to match the engineer-explaining voice used elsewhere in the recipe (voice review L11).
- Preserved the TechWriter TODO on Recipe 7.3 cross-reference. Note: a pass through categories/07-predictive-analytics.md finds no "DRG Prediction" recipe in the current plan (7.3 is currently "Patient Churn / Disenrollment Prediction"); the closest clinically related neighbors are 7.5 (30-Day Readmission) and 7.7 (Length of Stay). Flagging for the book-wide cross-reference sweep.
- Flagged remaining structural items as TODOs for TechWriter (see inline comments): PHI minimization guidance in Why This Isn't Production-Ready (H1), DLQ / reliable ingestion note (H3), idempotency on repeat events (M4), knowledge base retrieval caching and batching (M1), suggestion retention / secure deletion policy (L1), and EHR network connectivity sentence (L2). Per persona rules, structural additions that introduce new architectural content are left for the TechWriter rather than rewritten here.
- Verified: zero em dashes (U+2014 full-file scan), header hierarchy (H1 title, H2 major, H3 subsection, H4 Walkthrough) matches chapter01 and chapter02.01/02.02, RECIPE-GUIDE section order intact, vendor balance holds at ~70/30 (AWS names first appear at "The AWS Implementation"), all external URLs well-formed, no documentation-voice or LinkedIn-influencer anti-patterns present.

Editorial pass 2 (TechEditor, 2026-05-11):
- Corrected pass-1 changelog to say "Why LLMs Work Here" (the actual location of the `dramatically -> substantially` swap) rather than "Variations," and expanded the Recipe 7.3 note with the current title from categories/07-predictive-analytics.md so the downstream cross-reference sweep has the context it needs.
- Re-verified: zero em dashes (U+2014), zero triple-blank-line gaps in prose, header hierarchy unchanged from pass 1, pseudocode fences all tagged, Mermaid block intact, all sample ICD-10-CM codes (J18.9, J15.1, J15.6, J13, I50.9, I50.23) valid in the current code set, Related Recipes numbers match the current chapter 2 plan (2.1, 2.4, 2.6).
- Confirmed the five TODOs flagged in pass 1 are still the right handoff to TechWriter: each introduces new architectural prose (PHI redaction via Comprehend Medical, SQS/DLQ in the ingestion path, idempotency composite key, knowledge-base caching, retention policy, EHR connectivity) rather than in-place edits, which is the boundary persona rules draw between editor and writer. No rewrites performed.

Editorial pass 3 (TechEditor, 2026-05-11):
- Moved the visible "TODO: verify recipe number." text in the Recipe 7.3 bullet of Related Recipes into an HTML comment, matching the convention already used in chapter02.02 (Recipe 8.1 bullet). The TODO itself is preserved, including the pass-1 note that the current chapter 7 plan has 7.3 as "Patient Churn / Disenrollment Prediction" rather than "DRG Prediction." Persona rule on preserving TODO markers is honored; change is pure formatting/convention alignment so the TODO no longer appears in rendered output.
- Final checklist sweep against both reviews. No remaining fixable issues at the editing layer.
- Verified: zero em dashes (U+2014 full-file scan), zero en dashes, no hype markers (leverage, seamless, delve, empower, revolutionize, game-changer, cutting-edge, robust, unlock), no doubled-word typos, header hierarchy (H1 title / H2 major / H3 subsection / H4 Walkthrough) stable, all 10 external URLs in Additional Resources well-formed on their documented AWS / CMS / AHIMA domains, vendor balance holds at approximately 70/30 (AWS service names first appear in "The AWS Implementation").
- RECIPE-GUIDE section order verified: Problem, Technology, General Architecture Pattern, Why These Services, Architecture Diagram, Prerequisites, Ingredients, Code (Walkthrough), Expected Results, Why This Isn't Production-Ready, Honest Take, Variations, Related Recipes, Additional Resources, Estimated Implementation Time, Tags, Navigation.
- TODOs preserved verbatim for TechWriter: (H1) PHI minimization before LLM calls via Comprehend Medical DetectPHI, (H3) SQS/DLQ on the S3-to-Lambda ingestion path, (M4) idempotency composite key, (M1) knowledge-base retrieval caching and batching, (L1) suggestion retention / secure deletion policy, (L2) EHR network connectivity note on the EHR integration paragraph, and the Recipe 7.3 cross-reference handoff (now in HTML-comment form). Per persona instructions, these six structural items are left for the TechWriter rather than rewritten here because each introduces new architectural prose rather than an in-place correction.

Editorial pass 4 (TechEditor, 2026-05-11):
- Fixed a broken internal navigation link at the bottom of the file. The "Next" link previously pointed to `chapter02.04-prior-authorization-letter-generation`, but the actual filename in the repository is `chapter02.04-prior-auth-letter-generation.md` (verified against repo directory listing and confirmed consistent with the back-link convention used by chapter02.02 and chapter02.01). The link display text ("Recipe 2.4 - Prior Authorization Letter Generation") is unchanged; only the URL slug was corrected. Pure in-place fix, no structural change, no new content. Passes 1-3 all missed this because file-level grep for "prior-auth" was never run against the nav footer.
- Re-verified against chapter 1 reference files that bare-fenced pseudocode blocks (triple backticks with no language tag) match the established book convention; chapter01.02 uses the same style. No change required.
- Re-verified: zero em dashes, zero en dashes, no hype markers, all nine external URLs in Additional Resources well-formed, all internal links now point to real filenames, header hierarchy intact, RECIPE-GUIDE section order intact, vendor balance approximately 70/30, all six TechWriter TODOs preserved.
- No remaining fixable issues at the editing layer. Handing back to the pipeline.

Editorial pass 5 (TechEditor, 2026-06-17):
- Post-split polish. File was mechanically split from a combined recipe into main (story/concepts) and architecture companion (AWS implementation/pseudocode).
- Verified: General Architecture Pattern contains no AWS service references; The Honest Take contains no dangling references to AWS content now in the companion; architecture callout is correctly placed at the end of General Architecture Pattern.
- Fixed bare code fence on the pipeline flow diagram (added `text` language tag).
- RECIPE-GUIDE compliance for post-split main recipe confirmed: The Problem, The Technology, General Architecture Pattern (with callout), The Honest Take, Related Recipes, Tags, Navigation. All present and in order.
- Zero em dashes, zero en dashes, no hype markers, all TODOs preserved.
-->

# Recipe 2.3: Clinical Documentation Improvement (CDI) Suggestions

**Complexity:** Simple-Medium · **Phase:** MVP · **Estimated Cost:** ~$0.02-0.08 per note

---

## The Problem

A hospitalist admits a patient with pneumonia. They write in the progress note: "Patient has pneumonia, started on antibiotics." Clinically, this is fine. The patient gets treated. But from a coding and reimbursement perspective, this note is a disaster.

Was it community-acquired or hospital-acquired pneumonia? Bacterial, viral, or aspiration? Which organism, if known? Is it the principal diagnosis or a complication of something else? Each of these distinctions maps to a different ICD-10 code, and each code maps to a different DRG, and each DRG maps to a different reimbursement amount. The difference between "pneumonia, unspecified" (J18.9) and "pneumonia due to Streptococcus pneumoniae" (J13) can mean thousands of dollars in reimbursement difference for the same clinical care.

This is not about upcoding. This is about accuracy. The documentation should reflect what the physician actually knows and did. When a physician writes "pneumonia" but their lab results show Streptococcus and their antibiotic choice confirms they're treating a bacterial infection, the documentation is incomplete, not wrong. The clinical picture is clear in the physician's head. It just didn't make it onto the page.

Clinical Documentation Improvement (CDI) is the discipline of catching these gaps. Traditionally, CDI specialists (usually nurses or coders with clinical backgrounds) manually review charts, identify documentation that lacks specificity, and send queries to physicians asking them to clarify. "Dr. Smith, your note says pneumonia. Can you specify the type and causative organism?" The physician updates the note, the coder assigns a more specific code, and the claim reflects the actual complexity of care delivered.

The problem is scale. A typical hospital generates hundreds of inpatient notes per day. CDI specialists can review maybe 20-30 charts per day thoroughly. That means most notes never get a CDI review. The ones that do get reviewed are selected by simple heuristics (high-value DRGs, specific service lines) rather than by actual documentation quality. Notes with significant gaps slip through because nobody had time to look at them.

The financial impact is real. The American Health Information Management Association (AHIMA) estimates that hospitals lose 1-5% of potential revenue due to documentation specificity gaps. For a mid-size hospital doing $500M in annual revenue, that's $5-25M left on the table. Not because the care wasn't delivered, but because the documentation didn't capture it precisely enough.

What if you could scan every note as it's written, identify specificity gaps in real time, and suggest clarifications before the chart is even closed? That's what this recipe builds.

---

## The Technology: LLM-Based Documentation Analysis

### What CDI Actually Requires

CDI is not a simple text classification problem. It requires understanding three things simultaneously:

1. **Clinical context.** What does the note actually say happened? What diagnoses are mentioned, what treatments were given, what labs were ordered?
2. **Coding rules.** What level of specificity does ICD-10-CM require for each condition? What qualifiers (laterality, acuity, causative organism, stage) are needed for a complete code?
3. **Gap detection.** Where does the clinical context imply information that the documentation doesn't explicitly state? If the labs show E. coli and the antibiotics target gram-negative bacteria, but the note just says "UTI," there's a specificity gap.

Traditional CDI software uses rule-based engines: if the note mentions "heart failure" but doesn't specify systolic vs. diastolic, fire a query. These rules work for common, well-defined gaps. They miss nuanced cases, they generate false positives on notes that actually do contain the specificity elsewhere in the text, and they require constant manual maintenance as coding guidelines change.

LLMs change this equation because they can read and reason about clinical text the way a human CDI specialist does. They understand that "started on Zosyn" implies the physician suspects a gram-negative or anaerobic infection. They understand that "EF 25%" in an echo report means systolic heart failure even if the note doesn't use those words. They can identify what's implied but not stated, which is exactly what CDI is about.

### Why LLMs Work Here

**They understand medical language natively.** Modern LLMs trained on clinical literature understand the relationships between symptoms, diagnoses, treatments, and lab values. They don't need explicit rules mapping "Zosyn" to "gram-negative coverage." They learned these associations from millions of clinical documents.

**They can reason about specificity.** You can instruct an LLM: "Given this note, identify any diagnoses that could be documented more specifically per ICD-10-CM guidelines." The model understands what "more specifically" means in a coding context because it has seen thousands of examples of specific vs. unspecific documentation.

**They handle context across the full note.** A rule-based system might flag "heart failure" as lacking specificity in the assessment section, missing that the physician documented "systolic dysfunction, EF 30%" in the cardiac exam three paragraphs earlier. An LLM reads the entire note and understands that the specificity exists, just in a different section. This cuts false-positive queries substantially.

**They generate natural-language suggestions.** Instead of firing a cryptic alert ("HF: specify type"), an LLM can generate a physician-friendly query: "Your note mentions heart failure. The echocardiogram documents EF 30%, which suggests systolic heart failure (HFrEF). Would you like to specify this in your assessment?" This is closer to how a human CDI specialist would phrase the question.

### The Failure Modes (and They're Important)

**Hallucinated clinical findings.** The most dangerous failure. The model suggests a specificity improvement based on clinical information that isn't actually in the chart. "Your labs suggest E. coli" when no culture results exist yet. This is why CDI suggestions must always be framed as questions, never as assertions, and why physicians must always make the final documentation decision.

**Coding rule staleness.** ICD-10-CM guidelines update annually. CMS publishes new codes, retires old ones, and changes specificity requirements every October. An LLM's training data has a cutoff. If you're relying on the model's inherent knowledge of coding rules rather than providing current guidelines via retrieval, your suggestions will drift out of date. This is a strong argument for RAG (Retrieval-Augmented Generation) architecture.

**Over-querying.** A model that flags every possible specificity gap will drown physicians in queries. Alert fatigue is already a massive problem in healthcare IT. If your CDI system generates 15 suggestions per note, physicians will ignore all of them. You need confidence thresholds and prioritization: flag the high-impact gaps, suppress the marginal ones.

**Context window limitations.** Hospital notes can be long. A multi-day admission with daily progress notes, consult notes, procedure notes, and nursing documentation can easily exceed 50,000 tokens. You need a strategy for handling notes that exceed your model's context window: summarization, chunking with overlap, or selective section analysis.

**Physician trust.** This is not a technical failure mode, but it kills more CDI programs than any bug. If physicians perceive the system as a revenue-optimization tool rather than a documentation accuracy tool, they'll resist it. The suggestions must be clinically grounded, respectfully phrased, and genuinely helpful for documentation quality. "This will increase your DRG weight" is the wrong framing. "This will ensure your documentation reflects the complexity of care you actually delivered" is the right one.

### Retrieval-Augmented Generation for CDI

Pure LLM inference (just sending the note to a model and asking "what's missing?") works surprisingly well for common conditions. But for production CDI, you want RAG architecture. Here's why:

**Current coding guidelines.** ICD-10-CM Official Guidelines for Coding and Reporting change annually. Embedding the current year's guidelines in a vector store and retrieving relevant sections based on the diagnoses mentioned in the note ensures your suggestions reflect current rules, not the model's potentially outdated training data.

**Organization-specific query templates.** Every health system has preferred query language, approved query types, and compliance-reviewed phrasing. Retrieving your organization's approved templates and using them to format suggestions ensures consistency and compliance.

**Payer-specific requirements.** Different payers have different documentation requirements for the same condition. Medicare requires different specificity than commercial payers for certain diagnoses. Retrieving payer-specific rules based on the patient's coverage adds another layer of accuracy.

The RAG pattern here is: extract diagnoses from the note, retrieve relevant coding guidelines and query templates, then ask the LLM to identify gaps and generate suggestions using the retrieved context as ground truth.

### The General Architecture Pattern

```text
[Clinical Note] → [Extract Key Clinical Elements] → [Retrieve Coding Guidelines] → [Identify Specificity Gaps] → [Generate CDI Suggestions] → [Prioritize and Filter] → [Present to CDI Specialist / Physician]
```

**Extract Key Clinical Elements.** Parse the note to identify diagnoses, procedures, medications, lab values, and clinical findings. This gives you the "what's documented" baseline.

**Retrieve Coding Guidelines.** Based on the identified diagnoses, pull the relevant ICD-10-CM guidelines, specificity requirements, and your organization's query templates from a knowledge base.

**Identify Specificity Gaps.** Compare what's documented against what the guidelines require. Where is the documentation less specific than the coding rules demand? Where does clinical context (labs, meds, vitals) imply information not explicitly stated?

**Generate CDI Suggestions.** For each identified gap, generate a physician-friendly query suggesting the clarification needed. Include the clinical evidence supporting the suggestion.

**Prioritize and Filter.** Rank suggestions by clinical and financial impact. Suppress low-confidence suggestions. Limit the total number per note to avoid alert fatigue.

**Present.** Surface suggestions in the CDI specialist's workflow (for traditional review) or directly in the physician's EHR (for concurrent, real-time CDI).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.03-architecture). The Python example is linked from there.

## The Honest Take

CDI is one of those problems where the AI part is actually the easy part. Getting a model to identify specificity gaps in clinical notes is straightforward with modern LLMs. The hard parts are everything around it: EHR integration, physician workflow, compliance review, alert fatigue management, and organizational change management.

The 70-85% accuracy range for suggestions sounds mediocre until you compare it to the alternative: most notes never getting CDI review at all. A system that reviews 100% of notes at 75% accuracy catches more real gaps than a human team that reviews 15% of notes at 95% accuracy. The math works in your favor even with imperfect AI.

The thing that surprised me most: physician acceptance rates are highly sensitive to suggestion phrasing, not suggestion accuracy. A technically correct suggestion phrased poorly ("Documentation deficiency: heart failure type not specified") gets rejected. The same suggestion phrased respectfully ("The echo shows EF 35%. Would you characterize this as systolic heart failure?") gets accepted. Invest heavily in prompt engineering for the query generation step. It matters more than the gap detection step.

Alert fatigue is your biggest operational risk. Start with a high confidence threshold and low maximum suggestions per note. It's better to catch 50% of gaps with high physician trust than to catch 90% of gaps while physicians learn to ignore your system entirely. You can always lower the threshold once you've established credibility.

One more thing: the financial ROI on CDI is easy to measure (compare DRG weights before and after), which makes this one of the easier AI projects to get funded. But don't lead with revenue. Lead with documentation accuracy and patient safety (accurate documentation supports better care transitions). The revenue follows naturally from accurate documentation.

---

## Related Recipes

- **Recipe 2.1 (Patient Message Response Drafting):** Shares the Bedrock inference pattern but for a different text generation use case
- **Recipe 2.4 (Prior Authorization Letter Generation):** Uses similar clinical element extraction but generates outbound letters rather than internal queries
- **Recipe 2.6 (Clinical Note Summarization):** Complementary capability; summarization helps CDI specialists review notes faster
- **Recipe 7.3 (DRG Prediction):** Predicts DRG assignment, which CDI suggestions aim to improve through better documentation <!-- TODO: Verify recipe number and title against final chapter 7 index. Editorial pass 1 noted that categories/07-predictive-analytics.md currently lists 7.3 as "Patient Churn / Disenrollment Prediction"; closest clinical neighbors are 7.5 (30-Day Readmission) and 7.7 (Length of Stay). -->

---

## Tags

`llm` · `generative-ai` · `bedrock` · `rag` · `cdi` · `clinical-documentation` · `coding` · `icd-10` · `knowledge-bases` · `simple-medium` · `hipaa` · `lambda` · `dynamodb`

---

*← [Recipe 2.2: Medical Terminology Simplification](chapter02.02-medical-terminology-simplification) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.4 - Prior Authorization Letter Generation →](chapter02.04-prior-auth-letter-generation)*
