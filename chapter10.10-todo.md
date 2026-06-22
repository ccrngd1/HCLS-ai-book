# Open TODOs: Recipe 10.10: Multilingual Real-Time Medical Interpretation ⭐⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (42 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter10.10-multilingual-realtime-medical-interpretation.md`

- [NEEDS HUMAN] **L11** — Cannot verify specific federal regulatory citation evolution without legal review. The prose references Title VI, Section 1557, and OCR guidance correctly in general terms; a subject-matter expert should confirm the characterization is current.
- [NEEDS HUMAN] **L15** — Cannot verify specific peer-reviewed effect sizes for family interpretation outcomes. General claim is well-established but specific citations need a literature review.
- [NEEDS HUMAN] **L57** — Cannot verify the 1.5-3 second latency target claim against a specific published source. The range is consistent with commercial offerings but needs citation.
- [NEEDS HUMAN] **L97** — Cannot verify specific neural MT BLEU score ranges without access to current benchmark publications. The 35-50 range is plausible for high-resource pairs but needs citation.
- [NEEDS HUMAN] **L129** — Cannot verify NCIHC publication titles and current versions without checking their website at time of build.
- [NEEDS HUMAN] **L135** — Cannot verify specific commercial vendor capabilities and maturity claims without current market research.
- [NEEDS HUMAN] **L137** — Cannot verify specific peer-reviewed LLM translation study results without literature access.
- [NEEDS HUMAN] **L142** — Cannot verify specific VRI vendor feature integration claims without current market research.
- [NEEDS HUMAN] **L144** — Cannot verify current OCR regulatory posture on machine interpretation without legal review.
- [NEEDS HUMAN] **L146** — Cannot verify specific professional organization position statements without checking their current publications.
- [NEEDS HUMAN] **L430** — Expert review S1 (HIGH). Voice-as-biometric-data governance scaffolding requires a new subsection in the architecture companion covering: per-language consent disclosure assets validated by native speakers, per-jurisdiction biometric classification at session start, cross-border-data-flow with EU-resident endpoint routing, per-vendor disclosure-accounting log entries, right-to-deletion workflow with cross-language acknowledgment, voice-cloning and synthetic-voice-detection threat model. Requires deep privacy-law expertise to specify correctly; incorrect specification is worse than the gap.
- [NEEDS HUMAN] **L432** — Expert review S2 (HIGH). Working-store PHI minimization on the real-time hot path. Requires archive-reference discipline redesign of the data model (translation_state table, escalation-archive S3 prefix, encounter_table holds only structural metadata). Requires privacy-architecture expertise to specify correctly without introducing subtle data-flow errors.
- [NEEDS HUMAN] **L434** — Expert review A1 (HIGH). Per-language-pair quality monitoring with per-pair launch-gate discipline. Requires specifying population axes, minimum sample sizes, threshold metrics, launch-gate workflow, and pair-disabled-feature workflow. Substantial new subsection with operational-correctness requirements.

## architecture — `chapter10.10-architecture.md`

- [NEEDS HUMAN] **L11** — Cannot verify current Transcribe language coverage without checking AWS documentation at time of build.
- [NEEDS HUMAN] **L13** — Cannot verify current Translate language pair coverage and Active Custom Translation availability without checking AWS documentation.
- [NEEDS HUMAN] **L19** — Cannot verify current Polly voice catalog and language coverage without checking AWS documentation.
- [NEEDS HUMAN] **L21** — Cannot verify current Connect telephony and SIP integration capabilities without checking AWS documentation.
- [NEEDS HUMAN] **L177** — Cannot verify per-pair vendor coverage benchmarks without institutional evaluation data.
- [NEEDS HUMAN] **L180** (first) — Cannot verify current HIPAA-eligible services list and specific Bedrock models covered under BAA without checking AWS compliance page at build time.
- [NEEDS HUMAN] **L180** (second) — Cannot verify state-level qualified-interpreter requirements without jurisdiction-by-jurisdiction legal research.
- [NEEDS HUMAN] **L184** — Cannot verify available public benchmark sets for medical interpretation without current literature search.
- [NEEDS HUMAN] **L185** — Pricing figures need validation against AWS Pricing Calculator by the implementing team.
- [NEEDS HUMAN] **L221** — Expert review A5 (MEDIUM). Multi-language consent flow build-for-day-one specification. Requires specifying per-language consent-flow asset-development pattern (authoring, audio rendering, literacy-level assessment, right-to-request-human framing, audio-retention-and-biometric language, patient-understanding-verification, native-speaker validation cadence, asset-versioning). Requires language-access program expertise.
- [NEEDS HUMAN] **L359** — Expert review N1 (MEDIUM). Per-device-pattern audio path authentication and encryption. Requires specifying per-device data-in-transit posture across telephonic, WebRTC, kiosk, and mobile surfaces with correct security protocol details. Requires infrastructure-security expertise.
- [NEEDS HUMAN] **L361** — Expert review N2 (MEDIUM). External-vendor speech-and-translation-model API data-in-transit posture. Requires specifying vendor API authentication, TLS posture, per-call disclosure-accounting, vendor BAA scope, and data-residency commitments. Requires vendor-integration security expertise.
- [NEEDS HUMAN] **L438** — Expert review S3 (MEDIUM). LLM-based translation path faithfulness check expansion. Requires expanding check_faithfulness to specify per-layer checks (structured-output schema validation, citation-grounding, LLM-judge faithfulness scoring, rule-based contradiction detection, omission detection, hallucination detection, cultural-framing flagging). Substantial pseudocode expansion with correctness requirements.
- [NEEDS HUMAN] **L440** — Expert review S4 (MEDIUM). Foundation-model prompt-injection architectural specification. Requires promoting delimited-input framing to architectural primitive with per-language verification, delimiter-spoofing escape, jailbreak-test corpus, denied-topics list, output-validation. Requires LLM-security expertise.
- [NEEDS HUMAN] **L779** — Expert review A3 (MEDIUM). Latency-budget-overrun graceful-degradation specification. Requires per-pair budget allocation, per-utterance vs per-window vs per-encounter monitoring, degradation responses, user-visible indicators, and pseudocode update. Substantial new subsection.
- [NEEDS HUMAN] **L781** — Expert review A7 (MEDIUM). Conversational-context-briefing-with-confidentiality-scoping for human handoff. Requires per-content-category briefing-scope rules, briefing-delivery options per deployment mode, briefing-latency budget, and audit integration. Requires clinical-workflow expertise.
- [NEEDS HUMAN] **L873** — Expert review A4 (MEDIUM). Foundation-model and prompt and per-pair-vendor-configuration versioning. Requires specifying versioned artifact management, Bedrock inference profiles, held-out evaluation sets, model_versions stamping expansion, and per-pair canary deployment. Substantial new subsection.
- [NEEDS HUMAN] **L1038** — Performance benchmark figures need validation from deployed pairs. Cannot verify without institutional evaluation data.
- [NEEDS HUMAN] **L1096** — Expert review A6 (MEDIUM) and N4 (LOW). Disaster Recovery Topology. Requires specifying per-stage failover policy, cross-region failover with per-jurisdiction data-residency constraints, failover-detection thresholds, failover-back triggers, and testing cadence. Substantial new subsection requiring operational-architecture expertise.
- [NEEDS HUMAN] **L1106** — Expert review A2 (MEDIUM). Multi-vendor abstraction layer architectural primitive. Requires specifying per-vendor abstraction interfaces, fallback-detection thresholds, fallback-state-management, disclosure-accounting integration, faithfulness calibration, latency-budget management, versioning, and capability discovery. Substantial new subsection.
- [NEEDS HUMAN] **L1186** — Cannot verify repository names and locations without checking at time of build.
- [NEEDS HUMAN] **L1192** — Cannot verify specific blog post URLs without confirming they exist.
- [NEEDS HUMAN] **L1214** — Cannot verify ISO 13611 standard URL and current version without checking ISO website.
- [NEEDS HUMAN] **L1215** — Cannot verify ASTM F2089 standard number and current version without checking ASTM website.
