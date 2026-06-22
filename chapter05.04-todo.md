# Open TODOs: Recipe 5.4: Insurance Eligibility Matching ⭐⭐⭐

> Remaining items after expert-review and code-review resolution pass (2026-06-21).

## main - `chapter05.04-insurance-eligibility-matching.md`

- [NEEDS HUMAN] **L17** - Cannot verify externally: CAQH CORE and industry literature consistently report 5-15% of real-time eligibility verifications return "member not found" or "coverage indeterminate." Confirm this range against current CAQH Index data at time of publication.
- [NEEDS HUMAN] **L29** - Confirm at time of build: X12 270/271 as HIPAA-mandated standards and CAQH CORE operating rules. Well-established but verify no regulatory changes since draft.
- [NEEDS HUMAN] **L49** - Confirm at time of build: CAQH CORE Phase II response-time SLAs (20-second worst-case for 271). Verify against current published operating rules.
- [NEEDS HUMAN] **L75** - Confirm at time of build: current X12 version is 5010; verify no mandated version transition has taken effect.
- [NEEDS HUMAN] **L83** - Confirm at time of build: CAQH CORE operating rules on required demographic fields for search match. Verify against current published rules.
- [NEEDS HUMAN] **L87** - Confirm at time of build: CAQH CORE Phase I-IV operating rule layering. Verify against current published phases.
- [NEEDS HUMAN] **L97** - Confirm at time of build: member-ID stability practices by payer type. This is institutional knowledge; verify with current payer landscape.
- [NEEDS HUMAN] **L109** - Confirm at time of build: Da Vinci CRD, DTR, PAS implementation guides and CMS rules on FHIR-based APIs. Verify current status of these specifications.
- [NEEDS HUMAN] **L115** - Cannot verify externally: ONC, Pew, and equity-focused research on disparate impact of patient-matching errors. Confirm specific citations exist at time of publication.
- [NEEDS HUMAN] **L117** - Confirm at time of build: NSA implementing rules and enforcement guidance continue to evolve. Verify current regulatory status.
- [NEEDS HUMAN] **L119** - Confirm at time of build: academic literature on privacy-preserving record linkage for eligibility. Verify citations exist.
- [NEEDS HUMAN] **L336** - Confirm at time of build: NSA implementing rules and price-transparency rules status. Same as L117.

## architecture - `chapter05.04-architecture.md`

- [NEEDS HUMAN] **L15** - Confirm at time of build: ElastiCache HIPAA eligibility and encryption-at-rest configuration. Verify against current AWS HIPAA eligible services list.
- [NEEDS HUMAN] **L21** - Confirm at time of build: clearinghouse and payer PrivateLink availability. This is evolving and institution-specific.
- [NEEDS HUMAN] **L135** - Confirm at time of build: clearinghouse landscape and FHIR-based eligibility connectivity options. Market is evolving.
- [NEEDS HUMAN] **L142** - Confirm at time of build: Synthea capabilities and CAQH CORE certification test data availability.
- [NEEDS HUMAN] **L143** - Replace with verified, current pricing once the implementing team validates against partner quotes and the AWS Pricing Calculator.
- [NEEDS HUMAN] **L171** - Confirm at time of build: clearinghouse SDK availability (corporate ownership changes affect availability).
- [NEEDS HUMAN] **L172** - Confirm at time of build: pyx12 and bots maintenance status.
- [NEEDS HUMAN] **L175** - Confirm at time of build: CAQH CORE Operating Rules URL is current.
- [NEEDS HUMAN] **L909** - Replace illustrative performance figures with measured results from deployment. Current figures are typical ranges from CAQH CORE benchmarks and industry literature.
- [NEEDS HUMAN] **L1010** - Confirm at time of build: aws-samples repo names and locations (organizations reorganizing).
- [NEEDS HUMAN] **L1015** - Replace generic "search the blog" pointers with specific, verified blog post URLs once confirmed to exist.
- [NEEDS HUMAN] **L1018** - Confirm current URL at time of build (CMS Interoperability rule).
- [NEEDS HUMAN] **L1019** - Confirm current URL at time of build (HIPAA Administrative Simplification).
- [NEEDS HUMAN] **L1023** - Confirm current URL at time of build (CAQH Index Reports).
- [NEEDS HUMAN] **L1024** - Confirm current URL at time of build (HFMA).
- [NEEDS HUMAN] **L1038** - Confirm current URL at time of build (Additional Resources section).
