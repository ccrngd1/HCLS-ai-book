# Expert Review: Recipe 3.5 - Lab Result Outlier Detection

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-15
**Recipe file:** `chapter03.05-lab-result-outlier-detection.md`

---

## Overall Assessment

**Verdict: PASS**

This is the strongest fifth-recipe-in-a-chapter writing in the cookbook to date and the densest clinically-grounded teaching in Chapter 3. The 6:42 a.m. potassium-7.8 vignette (74-year-old admitted overnight for community-acquired pneumonia, peripheral draw that sat at the nursing station 90 minutes, hemolysis index 4+, the pseudohyperkalemia confirmed by a recollect showing K 4.2, the patient eating oatmeal while the rapid response team assembles) lands the operational reality of pre-analytical artifact in three paragraphs. The three-category framing of outliers (real-and-critical, real-and-unexpected, not-real) is the right teaching anchor because each category requires structurally different detection, routing, and clinical workflow, and the recipe is explicit about it. The five-outlier-types taxonomy (hard critical, delta-check failure, population-z improbability, clinical implausibility, specimen artifact) is operationally accurate and matches what a senior pathologist or clinical chemist would describe. The reference-range subsection is the most substantive treatment of reference-range complexity in the cookbook (age and sex banding, pregnancy physiology, population-specific intervals with explicit attention to the 2021 NKF-ASN race-coefficient revision, method-specific calibration, critical vs action vs reference tiers, source-and-versioning). The CLSI AUTO10 reference for autoverification validation is correctly cited. The autoverification-as-the-flip-side-of-outlier-detection framing is architecturally correct.

The Honest Take is publication-ready and should be preserved verbatim. The seven lessons (delta checks do more work than any other component, specimen quality fusion is the biggest unspoken lever, critical-value callback workflow is more complex than it looks, reference ranges encode more complexity than expected, autoverification is where the ROI lives, patient-specific baselines beat population baselines for patients with history, cross-test coherence rules surprised me) land the right teaching priorities. The closing trap warning ("do not let 'flag rate' become the primary business metric") is the kind of operations-engineer voice that distinguishes the cookbook from documentation. The "do delta checks well" framing on first-deployment prioritization is operationally correct: tuning delta thresholds analyte-by-analyte against the lab's actual population is unglamorous work that pays off more than any model improvement, and the recipe says so plainly.

The hybrid streaming-plus-batch architecture (real-time screen for autoverification gating, patient-baseline path for delta and z-score, cross-test path for panel coherence and Isolation Forest, severity tiering driving routing into autoverify-with-flag vs tech-review-hold vs critical-callback vs recollect-requested, feedback capture closing the loop into rule tuning and supervised retraining) is the architecturally correct factoring. The decision to run different paths at different latency regimes (tens-of-ms for the autoverification gate, hundreds-of-ms for patient-baseline statistics, sub-second batched for panel coherence) is the architectural reframe most first-time builders miss, and the recipe is explicit about it.

The Why This Isn't Production-Ready section is dense and substantive (clinical rule authoring as a continuous laboratory program, CLIA validation with explicit CLSI AUTO10 reference, critical-value callback compliance requirements, LIS integration ordering and corrections handling, method and reagent change management, reference range lifecycle, POCT vs central-lab differences, reference-lab send-out handling, patient-level alerting suppression governance, bias and equity monitoring including the creatinine-GFR race coefficient, FDA LDT 2024 rule with phased implementation, disaster recovery for the lab, autoverification-rate-as-business-decision). Thirteen substantive bullets, each tied to a real production concern.

Style hygiene is exceptionally clean: zero em dashes (direct U+2014 character check across the file: zero matches), no marketing language, no documentation-voice, 70/30 vendor balance preserved cleanly. The conceptual sections (Problem, Technology, General Architecture Pattern) are vendor-neutral and a reader on GCP or Azure could substitute their cloud's primitives without rewriting any of the teaching; AWS service names enter at the AWS Implementation section and stay there. HTML-comment TODOs (six total) are forward placeholders for industry-figure citation (CAP/CLSI pre-analytical error rates, lab pre-analytical error cost estimates, FDA LDT rule status verification, CAP Q-Probe / Q-Tracks benchmark figures, validated LLM-assisted lab-interpretation patterns, aws-samples laboratory-analytics repo verification), all the chapter-2-and-3-settled posture.

The findings cluster around two patterns: (1) recurring chapter-wide gaps (idempotency, DLQs, PHI minimization, subgroup governance) that have surfaced in every chapter-3 recipe and are now strong appendix-consolidation candidates, and (2) prose-vs-pseudocode asymmetry where the Honest Take and Why This Isn't Production-Ready sections call out a discipline that the canonical pseudocode walkthrough doesn't reflect. The most-consequential prose-vs-pseudocode gaps are method/reagent-change handling in delta checks (the recipe's prose says "the fix is to harmonize against the method and track method changes in the delta calculation," but Step 4's `patient_baseline_checks` doesn't compare `method` between the current and previous result) and cross-test coherence rules (the Honest Take identifies these as "one of the most reliable layers in the pipeline," but no Step in the pseudocode demonstrates a coherence check; only the panel-level Isolation Forest in Step 7).

There are no CRITICAL findings and no HIGH findings. The MEDIUM cluster includes outcome-event idempotency at the EventBridge → feedback-capture path (recurring trigger-idempotency pattern across Recipes 2.4-2.10 and 3.1-3.4, eleventh consecutive recipe); no DLQ or poison-message handling for the result-normalizer, real-time-outlier-service, or feedback-capture Lambdas (architecturally critical for a system that gates autoverification, where a dropped event is a result released to chart without an outlier check); CLIA critical-value-callback timing/read-back/escalation discipline named in prose but not in the routing pseudocode; method/reagent-change handling in delta checks not in pseudocode despite being called out in prose; reference-range version not propagated into the routing event or audit index despite being captured in Step 1; cross-test coherence rules called out as one of the most reliable layers but absent from the pseudocode; SNS critical-callback payload PHI minimization not stated in the pseudocode (the chapter-3-settled "event-id-only" convention is implied via the Python companion but not the main recipe); subgroup data governance acknowledged in prose but architectural artifacts unspecified.

LOW findings are operational and editorial polish: per-consumer IAM scoping for shared resources (patient-context-cache, outlier-events bus); HL7 v2 MLLP bridge security posture not specified; Bedrock LLM-assisted-interpretation BAA-discipline forward reference missing; Transfer Family SFTP source-IP allowlist and authentication not specified; VPC endpoint precision (recurring); VPC Flow Logs not explicitly required (recurring); central-line-recollect framing in opening vignette; sample timestamps use future dates (recurring); HTML-comment TODOs to resolve before publication; severity-tier mapping between flag-level and routing-level in pseudocode is implicit; performance-benchmark numbers should be flagged as illustrative until measured.

Priority breakdown: 0 CRITICAL, 0 HIGH, 8 MEDIUM, 9 LOW.

The risk profile is comparable to Recipe 3.4 (medication dispensing): the lab outlier pipeline gates autoverification, and a result released to chart without screening can produce direct patient harm through pseudohyperkalemia-driven inappropriate treatment, missed delta-check signals for acute bleeding or renal failure, or false reassurance from artifactual results. The recipe correctly addresses this in the three-categories framing, the alert-fatigue subsection, the CLIA validation discussion, and the disaster-recovery paragraph. The fairness surface area is also distinctive: the recipe explicitly names the creatinine-GFR race coefficient revision and population-aware ranges, which is the right discipline.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

- BAA posture is explicit: "AWS BAA signed. Every service above is HIPAA-eligible under the BAA when configured properly." Link points to the canonical [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/), not an invented URL.
- Encryption coverage is complete across every PHI-bearing store. S3: SSE-KMS with customer-managed keys; DynamoDB: encryption at rest with CMK; Kinesis: SSE with CMK; OpenSearch: at rest and in transit; SageMaker: KMS on volumes, model artifacts, Feature Store. TLS 1.2 or higher in transit everywhere.
- IAM is least-privilege with concrete examples: real-time outlier Lambda gets `dynamodb:GetItem` on patient-context-cache, `sagemaker-featurestore-runtime:GetRecord` on analyte-cohort-baselines, `s3:GetObject` on lab-rules bucket, `events:PutEvents` to the outlier-events bus, `kinesis:GetRecords`. Result normalizer Lambda: `kinesis:GetRecords`, `dynamodb:PutItem`. Callback Lambda: `sns:Publish` only on the callback topic. Batch pipelines scoped to specific S3 prefixes. "No `*` actions in production" is stated explicitly.
- CloudTrail data events on patient-context-cache, lab-rules bucket, feedback-labels bucket, OpenSearch domain operations, and the critical-value callback topic are required, with the explicit framing "Every flag decision and every callback is audit-logged." This is the audit-trail discipline a Joint Commission lab inspector or a CLIA surveyor actually uses.
- Retention posture is correct and substantive: "CLIA baseline is 2 years for most records, 5 years for blood bank. State regulations often extend this (5-10 years common). Pathology reports often 20 years or longer. Confirm retention schedule with legal and compliance before production." This reflects the multi-regime reality of laboratory recordkeeping.
- CLIA and Lab Regulatory row is unusually substantive: "The pipeline participates in a regulated laboratory workflow. Critical-value callbacks have documented-timing requirements under CLIA and state licensure. Autoverification rules require documented validation per CLSI AUTO10. Changes to rules require laboratory director sign-off. Validation records retained per regulatory retention schedule (minimum 2 years under CLIA; longer in many states)." Names the governance posture most lab analytics deployments fail to enforce.
- Clinical Governance row names the right co-ownership: "Lab director signs off on all rule thresholds, severity tier definitions, and callback protocols. Pathology and clinical leadership jointly own the governance of outlier suppression rules ... Changes logged and periodically reviewed."
- Synthetic data discipline is explicit and correct. Synthea is named with a verified GitHub link. MIMIC-IV is correctly identified as requiring PhysioNet credentialing and a data use agreement. LOINC is correctly named as free from Regenstrief. "Never use real PHI in development" is stated.
- The "Why This Isn't Production-Ready" section's FDA LDT paragraph is the most current FDA framing in any cookbook recipe to date: it correctly identifies the 2024 final rule on laboratory-developed tests, the phased implementation through the late 2020s, the implication that autoverification algorithms altering clinical reporting may cross into regulated software territory, and the discipline of coordinating with regulatory affairs and legal before production deployment. The HTML-comment TODO acknowledging the need to verify current rule status before publication is the right discipline.

#### Finding S1: SNS Critical-Callback Payload PHI Minimization Not Explicit in Pseudocode

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 6 `route_result`, the `"critical_callback"` branch (`SNS.Publish(topic = CRITICAL_CALLBACK_TOPIC, message = build_callback_payload(outlier_event))`); Why-These-Services Amazon SNS paragraph; Prerequisites IAM row.
- **Problem:** The pseudocode's SNS message is constructed by `build_callback_payload(outlier_event)` with no explicit specification of what fields are included. The `outlier_event` dict (constructed earlier in Step 6) carries `patient_id`, `loinc_code`, `loinc_display`, `value`, `unit`, `accession`, `flags` (which include actual lab values, threshold values, delta deltas), `specimen_quality`, `patient_context_summary` (which includes age, sex, acuity, active problems with ICD-10 codes, active medications, dialysis status), and `previous_result`. If `build_callback_payload` serializes the entire outlier_event into the SNS message, the payload carries a substantial PHI surface through SNS infrastructure, downstream callback platforms (Vocera, TigerConnect, custom services), pager-channel SMS, Teams or Slack webhooks, and any logs those subscribers generate. SMS or pager notifications can be visible on lock screens; Teams or Slack subscribers retain message history; mobile push notifications appear in the device's notification shade.

  Recipe 3.1's expert review settled the chapter discipline: notifications carry the event ID only, and the analyst UI fetches the full record by ID so the notification channel never carries PHI. Recipe 3.3 reaffirmed it, and Recipe 3.4's S1 finding called it out for medication dispensing. Recipe 3.5's Python companion (per the existing code review's Healthcare-Specific Requirements section) does the right thing: `_publish_critical_callback` builds a message with the minimum-necessary fields. But the main recipe's pseudocode doesn't state the discipline, so a reader who copies the walkthrough without reading the Python companion (or implements in a different language) will not know to constrain the payload.

  The LOINC display name in the subject line is itself a PHI-adjacency concern that the recipe's Python companion accepts as a teaching example. For a routine potassium critical value the disclosure is minimal; for high-stigma test types (HIV viral load LOINC 20447-9, hepatitis C viral load LOINC 20416-4, syphilis serology, drug-of-abuse panels, mental health markers like lithium level for psychiatric monitoring, gender-affirming hormone levels), the test name itself is a diagnostic disclosure that becomes visible on a recipient's lock screen if the SMS or pager notification renders the subject. CLIA requires the callback to occur, but the callback workflow does not require that the test identity be transmitted through unencrypted lock-screen-visible channels.
- **Fix:** Update the Step 6 pseudocode `"critical_callback"` branch to make the payload-minimization discipline explicit:
  ```
  // The SNS message carries the event ID, severity, and a coarse routing tier
  // only; the callback service fetches the full record (test, value, patient,
  // context) by ID before initiating the callback. PHI does not transit
  // through SNS, downstream paging or messaging platforms, or any logs they
  // generate. For high-stigma test types (HIV viral load, hepatitis C panels,
  // syphilis serology, drug screens, gender-affirming hormone monitoring,
  // psychiatric medication levels), even the LOINC display name is a
  // diagnostic disclosure and should not appear in the notification subject.
  SNS.Publish(
      topic   = CRITICAL_CALLBACK_TOPIC,
      message = {
          event_id:    outlier_event.event_id,
          severity:    "critical_callback",
          fetch_by_id: True
      },
      attributes = {
          "patient_location": enriched_result.patient_attributes.location,
          "severity":         "critical_callback"
      }
  )
  ```
  Add a one-line note to the Why-These-Services paragraph for SNS naming this convention. Cross-link to the Python companion's `_publish_critical_callback` implementation. Same chapter-3-settled minimum-PHI-in-notification pattern as Recipes 3.1, 3.3, 3.4.

#### Finding S2: Subgroup Data Governance for Fairness Monitoring Not Specified at the Infrastructure Level

- **Severity:** MEDIUM
- **Expert:** Security / Compliance
- **Location:** "The Technology" reference-range subsection (population-specific intervals paragraph naming the creatinine-GFR race coefficient revision); "Why This Isn't Production-Ready" Bias and Equity Monitoring bullet ("Subgroup monitoring dashboards (flag rate by patient race, ethnicity, language, insurance status) are part of the minimum deployment").
- **Problem:** The recipe is unusually explicit about fairness considerations for lab analytics: it names the creatinine-GFR race coefficient revision (a real, recent, and well-documented change in clinical practice driven by the 2021 NKF-ASN task force), names population-aware reference range validation as ongoing rather than check-the-box, and explicitly says subgroup monitoring is part of the minimum deployment. This framing is exactly right.

  But the architectural artifacts that make subgroup monitoring binding rather than aspirational are not specified: where the demographic and patient-attribute store lives, who has read access, how it joins to outlier events and override records, what the audit trail for subgroup queries looks like, what IAM scope the QuickSight dashboard role and the retraining job role need on demographic data, and how the dashboard avoids exposing row-level demographic data to dashboard viewers.

  Race and ethnicity data has different governance from PHI in some regulatory regimes; some state insurance and pharmacy laws restrict secondary use of race and ethnicity data more tightly than HIPAA restricts PHI per se. The recipe's framing-level treatment is correct; the architectural backstop that operationalizes it is missing.

  Same finding shape as Recipes 3.2 S2, 3.3 S2, and 3.4 S2.
- **Fix:** Add a "Subgroup data access" paragraph or row to Prerequisites: "Subgroup performance and override-pattern monitoring requires read access to patient demographic attributes (age band, sex, race, ethnicity, preferred language, insurance type). These attributes may be governed differently from clinical PHI in some regulatory regimes; restrict read access to the demographic-and-attribute store to the retraining job role and the QuickSight dashboard role, and audit subgroup queries via CloudTrail data events. The QuickSight dashboard backed by Athena should query an aggregated subgroup-metrics table (override rates by analyte by patient demographic, autoverification rates by demographic, specimen-rejection rates by collection unit), not the raw demographic-joined outlier archive, so that dashboard-user access does not require row-level read on the subgroup attributes." Strengthen the IAM row with the per-role scope: retraining job role gets `glue:GetTable` and `s3:GetObject` only on the demographic-joined view; QuickSight dashboard role gets read-only on the aggregated subgroup-metrics table.

#### Finding S3: Per-Consumer IAM Scoping for Patient-Context Cache and Outlier-Events Bus Not Explicit

- **Severity:** LOW
- **Expert:** Security
- **Location:** Step 2 `enrich_with_patient_context` (`DynamoDB.GetItem("patient-context-cache", ...)`); Step 6 `route_result` (`EventBridge.PutEvent(bus = "lab-outlier-events", ...)`); Prerequisites IAM row.
- **Problem:** The patient-context-cache DynamoDB table is read by the real-time outlier service Lambda and (per the General Architecture Pattern's "Patient-context cache" subsection) populated from EHR and LIS feeds with defined freshness windows. The lab-outlier-events EventBridge bus is written by the real-time outlier Lambda and the batch processing jobs, and read by five subscribers (critical-value-callback Lambda, OpenSearch audit indexer, tech-review-queue Lambda, autoverify-release Lambda, feedback-capture Lambda).

  The recipe gives generic least-privilege framing in the IAM row but doesn't break out per-consumer roles for these shared resources. For a system that gates autoverification, the blast-radius minimization matters: a compromised role with broad cache-write access could silently corrupt patient context (stale demographics, wrong dialysis flag, wrong pregnancy status), which would propagate into wrong reference-range selection (pregnancy-shifted ranges not applied), wrong delta-check calibration (dialysis-patient potassium not suppressed), and wrong cohort-z lookup (wrong cohort key built). All of these are autoverification-correctness failures.
- **Fix:** Strengthen the Prerequisites IAM row with per-consumer scoping: "Real-time outlier service Lambda role: `dynamodb:GetItem` on patient-context-cache only (no write). Cache-refresher Lambda role (populated from EHR/LIS feeds): `dynamodb:PutItem` and `dynamodb:UpdateItem` on patient-context-cache only; `kinesis:GetRecords` on the EHR event stream. Critical-value callback Lambda role: consumes events from the bus; `sns:Publish` on the callback topic only; no `events:PutEvents`. Autoverify-release Lambda role: consumes events from the bus; permission to write to the LIS-to-EHR bridge (HL7 v2 send queue or FHIR write API), no broader EHR access. Feedback-capture Lambda role: `dynamodb:UpdateItem` on a labels store only; `s3:PutObject` on the labels-parquet bucket only; `events:PutEvents` not granted (it consumes events, doesn't produce them)."

#### Finding S4: HL7 v2 MLLP Bridge Security Posture Not Specified

- **Severity:** LOW
- **Expert:** Security / Networking
- **Location:** Why-These-Services "Amazon MQ for HL7 v2 ingress" paragraph ("LIS-to-AWS integration usually uses MLLP (Minimal Lower Layer Protocol) over TCP. An on-premises MLLP listener (Mirth Connect, Rhapsody, Corepoint, or a simple listener built on the HL7 libraries) republishes to Amazon MQ (ActiveMQ) or to a Kinesis-backed ingress Lambda"); Architecture Diagram (`M[On-Prem MLLP Bridge\n+ Amazon MQ]`); Prerequisites Lab Integration row.
- **Problem:** MLLP itself has no native authentication or encryption (it is TCP framing over a stream socket). Production HL7 v2 deployments wrap MLLP in TLS (often called MLLP over TLS or MLLPS) and authenticate connections via mutual TLS with hospital-issued certificates. The on-premises MLLP listener is the PHI ingress surface from the hospital's LIS into AWS; it traverses the boundary between the hospital network and the AWS VPC via Site-to-Site VPN or AWS Direct Connect, both of which have their own configuration disciplines. The recipe describes the MLLP bridge at a high level without addressing MLLP-over-TLS vs unencrypted MLLP (the latter is still common in legacy deployments and is increasingly out of policy), Site-to-Site VPN vs Direct Connect for the on-premises-to-AWS connection (Direct Connect is the production standard for high-volume PHI ingress), mutual TLS or token-based authentication on the MQ broker, and DMZ deployment of the bridge. Same finding shape as Recipe 3.4 S3.
- **Fix:** Add a one-paragraph note to the Why-These-Services Amazon MQ paragraph: "The on-premises MLLP listener is the PHI ingress surface into AWS. Wrap MLLP in TLS (MLLPS) with mutual TLS authentication; deploy the listener in a DMZ or integration tier, not on the clinical network; connect to AWS via Direct Connect for production volumes (Site-to-Site VPN is acceptable for lower volumes and pilot deployments); authenticate the AWS-side MQ broker via mutual TLS or short-lived IAM-derived tokens rather than long-lived shared secrets." Add to Prerequisites Lab Integration row: "MLLP-over-TLS with mutual TLS authentication is the production posture; raw MLLP is acceptable only for development environments with synthetic data."

#### Finding S5: Bedrock LLM-Assisted Interpretation Lacks BAA-Discipline Forward Reference

- **Severity:** LOW
- **Expert:** Security / Healthcare Compliance
- **Location:** Why-These-Services "Amazon Bedrock for LLM-assisted interpretation (optional, advanced)" paragraph; "The Technology" Statistical Methods That Fit subsection ("LLM-assisted interpretation (emerging). A HIPAA-eligible LLM can read the result alongside the patient's recent clinical notes ..."); Variations "LLM-assisted pathology review queue prioritization" extension.
- **Problem:** The Bedrock paragraph correctly identifies the experimental nature ("Not a primary detector; a triage accelerator for the review queue"), the validation requirement, and the per-result cost concern. The Variations extension correctly says "Not a decision-maker; a prioritization aid." What's missing is the BAA-discipline forward reference that Chapter 2's recipes (especially 2.7-2.10) settled as the right framing for generative AI in PHI-bearing flows: Bedrock with Amazon foundation models is HIPAA-eligible under the BAA, but third-party models on Bedrock have differing BAA postures, and the model's terms of service must be reviewed before PHI-bearing prompts are sent. The recipe's "HIPAA-eligible LLM" framing doesn't differentiate. Also missing: minimum-necessary prompt construction (the prompt should not carry the entire chart; it should carry only the relevant note excerpts, the flagged result, and the active medication and problem lists), output filtering for clinical-recommendation hallucinations, and a full prompt-and-response audit trail. Same finding shape as Recipe 3.4 S4 and Recipe 3.3 V2.
- **Fix:** Expand the Bedrock paragraph: "A HIPAA-eligible LLM through Bedrock can read the patient's clinical context and the flagged result together and produce a triage recommendation. Use only models with BAA coverage on the inference path (Amazon's foundation models on Bedrock are HIPAA-eligible; third-party models on Bedrock have differing BAA postures, and the model's terms of service must be reviewed before PHI-bearing prompts are sent). Construct prompts with minimum-necessary context (the relevant note excerpts, the flagged result, and the active medication and problem lists; not the full chart), filter outputs for clinical-recommendation hallucinations, and log every prompt and response to the audit trail tied to the triage decision. See Chapter 2's generative AI recipes for the established BAA discipline." Add a forward reference to the Chapter 2 recipes that established this pattern.

#### Finding S6: Transfer Family SFTP Source-IP Allowlist and Authentication Method Not Specified

- **Severity:** LOW
- **Expert:** Security / Networking
- **Location:** Architecture Diagram (`C[Reference Lab Feeds\nSFTP / HL7 batch] --> E[AWS Transfer Family]`); Why-These-Services section (Transfer Family is named in the IAM and Prerequisites tables but not given a dedicated paragraph).
- **Problem:** Reference labs (Quest, LabCorp, specialty molecular labs) typically push send-out result files to a known SFTP endpoint via scheduled batch transfers. AWS Transfer Family supports SFTP, FTPS, and AS2 with KMS encryption at rest, but the recipe doesn't specify (a) public vs VPC endpoint for the Transfer Family server (a public endpoint is operationally easier but increases attack surface), (b) authentication method (SSH key for service-account-style access, password with IAM mapping, or a custom identity provider backed by Lambda), or (c) source-IP allowlist for the reference lab's known egress ranges. For PHI ingress from a third-party data sender, the source-IP allowlist combined with mutual key exchange is the production-standard control; the recipe assumes the reader knows this but doesn't name it.
- **Fix:** Add a Transfer Family note to the Why-These-Services section: "AWS Transfer Family for the reference-lab SFTP feed. Use a VPC endpoint (not public) for Transfer Family in production; restrict source IPs to the reference lab's known egress ranges via security group rules or IAM-resource-policy conditions; authenticate via SSH key with the reference lab providing the public key out of band, rotated per the lab's key-rotation policy; encrypt at rest with customer-managed KMS keys; CloudTrail data events on every PutObject and GetObject on the reference-lab inbound prefix."

### Architecture Expert Review

#### What's Done Well

- The hybrid streaming-plus-batch architecture (real-time screen for autoverification gating, patient-baseline path for delta and z-score, cross-test path for panel coherence and Isolation Forest, severity tiering driving routing into autoverify-with-flag vs tech-review-hold vs critical-callback vs recollect-requested, feedback capture closing the loop) is the architecturally correct factoring for this problem class. The decision to run the autoverification gate at tens-of-ms and the panel-level multivariate scoring at sub-second batched is the architectural reframe most first-time builders miss, and the recipe is explicit about it.
- The five-outlier-types taxonomy (hard critical, delta-check failure, population-z improbability, clinical implausibility, specimen artifact) is the right teaching anchor, and the recipe's prioritization guidance ("A useful v1 usually starts with delta checks plus specimen artifact fusion, because those two together catch most of the spurious critical values and the clinically meaningful changes") is operationally correct. This matches what every senior pathologist or clinical chemist would say if asked to advise a first-time builder.
- Reference-data versioning is named explicitly: "Storing them as first-class data with versioning is important because ranges change when methods change, and reproducing a past alert requires knowing which range was in force." The Step 1 `normalize_result` pseudocode correctly captures `reference_range_version` on the canonical result. This is the discipline most first-time builders skip and then fail to satisfy a CLIA inspection or CAP survey.
- The patient-context-cache pattern (DynamoDB with rolling-window recent-results store, baseline statistics computed on read or pre-computed) is the right factoring for the latency budget. The recipe correctly identifies that the recent-results store is what enables delta checks and patient-baseline z-scores without hitting the LIS for every incoming result.
- Severity tiering as a first-class architectural concern (autoverify-with-flag, tech-review-hold, critical-callback, recollect-requested) with explicit operational distinctions is the architecturally correct factoring. The CLIA-regulated callback workflow is correctly identified as separate from fire-and-forget alerting.
- The autoverification-as-flip-side-of-outlier-detection framing is architecturally correct and is the recipe's biggest pedagogical contribution: "Autoverification is 'is this result safe to release without human review?' and outlier detection is 'does this result look unusual enough that someone should pay attention to it?' They share the input data, they share the model machinery, and they produce complementary outputs (release vs. hold; alert vs. quiet). Serious deployments unify them rather than running them as separate pipelines."
- The "Why This Isn't Production-Ready" section is dense and substantive: thirteen bullets covering clinical rule authoring as a continuous program, CLIA validation with explicit CLSI AUTO10 reference, critical-value callback compliance requirements, LIS integration ordering and corrections, method and reagent change management, reference range lifecycle, POCT vs central-lab differences, reference-lab send-out handling, patient-level alerting suppression governance, bias and equity monitoring with explicit creatinine-GFR race coefficient framing, FDA LDT 2024 rule, disaster recovery, autoverification rate as a business decision. Each bullet is tied to a real production concern.
- Cost estimate is defensible and correctly framed against cost-avoidance: pre-analytical error recollections cost $10-50 per event in supplies and labor plus the unmeasurable clinical-workflow cost; sentinel-event-level errors from a missed critical value have costs that dwarf the infrastructure. The HTML-comment TODO for verification of CAP and Institute for Quality in Laboratory Medicine published estimates is the right discipline.
- Implementation-time tiers (4-7 months Basic, 9-15 months Production-ready, 12-24 months for variations) are realistic and resist optimism bias.
- Variations and Extensions covers the right adjacent patterns at the right depth (POCT-specific path, blood bank, microbiology, coagulation specialty, oncology biomarker trends, therapeutic drug monitoring, cross-facility harmonization, patient-facing context, LLM-assisted prioritization, sepsis-early-warning integration). The sepsis integration explicitly references Recipe 3.7, which is the right cross-recipe linkage.

#### Finding A1: Outcome-Event Idempotency Not Modeled at the Feedback-Capture Lambda

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 8 `on_tech_review_decision` and `on_recollect_result` (consumed via EventBridge by the feedback-capture Lambda); Architecture Diagram (`N --> O5[AWS Lambda\nfeedback-capture]`).
- **Problem:** The architecture is event-driven from the tech review tooling and the recollect-resulting workflow to the feedback-capture Lambda via EventBridge. EventBridge guarantees at-least-once delivery; Lambda asynchronous invocation also retries on failure. If EventBridge redelivers an event (the Lambda's first attempt timed out, the analyst tooling's PutEvents call retried after a transient error, or any of the failure modes documented in the recurring trigger-idempotency findings across Recipes 2.4-2.10 and 3.1-3.4), the feedback-capture runs twice on the same outcome. Each run:

  1. **Updates the OpenSearch outlier record with the tech review decision.** `on_tech_review_decision` calls `OpenSearch.Update("lab-outliers", decision_event.outlier_event_id, outlier)`. The update is idempotent in the document-replacement sense, but a redelivered event with a slightly different `decided_at` timestamp overwrites the resolution timestamp inconsistently, and any downstream consumer of "first-decision time" or "tech review duration" metrics gets noisy data.

  2. **Writes a fresh label row to S3 with a UUID-keyed path.** Both `on_recollect_result` paths (`label = "confirmed_artifact"` and `label = "confirmed_real"`) call `S3.PutObject(... key = date_partitioned_key(...) + "/" + uuid() + ".parquet", ...)`. Two label rows for the same recollect outcome get picked up by the next quarterly retraining job. This biases the supervised classifier's training distribution toward whichever cases happened to be retried, and degrades the confirmed-artifact-vs-confirmed-real signal which is the recipe's most-emphasized feedback signal.

  3. **Emits duplicate `flag_tech_decision` CloudWatch metrics**, double-counting in operational dashboards. For override-rate-driven rule retirement (which the recipe explicitly identifies as part of the rule-tuning loop in the Retraining and Threshold Tuning paragraph), doubled override counts directly distort which rules look high-override and get retired. For an autoverification-gating system this is consequential: a rule retired because of artificially-doubled override counts is a missed-future-flag, which can become a missed-future-artifactual-result-released-to-chart.

  Same recurring trigger-idempotency pattern as Recipes 2.4-2.10, 3.1, 3.2, 3.3, 3.4 (eleventh consecutive recipe). The fix template is the same.
- **Fix:** Two-part fix:
  1. Derive a deterministic event key from the source event identifier (`outlier_event_id + decision` for tech review; `original_outlier_event_id + recollect_accession` for recollect outcomes), and use it as a write-once guard in DynamoDB:
     ```
     event_key = decision_event.outlier_event_id + "|" + decision_event.decision
     try:
         DynamoDB.PutItem(
             table = "processed-feedback-events",
             item = { event_key: event_key, processed_at: NOW() },
             condition = "attribute_not_exists(event_key)"
         )
     except ConditionalCheckFailedException:
         emit_metric("feedback_event_duplicate_dropped", 1)
         RETURN
     ```
     The processed-feedback-events table can have a TTL of 90 days. This prevents the OpenSearch update, the label write, and the metric emissions from running twice for the same event.
  2. Add a "Trigger idempotency" bullet to "Why This Isn't Production-Ready" tying the discipline to the recurring chapter pattern.

  This is now the eleventh consecutive recipe with this finding (2.4-2.10, 3.1, 3.2, 3.3, 3.4, 3.5). The cookbook editor should treat the trigger-idempotency appendix as the highest-leverage cookbook-wide editorial investment. The per-recipe editorial loop is producing diminishing returns.

#### Finding A2: No DLQ or Poison-Message Handling for Result-Normalizer, Real-Time-Outlier-Service, or Feedback-Capture Lambdas

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram (`H[AWS Lambda\nresult-normalizer]`, `J[AWS Lambda\nreal-time-outlier-service]`, `O5[AWS Lambda\nfeedback-capture]` all without `OnFailure` destinations); Prerequisites table.
- **Problem:** No Dead Letter Queue or `OnFailure` destination is configured for any Lambda in the pipeline. The recipe's own "Why This Isn't Production-Ready" section names "Disaster recovery for the lab" as a core production concern and says "The outlier pipeline is in the result-release path. If the pipeline is down, results cannot be held indefinitely; clinical care needs results." But the per-event poison-message recovery discipline is at a different abstraction level than that paragraph addresses.

  Specific failure modes that surface here:

  - **Result-normalizer Lambda fails on a malformed message** (the LIS emits an unexpected HL7 segment, the LOINC crosswalk lookup fails because of a stale crosswalk version, the unit-conversion encounters an unhandled unit string, the patient master-index resolution fails). Lambda's default async retry behavior is two retries over six hours and then drop. The result is silently lost: no canonical event reaches the outlier service, no autoverification decision is made, the LIS's downstream release path (which assumes the canonical-result and outlier-screen pipeline has run) is left in an unknown state. For a CLIA-regulated workflow this is a result that cannot be accounted for in the lab's audit trail, which is itself a CLIA finding.

  - **Real-time-outlier-service Lambda fails during cache lookup or rule evaluation** (DynamoDB throttle, Feature Store cold-cache miss timeout, S3 read on the rule library timeouts). Same retry-then-drop pattern. The result passes through unscored. For an autoverification-gating system this is the failure mode the entire pipeline is designed to prevent: a result released to chart without an outlier check is exactly the case the system is supposed to catch.

  - **Feedback-capture Lambda fails on a malformed event** (the tech-review tooling emits an unexpected decision value, the outlier_event_id references a record not in OpenSearch due to retention rotation, the recollect event has a date format the parser doesn't handle). The label is never written, the OpenSearch record stays "open" forever, the confirmed-artifact-vs-confirmed-real signal that the recipe identifies as the highest-value training signal is silently lost.

  Without DLQs, these failures appear only in CloudWatch Logs and require log-trawling to discover. For a system whose value proposition is catching autoverification artifacts, silently-failing scoring is the worst possible failure mode.
- **Fix:** Add three SQS DLQs to the Architecture Diagram: `result-normalizer-dlq`, `real-time-outlier-service-dlq`, and `feedback-capture-dlq`. Add a Prerequisites note: "Configure each Lambda's `OnFailure` destination to a dedicated SQS DLQ. CloudWatch alarms on DLQ depth alert the on-call laboratory-informatics and pathology teams; for the result-normalizer-dlq and real-time-outlier-service-dlq specifically, alarm threshold should be 1 (a single dropped result is a result that the lab cannot account for in its CLIA audit trail). Replay events from DLQ after fixing the root cause; for events older than the autoverification window or the critical-callback window, escalate to laboratory-director review rather than auto-replay because the release decision has already been made and the callback timing has already been violated." Add a "DLQ and replay" bullet to "Why This Isn't Production-Ready" that ties the discipline to the existing disaster-recovery paragraph.

#### Finding A3: Method/Reagent-Change Handling in Delta Checks Identified in Prose but Absent from Pseudocode

- **Severity:** MEDIUM
- **Expert:** Architecture / Pedagogy
- **Location:** "The Technology" reference-range subsection (Method-specific ranges paragraph: "When a patient's labs move between facilities or analyzers (which happens routinely), naive delta checks across methods produce spurious flags. The fix is to harmonize against the method and track method changes in the delta calculation"); "Why This Isn't Production-Ready" section's Method and reagent change management paragraph; Step 4 `patient_baseline_checks` pseudocode.
- **Problem:** The recipe's prose is unusually clear that method/reagent changes invalidate naive delta checks: the Technology section names this as a first-class concern, the Why This Isn't Production-Ready section reinforces it, and The Honest Take's "reference ranges encode more complexity than you expect" lesson reflects on it. This is the right teaching.

  But Step 4's `patient_baseline_checks` pseudocode performs the delta check by computing `enriched_result.value - enriched_result.previous_result.value` without checking whether the two results came from the same `method` (or even the same `analyzer`). The Step 1 `normalize_result` pseudocode correctly captures `method` on the canonical result, and the recent-results store is presumably storing method per result, but Step 4 doesn't use it. A reader who treats the pseudocode as the implementation specification will produce a system that fires false delta-check flags every time a patient's labs cross analyzer methods. This is precisely the failure mode the recipe's prose warns against.

  This matters operationally because method-change events are common: a hospital that runs both Roche and Abbott chemistry analyzers in the central lab will have inter-method differences for many analytes; a patient whose labs were drawn at the main lab Friday and at a satellite lab Monday will routinely cross methods; an analyzer downtime that re-routes specimens to a backup analyzer will produce method changes for an entire shift. False delta-check flags on these crossings are exactly the alert-fatigue source the recipe correctly identifies elsewhere.

  Same prose-vs-pseudocode asymmetry pattern as Recipe 3.4 A3 (oncology context flag identified in The Honest Take but absent from pseudocode).
- **Fix:** Two coordinated edits:
  1. Update Step 4 `patient_baseline_checks` pseudocode to include a method-comparison check before the delta computation:
     ```
     IF enriched_result.previous_result is not null:
         time_delta_hours = hours_between(enriched_result.previous_result.resulted_at, enriched_result.resulted_at)
         analyte_meta = analyte_metadata.get(enriched_result.loinc_code)

         // Method-change suppression: if the current and previous results came
         // from different analyzer methods, suppress the absolute-delta check
         // unless the analyte has a documented method-harmonization coefficient.
         // Naive deltas across method boundaries produce spurious flags.
         IF enriched_result.method != enriched_result.previous_result.method:
             IF NOT analyte_meta.method_harmonization.has(enriched_result.method, enriched_result.previous_result.method):
                 emit_metric("delta_suppressed_method_change", 1, dimensions = {
                     loinc: enriched_result.loinc_code,
                     current_method: enriched_result.method,
                     previous_method: enriched_result.previous_result.method
                 })
                 // Skip absolute-delta check; still allow patient-history z-score
                 // because that uses the patient's full distribution and is
                 // less sensitive to single-method-pair shifts.
             ELSE:
                 // Apply the harmonization coefficient before computing delta.
                 harmonized_previous = apply_harmonization(
                     enriched_result.previous_result.value,
                     from_method = enriched_result.previous_result.method,
                     to_method = enriched_result.method,
                     coefficient = analyte_meta.method_harmonization.lookup(...)
                 )
         ELSE:
             harmonized_previous = enriched_result.previous_result.value

         IF time_delta_hours <= analyte_meta.delta_check_window_hours AND harmonized_previous is not null:
             absolute_delta = enriched_result.value - harmonized_previous
             ...
     ```
  2. Add a paragraph to the General Architecture Pattern's "Patient-baseline path" subsection naming method-harmonization as a first-class concern and pointing at the analyte_metadata field (`method_harmonization` per analyte, populated jointly by clinical chemistry and analytics teams).

#### Finding A4: Cross-Test Coherence Rules Identified as One of the Most Reliable Layers but Absent from Pseudocode

- **Severity:** MEDIUM
- **Expert:** Architecture / Pedagogy
- **Location:** General Architecture Pattern's "Cross-test path" (mentions "Coherence Rule Engine" as a path component); "The Technology" Statistical Methods subsection (lists "Cross-test coherence checks" with examples: TSH/T4 inconsistency, Na/glucose, hemoglobin/hematocrit 3:1 ratio, bilirubin fractions); The Honest Take section (the cross-test coherence rules "ended up being one of the most reliable layers in the pipeline"); Step 7 panel-level checks (only the Isolation Forest is shown).
- **Problem:** The recipe's prose elevates cross-test coherence rules to the most reliable layer in the pipeline. Step 7 of the pseudocode walkthrough demonstrates the panel-level Isolation Forest but does not demonstrate any coherence rule. A reader following the pseudocode walkthrough will not see how to encode anion-gap plausibility, TSH-T4 consistency, hemoglobin-hematocrit 3:1 ratio, or bilirubin-fraction summing as concrete rules.

  This is a teaching-fidelity gap with operational consequences: the recipe's audience includes laboratory-informatics teams who may design rule libraries based on the recipe's framing. The Honest Take's lesson is that coherence rules catch analyzer calibration drift, reagent dispense errors, and specimen mislabeling that no other layer catches reliably. A reader who skips this layer because the pseudocode skips it builds a system that is missing one of the highest-value detection layers.

  Same prose-vs-pseudocode asymmetry as A3.
- **Fix:** Add a coherence-check function to Step 7 alongside the panel multivariate check:
  ```
  FUNCTION panel_coherence_check(panel):
      // Cross-test coherence rules encode known physiological relationships
      // between results in the same panel. They run after all panel
      // components are available and produce flags when relationships fail
      // implausibility checks. They catch analyzer calibration drift,
      // reagent dispense errors, and specimen mislabeling that the other
      // layers miss.
      flags = []

      // Anion gap plausibility (BMP / CMP).
      // Anion gap = Na - (Cl + HCO3); typical 8-16 mEq/L.
      IF panel.has_all(["sodium", "chloride", "bicarbonate"]):
          anion_gap = panel.sodium.value - (panel.chloride.value + panel.bicarbonate.value)
          IF anion_gap < ANION_GAP_LOW_BOUND OR anion_gap > ANION_GAP_HIGH_BOUND:
              flags.append({
                  rule_type: "coherence_anion_gap_implausible",
                  severity:  "tech_review_hold",
                  computed_anion_gap: anion_gap,
                  expected_range: [ANION_GAP_LOW_BOUND, ANION_GAP_HIGH_BOUND],
                  message: f"Computed anion gap {anion_gap} outside plausible range; suspect analyzer calibration or specimen issue"
              })

      // Hemoglobin / hematocrit 3:1 ratio (CBC).
      IF panel.has_all(["hemoglobin", "hematocrit"]):
          hgb_hct_ratio = panel.hematocrit.value / panel.hemoglobin.value
          IF hgb_hct_ratio < HCT_HGB_RATIO_LOW OR hgb_hct_ratio > HCT_HGB_RATIO_HIGH:
              flags.append({
                  rule_type: "coherence_hgb_hct_ratio",
                  severity:  "tech_review_hold",
                  computed_ratio: hgb_hct_ratio,
                  expected_range: [HCT_HGB_RATIO_LOW, HCT_HGB_RATIO_HIGH],
                  message: f"Hct/Hgb ratio {hgb_hct_ratio:.2f} outside typical 2.7-3.3 range; suspect specimen or analyzer issue"
              })

      // TSH / Free T4 coherence.
      IF panel.has_all(["tsh", "free_t4"]):
          // Both very low (or both very high) is unusual without specific
          // pituitary or non-thyroidal-illness context.
          IF panel.tsh.value < TSH_LOW AND panel.free_t4.value < T4_LOW:
              flags.append({
                  rule_type: "coherence_tsh_t4_both_low",
                  severity:  "synchronous",
                  ...
              })

      // Bilirubin fractions sum check.
      IF panel.has_all(["total_bilirubin", "direct_bilirubin"]):
          IF panel.direct_bilirubin.value > panel.total_bilirubin.value * 1.05:    // small tolerance for measurement error
              flags.append({
                  rule_type: "coherence_bilirubin_fractions_inconsistent",
                  severity:  "tech_review_hold",
                  ...
              })

      RETURN flags
  ```
  Run `panel_coherence_check` before the panel multivariate check; both contribute flags to the panel-level routing decision.

#### Finding A5: CLIA Critical-Value Callback Workflow Timing/Read-Back/Escalation Discipline Not in Routing Pseudocode

- **Severity:** MEDIUM
- **Expert:** Architecture / Healthcare Compliance
- **Location:** Step 6 `route_result` `"critical_callback"` branch (`SNS.Publish(topic = CRITICAL_CALLBACK_TOPIC, message = build_callback_payload(outlier_event))`); "Why This Isn't Production-Ready" Critical-value callback workflow paragraph; The Honest Take's "the critical-value callback workflow is more complex than it looks" lesson.
- **Problem:** The recipe correctly identifies in prose that CLIA critical-value callbacks are "a CLIA-regulated workflow: the callback has to happen within a defined window, be documented, and be closed out with read-back. The routing infrastructure must support this documented workflow, not just fire-and-forget alerts." The Why This Isn't Production-Ready section names callback timing (30 or 60 minute windows from many states and accreditation bodies) and the documented fallback when automated callback fails. The Honest Take's lesson reinforces this: "Getting the automation for this right is 40% of the engineering effort in the critical-path part of the pipeline."

  But Step 6's `"critical_callback"` branch is a single SNS.Publish call. There's no timing-tracking primitive (a callback that is sent but not acknowledged within the window must escalate to the lab supervisor; the escalation must be triggered by the callback infrastructure, not by external monitoring), no read-back primitive (a callback is closed out by capturing the recipient's read-back, which is a data-collection step the routing pipeline should initiate), and no fallback-to-manual primitive (the recipe's own prose says "have a documented fallback when automated callback fails (page the lab supervisor, require manual phone calls, document the fallback invocation)" but the pseudocode doesn't show any fallback path).

  This is the same shape as Recipe 3.4's "the critical-value callback workflow is more complex than it looks" framing. For Recipe 3.5 specifically, the consequence of a missed callback timing is more directly regulatory: CLIA inspectors and CAP surveyors review callback logs, and a callback that was sent but not closed out within the window is a regulatory finding even if the clinician acted on the result.
- **Fix:** Expand Step 6's `"critical_callback"` branch to demonstrate the workflow primitives:
  ```
  "critical_callback":
      // CLIA-regulated callback. The callback service owns timing,
      // read-back, escalation, and documentation. This is not a
      // fire-and-forget SNS publish; it is an orchestration that may
      // span minutes (the callback window) to hours (escalation if
      // primary recipient is unreachable).
      callback_id = generate_callback_id()
      callback_record = {
          callback_id:      callback_id,
          outlier_event_id: outlier_event.event_id,
          severity:         "critical_callback",
          required_window_minutes: clia_callback_window_minutes(outlier_event.loinc_code),
          initiated_at:     NOW(),
          state:            "initiated",
          primary_recipient: route_to_ordering_provider(outlier_event.patient_id),
          escalation_chain: build_escalation_chain(outlier_event.patient_attributes.location)
      }
      DynamoDB.PutItem("critical-callbacks", callback_record)

      // Initiate the callback. The callback service tracks acknowledgement,
      // captures read-back, and escalates if the window expires without closure.
      SNS.Publish(
          topic   = CRITICAL_CALLBACK_TOPIC,
          message = { callback_id: callback_id, fetch_by_id: True },
          attributes = { "severity": "critical_callback" }
      )

      // Schedule the escalation timer. EventBridge Scheduler fires a
      // closure-check at the window boundary; if the callback is still
      // open, the closure-check Lambda escalates per the chain.
      EventBridge.Scheduler.CreateSchedule(
          name = f"callback-escalation-{callback_id}",
          schedule_expression = f"at(NOW + {callback_record.required_window_minutes} minutes)",
          target = ESCALATION_CHECK_LAMBDA,
          input = { callback_id: callback_id }
      )

      autoverify_release(enriched_result, with_flag = "critical_value")
  ```
  Add a callback-state-machine paragraph to the General Architecture Pattern's Routing subsection naming the four states (initiated, acknowledged, read-back-captured, closed) and the escalation chain. This is a substantial expansion but it reflects what the prose already says is "40% of the engineering effort." Alternatively, add a paragraph explicitly deferring the callback-state-machine details to the existing prose treatment, with a note that "the SNS.Publish in this pseudocode initiates the workflow; the workflow itself is documented in the callback service's own design." The first option is the architecturally correct fix; the second is the smaller editorial change.

#### Finding A6: Reference-Range Version Captured in Step 1 but Not Propagated to Routing Event or Audit Index

- **Severity:** MEDIUM
- **Expert:** Architecture / Healthcare Compliance
- **Location:** Step 1 `normalize_result` (correctly captures `reference_range_version`); Step 6 `route_result` (constructs `outlier_event` without reference_range_version); `OpenSearch.Index("lab-outliers", outlier_event)` call.
- **Problem:** Step 1's canonical_result correctly includes `reference_range_version`, which is the discipline The Honest Take section explicitly calls out: "Treat reference ranges as versioned first-class data, not as a config file. Audit trails that don't record which range was in force for a given alert are not audit trails; they're wishes." But Step 6's `outlier_event` construction does not propagate `reference_range_version` from the enriched_result into the routing event:
  ```
  outlier_event = {
      event_id:            enriched_result.event_id,
      patient_id:          enriched_result.patient_id,
      loinc_code:          enriched_result.loinc_code,
      ...
      // reference_range_version not present
  }
  ```
  The OpenSearch index that drives the lab director and pathologist dashboards therefore does not store the range version that was in force when the alert fired. A reader implementing the pseudocode produces exactly the audit-trail gap that The Honest Take warns against.

  For CLIA inspections and CAP surveys, "why did this alert fire?" is a question the laboratory director must be able to answer authoritatively. Reproducing the decision requires knowing which range version was in force, which method/analyzer was used, and which rule version was active. The Step 1 normalize_result captures method and reference_range_version; the rule library is versioned per the Prerequisites section. The gap is in the audit-event construction.
- **Fix:** Update Step 6's `outlier_event` construction to include the audit-trail discipline:
  ```
  outlier_event = {
      event_id:                outlier_event.event_id,
      patient_id:              enriched_result.patient_id,
      loinc_code:              enriched_result.loinc_code,
      loinc_display:           enriched_result.loinc_display,
      value:                   enriched_result.value,
      unit:                    enriched_result.unit,
      method:                  enriched_result.method,
      reference_range_version: enriched_result.reference_range_version,
      rule_library_version:    lab_rules.current_version(),
      analyte_metadata_version: analyte_metadata.current_version(),
      ...
  }
  ```
  Add a one-line note to the audit-event documentation that explicitly says "every flag carries the rule library version and reference range version that were in force at flag-firing time; reproducing the decision later requires fetching those versions from the versioned rule store and reference-range library."

#### Finding A7: Severity-Tier Mapping Between Flag-Level and Routing-Level Is Implicit in Pseudocode

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 3 `rule_screen` emits flags with severity values like `"critical_callback"`, `"informational"`, `"tech_review_hold"`; Step 4 emits `"synchronous"`, `"critical_callback"`; Step 6 `route_result` says routing is one of `"autoverify_with_flag" | "critical_callback" | "tech_review_hold" | "recollect_requested"` and uses `determine_routing(all_flags)` without showing the mapping.
- **Problem:** Three different severity vocabularies appear in the pseudocode without a clear mapping:
  1. Flag-level severities emitted by individual rule families: "critical_callback", "informational", "tech_review_hold", "synchronous", "recollect_requested" (in some places).
  2. Routing-level decisions returned by `determine_routing`: "autoverify_with_flag", "critical_callback", "tech_review_hold", "recollect_requested".
  3. Sample output uses both kinds in the same `flags` array of the same event (e.g., the potassium sample has flags with severity "critical_callback", "tech_review_hold", and "synchronous" all in one event, with overall routing "critical_callback").

  The relationship is semantically clear from context (the highest-severity flag drives routing, with specimen-quality-invalidating flags potentially overriding to tech_review_hold or recollect_requested), but `determine_routing` is just `determine_routing(all_flags)` without explicit logic. A reader implementing the routing logic from the pseudocode will not know how to compute the routing from individual flag severities, and will not know that a flag with severity "tech_review_hold" combined with a flag with severity "critical_callback" routes to "critical_callback" plus a tech_review_hold annotation (per the recipe's prose), not just "critical_callback" alone.
- **Fix:** Either (a) provide an explicit `determine_routing` body in Step 6, or (b) add a paragraph to the General Architecture Pattern's "Flag aggregator and severity tiering" subsection naming the precedence rules (critical-callback always fires; specimen-quality-invalidating + critical = callback-with-recollect-context; specimen-quality-invalidating alone = tech-review-hold; delta or z-score with no specimen quality concerns and no critical = autoverify-with-flag). Option (a) is the smaller editorial change; option (b) preserves the prose treatment but makes the precedence explicit.

#### Finding A8: Performance-Benchmark Numbers Should Be Flagged More Prominently as Illustrative

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Expected Results "Performance benchmarks" table (Flags per 1,000 results 50-180 across configurations, Tech review volume 3-12% of results, Autoverification rate 80-95%, Pre-analytical artifact catch rate 25-85%, Real critical-value miss rate <2% to <1%, Delta-check override rate 25-70%, Critical-callback timeliness 88-97% under 60 min, Real-time latency p95 30-250ms).
- **Problem:** The performance benchmarks table presents specific ranges that read as published or measured numbers. The table's HTML-comment TODO acknowledges they are directional from typical lab analytics project experience and should be replaced with measured numbers. The CAP Q-Probe and Q-Tracks studies publish peer comparative numbers that the TODO correctly references.

  Two specific numbers warrant additional caveat regardless of whether the table is replaced: the "Real critical-value miss rate <1%" claim implies a measured ground truth that most labs do not have (the missed-critical signal is detected by chart review or by downstream clinical signals; production miss-rate measurement is a multi-month chart-review project), and the "Pre-analytical artifact catch rate 65-85%" claim implies a measurement methodology (recollect-confirmed artifacts as ground truth, divided by a denominator of all true artifact events) that most production systems approximate rather than measure directly.

  This is LOW because the TODO acknowledges the gap and the table is positioned as illustrative. The fix is editorial: either tighten the TODO to call out the two measurement-methodology questions or move the table's caveat from a TODO comment to an inline visible-to-reader caveat paragraph above the table.
- **Fix:** Either (a) move the existing HTML-comment TODO into a visible inline caveat paragraph above the table ("These benchmark ranges are directional from typical lab analytics project experience. The 'Real critical-value miss rate' specifically requires multi-month chart-review measurement to establish ground truth and is approximate without that investment. The 'Pre-analytical artifact catch rate' similarly requires a recollect-confirmed-artifact denominator that production systems typically approximate. Replace with measured numbers for your environment and methodology."), or (b) leave the HTML-comment TODO and resolve before publication with citations to CAP Q-Probe / Q-Tracks figures. Option (a) makes the caveat visible to readers regardless of whether the published numbers are added; option (b) is cleaner once the numbers are verified.

### Networking Expert Review

#### What's Done Well

- VPC posture is named explicitly: "Production: Lambdas, SageMaker jobs, and OpenSearch in a VPC with VPC endpoints for S3, DynamoDB, Kinesis, SageMaker runtime, Comprehend Medical, Bedrock, and KMS. No public endpoints on OpenSearch." Seven endpoints named plus the OpenSearch-no-public-endpoints discipline is solid.
- TLS in transit is named explicitly across the encryption row.
- The on-premises MLLP bridge to AWS via Amazon MQ is correctly identified as the standard EHR-to-AWS integration pattern, with the right service choice (ActiveMQ flavor) and the right architectural pattern (republish to MQ, downstream Lambda picks up and normalizes).
- Gateway endpoints (S3, DynamoDB) are correctly mixed with interface endpoints; the recipe doesn't accidentally suggest a NAT Gateway in the path of PHI traffic.

#### Finding N1: VPC Endpoint Inventory Misses CloudWatch Monitoring vs Logs, EventBridge Bus vs Scheduler, SageMaker API/Runtime/FeatureStore-Runtime, SNS, Step Functions, Pinpoint

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row.
- **Problem:** Multiple precision gaps matching the recurring chapter-wide pattern from Recipes 2.7-2.10 and 3.1-3.4:

  1. **CloudWatch monitoring (`PutMetricData`) endpoint not distinguished from CloudWatch Logs.** The pipeline emits custom metrics throughout (Step 1's `emit_metric("unmapped_test", ...)`, Step 4's method-change-suppression metric proposed in Finding A3, Step 6's potential metrics, Step 8's `emit_metric("flag_tech_decision", ...)`). CloudWatch Logs uses `com.amazonaws.{region}.logs`; CloudWatch monitoring uses `com.amazonaws.{region}.monitoring`. They are distinct interface endpoints. A Lambda in a private subnet without the `monitoring` endpoint silently fails to publish custom metrics, which is the most consequential failure mode for this recipe specifically because override-rate metrics drive rule retirement decisions.

  2. **EventBridge bus vs Scheduler endpoints not distinguished.** The architecture uses both: EventBridge for outlier events and EventBridge Scheduler for the batch cadence triggers (`Q[EventBridge Scheduler\nhourly / daily]` in the diagram). The bus uses `com.amazonaws.{region}.events`; Scheduler uses `com.amazonaws.{region}.scheduler`.

  3. **SageMaker api/runtime/featurestore-runtime endpoints not distinguished.** SageMaker has multiple service endpoints: `api` for control-plane (creating Processing and Training jobs), `runtime` for invoking real-time endpoints, and `featurestore-runtime` for online feature retrieval. The recipe uses at least api (Step Functions invocations of SageMaker Processing) and featurestore-runtime (the real-time outlier service's cohort-baseline lookup); the recipe's "SageMaker runtime" label collapses these.

  4. **SNS interface endpoint not specified.** SNS publish from the critical-value callback Lambda uses `com.amazonaws.{region}.sns`. Without the endpoint, a Lambda in a private subnet hits a DNS or routing failure on the SNS publish call, which for a CLIA-regulated critical-callback workflow is a regulatory event.

  5. **Step Functions interface endpoint not specified.** Step Functions has its own interface endpoint (`com.amazonaws.{region}.states`) for state-machine invocation from a private VPC.

  6. **Pinpoint API egress.** The recipe uses Pinpoint for outpatient outreach; Pinpoint's REST API has a public endpoint. The Lambda that calls Pinpoint should reach the Pinpoint API through the appropriate egress path with appropriate IAM scoping.

  7. **Comprehend Medical and Bedrock interface endpoints.** The recipe correctly names Comprehend Medical and Bedrock in the existing endpoint list; verify the specific endpoint identifiers (`com.amazonaws.{region}.comprehendmedical` and `com.amazonaws.{region}.bedrock-runtime`).

  Same recurring chapter-wide finding as Recipes 3.2 N1, 3.3 N1, 3.4 N1.
- **Fix:** Update the VPC row in Prerequisites to list each endpoint explicitly: "Production: Lambdas, SageMaker jobs, and OpenSearch in a VPC with the following VPC endpoints. Gateway: `s3`, `dynamodb`. Interface: `kinesis`, `sagemaker.api` (control-plane Processing and Training), `sagemaker.featurestore-runtime` (online cohort-baseline retrieval), `sagemaker.runtime` (if a real-time endpoint variant is used), `states` (Step Functions), `events` (EventBridge bus), `scheduler` (EventBridge Scheduler), `logs`, `monitoring` (CloudWatch `PutMetricData`), `kms`, `sns`, `bedrock-runtime` (LLM-assisted interpretation), `comprehendmedical`. OpenSearch and Neptune (if used for graph extensions) only accessible via VPC; no public endpoints. Pinpoint API is reached through its regional endpoint via the Lambda's egress path."

#### Finding N2: VPC Flow Logs Not Explicitly Required

- **Severity:** LOW
- **Expert:** Networking / Compliance
- **Location:** Prerequisites VPC row; CloudTrail row.
- **Problem:** The recipe correctly specifies CloudTrail (with data events on patient-context-cache, lab-rules bucket, feedback-labels bucket, OpenSearch domain operations, and the critical-value callback topic) for control-plane and data-plane API audit. It does not explicitly require VPC Flow Logs, which capture network-level access patterns (source/destination IPs, ports, protocols, accept/reject) and are part of the standard HIPAA audit posture. CloudTrail records "who called the API" but doesn't record "which IP addresses talked to which IP addresses inside the VPC."

  For a CLIA-regulated workflow where the patient-context-cache and the rule library are high-value assets, network-level audit is the complement to API-level audit. Joint Commission and CAP surveyors expect network-level audit trails when investigating suspected unauthorized access to a regulated lab data store. Same finding as Recipes 3.2 N2, 3.3 N2, 3.4 N2.
- **Fix:** Add to the VPC row or to the CloudTrail row: "VPC Flow Logs enabled on the VPC carrying Lambda, SageMaker, and OpenSearch traffic; logs delivered to a dedicated S3 bucket with KMS encryption and retention aligned to the deepest applicable retention requirement (CLIA 2-year minimum for most records, 5-year for blood bank, longer in many states for pathology and for sentinel-event-related records)."

### Voice Reviewer

#### What's Done Well

- The opening 6:42 a.m. potassium-7.8 vignette is publication-ready voice. The 74-year-old admitted overnight for community-acquired pneumonia, the peripheral draw that sat at the nursing station for an hour and a half, the visibly hemolyzed sample arriving with hemolysis index 4+, the recollect from a central line showing K 4.2 matching the patient's previous values, and the patient sitting up eating oatmeal while the rapid response team assembles is the densest pre-analytical-artifact framing in any cookbook recipe to date. The closing line ("Everyone's Saturday morning just got wrecked by a pre-analytical artifact") lands the operational reality without rhetorical excess.
- The three-categories framing (real-and-critical, real-and-unexpected, not-real) is the right teaching anchor for this domain, and the transition into the layered detection system ("Rules for the obviously critical values ... Patient-specific delta checks ... Population-level statistical checks ... Clinical implausibility checks ... a pre-analytical context layer that tracks specimen quality indicators") is the architecturally correct factoring.
- The Three-Stage Lab Workflow subsection (pre-analytical, analytical, post-analytical) is the right teaching anchor for understanding where outliers hide. The "majority of lab errors originate here" framing for pre-analytical with the appropriate HTML-comment TODO for citation is the right discipline. The "QC watches the analyzer for drift; it's a process-control problem, not a patient-data problem" framing on the QC-vs-outlier-detection division of labor is operationally accurate.
- The five-outlier-types subsection (Hard critical values, Delta check failures, Population-level improbability, Clinical implausibility, Specimen artifact signals) is the right teaching anchor and is operationally accurate. The framing that "a first-time builder who treats them all the same will produce a system that's bad at all of them" is the kind of design-constraint-up-front teaching the cookbook is built on.
- The reference-range subsection is the most substantive treatment in any cookbook recipe. Age and sex variation (with the hemoglobin example correctly differentiated for adult male, adult female, and 9-month-old; alkaline phosphatase in adolescents vs adults; creatinine and muscle mass), pregnancy physiology (with the trimester-specific TSH, the dilutional hemoglobin drop, the placental-source alkaline phosphatase climb, the lower creatinine), population-specific intervals with explicit attention to the 2021 NKF-ASN race-coefficient revision and the WBC reference ranges in certain African populations, method-specific calibration, critical vs action vs reference tiers, source-and-versioning. Each detail is clinically accurate and operationally substantive.
- The patient-specific baselines subsection (rolling mean and stddev, delta checks as time-local baselines, CUSUM and change-point detection for slow trends, analyte-specific handling for intrinsic variability) is operationally correct. The "applying the same delta thresholds across all tests produces nonsense" framing on analyte-specific calibration is the kind of detail-level teaching that distinguishes the cookbook.
- The statistical-methods progression (rule-based criticality, delta checks, robust z-scores against patient history, population z-scores against demographic cohorts, specimen quality index fusion, time-series methods on slow drifts, multivariate outlier detection on panels, cross-test coherence checks, supervised classifiers when labels exist, LLM-assisted interpretation as emerging) is the right pedagogical order, and the closing posture ("Don't skip the first two layers; they catch most of the real clinical signal and anchor the system's explainability") is operationally correct.
- The autoverification connection subsection is the recipe's biggest pedagogical contribution. The framing of autoverification and outlier detection as flip sides of the same architectural idea, sharing input data, model machinery, and producing complementary outputs, is the architecturally correct unification that most production deployments converge on. The "the outlier detector can be the brain of the autoverification decision" framing is the right teaching for how to factor the system.
- The alert-fatigue subsection is substantive and explicitly cross-references Recipe 3.4. The four design implications (critical values still fire, delta-check thresholds need per-analyte calibration, patient-context-aware suppression for low-value alerts is allowed, override tracking is not optional) are concrete and operationally actionable. The closing observation that "the lab tech has a different cost/benefit calculation than the clinician" is operationally accurate and is the kind of constituency-aware framing the cookbook does well.
- The Honest Take is publication-ready and should be preserved verbatim. The seven lessons are the right teaching priorities. The closing trap warning ("do not let 'flag rate' become the primary business metric ... The metrics that matter are autoverification rate (higher is better, subject to not compromising safety), pre-analytical artifact catch rate (higher is better, measured against recollect confirmations), real critical-value miss rate (lower is better), and callback timeliness ... Frame the program around these. Flag rate is a knob to adjust, not a goal") is the kind of operations-engineer voice that distinguishes the cookbook.
- The Variations and Extensions section covers the right adjacent patterns at the right depth (POCT-specific, blood bank, microbiology, coagulation, oncology biomarker trends, therapeutic drug monitoring, cross-facility harmonization, patient-facing context, LLM-assisted prioritization, sepsis early warning integration). Each is one to two paragraphs and explicitly cross-references related recipes where appropriate.
- Style hygiene is exceptionally clean: zero em dashes (verified directly), no marketing language, no documentation-voice. The 70/30 vendor balance is preserved cleanly: the conceptual sections are vendor-neutral, AWS service names enter at the AWS Implementation section and stay there.
- HTML-comment TODO discipline is correct: six TODOs total, all forward-placeholder for industry-figure verification (CAP/CLSI pre-analytical error rate, lab pre-analytical error cost estimates, FDA LDT rule status, CAP Q-Probe / Q-Tracks autoverification benchmarks, validated LLM-assisted lab-interpretation patterns, aws-samples laboratory-analytics repos), and all the chapter-2-and-3-settled posture. No bracket-style visible TODOs that would render in published output.

#### Finding V1: Opening Vignette's "Recollect from a Central Line" Phrasing Is Imprecise

- **Severity:** LOW
- **Expert:** Voice / Domain Accuracy
- **Location:** Opening vignette ("A recollection from a central line with immediate transport shows potassium 4.2, which matches the patient's previous values and his clinical picture").
- **Problem:** The vignette's narrative thread is correct: the recollect with proper technique and immediate transport produced a potassium that matched the patient's clinical picture, confirming the original 7.8 was pseudohyperkalemia from hemolysis. The phrasing "from a central line" is the imprecision. The textbook canonical recommendation for confirming suspected pseudohyperkalemia is to recollect from a peripheral vein with proper technique (no fist clenching, minimal tourniquet time, larger-bore needle, immediate transport, no IV-line proximity), not from a central line. Drawing from a central line carries its own pre-analytical risks: sample dilution from infusates running through the central line lumen (dextrose, saline, TPN, antibiotics), contamination from heparin line locks (which can affect coagulation assays but generally not chemistries), and the sample-collection risk of accessing a central line specifically for blood draw when peripheral access is available.

  In the specific clinical scenario described (74-year-old admitted overnight for pneumonia, presumably with peripheral IV access), the canonical investigation is a properly drawn peripheral recollect with immediate transport, not a central line draw. Some hospitals do use central-line recollects for specific reasons (the patient had difficult peripheral access, the original draw had documented technique problems and the central line was the next available source), but the phrasing as written reads as if central-line recollect is the standard approach for pseudohyperkalemia investigation, which it is not.
- **Fix:** Either (a) change the phrasing to "A properly drawn peripheral recollect with immediate transport shows potassium 4.2" (smaller change, preserves narrative flow, aligns with canonical guidance) or (b) keep central line but add a one-clause justification ("A recollection from a central line, used because peripheral access was poor, with immediate transport shows potassium 4.2"). Option (a) is the smaller editorial change and aligns with the textbook canonical approach.

#### Finding V2: Sample Output Timestamps and Event IDs Use Future Dates

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** Expected Results sample alerts (`"event_id": "LAB-2026-05-12T06:42:11Z-771244"`, `"resulted_at": "2026-05-12T06:42:11Z"`, `"detected_at": "2026-05-12T06:42:11.180Z"`, etc.).
- **Problem:** The recipe is being drafted in May 2026 and the sample output uses 2026-05-12 timestamps that are current at draft time but will become a backdated example as the book ages. By publication (likely Q3 2026 or later), the timestamps will read as suspiciously specific. Same observation as Recipes 3.1 V1, 3.2 V1, 3.3 V1, 3.4 V1.
- **Fix:** Either (a) replace the specific dates with placeholder patterns ("`<draft-time>`" with HTML-comment notes) or (b) keep the dates but add an HTML-comment disclaimer at the top of the Expected Results block: "Sample timestamps and event IDs are illustrative and reflect the draft date; production output uses real ISO-8601 timestamps from the event-handler's invocation time."

#### Finding V3: HTML-Comment TODOs for Industry-Figure Verification

- **Severity:** LOW
- **Expert:** Voice / Publication Readiness
- **Location:** "The Technology" Three-Stage Lab Workflow subsection (CAP/CLSI pre-analytical error rate TODO); Cost Estimate row (lab pre-analytical error cost TODO); Code section's reference implementations paragraph (aws-samples lab analytics TODO); Why-These-Services Bedrock paragraph (validated LLM-assisted lab-interpretation patterns TODO); Performance benchmarks table (illustrative numbers TODO referencing CAP Q-Probe / Q-Tracks); Why This Isn't Production-Ready FDA LDT paragraph (current rule status verification TODO); Additional Resources section's AWS Sample Repos and Solutions/Blogs subsections (forward-placeholder TODOs).
- **Problem:** Six HTML-comment TODOs are present, all forward-placeholder. Three should be resolved before publication:
  1. The pre-analytical error rate citation in the Three-Stage Lab Workflow subsection. Reasonable sources: CAP Q-Probe studies, CLSI publications, peer-reviewed publications such as Plebani M, "The detection and prevention of errors in laboratory medicine."
  2. The pre-analytical error cost estimate in the Cost Estimate row ("$10-50 per event in supplies and labor plus the unmeasurable clinical-workflow cost"). Reasonable sources: CAP Q-Probe studies, Institute for Quality in Laboratory Medicine publications.
  3. The FDA LDT 2024 rule status verification in the Why This Isn't Production-Ready section. The FDA's final rule on laboratory-developed tests was issued in May 2024 with phased implementation; verify the current status of the implementation phases before publication. (This becomes increasingly important as 2026 progresses since the early phases will have taken effect.)

  The CAP Q-Probe / Q-Tracks benchmark figures TODO (in the Performance benchmarks table) should also be resolved if specific peer comparisons are cited. The validated-LLM-clinical-interpretation-patterns and aws-samples-repo forward placeholders read cleanly in published output and can remain.
- **Fix:** Resolve the three industry-figure TODOs before publication. The remaining TODOs (forward-looking Bedrock patterns, validated LLM clinical-interpretation architectures, aws-samples and AWS-blog-post verification) can remain as forward placeholders.

#### Finding V4: Reference to Recipe 3.7 (Patient Deterioration Early Warning) Is Forward-Pointing

- **Severity:** LOW
- **Expert:** Voice / Pedagogy
- **Location:** Variations "Sepsis early warning integration" extension; Related Recipes section (cross-reference to Recipe 3.7).
- **Problem:** Recipe 3.5 cross-references Recipe 3.7 (Patient Deterioration Early Warning) in two places: the Variations section's sepsis-early-warning extension says "the trajectory detection layer of this pipeline feeds directly into sepsis early warning (Recipe 3.7). In mature deployments, the two pipelines share infrastructure," and the Related Recipes section says "The trajectory detection layer of this recipe produces signals that feed into deterioration scoring."

  Per the project status, Recipe 3.7 has been written (per the file listing showing `chapter03.07-patient-deterioration-early-warning.md`), so this is not an unresolved forward reference. The cross-reference framing is operationally correct (lab trajectory features are core inputs to sepsis risk models, and the trajectory CUSUM analytics in Step 7 of this recipe are exactly the kind of features that feed deterioration scoring). The minor consideration is that the cross-reference assumes Recipe 3.7's specific framing of trajectory features, which a reader who hasn't read 3.7 will not have context for. This is LOW because cross-recipe references are expected in a cookbook structure.
- **Fix:** Either (a) leave as-is (the cross-reference is operationally correct and Recipe 3.7 exists), or (b) add a one-clause framing inline ("the trajectory CUSUM signals from Step 7 produce features (rising lactate, rising creatinine, dropping bicarbonate, dropping platelets) that feed directly into sepsis early warning scoring; see Recipe 3.7"). Option (a) is the smaller change; option (b) provides more context for readers who jump straight to this recipe.

---

## Stage 2: Expert Discussion

**Pattern: A1 (outcome-event idempotency) is the now-recurring trigger-idempotency finding, surfacing for the eleventh consecutive recipe (2.4-2.10 and 3.1-3.5).** Same fix template (deterministic event-key derivation, conditional-write enforcement at the orchestration layer), different specific event source (tech-review-decision events and recollect-result events here). For Recipe 3.5 the consequence is calibrated to autoverification: doubled override counts from redelivered tech-review events distort which rules look high-override and get retired, and a rule retired because of artificially-doubled counts can produce a missed-future-flag that releases an artifactual result to chart without screening. With this finding now flagged across eleven consecutive recipes, the per-recipe-edit posture is producing diminishing returns. The cookbook editor should treat the trigger-idempotency appendix as the highest-leverage cookbook-wide editorial investment.

**Pattern: A2 (DLQ / poison-message handling) is operationally critical for this recipe specifically because the pipeline gates autoverification.** For Recipes 3.1, 3.2, 3.3 a dropped event is an operational concern. For Recipe 3.4 (medication dispensing) a dropped event is a dispense without a check. For Recipe 3.5 a dropped event is a result that bypasses the autoverification screen and lands in the chart without an outlier check, which is precisely the failure mode the entire pipeline is designed to prevent. The DLQ-depth alarm threshold for the result-normalizer and real-time-outlier-service paths should be 1 (single-event sensitivity), not the typical "alert on sustained backlog" pattern. The recipe's prose disaster-recovery paragraph names "If the pipeline is down, results cannot be held indefinitely" but doesn't connect the discipline to per-event poison-message recovery.

**Pattern: A3 (method/reagent-change handling in delta checks) and A4 (cross-test coherence rules in pseudocode) are both the same prose-vs-pseudocode asymmetry shape as Recipe 3.4 A3 (oncology context flag).** The recipe's prose makes a discipline claim and the canonical pseudocode walkthrough doesn't reflect it. For Recipe 3.5 specifically, both gaps are calibrated against very high prose emphasis: the method-change discipline appears in the Technology section, the Why This Isn't Production-Ready section, and The Honest Take's reference-range lesson; the cross-test coherence rules appear in the Statistical Methods subsection, the General Architecture Pattern's Cross-Test Path, and (most consequentially) The Honest Take's "ended up being one of the most reliable layers in the pipeline" lesson. A reader who treats the pseudocode as the implementation specification will produce systems that exhibit exactly the failure modes the prose warns against (false delta-check alerts on method crossings; missing the highest-value coherence-rule layer entirely).

**Pattern: A5 (CLIA critical-callback timing/read-back/escalation discipline) is calibrated against the recipe's own framing.** The Honest Take section explicitly says "Getting the automation for this right is 40% of the engineering effort in the critical-path part of the pipeline," and the Why This Isn't Production-Ready section names the specific compliance requirements (timing windows from CLIA and state licensure, read-back, escalation when primary recipient cannot be reached, documented manual fallback). The pseudocode is a single SNS.Publish call. The asymmetry is pedagogically meaningful because a reader who builds from the pseudocode produces a fire-and-forget alerter, which is the exact failure mode the prose warns against. This is a similar shape to A3 (method changes) and A4 (coherence rules) but with regulatory-compliance stakes layered on top.

**Pattern: A6 (reference-range version not propagated to routing event) is a CLIA audit-trail discipline gap.** The Step 1 normalize_result correctly captures `reference_range_version`, which means the foundational data plumbing is right. The gap is that Step 6's outlier_event construction drops the field, so the OpenSearch index that drives lab director and pathologist dashboards does not store the range version that was in force at flag-firing time. The fix is editorially small (one line in the outlier_event dict) but materially important for CLIA inspection and CAP survey readiness. The Honest Take section's framing ("Audit trails that don't record which range was in force for a given alert are not audit trails; they're wishes") is the right teaching; the pseudocode just needs to reflect it.

**Pattern: A7 (severity-tier mapping) and A8 (performance benchmarks) are editorial polish.** Both have clear semantic intent in the recipe but would benefit from making the implicit explicit.

**Pattern: S1 is the now-recurring PHI-minimization-inside-the-BAA pattern with the sixth distinct surface across the cookbook** (Chapter 2: serialized prompt context; Recipe 3.1: examiner free-text reasoning; Recipe 3.2: patient-facing reminder content for high-stigma specialties; Recipe 3.3: internal SNS notification payload between system components; Recipe 3.4: SNS interrupt-alert payload with high-stigma drug-class disclosure; Recipe 3.5: SNS critical-callback payload with high-stigma test-class disclosure for HIV viral load, hepatitis C viral load, syphilis serology, drug screens, gender-affirming hormone monitoring, psychiatric medication levels). The underlying discipline is identical (don't carry identifying or PHI-adjacent information through stores or messages you don't need it in), but the surface has shifted again. A cookbook-wide PHI-minimization appendix would consolidate all six surfaces with one teaching pass.

**Pattern: S2 (subgroup data governance) is the same finding shape as Recipes 3.2 S2, 3.3 S2, and 3.4 S2.** All four recipes correctly identify the need for subgroup monitoring, all four correctly defer the "what data is captured" question to the operational team, and all four leave the architectural artifacts that make subgroup monitoring binding (data store location, access scope, audit trail, query path) unspecified. Recipe 3.5 has the additional consideration that population-aware reference ranges (the recipe's correct framing of the creatinine-GFR race coefficient revision) require subgroup-aware data infrastructure that outlasts the cohort baselines: range-version-by-population-segment-by-effective-date is itself a versioned data surface with audit-trail discipline that subgroup monitoring depends on.

**Pattern: S3 (per-consumer IAM scoping), S4 (HL7 v2 MLLP bridge security), S5 (Bedrock LLM-assisted interpretation BAA discipline), S6 (Transfer Family SFTP source-IP allowlist) are operational completeness findings.** Each is a domain-specific discipline that the recipe's mixed audience (executives, architects, engineers, PMs) benefits from being named explicitly even if engineers in healthcare integration teams already know them. S4 and S6 are both related to the on-premises-to-AWS PHI ingress surface, which is a domain-specific concern not covered well in any other recipe to date; if the editor pulls together a healthcare-integration-engineer appendix, S4 and S6 belong together.

**Non-conflict: A2 (DLQ), A7 (severity mapping), A8 (benchmarks), N1 and N2 (VPC endpoint detail and Flow Logs), V1, V2, V3, V4 (publication-readiness polish).** All operational-completeness and editorial findings independent of the safety/correctness findings.

**Coordination with the existing code review (`reviews/chapter03.05-code-review.md`):** The code review PASSed-with-reservations on three WARNINGs and seven NOTEs. WARNING 1 (the broken `__name__ != "__production__"` assert) has now appeared in all five Chapter 3 Python companions; treat it as the single-cookbook-wide-fix candidate. WARNING 2 (S3 `put_object` without `SSEKMSKeyId`) parallels Recipes 3.1, 3.2, 3.3, 3.4. WARNING 3 (the `mmol_factors` table mislabeling for creatinine) is a recipe-3.5-specific bug where the unit-conversion constant of 88.4 (the mg/dL ↔ μmol/L conversion factor) is stored in a branch that compares against `"mmol/L"`, where the correct factor would be 0.0884 (three orders of magnitude smaller). For a recipe whose opening framing explicitly calls out "mg/dL vs. mmol/L for glucose is a classic source of ten-fold dosing and interpretation mistakes," embedding a thousand-fold unit-conversion error in the teaching example is consequential even if the `__main__` path never exercises the branch. This is a Python-companion-only issue (the main recipe pseudocode handles unit harmonization at the conceptual level without exposing the specific conversion factors) and is the code reviewer's concern, not this expert review's. But the editor should be aware that the Python companion has a domain-accuracy error in its unit-conversion table that the main recipe's prose anti-pattern explicitly warns against.

The code review's NOTE findings are editorial or mirror items already acknowledged in the code; coordinate with the editorial pass.

**Pattern observation: the recipe is fundamentally sound, the autoverification stakes are calibrated correctly, and the most-consequential gap is the prose-vs-pseudocode asymmetry on method changes (A3) and cross-test coherence rules (A4).** Like Recipes 3.1, 3.2, 3.3, 3.4, this one's teaching density and voice are publication-ready. There are no HIGH findings: the cluster of MEDIUM findings is roughly evenly distributed between architectural completeness (A1 idempotency, A2 DLQs, A3 method changes, A4 coherence rules, A5 callback workflow, A6 audit trail) and PHI/governance (S1 SNS minimization, S2 subgroup governance). The risk profile is comparable to Recipe 3.4 (autoverification gating in a CLIA-regulated workflow, with regulatory consequences for missed callbacks and unscored releases). The recipe's prose framing addresses the elevated risk correctly (CLIA validation, CLSI AUTO10 reference, FDA LDT 2024 rule, callback compliance, disaster recovery), and the operational-completeness backstops (DLQs, idempotency, method-change gates, coherence rules, callback state machines, audit-trail propagation, subgroup governance) are the right next-pass priorities.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings, zero HIGH findings (well below the "more than 3 HIGH = FAIL" threshold). The recipe is teaching-strong, voice-clean, and architecturally sound at the conceptual level. The 6:42 a.m. potassium-7.8 vignette, the three-categories framing, the five-outlier-types taxonomy, the reference-range subsection (the most substantive in any cookbook recipe), the patient-specific baselines subsection, the statistical-methods progression, the autoverification connection (the recipe's biggest pedagogical contribution), the alert-fatigue subsection, the Why This Isn't Production-Ready section's thirteen substantive bullets, and The Honest Take are all publication-ready. Style hygiene is exceptionally clean (zero em dashes verified, no marketing language, no documentation-voice, 70/30 vendor balance preserved, HTML-comment TODOs only).

The eight MEDIUM findings cluster on architectural completeness, recurring patterns, and prose-vs-pseudocode asymmetry:
- **A1** Outcome-event idempotency for the EventBridge → feedback-capture Lambda path (recurring trigger-idempotency pattern across Recipes 2.4-2.10 and 3.1-3.4; eleventh consecutive recipe; cookbook-wide appendix candidate)
- **A2** No DLQ or poison-message handling for the result-normalizer, real-time-outlier-service, or feedback-capture Lambdas (architecturally critical for an autoverification-gating system; a dropped event = result released to chart without screening)
- **A3** Method/reagent-change handling identified as required in prose but absent from Step 4 delta-check pseudocode; reader implementing pseudocode produces false delta-check flags on routine method crossings
- **A4** Cross-test coherence rules identified in The Honest Take as "one of the most reliable layers in the pipeline" but absent from Step 7 pseudocode (only Isolation Forest is shown)
- **A5** CLIA critical-value-callback workflow timing/read-back/escalation discipline named in prose ("40% of the engineering effort in the critical-path part") but pseudocode is a single SNS.Publish call
- **A6** Reference-range version captured correctly in Step 1 normalize_result but not propagated to Step 6 outlier_event or the OpenSearch audit index; CLIA audit-trail discipline gap directly contradicting The Honest Take's "audit trails that don't record which range was in force ... are not audit trails; they're wishes"
- **S1** SNS critical-callback payload PHI minimization not explicit in pseudocode; chapter-3-settled "event-id-only" convention from Recipes 3.1 and 3.3 is implied via the Python companion but not stated in the main recipe; high-stigma test-class disclosure (HIV, hepatitis C, syphilis serology, drug screens, gender-affirming hormones, psychiatric medication monitoring) is a specific concern
- **S2** Subgroup data governance for fairness monitoring acknowledged in prose (with explicit creatinine-GFR race coefficient framing) but the architectural artifacts that make subgroup monitoring binding are not specified (same finding shape as Recipes 3.2 S2, 3.3 S2, 3.4 S2)

The nine LOW findings are operational and editorial polish:
- **A7** Severity-tier mapping between flag-level and routing-level is implicit in pseudocode
- **A8** Performance-benchmark numbers should be flagged more prominently as illustrative
- **S3** Per-consumer IAM scoping for patient-context cache and outlier-events bus not explicit
- **S4** HL7 v2 MLLP bridge security posture (MLLP-over-TLS, mutual TLS, Direct Connect vs VPN, DMZ deployment) not specified
- **S5** Bedrock LLM-assisted interpretation lacks BAA-discipline forward reference to Chapter 2's established patterns
- **S6** Transfer Family SFTP source-IP allowlist and authentication method not specified
- **N1** VPC endpoint precision (CloudWatch monitoring vs Logs, EventBridge events vs Scheduler, SageMaker api/runtime/featurestore-runtime, SNS, Step Functions, Pinpoint, bedrock-runtime, comprehendmedical)
- **N2** VPC Flow Logs not explicitly required (recurring chapter-wide pattern)
- **V1** Opening vignette's "recollect from a central line" phrasing is imprecise; canonical pseudohyperkalemia investigation is a properly drawn peripheral recollect
- **V2** Sample output future-dated timestamps (recurring chapter-wide pattern)
- **V3** HTML-comment TODOs for industry-figure verification (CAP/CLSI pre-analytical error rate, lab pre-analytical error cost estimates, FDA LDT 2024 rule status)
- **V4** Recipe 3.7 cross-reference framing could provide more inline context (optional)

With the MEDIUM findings addressed (especially A3 and A4's prose-vs-pseudocode asymmetry on method changes and coherence rules, which are the most-consequential teaching gaps) and the LOW polish completed, this recipe sits at the same publication-ready quality bar as Recipes 3.1, 3.2, 3.3, 3.4 and the strongest Chapter 2 recipes. The autoverification stakes are calibrated correctly; the recipe's prose framing addresses the regulatory and patient-safety concerns properly, and the operational-completeness backstops (DLQs, idempotency, method-change gates, coherence rules, callback state machines, audit-trail propagation, subgroup governance) are the right next-pass priorities.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | MEDIUM | Architecture | Step 8 `on_tech_review_decision` and `on_recollect_result` (consumed via EventBridge); feedback-capture Lambda | EventBridge → Lambda async is at-least-once; pseudocode has no idempotency guard. Redelivered events double-count override metrics (which directly drive rule-retirement decisions and can produce missed-future-flags-and-missed-future-artifactual-releases), bias the supervised classifier's training distribution, and corrupt the confirmed-artifact-vs-confirmed-real signal. Same recurring trigger-idempotency pattern as Recipes 2.4-2.10 and 3.1-3.4 (eleventh consecutive recipe). Fix: deterministic event-key derivation (`outlier_event_id + decision` for tech review; `original_outlier_event_id + recollect_accession` for recollects); conditional DynamoDB write to `processed-feedback-events` table before OpenSearch update, label write, and metric emission. Strongly recommend a cookbook-wide trigger-idempotency appendix. |
| A2 | MEDIUM | Architecture | Architecture Diagram (no DLQs configured); Prerequisites table; "Why This Isn't Production-Ready" disaster-recovery paragraph | No Dead Letter Queue or `OnFailure` destination configured for the result-normalizer, real-time-outlier-service, or feedback-capture Lambdas. For an autoverification-gating system, a dropped real-time event is a result released to chart without an outlier check, which is precisely the failure mode the entire pipeline is designed to prevent. For a CLIA-regulated workflow, a result the lab cannot account for is a regulatory finding. Fix: add `result-normalizer-dlq`, `real-time-outlier-service-dlq`, `feedback-capture-dlq` SQS queues with `OnFailure` destinations; CloudWatch alarms on DLQ depth (alarm threshold 1 for the real-time path because a single dropped result is a CLIA-audit-trail event); Prerequisites note covering replay discipline including the time-bound for replayability. |
| A3 | MEDIUM | Architecture / Pedagogy | "The Technology" reference-range subsection (Method-specific ranges paragraph: "the fix is to harmonize against the method and track method changes in the delta calculation"); "Why This Isn't Production-Ready" Method and reagent change management paragraph; Step 4 `patient_baseline_checks` pseudocode | Recipe correctly identifies in prose that method/reagent changes invalidate naive delta checks across method boundaries, but Step 4's `patient_baseline_checks` pseudocode performs the delta check without checking whether current and previous results came from the same `method`. A reader who treats the pseudocode as the implementation specification produces a system that fires false delta-check flags every time a patient's labs cross analyzer methods. Same prose-vs-pseudocode asymmetry as Recipe 3.4 A3. Fix: update Step 4 pseudocode to compare `method` between current and previous; suppress absolute-delta check on method mismatch unless `analyte_metadata` has a documented `method_harmonization` coefficient; add paragraph to General Architecture Pattern's Patient-baseline path subsection naming method-harmonization as a first-class concern. |
| A4 | MEDIUM | Architecture / Pedagogy | General Architecture Pattern Cross-Test Path; "The Technology" Statistical Methods subsection; The Honest Take ("the cross-test coherence rules ... ended up being one of the most reliable layers in the pipeline"); Step 7 panel-level checks (only Isolation Forest is shown) | The Honest Take elevates cross-test coherence rules to one of the most reliable layers in the pipeline. Step 7 demonstrates only the panel-level Isolation Forest. A reader following the pseudocode walkthrough will not see how to encode anion-gap plausibility, hemoglobin/hematocrit 3:1 ratio, TSH/T4 consistency, or bilirubin-fraction summing as concrete rules. The recipe's audience includes laboratory-informatics teams who may design rule libraries based on the recipe's framing; skipping the coherence-rule layer because the pseudocode skips it produces a system missing one of the highest-value detection layers. Fix: add a `panel_coherence_check` function to Step 7 with example rules for anion gap, Hgb/Hct ratio, TSH/T4, and bilirubin fractions; run it before the panel multivariate check; both contribute flags to panel-level routing. |
| A5 | MEDIUM | Architecture / Healthcare Compliance | Step 6 `route_result` `"critical_callback"` branch; "Why This Isn't Production-Ready" Critical-value callback workflow paragraph; The Honest Take's "the critical-value callback workflow is more complex than it looks" ("40% of the engineering effort in the critical-path part of the pipeline") | Recipe correctly identifies in prose that CLIA critical-callbacks are a regulated workflow with timing, read-back, escalation, and documented manual fallback. Step 6's pseudocode is a single SNS.Publish call. No callback-state-machine primitives (initiated → acknowledged → read-back-captured → closed), no escalation timer, no fallback-to-manual-phone-call path. CLIA inspectors review callback logs; a callback sent but not closed within the window is a regulatory finding even if the clinician acted on the result. Fix: expand Step 6 pseudocode to demonstrate callback-state-machine with `callback_id`, DynamoDB callback-records store, EventBridge Scheduler escalation timer, and callback-service ownership; or alternatively add an explicit "the callback workflow is documented in the callback service's design" pointer with a state diagram in the General Architecture Pattern's Routing subsection. |
| A6 | MEDIUM | Architecture / Healthcare Compliance | Step 1 `normalize_result` (correctly captures `reference_range_version`); Step 6 `route_result` (constructs `outlier_event` without propagating it); OpenSearch audit index | Step 1 correctly captures `reference_range_version` on the canonical_result, and the rule library is versioned per Prerequisites. But Step 6's `outlier_event` construction drops the field, so the OpenSearch index that drives lab director and pathologist dashboards does not store the range version that was in force at flag-firing time. The Honest Take's framing "audit trails that don't record which range was in force for a given alert are not audit trails; they're wishes" is the right teaching; the pseudocode contradicts it. Fix: add `reference_range_version`, `rule_library_version`, `analyte_metadata_version`, and `method` fields to the Step 6 outlier_event construction; add note to audit-event documentation that every flag carries the rule library and reference range versions for reproducibility. |
| S1 | MEDIUM | Security | Step 6 `route_result` `"critical_callback"` branch (`SNS.Publish(topic = CRITICAL_CALLBACK_TOPIC, message = build_callback_payload(outlier_event))`) | The pseudocode's SNS message construction is not specified explicitly; the Python companion does the right thing (event-id + minimal context only) but the main recipe doesn't state the discipline. SMS/pager/Teams/Slack notifications are visible on lock screens and in shared logs; for high-stigma test types (HIV viral load, hepatitis C viral load, syphilis serology, drug-of-abuse panels, mental health markers like lithium, gender-affirming hormone monitoring) even the LOINC display name is a diagnostic disclosure. Same chapter-3-settled "event-id-only" convention from Recipes 3.1, 3.3, 3.4 should be stated explicitly. Fix: update Step 6 pseudocode to publish only event_id, severity, fetch_by_id, and minimal location attribute; for high-stigma test classes, exclude LOINC display name from notification subject; add Why-These-Services note naming the convention. |
| S2 | MEDIUM | Security / Compliance | "The Technology" reference-range subsection (population-specific intervals); "Why This Isn't Production-Ready" Bias and Equity Monitoring bullet | Recipe correctly identifies the creatinine-GFR race coefficient revision (a real, recent, well-documented change), names population-aware reference range validation as ongoing, and explicitly says subgroup monitoring is part of the minimum deployment. Architectural artifacts that make subgroup monitoring binding are not specified: where demographic data lives, who has read access, how it joins to outlier events and override records, audit trail for subgroup queries, IAM scope for retraining and dashboard roles. Same finding shape as Recipes 3.2 S2, 3.3 S2, 3.4 S2. Fix: add Subgroup data access row to Prerequisites; restrict read access to demographic store to retraining and dashboard roles; CloudTrail data events on subgroup queries; QuickSight queries against an aggregated subgroup-metrics table rather than the raw demographic-joined outlier archive. |
| A7 | LOW | Architecture | Step 3 rule_screen, Step 4 baseline_checks, Step 6 `determine_routing(all_flags)` | Three different severity vocabularies appear in pseudocode without an explicit mapping (flag-level "critical_callback", "informational", "tech_review_hold", "synchronous"; routing-level "autoverify_with_flag", "critical_callback", "tech_review_hold", "recollect_requested"). `determine_routing` is just `determine_routing(all_flags)` without explicit logic. Fix: provide explicit `determine_routing` body or add precedence-rules paragraph to Flag aggregator subsection. |
| A8 | LOW | Architecture | Expected Results "Performance benchmarks" table | Performance benchmarks present specific ranges that read as published or measured; HTML-comment TODO acknowledges they are directional. Two specific numbers warrant additional caveat: "Real critical-value miss rate <1%" implies multi-month chart-review measurement that most labs do not have; "Pre-analytical artifact catch rate 65-85%" implies a recollect-confirmed-artifact denominator that production systems typically approximate. Fix: move TODO into visible inline caveat above table or resolve TODO with citations to CAP Q-Probe / Q-Tracks figures. |
| S3 | LOW | Security | Step 2 `enrich_with_patient_context` (DynamoDB GetItem); Step 6 `route_result` (EventBridge PutEvent); Prerequisites IAM row | Patient-context-cache and outlier-events bus are shared resources accessed by multiple Lambdas; recipe gives generic least-privilege framing but doesn't break out per-consumer roles. A compromised role with broad cache-write access could silently corrupt patient context (stale demographics, wrong dialysis flag, wrong pregnancy status), propagating into wrong reference-range selection, wrong delta-check calibration, wrong cohort lookup. Fix: per-consumer IAM scope examples in Prerequisites IAM row covering real-time outlier service Lambda (read-only on cache), cache-refresher Lambda (write-only on cache), critical-value-callback Lambda (consume from bus, no produce; sns:Publish on callback topic only), autoverify-release Lambda (consume from bus, write to LIS-EHR bridge), feedback-capture Lambda (write to labels store and feedback bus only). |
| S4 | LOW | Security / Networking | Why-These-Services Amazon MQ paragraph; Architecture Diagram on-prem MLLP bridge; Prerequisites Lab Integration row | On-premises MLLP receiver is the PHI ingress surface from LIS to AWS. Recipe describes the pattern at a high level but doesn't specify MLLP-over-TLS with mutual TLS authentication, Site-to-Site VPN vs Direct Connect, MQ broker authentication, or DMZ deployment. Same shape as Recipe 3.4 S3. Fix: one-paragraph note covering MLLP-over-TLS, mutual TLS, Direct Connect for production volumes, DMZ deployment, short-lived IAM-derived tokens. |
| S5 | LOW | Security / Healthcare Compliance | Why-These-Services Amazon Bedrock paragraph; "The Technology" Statistical Methods LLM-assisted-interpretation paragraph; Variations LLM-assisted-prioritization extension | LLM-assisted interpretation correctly framed as experimental and validation-required, but BAA-discipline forward reference to Chapter 2's established patterns is missing. Bedrock with Amazon foundation models is HIPAA-eligible; third-party models on Bedrock have differing BAA postures. "HIPAA-eligible LLM" framing doesn't differentiate. Same shape as Recipe 3.3 V2 and Recipe 3.4 S4. Fix: expand Bedrock paragraph to acknowledge Amazon foundation models vs third-party differentiation; name minimum-necessary prompt construction, output filtering for clinical hallucinations, full prompt-and-response audit trail; forward-reference Chapter 2's generative AI recipes. |
| S6 | LOW | Security / Networking | Architecture Diagram (`Reference Lab Feeds | SFTP / HL7 batch | AWS Transfer Family`) | Reference labs (Quest, LabCorp) push send-out result files to SFTP. Recipe doesn't specify VPC vs public endpoint, authentication method (SSH key vs password vs custom IDP), or source-IP allowlist for the reference lab's known egress ranges. Fix: add Transfer Family note covering VPC endpoint, source-IP allowlist via SG or IAM-resource-policy conditions, SSH key authentication with out-of-band public key exchange, KMS encryption at rest, CloudTrail data events on the inbound prefix. |
| N1 | LOW | Networking | Prerequisites VPC row | Multiple precision gaps (CloudWatch monitoring vs Logs, EventBridge events vs Scheduler, SageMaker api/runtime/featurestore-runtime, SNS, Step Functions, Pinpoint, bedrock-runtime, comprehendmedical). Same recurring chapter pattern as Recipes 3.2 N1, 3.3 N1, 3.4 N1. Fix: explicit endpoint inventory with per-endpoint identifier names. |
| N2 | LOW | Networking / Compliance | Prerequisites VPC row; CloudTrail row | VPC Flow Logs not explicitly required. CloudTrail covers API audit but not network-level access; HIPAA audit posture typically requires both. CLIA inspectors and CAP surveyors expect network-level audit when investigating suspected unauthorized access to lab data stores. Same recurring chapter pattern. Fix: add VPC Flow Logs requirement with KMS-encrypted S3 destination and retention aligned to deepest applicable requirement. |
| V1 | LOW | Voice / Domain Accuracy | Opening vignette ("A recollection from a central line with immediate transport shows potassium 4.2") | Phrasing reads as if central-line recollect is the standard pseudohyperkalemia investigation. Canonical approach is properly drawn peripheral recollect with proper technique and immediate transport. Central line draws have their own pre-analytical risks (infusate contamination from line lumen, line-lock contamination). Fix: change to "A properly drawn peripheral recollect with immediate transport shows potassium 4.2" or add one-clause justification for the central-line choice. |
| V2 | LOW | Voice / Publication Readiness | Expected Results sample alerts (LAB-2026-05-12T..., 2026-05-12T06:42:11Z, etc.) | Future-dated event IDs and timestamps will age awkwardly post-publication. Same observation as Recipes 3.1, 3.2, 3.3, 3.4 V1/V2. Fix: replace with placeholder pattern or add HTML-comment disclaimer. |
| V3 | LOW | Voice / Publication Readiness | "The Technology" Three-Stage Lab Workflow paragraph; Cost Estimate row; "Why This Isn't Production-Ready" FDA LDT paragraph; Performance benchmarks table; Code section aws-samples references; Additional Resources section | Six HTML-comment TODOs are present, all forward-placeholder. Three should be resolved before publication: pre-analytical error rate citation (CAP Q-Probe, CLSI, peer-reviewed); pre-analytical error cost estimate (CAP, IQLM); FDA LDT 2024 rule status verification (rule was issued May 2024 with phased implementation; verify current phase status). Forward-looking Bedrock and aws-samples placeholders can remain. |
| V4 | LOW | Voice / Pedagogy | Variations Sepsis early warning extension; Related Recipes section | Recipe 3.7 cross-reference is operationally correct (lab trajectory features feed sepsis risk models). Optional editorial: add inline framing of which trajectory signals (rising lactate, rising creatinine, dropping bicarbonate, dropping platelets) feed sepsis scoring, for readers who jump straight to this recipe. |

---

## Recommended Actions (Priority Order)

1. **Close the prose-vs-pseudocode asymmetry on method/reagent-change handling and cross-test coherence rules** (Findings A3 and A4). These are the highest-leverage fixes because the prose explicitly elevates these as core disciplines and the canonical pseudocode walkthrough doesn't reflect them. Two coordinated edits:
   - A3: update Step 4 `patient_baseline_checks` to compare `method` between current and previous results, suppress absolute-delta on method mismatch unless `analyte_metadata.method_harmonization` provides a coefficient; add paragraph to General Architecture Pattern's Patient-baseline path subsection.
   - A4: add `panel_coherence_check` function to Step 7 with example rules for anion gap, hemoglobin/hematocrit ratio, TSH/T4 consistency, and bilirubin-fraction summing; run before the panel multivariate check.

2. **Add outcome-event idempotency to the feedback-capture Lambda** (Finding A1). Derive a deterministic event key (`outlier_event_id + decision` for tech review; `original_outlier_event_id + recollect_accession` for recollects); conditional DynamoDB write to `processed-feedback-events` table before OpenSearch update, label write, and metric emission. Add "Trigger idempotency" bullet to "Why This Isn't Production-Ready." Strongly recommend a cookbook-wide trigger-idempotency appendix to consolidate this recurring pattern (now eleven recipes deep).

3. **Add DLQ / poison-message handling for the result-normalizer, real-time-outlier-service, and feedback-capture Lambdas** (Finding A2). Add three SQS DLQs to the Architecture Diagram with `OnFailure` destinations; CloudWatch alarms on DLQ depth (alarm threshold 1 for the real-time path because a single dropped result is a CLIA-audit-trail event); Prerequisites note covering replay discipline including time-bound for replayability.

4. **Demonstrate CLIA critical-callback workflow primitives in pseudocode** (Finding A5). Either expand Step 6's `"critical_callback"` branch to show callback_id, DynamoDB callback-records store, EventBridge Scheduler escalation timer, and the four state-machine states (initiated, acknowledged, read-back-captured, closed); or alternatively add an explicit pointer with a state-diagram in the General Architecture Pattern's Routing subsection deferring details to the callback service's own design.

5. **Propagate reference-range version into the routing event and audit index** (Finding A6). Add `reference_range_version`, `rule_library_version`, `analyte_metadata_version`, and `method` to the Step 6 outlier_event construction; add explicit note that every flag carries the versions that were in force at flag-firing time for CLIA-inspection reproducibility.

6. **Tighten SNS critical-callback payload PHI minimization** (Finding S1). Update Step 6 pseudocode to publish only event_id, severity, fetch_by_id; for high-stigma test classes (HIV, hepatitis C, syphilis, drug screens, gender-affirming hormones, psychiatric medication monitoring) exclude LOINC display name from notification subject; add Why-These-Services note naming the convention.

7. **Specify subgroup data governance at the infrastructure level** (Finding S2). Add a Subgroup data access row to Prerequisites; restrict read access to the demographic store to retraining and dashboard roles; CloudTrail data events on subgroup queries; QuickSight against an aggregated subgroup-metrics table.

8. **Close the LOW architecture findings** (A7, A8). Provide explicit `determine_routing` body or precedence-rules paragraph; move performance-benchmark caveat from HTML-comment TODO into visible inline caveat above the table.

9. **Close the LOW security and networking findings** (S3, S4, S5, S6, N1, N2). Per-consumer IAM scoping; HL7 v2 MLLP bridge security; Bedrock BAA-discipline forward reference; Transfer Family SFTP source-IP allowlist; VPC endpoint precision; VPC Flow Logs requirement.

10. **Close the LOW voice findings** (V1, V2, V3, V4). Adjust opening vignette's "central line" phrasing to align with canonical pseudohyperkalemia investigation. Replace future-dated timestamps. Resolve industry-figure TODOs (pre-analytical error rate, error cost, FDA LDT rule status). Optional inline framing of trajectory-to-sepsis cross-reference.

---

## Notes for Editor

- There are zero HIGH findings. The MEDIUM findings cluster across architectural completeness with a heavy prose-vs-pseudocode asymmetry signature: A3 (method changes), A4 (cross-test coherence rules), A5 (callback workflow), and A6 (audit-trail propagation) are all places where the prose makes a discipline claim that the canonical pseudocode walkthrough doesn't reflect. A1 (idempotency), A2 (DLQs), S1 (PHI minimization), S2 (subgroup governance) are the recurring chapter-wide patterns. The LOW findings cover operational and editorial polish.

- The two highest-leverage fixes are A3 (method-change suppression in delta checks) and A4 (cross-test coherence rules in pseudocode). Both are editorially small (a method-comparison branch in Step 4; a `panel_coherence_check` function in Step 7) but materially important because the recipe's domain authority depends on the pseudocode actually demonstrating the lessons in the prose. A reader who treats the pseudocode as the implementation specification produces exactly the failure modes the prose warns against.

- Finding A1 is the now-recurring trigger-idempotency pattern, surfacing for the eleventh consecutive recipe (2.4-2.10 and 3.1-3.5). The cookbook would benefit substantially from a shared appendix that covers the patterns once. Each subsequent recipe could reference the appendix rather than repeat the discipline. With the per-recipe-edit posture producing diminishing returns, the trigger-idempotency appendix is the highest-leverage cookbook-wide editorial investment.

- Finding A2 (DLQs) is operationally critical for this recipe specifically because the pipeline gates autoverification. For Recipes 3.1, 3.2, 3.3 a dropped event is an operational concern; for Recipes 3.4 and 3.5 a dropped real-time event is a result that bypasses screening, which for Recipe 3.5 means a result released to chart without an outlier check. The DLQ-depth alarm threshold for the real-time path should be 1 (single-event sensitivity), not the typical "alert on sustained backlog" pattern.

- Finding S1 is the now-recurring PHI-minimization-inside-the-BAA pattern with the sixth distinct surface across the cookbook (Chapter 2: serialized prompt context; Recipe 3.1: examiner free-text reasoning; Recipe 3.2: patient-facing reminder content for high-stigma specialties; Recipe 3.3: internal SNS notification payload; Recipe 3.4: SNS interrupt-alert payload with high-stigma drug-class disclosure; Recipe 3.5: SNS critical-callback payload with high-stigma test-class disclosure). A cookbook-wide PHI-minimization appendix would consolidate all six surfaces with one teaching pass.

- The Honest Take section is publication-ready and should be preserved verbatim. The seven-paragraph structure (delta checks do more work than any other component, specimen quality fusion is the biggest unspoken lever, critical-value callback workflow is more complex than it looks, reference ranges encode more complexity than expected, autoverification is where the ROI lives, patient-specific baselines beat population baselines, cross-test coherence rules surprised me) is the kind of operations-engineer voice the cookbook is built on. The closing trap warning ("do not let 'flag rate' become the primary business metric") is publication-ready voice on the most consequential business-metrics framing in this domain.

- The opening 6:42 a.m. potassium-7.8 vignette is the densest pre-analytical-artifact framing in any cookbook recipe and should not be shortened. The 74-year-old admitted overnight for community-acquired pneumonia, the peripheral draw that sat at the nursing station for 90 minutes before pickup, the visibly hemolyzed sample with hemolysis index 4+, the recollect that confirms pseudohyperkalemia, and the patient sitting up eating oatmeal while the rapid response team assembles is the kind of texture-rich storytelling that distinguishes the cookbook from documentation. The minor fix on V1 (changing "central line" to "properly drawn peripheral recollect") preserves all of this while aligning with canonical clinical guidance.

- The reference-range subsection is the most substantive treatment in any cookbook recipe to date and should be preserved verbatim. The age-and-sex-banding examples (hemoglobin for adult male vs adult female vs 9-month-old; alkaline phosphatase in adolescents vs adults; creatinine and muscle mass), pregnancy physiology (trimester-specific TSH, dilutional hemoglobin drop, placental-source alkaline phosphatase, lower creatinine), population-specific intervals with the 2021 NKF-ASN race-coefficient revision, method-specific calibration, and critical-vs-action-vs-reference tiers each carry detail-level teaching that operational lab analytics teams will recognize and rely on.

- The autoverification connection subsection is the recipe's biggest pedagogical contribution. The framing of autoverification and outlier detection as flip sides of the same architectural idea (sharing input data, model machinery, and producing complementary outputs of release vs. hold and alert vs. quiet) is the architecturally correct unification that most production deployments converge on. The closing observation that "the outlier detector can be the brain of the autoverification decision" is the right teaching for how to factor the system, and it is the design lesson most first-time builders miss.

- Style hygiene is exceptionally clean: zero em dashes (verified directly), no marketing language, no documentation-voice. The 70/30 vendor balance is preserved cleanly. HTML-comment TODO discipline is correct (six TODOs total, all forward-placeholder, no bracket-style visible TODOs). The pre-analytical error rate, error cost, and FDA LDT rule status citations should be resolved before publication; the forward-looking Bedrock and aws-samples placeholders read cleanly.

- Coordinate with the existing code review (`reviews/chapter03.05-code-review.md`). The code review PASSed-with-reservations on three WARNINGs and seven NOTEs in the Python companion. WARNING 1 (broken `__name__ != "__production__"` assert) has now appeared in all five Chapter 3 Python companions; treat it as the single-cookbook-wide-fix candidate. WARNING 2 (S3 `put_object` without `SSEKMSKeyId`) parallels Recipes 3.1, 3.2, 3.3, 3.4. WARNING 3 (creatinine `mmol_factors` table mislabeling: 88.4 stored under a `"mmol/L"` branch when 88.4 is the mg/dL ↔ μmol/L factor and the mg/dL ↔ mmol/L factor is 0.0884) is recipe-3.5-specific and Python-companion-only. For a recipe whose opening framing explicitly calls out unit-conversion errors as a classic source of clinical mistakes, the unit-conversion error in the Python companion is consequential even if `__main__` doesn't exercise the branch. The code review and editor's pass should fix this together.

- The autoverification stakes are the same calibration as Recipe 3.4 (medication dispensing): the outlier pipeline gates result release to the chart, and a dropped or mis-screened result can produce direct patient harm through pseudohyperkalemia-driven inappropriate treatment, missed delta-check signals for acute bleeding or renal failure, or false reassurance from artifactual results. The recipe correctly addresses this in the three-categories framing, the alert-fatigue subsection, the CLIA validation discussion, and the disaster-recovery paragraph. The MEDIUM severity is appropriate (none rise to HIGH) but the editorial pass should recognize that the same finding category has higher operational stakes here than in Recipes 3.1, 3.2, 3.3.

- The fairness surface area is distinctive and unusually well-handled: the recipe explicitly names the creatinine-GFR race coefficient revision (a real, recent, and well-documented change in clinical practice), names population-aware reference range validation as ongoing rather than check-the-box, and explicitly says subgroup monitoring is part of the minimum deployment. The architectural artifacts that operationalize this (S2) are the operational-completeness gap, but the framing-level treatment is the best in any cookbook recipe to date and should be preserved.
