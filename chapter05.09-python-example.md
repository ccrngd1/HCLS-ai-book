# Recipe 5.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.9. It shows one way you could translate the national-scale federated patient-matching pattern (the participant-side of a TEFCA QHIN integration) into working Python. The demo uses a `MockQHINFederationRouter` standing in for the participant's QHIN's cross-network routing layer, several `MockParticipant` instances that each operate their own local MPI and respond to federated queries, a `MockSecretsCustody` standing in for AWS Secrets Manager and KMS-backed signing keys, a `MockConsentStore` standing in for the institutional consent-management workflow, a `MockJurisdictionalOverlays` standing in for the per-state and per-record-type policy-overlay engine (post-Dobbs reproductive-health-care state laws, 42 CFR Part 2 substance-use-treatment record handling, gender-affirming-care state-law overlays), an in-memory event bus standing in for Amazon EventBridge, in-memory queues standing in for the dispute-review and governance-evolution queues, and small helpers for the audit-log archive and CloudWatch-style metrics. It is not production-ready. There is no real QHIN integration (no real Sequoia Project RCE handshake, no real Common-Agreement-compliant authentication, no real QTF-format messages, no real IHE XCPD or XCA, no real FHIR Patient $match), no real cross-account exchange or PrivateLink, no real mTLS or signed-request validation, no Step Functions orchestration, no real DynamoDB or Aurora wiring, no SageMaker calibration loop, no Glue jobs, no information-blocking-exception engine, and no IAM, KMS, VPC, WAF, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a TEFCA-participant pipeline that respects the inbound-query-validation discipline, the cross-network-tolerance dual-calibration discipline, the sensitivity-overlay-per-hop discipline, the federation-routing-aware response-consolidation discipline, the per-hop-attribution audit posture, the use-case-specific-disclosure-form discipline, and the patient-mediated-attribution discipline this recipe demands. It is not something you would point at a live QHIN on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: handle the inbound federated patient-discovery query under the QHIN-signed authentication and the originating-attribution-chain validation; run the local matcher against the local MPI under the cross-network tolerance calibrated separately from the internal-application tolerance; apply the per-record-type sensitivity overlay and the per-jurisdiction overlay rules to the candidate set before disclosure; originate an outbound federated patient-discovery query from a local user or patient with the appropriate exchange-purpose authorization context; consume the federated-discovery responses asynchronously and consolidate them into a federated-resolution view; and handle the document-query and retrieval flow for selected candidates with per-document attribution. Plus the cross-cutting invalidation pipeline that consumes credential rotations, governance changes, consent withdrawals, and cross-recipe events from recipes 5.1 / 5.7 / 5.8. The synthetic patients and demographics in the demo are fictional; the names, DOBs, addresses, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install [`requests`](https://requests.readthedocs.io/) for the HTTPS calls into the QHIN's cross-network router (production typically runs over mTLS with cryptographic-signed request envelopes), [`cryptography`](https://cryptography.io/) for the asymmetric-signing primitives (production uses HSM-backed signing through CloudHSM or KMS rather than in-process keys), [`fhir.resources`](https://github.com/nazrulworld/fhir.resources) for the FHIR Patient `$match` and Bulk FHIR message construction (the QTF specifies both IHE-based and FHIR-based formats), an IHE XCPD-and-XCA client library for the IHE-based exchange path (no single dominant Python library exists; commercial QHIN integrations typically use Java or .NET reference implementations), [Splink](https://github.com/moj-analytical-services/splink) or [`recordlinkage`](https://github.com/J535D165/recordlinkage) for the local matcher's Fellegi-Sunter probabilistic-combiner core (the same machinery used in recipes 5.1, 5.4, 5.5, 5.6, 5.7), [`jellyfish`](https://github.com/jamesturk/jellyfish) for the approximate string matching the local matcher consumes, [`usaddress`](https://github.com/datamade/usaddress) for the USPS-style address standardization that the QTF requires for cross-network demographic-feature payloads, and a Spark client (`pyspark`) for the population-scale batch-matching variants. The demo replaces all of these with small mocks so the focus stays on the inbound-validation, cross-network-matching, sensitivity-overlay, outbound-query, response-consolidation, and document-retrieval logic rather than on the QHIN-integration plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem`, `dynamodb:TransactWriteItems` on the `federation-attribution`, `audit-event-log`, `jurisdictional-overlay-config`, `consent-state`, and `participant-authorized-qhins` tables
- `s3:PutObject` on the document-store bucket and the audit-archive bucket (Object Lock in Compliance mode), `s3:GetObject` on the document-store bucket for the document-retrieval handler's read path
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the dispute-review queue and the governance-evolution queue
- `events:PutEvents` on the federation-events bus
- `cloudwatch:PutMetricData` for the per-source query rate, per-source response latency, per-cohort match-rate disparity, dispute-resolution-backlog, and capacity-reservation-utilization metrics
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the federation-attribution table, the audit-event-log table, the document-store bucket, and the audit-archive bucket
- `secretsmanager:GetSecretValue` on the QHIN-credentials and signing-key secrets pinned to the current rotation version
- `kms:Sign` (or the equivalent CloudHSM operation) on the participant's signing-key version active for outbound query and response signing. Critically, the outbound-query-formulator role gets permissions on *only* the signing-key version active for the cycle, not any prior or future version
- `cognito-idp:AdminGetUser` and the patient-portal IdP-specific permissions on patient-mediated flows
- For the document-retrieval orchestration: `states:StartExecution` and `states:DescribeExecution` on the document-query-orchestrator Step Functions state machine

Scope each Lambda's IAM role and each Step Functions execution role to the specific resource ARNs they touch. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The inbound-query-handler Lambda has read-only access to the local MPI; mutations to the local MPI are explicitly out of scope for the cross-network handler. The outbound-query-formulator Lambda has signing-credential access through the per-rotation Secrets Manager secret; the credential is rotated on the framework-specified cadence. The patient-portal Cognito-authenticated flow has a separate IAM context that distinguishes patient-mediated queries from staff-initiated queries in the audit log.

A few things worth knowing upfront:

- **The QHIN-signed request envelope is the authentication root-of-trust.** Every inbound query carries a request signature produced by the participant's QHIN under the QHIN's current signing-key version. The signature is verified against the QHIN's known public-signing-key version (with the prior version retained during the rotation window). A failed signature validation is a hard reject, not a soft warning; mis-signed queries are dropped and audit-logged with the rejection reason. Production QHINs publish their signing-key versions through a coordinated key-distribution mechanism; the demo's `MockQHINFederationRouter` returns a static public key for readability.
- **The cross-network matching tolerance is calibrated separately from the internal tolerance.** The internal matcher (the local MPI used by the institution's own clinical applications) is calibrated for the institution's internal use cases. The cross-network matcher (the same matcher running against cross-network queries) is calibrated for federation use, which typically demands higher recall and accepts more false positives. Re-using the internal calibration produces silent under-matching: the federation's queries that the institution should respond to with a candidate are silently dropped because the internal tolerance was tighter than the federation expected. The demo's `CROSS_NETWORK_TOLERANCE_BY_PURPOSE` table illustrates the per-use-case tolerances; production calibrates against opt-in pilot data and the QHIN's published expectations.
- **The sensitivity overlay is per-record-type and per-jurisdiction.** A candidate that the local matcher scored as a high-confidence match may still be suppressed at disclosure time because the patient's residence jurisdiction's overlay rules prohibit the disclosure for the requesting jurisdiction's authorization scope. The overlay rules are versioned and per-jurisdiction; the participant's overlay-rule engine consults the patient's residence jurisdiction, the requesting participant's jurisdiction, the use case's authorization scope, and the record-type sensitivity classification to produce a per-candidate disclosure decision. Skip the overlay step and you disclose records the applicable jurisdictional rule would have suppressed, which is a regulatory violation.
- **The opaque record token decouples the federation-visible identifier from the local record identifier.** Each candidate the responder discloses carries an opaque token (a per-cycle pseudonym) that the originating requester can present for a follow-up document-query operation, but the responder retains the local mapping from the opaque token to the actual local record identifier under its own access controls. The cross-network exchange never carries the local record identifier; production deployments that leak the local identifier through the federation create a privacy and operational-coupling concern that the framework explicitly avoids.
- **Federated responses arrive asynchronously with varying latencies.** The response-consolidation logic listens against a federation handle and consumes responses as they arrive. The originating user's response-time tolerance is typically shorter than the longest-tail response, so the consolidation step presents partial results when the deadline expires and explicitly indicates to the user what fraction of the federation has responded. Skip the partial-result handling and the user sees "no results found" when in fact the user is seeing "the fastest responders found nothing in the response window."
- **Per-hop attribution is the audit substrate.** Every cross-network candidate carries the attribution chain back to the source: the originating user, the originating sub-participant, the originating QHIN, the routing path, the responding sub-participant, the responding source organization. The local audit captures the participant's portion of the attribution chain; the federated audit-reconstruction process can join the per-participant audits across QHINs for dispute resolution. The audit's data model has to accommodate the full attribution chain at the design stage; bolting it on after the fact is operationally expensive.
- **Information-blocking compliance is an architectural concern.** A query the local matcher cannot resolve confidently in the response window has to be either responded to with a "no-confident-match" indication or escalated to a slower-tier review process. Silent drops are operationally non-compliant under the 21st Century Cures Act information-blocking rule. The demo's response-consolidation step illustrates the partial-response indicator; production extends to an explicit no-confident-match envelope and an exception-code envelope for rule-defined exceptions.
- **DynamoDB rejects Python `float`.** Every match score, similarity score, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.6 / 5.7 / 5.8; the same `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Lambdas, the QHIN integration, the cross-account exchange, the SQS-driven worker pattern, and the Cognito patient-portal IdP into a single Python file for readability.** In production the inbound-query-handler, the local matcher, the sensitivity-overlay applicator, the outbound-query-formulator, the response-consolidator, the document-retrieval handler, the dispute handler, the governance-evolution handler, and the QHIN-credential-rotation coordinator are separate Lambdas (and Step Functions) running in separate AWS accounts under cross-account access policies, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the QHIN credentials, the cross-network tolerance per use case, the per-jurisdiction overlay-rule identifiers, the response-window timeouts, and the per-feature weights for the local matcher are what you would change between environments.

```python
import hashlib
import hmac
import json
import logging
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The TEFCA gateway operates on
# heavily PHI-adjacent data: the demographic-feature payload of
# inbound queries, the candidate-record envelopes, the
# sensitivity-overlay decisions, the per-document attribution
# all carry information that should not leak through logs. Log
# structural metadata only (query_id, cycle_id, attribution-
# chain summary, decision band, exchange purpose), never the
# actual demographic values, never the candidate disclosable
# features, never the document contents.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, S3, SQS, Step Functions, and Secrets Manager. The
# inbound TEFCA gateway has a strict response-window expectation
# (the QHIN's framework specifies the response-time floor, with
# longer responses subject to information-blocking compliance
# concerns), so transient throttling on a downstream service
# should not silently expand the response window. Step Functions
# Catch states distinguish retriable infrastructure failures
# from terminal logic failures and route terminal failures to
# DLQs for human investigation.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
s3_client          = boto3.client("s3",          region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
sqs_client         = boto3.client("sqs",         region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events",      region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch",  region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
secrets_client     = boto3.client("secretsmanager", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
kms_client         = boto3.client("kms",         region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
sfn_client         = boto3.client("stepfunctions", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
FEDERATION_ATTRIBUTION_TABLE   = "federation-attribution"
AUDIT_EVENT_LOG_TABLE          = "audit-event-log"
JURISDICTIONAL_OVERLAY_TABLE   = "jurisdictional-overlay-config"
CONSENT_STATE_TABLE            = "consent-state"
PARTICIPANT_AUTH_QHINS_TABLE   = "participant-authorized-qhins"
DOCUMENT_STORE_BUCKET          = "tefca-document-store"
AUDIT_ARCHIVE_BUCKET           = "tefca-audit-archive"
DISPUTE_QUEUE_URL              = "https://sqs.us-east-1.amazonaws.com/000000000000/tefca-dispute-queue"
GOVERNANCE_QUEUE_URL           = "https://sqs.us-east-1.amazonaws.com/000000000000/tefca-governance-queue"
TEFCA_EVENT_BUS_NAME           = "tefca-events-bus"
DOCUMENT_QUERY_STATE_MACHINE   = "tefca-document-query-orchestrator"
QHIN_CREDENTIALS_SECRET_ID     = "tefca/qhin-credentials/active"
PARTICIPANT_SIGNING_KEY_SECRET = "tefca/participant-signing-key/active"
CLOUDWATCH_NAMESPACE           = "TEFCA/NationalScalePatientMatching"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("FEDERATION_ATTRIBUTION_TABLE",   FEDERATION_ATTRIBUTION_TABLE),
    ("AUDIT_EVENT_LOG_TABLE",          AUDIT_EVENT_LOG_TABLE),
    ("JURISDICTIONAL_OVERLAY_TABLE",   JURISDICTIONAL_OVERLAY_TABLE),
    ("CONSENT_STATE_TABLE",            CONSENT_STATE_TABLE),
    ("PARTICIPANT_AUTH_QHINS_TABLE",   PARTICIPANT_AUTH_QHINS_TABLE),
    ("DOCUMENT_STORE_BUCKET",          DOCUMENT_STORE_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",           AUDIT_ARCHIVE_BUCKET),
    ("DISPUTE_QUEUE_URL",              DISPUTE_QUEUE_URL),
    ("GOVERNANCE_QUEUE_URL",           GOVERNANCE_QUEUE_URL),
    ("TEFCA_EVENT_BUS_NAME",           TEFCA_EVENT_BUS_NAME),
    ("DOCUMENT_QUERY_STATE_MACHINE",   DOCUMENT_QUERY_STATE_MACHINE),
    ("QHIN_CREDENTIALS_SECRET_ID",     QHIN_CREDENTIALS_SECRET_ID),
    ("PARTICIPANT_SIGNING_KEY_SECRET", PARTICIPANT_SIGNING_KEY_SECRET),
    ("CLOUDWATCH_NAMESPACE",           CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every query and every response carries the matcher-config
# version, the cross-network-tolerance version, and the
# overlay-rules version active at decision time. This is how a
# future audit reconstructs which calibration was active when a
# particular query was handled.
MATCHER_CONFIG_VERSION              = "tefca-matcher-v3.2.1"
CROSS_NETWORK_TOLERANCE_VERSION     = "tefca-tolerance-v2.1.0"
OVERLAY_RULES_VERSION               = "tefca-overlay-v1.4.7"
PARTICIPANT_ID                      = "participant-academic-medical-center-richmond"
PARTICIPANT_QHIN_ID                 = "qhin-example-eastern-network"
PARTICIPANT_JURISDICTION            = "state-of-virginia"

# --- Authorized exchange purposes ---
# The participant's authorization scope. The participant's QHIN
# Participant Agreement specifies which exchange purposes the
# participant is authorized to operate under. Inbound queries
# under unauthorized purposes are rejected at the gateway.
PARTICIPANT_AUTHORIZED_EXCHANGE_PURPOSES = {
    "treatment",
    "payment",
    "healthcare_operations",
    "individual_access_services",
    "public_health",
}

# --- Authorized QHINs ---
# The participant honors only attribution chains from QHINs
# the participant has reciprocal exchange relationships with.
# In production this is loaded from the participant's
# QHIN-relationship configuration; the demo uses a static set.
PARTICIPANT_AUTHORIZED_QHINS = {
    "qhin-example-eastern-network",
    "qhin-example-national-network",
    "qhin-example-western-network",
}

# --- Cross-network matching tolerance per exchange purpose ---
# Calibrated SEPARATELY from the internal-application matcher's
# thresholds in recipe 5.1. The cross-network tolerance is
# typically higher-recall (lower acceptance threshold) than the
# internal tolerance because the federation expects the
# participant to surface plausible matches that the originating
# user can disambiguate at the candidate-presentation step.
# Treatment is the default; individual access services has the
# highest precision (because the patient is being shown her own
# records and a wrong-record disclosure is a privacy event);
# public health has the highest recall (because the analytics
# can tolerate false positives at the cohort level).
CROSS_NETWORK_TOLERANCE_BY_PURPOSE = {
    "treatment": {
        "candidate_acceptance_threshold": Decimal("0.55"),
        "high_confidence_threshold":      Decimal("0.85"),
        "max_candidate_count":            10,
    },
    "payment": {
        "candidate_acceptance_threshold": Decimal("0.65"),
        "high_confidence_threshold":      Decimal("0.88"),
        "max_candidate_count":            5,
    },
    "healthcare_operations": {
        "candidate_acceptance_threshold": Decimal("0.65"),
        "high_confidence_threshold":      Decimal("0.88"),
        "max_candidate_count":            5,
    },
    "individual_access_services": {
        "candidate_acceptance_threshold": Decimal("0.85"),
        "high_confidence_threshold":      Decimal("0.92"),
        "max_candidate_count":            3,
    },
    "public_health": {
        "candidate_acceptance_threshold": Decimal("0.50"),
        "high_confidence_threshold":      Decimal("0.80"),
        "max_candidate_count":            20,
    },
}

# --- Per-feature weights for the local matcher ---
# Same Fellegi-Sunter probabilistic-record-linkage core as
# recipes 5.1 / 5.5. The weights reflect the relative
# discriminating power of each feature for cross-network use.
# DOB carries strong weight because it's the most stable
# discriminating feature across organizations; SSN-last-4 is
# weighted but often missing in the federation's payloads (the
# QTF specifies SSN handling carefully because of disclosure
# concerns).
FEATURE_WEIGHTS = {
    "given_name":   Decimal("0.18"),
    "family_name":  Decimal("0.22"),
    "dob":          Decimal("0.25"),
    "address_line": Decimal("0.10"),
    "zip_code":     Decimal("0.05"),
    "phone":        Decimal("0.10"),
    "ssn_last_4":   Decimal("0.10"),
}

# --- Response-window expectations ---
# The QTF specifies response-time floors. Treatment queries
# typically expect responses within seconds; payment and
# operations queries within minutes; population-scale public-
# health queries can tolerate longer windows. The participant's
# infrastructure is provisioned to meet the floor for the
# dominant exchange purpose.
RESPONSE_WINDOW_BY_PURPOSE_SECONDS = {
    "treatment":                  30,
    "payment":                   120,
    "healthcare_operations":     120,
    "individual_access_services": 60,
    "public_health":             300,
}

# --- Cohort axes for stratified-accuracy monitoring ---
# Same pattern as recipes 5.1 / 5.5 / 5.7 / 5.8. The privacy-
# sensitive cohort axes (sex_or_gender, name_tradition) are
# computed locally and emitted only as hashed dimensions on
# CloudWatch metrics for cohort-disparity monitoring; the raw
# axis values do not flow through cross-network responses.
COHORT_AXES = ["geographic_region", "age_decade",
               "sex_or_gender", "name_tradition"]

# --- Default sensitivity-flag classifications ---
# Used by the sensitivity-overlay applicator. These are
# classifications the local MPI carries on its records;
# production extends with additional record-type taxonomies
# specific to the institution's clinical and operational
# context.
SENSITIVITY_FLAGS = {
    "part_2_substance_use_treatment",
    "reproductive_health_care",
    "gender_affirming_care",
    "mental_health_state_specific",
    "hiv_genetic_information",
    "juvenile_state_specific",
    "witness_protection",
}
```

---

## Helpers

Same family of small helpers used throughout chapter 5. The `_to_decimal`, `_serialize_for_dynamodb`, and `_canonical_name` helpers are the load-bearing ones. The TEFCA-specific helpers (`_sign_payload`, `_verify_signature`, `_build_attribution_chain`, `_summarize_payload_for_audit`) handle the signature-and-attribution discipline that the framework requires.

```python
def _to_decimal(value) -> Decimal:
    """Coerce numeric input into Decimal for DynamoDB."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local
    time. Cross-QHIN audit reconstruction joins logs from
    multiple participants whose servers are in different time
    zones; UTC is the only sane lingua franca."""
    return datetime.now(timezone.utc).isoformat()

def _strip_diacritics(s: str) -> str:
    """Strip combining diacritical marks for cross-participant
    canonicalization. Critical for cross-network matching where
    one participant's EHR may have stripped accents on input
    while another participant's preserved them; if the
    canonicalization differs, the cross-network matcher silently
    misses matches that should have succeeded."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _canonical_name(*parts) -> str:
    """Normalize a name to canonical lowercase whitespace-
    collapsed form. Production handles per-tradition rules
    (Spanish double-surname order, East Asian family-name-first
    conventions, Arabic patronymic structures) here too. The
    canonicalization is the same as the internal matcher's; the
    cross-network query reuses it for consistency."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"[^\w\s'-]", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def _normalize_address(address: str) -> str:
    """Light USPS-style standardization. Production uses a real
    USPS-CASS-certified standardizer; the QTF specifies the
    canonical address format for cross-network demographic-
    feature payloads."""
    if not address:
        return ""
    s = address.strip()
    replacements = [
        (r"\bStreet\b",    "St"),
        (r"\bAvenue\b",    "Ave"),
        (r"\bBoulevard\b", "Blvd"),
        (r"\bDrive\b",     "Dr"),
        (r"\bLane\b",      "Ln"),
        (r"\bRoad\b",      "Rd"),
    ]
    for pattern, repl in replacements:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    return _canonical_name(s)

def _normalize_phone(phone: str) -> str:
    """Strip non-digits, keep last 10. Production handles the
    e164 canonical form; the demo's last-10 is a stand-in."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits

def _jaro_winkler(s1: str, s2: str) -> Decimal:
    """Jaro-Winkler approximate string similarity. Production
    uses jellyfish; the demo provides a hand-rolled version so
    the dependency surface stays small. Range: 0.0 (no
    similarity) to 1.0 (identical)."""
    if not s1 and not s2:
        return Decimal("1.0")
    if not s1 or not s2:
        return Decimal("0.0")
    if s1 == s2:
        return Decimal("1.0")
    len1, len2 = len(s1), len(s2)
    match_window = max(len1, len2) // 2 - 1
    if match_window < 0:
        match_window = 0
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    for i in range(len1):
        start = max(0, i - match_window)
        end = min(i + match_window + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return Decimal("0.0")
    transpositions = 0
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2
    jaro = (
        Decimal(matches) / Decimal(len1)
        + Decimal(matches) / Decimal(len2)
        + Decimal(matches - transpositions) / Decimal(matches)
    ) / Decimal(3)
    # Winkler bonus for common prefix up to 4 chars.
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + Decimal(prefix) * Decimal("0.1") * (Decimal(1) - jaro)

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes
    5.1 - 5.8."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, set):
        return [_serialize_for_dynamodb(v) for v in sorted(obj)]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _summarize_payload_for_audit(demographic_features: dict) -> dict:
    """Audit-friendly summary of a demographic-feature payload.
    Records WHAT features were present (not their values), the
    payload's structural shape, and a content hash that lets the
    audit reconstruct payload identity for dispute resolution
    without retaining the actual demographic content. The actual
    feature values flow through the matcher and the audit
    archive (where they are encrypted at rest with the audit-
    archive KMS key); the structured logs hold only the
    summary."""
    features_present = sorted(k for k, v in demographic_features.items() if v)
    canonical = json.dumps(
        {k: demographic_features.get(k) for k in features_present},
        sort_keys=True,
        default=str,
    )
    return {
        "features_present":  features_present,
        "feature_count":     len(features_present),
        "payload_hash":      _sha256(canonical)[:16],
    }

def _build_attribution_chain(originating_user_or_patient: str,
                                is_patient_mediated: bool,
                                originating_sub_participant: str,
                                originating_qhin: str,
                                requesting_jurisdiction: str,
                                routing_path: list = None) -> dict:
    """Assemble the originating-attribution chain. The chain
    flows with the query through every hop in the federation;
    each hop adds its own attribution metadata. The audit log
    stores the full chain for dispute reconstruction."""
    return {
        "originating_user_or_patient_id": originating_user_or_patient,
        "is_patient_mediated":            is_patient_mediated,
        "originating_sub_participant_id": originating_sub_participant,
        "originating_qhin_id":            originating_qhin,
        "requesting_jurisdiction":        requesting_jurisdiction,
        "routing_path":                   routing_path or [originating_qhin],
        "attribution_chain_hash":         _sha256(
            f"{originating_user_or_patient}:"
            f"{originating_sub_participant}:"
            f"{originating_qhin}:"
            f"{is_patient_mediated}")[:16],
    }

def _emit_metric(metric_name: str, value: float,
                  dimensions: dict = None) -> None:
    """CloudWatch metric emit. Cohort-bucket-hash dimensions
    feed the cohort-stratified accuracy monitoring; production
    aggregates by CohortBucketHash and alarms on per-cohort
    match-rate or false-acceptance-rate disparities."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": k, "Value": v}
                    for k, v in (dimensions or {}).items()
                ],
            }],
        )
    except Exception as exc:
        logger.warning("metric emit failed",
                        extra={"metric": metric_name,
                                "error": str(exc)})

def _archive_to_s3(payload: dict, bucket: str, partition: str,
                     key_id: str = None) -> None:
    """Best-effort archive to S3 with KMS encryption. Failures
    logged and skipped (the demo prints what it would write)."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    kid = key_id or uuid.uuid4().hex
    key = f"{partition}/{today}/{kid}.json"
    body = json.dumps(payload, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.info("archive write skipped (demo mode is fine)",
                     extra={"bucket": bucket, "key": key,
                              "error": str(exc)})

def _audit_log(event: dict) -> None:
    """Write an audit-event-log row. In production this is a
    DynamoDB PutItem on the audit-event-log table with full
    attribution chain. The demo logs and archives best-effort."""
    enriched = dict(event)
    enriched.setdefault("audit_event_id", uuid.uuid4().hex)
    enriched.setdefault("logged_at", _now_iso())
    enriched.setdefault("matcher_config_version", MATCHER_CONFIG_VERSION)
    enriched.setdefault("tolerance_version", CROSS_NETWORK_TOLERANCE_VERSION)
    enriched.setdefault("overlay_rules_version", OVERLAY_RULES_VERSION)
    logger.info("audit_event", extra={"event": enriched["event_type"]})
    _archive_to_s3(enriched, AUDIT_ARCHIVE_BUCKET,
                     f"audit-events/{enriched['event_type']}",
                     key_id=enriched["audit_event_id"])
```

---

## Mock QHIN Router, Secrets Custody, Local MPI, Consent Store, and Jurisdictional Overlays

Production reads QHIN credentials and signing keys from AWS Secrets Manager (with KMS-backed encryption and rotation) and signs through CloudHSM or KMS where the institutional security posture requires single-tenant HSM custody. Production reads the local MPI from Aurora PostgreSQL or the institution's existing MPI vendor's product. Production reads consent posture and jurisdictional overlays from per-participant policy stores maintained by the compliance and privacy teams. Production routes outbound queries through HTTPS-with-mTLS to the QHIN's cross-network router (typically a PrivateLink endpoint where the QHIN supports it). The demo includes small mocks that exercise the full inbound-and-outbound flow without requiring those external dependencies.

```python
# --- Mock secrets custody ---
class MockSecretsCustody:
    """Stand-in for AWS Secrets Manager with KMS-backed
    encryption and rotation. Production never returns plaintext
    signing-key material to Python application code; KMS Sign
    operations call into the KMS context for asymmetric signing.
    The demo uses an in-memory HMAC key for readability so the
    signature verification in the inbound handler can succeed
    against the same key."""

    def __init__(self):
        # Per-rotation signing-key versions. The demo uses HMAC
        # keys for simplicity; production uses asymmetric
        # signing keys (RSA or ECDSA) with KMS-backed signing.
        self._participant_signing_keys = {
            "v-2026-q2-001": secrets.token_bytes(32),
        }
        self._participant_active_version = "v-2026-q2-001"
        # QHIN public-signing-key versions known to the
        # participant. Production loads these from the QHIN's
        # published key-distribution endpoint with explicit
        # rotation handling and a catch-up window.
        self._qhin_public_keys = {
            "qhin-example-eastern-network": {
                "v-2026-q2-001": secrets.token_bytes(32),
            },
            "qhin-example-national-network": {
                "v-2026-q2-001": secrets.token_bytes(32),
            },
            "qhin-example-western-network": {
                "v-2026-q2-001": secrets.token_bytes(32),
            },
        }
        self._access_log: list = []

    def get_participant_signing_key(self,
                                          version: str = None) -> tuple:
        """Acquire the participant's signing key for the active
        version. Production returns a KMS context, not plaintext."""
        v = version or self._participant_active_version
        self._access_log.append({
            "operation":    "get_participant_signing_key",
            "version":      v,
            "timestamp":    _now_iso(),
        })
        if v not in self._participant_signing_keys:
            raise KeyError(
                f"participant signing key version {v} not found "
                f"or expired (the rotation may have decommissioned "
                f"this version; load the active version)")
        return v, self._participant_signing_keys[v]

    def get_qhin_public_keys(self, qhin_id: str,
                                  include_previous: bool = True
                                  ) -> dict:
        """Acquire the QHIN's known public-signing-key versions.
        Includes the prior version during the rotation window
        so signatures produced before the cutover still verify."""
        self._access_log.append({
            "operation":    "get_qhin_public_keys",
            "qhin_id":      qhin_id,
            "timestamp":    _now_iso(),
        })
        keys = self._qhin_public_keys.get(qhin_id, {})
        return dict(keys) if include_previous else {
            k: v for k, v in keys.items() if k.endswith("active")
        }

    def rotate_participant_key(self, new_version: str,
                                    dual_control_approvers: list) -> None:
        """Rotation ceremony. Production requires dual-control
        approval; rotation is audit-logged with both operator
        identities."""
        if len(dual_control_approvers) < 2:
            raise ValueError(
                "participant signing-key rotation requires dual-"
                "control approval (at least two approvers from "
                "non-overlapping organizational units)")
        self._participant_signing_keys[new_version] = secrets.token_bytes(32)
        prior_active = self._participant_active_version
        self._participant_active_version = new_version
        self._access_log.append({
            "operation":     "rotate_participant_key",
            "new_version":   new_version,
            "prior_active":  prior_active,
            "approvers":     dual_control_approvers,
            "timestamp":     _now_iso(),
        })

def _sign_payload(payload: dict, signing_key: bytes,
                    key_version: str) -> dict:
    """Produce a signature envelope for a query or response
    payload. Production uses KMS asymmetric Sign with RSA-PSS
    or ECDSA; the demo uses HMAC-SHA-256 for simplicity. The
    envelope carries the signature value, the signing-key
    version active at signing time, and the canonical payload
    hash so verifiers can reconstruct what was signed."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    signature = hmac.new(signing_key, canonical.encode("utf-8"),
                            hashlib.sha256).hexdigest()
    return {
        "signature_value":      signature,
        "signing_key_version":  key_version,
        "payload_hash":         _sha256(canonical),
        "signed_at":            _now_iso(),
    }

def _verify_signature_against_any(payload: dict,
                                       signature_envelope: dict,
                                       known_keys: dict) -> bool:
    """Verify the signature against any of the known key
    versions. The catch-up window means both the current and
    the prior key version may verify legitimate signatures."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    sig_version = signature_envelope.get("signing_key_version")
    sig_value = signature_envelope.get("signature_value")
    if not sig_version or not sig_value:
        return False
    # Try the version the envelope claims first.
    if sig_version in known_keys:
        expected = hmac.new(known_keys[sig_version],
                              canonical.encode("utf-8"),
                              hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, sig_value):
            return True
    # Try any other known versions (production may need this
    # only during a rotation window where the envelope claims
    # the prior version).
    for v, key in known_keys.items():
        if v == sig_version:
            continue
        expected = hmac.new(key, canonical.encode("utf-8"),
                              hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, sig_value):
            return True
    return False

# --- Mock local MPI ---
# The local master patient index. Production is Aurora
# PostgreSQL or the institution's existing MPI vendor's product.
# The demo holds a handful of synthetic records that the
# cross-network matcher consults under the cross-network
# tolerance.
SYNTHETIC_LOCAL_MPI_RECORDS = [
    {
        "local_record_id":      "amc-richmond-mrn-00284271",
        "given_name":           "Sarah",
        "family_name":          "Mitchell",
        "dob":                  "1984-08-17",
        "sex_or_gender":        "F",
        "address_line":         "1247 Oak St",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23220",
        "phone":                "+18045551234",
        "ssn_last_4":           "4287",
        "source_organization_id":   "amc-richmond-cardiology-clinic",
        "source_organization_name": "Academic Medical Center Richmond - Cardiology",
        "source_organization_npi":  "1234567890",
        "sensitivity_flags":    [],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "40s",
            "sex_or_gender":      "F",
            "name_tradition":     "english_traditional",
        },
    },
    {
        "local_record_id":      "amc-richmond-mrn-00891344",
        "given_name":           "Maria",
        "family_name":          "Garcia-Lopez",
        "dob":                  "1972-03-14",
        "sex_or_gender":        "F",
        "address_line":         "8810 Maple Ave",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23230",
        "phone":                "+18045557654",
        "ssn_last_4":           "1119",
        "source_organization_id":   "amc-richmond-primary-care",
        "source_organization_name": "Academic Medical Center Richmond - Primary Care",
        "source_organization_npi":  "1234567891",
        "sensitivity_flags":    ["reproductive_health_care"],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "50s",
            "sex_or_gender":      "F",
            "name_tradition":     "spanish_double_surname",
        },
    },
    {
        "local_record_id":      "amc-richmond-mrn-00733215",
        "given_name":           "James",
        "family_name":          "Patterson",
        "dob":                  "1956-07-29",
        "sex_or_gender":        "M",
        "address_line":         "412 Birch Ln",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23221",
        "phone":                "+18045554443",
        "ssn_last_4":           "2244",
        "source_organization_id":   "amc-richmond-cardiology-clinic",
        "source_organization_name": "Academic Medical Center Richmond - Cardiology",
        "source_organization_npi":  "1234567890",
        "sensitivity_flags":    ["part_2_substance_use_treatment"],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "60s",
            "sex_or_gender":      "M",
            "name_tradition":     "english_traditional",
        },
    },
    {
        "local_record_id":      "amc-richmond-mrn-00499812",
        "given_name":           "Chen",
        "family_name":          "Liu",
        "dob":                  "1990-11-04",
        "sex_or_gender":        "F",
        "address_line":         "27 Beacon Ct",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23226",
        "phone":                "+18048889999",
        "ssn_last_4":           "9023",
        "source_organization_id":   "amc-richmond-internal-medicine",
        "source_organization_name": "Academic Medical Center Richmond - Internal Medicine",
        "source_organization_npi":  "1234567892",
        "sensitivity_flags":    [],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "30s",
            "sex_or_gender":      "F",
            "name_tradition":     "east_asian_traditional",
        },
    },
]

class MockLocalMPI:
    """Stand-in for Aurora PostgreSQL holding the participant's
    canonical patient identity records. Production has indexes
    on the demographic-feature blocking keys, full-text search,
    and per-record sensitivity flags. The cross-network matcher
    queries this MPI under the cross-network tolerance; the
    internal-application matcher (recipe 5.1) queries the same
    MPI under the internal tolerance."""

    def __init__(self, records: list):
        self._records = list(records)

    def get_all(self) -> list:
        return list(self._records)

    def get_by_id(self, local_record_id: str) -> Optional[dict]:
        for r in self._records:
            if r["local_record_id"] == local_record_id:
                return dict(r)
        return None

    def block_candidates(self, normalized_query: dict) -> list:
        """Light blocking-key candidate generation. Production
        uses indexes on (soundex(family_name), substring(dob,
        1, 4)) or similar blocking keys to reduce O(n) scans on
        the full MPI. The demo does a full scan."""
        return list(self._records)

# --- Mock consent store ---
class MockConsentStore:
    """Stand-in for the institutional consent-management
    workflow. Per-record consent posture is captured at intake
    and updated over time; the cross-network matcher's
    sensitivity-overlay step consults this store to determine
    whether a candidate may be disclosed for a specific
    exchange purpose."""

    def __init__(self):
        # Default-permissive consent for the demo. Production
        # captures consent explicitly at intake with appropriate
        # patient communication.
        self._withdrawals: dict = {}
        self._explicit_part_2_consents: dict = {}

    def consent_permits_disclosure(self, local_record: dict,
                                          exchange_purpose: str,
                                          requesting_jurisdiction: str
                                          ) -> bool:
        local_id = local_record["local_record_id"]
        if local_id in self._withdrawals:
            return False
        # 42 CFR Part 2 records require explicit consent for
        # disclosure beyond the originating program. The demo
        # does not have explicit consent so part 2 records are
        # suppressed by default.
        if "part_2_substance_use_treatment" in (
                local_record.get("sensitivity_flags") or []):
            if local_id not in self._explicit_part_2_consents:
                return False
        return True

    def withdraw_consent(self, local_record_id: str) -> None:
        """Patient withdraws cross-network disclosure consent.
        Forward-only: future cross-network queries exclude the
        record; prior disclosed records remain in the recipients'
        possession (the framework does not support retraction)."""
        self._withdrawals[local_record_id] = _now_iso()

    def grant_part_2_consent(self, local_record_id: str,
                                  exchange_purpose: str) -> None:
        self._explicit_part_2_consents[local_record_id] = {
            "exchange_purpose": exchange_purpose,
            "granted_at":       _now_iso(),
        }

# --- Mock jurisdictional overlay rules ---
class MockJurisdictionalOverlays:
    """Stand-in for the per-jurisdiction overlay-rules engine.
    Production has a versioned rule store with attorney-reviewed
    rules per jurisdiction, per record-type sensitivity
    classification, and per exchange-purpose authorization
    scope. The rules are consulted at every hop in the routing
    layer."""

    def applicable_overlays(self, local_record: dict,
                                  authorization_context: dict) -> list:
        flags = local_record.get("sensitivity_flags") or []
        overlays = []
        # Reproductive-health-care: post-Dobbs state-law overlay
        # applies when the requesting jurisdiction's posture is
        # incompatible with the patient's residence-jurisdiction
        # overlay. The demo treats Virginia (state-of-virginia)
        # as compatible and a few other example jurisdictions as
        # incompatible.
        if "reproductive_health_care" in flags:
            requesting = authorization_context.get(
                "requesting_jurisdiction") or ""
            incompatible = {
                "state-with-criminal-prohibition-1",
                "state-with-criminal-prohibition-2",
            }
            if requesting in incompatible:
                overlays.append({
                    "overlay_id": "post_dobbs_v3",
                    "decision":   "suppress",
                    "reason":     "incompatible_jurisdictional_posture",
                })
        # Gender-affirming-care: per-jurisdiction overlay similar
        # in shape to post-Dobbs but with different applicability.
        if "gender_affirming_care" in flags:
            requesting = authorization_context.get(
                "requesting_jurisdiction") or ""
            restrictive = {"state-with-gac-restriction-1"}
            if requesting in restrictive:
                overlays.append({
                    "overlay_id": "gac_restriction_v2",
                    "decision":   "suppress",
                    "reason":     "restrictive_jurisdictional_posture",
                })
        # Mental-health: per-state overlay; treat as suppress on
        # individual_access_services to a third-party requester.
        if "mental_health_state_specific" in flags:
            if authorization_context.get(
                    "exchange_purpose") == "individual_access_services":
                overlays.append({
                    "overlay_id": "mental_health_state_v1",
                    "decision":   "suppress",
                    "reason":     "ias_third_party_request_restriction",
                })
        return overlays

# --- Mock QHIN federation router ---
class MockQHINFederationRouter:
    """Stand-in for the participant's QHIN's cross-network
    routing layer. In production this is an HTTPS-over-mTLS
    endpoint at the QHIN that receives outbound queries from
    participants, routes them to other QHINs and to participants
    within the QHIN's own federation, and returns the responses
    asynchronously. The demo runs all participants in one
    process so the router holds them in a dict and routes
    queries by iterating."""

    def __init__(self, secrets_custody: MockSecretsCustody):
        self._secrets_custody = secrets_custody
        self._participants: dict = {}
        self._pending_responses: dict = {}

    def register_participant(self, participant_id: str,
                                   handler) -> None:
        """Register a participant's inbound-query handler."""
        self._participants[participant_id] = handler

    def submit_outbound_query(self, signed_query: dict,
                                    originating_participant_id: str
                                    ) -> str:
        """Receive an outbound query from a participant. Route
        in parallel to other participants. Return a federation
        handle the originator listens against for incoming
        responses."""
        federation_handle = f"fed-handle-{uuid.uuid4().hex[:12]}"
        self._pending_responses[federation_handle] = []
        # The router unwraps the originator's signed envelope
        # and re-signs the inner payload with the QHIN's own
        # signing identity before forwarding. Production QHINs
        # do this because every hop in the routing layer signs
        # its forwarded message with the QHIN's identity (the
        # originating participant's signature is captured in
        # the originating-attribution chain and is verifiable
        # separately from the cross-QHIN audit reconstruction).
        inner_payload = signed_query.get("payload") if (
            isinstance(signed_query, dict)
            and "payload" in signed_query) else signed_query

        # Route to every other participant. Production routes
        # selectively based on geographic hints, sub-network
        # hints, and the QHIN's reciprocal-exchange relationships.
        for pid, handler in self._participants.items():
            if pid == originating_participant_id:
                continue
            try:
                # The router signs the request with the QHIN's
                # signing key so the receiving participant can
                # verify the QHIN identity. The receiving
                # handler's signature validation runs against
                # the QHIN's known public keys; the originating
                # participant's identity flows through the
                # attribution chain in the payload.
                qhin_keys = self._secrets_custody._qhin_public_keys.get(
                    PARTICIPANT_QHIN_ID, {})
                if not qhin_keys:
                    raise RuntimeError(
                        "no QHIN signing key available for routing")
                qhin_key_version = next(iter(qhin_keys))
                qhin_signing_key = qhin_keys[qhin_key_version]
                request_signature = _sign_payload(
                    inner_payload, qhin_signing_key,
                    qhin_key_version)
                response = handler(inner_payload, request_signature,
                                       {"qhin_id": PARTICIPANT_QHIN_ID,
                                        "request_timestamp": _now_iso()})
                if response:
                    self._pending_responses[federation_handle].append({
                        "responder_id": pid,
                        "response":     response,
                        "received_at":  _now_iso(),
                    })
            except Exception as exc:
                logger.warning("router routing error",
                                extra={"target": pid,
                                        "error": str(exc)})
        return federation_handle

    def receive_responses(self, federation_handle: str
                              ) -> list:
        """Return the responses received for the federation
        handle. Production listens against an SQS queue or a
        WebSocket; the demo returns the in-memory list."""
        return list(self._pending_responses.get(
            federation_handle, []))

# --- Module-level singletons for the demo ---
secrets_custody              = MockSecretsCustody()
local_mpi                    = MockLocalMPI(SYNTHETIC_LOCAL_MPI_RECORDS)
consent_store                = MockConsentStore()
jurisdictional_overlays_db   = MockJurisdictionalOverlays()
qhin_router                  = MockQHINFederationRouter(secrets_custody)
_IN_MEMORY_FEDERATION_ATTRIBUTION: list = []
```

---

## Step 1: Handle the Inbound Federated Patient-Discovery Query

*The pseudocode calls this `handle_inbound_patient_discovery_query(request_payload, request_signature, request_metadata)`. A query arrives from the participant's QHIN. The handler validates the QHIN's signature, validates the originating-attribution chain against the participant's authorized QHINs, validates the exchange-purpose claim against the participant's authorized exchange purposes, and dispatches the query to the local matcher with the appropriate authorization context. Skip the validation step and you accept malformed or unauthorized queries that produce wrong-record disclosures with audit-trail attribution to QHINs that did not actually originate them.*

```python
def handle_inbound_patient_discovery_query(
        request_payload: dict,
        request_signature: dict,
        request_metadata: dict) -> dict:
    """
    Authenticate, validate, and dispatch an inbound federated
    query. Returns a signed response envelope or a structured
    rejection envelope.
    """
    qhin_id = request_metadata.get("qhin_id")
    query_id = request_payload.get("query_id") or (
        f"tefca-inbound-{uuid.uuid4().hex[:12]}")

    # Step 1A: validate the QHIN's request signature against the
    # QHIN's known public-signing-key versions (current plus
    # prior during the rotation window).
    qhin_public_keys = secrets_custody.get_qhin_public_keys(
        qhin_id, include_previous=True)

    if not _verify_signature_against_any(
            request_payload, request_signature, qhin_public_keys):
        _audit_log({
            "event_type": "TEFCA_INBOUND_QUERY_SIGNATURE_REJECTED",
            "query_id":   query_id,
            "qhin_id":    qhin_id,
            "rejected_at": _now_iso(),
        })
        _emit_metric("InboundQueryRejected", 1.0,
                      dimensions={"Reason": "BadSignature",
                                    "QhinId": qhin_id})
        return _build_rejection_response(
            query_id, qhin_id, "InvalidQHINSignature")

    # Step 1B: validate the originating-attribution chain. The
    # participant honors only chains from authorized QHINs;
    # mis-attributed chains are rejected.
    attribution_chain = request_payload.get(
        "originating_attribution_chain") or {}
    originating_qhin = attribution_chain.get("originating_qhin_id")
    if originating_qhin not in PARTICIPANT_AUTHORIZED_QHINS:
        _audit_log({
            "event_type": "TEFCA_INBOUND_QUERY_ATTRIBUTION_REJECTED",
            "query_id":   query_id,
            "qhin_id":    qhin_id,
            "originating_qhin": originating_qhin,
            "rejected_at": _now_iso(),
        })
        _emit_metric("InboundQueryRejected", 1.0,
                      dimensions={"Reason": "UnauthorizedOriginator",
                                    "QhinId": qhin_id})
        return _build_rejection_response(
            query_id, qhin_id, "UnauthorizedOriginatorQHIN")

    # Step 1C: validate the exchange-purpose claim against the
    # participant's authorization scope. A query under an
    # unauthorized purpose returns a structured purpose-denied
    # envelope that the framework's information-blocking
    # exception covers (this is the Privacy Exception's canonical
    # use case where the participant declines to honor a purpose
    # the participant is not authorized for).
    exchange_purpose = request_payload.get("exchange_purpose")
    if exchange_purpose not in PARTICIPANT_AUTHORIZED_EXCHANGE_PURPOSES:
        _audit_log({
            "event_type": "TEFCA_INBOUND_QUERY_PURPOSE_DENIED",
            "query_id":   query_id,
            "qhin_id":    qhin_id,
            "exchange_purpose": exchange_purpose,
            "denied_at":  _now_iso(),
        })
        _emit_metric("InboundQueryDenied", 1.0,
                      dimensions={"Reason": "UnauthorizedPurpose",
                                    "Purpose": str(exchange_purpose)})
        return _build_purpose_denied_response(
            query_id, qhin_id, attribution_chain, exchange_purpose)

    # Step 1D: build the authorization context the local matcher
    # consults. The context combines the exchange-purpose claim,
    # the originating-attribution chain, the patient-mediated
    # flag, and the applicable jurisdictional overlay rules.
    authorization_context = {
        "exchange_purpose":         exchange_purpose,
        "originating_attribution":  attribution_chain,
        "is_patient_mediated":      attribution_chain.get(
                                        "is_patient_mediated", False),
        "requesting_jurisdiction":  attribution_chain.get(
                                        "requesting_jurisdiction"),
        "responding_jurisdiction":  PARTICIPANT_JURISDICTION,
        "tolerance_version":        CROSS_NETWORK_TOLERANCE_VERSION,
        "overlay_rules_version":    OVERLAY_RULES_VERSION,
    }

    # Step 1E: persist the federation-attribution chain.
    _IN_MEMORY_FEDERATION_ATTRIBUTION.append({
        "query_id":           query_id,
        "qhin_id":            qhin_id,
        "attribution_chain":  attribution_chain,
        "exchange_purpose":   exchange_purpose,
        "captured_at":        _now_iso(),
    })

    _audit_log({
        "event_type": "TEFCA_INBOUND_QUERY_ACCEPTED",
        "query_id":   query_id,
        "qhin_id":    qhin_id,
        "attribution_chain": attribution_chain,
        "exchange_purpose":  exchange_purpose,
        "demographic_payload_summary":
            _summarize_payload_for_audit(
                request_payload.get("demographic_features") or {}),
        "accepted_at": _now_iso(),
    })

    # Step 1F: dispatch to the local matcher (Step 2).
    candidate_set = run_local_matcher_under_cross_network_tolerance(
        request_payload.get("demographic_features") or {},
        authorization_context, query_id)

    # Step 1G: apply the sensitivity overlay (Step 3).
    filtered_candidates = apply_sensitivity_overlay(
        candidate_set, authorization_context, query_id)

    # Step 1H: build and sign the response envelope.
    signing_key_version, signing_key = (
        secrets_custody.get_participant_signing_key())

    response_payload = {
        "query_id":             query_id,
        "responder_id":         PARTICIPANT_ID,
        "candidates":           filtered_candidates,
        "candidate_count_returned":  len(filtered_candidates),
        "candidate_count_truncated": False,
        "responded_at":         _now_iso(),
        "tolerance_version":    CROSS_NETWORK_TOLERANCE_VERSION,
        "overlay_rules_version": OVERLAY_RULES_VERSION,
    }
    response_signature = _sign_payload(
        response_payload, signing_key, signing_key_version)
    signed_response = {
        "payload":   response_payload,
        "signature": response_signature,
    }

    _audit_log({
        "event_type": "TEFCA_INBOUND_RESPONSE_DELIVERED",
        "query_id":   query_id,
        "candidate_count": len(filtered_candidates),
        "delivered_at": _now_iso(),
    })
    _emit_metric("InboundResponseDelivered", 1.0,
                  dimensions={"Purpose": exchange_purpose,
                                "QhinId": qhin_id})
    return signed_response

def _build_rejection_response(query_id: str, qhin_id: str,
                                  reason_code: str) -> dict:
    return {
        "payload": {
            "query_id":         query_id,
            "responder_id":     PARTICIPANT_ID,
            "rejection_reason": reason_code,
            "responded_at":     _now_iso(),
        },
        "signature": None,  # rejections are unsigned in the demo
    }

def _build_purpose_denied_response(query_id: str, qhin_id: str,
                                          attribution_chain: dict,
                                          exchange_purpose: str
                                          ) -> dict:
    """Information-blocking-compliance response: the participant
    declines under the framework's exception mechanism rather
    than silently dropping the query."""
    return {
        "payload": {
            "query_id":            query_id,
            "responder_id":        PARTICIPANT_ID,
            "denied_under_exception": "PrivacyException",
            "exception_reason":    "UnauthorizedExchangePurpose",
            "exchange_purpose":    exchange_purpose,
            "responded_at":        _now_iso(),
        },
        "signature": None,  # the demo skips signing for denied
    }
```

---

## Step 2: Run the Local Matcher Under the Cross-Network Tolerance

*The pseudocode calls this `run_local_matcher_under_cross_network_tolerance(demographic_features, authorization_context, query_id)`. The matcher consults the local MPI with a tolerance calibrated for cross-network use. Treatment queries operate under high-recall tolerance; individual-access-services queries operate under high-precision tolerance. Skip the dual-calibration and the federation's queries that the participant should respond to are silently dropped, which is an information-blocking compliance concern.*

```python
def run_local_matcher_under_cross_network_tolerance(
        demographic_features: dict,
        authorization_context: dict,
        query_id: str) -> list:
    """
    Apply the cross-network tolerance to the local MPI. Return
    the candidate set as a list of envelope dicts.
    """
    exchange_purpose = authorization_context["exchange_purpose"]

    # Step 2A: load the cross-network tolerance for the use case.
    tolerance = CROSS_NETWORK_TOLERANCE_BY_PURPOSE.get(
        exchange_purpose,
        CROSS_NETWORK_TOLERANCE_BY_PURPOSE["treatment"])

    # Step 2B: normalize the demographic features for matching.
    normalized = {
        "given_name":   _canonical_name(
            demographic_features.get("given_name")),
        "family_name":  _canonical_name(
            demographic_features.get("family_name")),
        "dob":          (demographic_features.get("dob") or "").strip(),
        "address_line": _normalize_address(
            demographic_features.get("address_line") or ""),
        "zip_code":     re.sub(
            r"\D", "",
            demographic_features.get("zip_code") or "")[:5],
        "phone":        _normalize_phone(
            demographic_features.get("phone") or ""),
        "ssn_last_4":   re.sub(
            r"\D", "",
            demographic_features.get("ssn_last_4") or "")[-4:],
    }

    # Step 2C: candidate generation through the MPI's blocking
    # key. The demo iterates the MPI; production uses indexed
    # blocking keys to bound the candidate set.
    blocked = local_mpi.block_candidates(normalized)

    # Step 2D: per-candidate scoring under the cross-network
    # tolerance. For each MPI record, compute per-feature
    # similarity, combine via weighted Fellegi-Sunter, and
    # accept if above the candidate-acceptance threshold.
    scored = []
    for mpi_record in blocked:
        # Apply the consent-and-jurisdiction filter at
        # candidate-evaluation time. Records the patient has
        # not consented to disclose for this exchange purpose
        # are excluded from the candidate set entirely (so the
        # matcher does not even score them, avoiding the
        # leakage of a "we have this record but won't disclose
        # it" inference).
        if not consent_store.consent_permits_disclosure(
                mpi_record, exchange_purpose,
                authorization_context.get(
                    "requesting_jurisdiction") or ""):
            continue

        per_feature_similarities = _compute_per_feature_similarities(
            normalized, mpi_record)

        match_score = _combine_with_fellegi_sunter(
            per_feature_similarities, FEATURE_WEIGHTS)

        if match_score >= tolerance["candidate_acceptance_threshold"]:
            confidence_tier = (
                "high" if match_score >= tolerance[
                    "high_confidence_threshold"] else "medium")
            candidate_envelope = {
                "opaque_record_token":
                    f"tok-{PARTICIPANT_ID[:3]}-"
                    f"{query_id[:12]}-"
                    f"{uuid.uuid4().hex[:12]}",
                "_local_record_id":
                    # Retained internally for the demo's
                    # document-retrieval lookup; never returned
                    # in the federation response. Production
                    # persists this mapping in the participant-
                    # local-mapping table and never includes it
                    # in the cross-network envelope.
                    mpi_record["local_record_id"],
                "disclosable_demographic_features":
                    _extract_disclosable_features(
                        mpi_record, exchange_purpose),
                "source_organization_attribution": {
                    "source_organization_id":
                        mpi_record["source_organization_id"],
                    "source_organization_name":
                        mpi_record["source_organization_name"],
                    "source_organization_npi":
                        mpi_record["source_organization_npi"],
                },
                "match_score":             match_score,
                "match_confidence_tier":   confidence_tier,
                "sensitivity_flags_summary":
                    list(mpi_record.get("sensitivity_flags") or []),
                "cohort_axis_hashes":
                    _compute_cohort_axis_hashes(mpi_record),
            }
            scored.append(candidate_envelope)

    # Step 2E: limit to max-candidate-count. Truncation is
    # audit-logged so the cross-QHIN dispute reconstruction can
    # see when the response was capped.
    if len(scored) > tolerance["max_candidate_count"]:
        scored.sort(key=lambda c: c["match_score"], reverse=True)
        original = len(scored)
        scored = scored[:tolerance["max_candidate_count"]]
        _audit_log({
            "event_type": "TEFCA_INBOUND_QUERY_CANDIDATES_TRUNCATED",
            "query_id":   query_id,
            "original_count": original,
            "returned_count": len(scored),
        })

    _emit_metric("LocalMatcherCandidates", float(len(scored)),
                  dimensions={"Purpose": exchange_purpose,
                                "ConfidenceTier": "mixed"})
    return scored

def _extract_disclosable_features(mpi_record: dict,
                                          exchange_purpose: str) -> dict:
    """Return the demographic-feature subset the participant is
    willing to disclose for cross-network discovery. Treatment
    queries get the full feature set; individual-access-services
    queries get a more limited disclosure (because the originating
    user is a patient or her authorized agent and the framework
    constrains what an IAS recipient learns about candidate
    matches that are not the patient's own records). Production
    has institution-specific disclosure policies; the demo's
    rules are illustrative."""
    if exchange_purpose == "individual_access_services":
        return {
            "given_name":   mpi_record["given_name"],
            "family_name":  mpi_record["family_name"],
            "dob":          mpi_record["dob"],
            "sex_or_gender": mpi_record["sex_or_gender"],
            # Address suppressed for IAS to limit
            # re-identification risk on near-match candidates.
        }
    return {
        "given_name":   mpi_record["given_name"],
        "family_name":  mpi_record["family_name"],
        "dob":          mpi_record["dob"],
        "sex_or_gender": mpi_record["sex_or_gender"],
        "city":         mpi_record["city"],
        "state":        mpi_record["state"],
        "zip_code":     mpi_record["zip_code"],
    }

def _compute_per_feature_similarities(query_normalized: dict,
                                          mpi_record: dict) -> dict:
    """Per-feature similarity scoring. Same machinery as recipe
    5.1 with cross-network normalization."""
    similarities = {}
    similarities["given_name"] = _jaro_winkler(
        query_normalized["given_name"],
        _canonical_name(mpi_record.get("given_name")))
    similarities["family_name"] = _jaro_winkler(
        query_normalized["family_name"],
        _canonical_name(mpi_record.get("family_name")))
    similarities["dob"] = (
        Decimal("1.0") if (query_normalized["dob"]
                              and query_normalized["dob"] ==
                              (mpi_record.get("dob") or "").strip())
        else Decimal("0.0"))
    similarities["address_line"] = _jaro_winkler(
        query_normalized["address_line"],
        _normalize_address(mpi_record.get("address_line") or ""))
    similarities["zip_code"] = (
        Decimal("1.0") if (query_normalized["zip_code"]
                              and query_normalized["zip_code"] ==
                              (mpi_record.get("zip_code") or ""))
        else Decimal("0.0"))
    similarities["phone"] = (
        Decimal("1.0") if (query_normalized["phone"]
                              and query_normalized["phone"] ==
                              _normalize_phone(
                                  mpi_record.get("phone") or ""))
        else Decimal("0.0"))
    similarities["ssn_last_4"] = (
        Decimal("1.0") if (query_normalized["ssn_last_4"]
                              and query_normalized["ssn_last_4"] ==
                              (mpi_record.get("ssn_last_4") or ""))
        else Decimal("0.0"))
    return similarities

def _combine_with_fellegi_sunter(per_feature: dict,
                                      weights: dict) -> Decimal:
    """Weighted-sum combination across features; the production
    Fellegi-Sunter implementation uses log-likelihood ratios
    with EM-trained per-feature m-and-u parameters."""
    total = Decimal("0")
    weighted = Decimal("0")
    for feature, sim in per_feature.items():
        w = weights.get(feature, Decimal("0"))
        weighted += w * sim
        total += w
    if total == 0:
        return Decimal("0")
    return weighted / total

def _compute_cohort_axis_hashes(mpi_record: dict) -> dict:
    """Compute hashed cohort-axis values for the response. The
    hashes flow back to the originator for cohort-stratified
    accuracy monitoring; the underlying axis values do not."""
    cohort_values = mpi_record.get("cohort_values") or {}
    out = {}
    for axis in COHORT_AXES:
        val = cohort_values.get(axis, "unknown")
        h = _sha256(f"{axis}:{val}")
        out[f"{axis}_hash"] = h[:16]
    return out
```

---

## Step 3: Apply the Per-Record-Type Sensitivity Overlay

*The pseudocode calls this `apply_sensitivity_overlay(candidate_set, authorization_context, query_id)`. Each candidate is filtered through the applicable overlay rules: 42 CFR Part 2 substance-use-treatment record handling (already filtered at Step 2 via consent), post-Dobbs reproductive-health-care state-law overlays, gender-affirming-care state-law overlays, mental-health and HIV-and-genetic-information state-specific rules. Skip the overlay step and you disclose records that the applicable jurisdictional rule would have suppressed.*

```python
def apply_sensitivity_overlay(candidate_set: list,
                                  authorization_context: dict,
                                  query_id: str) -> list:
    """
    Apply per-candidate overlay-rule evaluation. Suppressed
    candidates are dropped from the output with audit-logged
    suppression reasons.
    """
    filtered = []
    suppressed_count = 0
    for candidate in candidate_set:
        # Look up the candidate's source MPI record so we can
        # consult the sensitivity flags. Production carries the
        # flags inline on the candidate envelope; the demo looks
        # them up here.
        local_id = candidate.get("_local_record_id")
        mpi_record = local_mpi.get_by_id(local_id) if local_id else None
        if not mpi_record:
            filtered.append(candidate)
            continue

        applicable = jurisdictional_overlays_db.applicable_overlays(
            mpi_record, authorization_context)

        suppressing = [o for o in applicable
                          if o.get("decision") == "suppress"]
        if suppressing:
            for overlay in suppressing:
                _audit_log({
                    "event_type": "TEFCA_OVERLAY_SUPPRESSED",
                    "query_id":   query_id,
                    "overlay_id": overlay["overlay_id"],
                    "reason":     overlay["reason"],
                    "candidate_token":
                        candidate["opaque_record_token"],
                    "suppressed_at": _now_iso(),
                })
                _emit_metric("OverlaySuppressed", 1.0,
                              dimensions={
                                  "OverlayId": overlay["overlay_id"]})
            suppressed_count += 1
            continue

        # Drop the internal _local_record_id from the
        # cross-network envelope before disclosure.
        outbound = {k: v for k, v in candidate.items()
                       if not k.startswith("_")}
        filtered.append(outbound)

    _audit_log({
        "event_type": "TEFCA_OVERLAY_APPLIED",
        "query_id":   query_id,
        "original_count":   len(candidate_set),
        "suppressed_count": suppressed_count,
        "delivered_count":  len(filtered),
        "applied_at": _now_iso(),
    })
    _emit_metric("OverlayApplicationRate",
                  float(suppressed_count) / max(len(candidate_set), 1),
                  dimensions={"Purpose":
                                  authorization_context["exchange_purpose"]})
    return filtered
```

---

## Step 4: Originate an Outbound Federated Patient-Discovery Query

*The pseudocode calls this `originate_outbound_patient_discovery_query(user_or_patient_identity, requested_demographics, exchange_purpose, use_case_context)`. A local user or patient initiates a cross-network query. The query-formulation logic balances recall (sending enough demographic features that the federation can match) with the per-feature suppression-for-sensitivity discipline. The signed query is submitted to the participant's QHIN. Skip the formulation discipline and the outbound query produces either insufficient recall or excessive disclosure.*

```python
def originate_outbound_patient_discovery_query(
        user_or_patient_identity: dict,
        requested_demographics: dict,
        exchange_purpose: str,
        use_case_context: dict) -> str:
    """
    Authenticate the originator, formulate the federated query,
    sign it, and submit through the QHIN federation router.
    Returns the federation handle that the response-consolidator
    listens against for incoming responses.
    """
    # Step 4A: authenticate the originator.
    is_patient_mediated = user_or_patient_identity.get(
        "is_patient_mediated", False)
    if is_patient_mediated:
        # Production validates against the patient-portal Cognito
        # IdP and confirms the patient is authenticated for IAS.
        # The demo trusts the caller for readability.
        principal_id = user_or_patient_identity.get(
            "patient_id") or "patient-unknown"
    else:
        principal_id = user_or_patient_identity.get(
            "user_id") or "user-unknown"

    # Step 4B: validate the participant's authorization for the
    # exchange purpose.
    if exchange_purpose not in PARTICIPANT_AUTHORIZED_EXCHANGE_PURPOSES:
        raise ValueError(
            f"participant not authorized for exchange purpose "
            f"{exchange_purpose}")

    # Step 4C: formulate the query payload. The demo includes
    # all provided demographics; production applies per-feature
    # suppression for sensitivity reasons (e.g., not sending the
    # patient's address through the federation when the IAS
    # use case does not require it).
    formulated_payload = {
        "given_name":   requested_demographics.get("given_name"),
        "family_name":  requested_demographics.get("family_name"),
        "dob":          requested_demographics.get("dob"),
        "sex_or_gender": requested_demographics.get("sex_or_gender"),
        "address_line_1": requested_demographics.get("address_line"),
        "city":         requested_demographics.get("city"),
        "state":        requested_demographics.get("state"),
        "zip_code":     requested_demographics.get("zip_code"),
        "phone":        requested_demographics.get("phone"),
        "ssn_last_4":   requested_demographics.get("ssn_last_4"),
    }

    # Step 4D: build the originating-attribution chain.
    attribution_chain = _build_attribution_chain(
        originating_user_or_patient=principal_id,
        is_patient_mediated=is_patient_mediated,
        originating_sub_participant=PARTICIPANT_ID,
        originating_qhin=PARTICIPANT_QHIN_ID,
        requesting_jurisdiction=PARTICIPANT_JURISDICTION,
        routing_path=[PARTICIPANT_QHIN_ID])

    # Step 4E: sign the query under the participant's signing
    # credential.
    query_id = f"tefca-outbound-{uuid.uuid4().hex[:12]}"
    query_payload = {
        "query_id":               query_id,
        "exchange_purpose":       exchange_purpose,
        "demographic_features":   formulated_payload,
        "originating_attribution_chain": attribution_chain,
        "use_case_context":       use_case_context,
        "originated_at":          _now_iso(),
    }
    signing_key_version, signing_key = (
        secrets_custody.get_participant_signing_key())
    signature = _sign_payload(
        query_payload, signing_key, signing_key_version)
    signed_query = {
        "payload":   query_payload,
        "signature": signature,
    }

    _audit_log({
        "event_type": "TEFCA_OUTBOUND_QUERY_SUBMITTED",
        "query_id":   query_id,
        "attribution_chain": attribution_chain,
        "exchange_purpose":  exchange_purpose,
        "demographic_payload_summary":
            _summarize_payload_for_audit(formulated_payload),
        "submitted_at": _now_iso(),
    })
    _emit_metric("OutboundQuerySubmitted", 1.0,
                  dimensions={"Purpose": exchange_purpose,
                                "PatientMediated": str(is_patient_mediated)})

    # Step 4F: submit to the QHIN federation router. Returns the
    # federation handle that the response-consolidator listens
    # against for incoming responses.
    federation_handle = qhin_router.submit_outbound_query(
        signed_query, originating_participant_id=PARTICIPANT_ID)

    # Capture the (query_id, federation_handle) mapping so the
    # consolidator can join responses with the originating query.
    _IN_MEMORY_FEDERATION_HANDLES[federation_handle] = {
        "query_id":          query_id,
        "exchange_purpose":  exchange_purpose,
        "submitted_at":      _now_iso(),
        "use_case_context":  use_case_context,
    }
    return federation_handle

_IN_MEMORY_FEDERATION_HANDLES: dict = {}
```

---

## Step 5: Consume and Consolidate the Federated-Discovery Responses

*The pseudocode calls this `consume_and_consolidate_responses(federation_handle, query_id, response_window_seconds, use_case_context)`. Responses arrive asynchronously. The consolidator validates each response, normalizes the demographic-feature representations across responders, groups candidates by patient identity, applies the use-case-specific presentation filter, and presents the consolidated view. Partial results are presented when the response window expires before all responses have arrived. Skip the per-response signature validation and you accept malformed or unauthorized responses that produce wrong-record disclosures.*

```python
def consume_and_consolidate_responses(
        federation_handle: str,
        response_window_seconds: int = None) -> dict:
    """
    Consume responses for the federation handle, validate each
    response's signature, group candidates by likely patient
    identity, and produce the consolidated presentation view.
    """
    handle_meta = _IN_MEMORY_FEDERATION_HANDLES.get(
        federation_handle, {})
    query_id = handle_meta.get("query_id", "unknown")
    exchange_purpose = handle_meta.get("exchange_purpose", "treatment")
    response_window_seconds = response_window_seconds or (
        RESPONSE_WINDOW_BY_PURPOSE_SECONDS.get(
            exchange_purpose,
            RESPONSE_WINDOW_BY_PURPOSE_SECONDS["treatment"]))

    # Step 5A: pull responses from the QHIN router. Production
    # listens against an SQS queue or a WebSocket; the demo
    # returns the in-memory list (the responses have already
    # arrived synchronously in this single-process demo).
    received = qhin_router.receive_responses(federation_handle)

    valid_responses = []
    for response_envelope in received:
        responder_id = response_envelope["responder_id"]
        response_payload = (
            response_envelope.get("response", {}).get("payload"))
        response_signature = (
            response_envelope.get("response", {}).get("signature"))

        if not response_payload:
            continue

        # Rejections and purpose-denied envelopes carry no
        # signature; record them but do not include them in the
        # candidate consolidation.
        if response_payload.get("rejection_reason"):
            _audit_log({
                "event_type": "TEFCA_OUTBOUND_RESPONSE_REJECTED",
                "query_id":   query_id,
                "responder_id": responder_id,
                "rejection_reason": response_payload["rejection_reason"],
            })
            continue
        if response_payload.get("denied_under_exception"):
            _audit_log({
                "event_type": "TEFCA_OUTBOUND_RESPONSE_DENIED",
                "query_id":   query_id,
                "responder_id": responder_id,
                "exception": response_payload[
                    "denied_under_exception"],
            })
            continue

        # Step 5B: validate the responder's signature.
        responder_keys = (
            secrets_custody._participant_signing_keys
            if responder_id == PARTICIPANT_ID
            else dict(secrets_custody._qhin_public_keys.get(
                PARTICIPANT_QHIN_ID, {})))
        # The demo's mock router uses the QHIN's signing key for
        # all routed responses (production uses each responder's
        # own signing key). This shortcut keeps the demo's
        # signature validation truthful within its own model.
        signature_valid = _verify_signature_against_any(
            response_payload, response_signature, responder_keys)
        if not signature_valid:
            _audit_log({
                "event_type": "TEFCA_OUTBOUND_RESPONSE_SIGNATURE_REJECTED",
                "query_id":   query_id,
                "responder_id": responder_id,
            })
            continue

        # Step 5C: log and add to the consolidation set.
        _audit_log({
            "event_type": "TEFCA_OUTBOUND_RESPONSE_RECEIVED",
            "query_id":   query_id,
            "responder_id": responder_id,
            "candidate_count":
                len(response_payload.get("candidates") or []),
        })
        valid_responses.append({
            "responder_id":  responder_id,
            "payload":       response_payload,
        })

    # Step 5D: normalize the candidate-record representations
    # across responders. The demo's responders all use the same
    # representation (since they share the mock implementation);
    # production handles per-responder variation.
    all_candidates = []
    for r in valid_responses:
        for candidate in r["payload"].get("candidates") or []:
            enriched = dict(candidate)
            enriched["_responder_id"] = r["responder_id"]
            all_candidates.append(enriched)

    # Step 5E: group candidates by patient identity. Candidates
    # from different responders that appear to refer to the same
    # patient are grouped together. Production uses a federated-
    # resolution matcher with cross-responder demographic
    # consolidation; the demo groups by (family_name, dob) which
    # is sufficient for the synthetic data.
    groups: dict = {}
    for candidate in all_candidates:
        feats = candidate.get("disclosable_demographic_features") or {}
        group_key = (
            _canonical_name(feats.get("family_name")),
            feats.get("dob"))
        groups.setdefault(group_key, []).append(candidate)

    # Step 5F: apply the use-case-specific presentation filter.
    # Treatment queries surface all candidates with attribution;
    # IAS queries filter to candidates the patient is authorized
    # for; public-health queries return aggregate counts only.
    if exchange_purpose == "public_health":
        presentation_view = {
            "query_id":                query_id,
            "exchange_purpose":        exchange_purpose,
            "aggregate_candidate_count": len(all_candidates),
            "responder_count":         len(valid_responses),
            "groupings_count":         len(groups),
        }
    else:
        groupings_view = []
        for group_key, candidates in groups.items():
            consolidated_features = candidates[0].get(
                "disclosable_demographic_features") or {}
            confidence = "high" if any(
                c.get("match_confidence_tier") == "high"
                for c in candidates) else "medium"
            groupings_view.append({
                "grouping_id":
                    f"group-{query_id[:12]}-{uuid.uuid4().hex[:8]}",
                "consolidated_demographic_view":
                    consolidated_features,
                "candidates_in_grouping": [
                    {
                        "opaque_record_token":
                            c["opaque_record_token"],
                        "responder_id": c["_responder_id"],
                        "source_organization_id":
                            c.get(
                                "source_organization_attribution",
                                {}).get("source_organization_id"),
                        "match_confidence_tier":
                            c.get("match_confidence_tier"),
                    }
                    for c in candidates
                ],
                "grouping_match_confidence": confidence,
            })
        presentation_view = {
            "query_id":           query_id,
            "exchange_purpose":   exchange_purpose,
            "candidate_groupings": groupings_view,
        }

    # Step 5G: completeness indicator. Production tracks the
    # expected responder count from the QHIN's framework
    # registry; the demo uses the registered participant count
    # minus the originator.
    expected = max(len(qhin_router._participants) - 1, 1)
    received_count = len(valid_responses)
    presentation_view["completeness_indicator"] = {
        "expected_responder_count_estimate": expected,
        "received_responder_count":          received_count,
        "completeness_pct": int(
            (received_count / expected) * 100) if expected else 0,
        "deadline_reached": False,  # synchronous demo
    }

    _audit_log({
        "event_type": "TEFCA_OUTBOUND_VIEW_CONSOLIDATED",
        "query_id":   query_id,
        "responder_count": received_count,
        "candidate_count": len(all_candidates),
        "groupings_count": len(groups),
        "consolidated_at": _now_iso(),
    })
    _emit_metric("OutboundResponsesConsolidated", float(received_count),
                  dimensions={"Purpose": exchange_purpose})
    return presentation_view
```

---

## Step 6: Handle Document-Query and Retrieval for Selected Candidates

*The pseudocode calls this `execute_document_query_and_retrieval(selected_candidates, user_or_patient_identity, use_case_context, query_id)`. The user reviews the consolidated view and selects candidates for document retrieval. The orchestrator formulates per-candidate document-query requests through the QHIN federation, consumes the document responses, and consolidates them into the user's longitudinal-record view. Skip the per-document attribution discipline and the consolidated record loses the source attribution that subsequent operational concerns depend on.*

```python
def execute_document_query_and_retrieval(
        selected_candidates: list,
        user_or_patient_identity: dict,
        use_case_context: dict,
        query_id: str) -> list:
    """
    Issue per-candidate document-query requests, consume the
    document responses, persist documents to the document-store
    bucket with per-document attribution, and emit the
    cross-recipe event.
    """
    consolidated_documents = []
    is_patient_mediated = user_or_patient_identity.get(
        "is_patient_mediated", False)

    for candidate in selected_candidates:
        opaque_token = candidate["opaque_record_token"]
        responder_id = candidate.get("responder_id")
        source_org_id = candidate.get("source_organization_id")

        # Step 6A: formulate the document-query request and
        # submit through the QHIN federation. In production this
        # is an HTTPS-over-mTLS call to the QHIN's
        # document-query endpoint with the opaque record token
        # the responder issued at discovery time. The demo
        # retrieves a synthetic document directly from the local
        # MPI mapping where the responder is the participant
        # itself.
        documents = _retrieve_documents_for_candidate(
            opaque_token, responder_id, source_org_id,
            use_case_context)

        for document in documents:
            # Step 6B: persist with per-document attribution.
            attribution_metadata = {
                "query_id":          query_id,
                "responder_id":      responder_id,
                "source_organization_id": source_org_id,
                "exchange_purpose":  use_case_context.get(
                                          "exchange_purpose"),
                "is_patient_mediated": is_patient_mediated,
                "user_or_patient_id":
                    user_or_patient_identity.get("user_id") or
                    user_or_patient_identity.get("patient_id"),
                "retrieved_at":      _now_iso(),
            }
            document_with_attribution = dict(document)
            document_with_attribution["attribution_metadata"] = (
                attribution_metadata)

            # Persist to the document-store bucket. The demo
            # archives best-effort; production uses Step
            # Functions to orchestrate the persist and update
            # the longitudinal-record view.
            _archive_to_s3(document_with_attribution,
                            DOCUMENT_STORE_BUCKET,
                            f"documents/{query_id}",
                            key_id=document.get("document_id"))
            consolidated_documents.append(document_with_attribution)

    _audit_log({
        "event_type": "TEFCA_DOCUMENTS_RETRIEVED",
        "query_id":   query_id,
        "candidate_count":  len(selected_candidates),
        "document_count":   len(consolidated_documents),
        "retrieved_at": _now_iso(),
    })

    # Step 6C: emit the cross-recipe completion event.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "tefca-national-scale-matching",
            "DetailType":   "tefca_query_completed",
            "EventBusName": TEFCA_EVENT_BUS_NAME,
            "Detail": json.dumps({
                "query_id":          query_id,
                "candidate_count":   len(selected_candidates),
                "document_count":    len(consolidated_documents),
                "exchange_purpose":  use_case_context.get(
                                          "exchange_purpose"),
                "is_patient_mediated": is_patient_mediated,
                "completed_at":      _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _emit_metric("DocumentsRetrieved",
                  float(len(consolidated_documents)),
                  dimensions={"Purpose": use_case_context.get(
                                            "exchange_purpose",
                                            "treatment")})
    return consolidated_documents

def _retrieve_documents_for_candidate(opaque_token: str,
                                              responder_id: str,
                                              source_org_id: str,
                                              use_case_context: dict
                                              ) -> list:
    """Mock document retrieval. Production routes this through
    the QHIN's document-query endpoint; each responder honors
    its own access controls and returns the requested document
    types under the appropriate authorization framework.

    The demo synthesizes a small number of documents per
    candidate so the pipeline trace exercises the persistence
    and attribution paths."""
    requested_types = use_case_context.get(
        "requested_document_types") or ["consultation_note",
                                            "active_medication",
                                            "allergy_note"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    documents = []
    for dtype in requested_types:
        documents.append({
            "document_id":
                f"doc-{responder_id[:12]}-{dtype}-"
                f"{uuid.uuid4().hex[:8]}",
            "document_type":  dtype,
            "document_date":  today,
            "responder_id":   responder_id,
            "source_organization_id": source_org_id,
            # Document content body is intentionally a stub in
            # the demo; production carries the actual FHIR
            # bundle or CDA document from the responder.
            "content_summary": (
                f"[demo stub] {dtype} retrieved from "
                f"{source_org_id} via {responder_id}"),
        })
    return documents
```

---

## Full Pipeline

The pipeline assembles the six steps into a single end-to-end flow. In production these are separate Lambdas and Step Functions running in separate AWS accounts under cross-account access policies; here we run them in-process so the trace is easy to follow.

```python
def register_demo_participants() -> None:
    """Wire the local participant's inbound handler into the
    mock QHIN router so outbound queries from the participant
    can be routed to other (mock) participants. The demo creates
    two additional participants that respond from synthetic
    MPIs."""

    # The participant whose code we're showing (the originator
    # of outbound queries and the responder for inbound queries
    # routed back to it).
    qhin_router.register_participant(
        PARTICIPANT_ID,
        handle_inbound_patient_discovery_query)

    # Two additional mock participants whose handlers respond
    # from their own synthetic MPIs. The demo gives each of them
    # a small overlapping population so the cross-network
    # matcher has something to find.
    other_participants = [
        ("participant-virginia-hie",
         _make_inbound_handler_for_other_participant(
             "participant-virginia-hie",
             [
                 {
                     "local_record_id": "vahie-mrn-77221334",
                     "given_name": "Sarah",
                     "family_name": "Mitchell",
                     "dob": "1984-08-17",
                     "sex_or_gender": "F",
                     "address_line": "1247 Oak St",
                     "city": "Richmond",
                     "state": "VA",
                     "zip_code": "23220",
                     "phone": "+18045551234",
                     "ssn_last_4": "4287",
                     "source_organization_id":
                         "primary-care-clinic-richmond-west",
                     "source_organization_name":
                         "Primary Care Clinic Richmond West",
                     "source_organization_npi": "1111111111",
                     "sensitivity_flags": [],
                     "cohort_values": {
                         "geographic_region": "mid_atlantic",
                         "age_decade": "40s",
                         "sex_or_gender": "F",
                         "name_tradition": "english_traditional",
                     },
                 },
             ])),
        ("participant-national-pharmacy-data-network",
         _make_inbound_handler_for_other_participant(
             "participant-national-pharmacy-data-network",
             [
                 {
                     "local_record_id": "nhpdn-rx-44912988",
                     "given_name": "Sarah",
                     "family_name": "Mitchell",
                     "dob": "1984-08-17",
                     "sex_or_gender": "F",
                     "address_line": "1247 Oak St",
                     "city": "Richmond",
                     "state": "VA",
                     "zip_code": "23220",
                     "phone": "+18045551234",
                     "ssn_last_4": "4287",
                     "source_organization_id":
                         "regional-pharmacy-chain-mid-atlantic",
                     "source_organization_name":
                         "Regional Pharmacy Chain Mid-Atlantic",
                     "source_organization_npi": "2222222222",
                     "sensitivity_flags": [],
                     "cohort_values": {
                         "geographic_region": "mid_atlantic",
                         "age_decade": "40s",
                         "sex_or_gender": "F",
                         "name_tradition": "english_traditional",
                     },
                 },
             ])),
    ]
    for pid, handler in other_participants:
        qhin_router.register_participant(pid, handler)

def _make_inbound_handler_for_other_participant(
        participant_id: str, mpi_records: list):
    """Produce an inbound-query-handler closure for a mock
    participant. The closure runs the same six-step inbound
    pipeline against a different MPI."""
    other_mpi = MockLocalMPI(mpi_records)

    def handler(request_payload, request_signature, request_metadata):
        # Mock other participants always accept (they trust the
        # router's signing key for the demo). Production would
        # validate the QHIN's signature here too.
        query_id = request_payload.get("query_id") or (
            f"tefca-routed-{uuid.uuid4().hex[:12]}")
        attribution_chain = request_payload.get(
            "originating_attribution_chain") or {}
        exchange_purpose = request_payload.get("exchange_purpose")

        # Run the local matcher against the other participant's
        # MPI under the cross-network tolerance.
        tolerance = CROSS_NETWORK_TOLERANCE_BY_PURPOSE.get(
            exchange_purpose,
            CROSS_NETWORK_TOLERANCE_BY_PURPOSE["treatment"])
        demographic_features = (
            request_payload.get("demographic_features") or {})
        normalized = {
            "given_name":   _canonical_name(
                demographic_features.get("given_name")),
            "family_name":  _canonical_name(
                demographic_features.get("family_name")),
            "dob":          (demographic_features.get("dob")
                                or "").strip(),
            "address_line": _normalize_address(
                demographic_features.get("address_line_1")
                or demographic_features.get("address_line")
                or ""),
            "zip_code":     re.sub(
                r"\D", "",
                demographic_features.get("zip_code") or "")[:5],
            "phone":        _normalize_phone(
                demographic_features.get("phone") or ""),
            "ssn_last_4":   re.sub(
                r"\D", "",
                demographic_features.get("ssn_last_4") or "")[-4:],
        }
        scored = []
        for r in other_mpi.get_all():
            sims = _compute_per_feature_similarities(normalized, r)
            score = _combine_with_fellegi_sunter(sims, FEATURE_WEIGHTS)
            if score >= tolerance["candidate_acceptance_threshold"]:
                scored.append({
                    "opaque_record_token":
                        f"tok-{participant_id[:8]}-"
                        f"{query_id[:8]}-"
                        f"{uuid.uuid4().hex[:12]}",
                    "disclosable_demographic_features": {
                        "given_name":   r["given_name"],
                        "family_name":  r["family_name"],
                        "dob":          r["dob"],
                        "sex_or_gender": r["sex_or_gender"],
                        "city":         r["city"],
                        "state":        r["state"],
                        "zip_code":     r["zip_code"],
                    },
                    "source_organization_attribution": {
                        "source_organization_id":
                            r["source_organization_id"],
                        "source_organization_name":
                            r["source_organization_name"],
                        "source_organization_npi":
                            r["source_organization_npi"],
                    },
                    "match_score": score,
                    "match_confidence_tier":
                        "high" if score >= tolerance[
                            "high_confidence_threshold"] else "medium",
                    "sensitivity_flags_summary":
                        list(r.get("sensitivity_flags") or []),
                    "cohort_axis_hashes":
                        _compute_cohort_axis_hashes(r),
                })

        # Sign the response. The demo signs with the QHIN router's
        # signing key (the originator's MockSecretsCustody knows
        # this key as the QHIN public key, which is what the
        # response-consolidator validates against).
        response_payload = {
            "query_id":       query_id,
            "responder_id":   participant_id,
            "candidates":     scored,
            "candidate_count_returned": len(scored),
            "candidate_count_truncated": False,
            "responded_at":   _now_iso(),
        }
        _, qhin_key = (None,
                          secrets_custody._qhin_public_keys.get(
                              PARTICIPANT_QHIN_ID, {}).get(
                              "v-2026-q2-001"))
        response_signature = _sign_payload(
            response_payload, qhin_key, "v-2026-q2-001")
        return {
            "payload":   response_payload,
            "signature": response_signature,
        }
    return handler

def run_demo():
    """Run two representative cross-network query flows: a
    staff-initiated treatment query (the ED-attending searching
    for the unconscious-patient's longitudinal record) and a
    patient-mediated individual-access-services query (the
    patient pulling her own record through a personal-health-
    record app). Then exercise the inbound handler with both
    a valid query and a few rejection scenarios."""
    print("=" * 72)
    print("National-Scale Patient Matching (TEFCA Participant) Demo")
    print("=" * 72)
    print()
    print("All patients, demographics, organizations, and QHIN identifiers")
    print("in this demo are fictional. The mock QHIN federation router,")
    print("secrets custody, local MPI, consent store, and jurisdictional")
    print("overlays return hand-crafted data that exercises the inbound,")
    print("local-match, sensitivity-overlay, outbound, response-consolidation,")
    print("and document-retrieval paths; do not point this demo at a live QHIN.")
    print()
    print(f"Participant:           {PARTICIPANT_ID}")
    print(f"Participant QHIN:      {PARTICIPANT_QHIN_ID}")
    print(f"Participant juris:     {PARTICIPANT_JURISDICTION}")
    print(f"Matcher config:        {MATCHER_CONFIG_VERSION}")
    print(f"Tolerance config:      {CROSS_NETWORK_TOLERANCE_VERSION}")
    print(f"Overlay rules:         {OVERLAY_RULES_VERSION}")
    print()

    register_demo_participants()

    # --- Flow 1: staff-initiated treatment query ---
    print("-" * 72)
    print("Flow 1: ED-attending searches for an unconscious patient's record")
    print("        (treatment exchange purpose, staff-initiated)")
    print("-" * 72)
    federation_handle = originate_outbound_patient_discovery_query(
        user_or_patient_identity={
            "user_id": "user-emergency-department-attending-44211",
            "is_patient_mediated": False,
        },
        requested_demographics={
            "given_name":   "Sarah",
            "family_name":  "Mitchell",
            "dob":          "1984-08-17",
            "sex_or_gender": "F",
            "address_line": "1247 Oak Street",
            "city":         "Richmond",
            "state":        "VA",
            "zip_code":     "23220",
        },
        exchange_purpose="treatment",
        use_case_context={
            "exchange_purpose": "treatment",
            "requested_document_types": [
                "consultation_note", "active_medication",
                "allergy_note"],
        })
    print(f"  federation_handle: {federation_handle}")

    # Consolidate responses from the federation.
    presentation_view = consume_and_consolidate_responses(
        federation_handle)
    completeness = presentation_view.get("completeness_indicator", {})
    print(f"  completeness_pct:  {completeness.get('completeness_pct')}%")
    print(f"  groupings:         "
          f"{len(presentation_view.get('candidate_groupings') or [])}")
    for grouping in (presentation_view.get(
            "candidate_groupings") or [])[:3]:
        feats = grouping.get("consolidated_demographic_view") or {}
        print(f"    {feats.get('given_name')} {feats.get('family_name')} "
              f"(DOB {feats.get('dob')}): "
              f"{len(grouping['candidates_in_grouping'])} candidates "
              f"({grouping['grouping_match_confidence']} confidence)")
        for cand in grouping["candidates_in_grouping"]:
            print(f"      from {cand['responder_id']}: "
                  f"{cand['source_organization_id']}")

    # Select all candidates from the first grouping for document
    # retrieval (the ED attending picks the high-confidence
    # patient identity).
    if presentation_view.get("candidate_groupings"):
        selected = presentation_view["candidate_groupings"][0][
            "candidates_in_grouping"]
        documents = execute_document_query_and_retrieval(
            selected_candidates=selected,
            user_or_patient_identity={
                "user_id": "user-emergency-department-attending-44211",
                "is_patient_mediated": False,
            },
            use_case_context={
                "exchange_purpose": "treatment",
                "requested_document_types": [
                    "consultation_note", "active_medication",
                    "allergy_note"],
            },
            query_id=presentation_view["query_id"])
        print(f"  documents_retrieved: {len(documents)}")
        for doc in documents[:5]:
            print(f"    {doc['document_type']:<22} from "
                  f"{doc['source_organization_id']}")

    # --- Flow 2: patient-mediated IAS query ---
    print()
    print("-" * 72)
    print("Flow 2: patient retrieves her own longitudinal record")
    print("        (individual_access_services, patient-mediated)")
    print("-" * 72)
    federation_handle_2 = originate_outbound_patient_discovery_query(
        user_or_patient_identity={
            "patient_id": "patient-self-1984-08-17",
            "is_patient_mediated": True,
        },
        requested_demographics={
            "given_name":   "Sarah",
            "family_name":  "Mitchell",
            "dob":          "1984-08-17",
            "sex_or_gender": "F",
            "address_line": "1247 Oak Street",
            "city":         "Richmond",
            "state":        "VA",
            "zip_code":     "23220",
            "phone":        "+18045551234",
            "ssn_last_4":   "4287",
        },
        exchange_purpose="individual_access_services",
        use_case_context={
            "exchange_purpose": "individual_access_services",
            "requested_document_types": [
                "consultation_note", "active_medication"],
        })
    presentation_2 = consume_and_consolidate_responses(
        federation_handle_2)
    completeness_2 = presentation_2.get("completeness_indicator", {})
    print(f"  completeness_pct:  {completeness_2.get('completeness_pct')}%")
    print(f"  groupings:         "
          f"{len(presentation_2.get('candidate_groupings') or [])}")
    if presentation_2.get("candidate_groupings"):
        sample = presentation_2["candidate_groupings"][0]
        print(f"  IAS confidence:    {sample['grouping_match_confidence']}")
        feats = sample.get("consolidated_demographic_view") or {}
        # IAS responses do not include city/state/zip in the
        # disclosable feature set (see _extract_disclosable_features).
        print(f"  IAS feature_keys:  "
              f"{sorted(k for k in feats.keys())}")

    # --- Flow 3: inbound query rejection scenarios ---
    print()
    print("-" * 72)
    print("Flow 3: inbound query rejection scenarios")
    print("-" * 72)

    # Build a valid inbound query addressed to the participant
    # (Sarah Mitchell from a routed cross-network query).
    valid_inbound_payload = {
        "query_id": "tefca-inbound-test-001",
        "originating_attribution_chain": {
            "originating_user_id":
                "user-trauma-center-attending",
            "is_patient_mediated": False,
            "originating_sub_participant_id":
                "sub-regional-trauma-center-east",
            "originating_qhin_id":
                "qhin-example-eastern-network",
            "requesting_jurisdiction": "state-of-virginia",
            "routing_path": ["qhin-example-eastern-network"],
        },
        "exchange_purpose": "treatment",
        "demographic_features": {
            "given_name": "Sarah",
            "family_name": "Mitchell",
            "dob": "1984-08-17",
            "sex_or_gender": "F",
            "address_line": "1247 Oak St",
            "city": "Richmond",
            "state": "VA",
            "zip_code": "23220",
        },
    }
    qhin_keys = secrets_custody.get_qhin_public_keys(
        "qhin-example-eastern-network")
    qhin_signing_key_version = next(iter(qhin_keys))
    qhin_signing_key = qhin_keys[qhin_signing_key_version]
    valid_signature = _sign_payload(
        valid_inbound_payload, qhin_signing_key,
        qhin_signing_key_version)
    response = handle_inbound_patient_discovery_query(
        valid_inbound_payload, valid_signature,
        {"qhin_id": "qhin-example-eastern-network",
         "request_timestamp": _now_iso()})
    payload = response.get("payload") or {}
    print(f"  valid query:       "
          f"candidates={payload.get('candidate_count_returned')}")

    # Bad signature: tamper with the payload.
    tampered = dict(valid_inbound_payload)
    tampered["query_id"] = "tefca-inbound-test-002"
    response_bad = handle_inbound_patient_discovery_query(
        tampered, valid_signature,
        {"qhin_id": "qhin-example-eastern-network",
         "request_timestamp": _now_iso()})
    payload_bad = response_bad.get("payload") or {}
    print(f"  bad signature:     "
          f"rejection_reason={payload_bad.get('rejection_reason')}")

    # Unauthorized originator QHIN.
    unauth_payload = dict(valid_inbound_payload)
    unauth_payload["query_id"] = "tefca-inbound-test-003"
    unauth_payload["originating_attribution_chain"] = dict(
        valid_inbound_payload["originating_attribution_chain"])
    unauth_payload["originating_attribution_chain"][
        "originating_qhin_id"] = "qhin-not-on-our-list"
    unauth_signature = _sign_payload(
        unauth_payload, qhin_signing_key, qhin_signing_key_version)
    response_unauth = handle_inbound_patient_discovery_query(
        unauth_payload, unauth_signature,
        {"qhin_id": "qhin-example-eastern-network",
         "request_timestamp": _now_iso()})
    payload_unauth = response_unauth.get("payload") or {}
    print(f"  unauth originator: "
          f"rejection_reason={payload_unauth.get('rejection_reason')}")

    # Unauthorized exchange purpose.
    bad_purpose_payload = dict(valid_inbound_payload)
    bad_purpose_payload["query_id"] = "tefca-inbound-test-004"
    bad_purpose_payload["exchange_purpose"] = "research_secondary_use"
    bad_purpose_sig = _sign_payload(
        bad_purpose_payload, qhin_signing_key, qhin_signing_key_version)
    response_bp = handle_inbound_patient_discovery_query(
        bad_purpose_payload, bad_purpose_sig,
        {"qhin_id": "qhin-example-eastern-network",
         "request_timestamp": _now_iso()})
    payload_bp = response_bp.get("payload") or {}
    print(f"  bad purpose:       "
          f"denied_under_exception={payload_bp.get('denied_under_exception')}")

    # --- Flow 4: sensitivity-overlay-driven suppression ---
    print()
    print("-" * 72)
    print("Flow 4: cross-jurisdictional overlay suppression")
    print("-" * 72)
    # Send a query for Maria Garcia-Lopez (whose record carries
    # the reproductive_health_care sensitivity flag) from a
    # jurisdiction the demo treats as incompatible.
    overlay_payload = {
        "query_id": "tefca-inbound-test-005",
        "originating_attribution_chain": {
            "originating_user_id":
                "user-out-of-state-clinic-attending",
            "is_patient_mediated": False,
            "originating_sub_participant_id":
                "sub-out-of-state-clinic",
            "originating_qhin_id":
                "qhin-example-national-network",
            "requesting_jurisdiction":
                "state-with-criminal-prohibition-1",
            "routing_path": ["qhin-example-national-network"],
        },
        "exchange_purpose": "treatment",
        "demographic_features": {
            "given_name": "Maria",
            "family_name": "Garcia-Lopez",
            "dob": "1972-03-14",
            "sex_or_gender": "F",
            "address_line": "8810 Maple Ave",
            "city": "Richmond",
            "state": "VA",
            "zip_code": "23230",
        },
    }
    nat_keys = secrets_custody.get_qhin_public_keys(
        "qhin-example-national-network")
    nat_version = next(iter(nat_keys))
    nat_key = nat_keys[nat_version]
    overlay_sig = _sign_payload(
        overlay_payload, nat_key, nat_version)
    response_overlay = handle_inbound_patient_discovery_query(
        overlay_payload, overlay_sig,
        {"qhin_id": "qhin-example-national-network",
         "request_timestamp": _now_iso()})
    pl = response_overlay.get("payload") or {}
    print(f"  candidates returned: {pl.get('candidate_count_returned')}")
    print("  (Maria's record carries reproductive_health_care; the")
    print("   overlay engine suppressed the candidate because the")
    print("   requesting jurisdiction is incompatible with the")
    print("   patient's residence-jurisdiction overlay.)")

if __name__ == "__main__":
    run_demo()
```

---

Expected console output (the SQS / EventBridge / S3 / DynamoDB / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
========================================================================
National-Scale Patient Matching (TEFCA Participant) Demo
========================================================================

All patients, demographics, organizations, and QHIN identifiers
in this demo are fictional. The mock QHIN federation router,
secrets custody, local MPI, consent store, and jurisdictional
overlays return hand-crafted data that exercises the inbound,
local-match, sensitivity-overlay, outbound, response-consolidation,
and document-retrieval paths; do not point this demo at a live QHIN.

Participant:           participant-academic-medical-center-richmond
Participant QHIN:      qhin-example-eastern-network
Participant juris:     state-of-virginia
Matcher config:        tefca-matcher-v3.2.1
Tolerance config:      tefca-tolerance-v2.1.0
Overlay rules:         tefca-overlay-v1.4.7

------------------------------------------------------------------------
Flow 1: ED-attending searches for an unconscious patient's record
        (treatment exchange purpose, staff-initiated)
------------------------------------------------------------------------
  federation_handle: fed-handle-XXXXXXXXXXXX
  completeness_pct:  100%
  groupings:         1
    Sarah Mitchell (DOB 1984-08-17): 2 candidates (medium confidence)
      from participant-virginia-hie: primary-care-clinic-richmond-west
      from participant-national-pharmacy-data-network: regional-pharmacy-chain-mid-atlantic
  documents_retrieved: 6
    consultation_note      from primary-care-clinic-richmond-west
    active_medication      from primary-care-clinic-richmond-west
    allergy_note           from primary-care-clinic-richmond-west
    consultation_note      from regional-pharmacy-chain-mid-atlantic
    active_medication      from regional-pharmacy-chain-mid-atlantic

------------------------------------------------------------------------
Flow 2: patient retrieves her own longitudinal record
        (individual_access_services, patient-mediated)
------------------------------------------------------------------------
  completeness_pct:  100%
  groupings:         1
  IAS confidence:    high
  IAS feature_keys:  ['city', 'dob', 'family_name', 'given_name', 'sex_or_gender', 'state', 'zip_code']

------------------------------------------------------------------------
Flow 3: inbound query rejection scenarios
------------------------------------------------------------------------
  valid query:       candidates=1
  bad signature:     rejection_reason=InvalidQHINSignature
  unauth originator: rejection_reason=UnauthorizedOriginatorQHIN
  bad purpose:       denied_under_exception=PrivacyException

------------------------------------------------------------------------
Flow 4: cross-jurisdictional overlay suppression
------------------------------------------------------------------------
  candidates returned: 0
  (Maria's record carries reproductive_health_care; the
   overlay engine suppressed the candidate because the
   requesting jurisdiction is incompatible with the
   patient's residence-jurisdiction overlay.)
```

(The federation_handle and document_id suffixes include random UUID hex so the actual `XXXXXXXXXXXX` portions will differ from run to run. The Flow 1 grouping shows "medium confidence" because the ED attending's outbound query did not include phone or SSN-last-4, both of which carry significant weight in the matcher's calibration; the score of roughly 0.80 lands above the treatment-purpose acceptance threshold of 0.55 but below the high-confidence threshold of 0.85. With richer demographics the same query reaches "high confidence", which is the typical patient-mediated flow shown in Flow 2. Production with `jellyfish` and properly EM-trained Fellegi-Sunter weights produces different absolute scores. The Flow 2 IAS feature_keys list shows the full city/state/zip set in the consolidated-demographic view because each responding participant in the demo returns its own full feature set; in production each responder applies its own IAS-disclosure policy independently, and the participant's own responses (governed by the demo's `_extract_disclosable_features` policy) suppress city/state/zip on IAS responses.)

Several patterns to notice:

- **Flow 1 demonstrates the canonical treatment-purpose cross-network query.** The ED attending's outbound query reaches both other (mock) participants. Each runs its own local matcher under the cross-network tolerance and returns a candidate that scores high-confidence. The response-consolidator groups them by patient identity, presents a unified view, and the user (the ED attending) selects the candidates for document retrieval. The retrieval orchestrator pulls documents from each responder with per-document attribution. In a real deployment, the consultation note from the cardiology clinic, the active warfarin prescription from the pharmacy network, and the contrast-allergy note from a radiology center are exactly the kinds of records the federation surfaces that the local hospital's EHR did not have.
- **Flow 2 demonstrates patient-mediated individual-access-services.** The patient authenticates through her personal-health-record app (the `is_patient_mediated=True` flag flows through the attribution chain). The disclosable feature set is narrower than the treatment-purpose flow (only given_name, family_name, dob, sex_or_gender are returned in the candidate envelope; city/state/zip are suppressed) because the framework's IAS disclosure posture is more restrictive on near-match candidates. Production deployments may further narrow the disclosure, may require additional patient-consent confirmation before document retrieval, or may apply additional cohort-disparity-monitoring gates.
- **Flow 3 demonstrates the inbound-validation discipline.** The valid query is accepted and produces a candidate (Sarah Mitchell from the participant's local MPI matches the inbound query). The tampered query (the same signature against a different payload) is rejected with `InvalidQHINSignature`. The query from an unauthorized originator QHIN is rejected with `UnauthorizedOriginatorQHIN`. The query for an exchange purpose the participant is not authorized for (`research_secondary_use` in the demo) is denied under the `PrivacyException` of the information-blocking rule (this is the explicit "denied-under-exception" pattern that distinguishes the operationally-compliant denial from a silent-drop information-blocking violation).
- **Flow 4 demonstrates the cross-jurisdictional sensitivity overlay.** The query for Maria Garcia-Lopez (whose record carries the `reproductive_health_care` sensitivity flag) comes from a requesting jurisdiction the overlay engine treats as incompatible with the patient's residence jurisdiction. The matcher would have returned a candidate (Maria's record matches the query demographics), but the sensitivity-overlay step suppressed it before disclosure. Production overlay engines have attorney-reviewed rules per jurisdiction and per record-type sensitivity classification; the demo's two-jurisdiction demonstration is a stand-in for a much richer rule landscape.
- **The signature-verification pattern is the framework's authentication root-of-trust.** Every inbound query carries a request signature; every outbound response carries a responder signature. Failed validations are hard rejects with structured rejection envelopes (not silent drops); audit-logged with the rejection reason. Production extends to mTLS at the transport layer and asymmetric signing through KMS or CloudHSM for the message-layer signing.
- **The opaque record token is the participant-side mapping that the cross-network exchange does not expose.** Each candidate envelope carries an opaque token; the responder retains the local mapping from the token to the actual local record identifier under its own access controls. The originating participant uses the token to issue follow-up document-query requests; the local record identifier never flows through the federation. Production institutions sometimes leak local identifiers through the federation as a pragmatic shortcut and discover, the first time a cross-QHIN attribution-chain audit reconstruction surfaces the leak, that the framework's privacy posture is operationally less defensible than the architecture suggests.
- **The audit log captures every consequential operation.** Every inbound query (accepted, rejected, denied), every local-matcher decision (truncation), every sensitivity-overlay application (suppression), every outbound query (submitted), every response (received, rejected), every consolidation (completed), every document retrieval (completed) is audit-logged with the full attribution chain, the matcher-config version, the tolerance version, and the overlay-rules version active at the time. Production stores the audit-event log in a DynamoDB table with KMS-encrypted-at-rest backing and forwards a sampled-or-complete copy to the audit-archive S3 bucket with Object Lock in Compliance mode for retention.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Real QHIN integration through the Sequoia Project's QHIN-designation process.** The demo's `MockQHINFederationRouter` runs all participants in one process; production routes through the participant's QHIN, which has signed the Common Agreement with the RCE (Sequoia Project) and operates under the QHIN-Technical-Framework specifications. Integration is a multi-month onboarding (technical certification, governance review, operational testing) that the institution's QHIN selection drives. Different QHINs have different onboarding processes; the choice of QHIN is itself a strategic decision that affects onboarding timeline, fee structure, exchange-purpose authorization scope, and operational specifics. Plan the QHIN onboarding as a project with its own timeline, its own staffing, and its own iteration discipline.

**IHE-and-FHIR message construction with `fhir.resources` and an IHE XCPD-and-XCA library.** The demo's request and response payloads are simplified Python dicts. Production constructs IHE XCPD patient-discovery messages and IHE XCA document-query messages for the IHE-based exchange path, plus FHIR Patient `$match` operation invocations and Bulk FHIR responses for the FHIR-based path. The QTF specifies both formats for backward compatibility and forward evolution; the participant's gateway has to handle both depending on the responding participant's capabilities.

**mTLS-and-KMS-backed signing.** The demo uses HMAC-SHA-256 with in-process keys for readability. Production uses mTLS at the transport layer (with QHIN-issued participant certificates rotated on the framework's specified cadence) and KMS or CloudHSM-backed asymmetric signing at the message layer (RSA-PSS or ECDSA with the participant's signing key in KMS or in a CloudHSM cluster). The KMS Sign operation never returns the private key material; the Lambda's IAM role is permitted to invoke `kms:Sign` for the active signing-key version only, and the signing-key rotation is a coordinated operational ceremony with dual-control approval (two operators from non-overlapping organizational units must approve a rotation operation). Build the signing-key rotation as a deliberate operational program with named owners, named processes, and named review committees.

**HSM-backed QHIN-credential and signing-key custody with rotation ceremony.** The demo's `MockSecretsCustody` uses simple dict storage. Production custodies QHIN-issued credentials (mTLS certificates, OAuth client credentials) and the participant's signing keys in AWS Secrets Manager (with KMS-encrypted-at-rest backing and rotation Lambda functions for the rotation cadence) or in CloudHSM (for the high-assurance institutional posture). Rotation is a coordinated event between the participant and the QHIN with a catch-up window where the prior credentials remain valid for the cutover. Audit logging captures every access with the calling principal, the operation, the timestamp, and the cycle context. Many institutions discover the operational discipline of credential rotation when their first rotation deadline approaches; build the rotation capability deliberately rather than reactively.

**Real DynamoDB schema with the four primary tables.** The `federation-attribution` table holds per-query attribution chains (partition key: `query_id`, sort key: `attribution_event_id`). The `audit-event-log` table holds per-event audit records (partition key: `query_id`, sort key: `audit_event_id`). The `jurisdictional-overlay-config` table holds versioned overlay-rule configurations (partition key: `overlay_id`, sort key: `version`). The `consent-state` table holds per-patient consent posture (partition key: `local_record_id`, sort key: `consent_event_id`). Provision with on-demand capacity. Customer-managed KMS keys at rest. Point-in-time recovery for the federation-attribution and audit-event-log tables. DynamoDB Streams on the federation-attribution table to drive the cross-recipe event fan-out.

**TransactWriteItems for atomic cross-table writes.** The demo's audit log writes are independent. Production wraps the federation-attribution-plus-audit-event-log writes in `TransactWriteItems` so the per-query state is atomic across the two tables; partial-failure scenarios cannot leave a query's attribution recorded without the corresponding audit event.

**Real Aurora PostgreSQL local MPI.** The demo's `MockLocalMPI` is an in-memory list. Production has Aurora PostgreSQL (or the institution's existing MPI vendor's product) with indexes on the demographic-feature blocking keys, full-text search, sensitivity-flag enforcement, and recipe 5.1's identity-merge state. The cross-network matcher consults the MPI under read-only access; mutations to the MPI flow through recipe 5.1's separate write path.

**Real Step Functions orchestration for the document-query flow.** The demo's `execute_document_query_and_retrieval` runs synchronously in-process. Production orchestrates through Step Functions with per-candidate document-query parallelism, per-step retries, error routing to DLQs, and explicit synchronization at the consolidation step. The Step Functions execution context provides the orchestration trace for cross-QHIN dispute reconstruction.

**Real cross-account S3 buckets with PrivateLink for the document-store and audit-archive.** Production has a dedicated AWS account for the audit-archive bucket (separate from the operational account for blast-radius isolation). The audit-archive bucket has Object Lock in Compliance mode with retention pinned to the longest of the regulatory floors (HIPAA 7-year minimum, the QHIN's framework-specified audit-retention floor, the state-specific medical-records-retention, the cross-jurisdictional retention overlay where the participant operates across borders). Lifecycle to S3 Glacier Deep Archive after 90 days. PrivateLink endpoints between the operational VPC and the audit-archive account so the audit writes do not traverse the public internet.

**Real EventBridge bus with cross-recipe consumer subscriptions.** The demo emits events but they go nowhere in demo mode. Production deploys a dedicated `tefca-events-bus` with EventBridge rules routing the query-completed, dispute-raised, dispute-resolved, governance-event-received, consent-withdrawn, and credential-rotated events to the appropriate consumers (recipe 5.1 internal-MPI for upstream identity-merge events, recipe 5.5 cross-facility matcher for HIE-internal coordination, recipe 5.6 claims-clinical linkage for cross-payer use cases through TEFCA's payment exchange purpose, recipe 5.7 longitudinal-name-change for time-varying-name handling, recipe 5.8 privacy-preserving linkage for PPRL-through-TEFCA use cases, the dispute-handler Lambda for incoming disputes, the governance-evolution-handler Lambda for framework changes, the operational-systems consumers for cycle status). DLQs on every consumer; CloudWatch alarms on DLQ depth surface stuck consumers.

**Real Cognito patient-portal IdP for patient-mediated flows.** The demo trusts the `is_patient_mediated` flag in the originator dict. Production validates the patient's authentication through the participant's patient-portal Cognito user pool with multi-factor authentication, validates the OAuth token against the participant's IdP, captures the patient's authentication-event-id in the audit log, and propagates the patient-mediated attribution explicitly through the routing layer. The patient-portal IdP retains the authentication artifacts (with appropriate retention controls) for the audit-retention floor of the framework.

**Idempotency keys on every write.** Standardize at `(participant_id, query_id, hop_id)` for the inbound-query-handler Lambda; outbound at `(query_id, attribution_chain_hash)` for the outbound-query-formulator; consolidator at `(query_id, responder_id)`; document-retrieval at `(query_id, candidate_token, document_id)`; dispute at `(dispute_id, escalation_event_id)`; governance-evolution at `(governance_change_id, evaluation_event_id)`; QHIN-credential-rotation Step Functions at `(rotation_id, hop_id)`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate audit events, duplicate document-store persistences, or scrambled attribution chains.

**Cross-network-tolerance calibration with SageMaker and pilot-data infrastructure.** The demo's `CROSS_NETWORK_TOLERANCE_BY_PURPOSE` table is hand-tuned. Production calibrates against a curated calibration set (synthetic data plus opt-in pilot data from collaborating participants) using SageMaker training jobs. The pilot calibration is itself a separately authorized data-sharing event with its own data-use agreement, separate AWS account, separate access controls, separate audit posture; the calibration outputs (the candidate-acceptance threshold, the high-confidence threshold, the per-feature weights, the missing-feature weights) survive the pilot but the underlying pilot data is deleted at the end of the calibration project per the agreement. Re-calibration runs periodically and on detection of cohort-stratified disparity above the institutional threshold; institutional review (analytics governance committee, compliance, clinical informatics, privacy team, equity-monitoring committee) reviews the candidate before promotion.

**Real Splink-or-`recordlinkage` and `jellyfish` for the local matcher's combiner.** The demo's `_combine_with_fellegi_sunter` is a toy weighted-average. Production wraps Splink (or `recordlinkage`) with EM-trained per-feature m-and-u parameters, real Jaro-Winkler from `jellyfish`, real soundex from `jellyfish`, and the institution's full demographic-feature standardization library (USPS-CASS-certified address standardization, name-tradition-aware name parsing, e164 phone normalization). The same machinery as recipes 5.1 / 5.4 / 5.5 / 5.6 / 5.7; the cross-network variant is the same matcher running under a different tolerance configuration.

**Cross-jurisdictional overlay automation with regulatory-monitoring triggers.** The demo's `MockJurisdictionalOverlays` handles two example overlays. Production has a versioned overlay-rules engine that consumes the patient's residence jurisdiction, the requesting participant's jurisdiction, the responding participant's jurisdiction, the use case's authorization scope, and the record-type sensitivity classification, and produces a per-record disclosure decision. The overlay rules are versioned and reviewed on a regulatory-monitoring cadence (post-legislative-session and post-court-decision are typical triggers). The regulatory-monitoring function is shared between privacy and compliance teams with explicit per-state and per-RCE-bulletin subscriptions, court-decision tracking, and trigger thresholds with relevance-evaluation criteria. The per-query disclosure-decision audit trail captures every overlay-rule application with inputs, rule version active, and output decision.

**Patient-consent capture and withdrawal pathways.** The TEFCA deployment assumes that the patient has been asked (and has consented or declined) for cross-network disclosure under the applicable jurisdictional and use-case framework. The mechanism for asking is not the matcher's job; it is the registration workflow's, the patient-portal app's, and (for clinical-care contexts) the institutional consent-management workflow's. Build the consent-capture and withdrawal-pathway as a deliberate workflow with appropriate framing, training for the staff who solicit the information, and patient-facing communication about what cross-network disclosure does and what consent withdrawal means at federation scale (the retrospective limits are real; the institution can stop future disclosures but cannot retract records already disclosed to other participants).

**Information-blocking-exception handling automation.** The demo handles unauthorized-purpose queries with a `PrivacyException` envelope. Production has an exception-handling pipeline that evaluates each query's circumstances against the rule's defined exceptions (Privacy Exception, Security Exception, Infeasibility Exception, Health IT Performance Exception, Content and Manner Exception, Fees Exception, Licensing Exception), returns a structured "denied-under-exception" response with the exception code, and audit-logs the denial decision with the inputs that led to the exception's invocation. The pattern is operationally important for participants whose queries cannot be handled in the standard response window or whose policy excludes specific record types from the standard exchange purposes.

**Three review queues with cohort-and-cycle-aware tooling.** The cross-network-match-review queue surfaces medium-confidence candidates that the federation's response presented for review; reviewers see the consolidated-view candidates with the per-source attribution and (under appropriate authorization) the underlying records at each responder. The dispute-review queue surfaces incoming and outgoing disputes for cross-QHIN coordination; reviewers see the dispute artifacts with the full attribution chain. The governance-evolution queue surfaces framework changes (Common Agreement updates, QTF updates, SOP updates, jurisdictional-overlay-rule updates); reviewers from compliance, privacy, legal, and operations evaluate the operational impact and plan the institutional response. Each tool emits the reviewer's decision back into the operational training signal. Reviewer-authentication is two-factor and reviewer-action is dual-controlled for the dispute-review queue and the governance-evolution queue (two reviewers from non-overlapping organizational units must approve high-impact decisions).

**Cohort-stratified accuracy monitoring with disparity alarms.** The demo emits `CohortAxisHashes` summaries on each candidate envelope but does not aggregate or alarm. Production computes per-cohort match rate weekly, per-cohort false-acceptance rate weekly, per-cohort review-queue aging weekly, per-cohort sampled error rate monthly, all stratified by hashed cohort axes (geographic_region_hash, age_decade_hash, sex_or_gender_hash, name_tradition_hash) plus federation-specific extensions (responder-quality-tier cohort, jurisdictional-overlay cohort). Disparity (best-rate minus worst-rate) thresholds: match-rate > 0.10 = MEDIUM alarm; false-acceptance-rate > 0.02 = HIGH (because false acceptances at federation scale produce wrong-record disclosures that the originating participant cannot retract from the consumer); review-queue-aging disparity > 5 business days = MEDIUM. The privacy team is an explicit reviewer in addition to the standard analytics-governance committee, because cohort-stratified disparities at federation scale interact with the framework's privacy-and-equity expectations.

**Capacity coordination through the QHIN's operational interface.** The demo runs synchronously without rate limits. Production has API Gateway rate limiting per-QHIN with capacity reservations sized to the federation's projected volume (which grows faster than the institution's internal volume), per-source rate limiting on the inbound query handler with explicit fail-fast semantics, per-source error-rate monitoring with explicit escalation thresholds, and federation-wide capacity coordination through the QHIN's operational interface. Many participants discover the federation's capacity dynamics when their first capacity event hits; build the federation-aware capacity planning at program-design stage rather than reactively.

**KMS-encrypted everything.** Customer-managed keys for the federation-attribution table, the audit-event-log table, the jurisdictional-overlay-config table, the consent-state table, the document-store bucket, the audit-archive bucket, the SQS queues, the Lambda log groups, the Step Functions execution-context storage, the Secrets Manager secrets, and the local MPI Aurora cluster. CloudHSM where the institutional security posture or the framework's framework requires single-tenant HSM-backed key custody. Per-service KMS configuration is omitted for readability in the demo but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints + PrivateLink.** Production runs all Lambdas in VPC with VPC endpoints for DynamoDB (gateway), S3 (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, STS, and SageMaker. PrivateLink for the QHIN-to-participant exchange where the QHIN supports it. NAT Gateway only for outbound HTTPS to the QHIN where PrivateLink is not used; outbound proxy with allow-list. Aurora PostgreSQL in a private subnet with no public-network reachability; security group enumerates the specific Lambda execution-role-bound ENIs authorized to connect. Patient-portal-network-isolation pattern: the patient-portal Cognito flow operates through a separate API Gateway endpoint with its own WAF rule set, with rate limiting per-patient-session and per-patient-id below the staff-initiated query rate limits to prevent abuse.

**CloudTrail data events on every consequential operation.** Data events on the federation-attribution and audit-event-log DynamoDB tables, the audit-archive S3 bucket, the document-store S3 bucket, the QHIN-credentials Secrets Manager secrets, the signing-key KMS keys. Lambda invocations logged. Step Functions executions logged. EventBridge events logged. CloudTrail logs encrypted with KMS and retained per the regulatory floor (the longest of HIPAA 7-year minimum, the framework-specified audit-retention floor, the state-specific retention, and the cross-jurisdictional retention overlay). Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days; CloudTrail data events forwarded to a dedicated audit AWS account for blast-radius isolation.

**Lake Formation column-level and row-level access control on the analytics surface.** Different audiences need different views. Treatment-context users see the institution's own portion of the attribution chain; cross-QHIN-coordination users see the full attribution chain for dispute resolution; audit-and-compliance users see the full audit-event log; the institutional governance committee sees the federation-level metrics. Lake Formation enforces the per-audience access through column-level and row-level policies on the Athena queries.

**QHIN Participant Agreement and operational onboarding.** The institution has to negotiate and sign a Participant Agreement with the QHIN, complete the QHIN's onboarding (technical certification, governance review, operational testing), and operate continuously under the agreement's terms. The Participant Agreement is the load-bearing contractual artifact for the institution's TEFCA participation; the operational onboarding is a multi-month process that the institution has to plan and resource. Plan the QHIN onboarding as a project with its own timeline, its own staffing, and its own iteration discipline. Different QHINs have different onboarding processes; the institution's choice of QHIN affects the onboarding timeline and the operational specifics.

**Federation-participation governance program.** TEFCA participation is a multi-year program with named ownership, named processes, named milestones, and named review committees. The program spans compliance, privacy, legal, clinical operations, patient advocacy, security, IT, and analytics. Establish clear operational ownership: who tunes the cross-network tolerance, who reviews the cohort-disparity reports, who owns the QHIN-credential rotations, who handles the dispute-resolution coordination, who responds to consent withdrawals, who negotiates Participant Agreement changes, who owns the framework-evolution program. The pipeline works only when the operational ownership is clear and funded across the institution, not just within the IT or analytics organization.

The pipeline is the easy part. The operational discipline (federation-aware engineering, federation-aware compliance, federation-aware operations, federation-aware governance, with the institution-specific capabilities for QHIN-credential rotation as a deliberate operational program with HSM-backed custody and dual-control rotation, cross-network-tolerance calibration with pilot-data infrastructure as a separately governed substrate, sensitivity-overlay automation with regulatory-monitoring triggers, three-queue review tooling with cohort-and-cycle-aware oversight, consent-capture and withdrawal pathways with patient-facing communication, capacity coordination through the QHIN's operational interface, dispute-resolution coordination across QHINs with explicit attribution-chain reconstruction, governance-evolution program with explicit timeline-tracking against framework mandates) is what makes a TEFCA participant operate effectively in the federation rather than drifting into operational inadequacy. Build for that.

---

*← [Recipe 5.8: Privacy-Preserving Record Linkage](chapter05.08-privacy-preserving-record-linkage)*
