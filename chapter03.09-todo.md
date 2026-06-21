# Open TODOs: Recipe 3.9: Cybersecurity / Access Pattern Anomalies ⭐

> Auto-extracted 2026-06-18 from inline source comments (16 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter03.09-cybersecurity-access-pattern-anomalies.md`

- **L451** — TODO (TechWriter): verify the current state of NLRB guidance on workforce monitoring and any recent state-level employee privacy statutes (Illinois, California, New York have notable ones).
- **L453** — TODO (TechWriter): verify current state breach notification timelines; California specifically has tighter requirements than HIPAA.
- **L455** — TODO (TechWriter): cite specific OCR enforcement actions where inadequate audit controls were a contributing factor; the published settlements include several examples.
- **L539** — TODO (TechWriter): verify the current state-of-the-art for GNN-based insider threat or healthcare access anomaly detection; the literature is evolving.
- **L545** — TODO (TechWriter): verify specific published work on LLM-assisted patient-privacy-monitoring triage; the use case is emerging and the literature is sparse.
- **L585** — TODO (TechWriter): note that specific union and labor-law considerations vary substantially; this is meant as a flag, not a comprehensive treatment.
- **L739** — TODO (TechWriter): verify recent OCR settlement amounts; published examples include settlements in the multi-million-dollar range, with specific figures available in OCR's resolution-agreement archive.

## architecture — `chapter03.09-architecture.md`

- **L17** — TODO (TechWriter): verify current HIPAA eligibility status of Amazon Neptune.
- **L19** — TODO (TechWriter): verify the current HIPAA eligibility status of Amazon Timestream and BAA coverage; some deployments use S3 with Athena instead.
- **L27** — TODO (TechWriter): confirm the current set of HIPAA-eligible Bedrock foundation models.
- **L153** — TODO (TechWriter): verify recent OCR settlement ranges; the settlements are public and the figures are well-documented.
- **L207** — TODO (TechWriter): verify and add specific aws-samples or aws-solutions-library-samples repositories demonstrating insider-threat detection, EHR audit-log analysis, healthcare patient-privacy monitoring, or UEBA on AWS. Adjacent examples exist in the security domain; a direct healthcare match has not been confirmed at the time of writing.
- **L923** — TODO (TechWriter): benchmark ranges are directional from typical patient-privacy-monitoring program performance. Specific figures vary substantially by health system size, EHR vendor, workforce composition, base rate of policy violations, and privacy office staffing. The published academic literature on healthcare insider threat detection is sparse compared with the operational literature; vendor-published metrics from Protenus, Imprivata FairWarning, and similar products provide additional reference points. Replace with measured numbers from local validation.
- **L1041** — TODO (TechWriter): verify and add specific aws-samples or aws-solutions-library-samples repositories demonstrating insider-threat detection, EHR audit-log analysis, healthcare patient-privacy monitoring, or UEBA on AWS. Adjacent examples exist in the security domain; a direct healthcare-specific match has not been confirmed at the time of writing.
- **L1048** — TODO (TechWriter): verify and add specific AWS blog posts on healthcare audit-log analysis, patient-privacy monitoring, or UEBA on AWS; confirm URLs exist before inclusion.
- **L1066** — TODO (TechWriter): Add specific peer-reviewed citations for:
  - UEBA methodologies in healthcare: published comparison studies of UEBA approaches.
  - Insider threat detection: CERT National Insider Threat Center publications.
  - Graph-based anomaly detection: Akoglu, Tong, Koutra (2015) "Graph based anomaly detection and description: a survey".
  - Patient-privacy monitoring: published case studies from Protenus, Imprivata FairWarning, and academic medical center programs.
  - LLM-assisted security triage: emerging in 2024-2026; verify and cite as the literature stabilizes.
  Verify exact citations and DOIs before publication.
