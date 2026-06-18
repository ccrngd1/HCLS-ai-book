# Open TODOs — Recipe 4.8: Treatment Response Prediction ⭐⭐⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (31 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter04.08-treatment-response-prediction.md`

- **L24** — TODO: confirm current FDA Clinical Decision Support guidance and 21st Century Cures Act exemption criteria; the exemption is fact-specific and depends on the form of the recommendation, the underlying evidence, and the clinician's ability to review.
- **L113** — TODO: confirm current FDA guidance documents and the SaMD change control plan framework.
- **L115** — TODO: cite specific recent foundation-model-for-EHR work; the field is moving fast and citations should reflect recent literature at time of build.
- **L125** — TODO: cross-reference Recipe 13.x knowledge graph and Recipe 2.x evidence synthesis; the right integration depends on what the organization licenses.
- **L312** — TODO: confirm current FDA SaMD framework and Cures Act CDS exemption criteria; the regulatory landscape is evolving.

## architecture — `chapter04.08-architecture.md`

- **L11** — TODO: confirm SageMaker Real-Time Inference and Batch Transform HIPAA eligibility, and the appropriate instance types for the model sizes implied here.
- **L33** — TODO: confirm current Bedrock service terms, the eligible-model list, and the data-handling guarantees at the time of build.
- **L41** — TODO: confirm AWS HealthLake's current pricing, HIPAA eligibility, and FHIR specification version support.
- **L149** — TODO: pair these actions with one or two scoped Resource ARN examples. Same chapter-wide pattern flagged in 4.1 through 4.7.
- **L150** — TODO: confirm Bedrock + selected models, HealthLake, and any EHR-integration components at the time of build.
- **L154** — TODO: confirm current FDA Clinical Decision Support guidance, the Cures Act CDS exemption criteria, and the Good Machine Learning Practice principles applicable at the time of build.
- **L156** — TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- **L192** — TODO: confirm the current names and locations of the aws-samples repos.
- **L786** — TODO (TechWriter): Expert review S3 (MEDIUM). document the four-layer validator
        // pattern in the same shared specification used for 4.5
        // through 4.7, and extend it with the recommendation-language
        // and uncertainty-completeness layers specific to 4.8.
        // Specify (a) eleven-plus aggressive recommendation-language
        // patterns; (b) a fact-grounding layer that requires every
        // numeric value cited to trace byte-for-byte to a field in
        // observed_context.pair_results; (c) an uncertainty-completeness
        // layer that requires CI alongside every cited point estimate
        // and explicit OOD/disagreement disclosure when those flags
        // fire; (d) required-caveats including the observational-data
        // and conditional-average framings. Specify failure-handling
        // progression: regenerate with feedback, regenerate strict-mode,
        // fall back to templated. Co-specify with the OOD-suppression
        // bands tagged as A3 in Step 4.
- **L1248** — TODO: the benchmarks above are illustrative ranges informed by the published causal inference literature for treatment-effect estimation; replace with measured results from your deployment. Be wary of vendor-published numbers that report "X% accuracy" for treatment recommendations; accuracy is not the right metric for treatment effect estimation, and headline accuracy claims often elide calibration, fairness, and uncertainty.
- **L1273** — TODO (TechWriter): Expert review A10 (MEDIUM). Specify the SageMaker training-job trigger mechanism and model-promotion path for the propensity, outcome, and CATE-ensemble models. With three or more model artifacts per treatment-comparator pair times ten to thirty pairs, the model registry and promotion automation are central. Mirror the EventBridge-trigger plus SageMaker-Model-Registry-with-canary-run pattern flagged in 4.4 through 4.7, with the additional governance gate from Step 3.
- **L1275** — TODO: confirm current FDA SaMD framework, the Cures Act CDS exemption criteria, and the Good Machine Learning Practice principles applicable at the time of build.
- **L1279** — TODO (TechWriter): Expert review N2 (MEDIUM). Specify the SMART on FHIR / CDS Hooks integration credential posture: OAuth 2.0 with PKCE for SMART launches with JWT validation against the EHR's JWKS endpoint and audience/issuer pinning; mutual TLS or HMAC-signed bearer tokens for CDS Hooks calls with replay protection (timestamp + nonce); OAuth client secrets and HMAC keys in AWS Secrets Manager with KMS encryption and 90-day rotation; per-EHR-tenant TLS certificates managed via ACM; per-tenant audit logging of launch context, requesting clinician, patient context, and scoring API response. The clinician-facing scoring API is the highest-stakes integration in Chapter 4 and the credential posture deserves specification rather than the high-level "PrivateLink, Direct Connect, or institution-private network" framing.
- **L1283** — TODO (TechWriter): Expert review A6 (MEDIUM). Add a specification for the patient consent flow and the shared-decision capture pattern. The pattern needs to handle: (a) consent to the use of model-derived predictions in the patient's care; (b) consent to ongoing data use for model retraining; (c) capture of the patient's stated preferences and their influence on the chosen treatment; (d) the right to withdraw consent and have predictions excluded from future scoring. Mirror the language from 4.5 through 4.7 where applicable, but the consent layer here is more substantive because the prediction is a clinical-decision input.
- **L1287** — TODO (TechWriter): Expert review S2 (MEDIUM). Replace the string-concatenation scoring_run_id, briefing_id, decision_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids embedded in identifiers carried in EHR responses, scoring API responses, and decision events are PHI leakage. The treatment-class-in-identifier pattern (e.g., po-2026-07-21-pat-007842-glp1) is sharper than prior recipes because it intersects with state-specific confidentiality statutes for analogous pairs in stigmatized clinical areas (42 CFR Part 2, state mental-health-confidentiality laws). Mirror the language flagged in 4.4 through 4.7. Update Expected Results sample identifiers accordingly.
- **L1293** — TODO (TechWriter): Expert review A5 (MEDIUM). Architect adverse-event surveillance as first-class pseudocode in Step 6, alongside calibration drift detection. Per pair: define the adverse events of interest at model promotion (GLP-1 -- pancreatitis, severe GI; SGLT2 -- DKA, Fournier's gangrene; sulfonylurea -- severe hypoglycemia hospitalization), establish expected rates from training and trial data, compute observed rates per million patient-days of exposure in the surveillance window, fire alerts via Poisson or exact binomial test at p < 0.01 conditional on a minimum exposure floor, and produce cohort-stratified versions. Surveillance alerts integrate with the existing surveillance-alerts table. Reference Sentinel and OHDSI as the consortium-scale path.
- **L1295** — TODO (TechWriter): Expert review A7 (MEDIUM). Specify a separate validate_patient_summary function for the patient-facing path, distinct from the clinician-facing validator. Layers: (1) reading-level enforcement per Recipe 4.2 pattern; (2) prohibition of probabilistic point estimates as percentages and "you will [outcome]" framing in favor of "patients similar to you" cohort-based phrasing; (3) recommendation-language patterns plus extensions for patient context; (4) required content including shared-decision framing and approved-claim-language compliance.
- **L1297** — TODO (TechWriter): Expert review A8 (MEDIUM). The cohort-feature lookup at lookup_cohort_features(decision.patient_id) inside the per-pair scoring loop in Step 4 and inside match_outcome in Step 6 repeats per patient; chapter-wide pattern from 4.4 through 4.7. Hoist the cohort-feature cache out of the per-pair loop and compute once per patient. With 5 to 10 eligible pairs per patient and thousands of patients per surveillance run, the redundant lookups multiply.
- **L1299** — TODO (TechWriter): Expert review S4 (MEDIUM). Specify the de-identification posture for treatment-response briefings inside the Privacy paragraph. Banded clinical features (eGFR_band, BMI_band, A1c_band) rather than precise lab values. Demographic attributes (race, ethnicity, language, SDOH cohort) excluded by default with explicit pharmacy-and-therapeutics-committee opt-in only when the attribute is clinically relevant (pharmacogenomic indications). No patient_id or clinician_id in prompts; minimum-necessary disclosure remains the architectural posture even for HIPAA-eligible services.
- **L1305** — TODO (TechWriter): Specify DLQ coverage on all Lambda paths in the architecture. (a) Step Functions to Lambda pipeline: Catch on each Lambda task pointing to an SQS failure queue keyed on (run, stage, treatment_pair); (b) Kinesis to state-machine-worker Lambda: configure an OnFailure destination on the event source mapping; (c) SageMaker Real-Time inference failures: wire the scoring orchestrator's error handling to a degraded-state response that returns "scoring temporarily unavailable" rather than a partial or stale prediction. The point-of-care scoring path must fail loudly and return a non-prediction response rather than silently degrade. Mirror the language from 4.4 through 4.7.
- **L1361** — TODO: confirm the current names and locations of the aws-samples repos; they have been reorganizing.
- **L1368** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- **L1378** — TODO: confirm reference and update to a specific stable URL at the time of build.
- **L1382** — TODO: confirm the current FDA SaMD framework documents at the time of build.
- **L1383** — TODO: confirm the current FDA CDS guidance and the 21st Century Cures Act exemption criteria at the time of build.
- **L1384** — TODO: confirm the current GMLP guidance at the time of build.
