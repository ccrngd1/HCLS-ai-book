# Open TODOs — Recipe 3.4: Medication Dispensing Anomalies ⭐

> Auto-extracted 2026-06-18 from inline source comments (10 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter03.04-medication-dispensing-anomalies.md`

- **L167** — TODO (TechWriter): once HIPAA-eligible clinical LLM deployments become standard in hospital settings, this section should be expanded with specific patterns. Current state is that several vendors are piloting, no clear production-standard pattern has emerged.
- **L177** — TODO (TechWriter): look up specific published studies on pharmacy alert override rates. Possible sources: the literature around CPOE implementation studies, AHRQ patient safety reports, JAMIA publications on clinical decision support override rates. Don't fabricate specific numbers; cite real studies or keep the claim directional.

## architecture — `chapter03.04-architecture.md`

- **L39** — TODO (TechWriter): as HIPAA-eligible Bedrock patterns mature in healthcare in 2026, add a specific reference to validated clinical-reasoning triage architectures. Avoid speculative specifics for now.
- **L115** — TODO (TechWriter): confirm current published ADE cost estimates. AHRQ, ISMP, and IHI have published numbers over the years that need to be checked for current accuracy before citing specifics.
- **L155** — TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repo that demonstrates medication safety or clinical decision support analytics. A direct match has not been confirmed at the time of writing.
- **L824** — TODO (TechWriter): these benchmark ranges are directional from typical pharmacy-safety project experience. Replace with measured numbers once the pipeline runs for a few cycles. Consider referencing published studies on CDSS alert override rates; they consistently show rates in the 80-95% range for unfiltered pharmacy alerts which is the source of the "alert fatigue" framing.
- **L871** — TODO (TechWriter): consider adding a note about FDA 510(k) and De Novo pathways for clinical decision support software, as some dispensing anomaly detectors may cross into regulated device territory depending on how outputs are used. The FDA's 2022 CDS guidance document is the relevant reference.
- **L887** — TODO (TechWriter): once specific validated patterns for LLM-assisted clinical triage are published in the healthcare literature with demonstrated safety data, expand this section with concrete references. As of this writing, pilots exist but broadly-accepted production patterns do not.
- **L916** — TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repo that demonstrates an end-to-end medication safety or clinical decision support pipeline. A direct match has not been confirmed at the time of writing.
- **L922** — TODO (TechWriter): verify and add two or three specific AWS blog posts on clinical decision support, medication safety analytics, or pharmacy operations on AWS; confirm URLs exist before inclusion.
