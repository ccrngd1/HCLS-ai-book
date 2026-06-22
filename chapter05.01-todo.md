# Open TODOs: Recipe 5.1: Internal Duplicate Patient Detection ⭐

> Remaining items after resolution pass 2026-06-21. Items prefixed with `[NEEDS HUMAN]` require external verification or a product decision that cannot be made by the TechWriter alone.

## main — `chapter05.01-internal-duplicate-patient-detection.md`

- [NEEDS HUMAN] **L15** — Verify the most recent Joint Commission National Patient Safety Goals and ECRI Top 10 Patient Safety Concerns reports at time of build; the patient identification theme has been consistent but specific years and rankings shift. Reason: requires checking current-year publications.
- [NEEDS HUMAN] **L17** — Verify duplicate rate ranges (5-15% within-system, 20-30% poorly-maintained); commonly-cited figures from ONC, AHIMA, and EMPI vendor literature. Reason: requires verifying current literature at time of publication.
- [NEEDS HUMAN] **L114** — Confirm current state of Splink, dedupe.io, recordlinkage, and Zingg libraries at time of build. Reason: requires checking current maintenance status of each library.

## architecture — `chapter05.01-architecture.md`

- [NEEDS HUMAN] **L15** — Confirm Splink's current Glue/Spark compatibility and recommended integration pattern at time of build. Reason: requires verifying current library version compatibility with AWS Glue runtime.
- [NEEDS HUMAN] **L25** — Confirm whether the institution has an existing review tool to integrate with (Verato, NextGate, IBM Initiate, Epic MPI, or homegrown). Reason: product decision for the implementing team.
- [NEEDS HUMAN] **L118** — Pair IAM permissions with scoped Resource ARN examples. Reason: requires deployment-specific account IDs and resource names.
- [NEEDS HUMAN] **L124** — Verify staffing ratios (0.25-1.0 FTE per 100K active patients). Reason: requires confirming against current AHIMA practice guidance.
- [NEEDS HUMAN] **L126** — Replace cost estimates with verified pricing from AWS Pricing Calculator. Reason: requires current pricing validation at time of publication.
- [NEEDS HUMAN] **L156** — Confirm Splink's current Glue/Spark integration pattern and dedupe library's current state. Reason: duplicate of L15; same verification needed.
- [NEEDS HUMAN] **L757** — Replace illustrative figures in Expected Results with measured deployment results. Reason: requires actual deployment data; vendor-published claims need independent validation.
- [NEEDS HUMAN] **L847** — Confirm current names and locations of aws-samples repos for entity resolution. Reason: AWS has been reorganizing repos; requires checking GitHub at time of build.
- [NEEDS HUMAN] **L853** — Replace generic blog pointers with two or three specific, verified blog post URLs. Reason: requires confirming specific URLs exist and are stable.
- [NEEDS HUMAN] **L856** — Confirm stable accessible link to Fellegi-Sunter 1969 paper. Reason: academic mirrors change; current link needs verification.
- [NEEDS HUMAN] **L862** — Confirm current ONC reports on patient matching. Reason: requires checking current-year publications.
- [NEEDS HUMAN] **L865** — Confirm current Pew patient matching reports. Reason: requires checking current publications.
- [NEEDS HUMAN] **L866** — Confirm most recent ECRI Top 10 report. Reason: requires checking current-year publication.
- [NEEDS HUMAN] **L870** — Confirm specific RAND patient-matching publications. Reason: requires checking current publications.
