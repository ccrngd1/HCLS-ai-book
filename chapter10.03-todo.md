# Open TODOs: Recipe 10.3: Voice-to-Text for EHR Navigation ⭐

> Items remaining after the findings-resolution pass. Items marked `[NEEDS HUMAN]` require external verification, a product decision, or a URL check that cannot be performed programmatically.

## main — `chapter10.03-voice-to-text-ehr-navigation.md`

- [NEEDS HUMAN] **L17** — Cannot verify externally: the time-on-EHR-during-patient-encounters versus time-with-patient ratio has been studied extensively, with multiple studies finding roughly half or more of clinical-encounter time on EHR navigation; specific figures vary by specialty and study. Confirm a specific citation or soften to "roughly half" without attribution.
- [NEEDS HUMAN] **L69** — Cannot verify specific user-study numbers for conversational-interface latency thresholds. Confirm a citation or use "research consistently finds that response times above a couple of seconds feel sluggish" without a specific number.
- [NEEDS HUMAN] **L123** — Cannot verify specific FHIR-API capabilities by EHR vendor at time of build. FHIR R4 and SMART on FHIR are widely supported but write-operation coverage varies. Confirm current vendor landscape at publication time.
- [NEEDS HUMAN] **L125** — Cannot verify current SMART on FHIR feature coverage breadth at publication time.
- [NEEDS HUMAN] **L127** — Cannot verify current vendor program names (Epic App Orchard/Showroom, Cerner Code Console). Names and structures change. Confirm at publication time.
- [NEEDS HUMAN] **L155** — Cannot verify cloud-streaming ASR vs on-device performance claims at publication time. Confirm or soften.
- [NEEDS HUMAN] **L159** — Cannot verify FHIR R4/R5 write-side coverage status at publication time.
- [NEEDS HUMAN] **L161** — Cannot verify voice-product category fragmentation characterization at publication time.
- [NEEDS HUMAN] **L400** — Cannot verify Transcribe Medical vs general-purpose Transcribe relative accuracy at publication time.
- [NEEDS HUMAN] **L404** — Cannot verify SMART on FHIR write-side coverage and launch-context patterns at publication time.

## architecture — `chapter10.03-architecture.md`

- [NEEDS HUMAN] **L11** — Cannot verify Transcribe Medical streaming trade-off characterization at publication time.
- [NEEDS HUMAN] **L157a** — Cannot verify the AWS HIPAA-eligible services list completeness and specific Bedrock models under BAA at publication time. Confirm against the AWS HIPAA Eligible Services Reference page at build time.
- [NEEDS HUMAN] **L162** — Replace illustrative cost estimate with verified pricing once the implementing team validates against the AWS Pricing Calculator. Specific costs depend on per-minute Transcribe streaming pricing in the chosen region and the chosen NLU stack.
- [NEEDS HUMAN] **L833** — Replace illustrative performance benchmarks with measured results from a real deployment. The ranges above are typical for voice-navigation deployments in healthcare but vary substantially with clinical environment, EHR vendor, and clinician training.
- [NEEDS HUMAN] **L944** — Confirm the current names and locations of the AWS sample repos at time of build; the AWS sample repo organization changes over time.
- [NEEDS HUMAN] **L950** — Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- [NEEDS HUMAN] **L956** — Verify the dominant FHIR version characterization at publication time; FHIR R4 vs R5 adoption varies by vendor.
- [NEEDS HUMAN] **L959** — Confirm the current URL for the SMART App Launch Framework specification at time of build.
- [NEEDS HUMAN] **L963** — Confirm the specific URL for the 21st Century Cures Act / ONC Information Blocking Rules at time of build.
- [NEEDS HUMAN] **L964** — Confirm the current URL for the CDS Hooks specification at time of build.
