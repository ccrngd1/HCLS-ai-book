# Open TODOs — Recipe 3.1: Duplicate Claim Detection ⭐

> Auto-extracted 2026-06-18 from inline source comments (8 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter03.01-architecture.md`

- **L84** — TODO: verify current 837 version baseline for CMS and major commercial payers; note if/when 7030 becomes common.
- **L87** — TODO: verify recent published range for payer duplicate-claim recovery rates; typical citations in the 1-3% range but worth confirming against a current industry report.
- **L120** — TODO: verify a specific, current aws-samples repo that demonstrates duplicate claim detection on 837 data; as of this writing, a direct match has not been confirmed. The closest adjacent patterns are in general record-linkage and fraud-detection repos.
- **L586** — TODO: these benchmark ranges are directional and not tied to a specific published case study. Replace with measured numbers once deployed, or cite specific payer case studies if published.
- **L621** — TODO (TechWriter): consider adding a note about the SIU hand-off. When the detector identifies a pattern consistent with coordinated fraud (many duplicates from a single provider, unusual submission patterns), the handoff to the Special Investigations Unit is a separate workflow from prospective denial. This isn't in the core recipe scope but is a natural extension.
- **L635** — TODO (TechWriter): code review (Finding 5) flagged a small drift between Step 4 pseudocode and the Python companion's `route_claim`. The Python adds a `match_type` parameter and an exact-match fast-path (auto-suspend when `find_candidates` returned `match_type == "exact"`, regardless of score-threshold logic) that this pseudocode does not describe. The Python's branch is defense-in-depth (an exact `content_hash` collision lands at score 1.0 and would auto-suspend anyway) but the pseudocode-to-Python parity should be restored either by adding an explicit exact-match fast-path at the top of `route_claim` here, or by leaving a one-line note in the Python companion explaining the intentional deviation.
- **L671** — TODO: verify and add a specific aws-samples repo that demonstrates 837 parsing, claim deduplication, or related claims-processing patterns. As of this writing a direct match for duplicate claim detection specifically has not been confirmed.
- **L676** — TODO: verify and add two or three specific AWS blog posts on claims processing or record linkage architectures; confirm URLs exist before inclusion.
