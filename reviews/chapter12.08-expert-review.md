# Expert Review: Recipe 12.8 - Disease Progression Trajectory Modeling

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-26
**Recipe file:** `chapter12.08-disease-progression-trajectory-modeling.md` (PRESENT)
**Python companion:** `chapter12.08-python-example.md` (PRESENT)
**Code review:** `reviews/chapter12.08-code-review.md` (PRESENT, PASS with 1 WARNING + 9 NOTES)

---

## Overall Assessment

**Verdict: PASS**

This is a strong recipe. It is one of the most clinically and technically dense recipes in chapter 12 to date, and it lands the chapter pattern: concrete bedside-meaningful opening vignette (a 54-year-old ADPKD patient with nine years of longitudinal data and a 4.2 mL/min/1.73 m^2/year eGFR slope), three-layer model framing (population shape, per-patient deviation, intervention effect) that captures the actual statistical structure correctly, explicit naming and tradeoff comparison of the major model families (linear mixed-effects, non-linear mixed-effects, Bayesian hierarchical, joint models, Gaussian processes, deep learning), counterfactual reasoning grounded in causal inference vocabulary (g-computation, marginal structural models with IPW, target trial emulation) with the trial-literature-prior plug-in approach honestly acknowledged as the production-defensible compromise, calibration as the first-class operational metric, regulatory framing that lands on the operational-CDS side of the FDA SaMD line with the 21st Century Cures Act §3060 transparency-and-explainability requirements named explicitly, and a Honest Take with five distinct observations that read like lived experience rather than literature review. The voice is consistent with chapter 12 prior recipes; em-dash count is zero (verified by U+2014 codepoint scan); the 70/30 vendor balance is held; the "math is the easy part" thesis lands for the third time in the chapter and is owned in the prose ("you will notice this is becoming a theme in this chapter; it is not a coincidence"). The pseudocode aligns with the Python companion's structure across all five steps and the code reviewer found no ERROR-level issues.

The findings below are real but none rise to CRITICAL. The HIGH findings are clinical-precision concerns that the TechEditor should fix before publication; the MEDIUM findings are structural gaps that affect production fidelity but not the recipe's pedagogical correctness; the LOW findings are polish.

Priority breakdown: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW. **Verdict: PASS** (under the FAIL threshold of >0 CRITICAL or >3 HIGH).

---

## Stage 1: Independent Expert Reviews

### Security Expert Review (OWASP, CIS, NIST SP 800-66 for HIPAA)

**Strengths.**

- The Prerequisites table elevates the PHI-sensitivity framing correctly: "Trajectory data is PHI in the strongest sense: longitudinal disease-specific records tied to genetic phenotypes are inherently re-identifiable." This is the right framing for ADPKD, where PKD1/PKD2 mutation status combined with longitudinal eGFR-and-TKV data is genetically re-identifiable to a level that defeats most de-identification schemes. The recipe does not soft-pedal this.
- Customer-managed CMKs per data class are specified with the chapter pattern: cohort datasets, model artifacts, forecasts, priors. The KMS posture for SageMaker training and inference (KMS-encrypted EBS volumes and KMS-encrypted output) is called out.
- CloudTrail data events are explicitly required on every PHI-bearing S3 bucket and the DynamoDB serving table, with Object Lock in compliance mode for the audit trail. The "audit trail of who accessed which patient's trajectory" framing is correct, especially the rare-disease-cohort emphasis.
- The IAM permissions list scopes the service actions correctly (`healthlake:SearchWithGet`, `healthlake:ReadResource`, `s3:GetObject`/`PutObject`, `glue:StartJobRun`, `sagemaker:CreateTrainingJob`/`InvokeEndpoint`/`CreateTransformJob`, `lambda:InvokeFunction`, `dynamodb:BatchWriteItem`/`Query`, `states:StartExecution`, `kms:Decrypt`/`Encrypt`) and adds the chapter-pattern qualifier "Each pipeline component runs under a least-privilege role scoped to its data class."
- Synthetic-data discipline is specified: Synthea (with the CKD-module note), MIMIC-IV through PhysioNet credentialing, with the explicit "Never use real PHI in dev" rule.
- The Why-This-Isn't-Production-Ready section's "Cohort definition governance" item is a security-adjacent concern done well: cohort definitions are versioned, clinician-reviewed, controlled rollout, with retroactive recomputation. This is the right framing for what is effectively change-management governance over the analytic surface.

**Gaps.**

- **Imaging-and-genetics ingestion paths are mentioned but not security-modeled.** The Variations section calls out integrating MRI-derived TKV (Recipe 9.x) and genetic markers (PKD1 vs PKD2). The PHI exposure of these modalities is materially different from EHR data: imaging is HIPAA-PHI plus the specific re-identifiability concerns of structural neuroimaging (and to a lesser extent body imaging); genetic data is separately covered by GINA in addition to HIPAA, with state-specific layers (California genetic information privacy regulations, for example, are stricter than federal). The recipe should call out that the BAA-and-consent layer is materially different for imaging and genetics, not just an additional pipeline step. (See Finding M1.)
- **Counterfactual scenario inputs are not explicitly modeled as a privileged action surface.** A clinician requesting a counterfactual scenario ("what if we start tolvaptan in three months") is initiating a clinical-grade analytic action that should be authenticated, authorized, and audit-logged at the same standard as ordering a lab. The Lambda counterfactual composer takes a user request and runs a model invocation that produces a clinical-decision-supporting output. The recipe describes the technical flow but does not specify the authentication-and-authorization posture for that surface. (See Finding M2.)
- **Patient-facing surfaces are correctly flagged as a gap but the security framing is implicit.** The Why-This-Isn't-Production-Ready section says patient-facing prognostic outputs are "scrutinized more carefully than clinician-facing ones." The security framing is that patient-facing surfaces (a portal display of "your projected eGFR over five years") have a different access-control model: the patient is the data subject, but the portal authentication, the consent-to-display posture, the downloadable-PDF hazard if the trajectory leaves the institutional perimeter, and the family-member-access scenarios are all separate from clinician-facing. The recipe should mention this explicitly. (See Finding L4.)

### Architecture Expert Review

**Strengths.**

- The three-layer model framing (population shape, per-patient deviation, intervention effect) is the architecturally correct decomposition. The recipe does not collapse it into "fit a single model and call it done."
- The acute-vs-chronic separation is elevated as a first-class architectural concern, with explicit handoff to Recipe 12.7 for acute-context trajectory monitoring. This is the right way to scope the recipe and avoid the common chapter-pattern failure mode of one recipe trying to handle both contexts.
- The five-step pipeline (cohort definition -> harmonization -> trajectory model training -> per-patient inference -> counterfactual scenarios) is the right decomposition. Each step has a clear input, output, and clinical purpose. Step 5 (counterfactual scenarios) is correctly identified as "the architecturally distinctive step for trajectory modeling, and it is where most of the clinical value sits."
- The model-family menu is honest: linear mixed-effects, non-linear mixed-effects, Bayesian hierarchical, joint models, Gaussian processes, deep learning. The recipe explains why each shows up in production and which diseases each fits, which is the right level of architectural commentary. The 2026 state-of-the-art summary is realistic ("most production deployments still favor the simpler families above for the routine cases and reserve deep learning for diseases where the competing methods have visibly failed").
- The Step Functions orchestration with explicit retry/error semantics and the EventBridge cadence layer (weekly cohort refresh, monthly retrain, daily inference, ad-hoc priors-update on new trial publication) match the chapter-12 pattern.
- The architecture diagram captures the trial-literature priors as a separate input to the model-artifact bucket, which is the right structural choice (priors are versioned independently of model code and cohort definitions).
- DynamoDB partition key (patient_id) and sort key (disease_name + "#" + generated_at_ts) is the right design for the three primary access patterns (single patient lookup, per-disease cohort scan, time-ordered audit query).
- The "Where it struggles" section is honest and specific: insufficient measurements per patient, insufficient observation history, active titration, weak literature foundations, rare-disease cohorts, untrained intervention combinations, acute-episode contamination, long-horizon extrapolation. This is the right list.

**Gaps.**

- **The pseudocode `apply_treatment_change` does not handle pre-existing exposure to the requested drug class.** This is the architectural manifestation of the W1 finding from the code review. When a clinician asks "what if we start SGLT2 inhibitor now" for a patient already on an SGLT2 inhibitor, the function blindly appends a new entry, which then gets multiplied through `_treatment_modifier`, producing double-counted modifier effects. The pseudocode in Step 5 (line 491-505) inherits the same shape and a careful reader will copy the bug into their production system. The recipe should either show the dedup logic in pseudocode or call it out as a "what to watch out for" comment so the pseudocode communicates the real architectural requirement. (See Finding H1.)
- **The transplant endpoint is mentioned in the opening vignette but is not architecturally first-class.** The vignette explicitly invokes "transplant evaluation timing, vascular access planning, and whether to enroll in a tolvaptan trial," and the regulatory framing in The Honest Take notes that endpoint timing for transplant is a high-stakes decision. But the architecture's `ENDPOINT_DEFINITION` (eGFR < 15) only addresses the RRT-consideration threshold. Real ADPKD trajectory modeling at this fidelity level usually models multiple endpoints simultaneously: eGFR < 30 for transplant referral, eGFR < 20 for active transplant evaluation, eGFR < 15 for RRT planning, and dialysis initiation as a separate event from RRT consideration (since the patient may decline dialysis or pursue preemptive transplant). The architecture as drawn supports a single endpoint; the recipe should articulate that real production systems typically model multiple endpoints, and the architecture should accommodate a list of endpoint definitions per disease rather than a single one. (See Finding H2.)
- **Right-censoring and informative loss-to-follow-up are mentioned but not first-class.** The Statistical Approaches section says joint models are "the right answer when the question is not just 'what is the trajectory' but 'given the trajectory, when does the patient hit a clinically meaningful endpoint?'" That is correct but soft-pedals a chapter-pattern failure mode: in chronic-disease cohorts, patients who progress faster are more likely to leave the cohort (transferred to nephrology specialty, hospitalized, deceased) and patients who feel well are more likely to stop coming for visits. Both directions of dropout produce informative censoring that biases the population-level prior estimation. The recipe says "they are robust to right-censoring (some patients drop out of follow-up for reasons that are both random and informative)" but does not make this a first-class concern. The architecture should specify a dropout-pattern monitor that compares the cohort's trajectory distribution at observation-window-cutoff to the trajectory distribution of patients who continue to be observed; large divergence is the operational signal of informative censoring. (See Finding M3.)
- **Cost estimate footnotes hide an open issue.** The cost line includes an inline TODO from the TechWriter about verifying HealthLake, SageMaker training, and SageMaker inference pricing assumptions. That is correct, but the cost range ($800-$3,500/month per disease-cohort workload) is wide and the dominant components (HealthLake at $200-$800, SageMaker training at $200-$600, SageMaker inference at $100-$400) all depend on cohort size and call volume. A reader sizing budget for two diseases would multiply this incorrectly. The recipe should specify "per disease-cohort workload" more clearly in the cost line and show how the numbers scale (or at least name the linear-vs-nonlinear scaling assumptions). (See Finding M4.)
- **The architecture as drawn assumes one disease cohort; the multi-disease case is implicit.** A real institution running this pattern will run multiple disease cohorts in parallel (CKD, ADPKD, IPF, multiple sclerosis, several oncology indications), each with its own cohort definition, model artifact, treatment-effect prior registry, and forecast cadence. The architecture diagram and Step Functions orchestration should specify the per-disease parallelism structure and the resource isolation model. The cost estimate's "per disease-cohort workload" framing implies this but it is not architecturally articulated. (See Finding M5.)

### Networking Expert Review

**Strengths.**

- VPC-endpoint enumeration is specific: S3, HealthLake, DynamoDB, KMS, Step Functions, CloudWatch Logs, and SageMaker API/Runtime. This matches the production-deployment pattern.
- TLS 1.2 minimum in transit is specified correctly.
- "Production posture for HIPAA workloads with PHI of this sensitivity" is named, which is the right register for this recipe given the genetic-and-longitudinal re-identifiability concerns.
- The architecture diagram shows the data flow clearly, including the trial-literature priors as an external input to the model-artifact bucket.

**Gaps.**

- **VPC endpoint list is incomplete.** EventBridge, Lambda, Glue, and Secrets Manager are not in the enumerated list. The recipe uses EventBridge for scheduling, Lambda for the counterfactual composer, Glue for ETL, and could plausibly use Secrets Manager for any external API credentials (clinical-trial-literature feed, EHR integration credentials, paging vendor credentials for clinician-facing alerts on prior-update events). The chapter-12 pattern through 12.7 has consistently called these out. (See Finding M6.)
- **Egress-control posture is implicit.** The recipe does not explicitly say "no NAT egress for PHI-touching workloads" or "restrictive egress on Lambda VPCs and SageMaker endpoint subnets." The chapter-12 pattern through 12.7 has named this. (See Finding L1.)
- **Time-synchronization posture is unstated.** Continuing the chapter-12 pattern from 12.5/12.7: the trajectory pipeline is time-keyed at sub-day fidelity in the harmonization layer. Clock skew between the EHR feed, the HealthLake datastore, the Glue ETL, the SageMaker training and inference, and the DynamoDB serving table corrupts the trajectory. NTP / Amazon Time Sync Service should be called out, along with the convention that observation timestamps are stored in UTC in the durable archive even when the clinical surface displays institution-local time. (See Finding L2.)
- **Multi-AZ posture is unstated.** This is a clinical-trajectory pipeline that produces forecasts informing transplant-evaluation timing, vascular-access planning, and tolvaptan trial enrollment decisions. The chapter-12 pattern (12.7 explicitly) requires a multi-AZ specification with a documented RTO/RPO. The recipe does not say it. (See Finding M7.)

### Voice Reviewer

**Strengths.**

- **Opening vignette earns its sentence.** The 54-year-old ADPKD patient with nine years of nephrology data, 41 eGFR results, 38 TKV measurements, the specific 4.2 mL/min/1.73 m^2/year decline rate, and the 6% annual TKV growth is concrete enough to anchor the reader. The "transplant evaluation timing, vascular access planning, and whether to enroll in a tolvaptan trial that might bend the curve" closing sentence converts the analytic problem into a clinical conversation. This is the chapter pattern done well.
- **Em-dash count is zero.** Verified by U+2014 codepoint scan. En-dashes (U+2013) appear only in numeric ranges, which is the chapter convention.
- **Voice is consistent with chapter 12.** The "math is the easy part" thesis appears for the third time in the chapter and is explicitly self-referenced ("you will notice this is becoming a theme in this chapter; it is not a coincidence"). The Honest Take's first-person opening ("the first time I built a disease progression trajectory model, I spent eight weeks on the model itself, two weeks on the data plumbing, and assumed I was eighty percent done; I was twenty percent done") matches the engineer-explaining-something-cool register that the chapter has established.
- **70/30 vendor balance is held.** The Problem, The Technology, the Counterfactual section, the General Architecture Pattern, the Why-This-Isn't-Production-Ready section, the Honest Take, the Variations, and the Related Recipes are all vendor-agnostic. The AWS-specific sections (Why These Services, Architecture Diagram, Prerequisites, Ingredients, Code walkthrough, Expected Results, Performance benchmarks) are concentrated and proportional. The walk-through pseudocode is vendor-agnostic.
- **No marketing-voice creep detected.** Phrases like "powerful," "seamless," "real-time" without latency numbers, "AI-powered," and "predictive intelligence" are absent.
- **Honest Take has five distinct observations.** Required pattern is at least four; this recipe lands five (the eighty-twenty initial estimate, the disagreement-management problem, the calibration footgun caught at two weeks, the cohort-definition discipline, the regulatory framing, and the trial-literature-prior approach being better than the academically-pure causal model). The fifth observation about the narrative being the product is the chapter-pattern signature paragraph and lands well.
- **The "This is not the same problem as 12.4" framing is good.** The recipe earns its place in the chapter by explicitly differentiating from the lab-trend recipe (change-detection on a horizon of months versus forecasting-and-counterfactual on a horizon of years). A reader who has finished 12.4 will not be confused.

**Gaps.**

- **One sentence in the opening vignette tilts toward documentation register.** "It is a conversation about transplant evaluation timing, vascular access planning, and whether to enroll in a tolvaptan trial that might bend the curve" is good. The next paragraph opens with "That conversation is not happening, and the reason it is not happening is not that her care team is bad. It is that the cognitive job of integrating a nine-year longitudinal trajectory across multiple variables..." which is correct in argument but reads slightly more like a policy paper than the chapter's signature engineer-at-the-whiteboard register. The point is real and worth making, but the prose could be tighter. (See Finding L3.)
- **The "Variations and Extensions" section's federated-learning paragraph is the most generic prose in the recipe.** It correctly names the engineering and regulatory complexity but does not earn a CC-voice paragraph; it reads more like a textbook bullet. The chapter pattern is for variations to retain voice consistency. Lower-priority concern but worth flagging for the editor. (See Finding L4.)

---

## Stage 2: Expert Discussion

The four experts converge on three priority concerns and one substantive disagreement.

**Convergence 1: The `apply_treatment_change` dedup gap is both a clinical-correctness and an architectural concern.** The Architecture expert flagged it as an architectural gap (the pseudocode communicates the wrong production posture). The Security expert agreed because a counterfactual that produces a 2x-overstated treatment benefit is a clinical-decision-support failure with regulatory exposure (a clinician acting on the overstated benefit is acting on a SaMD-grade output that misrepresents the published evidence). The Voice reviewer agreed because the Honest Take observation about "calibration is the easiest thing to get wrong and the easiest to fix once you notice" is undermined by a recipe where a similar failure mode lives in the pseudocode without comment. The Networking expert deferred to the others. Consensus: this is HIGH severity, not WARNING, because it affects the clinical-decision-support output integrity rather than just code hygiene. (Finding H1.)

**Convergence 2: The endpoint-definition architecture is monolithic where reality is plural.** The Architecture expert flagged this as a single-vs-multi-endpoint gap. The Security expert agreed because endpoint-specific access controls are common in real institutions (transplant referrals trigger specific EHR workflows that have their own authorization; dialysis initiation triggers payer-specific prior-auth flows). The Voice reviewer agreed because the opening vignette explicitly raises transplant evaluation as a separate concern from RRT initiation, and the recipe never picks up that thread architecturally. Consensus: HIGH severity, with the fix being to make `ENDPOINT_DEFINITION` a list rather than a singleton in the design and to articulate the per-endpoint use cases. (Finding H2.)

**Convergence 3: Informative censoring is the single biggest unmodeled risk.** The Architecture expert flagged it as a first-class data-quality concern. The Security expert noted that informative censoring particularly affects subgroup calibration (the Why-This-Isn't-Production-Ready section's equity-and-bias auditing item assumes representative cohort sampling, but informative censoring can quietly violate that assumption per-subgroup). The Voice reviewer agreed because the Honest Take could earn another observation about this and the recipe is short of one. Consensus: MEDIUM severity, surfaced in both the architecture and The Honest Take. (Finding M3.)

**Disagreement: How aggressively to push the multi-disease scaling concern.** The Architecture expert argued for HIGH severity because the cost estimate's "per disease-cohort workload" framing implies but does not articulate the parallel-disease structure. The Security expert argued for MEDIUM because cross-disease isolation (separate CMKs per disease cohort, separate IAM roles per pipeline) is implicit in "Customer-managed CMKs per data class" and an experienced reader will infer it. The Voice reviewer argued for LOW because the recipe is already long and adding a multi-disease section would dilute the chapter pattern. The Networking expert sided with the Architecture expert (multi-disease typically means multi-account or multi-VPC patterns at scale, which deserve a paragraph). Resolved at MEDIUM severity (Finding M5) with the recommendation that the recipe add a paragraph in the AWS Implementation section about per-disease isolation and parallel pipelines, but not require a full multi-disease architecture diagram.

There are no other inter-expert conflicts. The remaining findings are MEDIUM-or-LOW severity and the experts agreed on disposition.

---

## Stage 3: Synthesized Findings

### Finding H1. HIGH: Pseudocode `apply_treatment_change` does not handle pre-existing exposure to the requested drug class

- **Severity:** HIGH
- **Expert:** Architecture (primary), Security (secondary), Voice (tertiary)
- **Location:** Step 5 pseudocode, lines ~488-510 (the `evaluate_counterfactual_scenarios` function and its `apply_treatment_change` helper). The Python companion exhibits the same shape (per the code review's W1 finding).
- **Problem:** The pseudocode for the counterfactual-scenario evaluator describes the treatment-change application but does not specify what happens when the patient is already on the requested drug class. Both the pseudocode and the corresponding Python implementation blindly append the new "start drug X" entry, and the downstream `_treatment_modifier` (which iterates the entire timeline and compounds the trial-derived modifier) applies the modifier twice for the same drug class. For an SGLT2 example, this produces `(1 - 0.25) * (1 - 0.25) = 0.5625` instead of `0.75`, a 25% over-attribution of the SGLT2 effect. A clinician acting on a 25%-overstated SGLT2 benefit in a patient already on an SGLT2 is acting on a clinical-decision-support output that misrepresents the published trial evidence, which is a regulatory-grade failure mode for a SaMD-adjacent system.
- **Quote:** Step 5 pseudocode (line 491):
  ```
  // Apply the treatment change to the patient's projected treatment timeline.
  modified_treatment_timeline = apply_treatment_change(
      base_timeline = patient_harmonized_data.treatments,
      change        = scenario.change,
      anchor_time   = patient_harmonized_data.last_observation_months
  )
  ```
  The pseudocode does not show or describe the dedup logic.
- **Fix:** Either (a) add the dedup-and-reconciliation logic explicitly to the pseudocode in Step 5, or (b) add a short prose paragraph just before the pseudocode explaining that real production implementations of `apply_treatment_change` must reconcile pre-existing treatment with the requested change rather than blindly appending. Option (a) is the clearer teaching choice. Suggested pseudocode addition:
  ```
  FUNCTION apply_treatment_change(base_timeline, change, anchor_time):
      modified = copy(base_timeline)
      IF change.action == "add":
          drug_class = change.drug_class
          // Reconcile against pre-existing exposure. A patient already on
          // the requested class does not get a second modifier applied; the
          // counterfactual is a no-op for them and should be flagged so the
          // clinical surface can communicate "patient is already on this."
          already_active = any(
              tx.drug_class == drug_class
              AND tx.start_months_from_zero <= anchor_time
              AND (tx.end_months_from_zero is null
                   OR tx.end_months_from_zero >= anchor_time)
              FOR tx IN modified
          )
          IF NOT already_active:
              modified.append({
                  drug_class:             drug_class,
                  start_months_from_zero: anchor_time + change.start_offset_months,
                  end_months_from_zero:   null
              })
      // (similar reconciliation for swap and stop actions)
      RETURN modified
  ```
  The corresponding Python companion fix is W1 in the code review.

### Finding H2. HIGH: Endpoint definition is monolithic where real ADPKD trajectory modeling is plural

- **Severity:** HIGH
- **Expert:** Architecture (primary), Voice (secondary)
- **Location:** AWS Implementation section's pseudocode (Step 4 `infer_patient_trajectory` line ~440) and the Expected Results JSON example (line ~547-595).
- **Problem:** The opening vignette explicitly invokes a constellation of decision points: "transplant evaluation timing, vascular access planning, and whether to enroll in a tolvaptan trial." These are not the same endpoint. Transplant referral typically begins at eGFR < 30, active transplant evaluation at eGFR < 20, vascular-access planning at eGFR ~15-20, RRT-consideration at eGFR < 15, dialysis initiation as a separate event from RRT-consideration. Real production trajectory systems for ADPKD model these endpoints as a list, with separate hazard curves per endpoint. The recipe's pseudocode and JSON example articulate a single endpoint (eGFR < 15 for RRT consideration), which is too narrow for the clinical scope the opening vignette establishes. The architecture as drawn cannot answer the clinically central question "when should we begin transplant evaluation," which is arguably more clinically actionable than RRT timing because it has a longer planning horizon.
- **Quote:** Step 4 pseudocode comment (line ~440):
  ```
  // time_to_endpoint contains: P(endpoint by month T) curves with credible intervals,
  // median time to endpoint, P10 and P90 time to endpoint.
  ```
  And the JSON example (line ~574-583):
  ```
  "time_to_egfr_under_15": {
    "p10_months": 84,
    "p50_months": 126,
    "p90_months": 192
  }
  ```
  Single endpoint, single credible-interval triple.
- **Fix:** Two changes. First, in the Step 3 model-config block (line ~342-360), add a list-of-endpoints field:
  ```
  // endpoint_definitions:
  //   - { name: "transplant_referral",     loinc: "48642-3", threshold: 30, direction: "below" }
  //   - { name: "transplant_evaluation",   loinc: "48642-3", threshold: 20, direction: "below" }
  //   - { name: "rrt_consideration",       loinc: "48642-3", threshold: 15, direction: "below" }
  //   - { name: "vascular_access_planning",loinc: "48642-3", threshold: 18, direction: "below" }
  ```
  Second, in the Step 4 inference and the Step 5 counterfactual pseudocode, change `time_to_endpoint` to `times_to_endpoints` (or equivalent), iterate over the list, and produce one credible-interval triple per endpoint. Update the Expected Results JSON to show two or three endpoints in the example payload, demonstrating that the surfaced output gives the clinical team a constellation of timing curves rather than a single threshold-crossing prediction. The narrative explanation should also update accordingly to mention multiple decision points.

### Finding M1. MEDIUM: Imaging-and-genetics ingestion paths are mentioned but their security-and-consent posture is unstated

- **Severity:** MEDIUM
- **Expert:** Security (primary), Architecture (secondary)
- **Location:** Variations and Extensions section's "Disease-specific multimodal integration" paragraph (line ~660); Why-This-Isn't-Production-Ready section's "Multi-modal data integration" paragraph (line ~622).
- **Problem:** The recipe correctly identifies multimodal data (kidney-volume MRI for ADPKD, brain volumetrics for neurodegenerative diseases, tumor volumes for oncology, genetic markers like PKD1/PKD2/APOE) as an extension that materially improves trajectory forecasts. But the security framing is missing: imaging adds re-identifiability concerns specific to structural neuroimaging and (to a lesser extent) body imaging; genetic data is separately covered by GINA and state-level genetic-information-privacy regulations (California, Florida, others) on top of HIPAA. The BAA-and-consent layer for multimodal trajectory work is materially different from text-only EHR-driven work. A reader implementing the multimodal extension without recognizing this will produce a system that is technically correct and regulatorily exposed.
- **Fix:** Add one paragraph to the Variations section's multimodal item, or one paragraph to the Why-This-Isn't-Production-Ready multimodal item, naming GINA, the state-level genetic-information layers, and the consent-and-BAA framing differences. Suggested addition:
  > Multimodal extension also brings additional regulatory layers. Genetic data is covered by GINA at the federal level and by stricter state laws in California, Florida, and several others; institutional consent for genetic testing typically scopes data use narrowly (clinical care versus research versus prognostic modeling) and the trajectory pipeline must respect those scopes. Imaging-derived measurements are HIPAA PHI plus the structural-imaging re-identifiability concern that complicates de-identification. Production systems planning the multimodal extension should engage their privacy office, their genetic-counseling team, and their imaging-informatics team before the engineering work begins.

### Finding M2. MEDIUM: Counterfactual scenario invocation is not modeled as a privileged action surface

- **Severity:** MEDIUM
- **Expert:** Security (primary), Architecture (secondary)
- **Location:** AWS Implementation section's "AWS Lambda for counterfactual scenario evaluation" paragraph (line ~138); Step 5 pseudocode.
- **Problem:** The Lambda counterfactual composer takes a clinician-issued request ("what if we start tolvaptan in three months") and produces a clinical-decision-supporting output. This is functionally equivalent to ordering a clinical analytic test: it consumes patient PHI, runs a SaMD-adjacent computation, and returns a result that may inform a clinical decision. The recipe describes the technical flow but does not say the Lambda surface must authenticate the caller, authorize the action against the patient's consent posture, audit-log the request and response with sufficient fidelity to reconstruct what scenario was run for which patient by which clinician on what date, and apply rate limits to prevent runaway scenario sweeps that could constitute PHI mining.
- **Fix:** Add a paragraph to the AWS Implementation section's Lambda counterfactual-composer description naming authentication (Cognito or institutional IdP via API Gateway), authorization (the requesting clinician must have a clinical relationship to the patient, validated against the EHR's relationship-of-care store), audit logging (every counterfactual request and response stored with patient_id, clinician_id, scenario_spec, model_version, timestamp), and rate limiting (per-clinician, per-patient, per-day limits to prevent scenario-mining patterns).

### Finding M3. MEDIUM: Informative censoring and dropout-pattern monitoring are not first-class

- **Severity:** MEDIUM
- **Expert:** Architecture (primary), Security (secondary, equity angle), Voice (tertiary)
- **Location:** The Statistical Approaches section (line ~45 on joint models, line ~57 on irregular sampling); the "Where it struggles" list (line ~604); the Why-This-Isn't-Production-Ready section.
- **Problem:** Patients with worsening disease are more likely to leave the cohort (transferred to specialty, hospitalized, deceased), and patients who feel well are more likely to stop coming for visits. Both directions of dropout produce informative censoring that biases the population-level prior estimation. The recipe mentions right-censoring once ("they are robust to right-censoring (some patients drop out of follow-up for reasons that are both random and informative)") but does not promote this to a first-class operational concern. In practice this is the single biggest unmodeled risk in chronic-disease trajectory work and the architecture should specify a dropout-pattern monitor that compares the cohort's trajectory distribution at observation-window-cutoff to the trajectory distribution of patients who continue to be observed.
- **Fix:** Two changes. First, in the Why-This-Isn't-Production-Ready section, add a "Loss-to-follow-up monitoring" item:
  > **Loss-to-follow-up monitoring.** In chronic-disease cohorts, patients who progress fast are more likely to leave (transfer to specialty, hospitalize, decease), and patients who feel well are more likely to stop coming in. Both directions bias the population-level prior estimation. Production systems run a continuous loss-to-follow-up monitor that compares the trajectory distribution of patients who left the cohort recently to the trajectory distribution of patients who remain; persistent divergence is the operational signal of informative censoring and triggers a model-and-prior review. Without this, the cohort's apparent disease behavior drifts away from the true disease behavior in subtle, slow ways.
  Second, in The Honest Take, consider adding a sentence acknowledging this as the chapter-pattern observation about "the data the model sees is not the data the disease has."

### Finding M4. MEDIUM: Cost estimate framing risks misuse for multi-disease deployments

- **Severity:** MEDIUM
- **Expert:** Architecture (primary)
- **Location:** Prerequisites table, Cost Estimate row (line ~184).
- **Problem:** The cost line says "Total: ~$800-$3,500/month per disease-cohort workload depending on cohort size, data density, and model complexity." A reader sizing budget for two diseases will naively double; for ten diseases, multiply by ten. That is not how the cost actually scales, because HealthLake is a per-datastore fixed component plus per-resource variable, S3 is essentially free at the scale here, SageMaker training scales sub-linearly with cohort count if the institution uses on-demand training rather than always-on endpoints, and DynamoDB-and-Lambda scale linearly with read traffic but the read traffic per-disease is roughly proportional to cohort size. The recipe should articulate the scaling model.
- **Fix:** Replace the cost row's last sentence with:
  > Total: ~$800-$3,500/month per disease-cohort workload depending on cohort size, data density, and model complexity. Scaling: HealthLake storage and Glue ETL scale roughly linearly with cohort size; SageMaker training scales sub-linearly when on-demand training jobs are reused across diseases (one container, many training runs); SageMaker inference and Lambda-and-DynamoDB scale roughly linearly with active-patient count. A multi-disease deployment running five cohorts at the smaller end is closer to $2,500/month total than five times $800; one running five cohorts at the larger end is closer to $14,000/month total than five times $3,500. Engage AWS Solutions Architecture for a worked sizing exercise before committing to a multi-disease rollout.

### Finding M5. MEDIUM: Multi-disease parallelism is implicit in the cost estimate but unarticulated in the architecture

- **Severity:** MEDIUM
- **Expert:** Architecture (primary), Networking (secondary), Security (tertiary)
- **Location:** AWS Implementation section; Architecture Diagram.
- **Problem:** A real institution running this pattern runs multiple disease cohorts in parallel. Each cohort has its own definition, model artifact, treatment-effect prior registry, and forecast cadence. The architecture as drawn shows one pipeline; the per-disease parallelism, the per-disease isolation (separate CMKs per disease, separate IAM roles per pipeline, separate Step Functions executions per disease), and the cross-disease orchestration (a single EventBridge schedule fanning out to per-disease Step Functions executions, or per-disease EventBridge rules) are unstated.
- **Fix:** Add a paragraph to the AWS Implementation section, just before or just after the Architecture Diagram, addressing the multi-disease pattern. Suggested addition:
  > In production, this pipeline pattern runs once per disease cohort. Each disease has its own cohort-definition config, its own training Step Functions state machine, its own model-artifact prefix (with per-disease KMS CMKs), its own DynamoDB partition prefix, and its own EventBridge schedule. The Step Functions and SageMaker layers are reused across diseases (one trajectory-pipeline state machine template, parameterized by disease; one set of training-and-inference container images that read disease-specific configs at runtime). Per-disease isolation is implemented at the IAM role level (one role per disease-pipeline, scoped to the disease's CMKs and S3 prefixes) and at the audit-log level (every record carries the disease name as a top-level attribute). At the institutional scale (five to fifteen disease cohorts is typical for a large academic medical center), expect the pipeline to run five-to-fifteen Step Functions executions in parallel on a typical schedule, with per-disease independent failure recovery.

### Finding M6. MEDIUM: VPC endpoint enumeration is incomplete

- **Severity:** MEDIUM
- **Expert:** Networking (primary)
- **Location:** Prerequisites table, VPC row (line ~182).
- **Problem:** The VPC row says "VPC endpoints for S3, HealthLake, DynamoDB, KMS, Step Functions, CloudWatch Logs, and SageMaker API/Runtime." Missing: EventBridge, Lambda, Glue, and (if external API credentials are used) Secrets Manager. The chapter-12 pattern through 12.7 has called these out consistently.
- **Fix:** Update the VPC row to:
  > Production: SageMaker training, inference, and processing in private subnets with VPC endpoints for S3 (gateway), HealthLake (interface), DynamoDB (gateway), KMS (interface), Step Functions (interface), CloudWatch Logs (interface), CloudWatch Monitoring (interface), SageMaker API/Runtime (interface), EventBridge (interface), Lambda (interface), Glue (interface), and Secrets Manager (interface, for any external API credentials). Required posture for HIPAA workloads with PHI of this sensitivity. No NAT egress for PHI-touching workloads; restrictive egress on Lambda VPCs and SageMaker endpoint subnets.

### Finding M7. MEDIUM: Multi-AZ posture and RTO/RPO are unstated

- **Severity:** MEDIUM
- **Expert:** Networking (primary), Architecture (secondary)
- **Location:** Prerequisites table; AWS Implementation section.
- **Problem:** The chapter-12 pattern (12.7 explicitly) requires a multi-AZ specification with a documented RTO/RPO. The recipe does not say it. For a clinical-trajectory pipeline producing forecasts that inform transplant-evaluation timing and dialysis-vascular-access planning, this is a real availability concern.
- **Fix:** Add a row to the Prerequisites table:
  > | **Availability** | Multi-AZ deployment for SageMaker endpoints, DynamoDB (default), and any Lambda compute fronting clinician-facing surfaces. Documented RTO of 4 hours and RPO of 24 hours for the trajectory-inference pipeline (the surfaced trajectories are recomputed nightly; a one-day staleness during a regional incident is clinically tolerable since the underlying disease progression is on a multi-month-to-multi-year horizon). For the cohort-and-training pipeline, RTO of 24 hours and RPO of 7 days are tolerable since the training cadence is monthly. |

### Finding L1. LOW: Egress controls are not explicitly stated

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites table, VPC row.
- **Problem:** Continuing the chapter-12 pattern, the recipe should explicitly say "no NAT egress for PHI-touching workloads; restrictive egress on Lambda VPCs and SageMaker endpoint subnets."
- **Fix:** Already covered by Finding M6's recommended replacement text.

### Finding L2. LOW: Time-synchronization posture is unstated

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites table.
- **Problem:** The trajectory pipeline is time-keyed at sub-day fidelity in the harmonization layer; clock skew corrupts the trajectory. The chapter-12 pattern (12.5 and 12.7 specifically) names NTP / Amazon Time Sync Service.
- **Fix:** Add a row to the Prerequisites table:
  > | **Time** | Amazon Time Sync Service for AWS-hosted compute. Observation timestamps are stored in UTC in the durable archive (HealthLake and S3); the clinical surface displays institution-local time when shown to a clinician at the bedside. Time-zone handling is explicit in the harmonization layer. |

### Finding L3. LOW: One opening-paragraph sentence reads slightly more like policy paper than chapter voice

- **Severity:** LOW
- **Expert:** Voice
- **Location:** The Problem section, second paragraph (line ~11): "That conversation is not happening, and the reason it is not happening is not that her care team is bad. It is that the cognitive job of integrating a nine-year longitudinal trajectory across multiple variables, accounting for treatment effects, factoring in known disease-specific progression rates, and communicating future-state uncertainty in a way that is actionable, is not the cognitive job that an outpatient nephrology visit is structured to do."
- **Problem:** The sentence's structure ("the cognitive job of X, accounting for Y, factoring in Z, and communicating W, is not the cognitive job that an outpatient nephrology visit is structured to do") is correct in argument but slightly heavier than the chapter's signature engineer-at-the-whiteboard register. CC-voice is sharper at this length and would typically break this into two sentences with a more colloquial second sentence ("That is too many cognitive tasks for a 20-minute outpatient visit. The trajectory lives across visits and across a gap that the EHR was not designed to bridge.").
- **Fix:** Consider tightening to:
  > That conversation is not happening, and the reason is not that her care team is bad. The cognitive work it requires (integrating nine years of irregular measurements across multiple variables, accounting for treatment effects, factoring in disease-specific progression rates, communicating future-state uncertainty in a way that is actionable on a multi-year horizon) is not what a 20-minute outpatient nephrology visit is structured to do. Each visit is a snapshot. The trajectory lives across snapshots and across an analytic gap that the EHR was never designed to bridge.

### Finding L4. LOW: Federated-learning paragraph reads like a textbook bullet rather than CC voice

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Variations and Extensions section, "Federated learning across institutions" paragraph (line ~676).
- **Problem:** The paragraph correctly names the engineering complexity (secure aggregation, differential privacy, federated training infrastructure) and the regulatory complexity (cross-institutional BAA structure), but does not have the CC-voice that the rest of the recipe has. It reads more like a survey paper's future-work section than the chapter's engineer-explaining-something-cool register.
- **Fix:** Either rewrite for voice consistency or shorten to one sentence with a pointer. Suggested rewrite:
  > **Federated learning across institutions.** For rare diseases or for institutions whose cohort is too small to train a robust model alone, federated learning lets multiple institutions contribute to the same model without sharing patient data. The engineering work is real (secure aggregation, differential privacy, the federated training plane itself); the regulatory work is more real (cross-institutional BAA structure for federated learning is genuinely novel territory in 2026 and most legal teams will not have a template). For the right disease cohorts (rare pediatric, rare adult, certain orphan oncology indications) federated learning is the only credible path to a useful trajectory model. Plan on this being a multi-year, multi-institution effort, not an internal sprint.

### Verdict

**PASS** because there are 0 CRITICAL findings and 2 HIGH findings (under the FAIL threshold of >0 CRITICAL or >3 HIGH).

The H1 and H2 findings should be addressed by the TechEditor before publication. The MEDIUM findings improve production fidelity; the editor should fold them in if the timeline allows, otherwise they can be tracked as forward-publication TODOs against the existing inline TechWriter TODO discipline in the recipe (V1, N1, A1, R1, N3 are already in the file as visible TODOs). The LOW findings are polish.

Recommendation: ship after H1 and H2 are fixed; MEDIUM findings are nice-to-have on the same pass; LOW findings can wait for the chapter-wide pre-publication audit.

---

## Appendix: Cross-Recipe Consistency Checks

The recipe lands the chapter-12 pattern correctly on the following dimensions:

- **Em-dash discipline.** Zero U+2014 codepoints (verified). En-dashes appear only in numeric ranges, matching 12.1-12.7.
- **Vendor balance.** ~70% vendor-agnostic prose, ~30% AWS-specific. The Problem, The Technology, the Counterfactual section, the General Architecture Pattern, the Why-This-Isn't-Production-Ready section, the Honest Take, the Variations, and the Related Recipes are all vendor-neutral.
- **Cohort-stratified accuracy monitoring.** The Why-This-Isn't-Production-Ready section's "Equity and bias auditing" item names per-subgroup calibration evaluation (race, ethnicity, sex, age band, insurance type), which is the chapter-pattern requirement established in 12.4 and 12.5.
- **Calibration as first-class metric.** The Why-This-Isn't-Production-Ready section's "Calibration drift detection" item promotes calibration to operational-monitoring status, matching the chapter-pattern observation about "the calibration backtest is not optional, and it is not something to add later."
- **Honest Take with at least four observations.** The recipe lands five (the eighty-twenty initial estimate, disagreement-management, calibration-footgun, cohort-definition discipline, regulatory framing, narrative-as-product).
- **"Math is the easy part" thesis.** Lands for the third time in the chapter, explicitly self-referenced, which is the chapter-pattern signature paragraph.
- **Cross-recipe references.** Recipe 12.4 (Lab Result Trend Analysis), Recipe 12.7 (Vital Sign Trajectory Monitoring), Recipe 12.9 (Epidemic Forecasting), Recipe 6.x (Cohort Analysis), Recipe 7.x (Predictive Analytics), Recipe 4.10 (Dynamic Treatment Regime), Recipe 13.x (Knowledge Graphs) are all named with their relationship to this recipe explained.

The recipe is ready for the TechEditor pass after the H1 and H2 fixes.
