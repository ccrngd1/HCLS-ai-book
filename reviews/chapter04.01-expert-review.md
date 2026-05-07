# Expert Review: Recipe 4.1 - Appointment Reminder Channel Optimization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-07
**Recipe file:** `chapter04.01-appointment-reminder-channel-optimization.md`

---

## Overall Assessment

This is a strong recipe and the strongest opener for Chapter 4 I could have hoped for. The problem statement is among the best in the book so far: four specific patient personas, each illustrating a distinct failure mode, set up the "right channel, right time, right message" framing without a single sentence of filler. The teaching arc from rules to propensity models to contextual bandits is pedagogically clean, and the choice of Thompson sampling with Beta-Binomial is the right level of sophistication to introduce bandits without demanding SageMaker from day one. "The Honest Take" is excellent, particularly "The ML is the easy part" and the reward-definition-is-the-system insight. Both are hard-won production wisdom, not documentation filler.

That said, there are three production-hardening gaps that need attention before publication. Two of them are security concerns that readers will trip over if they follow the recipe as written: push notifications via APNs/FCM are treated as if they're BAA-covered (they're usually not), and there is no dead-letter queue anywhere in the architecture, so dispatch failures are silently lost. Both need explicit callouts. The third is a set of missing VPC endpoints (KMS, Scheduler, EventBridge) that will break any VPC-isolated deployment.

The recipe also slightly oversells per-patient bandit convergence for low-frequency patients (most healthcare patients will never accumulate enough observations to move off the cohort prior), and conflates TCPA consent requirements in ways that could mislead readers on the regulatory floor. Neither breaks the recipe, but both should be nuanced.

Priority breakdown: 0 critical, 3 high, 6 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA coverage is explicitly stated in prerequisites with specific services enumerated (SNS, SES, Connect, End User Messaging, DynamoDB). Correct approach.
- Customer-managed KMS keys specified for DynamoDB and Kinesis (not "default" / AWS-owned). Correct.
- Lambda CloudWatch log groups are specifically called out for KMS encryption with the note that "lambdas can log extracted patient context." Good catch; many recipes miss this.
- SES TLS policy `Require` on configuration sets is mentioned. Correct.
- Minimum-necessary PHI is articulated as a design principle with a concrete example ("You have an appointment with Dr. Smith on Friday at 2 PM" vs. "You have your cardiology stress test on Friday").
- TCPA and CAN-SPAM are both flagged in prerequisites with STOP-keyword handling and the 10-business-day unsubscribe window.
- Synthea recommended for synthetic dev data. Correct.
- Opt-out enforced as a hard constraint BEFORE the model scores candidates. This is the right ordering.
- CloudTrail data events for DynamoDB tables containing PHI are called out. Correct.

### Finding 1: Push Notification PHI Without APNs/FCM BAA Discussion

- **Severity:** HIGH
- **Expert:** Security
- **Location:** Step 4 (dispatch), the `portal_push` branch; and the Architecture Diagram, which lists `portal_push` as a candidate channel without a corresponding BAA-covered delivery service.
- **Problem:** The pseudocode dispatches push via `push_client.send(patient_id = patient.id, payload = content, custom_data = { reminder_id: reminder_id })`, with only the comment "Push delivery is via your mobile app's push infrastructure." In practice, mobile app push infrastructure means Apple Push Notification service (APNs) and Firebase Cloud Messaging (FCM). Apple does not sign HIPAA BAAs for APNs. Google's BAA for FCM is narrow and excludes most consumer push configurations. This means any PHI in the notification payload (patient first name, provider name, appointment date, clinical context) passes through a non-BAA third party. The `content` object in the recipe contains `patient_first_name`, `provider_last_name`, `appt_date_local`, which is PHI in combination.

  The recipe's general BAA language ("any third-party messaging provider outside AWS, you need a separate BAA with that provider") technically covers this, but readers building a portal push path will not connect "third-party messaging provider" to APNs/FCM unless it's spelled out. The industry pattern is (a) empty/minimal push payload that triggers the app to fetch authenticated details, or (b) end-to-end encrypted payloads the app decrypts on device. Neither is mentioned.
- **Fix:** Add a paragraph to "Why These Services" (or a new sub-bullet under the portal_push dispatch case) explicitly stating: APNs and FCM are not typically BAA-covered for push. Production implementations must either (1) send a content-free notification that triggers the app to pull the reminder from a BAA-covered backend via an authenticated call, or (2) encrypt the payload end-to-end. The pseudocode passing `content` directly into push is illustrative only and should not be copy-pasted.

### Finding 2: Reminder-ID-Based Confirm URL Lacks Authentication Discussion

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 4 (dispatch), `confirm_url: short_url("/confirm/" + reminder_id)`
- **Problem:** The confirm URL is a UUID in the path, unauthenticated. A UUID4 is not trivially guessable, but reminder IDs travel through carrier SMS gateways, email servers, third-party URL shorteners, and browser histories. Anyone who intercepts or observes the URL (shared device, screenshot, carrier logs, SMS preview on lock screen) can confirm or decline the appointment on the patient's behalf, and the confirm page itself may display appointment details. For a reminder confirmation, this is widely considered acceptable with a short TTL and a single-use token, but the recipe discusses none of this. It also doesn't clarify whether `short_url(...)` resolves to an internal BAA-covered service or a third-party shortener (bit.ly, tinyurl) that would leak the mapping of short URL → reminder ID to a non-BAA provider.
- **Fix:** Add a short paragraph to the "Why This Isn't Production-Ready" section: confirm URLs should use single-use, time-limited tokens (not long-lived reminder IDs), and the shortening service must be an internal service or a BAA-covered provider. Not bit.ly. Also note that confirm pages should not display clinical detail beyond what the reminder itself contained.

### Finding 3: Bandit State and Reminder Decisions Are PHI, and the Recipe Treats Them as Metadata

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** "Expected Results" section, sample records for `bandit-state` and `reminder-decisions`
- **Problem:** Both sample records contain patient identifiers keyed to appointment identifiers and channel preferences. Under HIPAA Safe Harbor, patient ID and appointment ID combined with demographic or clinical signals (channel history, response patterns) constitute PHI. The prerequisites call out DynamoDB encryption correctly, so the data-at-rest story is fine. What's missing is access-pattern guidance: who can read these tables, audit logging for reads (not just writes), and retention/deletion policies for old bandit state and expired decision records. A seven-year accumulation of reminder decision records is itself a PHI dataset with disclosure risk.
- **Fix:** Add a note (either in prerequisites or in "Why This Isn't Production-Ready"): reminder-decisions and bandit-state tables contain PHI in combination. Enable DynamoDB Streams or CloudTrail data events for read access audit, define a retention policy, and scope IAM read access narrowly (the reward-updater Lambda, the recommender Lambda, and named audit roles only).

### Finding 4: TCPA Consent Language Is Stricter Than the Healthcare Exemption Requires

- **Severity:** MEDIUM
- **Expert:** Security (compliance accuracy)
- **Location:** Prerequisites, "Consent & Opt-out Management" row
- **Problem:** The prerequisites state "TCPA (Telephone Consumer Protection Act) compliance for voice and SMS: explicit prior written consent to send automated reminders to mobile numbers." This is the standard for telemarketing and advertising. For healthcare messages from HIPAA-covered entities, the FCC's 2015 ruling (47 CFR § 64.1200(a)(3)(iv) and subsequent orders) carved out an exemption: appointment reminders, confirmations, and certain other "health care messages" sent to wireless numbers do not require prior express written consent, provided the content is limited to the exempted categories, the provider is the patient's existing healthcare provider, and the patient can opt out. The recipe's stricter "prior written consent" standard is safer and over-compliant, which is fine as a default posture. The problem is that it misrepresents the regulatory floor, which could push readers to build consent-capture workflows that aren't required and may irritate patients who then complain they were asked to "sign up for reminders" for care they already asked for.
- **Fix:** Rewrite the consent row to say something like: "TCPA compliance for voice and SMS. Healthcare messages from an existing provider qualify for the FCC healthcare exemption for appointment reminders, but the content scope is narrow (no marketing, no billing collections, no third-party content). Many organizations default to prior-consent capture anyway for safety; pick a posture and document it. STOP-keyword handling and opt-out enforcement are required regardless." Cite the FCC ruling or AHA's summary if a clean public citation exists; if not, leave as a TODO for the editor.

### Finding 5: IAM Examples Hedge Against `*` But Don't Show Scoped ARNs

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites, "IAM Permissions" row
- **Problem:** The prerequisites row says "Never `*`" but then lists actions without example resource ARNs. A reader adding `sns:Publish` to an IAM policy may scope to the topic ARN, or may shortcut to `Resource: *`. The recipe's instruction is correct but not demonstrated.
- **Fix:** Add one or two example ARNs inline: `sns:Publish on arn:aws:sns:{region}:{account}:reminders-sms`; `scheduler:CreateSchedule on arn:aws:scheduler:{region}:{account}:schedule/default/reminder-*`. Makes the least-privilege guidance concrete.

---

## Architecture Expert Review

### What's Done Well

- The decision loop / feedback loop separation is explicit and correctly drawn. Many reminder systems conflate these and suffer for it.
- Hard constraints applied BEFORE the model scores candidates. This is both the correct security posture (opt-outs are never overridden) and the correct ML engineering (filter the action space before the policy, not after).
- The reminder ID propagation pattern (unique per-reminder ID travels through delivery receipts to enable joining events back to decisions) is correctly identified as the pivotal piece of plumbing. The sentence "If you can't join events to decisions, you can't learn" is exactly right and will save readers months of debugging.
- Writing the decision record BEFORE dispatching is subtle and correct. It anchors the audit trail even if dispatch fails, and it avoids the race where an engagement event arrives before the decision is queryable.
- "Why This Isn't Production-Ready" explicitly calls out appointment cancellation/reschedule as a symmetric handler. Good. Easy to miss.
- Idempotency on schedule firing is called out (schedule name deterministic from `appointment_id + offset_hours`).
- Cost estimate is grounded in per-channel pricing and stays in the right order of magnitude. The TODO on SNS pricing verification is appropriate.
- Cohort-sliced fairness monitoring is called out as a required operational surface, not an afterthought.

### Finding 6: No Dead-Letter Queue Anywhere in the Architecture

- **Severity:** HIGH
- **Expert:** Architecture
- **Location:** Architecture Diagram; also absent from prerequisites and "Why This Isn't Production-Ready"
- **Problem:** The architecture diagram shows EventBridge Scheduler invoking the recommender Lambda directly, the engagement event bus (Kinesis) invoking the reward-updater Lambda, and the messaging services (SNS/SES/Connect) publishing back to Kinesis. None of these paths have a dead-letter queue. EventBridge Scheduler's built-in retry policy will drop an event after max retries with no durable sink. A recommender Lambda that fails (Bedrock or SES throttling, DynamoDB hot partition, cold start timeout, transient VPC endpoint unavailability) silently loses the reminder decision. The patient never gets reminded. The operations team has no way to replay. This is the worst failure mode for a reminder system because it's invisible: the metric "reminders sent" drops slightly and no one notices.

  The reward-updater has the same issue. An engagement event that fails to join back to a decision record silently disappears, and the bandit state stops incorporating it. Over months, this degrades the model without any visible symptom.
- **Fix:** Add DLQs on both Lambdas. For EventBridge Scheduler → recommender, either configure the Scheduler target with a DLQ (SQS) or front the Lambda with SQS and let Scheduler enqueue to SQS. For Kinesis → reward-updater, configure an on-failure destination (SQS or SNS) on the event source mapping. Add CloudWatch alarms on DLQ depth. Update the architecture diagram to show both. Add a paragraph to "Why This Isn't Production-Ready" describing the replay runbook: when you find messages in a DLQ, what do you do with them?

### Finding 7: Missing Architecture for the `portal_push` Channel

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram and Step 4 pseudocode
- **Problem:** The pseudocode and eligibility filter treat `portal_push` as a first-class channel, but the architecture diagram shows only SMS, email, and voice dispatch services. There's no component labeled for push infrastructure, no mention of how push delivery events flow back into the engagement event bus, no discussion of whether push is via SNS mobile push (which does have a BAA path) or via the app's direct APNs/FCM integration (which does not, per Finding 1). The recipe lists push as a candidate but leaves its entire implementation undefined.
- **Fix:** Either (a) remove `portal_push` from the candidate list in the recipe pseudocode and mention it as a future extension, or (b) add a dedicated paragraph and architecture-diagram component for push. If going with (b), the minimum-viable path is Amazon SNS Mobile Push → APNs/FCM with a content-free payload that triggers the app to fetch details from a BAA-covered backend. Delivery events flow from SNS Mobile Push platform application attributes and CloudWatch metrics. Tie this into Finding 1.

### Finding 8: Per-Patient Bandit Convergence Is Overstated for Low-Frequency Patients

- **Severity:** MEDIUM
- **Expert:** Architecture (modeling)
- **Location:** "Where it struggles" bullet 1; "Expected Results" table row "Time to learn a new channel: ~50 observations per (patient, channel)"
- **Problem:** The recipe notes that very-low-volume patients have wide posteriors, which is true. What's understated is the prevalence of this case. A typical primary care patient has 1-3 appointments per year. At two reminders per appointment across four channels, a patient accumulates maybe 8 channel observations per year total, split across channels so that the per-channel rate is 1-3 observations per year. To accumulate 50 observations per (patient, channel) takes 15-50 years. In practice, the vast majority of patients never move off the cohort prior. The bandit's personalization benefit is concentrated in high-frequency patients (chronic disease cohorts, frequent specialty follow-ups) where it actually matters, and in cohort-level learning (which is effectively what the system does for everyone else).

  This isn't a bug; it's a feature of per-patient bandits with slow-arriving data. But the "learning by doing" framing in the Technology section oversells the personalization arc without flagging that most patients will be effectively cohort-targeted forever. Readers may build this expecting per-patient personalization and find that their fleet-wide metric moves are driven by cohort-level learning, not personal learning.
- **Fix:** Add one paragraph to the Technology section (near the cold-start discussion) or to "Where it struggles": for most patients, the personal posterior will remain broad because appointment frequency is low. The bandit's real value at fleet scale is efficient cohort-level learning (exploration concentrated where cohort-level uncertainty is high) combined with high-frequency-patient personalization. Consider a hierarchical or partial-pooling formulation if per-patient personalization is the primary goal. The simple Beta-Binomial in the recipe is fine, but set the expectation correctly.

### Finding 9: EventBridge Scheduler Quotas Not Discussed at Scale

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why These Services" / Prerequisites
- **Problem:** EventBridge Scheduler has account-level quotas: 1M schedules per account (default, adjustable), creation/deletion TPS limits, and group-based organization. A mid-size health system handling 100K appointments per month with 4 reminder offsets each has 400K active schedules, which is under the default but starts to constrain how aggressively you cancel/recreate on reschedules. A large system or a national chain can blow past the default. The recipe presents Scheduler as a clean fit without flagging that the quota is a real design constraint at scale.
- **Fix:** Add a line to "Why These Services" under the Scheduler entry: "At scale (hundreds of thousands of active schedules), you'll need to request a quota increase and consider schedule groups for operational management. For organizations with millions of appointments in flight, Scheduler may become the scaling bottleneck; evaluate DynamoDB-backed custom scheduling against your volume."

### Finding 10: Lambda Concurrency at Scheduler Fan-Out Not Addressed

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram and "Why This Isn't Production-Ready"
- **Problem:** Reminder sends cluster heavily around specific offsets from appointment time. At T-24h specifically, the morning before appointments, you get a fan-out spike: all of tomorrow's appointments firing reminders in a narrow window. For a practice with 500 appointments tomorrow, the recommender Lambda receives 500 invocations in minutes, each making 2-3 DynamoDB reads, a decision, and a dispatch. Lambda default account concurrency is 1000, which is fine for most practices but not guaranteed, and concurrency is shared across every Lambda in the account. Reserved concurrency for the recommender would ensure reminder dispatch isn't starved by other workloads. Not mentioned.
- **Fix:** Add one sentence to the recommender Lambda description in "Why These Services": "For production, set reserved concurrency on the recommender Lambda so shared-account workloads can't starve reminder dispatch during the T-24h fan-out spike."

### Finding 11: Cohort Prior Loading Mechanism Unspecified

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 3 pseudocode, `COHORT_PRIORS[cohort][channel].alpha`
- **Problem:** `COHORT_PRIORS` is referenced as a lookup without specifying how it's stored or refreshed. If it's in Lambda module-scope memory, it's pinned to cold-start init and may be stale for days. If it's in DynamoDB, that's an extra read per decision. If it's on S3 loaded at cold start, that's consistent but requires a redeploy to update. The recipe is silent.
- **Fix:** Add a comment in Step 3 or a paragraph in "Why This Isn't Production-Ready" describing the cohort prior refresh cadence: computed offline from a data warehouse on a monthly cadence, stored in a small DynamoDB lookup table keyed by cohort, read on cold start into module memory, re-fetched on a schedule. The k-anonymity threshold for cohort size is also called out in "Why This Isn't Production-Ready" but the loading mechanism itself isn't.

---

## Networking Expert Review

### What's Done Well

- VPC isolation specified for Lambdas with Flow Logs enabled.
- VPC endpoints listed for the primary services (DynamoDB, SNS, SES, Kinesis, CloudWatch Logs).
- TLS in transit specified for all channels.
- SES configuration set with TLS policy `Require` is the correct hardening.

### Finding 12: Missing KMS VPC Endpoint

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row
- **Problem:** The recipe specifies customer-managed KMS keys for DynamoDB, Kinesis, and CloudWatch log groups. Every Lambda operation touching any of those resources triggers a KMS call (for envelope encryption key decryption or generation). If Lambda is in a VPC with no `com.amazonaws.{region}.kms` VPC endpoint, those KMS calls either fail (no internet) or egress through NAT (more cost, more latency, and PHI-adjacent traffic on a potentially less-controlled path). The prerequisites list five VPC endpoints but omit KMS, which is used pervasively.
- **Fix:** Add KMS to the VPC endpoint list: "DynamoDB, SNS, SES, Kinesis, CloudWatch Logs, and KMS."

### Finding 13: Missing VPC Endpoints for EventBridge Scheduler and EventBridge

- **Severity:** MEDIUM
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row
- **Problem:** The `schedule-reminders` Lambda calls `Scheduler.CreateSchedule` and `Scheduler.DeleteSchedule` (Step 1 and the cancellation handler). In a VPC with no `com.amazonaws.{region}.scheduler` endpoint, those calls egress through NAT. The appointment event ingestion also hits EventBridge, which has its own endpoint `com.amazonaws.{region}.events`. Neither is in the prerequisites list.
- **Fix:** Add both endpoints: `com.amazonaws.{region}.scheduler` for the Scheduler API calls from the schedule-management Lambda, and `com.amazonaws.{region}.events` if Lambdas publish to EventBridge directly. The recommender Lambda itself doesn't need the Scheduler endpoint because Scheduler invokes it (that's an AWS-to-Lambda path, not Lambda-to-Scheduler).

### Finding 14: No Egress Posture for Outbound Messaging Calls

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites, "VPC" row
- **Problem:** SNS, SES, and Connect VPC endpoints keep the API call itself inside the AWS network, but the final delivery (SMS to carrier, email to recipient's mail server, voice to telco) necessarily egresses AWS. That's inherent and not a finding in itself. What is worth noting: for the schedule-reminders Lambda and any Lambda that integrates with the EHR (for appointment events), egress through a NAT Gateway with security group restrictions and a controlled outbound allow-list matters. The recipe says "Production: Lambdas in VPC with VPC endpoints" and "VPC Flow Logs enabled" but doesn't mention NAT posture or outbound egress control.
- **Fix:** One line in the VPC row: "Lambdas that need to reach non-VPC-endpoint-covered services egress through a NAT Gateway with a restricted security group. No 0.0.0.0/0 egress from any Lambda subnet."

---

## Voice Reviewer

### What's Done Well

- The Problem section is a highlight of the book. The four personas ("the 74-year-old who uses a flip phone," "the 34-year-old whose phone number on file is their previous employer's cell") are specific, human, and each illustrates a distinct failure mode. This is exactly the voice the style guide calls for.
- "Technical success, operational failure." Excellent one-sentence paragraph, lands.
- "(learning by doing, where each decision generates the signal that improves future decisions) is the defining feature of what machine learning people call the contextual bandit problem." Parenthetical aside, correctly teaches the term without talking down, and explicitly names the concept for readers who want to search more.
- "Rules-based systems are underrated." Good, direct, correct.
- "The simplest thing that could possibly work." Great. Honest.
- "Skip this step, and sooner or later your model will cheerfully text a patient who opted out three years ago and your compliance team will remember your name." This is peak CC voice.
- "The ML is the easy part." The whole paragraph on 80/20 vs 20/80 budgeting is excellent and will be quoted back to the reader by their PM later.
- "The reward definition is the system. Get it right, or build the wrong thing faster." Memorable.
- Em dash check: I ran a scan for U+2014. Zero em dashes present. Pass.
- Vendor balance: the Problem, Technology, and General Architecture Pattern sections are fully vendor-neutral. AWS enters in "The AWS Implementation" and stays there. The 70/30 prose split is cleanly maintained.

### Finding 15: "Modern approach" Is a Small Doc-Voice Creep

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "Three Approaches, Ordered by Sophistication," Approach 3 paragraph, opening sentence: "Contextual bandits. The modern approach."
- **Problem:** "The modern approach" is the kind of phrase that creeps in because it sounds authoritative but doesn't actually say anything. Thompson sampling is from 1933. The other two approaches in the list are also current. What the author actually means is "the approach that closes the loop between decision and data," which is much more useful.
- **Fix:** Replace with something like "The learning approach" or "The approach that generates its own training data." Or just drop the phrase and let the next sentence do the work: "Contextual bandits. A contextual bandit explicitly balances exploration..."

### Finding 16: "Materially more expensive" Is Mild Hedging

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "Why These Services," Amazon Connect paragraph: "For a reminder use case it's heavier than SMS or email, and you only want to use it for patients whose history says voice performs best."
- **Problem:** Elsewhere the recipe says "voice is materially more expensive, typically $0.01–$0.02 per minute of call plus per-minute telephony." "Materially more expensive" is slightly hedged and then immediately given a number, which makes the hedge redundant. It reads fine, just slightly verbose for CC's usual density.
- **Fix:** Optional. Either drop "materially" (voice is more expensive, $0.01-$0.02 per minute...) or drop the range and let the hedge carry (voice is materially more expensive; budget accordingly). Not a blocker, just a tighten.

### Finding 17: One Verbose Parenthetical in the Variations Section

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "Variations and Extensions," Content personalization via LLM: "Keep the LLM on a tight leash (templates, tone constraints, no clinical inference) and run it offline if you can, so real-time latency doesn't depend on the LLM."
- **Problem:** The paragraph is fine but three variations all start roughly the same way ("Hold the channel choice constant," "The recipe treats each reminder," "Instead of 'maximize confirmed rate,'"). Slight rhythm monotony. Not a blocker.
- **Fix:** Optional. Vary opening structure on one of them. Lowest-priority finding in the review.

---

## Stage 2: Expert Discussion

**Overlap: Security Finding 1 (push PHI) and Architecture Finding 7 (portal_push architecture undefined).** Both experts flagged the portal_push channel for the same underlying reason: it appears in the candidate list but has no real architectural or security treatment. These are two views of one gap. Resolution: treat them as a single issue with two facets (the architecture needs a push component, and that component has specific BAA constraints). Either remove push from the recipe and mention as future work, or add a real push architecture with the BAA-compliant pattern.

**Overlap: Security Finding 3 (bandit/decision table access control) and Architecture Finding 11 (cohort prior loading).** Both touch "who reads what, with what refresh cadence, under what audit." The security view is about PHI access control; the architecture view is about operational staleness. They're complementary and both should be addressed, but they don't conflict.

**Conflict: Security Finding 4 (TCPA over-compliance) vs. recipe author's likely defensive posture.** The recipe is stricter than the regulatory floor on TCPA. A security reviewer who represents "don't get sued" will argue for keeping the strict posture. A security reviewer who represents "accurate regulatory picture for the reader" will argue for nuance. Resolution: the cookbook's pedagogical mission favors accurate nuance over defensive maximalism. Readers building production systems will make their own risk-based choices; the cookbook's job is to describe the actual floor. Recommend rewriting the prerequisites row to acknowledge the healthcare exemption while noting that many orgs choose to exceed it.

**Priority alignment:** All experts converge on the same two top issues: the push notification PHI handling and the missing DLQ. Neither is CRITICAL (neither blocks the recipe's pedagogical mission), but both will actively mislead a production implementer. The networking findings are real but easier to fix (add endpoints to a table row). The voice findings are cosmetic.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Zero CRITICAL findings. Three HIGH findings, which is at the threshold (more than 3 is FAIL). The three HIGH findings (push PHI, DLQ, and the related portal_push architecture gap that compounds with the push PHI issue) are production-hardening concerns, not fundamental design flaws. The recipe's teaching of channel optimization, contextual bandits, Thompson sampling, and the feedback-loop architecture is solid and publishable. The HIGH findings should be addressed either in the main text or in "Why This Isn't Production-Ready" before the editor finalizes the recipe.

Counting: Findings 1, 6, and 7 are HIGH (one is the security-lens view and one is the architecture-lens view of the same portal_push gap; they are listed separately because they are distinct fixes). If Finding 1 and Finding 7 are treated as a single combined fix (remove portal_push from the recipe, or add a complete BAA-compliant push architecture), the HIGH count is effectively 2. Either way, below the FAIL threshold.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| 1 | HIGH | Security | Step 4 dispatch, portal_push branch | Push notifications via APNs/FCM lack BAA; recipe sends PHI in payload |
| 6 | HIGH | Architecture | Architecture Diagram, all Lambda paths | No DLQ anywhere; dispatch and reward failures silently lost |
| 7 | HIGH | Architecture | Architecture Diagram, Step 4 | portal_push listed as a channel but has no architecture component |
| 2 | MEDIUM | Security | Step 4 confirm_url | Unauthenticated reminder-ID URL; third-party shortener risk |
| 3 | MEDIUM | Security | Expected Results sample records | Reminder-decisions and bandit-state tables are PHI; access controls and retention not specified |
| 4 | MEDIUM | Security | Prerequisites, TCPA row | TCPA consent language stricter than FCC healthcare exemption; may mislead readers |
| 8 | MEDIUM | Architecture | Technology section / Expected Results | Per-patient bandit convergence overstated for low-frequency patients |
| 9 | MEDIUM | Architecture | Prerequisites | EventBridge Scheduler quotas not discussed at scale |
| 10 | MEDIUM | Architecture | Architecture Diagram | No reserved concurrency on recommender Lambda for T-24h fan-out spike |
| 12 | MEDIUM | Networking | Prerequisites, VPC row | Missing KMS VPC endpoint |
| 13 | MEDIUM | Networking | Prerequisites, VPC row | Missing EventBridge Scheduler and EventBridge VPC endpoints |
| 5 | LOW | Security | Prerequisites, IAM row | "Never *" stated but scoped ARN examples not shown |
| 11 | LOW | Architecture | Step 3 pseudocode | Cohort prior loading mechanism not specified |
| 14 | LOW | Networking | Prerequisites, VPC row | No explicit egress posture (NAT, security groups) |
| 15 | LOW | Voice | Technology section, Approach 3 | "The modern approach" is slightly doc-voice |
| 16 | LOW | Voice | Why These Services, Connect | "Materially more expensive" is mildly hedged |
| 17 | LOW | Voice | Variations section | Three variation paragraphs open similarly; minor rhythm issue |

---

## Recommended Actions (Priority Order)

1. **Resolve the portal_push gap** (Findings 1 and 7 combined): either remove `portal_push` from the candidate list and mention it as a future extension that requires BAA-compliant push infrastructure, or add an explicit architecture component (Amazon SNS Mobile Push → APNs/FCM with content-free trigger pattern) with a paragraph on APNs/FCM BAA limitations.
2. **Add DLQs to the architecture** (Finding 6): SQS DLQ on the EventBridge Scheduler → recommender path, on-failure destination on the Kinesis → reward-updater mapping. Update the architecture diagram. Add a replay-runbook note in "Why This Isn't Production-Ready."
3. **Tighten the confirm_url security story** (Finding 2): single-use, time-limited tokens; internal or BAA-covered URL shortener only.
4. **Add access-control and retention guidance for PHI tables** (Finding 3): CloudTrail data events, retention policy, narrow IAM read scopes.
5. **Rewrite the TCPA prerequisites row** (Finding 4) to acknowledge the FCC healthcare exemption while noting common over-compliance postures.
6. **Add KMS, Scheduler, and EventBridge VPC endpoints** (Findings 12, 13) to the prerequisites VPC row.
7. **Add a paragraph on bandit convergence for low-frequency patients** (Finding 8) to "Where it struggles" or the Technology section.
8. **Add Scheduler quota note and Lambda reserved concurrency note** (Findings 9, 10) to "Why These Services."
9. **Add a cohort prior loading mechanism note** (Finding 11) to Step 3 or "Why This Isn't Production-Ready."
10. **Scope IAM examples with ARNs** (Finding 5); one or two examples is enough.
11. **Optional voice polish** (Findings 15, 16, 17): tighten "modern approach," drop redundant "materially," vary one Variations paragraph opening.

---

## Notes for Editor

- The recipe is long (~4,300 words before the footer). Length is earned; the Problem section alone justifies the first 600 words. Do not trim the four-personas opener.
- Two `<!-- TODO -->` markers in the main recipe need resolution before publication: the SNS vs. End User Messaging SMS service boundary, and the illustrative lift numbers in the Expected Results table. The editor or a follow-up task should drive these to closure.
- The Related Recipes section references future recipes (4.2, 4.5, 4.6) that haven't been written yet. Standard practice for the book; flag for the chapter index but not a blocker.
- The Synthea link is verified as a real repository. The Wikipedia Thompson sampling link is real. The AWS documentation links all point to legitimate current AWS doc paths. No fake URLs detected.
- The AWS sample repos section has appropriate hedging (`<!-- TODO: verify a specific, current healthcare-engagement aws-samples repo -->`). Appropriate.
- The Python code review (chapter04.01-code-review.md) passed with two WARNINGs (non-portable strftime, SNS MessageAttributes propagation). Those are separate from the expert-review scope but worth cross-referencing when the editor reconciles the final versions.
