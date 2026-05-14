# Code Review: Recipe 3.6 Healthcare Fraud, Waste, and Abuse Detection (Python Companion)

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-14
**Files reviewed:**
- `chapter03.06-healthcare-fraud-waste-abuse-detection.md` (main recipe, pseudocode walkthrough)
- `chapter03.06-python-example.md` (Python companion)

**Validation performed:**
- Pseudocode's nine steps walked against Python functions, one-to-one
- boto3 DynamoDB resource-API calls (`Table.get_item`, `Table.put_item`, `Table.update_item`) verified for parameter names and Decimal discipline
- boto3 S3 `put_object` checked for leading slashes and SSE / SSEKMSKeyId pairing
- boto3 EventBridge `put_events`, SNS `publish`, CloudWatch `put_metric_data` call shapes verified
- boto3 Comprehend Medical (`detect_entities_v2`) and Bedrock (`invoke_model`) calls verified for current API shapes; Anthropic Claude 3 messages-API body format checked
- Every numeric value flowing into DynamoDB traced for Python-float writes (case_record, evidence_summary, update_item recovery)
- S3 keys inspected for leading slashes (none present)
- NetworkX graph construction in `refresh_graph` walked against the detector queries in `run_graph_analytics`
- Module-load evaluated: import surface, client instantiation, unused imports
- Healthcare-specific: PHI logging discipline, synthetic data labeling, BAA-eligible services, encryption for case-outcome labels, patient-ID handling in the graph, LEIE/NPPES/SAM exclusion semantics, CCI/MUE table semantics

---

## Verdict: FAIL

One ERROR finding and five WARNING findings. Per persona policy, ERROR findings automatically mean FAIL, and more than 3 WARNINGs also means FAIL. This recipe lands at FAIL on both criteria.

The ERROR is that `aggregate_flags_to_cases` writes the raw flag dicts (Python floats and all) into the DynamoDB `evidence_summary` attribute. boto3's resource-API serializer raises `TypeError: Float types are not supported. Use Decimal types instead.` the first time a statistical or graph flag (z-score, peer mean/std, isolation score, referral concentration) reaches that put. The teaching example fails before it produces a case for any realistic input. This is the same Decimal-discipline trap the project has been calling out for five chapters; here it bites at the case-write boundary instead of the flag-emit boundary.

The five WARNINGs are: (1) the `OWNERSHIP_CASCADE` graph detector cannot fire because `refresh_graph` never creates organization nodes with `node_type="organization"`; (2) `run_rules_on_claim`'s "Rule 3: LEIE exclusion" comment doesn't match the code, which checks the `UNRESOLVED:` prefix instead; (3) the patient node ID in the graph is the raw patient_id rather than a hash, contradicting the main recipe's pseudocode and PHI rationale; (4) `capture_case_outcome`'s S3 label write uses `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`, silently falling back to the AWS-managed default key (same gap pattern as Chapters 3.1-3.5); (5) `aggregate_flags_to_cases`'s `ConditionExpression="attribute_not_exists(case_id)"` claims to provide retry idempotency but generates a fresh `uuid.uuid4()` on every call, so retries write new cases each time rather than the same one.

Eight NOTEs follow the WARNINGs. The Decimal/PHI hygiene at the edges is otherwise solid: `_to_decimal` is applied at the right boundaries, `_redact_for_logs` keeps PHI out of CloudWatch Logs, the Bedrock prompt is constrained, `needs_human_review: True` is hard-wired on the LLM-assisted documentation review, and the structured outcome taxonomy in `capture_case_outcome` matches the prose's "label derivation is the most important business logic" framing. The pseudocode-to-Python mapping for the nine steps is faithful in shape; the issues are at the type-discipline boundary and at three teaching-fidelity points where the code says one thing and the prose says another.

Fix the ERROR and the five WARNINGs and this becomes a PASS. None of them require restructuring the file.

---

## Findings

### Finding 1: `aggregate_flags_to_cases` writes flag dicts containing Python floats to DynamoDB; the put_item call raises before any case is created

- **Severity:** ERROR
- **Location:** `chapter03.06-python-example.md`, `aggregate_flags_to_cases` (Step 7), specifically the `case_record["evidence_summary"] = flags[:20]` assignment and the subsequent `table.put_item(Item=case_record, ...)` call
- **Description:** The aggregator computes `case_record` and writes it to the case-state table:

  ```python
  case_record = {
      "target_entity_id": entity_id,
      "case_id": case_id,
      "status": "open",
      "severity": overall,
      "exposure_amount": _to_decimal(exposure),
      "num_flags": len(flags),
      "flag_types": sorted(set(f["rule_id"] for f in flags)),
      "evidence_summary": flags[:20],   # top-20 for the case viewer
      ...
  }
  table.put_item(
      Item=case_record,
      ConditionExpression="attribute_not_exists(case_id)",
  )
  ```

  `evidence_summary` is the raw flag-dict list, untouched. The flags emitted by Steps 5 and 6 carry Python floats:

  - `score_provider_statistics` peer z-score flags carry `details.value` (Python float from `provider_features[feature]`), `details.peer_mean` (`float(baseline["mean"])`), `details.peer_std` (`float(baseline["std"])`), and `details.z_score` (`round(z, 2)`, a Python float).
  - `score_isolation_forest` flags carry `details.isolation_score` (`round(float(score), 4)`, a Python float).
  - `run_graph_analytics`'s `REFERRAL_CONCENTRATION` flags carry `details.concentration` (`round(concentration, 3)`, a Python float).

  boto3's resource-API serializer (`boto3.dynamodb.types.TypeSerializer._serialize_n`) explicitly rejects Python `float` for numeric attributes:

  > `Float types are not supported. Use Decimal types instead.`

  The `put_item` call raises this TypeError the first time a statistical or graph flag reaches `evidence_summary`. In the demo, that's any run with `peer_baselines` provided, any run with `isolation_forest_model` provided, and any run with a graph that produces a referral-concentration flag (which is most non-trivial demos). A reader who follows the file top-to-bottom and runs `run_fwa_pipeline` against synthetic SynPUF or Synthea data hits this immediately and walks away with no case in DynamoDB.

  This is the same Decimal-discipline issue the cookbook has been teaching since Chapter 3.1, except the flags here are produced by Python ratio math (counts divided by counts) and sklearn (`round(float(score), 4)`) and never pass back through `_to_decimal` before being persisted. The flag-emit sites in Steps 4 (rules) happen to use only ints, strings, and lists, so a rules-only run does not surface the bug; that's why the demo could appear to work in shallow testing while still being broken for the realistic full-pipeline path.

- **How to fix:** Two options, smallest edit first:

  1. Add a recursive `_floats_to_decimal` helper and apply it at the `case_record` boundary right before the put:

     ```python
     def _floats_to_decimal(obj):
         """Recursively convert Python floats in a dict/list tree to Decimal.

         DynamoDB rejects Python float for numeric attributes. Apply this to
         any structured payload at the put-item boundary so flag dicts
         produced by sklearn or by Python ratio math can be persisted
         without per-call-site Decimal coercion.
         """
         if isinstance(obj, float):
             return Decimal(str(obj))
         if isinstance(obj, dict):
             return {k: _floats_to_decimal(v) for k, v in obj.items()}
         if isinstance(obj, list):
             return [_floats_to_decimal(v) for v in obj]
         return obj

     case_record["evidence_summary"] = _floats_to_decimal(flags[:20])
     table.put_item(Item=_floats_to_decimal(case_record), ...)
     ```

  2. Push `_to_decimal` discipline upstream into the flag-emit sites so every numeric field in every flag dict is already a `Decimal` when it lands in `aggregate_flags_to_cases`. Change `score_provider_statistics`'s `"value": provider_features[feature]` to `"value": _to_decimal(provider_features[feature])`, the same for `peer_mean`, `peer_std`, `z_score`, the `isolation_score`, and `concentration`. This is a larger edit but matches the pattern Chapter 3.5 uses (Decimal at the flag-dict boundary), so it harmonizes the chapter style.

  Option 1 is the minimum fix to make the example run. Option 2 is the more pedagogically consistent fix. Either way, add a one-line comment naming the failure mode: "DynamoDB rejects Python float for numeric attributes; the resource-API serializer raises TypeError at put time. Coerce numeric fields to Decimal at the type boundary."

  As a defensive supplement, add a unit test that constructs a representative `case_record` with a peer-z-score flag and an isolation-score flag, then writes it to DynamoDB Local or moto. The test catches future regressions where someone adds a new flag detector with float fields and forgets to coerce.

---

### Finding 2: `OWNERSHIP_CASCADE` graph detector cannot fire because organization nodes are never created with `node_type="organization"`

- **Severity:** WARNING
- **Location:** `chapter03.06-python-example.md`, `refresh_graph` (Step 3) and `run_graph_analytics`'s `OWNERSHIP_CASCADE` block (Step 6)
- **Description:** The graph constructor adds three node types explicitly:

  ```python
  for original_npi, canonical_id in resolved_entities.items():
      graph.add_node(canonical_id, node_type="provider", npi=original_npi)
  ...
  graph.add_node(claim_node, node_type="claim", ...)
  ...
  graph.add_node(patient_node, node_type="patient")
  ```

  Ownership edges are added without ever calling `add_node` for the parent or child:

  ```python
  for edge in (ownership_edges or []):
      graph.add_edge(edge["parent"], edge["child"], edge_type="owns",
                     percentage=edge.get("percentage"))
  ```

  NetworkX implicitly creates the endpoint nodes when you add an edge to a previously-unseen ID, but those auto-created nodes have no `node_type` attribute. The `OWNERSHIP_CASCADE` detector then filters by exactly that attribute:

  ```python
  owners = [n for n, d in graph.nodes(data=True) if d.get("node_type") == "organization"]
  for owner in owners:
      owned = [t for _, t, d in graph.out_edges(owner, data=True)
               if d.get("edge_type") == "owns"]
      if len(owned) >= 5:
          flags.append({"rule_id": "OWNERSHIP_CASCADE", ...})
  ```

  `owners` is always `[]` regardless of how many ownership edges were passed in, so the loop never enters and no `OWNERSHIP_CASCADE` flag can ever fire. A reader who passes a synthetic ownership-cascade dataset (one owner LLC with five downstream clinics, exactly the textbook collusive-network signature the main recipe spends a page describing) gets zero flags from the detector.

  This is a teaching miss for two reasons. First, the main recipe's "Honest Take" calls ownership cascades and collusive networks the highest-dollar fraud category and explicitly says graph analytics is the only way to catch them. The Python companion includes the detector for that exact pattern and then makes it dead code. Second, the bug is silent: there's no log line, no exception, no flag-count metric showing zero firings. A reader extending the example for their own data won't notice.

- **How to fix:** When iterating ownership edges, add the endpoint nodes with the correct `node_type` and any structural attributes the detector wants (EIN, primary address). Tag organizations explicitly:

  ```python
  for edge in (ownership_edges or []):
      parent_id = edge["parent"]
      child_id = edge["child"]
      # Auto-create endpoint nodes if they don't already exist. Tag them
      # as organizations so the OWNERSHIP_CASCADE detector can find them.
      # In production, the entity-resolution step writes organization
      # nodes during Step 2 alongside providers; this branch is the
      # teaching-example shortcut.
      if parent_id not in graph:
          graph.add_node(parent_id, node_type="organization")
      if child_id not in graph:
          graph.add_node(child_id, node_type="organization")
      graph.add_edge(parent_id, child_id, edge_type="owns",
                     percentage=edge.get("percentage"))
  ```

  Optionally, extend `resolve_providers` (or add a sibling `resolve_organizations` function) to populate organization canonical IDs for the billing tax IDs referenced by claims, then add organization nodes for those in `refresh_graph`. That matches the main recipe's Step 2 pseudocode more closely and gives the OWNERSHIP_CASCADE detector something to find even when no `ownership_edges` argument is supplied.

  Add a synthetic ownership-edge example to the `__main__` walkthrough (one owner, six downstream clinics) so the detector actually fires once per file run; otherwise the reader can't see the flag shape.

---

### Finding 3: `run_rules_on_claim`'s "LEIE exclusion" rule does not check LEIE; the comment and the code disagree

- **Severity:** WARNING
- **Location:** `chapter03.06-python-example.md`, `run_rules_on_claim` (Step 4), the block labeled "Rule 3: LEIE exclusion"
- **Description:** The block opens with a clear claim about what it does:

  ```python
  # Rule 3: LEIE exclusion. Any claim touching a LEIE-excluded provider
  # gets the critical tier. (The exclusion flags were computed in Step 2.)
  for role in ["rendering_provider_npi", "billing_provider_npi",
               "referring_provider_npi", "facility_npi"]:
      npi = canonical_claim.get(role)
      if npi and resolved_entities.get(npi, "").startswith("UNRESOLVED:"):
          flags.append({
              "rule_id": "UNRESOLVED_PROVIDER",
              "claim_id": claim_id,
              "severity": "medium",
              "details": {"role": role, "npi_prefix": npi[:4]},
              "explain": f"Provider role {role} could not be resolved to NPPES.",
          })
  ```

  The comment promises a LEIE-exclusion check that produces critical-severity flags. The code is checking for the `UNRESOLVED:` sentinel from `resolve_providers` and emitting a medium-severity `UNRESOLVED_PROVIDER` flag. These are different rules. The actual LEIE flagging happens elsewhere: `resolve_providers` returns `exclusion_flags` and the pipeline driver does `rule_flags.extend(exclusion_flags)` separately. The exclusion check in this function is misnamed.

  Two consequences. First, a reader following the rule-by-rule walkthrough learns that "LEIE exclusion" looks like an `UNRESOLVED:`-prefix string check, which is incorrect operationally and incorrect compliance-wise (LEIE is the OIG's mandatory and permissive exclusion list, not a provider-resolution failure mode). Second, the prose around the rule emphasizes LEIE-touching claims get "the critical tier"; the actual code emits `severity: "medium"` and a flag with `rule_id: "UNRESOLVED_PROVIDER"`. The severity tier is wrong for the rule the comment names.

  The exclusion check from `resolve_providers` is correct (LEIE matches produce `severity: "critical"`, SAM matches produce `severity: "high"`), so the policy is in the codebase; it's just not where the comment says it is. A reader who copies the `run_rules_on_claim` rule pattern for a new rule library will inherit the mismatch.

- **How to fix:** Three options:

  1. Rewrite the comment to describe what the code actually does. The block is genuinely useful as an "unresolved provider" check (a provider role that fell through entity resolution is a data-quality flag worth surfacing). Rename the comment to "Rule 3: Unresolved provider role" and remove the misleading reference to LEIE.

  2. Move the actual LEIE check inline into `run_rules_on_claim` (replacing or supplementing the unresolved check), so the rule the comment names is the rule the function emits:

     ```python
     # Rule 3: LEIE/SAM exclusion. Any claim touching an excluded provider
     # carries critical (LEIE) or high (SAM) severity. The exclusion-set
     # lookup runs against the in-memory reference data here so the rule
     # is visible in this function rather than fan-in from Step 2.
     for role in ["rendering_provider_npi", "billing_provider_npi",
                  "referring_provider_npi", "facility_npi"]:
         npi = canonical_claim.get(role)
         if npi and npi in external_reference["leie"]:
             flags.append({
                 "rule_id": "LEIE_EXCLUSION",
                 "claim_id": claim_id,
                 "severity": "critical",
                 "details": {"role": role, "npi_prefix": npi[:4],
                             "exclusion_source": "LEIE"},
                 "explain": (
                     f"Claim touches an LEIE-excluded provider in role {role}. "
                     "Payment is recoverable; no claim activity is permitted."
                 ),
             })
         elif npi and npi in external_reference["sam"]:
             ...
     ```

     This requires plumbing `external_reference` (or a slimmed-down exclusion view) into `run_rules_on_claim`. Slightly more wiring; cleaner pedagogy.

  3. Keep the current split (Step 2 emits exclusion flags, Step 4 emits unresolved flags) and rewrite the comment in Step 4 to make the split explicit:

     ```python
     # Rule 3: Unresolved provider role. The actual LEIE/SAM exclusion check
     # ran in Step 2 (resolve_providers returns exclusion_flags); the pipeline
     # driver concatenates those into rule_flags. Here we surface the
     # data-quality flag for any provider role that fell through entity
     # resolution.
     ```

  Option 1 is the smallest edit. Option 2 is the most readable end-to-end. Option 3 keeps the existing architecture but at least the rule is correctly labeled.

---

### Finding 4: Patient nodes use the raw `patient_id` rather than a hash; contradicts the main recipe and the file's own PHI rationale

- **Severity:** WARNING
- **Location:** `chapter03.06-python-example.md`, `refresh_graph` (Step 3)
- **Description:** The Python builds patient nodes directly from the unhashed patient ID:

  ```python
  if claim.get("patient_id"):
      patient_node = f"PATIENT:{claim['patient_id']}"
      graph.add_node(patient_node, node_type="patient")
      graph.add_edge(patient_node, claim_node, edge_type="patient_of",
                     service_date=claim["service_date"])
  ```

  The main recipe's pseudocode for the same step is explicit:

  ```
  // Upsert patient nodes (hashed patient ID, no PHI in graph node properties).
  patient_ids = distinct(c.patient_id for c in new_claims)
  FOR each patient_id in patient_ids:
      Neptune.UpsertVertex(
          label = "Patient",
          id    = hash_patient_id(patient_id),
          ...
      )
  ```

  The pseudocode hashes; the Python does not. The hashing is not cosmetic. The main recipe spends a paragraph in the Architecture section explaining why patient nodes carry only structural attributes (age band, region, acuity band) and use a hashed identifier: the FWA graph crosses provider, payment, and ownership data with patient connections, and an investigator (or a downstream system, or a subpoena response) traversing the graph should see the structural relationship, not a re-identifiable patient pointer. The Honest Take and Gap to Production both reinforce that the patient layer of the graph has a different sensitivity tier than the provider layer.

  The Python companion's own narration agrees with the pseudocode: the graph step's prose says "Patients are a separate node type because the ownership graph does not include them (patient-level privacy separation is important for legal review) but the care graph does." Yet the node ID in the next code block is the raw patient ID. The narration and the code disagree.

  Operational consequence: in a production deployment that swaps NetworkX for Neptune (the file makes the swap explicit as a teaching-to-production migration), the patient node IDs persist in Neptune, in OpenSearch case indices via the subgraph descriptor, and in any S3 subgraph exports referenced by `case_bundle_s3_uri`. A patient ID flowing through three of those stores untransformed gives every downstream consumer of the case bundle direct PHI rather than a structural reference. The legal-privilege isolation the recipe describes is undermined.

- **How to fix:** Add a tiny hashing helper near `_to_decimal` and apply it in `refresh_graph`:

  ```python
  def _hash_patient_id(patient_id: str, salt: bytes = HASH_SALT) -> str:
      """Stable hash for patient identifiers used as graph node IDs.

      Use HMAC-SHA256 with a salt rotated on a documented schedule. The
      salt lives in Secrets Manager and is loaded at module init in
      production; this teaching example uses a static placeholder.
      """
      import hmac
      import hashlib
      return hmac.new(salt, patient_id.encode("utf-8"),
                      hashlib.sha256).hexdigest()[:16]
  ```

  Then change the patient-node line:

  ```python
  if claim.get("patient_id"):
      patient_node = f"PATIENT:{_hash_patient_id(claim['patient_id'])}"
      graph.add_node(patient_node, node_type="patient")
      ...
  ```

  Two things to teach in the comment around the helper: (1) the hash must be stable across runs so the same patient produces the same node ID across batches (which is why a salt rotated on a long cadence is appropriate, not a per-run random salt); (2) the hash is one-way for the FWA pipeline's purposes, but a downstream system that needs to look up the underlying patient (the case management UI surfacing the patient's full record to an investigator with appropriate access) does the reverse lookup through the patient master, not by reversing the hash.

  Same fix applies to any other place patient IDs are used as identifiers. The current code uses unhashed patient IDs only in the graph; the rest of the file passes patient IDs only as DynamoDB keys to the patient-context cache (no graph or case exposure), so the fix is localized.

---

### Finding 5: `aggregate_flags_to_cases` claims retry idempotency via `ConditionExpression` but generates a fresh `uuid.uuid4()` on every call

- **Severity:** WARNING
- **Location:** `chapter03.06-python-example.md`, `aggregate_flags_to_cases` (Step 7), and the corresponding "Idempotency everywhere" entry in the Gap to Production section
- **Description:** The aggregator generates a UUID and writes a case with a no-overwrite condition:

  ```python
  case_id = f"CASE:{uuid.uuid4()}"
  case_record = {...}
  table.put_item(
      Item=case_record,
      ConditionExpression="attribute_not_exists(case_id)",
  )
  ```

  The companion's "Gap to Production" section then teaches:

  > Use DynamoDB `ConditionExpression` with `attribute_not_exists(case_id)` on case writes (treat `ConditionalCheckFailedException` as success);

  The intent is right (Step Functions retry of a transient failure shouldn't double-create a case). The implementation does not deliver it. `uuid.uuid4()` produces a fresh random ID on every call; on retry, the function generates a *different* `case_id`, the `attribute_not_exists` condition is trivially true (no record exists with the new ID), and a duplicate case is written. The condition expression is window dressing.

  Real retry idempotency requires a deterministic case_id derived from inputs that don't change across retries: target entity ID, the rule_ids that fired, the time window the flags cover, or a hash of those. The simplest fix is to use a stable hash of the entity ID and the sorted flag-rule-ids:

  ```python
  case_key_material = f"{entity_id}|{','.join(sorted(set(f['rule_id'] for f in flags)))}"
  case_id = f"CASE:{hashlib.sha256(case_key_material.encode()).hexdigest()[:24]}"
  ```

  This produces the same `case_id` for the same entity and the same flag set, so the retried put hits `attribute_not_exists` and fails closed (which the production code catches and treats as success). Two retries produce one case.

  The current code's failure mode is silent: a retry storm during a transient DynamoDB throttling event creates one case per retry. An investigator opening the priority queue sees N copies of the same case, each with a separate `case_id`, all with the same severity and exposure. The flag-count metric in CloudWatch is inflated by the retry factor. The downstream EventBridge `CaseCreated` event fires once per duplicate, fanning out to the documentation-assist, notification, and audit consumers, which now do their work N times.

  The Gap to Production language that says "treat `ConditionalCheckFailedException` as success" is the right teaching, but the example contradicts it. A reader who reads the Gap section, looks at the code, and concludes "the example does what the prose says" carries a broken pattern into production.

- **How to fix:** Pick a deterministic case_id derivation, document the choice, and update the code and the Gap section together.

  Recommended derivation, adapted from common payment-integrity practice: hash the entity ID, the sorted set of rule_ids that fired, and a coarse time window (e.g., the date or week of detection). Cases that fire on the same entity with the same rules in the same window collapse to a single `case_id`; new flags or a new window produce a new case. Sketch:

  ```python
  def _derive_case_id(entity_id: str, rule_ids: list, window_key: str) -> str:
      """Deterministic case_id so retries collapse to the same record.

      window_key is a coarse bucket like 'year=2026/week=20'. It collapses
      retries within a detection window to a single case while letting a
      week-over-week recurrence open a new case.
      """
      key_material = "|".join([
          entity_id,
          ",".join(sorted(set(rule_ids))),
          window_key,
      ])
      digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
      return f"CASE:{digest[:24]}"
  ```

  And in the call site, catch the conditional-check failure as success rather than letting it bubble:

  ```python
  case_id = _derive_case_id(
      entity_id=entity_id,
      rule_ids=[f["rule_id"] for f in flags],
      window_key=datetime.now(timezone.utc).strftime("year=%Y/week=%V"),
  )
  ...
  try:
      table.put_item(Item=case_record,
                     ConditionExpression="attribute_not_exists(case_id)")
  except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
      # Retry path: the case is already there. Treat as success.
      logger.info("case already exists; idempotent retry",
                  extra={"case_id": case_id, "entity_id": entity_id})
  ```

  Then the Gap to Production section's "treat `ConditionalCheckFailedException` as success" matches what the example actually does, and a reader sees the full retry pattern instead of half of it.

---

### Finding 6: `capture_case_outcome`'s S3 label write sets SSE-KMS without specifying a customer-managed KMS key

- **Severity:** WARNING
- **Location:** `chapter03.06-python-example.md`, `capture_case_outcome` (Step 9), the `s3_client.put_object` call for the label record
- **Description:** The outcome handler writes a label row to S3 with server-side encryption requested but no key ARN:

  ```python
  s3_client.put_object(
      Bucket=CASE_OUTCOMES_BUCKET,
      Key=label_key,
      Body=json.dumps(label_record).encode("utf-8"),
      ServerSideEncryption="aws:kms",
  )
  ```

  When `ServerSideEncryption="aws:kms"` is set without `SSEKMSKeyId`, S3 encrypts with the AWS-managed default key (the `aws/s3` alias), not a customer-managed key. For PHI-adjacent workloads the difference matters operationally and contractually: customer-managed keys let you rotate on your schedule, scope grants per-bucket, audit `kms:Decrypt` per principal via CloudTrail, and disable a key to revoke access immediately. The AWS-managed default cannot be disabled, scoped with a custom key policy, or revoked.

  The label payloads written here are sensitive. Each row carries `entity_id` (the canonical provider ID), `outcome_raw` (CONFIRMED, CLEARED, REFERRED_TO_REGULATOR, etc.), `recovery_amount`, and `case_id`. Aggregated across cases, this label store reconstructs the SIU's adjudication history per provider. A subpoena, a discovery request in a False Claims Act suit, or an internal compliance audit will all target this exact dataset. The main recipe's Prerequisites table is explicit: "Customer-managed KMS keys on every PHI-bearing store" and the Gap to Production section in the Python file repeats it: "Every data-at-rest store ... is encrypted with customer-managed KMS keys scoped by role." The Python example does not demonstrate the pattern the prose requires.

  This is the same gap pattern as Chapters 3.1, 3.2, 3.3, 3.4, and 3.5 (each had a Finding 2 on the missing `SSEKMSKeyId`). At this point in Chapter 3 a reader has seen the omission five times in a row; if it appears again unaddressed, the implicit teaching is that the customer-managed-key requirement in the Prerequisites table is aspirational rather than operational.

- **How to fix:** Add a key-ARN constant near the top of the Configuration block and pass it through:

  ```python
  CASE_OUTCOMES_CMK_ARN = "arn:aws:kms:REGION:ACCOUNT:key/..."

  s3_client.put_object(
      Bucket=CASE_OUTCOMES_BUCKET,
      Key=label_key,
      Body=json.dumps(label_record).encode("utf-8"),
      ServerSideEncryption="aws:kms",
      SSEKMSKeyId=CASE_OUTCOMES_CMK_ARN,
  )
  ```

  Document the constant in the Configuration block: "Customer-managed KMS key ARN for the case-outcomes bucket. Separate key per bucket so rotation and grants can be scoped independently. The labels-bucket key gets stricter access policy than the general-claims-lake key because labels carry adjudication outcomes that are subject to discovery in FCA proceedings." The same pattern would apply to any future write to the SUBGRAPH_ARTIFACTS_BUCKET (subgraph descriptors carry provider-patient relationships and are equally sensitive); the file does not currently write to that bucket, but the precedent matters.

  Optionally, factor the SSE arguments into a small helper used at every put-object site:

  ```python
  def _phi_sse_args(key_arn: str) -> dict:
      return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": key_arn}
  ```

  Used as `s3_client.put_object(Bucket=..., Key=..., Body=..., **_phi_sse_args(CASE_OUTCOMES_CMK_ARN))`. The helper makes the SSE pairing harder to forget.

  Given this is the sixth recipe in Chapter 3 with the same omission, it's worth a coordinated fix across all six recipes plus a one-line addition to the project STYLE-GUIDE.md so future Python companions inherit the pattern rather than re-litigating it.

---

### Finding 7: `import io` and `import math` are unused

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, the imports block at the top of the Configuration section
- **Description:** Lines 50 and 53 import `io` and `math`. Neither is used anywhere in the file. The Chapter 3.5 companion used both (`io.BytesIO` for joblib model loading from S3, `math.isnan` / `math.isinf` for the `_to_decimal` non-finite guard); this companion strips down `_to_decimal` (no NaN check) and does not load the Isolation Forest from S3 (the model is passed in as a function argument, not joblib-loaded), so neither import is exercised.

  Teaching impact is small (a reader running `pylint` or `flake8` will see the unused-import warnings; a reader scrolling past the imports will spend a moment wondering where they're used). The pattern of carrying imports across a copy from a sibling file is worth fixing because it suggests the cleanup pass was rushed.

- **How to fix:** Remove the two lines, or use them. Recommended cleanup is to remove them because the companion explicitly does not include the Isolation Forest persistence path or the NaN-guarded Decimal coercion that would justify them.

---

### Finding 8: Module logger has no handler configured; `logger.info` / `logger.warning` calls drop silently in the `__main__` run

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, Configuration block
- **Description:** Same pattern flagged in Chapters 3.1 through 3.5. Without `logging.basicConfig(...)` or an explicit handler, structured log calls (`logger.info("claim normalized", ...)`, `logger.info("graph refreshed", ...)`, `logger.warning("npi not found in nppes", ...)`, `logger.info("documentation review draft generated", ...)`) do not reach the console when the file runs as `__main__`. The `print("[1/9] normalizing ...")` lines in `run_fwa_pipeline` keep narration visible, but the structured logs (which are the more useful artifacts for a learner tracing a run through normalize → resolve → graph → rules → stats → graph-analytics → aggregate) disappear. In Lambda this is not an issue (Lambda configures a root handler); the `__main__` block is the first way most readers exercise the code.

- **How to fix:** Add one line near the top of the Configuration block:

  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

  Document as "visible when running this file directly; Lambda configures its own handler and this becomes a no-op there."

---

### Finding 9: `update_item` "Version attribute for optimistic locking" comment promises a guarantee the code does not provide

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, `capture_case_outcome` (Step 9), the `table.update_item` call and its preceding comment
- **Description:** The comment frames the version counter as optimistic locking:

  ```python
  # Version attribute for optimistic locking. EventBridge delivers at
  # least once, so the same outcome event may arrive multiple times.
  # Increment the version atomically and fail-closed if the case no
  # longer exists.
  table.update_item(
      ...
      UpdateExpression=(
          "SET ... ADD version :one"
      ),
      ExpressionAttributeValues={..., ":one": 1},
      ConditionExpression="attribute_exists(case_id)",
  )
  ```

  The `ADD version :one` increments atomically, which is fine. The `ConditionExpression="attribute_exists(case_id)"` is fail-closed-on-missing-case, which is also fine. But neither of those is optimistic locking. Real OCC requires reading the current version, then conditioning the update on `version = :expected_version`; the update succeeds only if no other writer has incremented in the meantime. This code reads no version, conditions only on existence, and would happily stomp on a concurrent investigator's outcome write if EventBridge delivered two outcome events for the same case.

  In practice for this specific function the consequence is small: outcome capture is meant to be terminal, and a duplicate-delivery scenario produces the same outcome write twice (idempotent in effect). The version counter is useful only as an audit trail for how many writes the case received. But the comment teaches a pattern the code does not implement, and a reader who copies the snippet for a different update path (where two writers genuinely contend) will inherit the gap.

- **How to fix:** Two options:

  1. Rewrite the comment to describe what the code actually does:

     ```python
     # Atomic write counter for audit. The version attribute increments
     # on every outcome write so retroactive review can tell whether the
     # outcome was overwritten and how many times. ConditionExpression
     # ensures we never write to a case that has been deleted.
     # EventBridge at-least-once delivery is fine here because outcome
     # writes are terminal and idempotent; if a real concurrent-writer
     # scenario emerges, switch to read-modify-write with a version
     # check on the ConditionExpression.
     ```

  2. Implement actual optimistic locking by reading the current version first, conditioning the update on `version = :expected_version`, and treating `ConditionalCheckFailedException` as a retry signal. This is more code than the teaching example warrants.

  Option 1 is the right edit. The point is to keep the comment honest.

---

### Finding 10: `SUPPRESSION_REGISTRY_TABLE` is defined in the Configuration block but never referenced in the code

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, Configuration block (line ~109) and the IAM permissions list in the Setup section
- **Description:** The Setup section's IAM checklist promises permissions on the suppression registry: "`dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem` on the `resolved-entities`, `case-state`, and `suppression-registry` tables." The Configuration block defines `SUPPRESSION_REGISTRY_TABLE = "suppression-registry"`. The Setup section even spells out the schema: "`suppression-registry` is keyed on `entity_id` (partition) and `rule_id` (sort) with TTL on `expires_at`." But the code never reads from or writes to the table. The constant is a configuration ghost.

  The main recipe's `on_case_outcome` pseudocode shows where the suppression registry plugs in:

  ```
  IF outcome_event.outcome_type == "closed_no_action" AND outcome_event.suppression_requested:
      SuppressionStore.Upsert(
          entity_id       = case.target_entity_id,
          rule_ids        = outcome_event.suppressed_rules,
          expires_at      = NOW() + outcome_event.suppression_window,
          ...
      )
  ```

  And the rules engine and statistical layer are supposed to consult the suppression store before emitting flags ("Suppression rules are politically sensitive ... but those suppressions must be auditable. Suppression rules that are set and forgotten become blind spots; expire them by default."). Neither side of the loop is wired in the Python.

  Teaching impact: a reader sees the constant, sees the IAM permission, sees the prose mention of suppression rules with TTL, and looks for the implementation. Finding nothing, they're not sure whether suppression is meant to be exercised in the example or deliberately deferred. Either is a defensible design decision; the file should make the choice explicit.

- **How to fix:** Two options:

  1. Remove the constant and the IAM permission line, and add a sentence to the "Heads up" preamble explaining the omission: "Suppression-rule lookups (the `suppression-registry` DynamoDB table the main recipe describes) are not implemented in this teaching example. The suppression workflow needs the case management UI to capture `suppression_requested` and `suppression_window` from the investigator at outcome-capture time, plus a per-flag pre-emit check in the rules and statistical layers; both are out of scope for the sketchpad version."

  2. Implement a minimal suppression check: in `run_rules_on_claim` and `score_provider_statistics`, look up `(entity_id, rule_id)` against `suppression-registry` before appending the flag, and skip if a non-expired suppression exists. Then in `capture_case_outcome`, when the outcome is `CLEARED` and a `suppression_window` parameter is supplied, write the suppression rows. This is more code, but it gives the reader the full operational pattern.

  Option 1 is the smaller edit. Option 2 turns the example into a more complete teaching artifact.

---

### Finding 11: `_cusum` uses the series mean as the reference value rather than a target mean; the chart is self-referential and less sensitive than the textbook CUSUM it appears to be

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, `_cusum` helper (Step 5)
- **Description:** The CUSUM implementation:

  ```python
  def _cusum(series, k, h):
      """Classic one-sided upper CUSUM."""
      mean = np.mean(series)
      std = np.std(series) or 1.0
      c = 0.0
      for i, x in enumerate(series):
          c = max(0, c + (x - mean - k * std))
          if c > h * std:
              return i
      return None
  ```

  Two issues. First, classical CUSUM uses a fixed reference value (μ₀, often the in-control process mean estimated from a clean baseline window) and detects deviation from that reference. The Python uses `np.mean(series)` as the reference, which is the mean of the *same series being checked*. If the series has an upward shift, the reference mean already incorporates the shifted portion, suppressing the cumulative deviation the chart is meant to detect.

  Second, even with the series mean as reference, the function returns "the first index where cumulative positive deviation exceeds h standard deviations" — but the loop iterates in order, so the change-point reporting is structurally biased toward earlier in the series. A real provider who shifts in month 9 of a 12-month series will get flagged at month 9 (correctly), but a provider whose entire series is high-variance noise will fire at month 1 (where the cumulative max happens to cross first), which is misleading.

  The teaching example doesn't exercise CUSUM in `__main__` (the `history_*` features default to empty lists, and the CUSUM function is only called when the history is at least 6 entries deep). A reader extending the example with real history data will hit both biases.

- **How to fix:** Two minimum changes:

  1. Compute the reference mean from a baseline window (e.g., the first half of the series, or an explicit `baseline_mean` argument) rather than the full series:

     ```python
     def _cusum(series, k, h, baseline_window=None):
         baseline = series[:baseline_window] if baseline_window else series
         mean = np.mean(baseline)
         std = np.std(baseline) or 1.0
         ...
     ```

     Document the parameter: "baseline_window slices the early portion of the series as the in-control reference. None uses the full series, which is structurally less sensitive but appropriate for a teaching example with no obvious baseline boundary."

  2. Add a one-line comment naming the simplification so a reader extending to production knows what to revisit: "Production CUSUM uses an explicit baseline window or a target mean from the SIU's process spec, not the series mean. See Recipe 3.3 for the same pattern in billing-code-drift detection."

  Both edits keep the function shape compatible with the existing call sites.

---

### Finding 12: `json.dumps(..., default=str)` in the SNS publish silently stringifies any Decimal that escapes upstream coercion

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, `aggregate_flags_to_cases` (Step 7), the SNS publish for priority cases
- **Description:** The SNS publish uses `default=str` as a JSON serialization fallback:

  ```python
  sns.publish(
      TopicArn=INVESTIGATOR_NOTIFICATION_TOPIC_ARN,
      Subject=f"[{overall.upper()}] FWA Case Opened: {entity_id}",
      Message=json.dumps({
          "case_id": case_id,
          "entity_id": entity_id,
          "exposure": str(exposure),
          "flag_types": case_record["flag_types"],
      }, default=str),
  )
  ```

  Same pattern flagged in Chapter 2.10, Chapter 3.2, Chapter 3.4, and Chapter 3.5. `default=str` is a catch-all that stringifies `Decimal`, `datetime`, and `UUID` without complaint. With `exposure` already pre-stringified via `str(exposure)`, the immediate payload is fine, but a future addition to the dict (someone adds `"created_at": datetime.now(timezone.utc)`, or `"exposure_amount": exposure` without the `str()` wrap) silently emits a string where a number would be more useful for the downstream consumer. Investigator-notification consumers parse the JSON; an inconsistent type for `exposure` across notifications produces silent breakage.

- **How to fix:** Either drop `default=str` and rely on explicit pre-coercion (preferred), or move to a single custom encoder used everywhere JSON is serialized:

  ```python
  class _PHIJsonEncoder(json.JSONEncoder):
      def default(self, o):
          if isinstance(o, Decimal):
              return float(o)
          if isinstance(o, datetime):
              return o.isoformat()
          return super().default(o)

  Message=json.dumps({...}, cls=_PHIJsonEncoder),
  ```

  The custom-encoder pattern scales across files and makes type coercion explicit; the project would benefit from a shared encoder in the style guide so all chapter Python companions inherit it.

---

### Finding 13: `capture_case_outcome` does not validate the `outcome_event` payload before applying side effects

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, `capture_case_outcome` (Step 9)
- **Description:** The handler validates the `outcome` argument against the enum but doesn't validate that the call was supplied an entity_id that maps to an actual case, doesn't validate `recovery_amount` is non-negative, and doesn't sanity-check `case_id` format:

  ```python
  def capture_case_outcome(case_id, entity_id, outcome, recovery_amount=None, notes=None):
      valid_outcomes = {...}
      if outcome not in valid_outcomes:
          raise ValueError(f"invalid outcome: {outcome}")

      table = dynamodb.Table(CASE_STATE_TABLE)
      table.update_item(
          Key={"target_entity_id": entity_id, "case_id": case_id},
          ...
          ConditionExpression="attribute_exists(case_id)",
      )
  ```

  The `ConditionExpression` does provide the safety net for a missing case (the update fails closed). But a `recovery_amount` of `-50000.00` (data-entry error) writes a negative recovery, which propagates into the label record, into S3, and into the retraining label store. A `case_id` of `"None"` or `""` reaches DynamoDB before failing. A reader who builds a UI on top of this function inherits the gap.

  Same shape as Chapter 3.5 Finding 8. Worth a one-line validator that catches the obvious bad inputs before the side effects:

  ```python
  if recovery_amount is not None and recovery_amount < 0:
      raise ValueError(f"recovery_amount must be non-negative; got {recovery_amount}")
  if not case_id or not case_id.startswith("CASE:"):
      raise ValueError(f"case_id must be a CASE: prefixed identifier; got {case_id!r}")
  if not entity_id:
      raise ValueError("entity_id is required")
  ```

- **How to fix:** Add the validators above at the top of the function, before any DynamoDB or S3 call.

---

### Finding 14: Label key in `capture_case_outcome` lacks date partitioning; inconsistent with Chapter 3.5's pattern

- **Severity:** NOTE
- **Location:** `chapter03.06-python-example.md`, `capture_case_outcome` (Step 9), the `label_key` construction
- **Description:** The label is written to:

  ```python
  label_key = f"labels/{case_id}.json"
  ```

  Chapter 3.5's equivalent helper (`_write_label_to_s3`) uses date partitioning:

  ```python
  key = f"labels/year={dt.year:04d}/month={dt.month:02d}/day={dt.day:02d}/{uuid.uuid4().hex}.json"
  ```

  The teaching impact is moderate. Date-partitioned keys let downstream Athena, Glue, and Spark jobs prune at the partition level when reading the labels for retraining, which matters at scale (a year of labels is hundreds of thousands of files; without partitioning, Athena scans them all). The non-partitioned scheme also makes lifecycle policies (deletion or transition to Glacier after N years) harder to express because the `LastModified` time of the object is the only available filter rather than a partition the policy can scope to.

  More subtly, a flat namespace makes investigator workflow tooling harder. An auditor wants to "show me all labels written in the last 30 days for FCA window review"; with date partitioning that's a partition predicate; without it that's a full bucket scan. The retraining job mentioned in the Gap to Production section is the canonical consumer; it benefits directly from the partition.

- **How to fix:** Match Chapter 3.5's pattern:

  ```python
  decision_dt = datetime.now(timezone.utc)
  label_key = (
      f"labels/year={decision_dt.year:04d}/"
      f"month={decision_dt.month:02d}/"
      f"day={decision_dt.day:02d}/"
      f"{case_id.replace(':', '-')}.json"
  )
  ```

  Document the partitioning choice with a one-line comment: "Date-partitioned key so Athena and Glue can prune at the partition level when reading the labels for retraining; case_id uniqueness inside the partition is preserved by the deterministic case_id." If the deterministic case_id from Finding 5 is adopted, the leaf can stay as `case_id` directly without the UUID flourish.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function(s) | Consistent? |
|-----------------|---------------------|---------------------|-------------|
| Step 1 | `normalize_claim(raw_claim)` | `normalize_claim` + `_to_decimal` + `_redact_for_logs` | Yes. Service-date normalization, line-item harmonization with modifier list canonicalization, billed-amount-total fallback to sum-of-lines, ingestion-timestamp stamping, log redaction all present. The `claim_total_paid` field from the pseudocode is exposed as `paid_amount`. Provenance via `source_system` matches |
| Step 2 | `resolve_providers(claims_batch, external_provider_data)` | `resolve_providers` + `_load_external_reference_data` | Mostly. Per-NPI cache lookup against DynamoDB, fallback to NPPES, `UNRESOLVED:` sentinel for misses, separate exclusion-flag emission. The pseudocode includes ownership cascade resolution (state filings, Sunshine Act) which is documented as a stub here |
| Step 3 | `refresh_graph(since_timestamp)` | `refresh_graph` | Partial. Provider, claim, and patient nodes added. Patient nodes use unhashed IDs (Finding 4). Ownership endpoint nodes are not tagged as organizations (Finding 2). Co-location edges from the pseudocode are not implemented; the prose calls out NetworkX-as-Neptune-substitute for teaching, so the omission is acceptable for that scope |
| Step 4 | `run_rules_on_claim(canonical_claim, resolved_entities)` | `run_rules_on_claim` | Yes. CCI edits (mutually-exclusive code pairs), MUE (units-per-day caps), provider exclusion check (misnamed; Finding 3), post-mortem billing, DME oxygen medical-necessity gate. Severity tiering matches recipe |
| Step 5 | `score_provider_statistics(provider_id, evaluation_window)` | `score_provider_statistics` + `_safe_zscore` + `_cusum` + `train_isolation_forest` + `score_isolation_forest` | Mostly. Peer z-scores on E&M and modifier rates, self-history CUSUM with the textbook simplification (Finding 11), Isolation Forest training-and-scoring split. Severity escalation at \|z\| ≥ 5 |
| Step 6 | `run_graph_analytics()` | `run_graph_analytics` | Partial. Louvain community detection (gated on `python-louvain` import), referral-concentration query, ownership-cascade detector that cannot fire (Finding 2), no embedding-similarity-search path (deferred to Variations in the main recipe). The prose calls graph the "secret sauce" so the dead detector is a teaching loss |
| Step 7 | `on_flag_event(flag)` (per-flag aggregator) | `aggregate_flags_to_cases` (batched) + `_overall_severity` + `_determine_routing` + `_emit_metric` | Mostly. The Python aggregates by entity in a single batch rather than streaming flag-by-flag; the case-record shape, severity folding, and routing policy match. Idempotency via `attribute_not_exists(case_id)` does not actually deduplicate due to fresh UUID per call (Finding 5). Float fields in `evidence_summary` break the put (Finding 1) |
| Step 8 | `assist_documentation_review(case_id, medical_records_uri)` | `assist_documentation_review` | Yes. Comprehend Medical entity extraction at ≥0.8 confidence, Bedrock Claude 3 messages-API invocation with low temperature for structured output, JSON parse with brace-extraction fallback, `needs_human_review: True` hard-wired |
| Step 9 | `on_case_outcome(case_id, outcome_event)` | `capture_case_outcome` | Mostly. Outcome enum validation, atomic version increment via `ADD version :one`, label row written to S3, EventBridge publish, metric emission. Optimistic-locking framing in the comment is misleading (Finding 9). S3 write missing customer-managed KMS key (Finding 6). No payload validation beyond the enum (Finding 13). Suppression-rule path from the pseudocode is not implemented (Finding 10) |

The `run_fwa_pipeline` driver wires Steps 1-7 in sequence with print-based narration; Steps 8 and 9 are documented as event-triggered (LLM review fires from `CaseCreated`; outcome capture from the investigator UI) and shown as explicit calls for clarity. The structural mapping matches the main recipe's architectural diagram.

---

## AWS SDK Accuracy

### DynamoDB
- `dynamodb.resource("dynamodb", ...)`, `Table.get_item`, `Table.put_item`, `Table.update_item`: current API shapes
- `Table.get_item(Key={"canonical_id": ...})` in `resolve_providers`: correct partition-key GetItem
- `Table.put_item(Item={...}, ConditionExpression=...)` in `aggregate_flags_to_cases`: correct shape; the condition expression itself is correct boto3 syntax even though it does not deliver the idempotency the comment claims (Finding 5)
- `Table.update_item(Key={partition, sort}, UpdateExpression="SET ... ADD ...", ExpressionAttributeNames=..., ExpressionAttributeValues=..., ConditionExpression=...)` in `capture_case_outcome`: current API shape, mixed SET and ADD usage is correct, `#status` reserved-word alias is correct
- `attribute_not_exists(case_id)` and `attribute_exists(case_id)` are valid DynamoDB condition functions on a sort-key attribute
- Decimal discipline at `:recovery` parameter is correct (`_to_decimal(recovery_amount or 0)`); however `:one` is `1` (Python int), which DynamoDB accepts as a number. Pass
- The float-in-evidence_summary issue (Finding 1) is at the Item level, not the call shape

### S3
- `s3_client.put_object(Bucket=..., Key=..., Body=..., ServerSideEncryption=...)`: parameter names correct
- `Body=json.dumps(label_record).encode("utf-8")`: correct encoding (UTF-8 bytes)
- Key path `f"labels/{case_id}.json"`: no leading slash, no `s3://` scheme leakage. Date partitioning would help (Finding 14)
- Subgraph artifacts URI in `case_record["case_bundle_s3_uri"]` is constructed as `f"s3://{SUBGRAPH_ARTIFACTS_BUCKET}/cases/{case_id}/bundle.json"`; this is a stored reference (the actual subgraph upload path is out of scope for the example), so the `s3://` scheme is appropriate here
- `SSEKMSKeyId` missing on the write site (Finding 6)

### EventBridge
- `eventbridge.put_events(Entries=[{...}])`: current API shape at two call sites (`aggregate_flags_to_cases` for `CaseCreated`, `capture_case_outcome` for `CaseClosed`)
- Entry fields `Source`, `DetailType`, `Detail`, `EventBusName`: correct
- `Detail` is JSON-serialized via `json.dumps(...)` with explicit fields. The `default=str` fallback in the SNS publish is the only place stringification can leak (Finding 12); EventBridge call sites are clean
- Detail-type names (`CaseCreated`, `CaseClosed`) are simple enum-style identifiers. Could encode severity in the detail-type for downstream EventBridge filtering as Chapter 3.5 does (`LabOutlier.{routing}`), but this is an optional pattern, not an SDK accuracy issue

### SNS
- `sns.publish(TopicArn=..., Subject=..., Message=...)`: correct
- `Message` is a JSON-encoded string; `Subject` is a templated string with the case severity and entity ID. The entity ID is a canonical provider ID (NPI-derived); not PHI but PHI-adjacent. Subject lines route through the SNS subscription chain unencrypted by default, so a real deployment may want to redact further. Within scope for a teaching example
- Failure handling on `sns.publish` is not present; same posture as Chapter 3.5

### CloudWatch
- `cloudwatch.put_metric_data(Namespace="FWA/Detection", MetricData=[{MetricName, Value, Unit, Timestamp}])`: current shape
- `Value=float(value)`: correct (CloudWatch expects float for metric values)
- No try/except around `put_metric_data`; a metric-emission failure raises into the caller. Same posture as Chapter 3.5; worth a defensive wrapper in production but not a teaching-example issue

### Comprehend Medical
- `comprehend_medical.detect_entities_v2(Text=text)`: current API parameter name (`Text`, capital T) and method name (`detect_entities_v2`, the V2 API)
- Response shape parsed as `entities_response.get("Entities", [])` with each entity's `Score`, `Category`, `Type`, `Text` fields: matches the actual API response
- The `InferICD10CM` and `InferRxNorm` calls referenced in the pseudocode are not implemented in the Python; documentation review uses only entity extraction. Acceptable simplification

### Bedrock
- `bedrock_runtime.invoke_model(modelId=BEDROCK_MODEL_ID, body=json.dumps({...}))`: current API shape
- `BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"`: a real Bedrock model ID for Claude 3 Sonnet. HIPAA-eligible under the BAA (verify in the Bedrock console for the deployment region)
- Body fields `anthropic_version: "bedrock-2023-05-31"`, `max_tokens: 2048`, `temperature: 0.1`, `messages: [{"role": "user", "content": prompt}]`: matches the Anthropic Claude 3 messages-API request shape on Bedrock
- Response parsing `bedrock_response["body"].read()` -> `json.loads(...)["content"][0]["text"]`: matches the response shape
- The brace-extraction fallback for malformed JSON in the model output is a reasonable defensive pattern

### Boto3 Config
- `Config(retries={"max_attempts": 5, "mode": "adaptive"})`: current parameter names, appropriate for bursty FWA workload (monthly graph refresh plus daily scoring is naturally bursty across DynamoDB, OpenSearch, Feature Store, Comprehend Medical, and Bedrock). Rationale documented in the Configuration block

### SageMaker Feature Store Runtime
- The client is instantiated (`featurestore_runtime = boto3.client("sagemaker-featurestore-runtime", ...)`) but never called. The Feature Store role appears in the IAM permissions list and the prose mentions Feature Store as the production backing for `peer_baselines`, but the example passes `peer_baselines` as a function argument. Acceptable simplification; would benefit from a one-line comment in the Configuration block naming the deferral

---

## DynamoDB Decimal Check

- `_to_decimal` helper routes through `Decimal(str(value)).quantize(Decimal(precision))`, avoiding binary-precision drift. Default precision is `"0.01"`; callers can override
- `HIGH_SEVERITY_EXPOSURE = Decimal("100000.00")` and `CRITICAL_EXPOSURE = Decimal("500000.00")` are Decimal constants; `PEER_ZSCORE_FLAG`, `PEER_ZSCORE_HIGH_SEVERITY`, `CUSUM_H`, `CUSUM_K`, `ISOLATION_FOREST_CONTAMINATION`, `REFERRAL_CONCENTRATION_FLAG` are Python floats (these never cross the DynamoDB boundary; they feed into `_safe_zscore`, `_cusum`, sklearn, and Counter math whose results pass through `_to_decimal` only if they reach the put-item boundary, which they do not in `evidence_summary` for Finding 1)
- Canonical claim `billed_amount` per line and `billed_amount_total` and `paid_amount` are `_to_decimal`-wrapped at normalization time. Pass at the normalization boundary
- `aggregate_flags_to_cases`'s `case_record`:
  - `"exposure_amount": _to_decimal(exposure)`: pass
  - `"num_flags": len(flags)`: int, pass
  - `"flag_types": sorted(set(...))`: list of strings, pass
  - `"evidence_summary": flags[:20]`: contains float fields (Finding 1). FAIL
- `capture_case_outcome`'s update_item:
  - `:recovery`: `_to_decimal(recovery_amount or 0)`, pass
  - `:one`: `1` (int), pass; DynamoDB accepts int for ADD on a number attribute
  - All other expression values are strings or already strings
- The label record written to S3 in Step 9:
  - `"recovery_amount": str(_to_decimal(recovery_amount or 0))`: pass (string in JSON; downstream consumers parse to float or Decimal as needed)
  - Other fields are strings, ints, or booleans
- The `__main__` driver (`run_fwa_pipeline` plus the supporting helpers) does not seed DynamoDB tables directly with example data, so there are no module-load Decimal coercion paths to verify. The IsolationForest training, the per-provider feature build, and the graph construction all operate on Python primitives that don't need to be Decimals (they don't cross the DynamoDB boundary)

Result: the `_to_decimal` helper is correctly applied at the case-write boundary for the top-level numeric fields. The failure is at the nested level inside `evidence_summary`, where flag dicts containing float values flow through unchanged. The fix proposed in Finding 1 (recursive coercion at the put-item boundary) closes the gap without restructuring the flag-emit sites.

---

## S3 Key Check

Keys inspected:

- `f"labels/{case_id}.json"` (`capture_case_outcome`)
- `f"s3://{SUBGRAPH_ARTIFACTS_BUCKET}/cases/{case_id}/bundle.json"` (stored reference in `case_record["case_bundle_s3_uri"]`; the actual put is not in this file)

All keys use forward-slash partitioning, no leading slashes, no reserved characters. The labels key lacks date partitioning (Finding 14). The subgraph URI uses the `s3://` scheme correctly because it's stored as a reference value, not used as a key in a put-object call.

Pass for the key format itself; partitioning improvement is a NOTE.

---

## Healthcare-Specific Requirements

- **PHI logging discipline.** The `_redact_for_logs` helper produces a structural summary (claim_id, rendering provider NPI, service date, line count) without billed amounts, patient identifiers, or diagnosis codes. The Configuration-block comment names the rule explicitly: "Claim, provider, and patient data is PHI-adjacent (an NPI plus a date range plus a patient population is re-identifying even without names). Log structural metadata only. Never log full claim bodies, patient identifiers, ownership chains, or raw Comprehend Medical output in application logs." Inline `logger.info` calls respect the rule, e.g., `logger.warning("npi not found in nppes", extra={"npi_prefix": npi[:4]})` truncates to four digits. NPIs are public, so the truncation is conservative; it doesn't hurt. Pass.
- **Synthetic data labeling.** The Setup section's "All example claim, provider, patient, and ownership data is synthetic" paragraph names every category of identifier (NPIs, EINs, patient IDs, claim IDs, entity IDs) and points to SynPUF, Synthea, public LEIE, public SAM, and public Open Payments as the appropriate development data sources. The CPT/HCPCS codes used (99213/99214/99215, 80307, E1390) are explicitly noted as real codes for teaching realism. Pass.
- **BAA / HIPAA context.** All services used (DynamoDB, S3, EventBridge, SNS, CloudWatch, Comprehend Medical, Bedrock, SageMaker Feature Store Runtime) are HIPAA-eligible under the AWS BAA. The main recipe's Prerequisites table covers this; the Python file's Setup heads-up section is consistent. Pass.
- **Patient ID handling in the graph.** Pseudocode hashes; Python does not (Finding 4). This is the one healthcare-specific item that fails the consistency check.
- **LLM-assisted review is a draft, not a decision.** `assist_documentation_review` returns a `finding` dict with `needs_human_review: True` hard-wired. The system prompt to Bedrock explicitly constrains the model: "You are not making a clinical judgment. You are identifying whether the documentation, as written, contains the elements that each code requires." Output is asked to be a JSON object with structured keys. The two design points are present and named: structured output with no free-form clinical opinion, and `needs_human_review` always true. Pass.
- **Bedrock input and output handling.** The `prompt` variable contains the full clinical documentation text that is passed to Bedrock; the success-path log line emits only `case_id`, `supported_count`, and `unsupported_count`, not the prompt or the response. The `temperature=0.1` setting reduces hallucination risk for structured-output prompts. Pass.
- **Comprehend Medical is PHI processing.** Comprehend Medical is HIPAA-eligible by default. The example invokes `detect_entities_v2` and stores only the high-confidence entity summary (`category`, `type`, `text`) without persisting the raw response. For a teaching example this is acceptable; production retains the response under the same KMS keys and retention policy as the source documentation per the recipe's Prerequisites. Pass.
- **Encryption at rest.** S3 `put_object` for the label record sets `ServerSideEncryption="aws:kms"` without `SSEKMSKeyId` (Finding 6). DynamoDB encryption configuration is out of the Python code's scope (table-level configuration). Pass modulo Finding 6.
- **Exclusion-list semantics.** The example correctly identifies LEIE (mandatory and permissive OIG exclusions) and SAM (federal-contracting exclusions) as separate sources. The severity assignment (LEIE → critical, SAM → high) matches the regulatory weight of each list. The placement of the exclusion check in `resolve_providers` rather than `run_rules_on_claim` (with the documented mismatch in Finding 3) is operationally correct because exclusion is an entity-level fact that should propagate to every claim touching the entity, but the teaching presentation is weakened by the Rule 3 mislabeling.
- **CCI and MUE table semantics.** The illustrative tables (`CCI_EDIT_PAIRS` with two pairs, `MUE_THRESHOLDS` with three codes) are explicitly called out as illustrative with the expected production source: "Production loads the full CMS NCCI PTP edit file (tens of thousands of pairs) and refreshes quarterly." The pseudocode's references to `cci_table_version` and `mue_table.get(...)` are simplified to direct dict lookups in Python; acceptable for teaching, with the version-tracking responsibility clearly named in the prose.
- **Subgroup and fairness monitoring.** The main recipe's Gap to Production section explicitly names subgroup monitoring as a continuous operational requirement. The Python companion documents the gap at the bottom: "If the pipeline disproportionately flags providers serving Medicaid or rural populations, or if confirmation rates vary systematically across specialty, that is a signal of bias in the features or the thresholds and warrants investigation before scale-out." The companion does not implement subgroup gating in the trained-model path; consistent with Chapters 3.3-3.5. Pass in architecture, NOTE on completeness.
- **Retention and legal hold.** Main recipe's Prerequisites section covers FCA-driven retention (up to 10 years) and the "investigation records may be retained indefinitely under specific programs" framing. The Python companion's Gap to Production reinforces this with concrete numbers: "Retain for the HIPAA baseline (6 years) plus any anti-fraud retention requirements (often 7-10 years in some jurisdictions). Use S3 Object Lock in COMPLIANCE mode for the case-outcomes and subgraph-artifacts buckets in production." Pass; production enforces this at bucket-config time, not in this code.
- **Legal-privilege isolation.** The Setup section's heads-up names the constraint: "Legal privilege is not modeled here. In production, depending on the SIU's organizational structure, the case store and subgraph exports may live in an AWS account isolated from general analytics, with access controlled by general counsel. This example keeps everything in one notional account so the code is readable." Pass for naming the gap.
- **Referral packaging to OIG/CMS/state MFCUs.** The Setup heads-up names this as out of scope: "Referral packaging to OIG/CMS/state MFCUs is out of scope. When a confirmed case is referred to a regulator, the payload is a structured data package that meets the receiving agency's specification..." The Gap to Production section repeats: "Build this as a distinct workflow gated by dual approval; do not put the CaseReferred consumer directly on the workflow bus without an approval step." Pass for naming the gap and the dual-approval gate.

---

## Comment Quality

Comments consistently explain *why*, not just *what*. High-value examples:

- "All numeric values must be Decimal going into DynamoDB. DynamoDB rejects Python `float` for numeric attributes. A dollar exposure of `287450.00` becomes `Decimal(\"287450.00\")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For a fraud pipeline the precision discipline matters: a dollar exposure stored as `287449.9999999` from float drift, compared against a `100000` high-severity cut, produces the correct routing today and might not tomorrow when the threshold moves." Names the DynamoDB gotcha and ties it to a specific operational failure mode (the high-severity routing cut). The comment is accurate; the file's failure to follow it through into `evidence_summary` (Finding 1) is what makes the bug surprising.
- "Adaptive retry mode handles throttling across DynamoDB, OpenSearch, SageMaker Feature Store, Comprehend Medical, and Bedrock with exponential backoff and jitter. Monthly graph refresh plus daily scoring is naturally bursty, and adaptive mode keeps burst windows from cascading into retry storms. Setting a higher max on Bedrock specifically would be reasonable, since throttles there are model-capacity bound." Concrete operational guidance.
- "These are teaching defaults. Real deployments tune them with SIU leadership against a labeled case stream and revisit them quarterly. A threshold too tight drops real cases; too loose buries investigators under noise." On the threshold block: names the operational tradeoff and the cadence of revisit.
- "Real CPT/HCPCS code identifiers used illustratively. A production deployment loads these from the published CMS files and refreshes quarterly. Code set drift (ICD-10-CM annual updates in October, CPT updates in January, HCPCS quarterly) will silently invalidate rules that reference retired codes." Names a real failure mode (silent rule invalidation) and the calendar of code-set updates.
- "The LEIE exclusion check is the simplest, highest-value rule in the entire pipeline. If a provider is on the HHS-OIG exclusion list, the provider cannot be paid by any federal program, period. A single month of paid claims to an excluded provider is a False Claims Act exposure in the millions. Treat the LEIE check as a pre-payment gate, not a post-payment detector, whenever the pipeline allows it." Tied to the rule's regulatory weight; this kind of context is what differentiates the cookbook from a stack of API examples.
- "The graph is the secret sauce. Rules catch individual claims and statistics catch outlier individuals; the graph catches coordinated schemes where each actor looks ordinary alone but the network between them is impossible under legitimate practice. In production this runs on Amazon Neptune. For teaching, we use NetworkX in-process." Frames the graph layer as the differentiator; the Finding 2 dead-detector then erodes the framing.
- "The Isolation Forest is intentionally the second-line detector. The z-scores are interpretable (explain to an investigator why a provider was flagged), while the Isolation Forest is opaque (a combination of features). Use the z-scores for the case summary and the Isolation Forest as a tie-breaker and a cold-start mechanism for schemes that do not show up on any single z-score." Names the explainability tradeoff and where each fits.
- "A case is one investigable unit of work for an SIU investigator. It bundles every flag touching a single entity (provider, organization, patient, or network) with ranked evidence, dollar exposure, and routing metadata. Without this aggregation step the investigator sees a flat list of fifty flags and has no idea which ones relate; with it they see a case that says 'this provider has three statistical flags, two rules flags, and one graph flag, with $X exposure across Y claims.'" Frames the case as the operational atom; the dead-`ConditionExpression` (Finding 5) then weakens the framing's correctness.
- "Two critical design points. First, `needs_human_review` is always True; do not let a review pipeline quietly start auto-closing cases on LLM output. Second, the prompt constrains the model to a specific structured output and explicitly does not ask for a clinical judgment. The model is a documentation-element checker; the credentialed reviewer is the judge." Names the LLM-as-draft-not-decider rule explicitly.
- "The label derivation (CONFIRMED/PENDING_PAYER_RECOVERY/REFERRED_TO_REGULATOR as positive; CLEARED/DUPLICATE as negative) is the single most important piece of business logic in the retraining loop. If the SIU changes its closure codes, the label mapping has to change with them. Audit the label distribution monthly and ask the lead investigator whether a random sample of labeled cases matches their expectation." Names the audit cadence and the operational signal worth tracking.
- The Heads-up block is a clean enumeration of every production gap (no real X12 parsing, no real Neptune, no Neptune ML GNN, no CLIA-compliant referral packaging, no investigator UI, no legal-privilege isolation, no provider appeals workflow). Sets reader expectations correctly.

The narration around the function definitions consistently references the pseudocode step ("Step 1: Normalize a Raw Claim", "Step 4: Run the Rules Layer", etc.) which makes navigation between the recipe and the companion easy.

---

## Logical Flow

The file reads cleanly top-to-bottom:

1. Heads-up block (scope, no-real-parser caveats, NetworkX-not-Neptune framing, DynamoDB schema reminder, Decimal discipline, synthetic-data label, legal-privilege gap, LLM-as-draft-not-decider, referral packaging out of scope)
2. Configuration and constants (retry config, clients, resource names, thresholds, code families, CCI pairs, MUE thresholds)
3. Step 1: `_to_decimal` + `_redact_for_logs` + `normalize_claim`
4. Step 2: `_load_external_reference_data` + `resolve_providers`
5. Step 3: `refresh_graph`
6. Step 4: `run_rules_on_claim`
7. Step 5: `_safe_zscore` + `_cusum` + `score_provider_statistics` + `train_isolation_forest` + `score_isolation_forest`
8. Step 6: `run_graph_analytics`
9. Step 7: `_overall_severity` + `_determine_routing` + `aggregate_flags_to_cases` + `_emit_metric`
10. Step 8: `assist_documentation_review`
11. Step 9: `capture_case_outcome`
12. Full pipeline: `run_fwa_pipeline` + `_build_provider_features` + `_compute_exposure`
13. Gap to Production

The progression matches the conceptual flow of the main recipe (ingest → resolve → graph → rules → stats → graph-analytics → aggregate → LLM review → outcome capture). The pseudocode-to-Python mapping is one-to-one at the function level. Helper functions are introduced just before they're used. The prose between code blocks consistently calls out what's simplified, what's deferred to production, and what's a deliberate teaching simplification.

---

## What Is Clean

- `_to_decimal` helper applied at the right boundaries (line items, billed-amount-total, paid amount, exposure, recovery amount). The failure mode in Finding 1 is at a *nested* boundary (flag dicts inside `evidence_summary`) rather than at the top-level boundary, which the helper handles correctly
- `_redact_for_logs` emits only structural metadata. NPIs are truncated to 4 chars in the warning log; patient IDs and full claim bodies never reach the application logs
- The Bedrock prompt is constrained to a structured-output JSON contract with explicit "you are not making a clinical judgment" guardrail. `temperature=0.1` is appropriate for structured-output prompts
- The Anthropic Claude 3 messages-API request shape is correct (`anthropic_version`, `max_tokens`, `temperature`, `messages` with `role`/`content`)
- `needs_human_review: True` is hard-wired on the LLM-assisted documentation review and the comment names the rule explicitly
- The structured outcome taxonomy in `capture_case_outcome` (`CONFIRMED`, `CLEARED`, `PENDING_PAYER_RECOVERY`, `REFERRED_TO_REGULATOR`, `DUPLICATE_OF_EARLIER_CASE`) maps to the main recipe's prose. The label-derivation logic (`CONFIRMED` plus `PENDING_PAYER_RECOVERY` plus `REFERRED_TO_REGULATOR` as positive; `CLEARED` and `DUPLICATE` as negative) is named in the comment as the single most important piece of business logic in the retraining loop
- Atomic version increment via `ADD version :one` is correct DynamoDB syntax; the comment around it (Finding 9) overstates what the increment provides, but the increment itself is sound
- EventBridge `Detail` payloads are JSON-serialized with explicit field names rather than dump-and-pray; only the SNS publish uses the `default=str` fallback (Finding 12)
- `_compute_exposure` uses `Decimal("0")` accumulator and Decimal-typed arithmetic; no float drift in exposure computation
- Comments tie thresholds to operational tradeoffs: "PEER_ZSCORE_FLAG = 3.0 ... A threshold too tight drops real cases; too loose buries investigators under noise."
- The `_build_provider_features` helper is an honest minimal implementation with the gap clearly named: "Real implementation uses a Glue job reading the full claims warehouse plus the patient master; this inline version is enough to show the shape."
- Adaptive retry config is documented with the right rationale ("Monthly graph refresh plus daily scoring is naturally bursty")
- The Heads-up section calls out every production gap before the code starts; the Gap to Production section at the end repeats the production-readiness checklist with concrete actionable items
- The pseudocode-to-Python step-by-step section headers (`## Step 1: Normalize a Raw Claim`, `## Step 2: Resolve Providers and Organizations`, ...) make cross-file navigation easy and reinforce the structural mapping

---

## Closing Assessment

The teaching content is substantial and the architectural fidelity to the main recipe is high. The nine pseudocode steps map cleanly onto Python functions, the Decimal helper applies correctly at the top-level boundaries, the LLM-assisted review is constrained properly, and the structured outcome taxonomy in Step 9 is the right operational atom for an SIU label store. The Heads-up section and the Gap to Production section together do honest work naming the production gaps a reader needs to understand.

The ERROR is a Decimal-discipline failure at a nested boundary: `evidence_summary` carries the raw flag dicts, and the flag dicts produced by Steps 5 and 6 contain Python floats (z-scores, peer means/stds, isolation scores, referral concentrations) that boto3's DynamoDB resource serializer rejects at put time. The fix is mechanical (recursive coercion at the put-item boundary, or per-field coercion at the flag-emit sites), but the example breaks for any realistic full-pipeline run as written. This is the kind of bug that doesn't surface in a rules-only test because the rule flags happen to use only ints, strings, and lists. A reader who runs the demo with peer baselines configured (the documented full-pipeline path) gets a TypeError before they see a case.

The five WARNINGs cluster around teaching-fidelity gaps where the prose says one thing and the code does another: a graph detector that can never fire (Finding 2), a rule comment that mislabels its own check (Finding 3), a patient ID that's hashed in pseudocode but not in Python (Finding 4), an idempotency claim that the UUID-per-call invalidates (Finding 5), and the SSE-KMS-without-key pattern that Chapters 3.1 through 3.5 also missed (Finding 6). Each is a small fix individually; together they pull the recipe's teaching arc out of alignment with its operational claims. Finding 4 in particular matters for the FWA domain because patient-graph privacy isolation is the one piece of architecture the legal-privilege framing in the Honest Take rests on.

The eight NOTEs are editorial or hygiene items (unused imports, missing logger handler, optimistic-locking comment overstates the guarantee, unused `SUPPRESSION_REGISTRY_TABLE` constant, CUSUM uses series mean as reference, `default=str` JSON fallback, missing event-payload validation, label key lacks date partitioning). Most mirror gaps already flagged in earlier Chapter 3 reviews. They don't block the example; they would harden it.

With Finding 1 fixed and the five WARNINGs addressed, this becomes a clean PASS. The graph-analytics framing is genuinely the differentiator for FWA detection (the main recipe spends a page explaining why), so the Finding 2 fix matters disproportionately to the recipe's teaching arc — making the OWNERSHIP_CASCADE detector actually fire on a small synthetic ownership cascade in `__main__` would be the single strongest improvement. The Decimal fix in Finding 1 is the gating fix because without it the example doesn't run. The remaining WARNINGs and the NOTEs are editorial refinements that would bring the file's teaching quality up to the bar Chapter 3.5 set.

---

## Re-review Checklist

When this review is addressed, a re-reviewer should verify:

1. **(ERROR)** `aggregate_flags_to_cases` does not raise `TypeError: Float types are not supported` when called with a flag list that includes peer-z-score flags and graph referral-concentration flags. Either a recursive `_floats_to_decimal` helper coerces at the put-item boundary, or every flag-emit site in Steps 5 and 6 produces Decimal-typed numeric fields. A representative integration test exercises the full pipeline against synthetic data with all four detector layers active and confirms the case is written.
2. **(WARNING)** `refresh_graph` adds organization nodes with `node_type="organization"` for every endpoint of an ownership edge (or via a dedicated entity-resolution branch for organizations), and the `__main__` example seeds at least one ownership cascade so the `OWNERSHIP_CASCADE` detector actually fires once per file run.
3. **(WARNING)** `run_rules_on_claim`'s "Rule 3" block is either renamed/recommented to describe the unresolved-provider check it actually performs, or rewritten to inline the LEIE/SAM exclusion check the comment promises. Either way, the rule the comment names is the rule the function emits.
4. **(WARNING)** Patient nodes in `refresh_graph` use a hashed identifier (HMAC-SHA256 with a salted constant or a salt-from-Secrets-Manager wrapper). The hash is stable across runs and the comment explains why the salt is rotated on a long cadence rather than per-run.
5. **(WARNING)** `aggregate_flags_to_cases` derives `case_id` deterministically from entity ID, sorted rule IDs, and a coarse time window; the `ConditionExpression="attribute_not_exists(case_id)"` actually deduplicates retries, and `ConditionalCheckFailedException` is caught and treated as success with a corresponding info log.
6. **(WARNING)** `capture_case_outcome`'s S3 put_object passes `SSEKMSKeyId` with a documented customer-managed-key constant. The label record encrypts under a customer-managed key per the recipe's Prerequisites table.
7. **(NOTE)** `import io` and `import math` are removed from the imports block (or actually used).
8. **(NOTE)** `logging.basicConfig(level=logging.INFO, format=...)` is added near the top of the Configuration block so structured logs are visible during direct `__main__` runs.
9. **(NOTE)** The "Version attribute for optimistic locking" comment in `capture_case_outcome` is rewritten to describe the audit-counter behavior the code actually implements, or the code switches to true read-modify-write OCC with a `version = :expected_version` ConditionExpression.
10. **(NOTE)** The `SUPPRESSION_REGISTRY_TABLE` constant and the corresponding IAM permission are either removed (with the omission explained in the Heads-up) or wired into a minimal suppression-check call in the rules and statistical layers.
11. **(NOTE)** `_cusum` either takes an explicit baseline-window argument or carries a one-line comment naming the simplification (series mean as reference) and pointing to Recipe 3.3 for the production pattern.
12. **(NOTE)** The SNS publish drops `default=str` and relies on explicit pre-coercion (or the project adopts a shared `_PHIJsonEncoder` class used everywhere JSON is serialized).
13. **(NOTE)** `capture_case_outcome` validates `recovery_amount >= 0`, `case_id` startswith `"CASE:"`, and `entity_id` is non-empty before any DynamoDB or S3 side effect.
14. **(NOTE)** The label key in `capture_case_outcome` uses date partitioning (`labels/year=.../month=.../day=.../{case_id}.json`) so retraining and audit jobs can prune at the partition level.
