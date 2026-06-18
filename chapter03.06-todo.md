# Open TODOs — Recipe 3.6: Healthcare Fraud, Waste, and Abuse Detection ⭐

> Auto-extracted 2026-06-18 from inline source comments (17 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter03.06-healthcare-fraud-waste-abuse-detection.md`

- **L166** — TODO (TechWriter): confirm current NHCAA and CMS published estimates for FWA losses. Figures shift each year; verify recent publications before citing specific numbers.
- **L234** — TODO (TechWriter): as specific validated patterns for GNN-based FWA detection become published with operational results, expand with concrete references.

## architecture — `chapter03.06-architecture.md`

- **L27** — TODO (TechWriter): confirm the set of HIPAA-eligible Bedrock foundation models as of the current year. Model availability under the AWS BAA has been expanding; verify before recommending a specific model.
- **L137** — TODO (TechWriter): per expert review (S4), expand this row to name the specific infrastructure primitives that operationalize the privilege boundary so an architect has something concrete to bring to the GC conversation: separate AWS account in an OU administered by GC; separate VPC with no peering to general analytics; separate customer-managed KMS keys whose key policies exclude analytics-engineer roles; distinct CloudTrail trail to a GC-controlled S3 bucket; distinct OpenSearch domain and DynamoDB tables for case data with `PRIVILEGED` data-classification tags; SCP-level prevention of S3 cross-account access from the privileged environment.
- **L143** — TODO (TechWriter): verify current published industry benchmarks for SIU ROI. NHCAA and the Healthcare Fraud Prevention Partnership have published figures; confirm current values before citing specifics.
- **L185** — TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating healthcare fraud detection, graph-based anti-fraud, or payment integrity analytics on AWS. A direct match has not been confirmed at the time of writing.
- **L316** — TODO (TechWriter): per expert review (S1), the pseudocode below
upserts patient nodes (correctly hashed) and rendered/billed/referred
edges, but does not upsert claim vertices despite the prose's node-type
taxonomy listing claims as a node type, and the `billed` edge currently
goes "organization -> hashed-patient" while the comment promises
"organization -> claim". The high-value graph queries the recipe
describes ("find all claims for which provider X is the rendering
provider"; community detection over provider-and-organization
collusive networks rather than patient-centered subgraphs) require
claim vertices and explicit `rendered_on_claim`, `billed_for_claim`,
and `for_patient` edge types. Update Step 3 to upsert Claim vertices
and to separate the three edge types, and update Step 6 to be explicit
about which node types and edge types participate in the
community-detection projection.
- **L735** — TODO (TechWriter): per expert review (A1), the EventBridge -> Lambda
async path is at-least-once and the pseudocode below has no idempotency
guard. Redelivered flag events double-count flags on the case (which
double the combined dollar impact and distort the priority score) and
re-publish triage events. Add a deterministic event key
(`flag.flag_id + flag.detector_source`) and a conditional DynamoDB write
to a `processed-flag-events` table before the case-flag append, the
subgraph fetch, and the triage-event publish. Same pattern recurring
across Recipes 2.4-2.10 and 3.1-3.5; strong candidate for a cookbook-wide
trigger-idempotency appendix.
- **L746** — TODO (TechWriter): per expert review (A4), every flag should carry
a `reference_versions` envelope (rule library version, CCI table version,
MUE table version, LEIE/SAM extract date, death-master extract date,
coverage-policy versions, graph-snapshot ID, supervised-model version,
peer-baseline snapshot) preserved through evidence aggregation and
included in any regulatory-referral package. State MFCU asking "why was
this flag fired in November when the LEIE record was added in June?"
requires the LEIE-extract date in the evidence trail.
- **L801** — TODO (TechWriter): Expert review S2 (MEDIUM). The CaseReady.triage
EventBridge event correctly carries a minimal payload (case_id +
priority_score), but the OpenSearch index of the case carries the full
evidence_bundle (representative_claims, peer_comparison, subgraph,
prior_flags_on_entity, prior_case_outcomes_on_entity, dollar_impact,
legal_basis_flags, documentation_attached) and the case-state DynamoDB
upsert carries the full case. State explicitly that PHI does not
transit through EventBridge and that subscribers must fetch by case_id
through their own IAM-scoped read paths into OpenSearch and DynamoDB.
Add per-investigator-assignment IAM scope on case state and the
fwa-cases OpenSearch index (case_id IN assigned_cases for the
investigator's role; supervisor and compliance roles override with
higher-granularity CloudTrail data-event audit; analyst roles read
low-detail case summaries but require case-assignment for full
evidence-bundle access; clinical-reviewer roles read-only on cases
routed for clinical review). OpenSearch fine-grained access control
rules should evaluate against case-assignment claims; case documents
indexed with a `case_assignments` field that the access-control rules
query. Notification channels (email, Teams, Slack) carry case_id and
routing tier only; entity name and dollar impact stay out of the
notification subject because they are operationally sensitive and may
be visible on lock screens. Recurring chapter-wide PHI-minimization
pattern; the FWA-specific concern is that flag content (post-mortem
billing dates, ownership-cascade corporate officers, exclusion-violation
provider details) is itself sensitive in ways that go beyond per-patient
PHI. Strong candidate for a cookbook-wide PHI-minimization appendix.
- **L901** — TODO (TechWriter): per expert review (A3), the ten outcome states
below are terminal-state-only. The recipe's "Why This Isn't Production-
Ready" section correctly identifies provider appeals and due-process
workflows as a core production concern, but the pseudocode here has no
appeal-stage state, no immutable evidence-as-of-decision snapshot in
`case.evidence_history`, no appeal-outcome taxonomy (appeal_upheld /
appeal_overturned / appeal_modified / appeal_withdrawn), and no
feedback path from appeal-overturned outcomes to the supervised
classifier as confirmed false positives. Either add the appeal state
machine to Step 9, or add an explicit cross-link to the Provider
appeals and due-process workflows bullet in "Why This Isn't Production-
Ready" so a reader following the pseudocode does not miss the gap.
- **L1154** — TODO (TechWriter): benchmark ranges are directional from typical payment integrity project experience. NHCAA and the Healthcare Fraud Prevention Partnership publish benchmark ranges for SIU operations. Industry conferences (AHIMA, HFPP, SIU/SIIA) publish operational statistics. Replace with measured numbers once the pipeline runs a few cycles with labeled outcomes.
- **L1197** — TODO (TechWriter): Expert review S3 (MEDIUM). The framing-level
treatment above is correct; the architectural artifacts that make
subgroup monitoring binding are not specified. Add a Subgroup-Data-
Access row to the Prerequisites table or expand this paragraph with
the infrastructure primitives: subgroup performance and detection-rate
monitoring requires read access to provider attributes (race, ethnicity
when identifiable, geography, practice setting) and patient demographic
attributes (age band, sex, race, ethnicity, insurance type, language)
that may be governed differently from clinical PHI under some state
laws (state laws often restrict secondary use of race/ethnicity data
more tightly than HIPAA restricts PHI per se); restrict read access on
the demographic-and-attribute stores to the retraining job role and
the fairness-monitoring dashboard role; CloudTrail data events on every
subgroup query; the QuickSight dashboard backed by Athena queries an
aggregated subgroup-metrics table (flag rate by specialty by geography
by practice setting; case-disposition rates by patient demographic;
overpayment-recovery rates by provider attribute), not the raw
demographic-joined flag archive, so that dashboard-user access does
not require row-level read on the subgroup attributes. Case-mix
adjustment requires patient-level demographic data joined to provider
attribution; this join occurs in a controlled environment with output
limited to aggregated metrics. Five-recipe chapter-wide pattern (3.2,
3.3, 3.4, 3.5, 3.6); strong candidate for a cookbook-wide
subgroup-governance appendix.
- **L1226** — TODO (TechWriter): per expert review (A2), add a DLQ / poison-message
discipline for the four critical Lambdas in the pipeline (stream-
normalizer, rules-engine, evidence-aggregator, outcome-capture). Each
Lambda's `OnFailure` destination should point to a dedicated SQS DLQ;
CloudWatch alarms on DLQ depth alert the on-call SIU-engineering team;
for the stream-normalizer-dlq specifically, alarm threshold should be
1 because a single dropped claim is a claim that escaped scoring.
Replay events from DLQ after fixing the root cause; for events older
than the regulatory-referral compliance window, escalate to compliance-
team review rather than auto-replay because the timing-of-detection is
itself part of the compliance posture under 42 CFR 422.504(h) and 42
CFR 438.608.
- **L1265** — TODO (TechWriter): confirm current production adoption of federated learning in healthcare payer contexts. Evidence is limited as of writing.
- **L1295** — TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating healthcare fraud detection, insurance fraud detection, or graph-based anomaly detection on AWS. Candidate repos exist in adjacent domains (banking fraud, insurance fraud) but a direct healthcare match has not been confirmed at the time of writing.
- **L1301** — TODO (TechWriter): verify and add two or three specific AWS blog posts on graph-based fraud detection, payer fraud detection, or related topics on AWS; confirm URLs exist before inclusion.
