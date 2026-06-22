# Open TODOs: Recipe 11.1: FAQ Chatbot

## main - `chapter11.01-faq-chatbot.md`

- [NEEDS HUMAN] **L17** - Verify healthcare contact-center volume figures. Industry surveys from HIMSS, Press Ganey, and similar organizations publish these; specific numbers vary widely by health-system size and methodology. Author should pick a defensible source or soften the claim.
- [NEEDS HUMAN] **L167** - Verify the timing claim about healthcare conversational AI vendor landscape growth/consolidation. The approximate date and vendor references need a citable source or should be generalized.

## architecture - `chapter11.01-architecture.md`

- [NEEDS HUMAN] **L152** - Verify validation-set sourcing options. Commercial conversational-AI vendors typically have proprietary benchmarks; open patient-utterance datasets remain limited. Author should confirm current sources at build time.
- [NEEDS HUMAN] **L154** - Verify the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA; these evolve. Confirm at build time against the AWS HIPAA Eligible Services Reference page.
- [NEEDS HUMAN] **L159** - Replace with verified pricing once the implementing team validates against the AWS Pricing Calculator. Specific costs depend on the chosen Bedrock model, the corpus size, the conversation turn count, and the chosen vector store.
- [NEEDS HUMAN] **L951** - Replace illustrative figures in the Expected Results table with measured results from deployment. The ranges are typical for healthcare FAQ chatbot deployments but vary with corpus quality, scope mix, and patient demographics.
- [NEEDS HUMAN] **L988** - Verify that WCAG 2.1 AA and WAI-ARIA Authoring Practices are the correct current standards for chat surfaces in regulated/government-aligned contexts; institutional standards may have evolved.
- [NEEDS HUMAN] **L1002** - Verify the nuance around HIPAA patient rights: the Privacy Rule grants access rights; the right to delete is more limited and governed by a combination of HIPAA, state law, and (where applicable) state-specific consumer privacy laws. Author should confirm the legal framing with compliance counsel.
- [NEEDS HUMAN] **L1056** - Confirm current repo name and location at time of build.
- [NEEDS HUMAN] **L1060** - Confirm current repo names and locations at time of build; the AWS sample repo organization changes over time.
- [NEEDS HUMAN] **L1067** - Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once confirmed to exist.
- [NEEDS HUMAN] **L1079** - Confirm specific URL at time of build.
- [NEEDS HUMAN] **L1080** - Confirm current URL at time of build.
