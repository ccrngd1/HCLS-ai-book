# Open TODOs — Recipe 4.9: Personalized Care Plan Generation ⭐⭐⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (25 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter04.09-personalized-care-plan-generation.md`

- **L338** — TODO: confirm current FDA Clinical Decision Support guidance and the 21st Century Cures Act exemption criteria; the regulatory landscape is evolving and the analysis is fact-specific.

## architecture — `chapter04.09-architecture.md`

- **L15** — TODO: confirm AWS HealthLake's current pricing, HIPAA eligibility, and FHIR specification version support.
- **L29** — TODO: confirm current Bedrock service terms, the eligible-model list, and the data-handling guarantees at the time of build.
- **L41** — TODO: confirm Pinpoint HIPAA-eligible channel list at the time of build.
- **L164** — TODO: pair these actions with one or two scoped Resource ARN examples. Same chapter-wide pattern flagged in 4.1 through 4.8.
- **L165** — TODO: confirm Bedrock + selected models, HealthLake, Pinpoint channel eligibility, and any EHR-integration components at the time of build.
- **L171** — TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- **L205** — TODO: confirm the current names and locations of the aws-samples repos.
- **L1282** — TODO: the benchmarks above are illustrative; replace with measured results from your deployment. Be wary of vendor-published claims about "AI-generated care plans"; the headline metric (plans generated per minute) is the wrong metric, and the substantive metrics (reconciliation quality, cohort fairness, plan adherence over time) are rarely reported.
- **L1289** — TODO (TechWriter): Expert review A4 (HIGH). Architect this as a first-class component (asynchronous status pipeline, per-integration success-rate dashboards) rather than leaving it as a struggle bullet.
- **L1305** — TODO (TechWriter): Expert review A9 (MEDIUM). Specify clinical-content version transitions in the architecture: how plan_input_record freezes effective template versions at generation time; how plan revision distinguishes patient-state changes from template-content changes via per-element diff; how retired templates are handled for active plans; how parallel evaluation runs (shadow Step Functions pipeline against held-out cohort, diff surface for committee review). Also flagged: A11 (MEDIUM) on the coordinated promotion path for 50-200 goal templates and 200-1000 action templates with cohort overrides; the scale here is materially larger than 4.4-4.8.
- **L1311** — TODO (TechWriter): document the four-layer validator pattern in a shared specification used across 4.5 through 4.9. The patterns rhyme but are not identical (the patient-facing layer in 4.9 has reading-level enforcement that 4.7 does not; the recommendation-language layer in 4.8 is stricter than in 4.9). Consolidate the chapter-level validator pattern with cross-recipe references.
- **L1317** — TODO (TechWriter): specify the channel-credential posture: portal API credentials in Secrets Manager with rotation, mailing-vendor SFTP keys with rotation, SMS short-code provisioning, language-specific template approval. Reference the channel-integration patterns from 4.1 and 4.2.
- **L1321** — TODO (TechWriter): specify the consent-data-flow pattern: explicit consent capture, consent versioning, consent-revocation handling, audit-trail of consent state at the time of plan generation. Mirror the language from 4.5 through 4.8 where applicable.
- **L1323** — TODO: confirm current FDA Clinical Decision Support guidance, the Cures Act CDS exemption criteria, and applicable state-level care-management regulations at the time of build.
- **L1327** — TODO (TechWriter): specify the trigger-calibration pattern. Per-trigger sensitivity (acute hospitalization always triggers; weight gain only triggers if exceeds threshold and persists; new medication only triggers if class is in the watch list); per-cohort tuning (older patients have more sensitive triggers because the underlying instability is higher); review the trigger rates at the cohort level monthly.
- **L1333** — TODO (TechWriter): replace the string-concatenation plan_id, narrative_id, plan_action_record_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plan-version-and-patient-id-in-identifier patterns are PHI leakage in URLs, logs, and event payloads. Mirror the language flagged in 4.4 through 4.8.
- **L1337** — TODO (TechWriter): specify DLQ coverage on all Lambda paths: Step Functions task failures route to a per-stage SQS DLQ keyed on (plan_id, stage); Kinesis to state-machine-worker Lambda configures an OnFailure destination; narrative-generation Bedrock failures route to a degraded-state response that returns a templated narrative rather than a partial or empty plan. The plan finalization path must fail loudly and produce no plan rather than a partial plan. Mirror 4.4 through 4.8.
- **L1345** — TODO (TechWriter): Expert review A10 (MEDIUM). Multi-language is broader than a variation framing suggests because non-English-preferring cohorts are exactly the cohorts the equity instrumentation should be most sensitive to. Promote the per-language validator dispatch (Flesch-Huerta-Macuso for Spanish, INFLESZ for Spanish-medical, syllable algorithms per language), the per-language catalog of prohibited-language patterns and required-content templates, and the per-language templated fallback into a first-class architectural concern with cross-references to Recipe 4.2 reading-level pattern and Recipe 4.1 language-as-channel-attribute pattern.
- **L1389** — TODO: confirm the current names and locations of the aws-samples repos; they have been reorganizing.
- **L1396** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- **L1404** — TODO: confirm reference at the time of build; the original paper is from 2009 with subsequent literature extending the framework.
- **L1405** — TODO: confirm reference at the time of build; the criteria have been updated in subsequent versions.
- **L1410** — TODO: confirm the current FDA SaMD framework documents at the time of build.
- **L1411** — TODO: confirm the current FDA CDS guidance and the 21st Century Cures Act exemption criteria at the time of build.
