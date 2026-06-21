# Open TODOs: Recipe 3.10: Epidemic / Outbreak Detection ⭐

> Auto-extracted 2026-06-18 from inline source comments (15 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter03.10-epidemic-outbreak-detection.md`

- **L553** — TODO (TechWriter): verify the current staffing ranges for state and local health department communicable disease units; the CDC and CSTE publish surveys periodically.
- **L571** — TODO (TechWriter): verify the current state of HIPAA's public health exception and any recent OCR guidance on its scope; the rule is in 45 CFR 164.512(b).
- **L575** — TODO (TechWriter): verify the current state of cross-jurisdictional coordination practices; CSTE publishes guidance on this.
- **L671** — TODO (TechWriter): the `bsts` package (Bayesian Structural Time Series by Steven L. Scott) uses a custom MCMC sampler implemented in C++ and is not Stan-based; only `brms` is Stan-based. Either drop "Stan-based" from the qualifier or restate the relationship, for example: "MCMC-based R packages including `bsts` and `brms` (the latter Stan-based with appropriate priors)."
- **L875** — TODO (TechWriter): verify recent CDC cost-of-outbreak studies and BARDA-published preparedness ROI estimates for the financial framing here.

## architecture — `chapter03.10-architecture.md`

- **L21** — TODO (TechWriter): verify the current HIPAA eligibility status of Amazon Timestream and BAA coverage; some deployments use S3 with Athena instead.
- **L27** — TODO (TechWriter): verify current HIPAA eligibility status of Amazon Neptune.
- **L35** — TODO (TechWriter): confirm the current set of HIPAA-eligible Bedrock foundation models.
- **L155** — TODO (TechWriter): cost ranges are directional from typical state-level surveillance program budgets; specific figures vary by population covered, source-feed count, retention requirements, and program scope.
- **L1013** — TODO (TechWriter): benchmark ranges are directional from typical state-level surveillance program performance. Specific figures vary substantially by jurisdiction size, source-feed coverage, syndrome mix, baseline data quality, and surveillance team staffing. Published academic literature on syndromic surveillance performance (Buehler et al., the ESSENCE evaluation literature, the BARDA-funded benchmarking studies) provides reference points; replace with measured numbers from local validation.
- **L1091** — TODO (TechWriter): verify the current operational status of major wearable-surveillance research programs and any production-grade integrations.
- **L1147** — TODO (TechWriter): verify and add specific aws-samples or aws-solutions-library-samples repositories demonstrating syndromic surveillance, public health surveillance, NSSP integration, eCR integration, or wastewater surveillance on AWS. Direct healthcare-public-health-specific matches may be limited; adjacent FHIR and analytics examples are likely.
- **L1154** — TODO (TechWriter): verify and add specific AWS blog posts on public health surveillance, syndromic surveillance, FHIR-based public health integration, or NSSP-aligned architectures on AWS; confirm URLs exist before inclusion.
- **L1183** — TODO (TechWriter): "SaNDS" does not appear to be a standard CDC acronym for the resource at this URL. The linked page is CDC's "Surveillance Message Mapping Guides" (MMGs); the canonical resource name for CDC's NNDSS surveillance message-structure standards is "Message Mapping Guide" or "MMG." Either replace the label with "CDC NNDSS Message Mapping Guides" to match the actual resource name, or verify that "SaNDS" is the intended acronym and that the URL points to the correct page.
- **L1186** — TODO (TechWriter): Add specific peer-reviewed citations for:
  - Farrington algorithm: Farrington, Andrews, Beale, Catchpole (1996) "A statistical algorithm for the early detection of outbreaks of infectious disease." Journal of the Royal Statistical Society: Series A.
  - Farrington Flexible: Noufaily, Enki, Farrington, Garthwaite, Andrews, Charlett (2013) "An improved algorithm for outbreak detection in multiple surveillance systems." Statistics in Medicine.
  - Spatial scan statistic: Kulldorff (1997) "A spatial scan statistic." Communications in Statistics - Theory and Methods.
  - Space-time permutation scan: Kulldorff, Heffernan, Hartman, Assunção, Mostashari (2005) "A space-time permutation scan statistic for disease outbreak detection." PLoS Medicine.
  - ESSENCE evaluation: Buehler et al. publications and the JHUAPL technical literature.
  - Wastewater surveillance: Wu et al., Bibby et al., Larsen and Wigginton publications on wastewater-based epidemiology.
  - Genomic surveillance: PulseNet methodology papers; Nextstrain methodology and reference papers.
  Verify exact citations and DOIs before publication.
