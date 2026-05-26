# Expert Review: Recipe 11.10 - Clinical Trial Recruitment Conversationalist

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-25
**Recipe file:** `chapter11.10-clinical-trial-recruitment-conversationalist.md`

---

## Verdict: FAIL

The recipe is structurally incomplete. The file ends at line 199, immediately after the "Where the Field Has Moved" subsection of Section 2 ("The Technology"). The recipe contains only the first two of the structural sections required by `RECIPE-GUIDE.md`. The General Architecture Pattern (vendor-agnostic), the entire AWS-Specific Build (Why These Services, Architecture Diagram, Prerequisites, Ingredients, Code/Pseudocode walkthrough, Python-companion callout), Expected Results, The Honest Take, Variations and Extensions, Related Recipes, Additional Resources, Estimated Implementation Time, Tags, and Navigation are absent. This is a CRITICAL completeness defect that automatically fails the review. The Stage-1 reviewers below were therefore unable to evaluate large portions of the recipe (architecture diagram, ingredients table, AWS service IAM scoping, networking topology, code samples, honest-take traps, related-recipe cross-references) because none of those sections exist in the file.

The text that does exist (The Problem; The Technology) is high-quality, consistent with CC's voice, broadly accurate from a healthcare-domain perspective, and well-aligned with the chapter's architectural inheritance pattern. The expert panel's substantive feedback on those two sections is below as Stage-1 findings, but the dominant issue is structural incompleteness.

By the bar set in the task instructions:
- 1 CRITICAL finding (recipe incomplete) → automatic FAIL.
- 0 HIGH findings issued because the architecture sections that would normally accumulate HIGH findings do not exist in the file. (HIGH findings will likely emerge after the missing sections are written; the chapter pattern from 11.1 through 11.9 produces 3 HIGH findings per recipe.)
- Several MEDIUM and LOW findings on the prose that does exist are listed in Stage 3.

The TechWriter must complete the recipe before a substantive technical-correctness review can be performed end-to-end. This review identifies the gap and provides concrete guidance on what the missing sections must contain so the rewrite hits the chapter pattern on first pass.

---

## Stage 1: Independent Expert Reviews

### Security Expert (OWASP, CIS, NIST SP 800-66 for HIPAA, plus 21 CFR Part 11 and 21 CFR Part 50 for FDA-regulated research)

**What's done well in the existing prose:**

- IRB-approved-content corpus framed as the only allowed source of trial-specific patient-facing language is the architecturally correct primitive and is correctly elevated to load-bearing status in the Technology section.
- Per-trial isolation framed as architectural primitive is correct; cross-trial leakage of recruitment language is a real regulatory finding waiting to happen and the prose anticipates it.
- Recruitment-conversation content correctly identified as research data under HIPAA's research provisions and 45 CFR 46, distinct from clinical-care PHI handling. This is a recipe-distinct privacy posture that 11.1 through 11.9 did not have to enforce.
- 21 CFR Part 50 and ICH-GCP correctly cited (with TODO-verify hedge) as governing the consent-not-the-recruitment line.
- 45 CFR 46 Subparts B/C/D for vulnerable-population protections correctly elevated.
- Continuous emergency screening across every utterance correctly inherited from prior chapter recipes.
- Eligibility-evaluation engine framed as deterministic with named clinical-leadership ownership per criterion is correct (LLMs do clinical-decision-rule arithmetic poorly).

**Finding S1 (CRITICAL — recipe-incomplete):** The Build section that would normally specify BAA coverage, KMS-CMM keying per record class (research-data vs clinical-care-data), customer-managed-keys for the IRB-approved-corpus store, separate keys for the recruitment-conversation archive, separately-keyed coordinator-handoff store, CloudTrail data events on all sensitive S3 buckets and DynamoDB tables, Object Lock in compliance mode for the recruitment-decision-record journal and IRB-corpus archive, audit retention floor (longest of HIPAA's 6-year, 21 CFR Part 11 record-retention rules for FDA-regulated trials, ICH-GCP retention through trial-completion-plus-N-years per protocol, state-specific medical-record retention, FDA SaMD post-market obligations where applicable, and any litigation-hold obligations), per-Lambda least-privilege roles, Bedrock Guardrails configuration with recruitment-specific denied topics (recommendation-attempted, diagnosis-attempted, dose-titration-attempted, consent-attempted, enrollment-attempted, advice-on-whether-to-participate-attempted), WAF in front of the chat endpoint, identity assurance lifecycle, prompt-injection defense, and per-cohort monitoring with launch-gate discipline does not exist. **Fix:** TechWriter must author the AWS-Specific Build section. The chapter-9 pattern (and 11.6 through 11.9 specifically) provides the template.

**Finding S2 (HIGH — research-record-class will be acute):** Once the architecture is written, the recipe will need to elevate research-data-as-distinct-record-class handling beyond the chapter pattern. The Technology section names this correctly as a recipe-distinct primitive. The architecture must follow through with separately-keyed buckets for the IRB-approved-content corpus, the recruitment-conversation archive, the prescreen-result store, the coordinator-handoff queue, the recruitment-funnel-instrumentation store, and the diversity-action-plan-tracking store, with separate IAM principals scoped to research-data access (research-data-officer, sponsor-recruitment-team, IRB-inspector audit-only role, principal-investigator role, coordinator-team role) versus clinical-care principals (clinician, care-team). Cross-class read paths must be explicitly disallowed at the IAM-policy level.

**Finding S3 (HIGH — 21 CFR Part 11 and audit-trail discipline):** FDA-regulated clinical-trial recruitment material is part of the IND/IDE record. 21 CFR Part 11 imposes electronic-record-and-signature requirements on the recruitment-platform's audit trail when the trial is FDA-regulated. The architecture must specify Part-11-compliant audit logging, electronic-signature workflows for IRB-approved-content version sign-off, and inspection-ready audit-trail export. The Technology section anticipates this ("Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record.") with a TODO-verify hedge but the architecture does not yet operationalize it.

**Finding S4 (MEDIUM — 21 CFR Part 11 hedge missing in Technology section):** The Technology section names 21 CFR Part 50 and ICH-GCP for consent but does not mention 21 CFR Part 11 for the electronic-record-and-signature surface that the recruitment-platform's audit trail will live in. **Fix:** Add a sentence to the "It is not a regulatory afterthought" paragraph or the "The IRB is an active participant in product development" paragraph naming 21 CFR Part 11 with a TODO-verify hedge.

### Architecture Expert (scalability, anti-patterns, distributed systems)

**What's done well in the existing prose:**

- Per-trial isolation as an architectural primitive (not a tenancy afterthought) is the correct shape.
- Trial-state-and-trial-amendment tracking framed as a separate subsystem the assistant queries on every conversation is the correct shape — recruitment context is mutable, and the assistant must not cache stale trial state.
- Coordinator-handoff orchestration framed as production scope (not phase 2) is correct. A recruitment funnel that delivers warm handoffs to a coordinator team that has not been trained on the platform is a workflow-rejection risk that the recipe correctly anticipates.
- Coordinator capacity called out as a hard constraint (with calibrated-throughput guidance) is correct — flooding the coordinator queue is a known anti-pattern that produces patient-experience harm.
- IRB-approved-content corpus as the only allowed source of trial-specific language with strict citation grounding is the correct architectural primitive for hallucination defense, and matches the chapter-9 reasoning section's RAG discipline pattern.

**Finding A1 (CRITICAL — recipe-incomplete):** The architecture pattern (vendor-agnostic), the architecture diagram, the staged decomposition, the ingredients table, and the pseudocode walkthrough are all absent. The chapter pattern from 11.1 through 11.9 establishes a 10-stage decomposition (input safety screening → identity verification → trial-context loading → tool-use loop → eligibility evaluation → output safety → coordinator handoff → audit persistence → per-cohort monitoring → reporting). The reader cannot evaluate whether the architecture has SPOFs, whether it has DLQ coverage on async paths, whether the eligibility-evaluation engine is a separate Lambda or co-located with the LLM-tool dispatcher, or whether the IRB-approved-corpus retrieval is RAG-with-citation-coverage-check or a pure prompt-injection of the trial-context. **Fix:** Author the architecture pattern with explicit per-stage decomposition matching the chapter pattern.

**Finding A2 (HIGH — IRB-amendment-application-mid-conversation):** Once the architecture is written, it will need to address an architectural edge case that the Technology section calls out but does not fully specify: "where amendments materially change recruitment communication, re-presents the updated information to in-flight prospective participants per the IRB-approved process." This is a real distributed-systems problem (the assistant has in-flight conversations against the prior trial-context version when the IRB-amendment is approved) that needs an explicit architectural treatment: snapshot trial-context-version at conversation start; on every turn re-fetch trial-state and compare versions; if material amendment, branch to the IRB-approved re-disclosure flow; if non-material amendment, continue on the original snapshot with stamped version-history. This is a recipe-distinct architectural primitive not present in 11.1 through 11.9.

**Finding A3 (HIGH — coordinator-queue-as-throughput-control):** The Technology section correctly identifies coordinator capacity as a hard constraint. The architecture will need a queue-throughput-control primitive (not just a queue), with explicit overflow handling: when the coordinator queue exceeds the configured throughput-floor, the assistant transitions to a "coordinator-team-busy, we'll reach out within X business days, here are the trial materials in the meantime" flow rather than continuing to enqueue handoffs that age out. This is a recipe-distinct primitive not present in 11.1 through 11.9.

**Finding A4 (MEDIUM — multi-trial scenario):** The Technology section names the multi-trial-candidate scenario ("a patient may be a candidate for more than one trial") and asserts "discussing one trial at a time" as the correct posture. The architecture should specify how this is enforced: per-conversation trial_id binding at session-start; switching trials within a session triggers a new conversation with new disclosures and new consent posture; cross-trial recommendation is structurally prohibited at the tool-dispatcher level. **Fix:** Add a "Per-Conversation Trial-Binding" primitive to Cross-Cutting Design Points when the architecture is written.

### Networking Expert (RFCs, cloud-provider best practices)

**Finding N1 (CRITICAL — recipe-incomplete):** The Prerequisites and AWS-Specific Build sections are absent, so the VPC topology, VPC-endpoint posture, egress posture, and TLS-in-transit configuration cannot be evaluated. **Fix:** TechWriter must author the AWS-Specific Build section.

**Anticipated networking guidance for when the build section is written:**

- VPC endpoints for Bedrock, Bedrock Agents, Bedrock Knowledge Bases, S3, DynamoDB, Secrets Manager, Step Functions, KMS, CloudWatch Logs, Comprehend Medical (where used), Connect (where used for voice/SMS handoff), Pinpoint (where used for proactive recruitment outreach). Egress to the public internet should not be required for any PHI-bearing path. The recruitment-conversation surface (web chat, SMS, voice) terminates at API Gateway or Connect, which front the VPC-resident Lambda fleet.
- TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary (API Gateway, CloudFront, Connect endpoints, Pinpoint outbound channels).
- Cross-organizational data ingestion (where the assistant pulls from EHR for the EHR-integrated prescreen-invitation entry path) should use the institution's existing FHIR-API integration with mTLS or signed-JWT, not novel direct connections.
- ClinicalTrials.gov integration (where the assistant integrates with the trial-listing for trial discovery) should use the public ClinicalTrials.gov API over TLS with no PHI on the outbound path; only public trial metadata is retrieved.
- WAF in front of the chat endpoint with managed rule sets for SQL-injection, XSS, prompt-injection-pattern detection, and rate-limiting per IP and per session.

### Voice Reviewer (STYLE-GUIDE.md, RECIPE-GUIDE.md)

**Em-dash count: 0** (verified via grep for the `—` character against the file). The prose follows the no-em-dashes rule in the existing sections.

**TODO-verify markers: 13** (verified via grep). All are appropriately scoped to factual claims about regulatory guidance, published literature, or industry trends. These are author hedges, not blocking issues, but should be resolved before publication.

**Voice consistency:** The Maria-and-her-endocrinologist opening earns its position as the chapter's clearest articulation of the recruitment-funnel-as-friction-not-clinical-failure primitive. The "If you talk to clinical research coordinators about their daily work, this is a recognizable arc" pivot is consistent with CC's engineer-explaining-something-cool register. The "the thing the recruitment funnel needs is not faster coordinators" framing earns its position. The "what this recipe is and is not" enumeration is operationally accurate and recipe-distinct. The Technology section's three subsections are appropriately granular. The "Why a Generic LLM Cannot Run a Clinical Trial Recruitment Conversationalist" enumeration is operationally accurate. The "What the Recruitment Conversationalist Has To Do That the Previous Bots Did Not" eight-structural-commitments enumeration is recipe-distinct. The "Recruitment Reality" subsection's fifteen-property enumeration earns its position.

**Vendor-balance (70/30):** Cannot evaluate; the AWS-Specific Build section is absent. The existing prose is approximately 100% vendor-agnostic, which is correct for sections 1 and 2. The 30% AWS-specific content is missing entirely.

**Finding V1 (CRITICAL — recipe-incomplete):** Voice cannot be evaluated end-to-end on the missing sections. The Honest Take section, in particular, is where CC's voice typically lands hardest, and its absence is a significant gap. **Fix:** Author the missing sections.

**Finding V2 (LOW — sentence length in opening paragraph):** The Maria opening paragraph contains a single sentence that runs for nearly 200 words ("Maria put the sheet in her purse, intended to call, did not call... pending further review."). This is intentional voice (the accumulating-list-as-rhetorical-device is a CC pattern) and lands well, but pushes the limit. No fix required; flagging only.

**Finding V3 (LOW — TODO-verify markers should be tracked for resolution):** 13 inline `<!-- TODO: verify -->` markers. These are appropriate hedges for the draft stage but should be resolved or accepted-as-hedge before publication. Specific markers worth prioritizing for resolution:
- 21 CFR Part 50 and ICH E6 GCP guidelines for informed consent (line 27)
- 45 CFR 46 Subparts B/C/D vulnerable-population protections (line ~111)
- FDA 2022 draft guidance on diversity action plans for clinical trials (multiple)
- ClinicalTrials.gov registration requirements under FDAAA 801 (line ~189)
- FDA decentralized-trials guidance and EMA reflection paper (line ~187)

**Finding V4 (LOW — "should" vs "must" register in disclaimers):** The disclosure language ("the assistant is a chat tool not a person, the assistant is not the research coordinator, the assistant cannot enroll the patient...") uses lowercase declarative form that reads like specification rather than IRB-approved patient-facing copy. This is correct for the recipe (the recipe is describing what the disclosure must contain, not authoring the disclosure itself), but the architecture section, when written, should make explicit that the disclosure copy itself is IRB-approved content authored separately, not generated by the LLM.

---

## Stage 2: Expert Discussion

The four reviewers concur on the dominant finding: the recipe is structurally incomplete. The Security, Architecture, and Networking experts each surfaced what would be CRITICAL or HIGH findings if the relevant sections existed; they cannot. The Voice reviewer concurs that the Honest Take section is where CC's voice lands hardest in chapter 11 recipes (see 11.7, 11.8, 11.9 reviews), and its absence is a meaningful gap that no voice reformulation in the existing sections can compensate for.

**Conflict resolution:** None of the four reviewers' findings conflict. The Security and Architecture findings overlap on multi-asset governance scaffolding (IRB-approved-content corpus as code, eligibility-evaluation rule library, FDA-strategy artifact, consent-language artifact, vulnerable-population-policy artifact, recruitment-funnel-instrumentation policy, coordinator-team-workflow policy, sponsor-relationship policy, ClinicalTrials.gov-integration policy) which both reviewers will surface as a HIGH finding once the architecture is written. This pattern matches the chapter pattern from 11.1 through 11.9.

**Priority ordering:** Recipe completeness (CRITICAL) before any of the substantive findings. Once the architecture is written, the chapter pattern predicts 3 HIGH findings (multi-asset governance scaffolding; per-cohort monitoring with launch-gate discipline; record-class retention with research-data-and-FDA-regulated extensions), 12-18 MEDIUM findings, and 4-6 LOW findings.

---

## Stage 3: Synthesized Feedback

### CRITICAL Findings

**C1. Recipe is structurally incomplete; entire AWS-Specific Build, Architecture Pattern, Honest Take, Variations, Related Recipes, Additional Resources, Estimated Implementation Time, Tags, and Navigation are missing.**

- **Severity:** CRITICAL (automatic FAIL)
- **Expert:** Security, Architecture, Networking, Voice (all four)
- **Location:** File ends at line 199, immediately after the "Where the Field Has Moved" subsection of "The Technology". The closing `---` separator at line 199 is the last content in the file. By comparison, recipe 11.09 is 2,729 lines.
- **Quote:** The last content in the file reads:
  > "**Equity-and-representativeness work is an active area of investment.** Recruitment platforms are investing in multilingual content, low-literacy content adaptations, channel diversification (SMS, voice, in-person kiosk options), partnerships with community-based organizations, and per-cohort outcome monitoring with explicit equity targets.\n\n---"
- **Fix:** TechWriter must author the missing sections, following the chapter pattern from 11.6, 11.7, 11.8, and 11.9. Specifically required:
  1. **General Architecture Pattern** (vendor-agnostic): 10-stage decomposition with named architectural primitives (input safety, identity, trial-context loading, tool-use, eligibility-evaluation, output safety, coordinator handoff, audit persistence, per-cohort monitoring, reporting).
  2. **Why These Services**: AWS service rationale per primitive (Bedrock Agents for tool-orchestration; Bedrock Knowledge Bases for IRB-approved-content RAG; OpenSearch Serverless for vector and lexical retrieval; DynamoDB for per-trial state, prescreen state, recruitment-funnel-instrumentation; Step Functions for trial-state-and-amendment workflows; Lambda for the per-stage compute; SQS for the coordinator-handoff queue with throughput control; EventBridge for trial-state-change events; Connect and/or Pinpoint for SMS/voice channels; Comprehend Medical optional for de-identification of free-text patient-reported information).
  3. **Architecture Diagram**: Mermaid flowchart with explicit per-trial-isolation boundaries and the IRB-approved-content corpus as a separately-stored, separately-keyed asset class.
  4. **Prerequisites table**: AWS Services, IAM Permissions, BAA, Encryption, VPC, CloudTrail, Sample Data, Cost Estimate.
  5. **Ingredients table**: per-service role.
  6. **Code (Pseudocode Walkthrough)** with Python-companion callout linking to `chapter11.10-python-example`.
  7. **Expected Results** with sample JSON output and performance benchmarks table.
  8. **The Honest Take**: 10-12 traps in CC's voice, including (suggested) the IRB-as-active-product-development-participant trap, the protocol-amendment-cadence trap, the coordinator-capacity-as-hard-constraint trap, the equity-gap-with-recruitment-platform-reach trap, the diversity-action-plan-as-regulatory-not-marketing trap, the ClinicalTrials-gov-integration-as-not-quite-as-clean-as-you-hoped trap, the multi-trial-disambiguation trap, the consent-vs-recruitment-line trap, the conversations-completed-as-vanity-metric trap, the per-trial-onboarding-as-multi-week-clinical-work trap, the build-vs-buy-and-vendor-coexistence trap.
  9. **Variations and Extensions**: 2-3 practical extensions (suggested: pediatric-recruitment with assent-and-parental-permission identity model; multilingual recruitment with culturally-appropriate content and community-research-engagement-team review; decentralized-trial recruitment with home-visit-and-telehealth visit-schedule communication).
  10. **Related Recipes**: cross-references to 11.1 (FAQ chatbot — pattern parent), 11.2 (appointment scheduling — handoff pattern), 11.6 (symptom triage — IRB-vs-medical-device distinction), 11.7 (chronic-disease coach — citation-grounding pattern), 11.8 (mental-health support — sensitive-topic-handling), 11.9 (care coordination — longitudinal-state pattern), and forward references to 13.x (knowledge graphs for trial-eligibility encoding).
  11. **Additional Resources**: ClinicalTrials.gov, FDA 2022 draft guidance on diversity plans, FDORA, ICH E6 GCP, 21 CFR Part 11, 21 CFR Part 50, 45 CFR 46, AWS HealthLake, Bedrock, Bedrock Agents, Bedrock Knowledge Bases, AWS HIPAA Eligible Services list, AWS Solutions Library healthcare entries.
  12. **Estimated Implementation Time**: Basic / Production-ready / With variations.
  13. **Tags**: searchable labels.
  14. **Navigation footer**: prev/index/next links.

### HIGH Findings

(None at this review pass. The architecture sections that would normally accumulate HIGH findings do not exist. Anticipated HIGH findings for the rewrite are documented above as A2, A3, S2, S3 to give the TechWriter advance notice of the chapter-pattern issues to address proactively.)

### MEDIUM Findings

**M1. 21 CFR Part 11 not named in the Technology section despite its applicability to the FDA-regulated-trial recruitment-platform audit trail.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "It is not a regulatory afterthought" paragraph (line ~33) and the "The IRB is an active participant in product development" paragraph (line ~165).
- **Quote:** "Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record."
- **Fix:** Add a sentence (or extend the existing one) to name 21 CFR Part 11 alongside the IND/IDE reference, with a TODO-verify hedge. Suggested: "Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record, and the recruitment platform's audit trail is subject to 21 CFR Part 11 electronic-record-and-signature requirements. <!-- TODO: verify; 21 CFR Part 11 applies to electronic records and signatures used in FDA-regulated activities; specific applicability to recruitment-platform audit trails varies by deployment posture and FDA inspection scope -->"

**M2. ICH E6(R3) not named alongside ICH E6 GCP.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Line 27 "It is not the informed consent process" paragraph.
- **Quote:** "Informed consent for clinical research is a specific, regulated activity governed by 21 CFR Part 50, the ICH-GCP guidelines..."
- **Fix:** ICH E6(R3) was finalized in January 2025 and supersedes E6(R2). The current draft references "ICH-GCP guidelines" generically, which is acceptable, but the TODO-verify hedge could mention the R3 finalization. Suggested: extend the TODO-verify to read "...with state-specific provisions varying by jurisdiction; ICH E6 was updated to R3 in 2025 with risk-based and quality-by-design framing relevant to recruitment-platform deployments."

**M3. Diversity Action Plan regulatory landscape has moved past the 2022 draft guidance; FDORA codified the requirement and the FDA finalized the diversity-action-plan guidance in 2024.**

- **Severity:** MEDIUM
- **Expert:** Security, Voice
- **Location:** Multiple paragraphs reference "FDA's 2022 draft guidance on diversity action plans" (lines ~167, ~189). The TODO-verify on line ~189 acknowledges "subsequent regulatory and industry developments have continued to evolve the diversity-action-plan landscape."
- **Fix:** Update the references to acknowledge FDORA (Food and Drug Omnibus Reform Act of 2022, Section 3601) which codified the requirement, and the FDA's June 2024 final guidance on Diversity Action Plans. The TODO-verify hedge can remain. Suggested wording: "FDA guidance on diversity action plans for FDA-regulated trials, codified by FDORA in 2022 and operationalized through the FDA's 2024 final guidance, has raised the operational bar for measuring and improving recruitment representativeness. <!-- TODO: verify; FDORA Section 3601, the FDA's 2024 final guidance on Diversity Action Plans, and subsequent regulatory developments continue to evolve the diversity-action-plan landscape -->"

**M4. The "It is not a clinical-decision tool" assertion would benefit from a TODO-verify hedge or explicit reference to the FDA's CDS guidance.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "It is not a clinical-decision tool" paragraph (line ~31).
- **Fix:** The architectural assertion is correct, but the FDA's regulatory boundary on what constitutes Clinical Decision Support software (and therefore SaMD versus non-device) is governed by Section 3060 of the 21st Century Cures Act and the FDA's CDS guidance. Where the recruitment conversationalist explicitly does not provide clinical decision support, the FDA-positioning is "non-device informational tool"; where the assistant strays into recommendations or condition-specific decision logic, the FDA-positioning shifts. A TODO-verify hedge or a brief reference to the CDS-vs-SaMD line would strengthen the architectural claim.

**M5. Equity-and-representativeness paragraph would benefit from explicit reference to the patient populations historically underrepresented in research, beyond the current racial-and-ethnic minority framing.**

- **Severity:** MEDIUM
- **Expert:** Voice, Security
- **Location:** Multiple paragraphs (lines ~17, ~169, ~191).
- **Fix:** The existing prose covers racial and ethnic minority populations, low-income populations, limited English proficiency, and geographic disparities. Pediatric and pregnant-patient populations, older adults, and patients with disabilities are also historically underrepresented and are explicit targets of FDA's diversity-action-plan guidance. A sentence acknowledging this would strengthen the prose. (Note: the recipe does mention pediatric and surrogate-decision-maker scenarios in the identity-model context, but does not connect them to the equity-and-representativeness frame.)

**M6. The "It is not the informed consent process" assertion is correct but would benefit from an explicit boundary on what the assistant does and does not capture related to the patient's interest signal.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Line 27.
- **Fix:** The existing prose is correct: the assistant does not collect informed consent. The Build section, when written, should explicitly distinguish "interest captured" (allowed; non-consent) from "consent collected" (not allowed; coordinator-only). The Recruitment Reality section's prose is the correct setup; the architecture must follow through.

**M7. The "Sensitive-topic handling within recruitment scope" paragraph names patient-advocate-consultant and IRB review for mistrust-of-clinical-research language but does not name community-research-engagement-team review for racial-and-ethnic-minority outreach explicitly.**

- **Severity:** MEDIUM
- **Expert:** Voice
- **Location:** Lines ~80-82.
- **Fix:** Existing prose covers "religious or cultural considerations (with culturally-appropriate language reviewed by the institution's community-research-engagement teams where applicable)." The mistrust-of-clinical-research language line should also reference community-research-engagement-team review (this is a real and recognizable institutional pattern, not just patient-advocate-consultant review). Suggested: extend "mistrust of clinical research (the assistant acknowledges with calibrated language reviewed by patient-advocate consultants, community-research-engagement teams, and IRB)..."

**M8. The "Continuous emergency screening" paragraph does not name the recruitment-specific acuity classifier extensions that the chapter-9 pattern would predict.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Lines ~83-85.
- **Fix:** The existing prose ("acute emergencies (chest pain, suspected stroke, severe symptom presentations, suicidal ideation)") is correct but generic. The recruitment context introduces specific acuity scenarios: prospective participants who, during the recruitment conversation, surface symptoms that suggest their condition is decompensating beyond what the trial protocol assumes; prospective participants who, during the eligibility prescreen, report a recent change in their condition that may reflect an acute event; prospective participants whose recruitment-conversation context surfaces psychosocial crisis that the recruitment platform is not equipped to handle. The architecture, when written, should specify these recipe-distinct acuity-classifier extensions.

**M9. The "Out-of-scope routing" paragraph does not name a research-compliance-office routing distinct from institutional-patient-services routing.**

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Lines ~85-87.
- **Fix:** Existing prose names the research-compliance office. The architecture should specify the routing rules: clinical questions about existing care → patient's care team; requests for medical advice → institutional patient-services line; requests to enroll without prescreen → coordinator team; attempts to recruit in violation of IRB-approved process → research-compliance office; emergencies → 911. The current prose lists these but the routing-table form would be clearer in the architecture section.

**M10. The TODO-verify on the recruitment-funnel-attrition-rate paragraph (line 13) is correct hedge but the prose could be more specific about the published-literature scope.**

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Line 13.
- **Fix:** Optional. The current prose is accurate at the operational level; the TODO-verify hedge is appropriate.

### LOW Findings

**L1. The Maria opening paragraph contains a single sentence approaching 200 words.** Intentional voice; lands well; flagging only.

**L2. The phrase "investigational therapy" appears once in the prose without explicit definition.** Voice register-consistency; the term is appropriate for a clinical-research recruitment context but a parenthetical inline definition would help non-clinical readers (architects, product managers).

**L3. The phrase "recruitment funnel" appears repeatedly without an inline definition.** Same as L2; a brief inline definition early in The Problem section would help non-clinical readers.

**L4. The "What this recipe is and is not" enumeration uses the form "It is..." / "It is not..." which is clean and CC-voice-consistent, but the negative form is repeated 7 times.** Voice register-consistency; the accumulating-list-as-rhetorical-device is intentional and lands well; flagging only as a potential editor opportunity.

**L5. The "Where the Field Has Moved" subsection's six bullets repeat the "X has Y'd" pattern.** Cosmetic.

**L6. The 13 unresolved TODO-verify markers should be tracked through to publication.** Acceptable as draft hedges; flagging for traceability.

---

## Summary Table

| Severity | Count | Action |
|----------|-------|--------|
| CRITICAL | 1     | Recipe is incomplete. TechWriter must author the missing sections before any further review. |
| HIGH     | 0     | Anticipated 3 HIGH findings on rewrite (multi-asset governance scaffolding; per-cohort monitoring with launch-gate discipline; research-record-class retention with FDA-regulated extensions). |
| MEDIUM   | 10    | Most are content-strengthening updates to the existing prose; some are anticipatory guidance for the rewrite. |
| LOW      | 6     | Cosmetic; flagging only. |

**Verdict: FAIL** (CRITICAL finding present; recipe is structurally incomplete and the rewrite must complete the missing sections before publication).

---

## Recommended Next Steps

1. TechWriter authors the missing sections (General Architecture Pattern through Navigation footer) following the chapter-9 pattern (recipes 11.6 through 11.9 specifically).
2. After the rewrite, this review is re-run end-to-end. The chapter pattern predicts 3 HIGH findings will emerge at that point, matching 11.7, 11.8, and 11.9.
3. The 13 TODO-verify markers should be resolved (or accepted-as-hedge with reviewer signoff) during the TechEditor pass.
4. Multi-asset governance scaffolding (IRB-approved-content corpus, eligibility-evaluation rule library, FDA-strategy artifact, consent-language artifact, vulnerable-population-policy artifact, recruitment-funnel-instrumentation policy, coordinator-team-workflow policy, sponsor-relationship policy, ClinicalTrials.gov-integration policy) should be elevated from prose to architectural primitive when the architecture section is authored — the chapter pattern from 11.6 through 11.9 makes this a HIGH finding if it is not addressed proactively.
5. Per-cohort recruitment-funnel monitoring with launch-gate discipline should be elevated from prose to architectural primitive at the same time, matching the chapter pattern.
6. Research-record-class retention with separate KMS keying, separate access controls, separate audit trail, and FDA-regulated extensions (21 CFR Part 11 electronic-record-and-signature, ICH E6 retention rules, IND/IDE record obligations) should be elevated from prose to architectural primitive at the same time.
