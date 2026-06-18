# Open TODOs — Recipe 13.5: Clinical Pathway / Protocol Modeling

> Auto-extracted 2026-06-18 from inline source comments (3 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter13.05-architecture.md`

- **L65** — TODO (TechWriter): Expert review S2 (HIGH). DynamoDB patient-pathway-state table has no item-level access control. For HIPAA Minimum Necessary, consider IAM leading-key conditions (dynamodb:LeadingKeys with department tags) or application-layer enforcement so that Lambdas processing one department cannot access another department's patient records. Document the chosen approach in the Prerequisites or a security callout.
- **L453** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add a section covering gaps a production deployment must close (e.g., HL7/FHIR integration testing, pathway authoring UI, clinical committee governance workflow).
- **L481** — TODO (TechWriter): Verify if there are additional healthcare-specific Neptune samples available on aws-samples.
