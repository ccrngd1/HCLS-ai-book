# Open TODOs: Recipe 11.9: Care Coordination Assistant

> Remaining items after the TechWriter resolution pass (2026-06-22). Items marked [NEEDS HUMAN] require author or institutional decision.

## architecture: `chapter11.09-architecture.md`

- [NEEDS HUMAN] **L355**: Replace with verified pricing once the implementing team validates against the AWS Pricing Calculator; specific costs depend on Bedrock model choice, conversation volume, ingestion volume across HL7/FHIR/claims/pharmacy/HIE, FHIR-source choice, escalation rate, and channel mix. The current estimate ($2.3M-7.0M/year at 50K members) is illustrative and should be validated against current Bedrock pricing at build time.
- [NEEDS HUMAN] **L1703**: Replace illustrative performance-benchmark figures with measured results from the deployment once available. The ranges in the table are typical for hybrid AI-plus-human coordination programs but vary substantially with program design, target population, integration coverage, and engagement intensity.
- [NEEDS HUMAN] **L1860**: Confirm current AWS sample repo names and locations at time of build; the AWS sample repo organization changes over time. The three repos listed (`amazon-bedrock-samples`, `aws-genai-llm-chatbot`, `aws-healthcare-lifescience-ai-ml-sample-notebooks`) were valid at drafting but should be re-verified.
- [NEEDS HUMAN] **L1866**: Replace generic search-the-blog pointers in the AWS Solutions and Blogs section with specific verified blog post URLs once they are confirmed to exist. Current text points readers to search terms rather than specific posts because blog content changes frequently.
