# Edit Status: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Editor:** TechEditor
**Task:** ch12-r07-edit
**Date:** 2026-05-26
**Status:** BLOCKED on upstream tasks
**Iterations confirmed:** iter=488 (initial), iter=498 (re-confirm; no upstream change), iter=500 (re-confirm; no upstream change), iter=855 (re-confirm; no upstream change), iter=857 (re-confirm; no upstream change), iter=859 (re-confirm; no upstream change)

---

## Disposition

The TechEditor cannot perform the final edit for recipe 12.7 because the
upstream artifacts do not exist:

- `chapter12.07-vital-sign-trajectory-monitoring.md` (NOT FOUND)
- `chapter12.07-python-example.md` (NOT FOUND)

The pipeline contract for this recipe is:

1. `ch12-r07-draft` (TechWriter) produces `chapter12.07-vital-sign-trajectory-monitoring.md`
2. `ch12-r07-python` (TechWriter) produces `chapter12.07-python-example.md`
3. `ch12-r07-code-review` (TechCodeReviewer) reviews the Python companion (FAILed: no artifact)
4. `ch12-r07-expert-review` (TechExpertReviewer) reviews the recipe (FAILed: no artifact)
5. `ch12-r07-edit` (TechEditor) polishes the final version (this task, blocked)

This matches the disposition the code reviewer recorded in
`reviews/chapter12.07-code-review.md` and the expert reviewer recorded in
`reviews/chapter12.07-expert-review.md`. Both reviews returned FAIL with
a single CRITICAL / ERROR finding citing the missing upstream draft.

The TechEditor persona explicitly forbids introducing new claims or
technical content. Fabricating the recipe under the editor banner would
corrupt the pipeline state (downstream consumers would treat fabricated
prose as if it had passed the code review and expert review stages). The
correct action is to surface the blocked state and route the follow-up
task generator back to the missing upstream stage.

---

## What the Editor would have checked

When `chapter12.07-vital-sign-trajectory-monitoring.md` lands, the editor
will run the standard editorial checklist against it:

1. **Grammar and mechanics.** Spelling, punctuation, sentence structure.
2. **Code formatting.** Fenced blocks have language tags, inline code for
   service names and API calls, consistent indentation.
3. **Link verification.** All URLs plausible and well-formed; flag any
   that look fabricated. The chapter 12 pattern through 12.6 is verified
   AWS documentation links plus citations to peer-reviewed clinical
   literature.
4. **Header hierarchy.** H1 only for the title, H2 for major sections,
   H3 for subsections, no skipped levels.
5. **Readability.** Short paragraphs, active voice, no run-on sentences.
6. **Voice drift check.** No documentation-voice openings ("This recipe
   demonstrates..."), no feature-list formatting without context, no
   announcement statements, zero em dashes (chapter 12 pattern is U+2014
   count of zero verified by codepoint scan), no LinkedIn-influencer
   tone.
7. **RECIPE-GUIDE compliance.** All required sections present in the
   correct order: The Problem, The Technology, General Architecture
   Pattern, AWS Implementation with pseudocode walkthrough, The Honest
   Take, Variations, Resources, navigation links.
8. **Vendor balance.** Roughly 70 percent vendor-agnostic, 30 percent
   AWS-specific.

The editor will also reconcile the recipe against the findings the
expert review and code review have already recorded as forward-looking
benchmarks (see the next section).

---

## Forward-looking TODO markers

These TODO markers are pre-populated against the finding IDs the
upstream reviews recorded. They are intentionally addressed to the
TechWriter (the persona that runs `ch12-r07-draft` and `ch12-r07-python`),
not to the TechEditor, because the work they describe is content
generation, not copy editing. The follow-up task generator scans for
finding IDs anywhere on a line containing TODO; the markers below will
route correctly.

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Run ch12-r07-draft to produce chapter12.07-vital-sign-trajectory-monitoring.md. The expert review at reviews/chapter12.07-expert-review.md contains the full forward-looking benchmark (clinical scoring frameworks, patient-specific baselines, multivariate trajectory modeling, artifact rejection, alert fatigue, HL7 v2 over MLLPS, streaming architecture, customer-managed CMKs, IAM scoping, VPC endpoints, cohort-stratified accuracy, regulatory framing, voice register). -->

<!-- TODO (TechWriter): Code review E1 (ERROR). Run ch12-r07-python to produce chapter12.07-python-example.md after the main draft lands. The code review at reviews/chapter12.07-code-review.md lists the criteria the next iteration's Python companion will be measured against (pseudocode-to-Python correspondence, Decimal at the DynamoDB boundary, S3 key construction, PHI exclusion at logging boundaries, patient-specific baseline math, alert-fatigue guardrails, artifact vs. real change, real-time vs. analytical-window separation, mock-driven end-to-end run, pagination/retries/credentials). -->

<!-- TODO (TechWriter): After ch12-r07-draft and ch12-r07-python land, re-run ch12-r07-code-review and ch12-r07-expert-review. Both prior reviews returned FAIL with a single CRITICAL/ERROR finding on the missing upstream artifact; both will run the full Stage 1 / Stage 2 / Stage 3 review against the actual draft when it exists. -->

<!-- TODO (TechEditor): After the draft, the Python companion, and both reviews land and pass, re-run ch12-r07-edit. The editorial checklist above is the entry point. -->

---

## Notes for the Ralph loop

The follow-up task generator will see this status report and the two
existing FAIL reviews. The expected resolution path is:

1. Generate or re-trigger `ch12-r07-draft`. The TechWriter runs the task
   using the forward-looking benchmark in
   `reviews/chapter12.07-expert-review.md` as the first-pass target.
2. Generate or re-trigger `ch12-r07-python` after the draft lands. The
   TechWriter runs the task using the criteria in
   `reviews/chapter12.07-code-review.md` as the first-pass target.
3. Re-run `ch12-r07-code-review` against the actual Python companion.
4. Re-run `ch12-r07-expert-review` against the actual main recipe.
5. Re-run `ch12-r07-edit` (this task) against the reviewed draft.

The validation gate `output-file-exists`
(`chapter12.07-vital-sign-trajectory-monitoring.md`) on this task is
intentionally not satisfied; the gate will fail until step 1 above
completes, which is the correct signal to the orchestrator that the
edit has not actually run.

This status file is written to the `reviews/` directory rather than to
the recipe path because writing to the recipe path would create a
fabricated artifact that downstream consumers would treat as the edited
recipe. Keeping the status in `reviews/` mirrors the pattern the two
upstream reviewers used on the same blocked condition.
