# Edit Status: Recipe 14.10 - Health System Network Design

## Changes Applied

### From Expert Review

| Finding | Severity | Action |
|---------|----------|--------|
| SEC-1 (QuickSight IAM) | MEDIUM | **Fixed.** Replaced `quicksight:*` with specific actions (`CreateIngestion`, `DescribeIngestion`, `UpdateDataSet`, `DescribeDashboard`) scoped to resource ARNs. |
| SEC-2 (BAA boundary) | MEDIUM | **Fixed.** Rewrote BAA row to explicitly state that gravity model estimation uses PHI, all upstream services need BAA coverage, and optimizer output contains only zone-level aggregates. |
| SEC-3 (Solver licensing in VPC) | MEDIUM | **Fixed.** Expanded Solver Licensing row with guidance on self-hosted license servers, WLS connectivity requirements, telemetry concerns, and open-source alternatives. |
| ARC-1 (Gravity model linearization) | MEDIUM | **Fixed.** Added inline note in Step 3 flow consistency constraint explaining iterative balancing approach. Added cross-reference in "Where it struggles" section. |
| ARC-2 (Training Job vs Processing Job) | MEDIUM | **Deferred as TODO.** Changed architecture diagram and Ingredients table to say "Processing" but left a TODO for TechWriter to fully explain the rationale. |
| ARC-3 (Infeasibility handling) | MEDIUM | **Fixed.** Added infeasibility handling with IIS computation in Step 4 pseudocode. |
| ARC-4 (Redshift Serverless) | MEDIUM | **Fixed.** Added Redshift Serverless recommendation in "Why These Services" and updated cost estimate. |
| ARC-5 (Standard vs Express) | LOW | **Fixed.** Added explicit note about Standard Workflows in Step Functions paragraph. |
| NET-1 (VPC endpoints) | MEDIUM | **Fixed.** Expanded VPC row with complete endpoint list. |
| NET-2 (QuickSight VPC Connection) | LOW | **Fixed.** Added VPC Connection guidance in QuickSight paragraph. |
| SEC-4 (Decision-level audit) | LOW | **Fixed.** Added S3 audit bucket with object lock guidance in CloudTrail row. |
| VOI-1 (Documentation-voice) | MEDIUM | **Fixed.** Rephrased "The optimization approach doesn't replace human judgment" to match cookbook voice. |

### From Code Review

| Finding | Severity | Action |
|---------|----------|--------|
| Finding 1 (sol_status) | WARNING | No action needed in main recipe (Python companion issue). |
| Finding 2 (Incomplete robustness) | NOTE | No action needed in main recipe (Python companion issue). |
| Finding 3 (Choice probability comment) | NOTE | No action needed in main recipe (Python companion issue). |

### Editorial Checklist

- [x] Grammar and mechanics: Fixed minor punctuation inconsistencies
- [x] Code formatting: All fenced blocks have language tags or are plain pseudocode
- [x] Link verification: All URLs are plausible AWS documentation links; existing TODO preserved for sample repos
- [x] Header hierarchy: H1 title, H2 major sections, H3 subsections, no skipped levels
- [x] Readability: Short paragraphs, active voice throughout
- [x] Voice drift: Fixed one documentation-voice instance (VOI-1); no em dashes found
- [x] RECIPE-GUIDE compliance: All required sections present in correct order
- [x] Vendor balance: ~70% vendor-agnostic (Technology section), ~30% AWS-specific (Implementation section)

### Remaining TODOs

1. `<!-- TODO (TechWriter): Expert review ARC-2 (MEDIUM). Clarify why Processing Jobs... -->` - Needs TechWriter to fully articulate the Processing vs Training Job rationale
2. `<!-- TODO: Verify these AWS sample repos exist and are current -->` - Pre-existing, retained
