# Recipe 3.9: Cybersecurity / Access Pattern Anomalies ⭐

**Complexity:** Complex · **Phase:** Production (with privacy office and infosec governance) · **Estimated Cost:** ~$0.0001 to $0.001 per audit event scored (mostly ingest, enrichment, and storage; full user-graph rescoring runs nightly and dominates compute)

---

## The Problem

It's 11:47 p.m. on a Tuesday and a nurse on the cardiology step-down floor opens the chart of a patient she's never cared for. The patient was admitted earlier that day. They share a last name. They live on the same street. The nurse spends about ninety seconds in the chart, opens the demographics tab, the medication list, the discharge plan from the patient's previous admission six months ago, and then closes it. She doesn't open her assigned patients' charts again for the rest of her shift; her shift is mostly over.

In the audit log, that's six events. Six rows out of the roughly forty million audit rows the EHR generates that night across the health system. The user account is legitimate. The login was from her usual workstation. She has the role of registered nurse on a cardiology unit, which means she has read access to most patient charts in the hospital because the EHR was configured for clinical workflow flexibility, not least-privilege access. The chart she opened has no special "VIP" flag. Nothing in the rules engine fires. Nothing in the daily reports notices. The events sit in the audit log unread.

Three weeks later the patient (a relative of hers, as it turns out) calls the privacy office to complain that his cousin asked him about a medication he hadn't told her about. The privacy office pulls the access log for his record, sees the nurse's name, runs the standard "did this employee provide care to this patient" check against the encounter assignment data, sees that no, she did not, and opens an investigation. The investigation takes six weeks. The nurse is terminated. The hospital files a HIPAA breach notification with the Office for Civil Rights. The patient, who is now an ex-relative for several reasons, files a civil suit. The local newspaper picks up the story. The CIO gets a phone call from the CEO that begins with "explain to me how this happened."

That's the unglamorous reality of healthcare access monitoring. Not the Hollywood scenario where a foreign state actor exfiltrates ten million records (that happens too, and it's a different problem). The everyday reality is a workforce of thirty or forty thousand authenticated users, each of whom has been granted broad access to the EHR by clinical necessity, browsing records they shouldn't be looking at for reasons that range from idle curiosity to malicious snooping to credential compromise. The access is technically authorized. It's just not appropriate. And the audit log records every event, but nobody is looking at the audit log because looking at the audit log is like trying to drink from a fire hose by reading every drop.

Healthcare has a specific structural problem that makes this hard, and it's worth naming clearly before getting into the technology. Most enterprise security tools assume that users are granted narrow access, and that anomalous access (a finance person opening engineering files) is by definition suspicious. That model breaks in healthcare. A clinician needs broad access because patients move between units, get cross-covered by specialists, end up in the ED at 3 a.m. when their primary team isn't on, and require care that crosses departmental boundaries. The EHR is configured for that flexibility. "Break-glass" overrides exist because the alternative (a patient dying because the right doctor couldn't open the right chart fast enough) is unacceptable. Pulling access permissions tighter solves the privacy problem and creates the patient safety problem, and patient safety wins every time.

So the access is broad. The audit log is enormous. And inside the audit log, there are real signals that real people are doing real things that violate the privacy of real patients. The published OCR enforcement actions tell the story over and over: an employee browsing the records of a co-worker going through a divorce; a clerk looking up the records of a high-profile patient because the local news ran a story about them; a nursing student accessing her ex-boyfriend's chart out of curiosity; a billing analyst looking up family members; a contractor whose credentials got phished and now an external actor is methodically pulling records that could be used for medical identity theft. Every one of these is in the audit log. Every one of these violates 45 CFR 164.502(a) and 164.514. Every one of these is a breach if it goes undetected and undisclosed long enough. The technology problem is finding them in the noise.

Healthcare also has a particular flavor of insider threat that doesn't show up much in other industries. The "VIP snooping" problem is real and persistent. Every health system that's treated a celebrity, a professional athlete, a prominent local figure, a victim of a high-profile crime, or simply someone whose name has been in the news this week has dealt with it. The published enforcement actions and settlement agreements include cases involving access to records of public figures, ranging from individual employee terminations to multi-million-dollar corporate settlements. The behavioral signature is consistent: a sudden cluster of access events on a record from users who have no clinical relationship to the patient, often beginning within hours of news coverage and sometimes lasting for weeks.

Then there's the credential compromise problem. The cybersecurity literature tracks credential theft (phishing, credential stuffing, infostealer malware on a clinician's home laptop) as one of the leading initial-access vectors for healthcare breaches. Once the credential is stolen, the attacker logs in as the legitimate user. The audit log shows the legitimate user. The behavior is what's anomalous: access from an unusual location, at an unusual time, in an unusual sequence (broad reconnaissance across many records rather than the focused workflow of a clinician taking care of a panel of patients), or to records the legitimate user has never opened before. The detection problem here is similar in shape to the insider snooping problem (deviation from the user's behavioral baseline) but the cadence and the patterns differ.

And then there's the slowest-moving but highest-stakes case: the privileged user who is methodically extracting records for sale. Database administrators, integration engineers, IT analysts, and other privileged users have access to bulk data exports as part of their legitimate job. A small fraction of them, over time, have used that access to exfiltrate data. These cases are often discovered through downstream events (patients reporting medical identity theft, dark web market monitoring) rather than through detection on the access logs themselves, because the legitimate work and the malicious work look identical at the access-event level. The detection has to look at the longer time scale: who's pulling more bulk data than their peers in the same role, whose pulls have shifted over time, who's exporting data in formats or to destinations that don't match the documented workflows.

The reason this problem lands at the complex end of the chapter, despite being a fundamentally well-defined problem (audit log in, prioritized cases out), comes down to a tangle of intertwined issues.

**The base rate is brutal.** A typical health system's EHR generates tens of millions of audit events per day. The fraction that represent actual policy violations is somewhere in the parts-per-million range. Even a 99% accurate detector produces a flood of false positives that no privacy office can review. The math is the same alert-fatigue math as the rest of this chapter, with an extra twist: the privacy office staff is small (often single digits across an entire health system) and the reviews are time-consuming (you have to read the access events in context, check the user's role and assignments, often interview the user). The system has to be ruthlessly precise at the top of its ranking, because the privacy office can review tens of cases per day, not thousands.

**Legitimate access patterns are extraordinarily diverse.** A hospitalist covers a different patient panel every week. A float nurse moves between units. A consulting cardiologist sees referrals from across the medical staff. A pharmacist reviewing inpatient orders touches every patient with active prescriptions. A medical student rotates services every month. A clinical researcher pulls cohorts that span thousands of patients. None of these are anomalous. All of them produce access patterns that look unusual relative to a naive baseline. Establishing what's normal for each role and team is a substantial part of the work.

**The "treatment relationship" is poorly captured in source data.** The first question a privacy office asks about a flagged access is "did this employee have a clinical reason to access this patient's record?" Answering that should be straightforward. It usually isn't. Care team membership in EHRs is set inconsistently (some systems require explicit assignment, some infer from documentation, some from order signatures, some from scheduled appointments). Cross-coverage is often not represented at all. Pre-admission and pre-procedure access (radiology techs preparing for tomorrow's cases, OR staff prepping for the morning lineup) happens before the formal care team relationship exists in the data. Floor-coverage and rapid-response relationships are real but transient. A detector that needs a clean treatment-relationship signal to operate finds itself working with a noisy and incomplete one.

**The data is high-dimensional and multi-modal.** Each audit event has a user, a patient, a resource type (chart, lab result, image, note, order), an action type (view, edit, print, export), a timestamp, a device, an application context (which screen the user was on), a network context (IP address, geographic location for remote workers), and often a clinical context (the user's current scheduled or assigned patients). Modeling all of these jointly without exploding the false-positive rate requires careful feature engineering and sometimes representation learning.

**Adversarial dynamics matter.** A subset of insider threats are sophisticated. The user knows there's monitoring. The user reads about cases that get caught. The user adjusts behavior to stay below thresholds: small numbers of accesses spread over weeks, accesses inside a plausible workflow (open the patient's chart from the schedule view rather than search), accesses that mimic the normal pattern of a colleague. The detector has to handle the unsophisticated cases (which are the majority) and have a story for the sophisticated cases (which are the minority but the highest-stakes).

**The output isn't an alert; it's an investigation.** Same lesson as Recipes 3.6, 3.7, and 3.8. The detection is the small part. The investigation is the work product. Privacy office investigators need: the user's HR record, the patient's encounter history, the user's care assignments, the user's recent activity, the patient's relationships (employee status, family relationships, neighborhood, divorce records when relevant, public-figure status), and a way to document the investigation outcome so the system can learn. The pipeline that ends with "here's a scored list of users" is producing maybe 30% of the value.

**Workforce monitoring has its own legal and labor considerations.** Monitoring employee behavior crosses several legal frameworks (HIPAA, ECPA, state-specific employee privacy statutes), labor frameworks (NLRB protected concerted activity, union collective bargaining agreements), and organizational ones (transparency to staff, due process when an investigation is initiated). The monitoring system should be deployed under a written acceptable-use and monitoring policy that the workforce has been notified of. The legal posture differs substantially across jurisdictions, especially for state employees, unionized environments, and remote workers in different states. 

**The breach notification clock is real.** HIPAA breach notification rules require notification within 60 days of discovery; some states have shorter windows (California's 15-business-day rule for medical information breaches, for example). Once an investigation confirms unauthorized access, the clock starts. A detection system that finds breaches late produces breaches that get reported late, which produces additional regulatory exposure. Speed of detection is part of the operational metric, not just an engineering nice-to-have. 

**HIPAA Security Rule audit controls are mandatory but underspecified.** The HIPAA Security Rule (45 CFR 164.312) requires covered entities to "implement hardware, software, and/or procedural mechanisms that record and examine activity in information systems that contain or use electronic protected health information." It does not specify what to look at, how often, or what the response should be. OCR has issued guidance and enforcement actions that effectively define the floor (you must do something; "we collect logs but never look at them" is not a defense), but the ceiling is whatever you choose to do. 

What you actually want to build is a continuously running pipeline that consumes EHR audit logs (and ideally application access logs from related systems: PACS, lab systems, billing platforms, communication tools), enriches every event with identity context (the user's role, department, manager, current assignments), patient context (encounter history, care team relationships, sensitivity flags), and behavioral baselines (this user's normal pattern), produces user-level and access-cluster-level risk scores on a streaming and batch basis, and routes the highest-risk cases to a privacy-office investigation workflow with the supporting evidence pre-assembled. Underneath sits a relationship graph of users, patients, encounters, and devices because the most interesting patterns live in the relationships, not in any single event. Around it sits the integration with the SIEM (most security teams expect access anomalies to flow into the same case management system as the rest of the security operations work), the privacy office case management system (which is often separate from the SIEM), and the HR and identity systems that provide the enrichment data.

Let's get into how.

---

## The Technology

### The Vocabulary You Need

Healthcare access monitoring has its own jargon, partly inherited from general cybersecurity (UEBA, UBA, SIEM) and partly specific to healthcare (FairWarning-style monitoring, "patient privacy monitoring," "appropriate use review"). Quick tour, because these terms are going to recur.

**UEBA (User and Entity Behavior Analytics).** The general cybersecurity discipline of building behavioral baselines for users and devices and flagging deviations. UEBA tools (Splunk UBA, Exabeam, Securonix, Microsoft Sentinel UEBA, etc.) come from the broader infosec world and are designed for general enterprise environments. They can be tuned for healthcare but rarely ship with healthcare-specific knowledge of the kind that distinguishes a hospitalist's normal access pattern from a billing analyst's.

**Patient privacy monitoring (PPM).** The healthcare-specific category. Tools like Protenus, Imprivata FairWarning (now FairWarning), MaizeAnalytics (now part of Imprivata), Iatric Patient Privacy Monitor, and Epic's Provider Access Audit are built around the specific patterns that matter in healthcare: same-name access, neighbor access, VIP/employee/celebrity access, family-relationship access, break-glass override review, and treatment-relationship validation. These tools encode much of the policy logic that a generic UEBA tool doesn't know about.

**EHR audit logs.** The primary data source. Every major EHR (Epic, Cerner/Oracle Health, MEDITECH, Allscripts, athenahealth, eClinicalWorks) produces audit logs covering chart accesses, but the format, the granularity, the latency, and the completeness vary substantially. Epic's Audit Log API, Cerner's Behavior Tracker, and MEDITECH's audit reports are not interchangeable; the integration is vendor-specific.

**HIPAA Security Rule audit controls.** The regulatory backbone. Required under 45 CFR 164.312(b). The implementation specification is "addressable," meaning a covered entity can either implement the safeguard, document why an alternative is reasonable and appropriate, or do neither and document why. In practice, OCR enforcement has made it clear that meaningful audit-log review is required.

**Treatment relationship.** The clinical relationship between a workforce member and a patient that legitimizes access. Captured (often imperfectly) in care team assignments, encounter assignments, order signatures, scheduling data, on-call schedules, and break-glass logs. The single most important enrichment for distinguishing legitimate from problematic access.

**Break-glass.** Emergency access override. When a user accesses a record they don't have routine permissions for (a patient with a "sensitive patient" flag, a record outside their normal department), the EHR may require them to confirm an override and document a reason. Break-glass logs are a critical input to access monitoring because they're explicit user assertions of intent.

**Appropriate use review.** The privacy office workflow term for the review of flagged access events. Not "investigation" until the case has been escalated; the early-stage review is part of the routine privacy-office function.

**Workforce member.** The HIPAA term for anyone with EHR access (employees, contractors, students, volunteers, residents, business associates). A useful term because the monitoring scope includes all of these, not just W-2 employees.

### The Detection Pattern Catalog

Before picking algorithms, a builder should know the detection patterns that map to the actual policy violations the privacy office cares about. These are the canonical patterns that show up in privacy monitoring tooling, in OCR enforcement actions, and in the literature on healthcare insider threats.

**Same-name access.** A workforce member accesses the record of a patient sharing the same last name. Family-relationship access is the most common policy violation by volume, and same-name is its strongest signal. Refinements: weighted by how unusual the name is (a user named "Smith" matching a patient named "Smith" is much weaker than "Wojnarowski" matching "Wojnarowski"), and combined with the patient's home address (same household is a stronger signal than same surname alone).

**Same-address or same-neighborhood access.** A workforce member accesses a record where the patient's address is the same as the workforce member's, or in the same small geographic area. Captures family members who don't share a name (in-laws, blended families, cohabitating partners). Requires HR address data linked to workforce identifiers, which is sensitive but typically accessible to the privacy office under appropriate controls.

**Self-access and dependent-access.** A workforce member accesses their own record or a dependent's. Often legitimate (accessing one's own discharge summary after a procedure), often a policy violation (most health systems prohibit self-access to records and require that workforce members go through the patient portal like everyone else; some have explicit exceptions for accessing one's own records during care). Highly noisy as a flag without policy context; very useful when paired with the organization's specific policy.

**Co-worker access.** A workforce member accesses the record of another workforce member. Sensitive area: co-worker records are often viewed during care delivery (the employee was a patient at the facility), but they're also a frequent privacy-violation pattern (the curious co-worker checking on someone's surgery). Requires linking workforce identity data with patient identity data, which has its own access controls and concerns.

**VIP/sensitive-patient access.** A workforce member accesses the record of a patient flagged as VIP, public figure, employee, foster child, victim of crime, behavioral health patient, or other sensitivity category. The flag is set in the EHR by the privacy office or the patient relations team. Access to flagged records is sometimes blocked by routine permissions and requires a break-glass override; sometimes it's allowed but logged with elevated scrutiny.

**Off-hours and off-shift access.** Access that occurs outside the workforce member's normal working hours. A nurse who works day shift accessing records at 2 a.m. is anomalous; a nurse who works nights accessing records at 2 a.m. is normal. Requires the user's scheduled-shift data, which lives in workforce management systems (Kronos, UKG, Workday, etc.).

**Geographic and device anomalies.** Login from an IP address that doesn't match the user's normal pattern, or from a country the user doesn't operate in. Useful for credential-compromise detection. Less useful for insider snooping (the insider is at their normal workstation). Refinements: VPN coverage and remote-work patterns make raw IP geolocation noisy; impossible-travel detection (login from Boston at 9:00 a.m. and Dallas at 9:30 a.m.) is more robust.

**Volume anomalies.** A user who normally opens 30-60 charts per day suddenly opens 300. The classic compromise signature. Requires user-level behavioral baselines and time-window aggregation.

**Search anomalies.** Searches by patient name that don't lead to expected workflow patterns. A user searching for "Smith, John" repeatedly without ever progressing into a chart-open-to-document flow is exhibiting curiosity behavior, not workflow behavior. Many EHRs log search events distinctly from chart-open events, which provides a useful signal source.

**Print and export anomalies.** Printing records, exporting reports, generating "patient lists" that produce CSV or PDF outputs that leave the system. Higher-stakes than view events because the data is now portable. Some EHRs differentiate between "print preview" (which is less risky) and "actual print job sent to a printer" (which is more so).

**Bulk and reporting anomalies.** Database queries, report-server requests, ad-hoc query builder usage that pulls data on many patients at once. Privileged-user territory. Detection requires monitoring of the query/reporting layer in addition to the EHR audit log.

**Break-glass override patterns.** Break-glass overrides should be infrequent (a small percentage of accesses) and concentrated in clinical roles where unexpected coverage is plausible. Users with high break-glass override rates relative to peers, or break-glass overrides on patients they have no clinical relationship to, are notable. Reasons documented in break-glass overrides are also a source of signal: vague reasons ("clinical review") versus specific reasons ("emergency consult during code blue") differ in their reviewability.

**Sequence and workflow anomalies.** Access sequences that don't match clinical workflow. A clinician opening a chart, jumping to demographics, then to social history, then to the address field, then closing without writing notes or orders, is exhibiting a curiosity pattern, not a clinical workflow. A clinician opening a chart and proceeding through history-of-present-illness, exam, assessment, and plan, in that order, is exhibiting a normal workflow. Sequence-aware models can catch what point-in-time models miss.

**Access to deceased patient records.** Specific subset that's worth handling explicitly: deceased patients' records sometimes get accessed by curious workforce members because the patient won't notice and complain. Some health systems flag deceased patients in the EHR and elevate scrutiny on access events to those records.

**Patterns around news cycles.** When a public figure is treated, or a high-profile patient is admitted (a victim of a publicized incident, a celebrity, an athlete), the access pattern to that patient's record often shows a spike of curiosity-driven access from users with no clinical relationship. Some patient-privacy-monitoring tools include "news-watch" features that automatically elevate scrutiny on records linked to patients matching name patterns from news feeds.

**Account abandonment and reactivation.** Accounts that haven't logged in for an extended period, then suddenly become active. Could be a returning user, could be a compromised account. Depends on context.

**New-user behavior.** New employees ramping up have different access patterns than established employees: more searches, more discovery behavior, more chart browsing. The detector has to differentiate "new and learning" from "compromised or curious."

### Statistical and ML Methods That Fit

The technique palette spans rules-based detection through unsupervised behavioral models through graph analytics. The right approach is layered, not monolithic.

**Rules engines.** The CCI-edits-equivalent of access monitoring. Encodes the explicit policy: same-name access flags, VIP-record access flags, self-access blocks (for organizations whose policy is to block them), break-glass-override review queues, off-hours access for users on standard daytime schedules. Rules are precise, explainable, defensible in front of a workforce member ("you triggered the same-last-name rule and the access doesn't match a documented care relationship"), and fast to compute. They miss the diffuse and the novel, which is what the rest of the stack is for.

**Per-user behavioral baselines.** For each workforce member, establish a baseline of their normal behavior across multiple dimensions: typical hours active, typical chart-open volume per shift, typical patient-set size accessed per week, typical sequence patterns, typical resource types touched, typical departments accessed. Baselines updated continuously (with appropriate handling of role changes and ramp-up). Deviations beyond control limits flag for review. The classic UEBA backbone.

**Peer-group baselines.** Each user is compared not just to their own history but to the distribution within their peer group: same role, same department, same shift, same training program. A new resident's behavior is compared to other new residents, not to attending physicians. A float nurse's behavior is compared to other float nurses. Peer-group definition is one of the most consequential design choices in the entire system; bad peer groups produce bad baselines and bad alerts.

**Isolation Forest and other unsupervised outlier detectors.** On per-user feature vectors aggregated over various time windows (per-day, per-week, per-shift). Captures multivariate outliers that no single dimension would flag. Pairs with SHAP values for explaining why a particular user-window was flagged.

**Sequence models (RNN, LSTM, Transformer).** On audit-event sequences within a session or shift. Learns the typical sequences of resource-type and action-type events and flags sessions whose sequences don't match. Captures the workflow-vs-curiosity distinction. More expensive to train and operate than tabular models, and the interpretability is harder; usually a second-pass technique on candidates surfaced by simpler detectors.

**Graph-based detection.** Construct the graph of workforce members, patients, encounters, devices, and applications. Compute graph features: how connected is this user to this patient through legitimate care relationships, how unusual is this user's access pattern within their team, what's the reachability between the user's documented panel and the accessed patient. Graph methods are essential for catching the patterns that rules-and-baselines methods miss: relationship-based access (the user accessed someone they have an off-system relationship with), team-level anomalies (a team's collective access pattern shifted), and credential-compromise patterns (the user accessed a set of patients that don't share any care-team or workflow connection).

**Graph neural networks (GNNs).** The learned-representation evolution of graph features. A GNN trained on the heterogeneous graph (users, patients, encounters, departments, applications) learns embeddings that incorporate role, structural position, and behavioral features. Anomaly detection on the embeddings catches patterns that hand-crafted graph features miss. Still emerging in production privacy monitoring; promising in research. 

**Autoencoders on access vectors.** Train an autoencoder on the feature vector of legitimate access events; flag events with high reconstruction error. Works well on high-dimensional event representations. Suffers from the standard autoencoder concerns: needs a reasonably clean training set, needs care to prevent the model from learning to reconstruct anomalies.

**Supervised classification on labeled cases.** When the privacy office has accumulated enough confirmed-violation labels, supervised models can re-rank candidates from unsupervised detectors. The label problem is severe: confirmed violations are rare, the labeling latency is long, dismissed candidates (which are the majority) are noisy negatives, and the labels reflect what the privacy office found, not what was actually present (selection bias). Supervised approaches are useful as re-rankers, not as primary detectors.

**LLM-assisted triage.** Given an alert payload (the access events, the user context, the patient context, the care relationship status), an LLM can produce a plain-language assessment of whether the access pattern looks more like a workflow or a curiosity-snooping pattern, with reasoning. Investigators report substantial time savings on the per-case review, and the LLM's analysis often surfaces context the investigator might have missed (the patient was discussed in a recent staff meeting, for instance). Always with human review; the LLM produces decision support, not decisions. 

**Feedback-driven threshold tuning.** Same operational rule as the rest of the chapter. The privacy office's adjudications (true positive, false positive, inconclusive) flow back into threshold tuning, peer-group refinement, and (where labels are sufficient) supervised re-ranker training. Without feedback, the system decays.

A reasonable layered architecture: rules engine for the policy-defined patterns (same-name, VIP, self-access, break-glass), per-user and peer-group baselines for the deviation patterns, graph features for the relationship patterns, sequence models for the workflow patterns, and an LLM-assisted triage layer that compiles all the evidence into reviewable cases for the privacy office. The supervised classifier on labels comes in as the operational program matures.

### Identity, Patient, and Workforce Enrichment

The enrichments that transform a raw access event into a reviewable signal are as important as the detector logic. The data sources that enable the enrichments often live outside the EHR and the security stack.

**Identity and access management (IAM).** Active Directory, Okta, Azure AD/Microsoft Entra ID, or equivalent. The user's account, group memberships, role assignments, employment status, and credential lifecycle. Source of truth for "is this account active" and "what is this user's role this week."

**Human resources information system (HRIS).** Workday, Oracle HCM, SAP SuccessFactors, UKG, etc. The user's organizational hierarchy (manager, department, business unit), employment dates, address, dependents, employment type (employee, contractor, student, volunteer). Source of truth for the demographic data needed for same-name and same-address detection.

**Workforce management / scheduling.** Kronos (now UKG), API Healthcare, Symplr, etc. The user's scheduled shifts, on-call schedules, time-off, and unit assignments. Source of truth for "was this user supposed to be working at this time" and "was this user assigned to this unit."

**EHR care team and encounter data.** The clinical relationships between providers and patients: assigned attending, assigned nurse, on-call coverage, consult relationships, treatment teams. The single most important enrichment for differentiating legitimate from problematic access. Quality varies: some EHRs capture this comprehensively, some require deduction from order signatures, documentation authorship, or scheduling.

**EHR sensitive-patient flags.** VIP, employee, foster child, behavioral health, victim of crime, opt-out, sealed record, restricted access. These flags must flow through to the monitoring system because they trigger different policies and elevate scrutiny.

**Patient demographics.** Name, address, date of birth, employer, employment relationship to the health system, family relationships (when documented). Source of the data that drives same-name, same-address, same-employer, and family-relationship detection.

**News and public-figure feeds.** Some health systems integrate news feeds or public-figure databases to elevate scrutiny on patients matching prominent names in current coverage. Useful but requires policy clarity (the system shouldn't be making judgments about who is "prominent"; it should be implementing policies set by the privacy office).

**Network and device context.** User's typical workstation, device, IP range, geographic region. Source of compromise-pattern detection.

**Privacy office case history.** Previously confirmed violations by user, previously confirmed legitimate accesses, previously dismissed cases. Feeds back as features and as suppression signals (don't re-flag the same pattern that was already cleared).

The enrichment pipeline is often the largest engineering effort in the system. The detection algorithms, even sophisticated ones, are commodity; the enrichment plumbing across IAM, HRIS, scheduling, EHR, and case history systems is what differentiates working programs from non-working ones.

### Calibration, Subgroup Performance, and the Workforce-Equity Question

The monitoring system has a uniquely sensitive stakeholder dynamic. The workforce members being monitored are often the same employees the organization is trying to retain and engage. Disparate-impact concerns arise: do certain roles, certain departments, certain demographic groups get flagged at higher rates than others, and is the difference clinically/operationally justified or is it bias?

**Subgroup performance.** Track flag rates and confirmed-violation rates by role, department, demographic group, employment type, and shift. Wide variation in flag rates across subgroups warrants investigation: is the variation real (one department genuinely has more curiosity-driven snooping) or artifactual (the baselines are calibrated for one group's workflow and don't fit another's)?

**Threshold calibration.** Per-cohort thresholds may be appropriate when peer-group definitions don't fully capture the variation. A new-resident cohort may justify higher false-positive tolerance because the cost of missing a true positive is the same but the operational impact of false positives during their training is different.

**Workforce communication and transparency.** The acceptable-use policy should disclose that monitoring exists. The investigation policy should describe the process when an investigation is initiated. The appeals process should exist and be documented. Workforce members who have been investigated and cleared should be informed of the outcome. The legal posture varies by jurisdiction, but the operational ethic is consistency and process.

**Union considerations.** In unionized environments, monitoring policies are subject to collective bargaining and may have specific notification, due-process, and appeals requirements. The system implementation should reflect the bargained terms. 

**Appeals and remediation.** When a workforce member is wrongly flagged or wrongly investigated, there should be a path to clear the record and (when appropriate) update the model so the same false positive doesn't recur. The feedback loop matters; a one-way system that never corrects mistakes erodes trust.

### Workflow Integration Is, Again, the Actual Product

The lesson recurs because it's the lesson that matters most. The detection pipeline is one component. The privacy-office case management workflow, the SIEM integration for the cybersecurity team, the HR coordination for employment actions, the legal coordination for breach notification, and the reporting infrastructure for compliance documentation are the other components.

The specific workflows that matter:

- **Privacy office daily case queue.** Sorted by composite risk score, with suppression for already-investigated cases and recently-cleared users. Click-through to the user's identity context, the patient's encounter context, the access event detail, and the relationship-graph view.
- **Investigator case assembly.** When an investigator opens a case, the system pre-assembles the supporting evidence: the access events in question, the user's recent activity, the patient's care team and encounter history, prior cases involving the user, and the LLM-generated narrative summary.
- **Investigation outcome capture.** Confirmed violation, dismissed (legitimate access with documented reason), inconclusive (cannot determine), referred to HR, referred to law enforcement. Outcomes feed back into the model and the suppression rules.
- **HR coordination.** Confirmed violations move into HR for employment action (counseling, retraining, suspension, termination). The monitoring system should hand off the case package to HR through a defined process.
- **Breach notification clock.** Confirmed unauthorized access initiates the HIPAA breach notification process. The monitoring system should track the time from initial detection to confirmed unauthorized access and from confirmed unauthorized access to notification, because both clocks matter operationally.
- **Compliance reporting.** Boards, audit committees, and regulators want regular reports on the program: cases reviewed, cases confirmed, breach notifications issued, patterns observed, remediation actions taken. The reporting infrastructure should produce these on a defined cadence.
- **SIEM integration.** Cybersecurity teams want access anomalies in the same case management system as the rest of the SOC's work. The pipeline should publish events to the SIEM (Splunk, Microsoft Sentinel, Chronicle, IBM QRadar) in addition to the privacy-office workflow, with a defined separation of which event types go where.

---

## General Architecture Pattern

At a conceptual level, the access pattern anomaly detection pipeline ingests audit events from the EHR (and supporting clinical systems), enriches each event with identity, workforce, patient, and clinical-context data, computes per-user and per-event behavioral and relationship features, scores users and access clusters on a streaming and batch basis, ranks the resulting case queue, and delivers it to the privacy office (and the SIEM) with the supporting evidence pre-assembled. Underneath sits the relationship graph, the per-user baseline store, and the case-history database. Around it sits the integration with HRIS, IAM, scheduling, and patient registration systems that provide the enrichment data, plus the integration with case management, HR, and legal workflows that consume the outputs.

```text
┌────────── ACCESS PATTERN ANOMALY DETECTION PIPELINE ─────────────┐
│                                                                  │
│   [EHR audit log:        [Application audit:    [Network /        │
│    chart, lab, image,     PACS, lab system,      VPN logs,         │
│    note, order, search,   pharmacy, billing,     auth logs,        │
│    print, export]         portals, comms]        device telemetry]│
│                                                                  │
│   [Break-glass            [Search and report     [Bulk export      │
│    override events]        requests]              and query logs]  │
│                                                                  │
│           │                                                      │
│           ▼                                                      │
│   [Streaming Ingest and Normalization]                           │
│   (canonical access event format, time normalization, user and  │
│    patient identifier resolution, deduplication)                 │
│           │                                                      │
│           ▼                                                      │
│   [Enrichment Layer]                                             │
│   (identity from IAM, role and dept from HRIS, schedule from    │
│    workforce mgmt, care team and encounters from EHR,           │
│    sensitivity flags, geographic and device context)            │
│           │                                                      │
│           ▼                                                      │
│   [Relationship Graph]                                           │
│   (users ↔ patients ↔ encounters ↔ devices ↔ departments;       │
│    treatment relationships, care team membership, scheduling)   │
│           │                                                      │
│           ▼                                                      │
│   [Per-User Behavioral Baselines]                                │
│   (typical hours, volume, sequence, resource mix, peer cohort   │
│    distribution, drift detection on baseline shifts)            │
│           │                                                      │
│           ▼                                                      │
│   [Detector Bank]                                                │
│   (rules engine: same-name, VIP, self, break-glass;              │
│    statistical: per-user and peer-group deviation;               │
│    graph: relationship-based detection;                           │
│    sequence: workflow vs curiosity)                               │
│           │                                                      │
│           ▼                                                      │
│   [Composite Scoring and Calibration]                            │
│   (per-user composite, per-cluster composite, calibration        │
│    layer, subgroup-stratified thresholds)                         │
│           │                                                      │
│           ▼                                                      │
│   [Case Builder]                                                 │
│   (group flagged events into cases, attach evidence,             │
│    LLM-generated narrative, deduplicate against open cases,      │
│    suppress recently-cleared patterns)                           │
│           │                                                      │
│           ▼                                                      │
│   [Privacy Office Case Queue]   [SIEM Integration]               │
│   (investigation workflow,        (security operations              │
│    evidence package, outcome      visibility, correlation)        │
│    capture)                                                       │
│           │                                                      │
│           ▼                                                      │
│   [Investigation Outcome]                                        │
│   (confirmed violation, dismissed, inconclusive; HR referral;    │
│    breach notification trigger; case closure)                    │
│           │                                                      │
│           ▼                                                      │
│   [Outcome and Feedback Capture]                                 │
│   (label store for retraining; suppression rule updates;         │
│    threshold tuning; subgroup performance; equity audits)        │
│           │                                                      │
│           ▼                                                      │
│   [Compliance Reporting + Governance]                            │
│   (board and audit-committee reports, OCR documentation,         │
│    breach-notification clock, workforce communication)           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Ingest and normalization.** Audit events flow from the EHR through vendor-specific export mechanisms (Epic Audit Log API, Cerner Behavior Tracker, MEDITECH audit reports) into the pipeline. Application audit logs from PACS, lab systems, billing platforms, and patient-facing portals join the same stream. Network and authentication logs from the IdP and VPN provide context. The normalizer produces canonical events with a consistent schema: who, what, when, where, how, on what.

**Enrichment.** Each canonical event is enriched with identity, role, department, schedule, care team, sensitivity flag, and device context. Some enrichments are real-time (the user's role and department) and some are batch (the user's HR record from the previous night's HRIS export). The enrichment layer is conceptually separate from detection and is heavily plumbing-oriented.

**Relationship graph.** A continuously updated graph of workforce members, patients, encounters, departments, and devices. The graph is the substrate for relationship-based detection (does this user have a documented care relationship with this patient) and for higher-order pattern detection (is this user accessing patients in a cluster that doesn't share any care team or workflow connection).

**Per-user behavioral baselines.** Rolling windows of typical access patterns: typical chart-opens per shift, typical hour distribution, typical resource type mix, typical sequence patterns. Stored per user with peer-cohort statistics for context. Drift detection alerts when a user's baseline shifts substantially (which can indicate role change or compromise).

**Detector bank.** Multiple detectors run in parallel: the rules engine for policy-defined patterns, the per-user statistical detectors for deviation patterns, the graph-based detectors for relationship patterns, the sequence-based detectors for workflow patterns. Each produces a per-event or per-window score; the composite layer combines them.

**Composite scoring and calibration.** Per-user and per-cluster composite scores. Calibration ensures that a score of 0.8 means roughly the same probability of being a confirmed violation across cohorts. Subgroup-stratified thresholds where calibration drift differs.

**Case builder.** The component that turns scored events into reviewable cases. Groups related events (the same user accessing the same patient over multiple sessions, or a session with multiple flagged accesses), attaches the supporting evidence (user context, patient context, care relationship status, prior cases), runs the LLM-generated narrative summary, and de-duplicates against open cases and recently-cleared patterns.

**Privacy office case queue and SIEM integration.** The privacy office case queue is the primary product. The SIEM integration provides cybersecurity-team visibility for cases that overlap with broader security concerns (credential compromise, lateral movement). The two queues are complementary, not duplicative; clear separation of which case types go where.

**Investigation outcome.** Investigators adjudicate cases as confirmed violations, dismissals, or inconclusive. Confirmed violations trigger HR referral and (if unauthorized access of PHI is confirmed) the HIPAA breach notification clock. Outcomes are captured for the feedback loop.

**Outcome and feedback capture.** Outcomes flow back as labels for retraining, suppression-rule updates, threshold tuning, and subgroup-performance analysis. The feedback loop is a first-class component, not a side effect.

**Compliance reporting and governance.** Periodic reports to the privacy committee, the audit committee, the board, and (when relevant) regulators. Documentation of program operation supports the HIPAA Security Rule audit-control requirement and any future OCR audit response.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.09-architecture). The Python example is linked from there.

## The Honest Take

The detection problem is technically interesting, and it's a tiny fraction of what makes this program work. Same lesson as every other complex recipe in this chapter, said again because the lesson is the lesson. A great detector with a privacy office that can't review the cases produces no value. A simple rules-only detector with a well-staffed privacy office, a clear acceptable-use policy, and tight HR coordination produces real value. Build the program first. Build the technology into the program second. The [Architecture companion's](chapter03.09-architecture) Estimated Implementation Time table reflects exactly this discipline: a rules-only deployment with a manual privacy-office case queue and basic governance in 4-9 months, before per-user baselines, graph features, and the LLM-assisted triage layer enter the picture.

The thing that surprised me the first time I worked on access monitoring at scale: the volume is somehow both crushing and tractable. A major health system generates tens of millions of audit events per day, which sounds impossible to review until you realize that you're not trying to review individual events. You're trying to identify users whose behavior over a window is anomalous. The day-event count drops to thousands when you aggregate to user-window vectors. The flagged-user-window count drops to hundreds with rules and baselines. The reviewable case count drops to tens with composite scoring and graph features. The math works because you're not reviewing events; you're reviewing patterns. Get the aggregation right and the volume problem is mostly solved.

The thing that didn't surprise me but is worth reiterating: the false-positive rate is the binding constraint, and most teams underweight it during design. Engineers love to optimize recall ("we caught 98% of confirmed violations!"). Privacy office investigators care about precision because their day is bounded by the number of cases they can review. A system with 95% recall and 5% precision floods the queue with false positives until reviewers stop trusting it; a system with 70% recall and 25% precision is reviewable, trustable, and produces real outcomes. The math is the same as the rest of the chapter. The cure is the same: tune to capacity, not to recall.

Same-name and same-address rules are surprisingly high-yield. They're embarrassingly simple and they catch real cases. The first time I ran them on a real audit-log archive, the volume was higher than expected and the confirmed-violation rate at the top of the ranking was higher than expected. Every health system I've worked with has had at least a few cases of employees accessing family members' records, and the rules catch most of them. Don't dismiss the simple rules because they look unsophisticated; they're often the highest-precision component of the system.

The sophisticated cases are rare and they're often caught by accident. The methodical privileged-user data-extraction case, the well-trained-insider-snooping case, the cohesive credential-compromise reconnaissance case: these are the high-stakes cases, and they're harder to catch than the curiosity-snooping cases. They often surface through downstream events (a patient reports identity theft, an external feed flags data appearing on a market, a tip from a colleague) rather than through the detection pipeline. The pipeline matters for catching the bulk of cases (which are unsophisticated), and matters for the documented-program defense ("we have an active monitoring program that meets the audit-control requirement"), but it shouldn't be sold as catching every sophisticated case. Honesty about what the system does and doesn't catch is part of the operational ethic.

Care-relationship data is the longest-running pain point. Every program I've seen has the same issue: the EHR's care-team data is incomplete, the gaps are real and frequent, and the privacy office spends a lot of time investigating cases that turn out to be legitimate access in a relationship the EHR didn't capture. The structural fix is improving the EHR's native capture. The operational workaround is building suppression rules for known patterns and accepting that some false positives are unavoidable until the underlying data improves. Programs that try to chase the perfect care-relationship signal end up over-engineering the detector to compensate for upstream data quality problems; the right answer is to escalate the data-quality issues to the EHR team while operating with the data you have.

Privileged users are a different program. I cannot stress this enough. The detection patterns that work for clinical workforce don't work for IT staff with broad data access. Privileged-user monitoring needs separate baselines, separate detectors (often session recording rather than per-event analysis), separate review workflows, and separate governance. Many health systems treat privileged-access management as an entirely separate program from patient-privacy monitoring, with different staff, different vendors, and different reporting lines. If you're building a single system that tries to monitor both populations with the same detector, you're going to either flood the queue with privileged-user noise or miss real privileged-user incidents. Build them as related but distinct.

LLM-assisted triage is the biggest near-term productivity improvement I've seen in this space. The privacy office investigator's day used to be: open case, read the access events, look up the user's HR record, look up the patient's encounter history, check the care-team module, check break-glass overrides, write a note, decide. That's twenty to forty minutes per case. A well-engineered LLM triage layer that compiles all of this into a structured narrative cuts the per-case review time by half or more. The investigator still makes the decision; the LLM does the legwork. The productivity gain compounds: more cases reviewed per day means more thresholds calibrated, more feedback into the system, faster operational learning. The technology is recent enough that programs that adopted it in 2025 are still measuring the gains; the early reports are positive. Treat it as a substantial productivity improvement, not as a replacement for investigators.

The biggest mistake I see: programs that flood the workforce with investigations. A program that produces a hundred investigations a week, most of them dismissed as legitimate, generates substantial workforce friction. People stop trusting the system. People stop trusting their managers. Union grievances proliferate. Morale drops. The right tempo is: detect at high precision, investigate efficiently, communicate the outcomes to the affected workforce member (when an investigation clears them, they should know), and accept that some false negatives are the cost of a low false-positive rate. The program's social legitimacy is part of its operational viability. Programs that ignore it produce backlash that constrains the program politically.

The political reality: this is a CISO-and-CPO joint function, and the two roles often have different operational priorities. The CISO wants the system to integrate with the SIEM, to detect credential compromise, to align with the broader security operations model. The CPO wants the system to detect curiosity snooping, family-relationship access, VIP-record access, and other privacy-policy-focused patterns. Both are valid; they're slightly different problems. The most successful programs have explicit joint governance with both roles signing off on detector tuning, threshold calibration, and case-disposition policy. Programs run by infosec alone tend to under-detect privacy patterns (they're not in the SOC's wheelhouse). Programs run by privacy alone tend to under-detect cybersecurity patterns (they don't have the SIEM context). Joint governance is the durable answer.

The thing nobody talks about: training-data scarcity is a real constraint on what you can build. Confirmed violations are rare, the labels are noisy (an "inconclusive" outcome doesn't tell the model whether the access was a violation or not), and the dismissed-as-legitimate cases include both true negatives and false negatives (cases where the violation existed but couldn't be proven). Supervised models in this space have to be designed with the label-quality issues in mind. Most of the actual detection work is unsupervised or rules-driven for this reason; the supervised re-rankers are useful at the margin but not as primary detectors.

Mature programs make the false-positive rate a leading indicator. A rising false-positive rate (an increasing fraction of surfaced cases that turn out to be legitimate) signals one of several things: an EHR upgrade has shifted behavior patterns, a new role or department has emerged that the baselines don't cover, the underlying data quality has degraded, or the threshold calibration needs refresh. Programs that watch the false-positive rate as carefully as they watch the true-positive rate catch the operational drift earlier than programs that don't.

The thing I'd do differently: I'd start narrower than I usually have. A program that begins with rules-only detection (same-name, VIP, self-access, break-glass, off-hours) on a single high-priority category (employee snooping, for example), with manual review by a defined privacy office team, will produce meaningful outcomes within a quarter. From that base, behavioral baselines for the same category, then graph features for relationship-based patterns, then sequence models, then LLM-assisted triage, each in sequence with measured impact. Programs that try to deploy the full multi-detector composite system on day one usually end up with a system that's too noisy to use and too complex to tune. Pilot, validate, scale.

The financial story has changed in the last few years. OCR enforcement has grown more visible and the fines have grown larger. The largest published settlements involving inadequate audit controls are now in the multi-million-dollar range. The cost of a single confirmed breach (notification costs, credit monitoring, legal fees, potential settlement, reputation damage, regulatory action) easily exceeds the cost of running an active monitoring program. The financial argument used to be "we should do this because it's the right thing to do." It's increasingly "we should do this because the alternative is more expensive." Both motivations are valid. The change is that the latter is now defensible at the CFO level. 

Patients matter most, even when they're invisible in the operational workflow. The workforce members are the ones being monitored. The privacy office and infosec teams are the ones running the program. The leaders are the ones reading the reports. The patients whose privacy is being protected are mostly invisible to the operational machinery. They show up only when something goes wrong (they call to complain, they get notified of a breach, they file a suit). The program's purpose is to protect them. The operational ethic should reflect that, even when the day-to-day work doesn't bring them into the room.

---

## Related Recipes

- **Recipe 3.3 (Billing Code Anomalies):** Per-provider behavioral baselining is the same statistical approach applied to a different data substrate (claims rather than audit logs).
- **Recipe 3.6 (Healthcare Fraud, Waste, and Abuse Detection):** Graph analytics for relationship-based detection, adversarial dynamics, investigator workflow design, and case management patterns transfer directly. The two programs share architectural DNA and sometimes share staff.
- **Recipe 3.7 (Patient Deterioration Early Warning):** Calibration, subgroup performance, alert-volume management, and the workflow-as-product lesson all apply.
- **Recipe 3.8 (Readmission Risk Anomaly Detection):** Engagement-decay detection (a previously-engaged patient who stops engaging) shares statistical foundations with workforce-behavior baselining.
- **Recipe 3.10 (Epidemic / Outbreak Detection):** Cluster-detection on graph data and signal-detection in low-base-rate settings overlap conceptually.
- **Recipe 2.x (LLM / Generative AI):** Case narrative generation and investigator-copilot patterns use techniques from Chapter 2.
- **Recipe 8.x (NLP / Traditional):** Break-glass override reason extraction and policy-text analysis use NLP patterns from Chapter 8.
- **Recipe 13.x (Knowledge Graphs / Ontology):** The relationship graph is a healthcare-specific instance of the broader knowledge-graph patterns covered in Chapter 13.

---

## Tags

`anomaly-detection` · `cybersecurity` · `access-monitoring` · `insider-threat` · `ueba` · `user-behavior-analytics` · `patient-privacy-monitoring` · `audit-log-analysis` · `ehr-audit` · `hipaa-security-rule` · `audit-controls` · `breach-notification` · `vip-access` · `same-name-detection` · `break-glass` · `credential-compromise` · `graph-analytics` · `neptune` · `relationship-graph` · `gnn` · `xgboost` · `isolation-forest` · `autoencoder` · `sequence-model` · `lstm` · `feature-store` · `clarify` · `model-monitor` · `bedrock` · `comprehend-medical` · `kinesis` · `timestream` · `dynamodb` · `opensearch` · `eventbridge` · `sagemaker` · `appsync` · `step-functions` · `siem` · `splunk` · `sentinel` · `privacy-office` · `infosec` · `case-management` · `subgroup-performance` · `equity` · `workforce-monitoring` · `acceptable-use-policy` · `calibration` · `shap` · `peer-group-baselines` · `cold-start` · `hipaa` · `complex` · `production` · `compliance`

---

*← [Recipe 3.8: Readmission Risk Anomaly Detection](chapter03.08-readmission-risk-anomaly-detection) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.10 - Epidemic / Outbreak Detection →](chapter03.10-epidemic-outbreak-detection)*
