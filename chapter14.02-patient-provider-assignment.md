# Recipe 14.2: Patient-Provider Assignment

**Complexity:** Moderate · **Phase:** MVP · **Estimated Cost:** ~$30-150/month compute

---

## The Problem

A physician leaves your practice. Maybe they retired, maybe they moved across the country, maybe they burned out (it happens more than anyone admits). Whatever the reason, their panel of 1,800 patients just became orphaned. Every one of those patients needs a new primary care provider. Today.

The scheduler opens a spreadsheet. They start manually assigning patients based on... what, exactly? Alphabetical order? Whoever has the most open slots? The provider who happens to be in the office that day? There's no systematic way to match patients to providers based on clinical needs, language preferences, visit frequency, or panel composition goals.

So what happens? The complex diabetic with CKD who needs monthly visits gets assigned to the part-time NP who's already over target. The Mandarin-speaking patient gets assigned to a provider who doesn't speak Mandarin, adding interpreter costs to every visit and reducing the quality of the therapeutic relationship. The patient with CHF and COPD who was seeing an internist gets reassigned to a family medicine doc who's great but has never managed that combination of conditions.

This isn't just an administrative headache. It's a clinical quality problem. Patients who get poorly matched to providers are more likely to no-show, more likely to leave the practice entirely, and less likely to achieve their care goals. The first 90 days after a provider transition are when patients are most vulnerable to falling through the cracks.

And it's not just provider departures. New patients calling to establish care need a PCP assigned. Panel rebalancing happens quarterly. Providers change their FTE status. Every one of these events triggers the same question: which patients should go to which providers?

---

## The Technology: Constrained Optimization for Assignment Problems

### What Is an Assignment Problem?

The patient-provider assignment problem is a variant of a classic in operations research: the assignment problem. You have a set of agents (patients) and a set of tasks (provider slots), and you want to find the matching that maximizes some measure of quality while respecting constraints.

More formally: you have N patients and M providers. Each patient-provider pair has a "preference score" that captures how good that match would be (based on language, complexity, capacity, continuity, and other factors). You want to assign every patient to exactly one provider such that the total preference score across all assignments is maximized, subject to constraints like panel capacity limits and provider availability.

This is a binary integer program. The decision variables are binary (patient i is either assigned to provider j, or they're not; there's no "half assigned"). The objective is linear (sum of scores times assignment indicators). The constraints are linear (sum of assignments per provider must not exceed capacity). Linear solvers eat this for breakfast.

### Why This Is Harder Than It Sounds

The mathematical formulation is clean. The real-world complexity lives in three places:

**Scoring is subjective.** How much does language concordance matter relative to panel balance? Is a gender preference match worth more than clinical complexity alignment? These weights encode organizational values, and different stakeholders will disagree. Your medical director cares about complexity matching. Your operations team cares about panel balance. Your patient experience team cares about language and gender preferences. The optimization framework forces you to make these tradeoffs explicit and quantifiable, which is uncomfortable but ultimately healthy.

**Capacity isn't uniform.** A patient who visits biweekly consumes 26 appointment slots per year. A patient who comes annually consumes 1. Assigning five biweekly patients to a provider is not the same as assigning five annual patients, even though the raw patient count is identical. Your capacity constraints need to account for visit frequency, which means you're really optimizing weighted panel load, not just headcount.

**The problem recurs.** This isn't a one-time optimization. Patients join and leave. Providers change availability. Panel targets shift. You need both a batch mode (reassign 500 patients from a departing provider) and an incremental mode (assign one new patient who just called). The batch mode uses the full optimizer. The incremental mode can use a simplified greedy approach (pick the highest-scoring available provider) but must respect the same constraints and scoring logic.

### Solver Selection

For healthcare panel assignment at typical scales (hundreds of patients, dozens of providers), open-source solvers handle the problem easily:

**CBC (Coin-or Branch and Cut).** Ships with PuLP, the most popular Python optimization modeling library. Handles binary integer programs with tens of thousands of variables in seconds. No license required. This is the right choice for most healthcare organizations starting out.

**HiGHS.** A newer open-source solver that's faster than CBC on larger problems. Good if you're scaling to thousands of patients across hundreds of providers.

**Gurobi / CPLEX.** Commercial solvers that are faster still, but the free tier has variable limits and the commercial license is expensive. Overkill for panel assignment unless you're a massive health system running this across 10,000+ providers.

For the problem sizes typical in primary care (a departing provider's panel of 500-2,000 patients distributed across 10-50 remaining providers), CBC solves optimally in under 5 seconds. You don't need a commercial solver.

### Batch vs. Incremental Assignment

Two modes, same scoring logic:

**Batch assignment** runs when a large event triggers many reassignments: provider departure, panel rebalancing, practice merger. The full optimizer runs, considers all patients simultaneously, and produces a globally optimal assignment. This is the mode we focus on in this recipe.

**Incremental assignment** runs when a single new patient needs a PCP. The optimizer is overkill for one patient. Instead, compute the preference score for that patient against all accepting providers, and assign to the highest-scoring one with available capacity. This is a greedy approach that's suboptimal globally but fast and good enough for single-patient decisions.

Both modes must use the same scoring function and respect the same constraints. If your batch optimizer says language concordance is worth 30 points, your incremental assigner should too. Otherwise you get inconsistent panel compositions depending on whether patients arrived in a batch or one at a time.

---

## General Architecture Pattern

```
[Patient & Provider Data] → [Preference Scoring] → [Constraint Optimization] → [Validation] → [Human Review] → [EHR Write-back]
```

**Data Collection.** Pull current panel rosters, provider attributes (languages, specialty, FTE, panel targets), and patient attributes (demographics, conditions, visit frequency, preferences) from your EHR and scheduling systems. For batch reassignment, also pull the departing provider's panel list.

**Preference Scoring.** For every patient-provider pair, compute a match quality score. The scoring function combines multiple factors with configurable weights: language concordance, gender preference, clinical complexity alignment, panel balance (how far is this provider from their target?), and continuity (was this provider on the same care team as the patient's previous PCP?). The output is a score matrix: patients on one axis, providers on the other, scores in the cells.

**Constraint Optimization.** Feed the score matrix and constraints into a solver. Constraints include: each patient assigned to exactly one provider, no provider exceeds their panel maximum (weighted by visit frequency), and providers who've closed their panels get zero new assignments. The solver finds the assignment that maximizes total match quality while respecting all constraints.

**Validation.** After the solver runs, verify the solution makes clinical sense. Check that all patients are assigned, no capacity limits are violated, and the distribution across providers is reasonable (flag if one provider gets more than 60% of new assignments). Generate human-readable rationale for each assignment explaining why that match was chosen.

**Human Review.** Present proposed assignments to the panel management team with scores, rationale, and distribution summaries. They approve, reject, or override individual assignments. This step is non-negotiable in healthcare: optimization suggests, humans decide.

**EHR Write-back.** After approval, update the EHR's panel attribution. This is typically an HL7 FHIR CareTeam resource update or a proprietary API call. Handle failures gracefully; a failed write-back should not leave your assignment table and the EHR out of sync.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add a subsection or paragraph explaining how batch and incremental assignment modes coexist architecturally. The incremental case (single new patient, needs PCP immediately) uses a simplified greedy approach with the same scoring function. Discuss latency requirements (seconds vs. minutes) and how both modes share constraint/scoring logic. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Add a "Fairness and Bias" subsection (in Honest Take or Variations). At minimum: log all assignments with patient demographics, run periodic statistical tests (chi-square on distributions by race/ethnicity/language), alert if any provider's panel demographics deviate significantly from the practice's overall patient demographics. -->

---

## The AWS Implementation

### Why These Services

**AWS Lambda for orchestration and the incremental path.** Lambda coordinates the batch pipeline (triggering the optimizer, storing results, notifying reviewers) and handles the incremental assignment path directly (single patient, compute scores, pick the best provider, respond in under a second).

**Amazon SageMaker Processing for batch optimization.** The batch optimizer (hundreds of patients, full constraint formulation) runs as a SageMaker Processing job. Spin up compute, run the solver, shut down. No persistent infrastructure to maintain. For the typical problem size, an `ml.m5.large` instance finishes in under a minute.

**Amazon DynamoDB for assignment storage and workflow.** Stores proposed assignments with status tracking (proposed, approved, rejected, overridden). Supports the review workflow and provides an audit trail. The partition key is patient ID; the sort key includes the batch identifier for versioning.

**AWS Step Functions for batch pipeline orchestration.** The batch pipeline has multiple steps with dependencies: extract data, compute scores, run optimizer, validate, store, notify. Step Functions manages the workflow, handles retries, and provides visibility into pipeline state.

**Amazon S3 for data staging.** Patient and provider data exports from the EHR land in S3. Optimization results and audit logs persist in S3 for compliance.

### Architecture Diagram

```mermaid
flowchart TD
    A[EHR Panel Data] -->|Export| B[S3 Data Lake\npanel-data/]
    B --> C[Step Functions\nBatch Pipeline]
    C --> D[Lambda\npreference-scoring]
    D --> E[SageMaker Processing\noptimization-solver]
    E --> F[Lambda\nvalidation]
    F --> G[DynamoDB\nassignment-store]
    G --> H[Review Dashboard\nPanel Management Team]
    H -->|Approved| I[Lambda\nehr-writeback]
    I --> A

    J[New Patient Event] --> K[Lambda\nincremental-assign]
    K --> G

    style B fill:#f9f,stroke:#333
    style E fill:#ff9,stroke:#333
    style G fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | AWS Lambda, Amazon SageMaker, Amazon DynamoDB, AWS Step Functions, Amazon S3 |
| **IAM Permissions** | `sagemaker:CreateProcessingJob`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:BatchWriteItem`, `dynamodb:GetItem`, `states:StartExecution` |
| **BAA** | AWS BAA signed. Patient demographics, conditions, and provider assignments are PHI. |
| **Encryption** | S3: SSE-KMS with customer-managed key. DynamoDB: encryption at rest with KMS CMK. All data in transit over TLS. |
| **VPC** | SageMaker Processing and Lambda in VPC with no internet access. VPC endpoints for DynamoDB (gateway), S3 (gateway), CloudWatch Logs (interface), and STS (interface). Security groups allow outbound HTTPS (443) to VPC endpoint prefix lists only. |
| **CloudTrail** | Enabled for all API calls. Audit trail for assignment changes and approvals. |
| **Sample Data** | Synthetic patient and provider data. Never use real PHI in development. |
| **Cost Estimate** | SageMaker Processing: ~$0.50-2 per batch run (ml.m5.large, under 1 min). Lambda + DynamoDB + S3: negligible for typical volumes. Monthly total: $30-150 depending on frequency. |

<!-- TODO (TechWriter): Expert review S2 (HIGH). Expand the Prerequisites table or add a paragraph specifying that the DynamoDB assignments table must use KMS CMK encryption because the rationale field and patient_complexity field contain PHI-adjacent data. Also specify that IAM access to the assignments table should be restricted to the panel management team's roles. -->

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Add a note that the review dashboard requires authentication (Cognito or enterprise SSO) with role-based access scoped to the user's department/practice. -->

### Ingredients

| AWS Service | Role |
|------------|------|
| **AWS Lambda** | Orchestration, preference scoring, incremental assignment, EHR write-back |
| **Amazon SageMaker** | Runs batch optimization solver as a Processing job |
| **Amazon DynamoDB** | Stores assignment records with status workflow (proposed/approved/active) |
| **AWS Step Functions** | Coordinates the multi-step batch pipeline |
| **Amazon S3** | Stages patient/provider data exports and stores audit logs |
| **AWS KMS** | Encryption key management for all data at rest |

### Code

#### Walkthrough

**Step 1: Compute preference scores.** For every patient-provider pair, compute a match quality score. The scoring function combines multiple weighted factors into a single number the optimizer can maximize. This is where clinical judgment gets encoded as math.

The key factors:

- **Language concordance** (highest weight). If the patient has a language preference and the provider speaks it, that's a major quality signal. Concordant language improves outcomes, reduces interpreter costs, and increases patient satisfaction.
- **Gender preference.** If the patient stated a preference and the provider matches, bonus. If they stated a preference and it doesn't match, soft penalty.
- **Clinical complexity alignment.** High-complexity patients (multiple chronic conditions, frequent visits) should go to experienced physicians. Low-complexity patients are great for providers ramping up their panels.
- **Panel balance.** Prefer providers who are further below their target. This naturally distributes patients toward providers with more capacity.
- **Continuity bonus.** If the patient's previous provider left and this provider was on the same care team, there's a continuity benefit from shared knowledge of the care plan.

```
FUNCTION compute_preference_score(patient, provider):
    score = 0

    // Language match: biggest single factor in match quality
    IF patient.language_preference IN provider.languages:
        score += WEIGHT_LANGUAGE  // e.g., 30 points

    // Gender preference: respect stated preferences
    IF patient.gender_preference == provider.gender:
        score += WEIGHT_GENDER  // e.g., 20 points
    ELSE IF patient.gender_preference IS NOT NULL:
        score -= WEIGHT_GENDER * 0.5  // soft penalty

    // Complexity alignment: match patient acuity to provider experience
    IF patient.complexity == "high" AND provider.specialty == "internal_medicine":
        score += WEIGHT_COMPLEXITY  // internists handle complex patients well
    ELSE IF patient.complexity == "low" AND provider.remaining_capacity > 400:
        score += WEIGHT_COMPLEXITY * 0.5  // good for ramping providers

    // Panel balance: prefer providers below their target
    remaining_to_target = provider.panel_target - provider.panel_current
    IF remaining_to_target > 0:
        score += WEIGHT_BALANCE * min(1.0, remaining_to_target / 500)
    ELSE:
        score -= WEIGHT_BALANCE * min(1.0, abs(remaining_to_target) / 200)

    // Continuity: same care team as previous provider
    IF patient.previous_provider IN continuity_map:
        IF provider.id IN continuity_map[patient.previous_provider]:
            score += WEIGHT_CONTINUITY  // e.g., 10 points

    RETURN score
```

The weights are tunable. Your medical director and operations team should agree on them. Higher weight means more influence on the assignment decision. Getting these weights right is an ongoing conversation, not a one-time configuration.

**Step 2: Formulate and solve the optimization.** Feed the score matrix into a binary integer program. Each decision variable represents whether a specific patient is assigned to a specific provider (1 = yes, 0 = no). The solver finds the combination that maximizes total match quality while respecting all constraints.

```
FUNCTION solve_assignment(patients, providers, preference_scores):
    // Decision variables: x[patient][provider] = 0 or 1
    FOR each patient, provider pair:
        CREATE binary variable x[patient][provider]

    // Objective: maximize total match quality
    MAXIMIZE sum of (preference_scores[p][v] * x[p][v]) for all p, v

    // Constraint 1: each patient assigned to exactly one provider
    FOR each patient:
        sum of x[patient][all providers] == 1

    // Constraint 2: weighted capacity limits
    // High-frequency patients consume more panel capacity than annual patients.
    // A biweekly patient uses 26 slots/year; an annual patient uses 1.
    FOR each provider:
        weighted_load = sum of (frequency_weight[p] * x[p][provider]) for assigned patients
        weighted_load <= remaining_capacity * average_frequency_weight

    // Constraint 3: closed panels get zero assignments
    FOR each provider WHERE accepting_new == false:
        x[all patients][provider] == 0

    SOLVE using CBC (or HiGHS for larger problems)

    IF status != OPTIMAL:
        RETURN structured error with explanation
        // Don't crash. Infeasibility means more patients than capacity.
        // Flag for manual assignment by the panel management team.

    RETURN assignment map and objective value
```

The solver handles problems with hundreds of patients and dozens of providers in seconds. For a typical panel reassignment (500 patients across 30 providers, roughly 15,000 binary variables), CBC finds the optimal solution in under 5 seconds on modest hardware.

**Step 3: Validate and interpret results.** After the solver runs, verify the solution makes clinical sense. The optimizer is mathematically correct, but "mathematically correct" and "clinically appropriate" aren't always the same thing.

```
FUNCTION validate_assignments(assignments, patients, providers):
    errors = []
    warnings = []

    // Check 1: all patients assigned
    IF any patient not in assignments:
        errors.append("Unassigned patients found")

    // Check 2: no assignments to closed panels
    FOR each assignment:
        IF provider.accepting_new == false:
            errors.append("Assignment to closed panel")

    // Check 3: panel sizes within limits
    FOR each provider:
        new_total = provider.panel_current + count of new assignments
        IF new_total > provider.panel_max:
            errors.append("Panel max exceeded")

    // Check 4: distribution fairness
    // Flag if one provider gets a disproportionate share
    FOR each provider:
        IF their share > 60% of total new assignments:
            warnings.append("Concentration risk")

    RETURN {valid: errors is empty, errors, warnings}
```

For each assignment, also generate a human-readable rationale explaining why that match was chosen. The panel management team needs to understand the "why" before they approve.

**Step 4: Store proposed assignments.** Write results to DynamoDB with `status: "proposed"`. Each record includes the patient ID, assigned provider, match score, rationale, and batch identifier. The panel management team reviews these in a dashboard and either approves (triggering the EHR update) or overrides with a manual assignment.

```
FUNCTION store_assignments(records, validation, objective_value):
    batch_id = generate unique batch identifier
    timestamp = current UTC time

    FOR each assignment record:
        WRITE to DynamoDB:
            pk: patient_id
            sk: "ASSIGNMENT#" + batch_id
            assigned_provider: provider_id
            match_score: score (as Decimal, not float)
            rationale: list of reasons
            status: "proposed"
            created_at: timestamp

    RETURN batch metadata
```

Note the `Decimal(str(score))` pattern for DynamoDB. DynamoDB doesn't support Python floats; you must convert to Decimal. This is a common gotcha that causes silent data corruption if you miss it (floats get stored with unexpected precision).

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using PuLP and boto3, check out the [Python Example](chapter14.02-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

For a typical batch of 7 patients assigned across 4 providers (3 accepting):

```json
{
  "solver_status": "Optimal",
  "objective_value": 287.5,
  "assignments": {
    "PAT-001": "DR-CHEN",
    "PAT-002": "DR-PATEL",
    "PAT-003": "DR-CHEN",
    "PAT-004": "NP-JOHNSON",
    "PAT-005": "DR-PATEL",
    "PAT-006": "NP-JOHNSON",
    "PAT-007": "DR-PATEL"
  },
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  }
}
```

**Performance benchmarks:**

| Metric | Value |
|--------|-------|
| Solve time (7 patients, 4 providers) | < 100ms |
| Solve time (500 patients, 30 providers) | < 5 seconds |
| Solve time (2,000 patients, 100 providers) | < 30 seconds |
| DynamoDB write (batch of 500) | < 3 seconds |
| End-to-end pipeline (500 patients) | < 60 seconds |

**Where it struggles:**

- Very large problems (5,000+ patients, 200+ providers) may need solver tuning or decomposition
- Infeasible problems (more patients than total available capacity) require graceful handling, not crashes
- Highly constrained problems (many closed panels, strict language requirements) may produce suboptimal assignments because feasibility dominates optimality

---

## The Honest Take

The optimization part is the easy part. Seriously. Formulating the integer program, running the solver, getting an optimal solution: that's a weekend project for anyone who's taken an OR class. The hard parts are everything around it.

**Getting the weights right is a political problem, not a technical one.** Your medical director wants complexity matching weighted at 50%. Your operations VP wants panel balance at 50%. Your patient experience officer wants language concordance at 50%. They can't all be 50%. The optimization framework forces this conversation into the open, which is valuable but uncomfortable. Expect the first three months to be mostly weight-tuning based on stakeholder feedback on the assignments produced.

**The scoring function encodes bias whether you intend it or not.** If language concordance is weighted heavily and your Mandarin-speaking providers happen to be your most junior, you'll systematically assign Mandarin-speaking patients to junior providers. That might be fine (language concordance genuinely matters for outcomes) or it might perpetuate a disparity you'd rather address by hiring more senior Mandarin-speaking providers. Monitor assignment patterns by patient demographics. Run chi-square tests quarterly. Build alerts for statistical anomalies.

**Providers will override your optimizer.** And that's fine. The optimizer suggests; humans decide. But track the override rate. If it's above 20%, your scoring function doesn't match clinical judgment and needs recalibration. If it's below 5%, you might be able to auto-approve low-risk assignments (healthy patients to providers with ample capacity) and only route complex cases to human review.

**The incremental case is where you'll spend most of your engineering time.** The batch optimizer runs weekly or on-demand. The incremental assigner runs every time a new patient calls. It needs sub-second latency, which means you can't spin up a SageMaker job for each patient. Pre-compute provider scores and cache them. Update the cache when panel counts change. The architecture for incremental assignment is fundamentally different from batch, even though the scoring logic is shared.

---

## Variations and Extensions

### Multi-Site Assignment

If your health system has multiple clinic locations, add geographic proximity to the scoring function. Drive time from patient home to clinic matters, especially for patients with mobility limitations or those who rely on public transit. You can use a distance matrix API to compute drive times and add a distance penalty to the preference score. Weight it appropriately: a 5-minute drive difference matters less than language concordance, but a 45-minute difference matters more.

### Temporal Panel Rebalancing

Instead of waiting for a provider departure to trigger reassignment, run the optimizer quarterly to proactively rebalance panels. Identify providers who are significantly over or under target, and propose a small number of voluntary transfers (patients who would score higher with a different provider anyway). This is politically sensitive: patients don't like being "reassigned" without a clear reason. Frame it as "we found a provider who's a better fit for your needs" rather than "we're moving you for operational reasons."

### Insurance Network Constraints

Add a hard constraint that patients can only be assigned to providers who are in-network for their insurance plan. This is a binary constraint (in-network or not), not a scoring factor. If a patient's plan has limited in-network providers, the optimizer's feasible set shrinks and the assignment may be suboptimal on other dimensions. Surface this tradeoff to the panel management team: "This patient got a lower match score because only 2 of 30 providers are in-network for their plan."

---

## Related Recipes

- **Recipe 14.1: Appointment Slot Optimization** - Optimizes the template structure; this recipe optimizes who fills those slots
- **Recipe 14.3: Nurse Scheduling** - Similar constraint optimization but with shift-based temporal constraints
- **Recipe 14.6: Real-Time Resource Allocation** - The real-time counterpart to this batch optimization

---

## Additional Resources

### AWS Documentation
- [Amazon SageMaker Processing](https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html) - Running batch compute jobs
- [Amazon DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html) - Table design and access patterns
- [AWS Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html) - Workflow orchestration
- [AWS Lambda in VPC](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html) - Network isolation for PHI workloads
- [AWS KMS](https://docs.aws.amazon.com/kms/latest/developerguide/overview.html) - Customer-managed encryption keys

### Optimization Libraries
- [PuLP Documentation](https://coin-or.github.io/pulp/) - Python linear programming modeling
- [HiGHS Solver](https://highs.dev/) - High-performance open-source solver
- [Google OR-Tools](https://developers.google.com/optimization) - Alternative optimization framework

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 2-3 weeks | Batch optimizer with hardcoded weights, manual CSV export for review |
| **Production-ready** | 6-8 weeks | Full pipeline with DynamoDB workflow, review dashboard, EHR write-back, VPC isolation |
| **With variations** | 10-12 weeks | Add incremental assignment, multi-site support, fairness monitoring, insurance constraints |

---

**Tags:** `optimization` · `operations-research` · `panel-management` · `assignment-problem` · `integer-programming` · `primary-care` · `patient-matching`

---

[← Recipe 14.1: Appointment Slot Optimization](chapter14.01-appointment-slot-optimization) · [Chapter 14 Index](chapter14-index) · [Recipe 14.3: Nurse Scheduling →](chapter14.03-nurse-scheduling)
