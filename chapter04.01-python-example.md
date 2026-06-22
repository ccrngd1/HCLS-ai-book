# Recipe 4.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.1. It shows one way you could translate those channel-optimization concepts into working Python using boto3. It is not production-ready. There's no real EHR integration, no consent ledger, no TCPA/CAN-SPAM workflow, no retries, no fairness dashboard. Think of it as the sketchpad version: useful for understanding the shape of the Thompson-sampling bandit pattern, not something you'd wire into your reminder service on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline follows the five steps from the main recipe: schedule reminders when appointments are booked, filter eligible channels when a schedule fires, pick a channel with Thompson sampling, dispatch the reminder, and update the bandit posterior when engagement events arrive. Each step maps 1:1 to the pseudocode.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem` on the specific tables (patient profile, bandit state, reminder decisions)
- `scheduler:CreateSchedule` and `scheduler:DeleteSchedule` for EventBridge Scheduler
- `sns:Publish` for SMS dispatch (or `sms-voice:SendTextMessage` if you are using AWS End User Messaging SMS)
- `ses:SendEmail` or `ses:SendTemplatedEmail` for email dispatch
- `cloudwatch:PutMetricData` for monitoring metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

SES-sending identities (domain or email address) must be verified in the account and region you are using. If you are still in the SES sandbox, recipient addresses must also be verified. For SMS, SNS needs an origination number (long code, short code, or 10DLC) in the account, and the destination region must be enabled for the sandbox you are in. These are account-level configurations that are easy to forget until your first message fails to deliver.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. The cohort priors, reminder offsets, and quiet-hours window are the knobs you will tune during pilot. Start with conservative cohort priors (so the bandit explores enough to learn) and tighten as you accumulate data.

```python
import json
import logging
import uuid
import random
import datetime
from datetime import timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo  # Python 3.9+ standard library

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (patient name, phone,
# email, appointment details, or anything that reveals clinical context).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SNS, SES, DynamoDB, and Scheduler
# during burst traffic (e.g., when Monday morning appointment reminders
# all fire within the same minute). Adaptive mode uses exponential
# backoff with jitter automatically.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
scheduler_client = boto3.client("scheduler", config=BOTO3_RETRY_CONFIG)
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)
ses_client = boto3.client("ses", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)

# --- DynamoDB Table Names ---
# Three tables. Keep them separate so access patterns stay clean:
#   1. patient-profile: patient contact info, preferences, opt-outs
#   2. bandit-state: per-(patient, channel) Beta posterior parameters
#   3. reminder-decisions: one row per reminder dispatched, for audit
#      and for joining engagement events back to the original decision
PATIENT_TABLE = "patient-profile"
BANDIT_TABLE = "bandit-state"
DECISIONS_TABLE = "reminder-decisions"

# --- EventBridge Scheduler Configuration ---
# Each scheduled reminder invokes this Lambda via an EventBridge Scheduler
# one-time schedule. The target ARN is the Lambda that runs the recommender.
# Scheduler needs an IAM role it can assume to invoke the target.
RECOMMENDER_LAMBDA_ARN = "arn:aws:lambda:us-east-1:123456789012:function:reminder-recommender"
SCHEDULER_ROLE_ARN = "arn:aws:iam::123456789012:role/eventbridge-scheduler-invoke-lambda"
SCHEDULE_GROUP = "reminders"  # Logical grouping for easier cleanup and filtering

# --- Messaging Configuration ---
# SES from-address must be a verified identity in the account/region.
# Use a dedicated subdomain (e.g., reminders@notifications.example.com)
# with SPF, DKIM, and DMARC configured so messages don't land in spam.
SES_FROM_ADDRESS = "reminders@notifications.example.com"
SES_CONFIGURATION_SET = "reminders"  # For engagement event publishing

# SNS topic for SMS (or use SNS.Publish directly to a phone number for simple cases).
# For production SMS at scale, AWS End User Messaging SMS (sms-voice client)
# is the more feature-rich path. This example uses SNS for simplicity.
SNS_SMS_ORIGINATION_NUMBER = "+18885551212"  # Your registered origination number

# --- Reminder Schedule ---
# How many hours before the appointment each reminder fires.
# Negative values because they are "before the appointment".
# This example uses three offsets; production systems often use 4-5.
REMINDER_OFFSETS_HOURS = [-168, -72, -24]  # 1 week, 3 days, 1 day before

# --- Quiet Hours (patient local time) ---
# Don't send SMS or voice during these hours. Email is fine overnight.
QUIET_HOURS_START = 21  # 9 PM local
QUIET_HOURS_END = 8     # 8 AM local

# --- Thompson Sampling Cold-Start Priors ---
# When we have no per-patient data for a (patient, channel) pair,
# we fall back to a cohort-level prior. For this illustrative example
# we use a single system-wide prior. Production would have a lookup
# keyed by cohort (age bucket, visit type, prior engagement).
#
# Beta(alpha, beta) where:
#   alpha = prior number of "successes" (confirmed/kept appointments)
#   beta  = prior number of "failures" (no-shows or non-responses)
#
# A Beta(2, 2) prior has mean 0.5 with moderate uncertainty, which
# encourages exploration early. As real data accrues, the posterior
# dominates the prior and mean shifts toward the observed rate.
COLD_START_PRIOR_ALPHA = Decimal("2.0")
COLD_START_PRIOR_BETA = Decimal("2.0")

# All channels the organization supports. The bandit chooses from this set
# after hard constraints are applied.
ALL_CHANNELS = ["sms", "email", "voice", "portal_push"]

# CloudWatch namespace for reminder metrics. Slice by channel and cohort
# in the dashboard to catch subgroup regressions early.
METRIC_NAMESPACE = "HealthcareReminders"
```

---

## Step 1: On Appointment Creation, Schedule the Reminders

*The pseudocode calls this `on_appointment_created(appointment)`. When an appointment is booked, this function creates one EventBridge Scheduler one-time schedule per reminder offset. Each schedule fires at exactly the right moment and invokes the recommender Lambda with the appointment ID. This beats polling your scheduling system on a cron, which turns into a distributed-lock problem you didn't want.*

```python
def on_appointment_created(appointment: dict) -> list:
    """
    Create EventBridge Scheduler schedules for each reminder offset.

    The appointment dict is expected to contain:
      - id:                unique appointment identifier
      - patient_id:        FK to patient profile
      - start_iso:         appointment start time in ISO 8601 with timezone
      - patient_timezone:  IANA tz like "America/New_York" for quiet-hours math

    Args:
        appointment: Dict representing the newly created appointment.

    Returns:
        List of schedule names that were created. Useful for idempotency
        and for cleanup on appointment cancellation (Step 1b).
    """
    # Parse the appointment start time. In production this comes from your
    # EHR's Appointment resource (FHIR) or scheduling system event.
    appt_time_utc = datetime.datetime.fromisoformat(
        appointment["start_iso"]
    ).astimezone(timezone.utc)

    patient_tz = ZoneInfo(appointment.get("patient_timezone", "UTC"))
    now_utc = datetime.datetime.now(timezone.utc)

    created_schedules = []

    for offset_hours in REMINDER_OFFSETS_HOURS:
        # Compute when this reminder should fire (UTC).
        send_time_utc = appt_time_utc + timedelta(hours=offset_hours)

        # Don't schedule reminders that would fire in the past. Same-day
        # bookings routinely blow past the T-168h and T-72h offsets.
        if send_time_utc <= now_utc:
            logger.info(
                "Skipping offset %dh: send time %s is in the past",
                offset_hours, send_time_utc.isoformat(),
            )
            continue

        # If the computed send time lands in the patient's quiet hours,
        # shift forward to the next allowed window. This protects the
        # patient from a 3 AM SMS without losing the reminder entirely.
        send_time_utc = _shift_if_quiet_hours(send_time_utc, patient_tz)

        # Schedule name encodes appointment_id + offset so it is deterministic.
        # That gives us idempotency for free: if the same event fires twice,
        # CreateSchedule on the same name will fail, which is what we want.
        schedule_name = f"reminder-{appointment['id']}-{abs(offset_hours)}h"

        # EventBridge Scheduler expects the expression in a specific format.
        # "at(yyyy-mm-ddTHH:MM:SS)" expects the time in the schedule's
        # ScheduleExpressionTimezone (we use UTC here, so strip the offset).
        schedule_expression = f"at({send_time_utc.strftime('%Y-%m-%dT%H:%M:%S')})"

        # The payload is what gets delivered to the recommender Lambda when
        # the schedule fires. Keep it small: just the join keys we need to
        # fetch the full patient and appointment context at decision time.
        payload = json.dumps({
            "appointment_id": appointment["id"],
            "patient_id": appointment["patient_id"],
            "offset_hours": offset_hours,
        })

        try:
            scheduler_client.create_schedule(
                Name=schedule_name,
                GroupName=SCHEDULE_GROUP,
                ScheduleExpression=schedule_expression,
                ScheduleExpressionTimezone="UTC",
                # Flexible window OFF: we want precise reminder timing.
                # Use FlexibleTimeWindow=ON for workloads where "sometime
                # in the next 15 minutes" is fine; it is not for reminders.
                FlexibleTimeWindow={"Mode": "OFF"},
                Target={
                    "Arn": RECOMMENDER_LAMBDA_ARN,
                    "RoleArn": SCHEDULER_ROLE_ARN,
                    "Input": payload,
                    # Retry policy for the Lambda invocation itself. If the
                    # Lambda fails transiently, Scheduler will retry within
                    # this window. For a reminder, a few minutes of lag is
                    # acceptable; days is not.
                    "RetryPolicy": {
                        "MaximumEventAgeInSeconds": 300,
                        "MaximumRetryAttempts": 3,
                    },
                },
                # Auto-delete the schedule after it fires. Keeps the account
                # tidy; Scheduler has per-account limits on schedule count.
                ActionAfterCompletion="DELETE",
                Description=f"Reminder for appointment {appointment['id']} "
                            f"at T{offset_hours}h",
            )
            created_schedules.append(schedule_name)
            logger.info(
                "Created schedule %s for %s",
                schedule_name, send_time_utc.isoformat(),
            )

        except scheduler_client.exceptions.ConflictException:
            # Schedule already exists. This is the idempotency win:
            # duplicate "appointment created" events don't create duplicate
            # reminders.
            logger.info("Schedule %s already exists; skipping", schedule_name)

    return created_schedules

def _shift_if_quiet_hours(send_time_utc: datetime.datetime,
                           patient_tz: ZoneInfo) -> datetime.datetime:
    """
    If send_time falls in the patient's quiet hours, shift to next morning.

    Quiet hours are an organization-wide hard rule: no SMS or voice between
    QUIET_HOURS_START and QUIET_HOURS_END in the patient's local time.
    Email gets a pass because it doesn't ring or buzz.

    For simplicity, this function shifts the send time for all channels.
    A more sophisticated implementation would pass the channel through and
    only shift for SMS/voice, letting email fire overnight.

    Edge case (NOTE for TechWriter, code review Finding 3): for tight
    offsets like T-2h, a shift of up to 11 hours could push the send time
    past the appointment itself. The current offsets (-168, -72, -24) are
    safe, but if you add T-2h, cap the shift against appt_time_utc in the
    caller (return None and skip when the shifted time is no longer
    strictly before the appointment).
    """
    local_time = send_time_utc.astimezone(patient_tz)
    local_hour = local_time.hour

    # Quiet hours span midnight (e.g., 21:00 to 08:00 next day).
    in_quiet_hours = (local_hour >= QUIET_HOURS_START) or (local_hour < QUIET_HOURS_END)

    if not in_quiet_hours:
        return send_time_utc

    # Shift to QUIET_HOURS_END on the next calendar day if we are after
    # QUIET_HOURS_START, or today if we are before QUIET_HOURS_END.
    if local_hour >= QUIET_HOURS_START:
        shifted_local = local_time.replace(
            hour=QUIET_HOURS_END, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
    else:
        shifted_local = local_time.replace(
            hour=QUIET_HOURS_END, minute=0, second=0, microsecond=0
        )

    return shifted_local.astimezone(timezone.utc)
```

**Step 1b: Cancel schedules when the appointment is cancelled or rescheduled.** Not strictly a different pseudocode step, but production reality. If you skip this, patients get reminders for appointments they no longer have, which is worse than no reminder.

```python
def on_appointment_cancelled(appointment_id: str) -> int:
    """
    Delete any pending reminder schedules for a cancelled appointment.

    Called when the EHR publishes an appointment cancellation event.
    Returns the number of schedules deleted.
    """
    deleted = 0
    for offset_hours in REMINDER_OFFSETS_HOURS:
        schedule_name = f"reminder-{appointment_id}-{abs(offset_hours)}h"
        try:
            scheduler_client.delete_schedule(
                Name=schedule_name,
                GroupName=SCHEDULE_GROUP,
            )
            deleted += 1
            logger.info("Deleted schedule %s", schedule_name)
        except scheduler_client.exceptions.ResourceNotFoundException:
            # Schedule already fired or never existed. Not an error.
            pass
    return deleted
```

---

## Step 2: Fetch Patient Features and Apply Hard Constraints

*The pseudocode calls this `get_eligible_channels(patient_id, send_time_utc)`. Before the model sees anything, hard rules filter the channel set: opt-outs, missing contact info, quiet hours, portal inactivity. Skip this step, and sooner or later your model will text a patient who opted out three years ago and your compliance team will learn your name.*

```python
def get_eligible_channels(patient_id: str,
                          send_time_utc: datetime.datetime) -> tuple:
    """
    Return the list of channels this patient is eligible to receive on.

    Returns a tuple of (eligible_channels, patient_profile). The profile
    is returned alongside so the caller doesn't need a second DynamoDB
    lookup to compose the message in Step 4.

    Eligibility rules (all of these are hard constraints, not soft features):
      - Patient must not have opted out of the channel
      - Contact info must be present for the channel
      - For SMS and voice, TCPA consent must be on file
      - Quiet hours bans SMS and voice but not email or portal_push
      - Portal_push requires recent (90-day) portal activity
    """
    patients_table = dynamodb.Table(PATIENT_TABLE)

    response = patients_table.get_item(Key={"patient_id": patient_id})
    patient = response.get("Item")
    if patient is None:
        logger.warning("Patient %s not found; no reminder sent", patient_id)
        return [], None

    # Start with every channel the organization supports.
    candidates = list(ALL_CHANNELS)

    # Rule: explicit opt-outs are immediate removals. This is the rule
    # that keeps you out of TCPA lawsuits. Treat opt_outs as a set.
    opt_outs = set(patient.get("opt_outs", []))
    candidates = [c for c in candidates if c not in opt_outs]

    # Rule: contact info must exist for the channel.
    if not patient.get("phone"):
        candidates = [c for c in candidates if c not in ("sms", "voice")]
    if not patient.get("email"):
        candidates = [c for c in candidates if c != "email"]

    # Rule: TCPA consent for auto-dialed messages to mobile numbers.
    # sms_consent and voice_consent are boolean flags that should be
    # captured at registration and updated via preference center.
    if not patient.get("sms_consent", False):
        candidates = [c for c in candidates if c != "sms"]
    if not patient.get("voice_consent", False):
        candidates = [c for c in candidates if c != "voice"]

    # Rule: portal push requires recent portal activity. A 90-day cutoff
    # is a proxy for "patient still uses the portal". Push to a dormant
    # app is wasted effort at best, creepy at worst.
    last_login_iso = patient.get("portal_last_login")
    if last_login_iso:
        last_login = datetime.datetime.fromisoformat(last_login_iso)
        cutoff = datetime.datetime.now(timezone.utc) - timedelta(days=90)
        if last_login < cutoff:
            candidates = [c for c in candidates if c != "portal_push"]
    else:
        # Never logged in: remove portal_push.
        candidates = [c for c in candidates if c != "portal_push"]

    # Rule: quiet hours removes SMS and voice (but not email or push,
    # which don't ring). The quiet-hours check here is a safety net;
    # Step 1 already tries to avoid scheduling into quiet hours.
    patient_tz = ZoneInfo(patient.get("timezone", "UTC"))
    local_hour = send_time_utc.astimezone(patient_tz).hour
    in_quiet_hours = (local_hour >= QUIET_HOURS_START) or (local_hour < QUIET_HOURS_END)
    if in_quiet_hours:
        candidates = [c for c in candidates if c not in ("sms", "voice")]

    logger.info(
        "Patient %s eligible channels: %s (opt_outs=%s)",
        patient_id, candidates, sorted(opt_outs),
    )
    return candidates, patient
```

---

## Step 3: Score Candidate Channels with Thompson Sampling

*The pseudocode calls this `score_and_select(patient_id, candidates)`. This is the recommendation core. For each eligible channel, we maintain a Beta posterior over the channel's confirmation probability for this specific patient. Sample once from each, pick the highest. Channels with few observations have wide posteriors and naturally get explored. Channels with many observations have tight posteriors and get selected when they're actually best.*

```python
def score_and_select(patient_id: str, candidates: list) -> tuple:
    """
    Pick a channel for this patient using Thompson sampling.

    For each candidate channel, fetches the Beta(alpha, beta) posterior
    from DynamoDB (or initializes from the cold-start prior if none
    exists), samples one value from Beta(alpha, beta), and picks the
    channel with the highest sampled value.

    Returns a tuple of (selected_channel, all_scores) so the scores can
    be logged to the decision record for audit.

    The elegance of Thompson sampling: exploration is automatic. Channels
    with small alpha+beta (few observations) produce wide, uncertain
    distributions that will occasionally sample very high values, forcing
    the system to try them. Channels with large alpha+beta produce tight
    distributions that rarely get "lucky" unless their mean is actually
    high. Over many decisions, this balances exploration and exploitation
    without any tuning of an epsilon knob.
    """
    if not candidates:
        return None, {}

    bandit_table = dynamodb.Table(BANDIT_TABLE)
    scores = {}

    for channel in candidates:
        # The partition key is patient_id, sort key is channel. This
        # makes "get all arm states for this patient" a single Query,
        # and "update one arm" a single UpdateItem.
        response = bandit_table.get_item(
            Key={"patient_id": patient_id, "channel": channel}
        )
        state = response.get("Item")

        if state is None:
            # Cold start: no data yet for this (patient, channel).
            # Fall back to the cohort-level prior. In production, the
            # prior would be looked up by cohort (age bucket, visit type,
            # etc.); here we use a system-wide prior for simplicity.
            alpha = float(COLD_START_PRIOR_ALPHA)
            beta = float(COLD_START_PRIOR_BETA)
        else:
            # DynamoDB stores numbers as Decimal. Convert to float for the
            # random.betavariate call. This is a narrow conversion that
            # can lose precision for very large alpha/beta, but reminder
            # counts don't get that big.
            alpha = float(state["alpha"])
            beta = float(state["beta"])

        # Draw one sample from Beta(alpha, beta). random.betavariate is
        # in the Python standard library; no numpy required. For higher
        # throughput you would batch this with numpy.random.beta.
        sampled_score = random.betavariate(alpha, beta)
        scores[channel] = sampled_score

        logger.debug(
            "Channel %s: Beta(%.2f, %.2f), sampled=%.4f",
            channel, alpha, beta, sampled_score,
        )

    # argmax: pick the channel with the highest sample.
    selected_channel = max(scores, key=scores.get)

    logger.info(
        "Patient %s selected channel=%s from candidates=%s (scores=%s)",
        patient_id, selected_channel, candidates,
        {k: round(v, 4) for k, v in scores.items()},
    )
    return selected_channel, scores
```

---

## Step 4: Compose and Dispatch the Reminder

*The pseudocode calls this `dispatch(patient, appointment, channel)`. Once a channel is picked, compose the reminder with minimum-necessary PHI, log the decision before dispatching (so we have a record even if dispatch fails), and send through the appropriate AWS service. Each message carries a unique reminder_id that rides along through delivery receipts and comes back on engagement events in Step 5.*

```python
def dispatch(patient: dict, appointment: dict, channel: str,
             scores: dict) -> str:
    """
    Compose and send the reminder through the selected channel.

    Returns the reminder_id (UUID) that uniquely identifies this dispatch.
    The reminder_id is stored in the decision record and is included as a
    tag/attribute on the outbound message so delivery receipts and
    engagement events can be joined back to the decision.

    HIPAA minimum-necessary: the message reveals the provider and the
    appointment time, but not the clinical reason for the visit. Patients
    who want more detail in reminders can opt in via their preference
    center; the default is the minimum-necessary baseline.
    """
    reminder_id = str(uuid.uuid4())

    # Compose the content object. Keep it channel-agnostic; the channel-
    # specific renderers below turn it into SMS/email/voice format.
    content = {
        "patient_first_name": patient.get("first_name", ""),
        "provider_last_name": appointment.get("provider_last_name", ""),
        # Format the appointment time in the patient's local timezone.
        # Reminders that quote UTC or the clinic's zone confuse patients.
        "appt_datetime_local": _format_local_time(
            appointment["start_iso"], patient.get("timezone", "UTC")
        ),
        "confirm_url": f"https://example.com/confirm/{reminder_id}",
    }

    # Log the decision BEFORE dispatching. If dispatch fails partway,
    # we still have an audit record of what we decided. Also, writing
    # before dispatch gives us an idempotency anchor: the engagement
    # event processor can find the decision even if the messaging API
    # returned an error we didn't handle.
    decisions_table = dynamodb.Table(DECISIONS_TABLE)
    decisions_table.put_item(
        Item={
            "reminder_id": reminder_id,
            "patient_id": patient["patient_id"],
            "appointment_id": appointment["id"],
            "channel": channel,
            "decision_time": datetime.datetime.now(timezone.utc).isoformat(),
            "model_version": "thompson-v1.0",
            # Store the candidate scores so we can later analyze how often
            # the model picked the best-scoring option, and how close the
            # runner-up was. DynamoDB stores numbers as Decimal.
            "candidate_scores": {k: Decimal(str(round(v, 4)))
                                  for k, v in scores.items()},
        }
    )

    # Dispatch via the selected channel. Each branch uses the appropriate
    # AWS service. In production, you would also handle partial failures
    # (message accepted by SNS but rejected by carrier) explicitly.
    try:
        if channel == "sms":
            _send_sms(patient["phone"], content, reminder_id)
        elif channel == "email":
            _send_email(patient["email"], content, reminder_id)
        elif channel == "voice":
            # Voice dispatch goes through Amazon Connect's outbound API.
            # Omitted in this example because Connect setup is non-trivial.
            # In production you would call connect.start_outbound_voice_contact
            # with the contact flow that plays the reminder script.
            logger.warning("Voice channel selected but not implemented in example")
        elif channel == "portal_push":
            # Push delivery is via your mobile app's push infrastructure
            # (SNS Mobile Push to APNs/FCM). IMPORTANT: APNs and FCM are
            # NOT typically BAA-covered. Do NOT send PHI in the push
            # payload. Send a content-free notification ("You have a new
            # reminder") and have the app fetch details from your
            # BAA-covered backend via an authenticated API call.
            # See the architecture companion for the full pattern.
            logger.warning("Push channel selected but not implemented in example")
        else:
            raise ValueError(f"Unknown channel: {channel}")

        logger.info(
            "Dispatched reminder_id=%s channel=%s to patient=%s",
            reminder_id, channel, patient["patient_id"],
        )
    except Exception as exc:
        # Log but don't re-raise: the decision record is already written,
        # and a dispatch failure should be an observable event, not a
        # crash that the caller has to handle. The engagement processor
        # will see no delivery event for this reminder and can treat that
        # as a failure signal.
        logger.exception(
            "Dispatch failed for reminder_id=%s channel=%s: %s",
            reminder_id, channel, exc,
        )

    return reminder_id

def _send_sms(phone: str, content: dict, reminder_id: str) -> None:
    """Send an SMS reminder via SNS. For scale, migrate to AWS End User Messaging SMS."""
    message_body = (
        f"Hi {content['patient_first_name']}, this is a reminder of your "
        f"appointment with Dr. {content['provider_last_name']} on "
        f"{content['appt_datetime_local']}. Confirm: {content['confirm_url']}. "
        f"Reply STOP to opt out."
    )

    # SNS.Publish to a phone number directly (transactional SMS).
    # Note: SNS SMS delivery-status logs (CloudWatch Logs records emitted
    # when you configure a delivery-status role) reference the SNS-generated
    # MessageId, not custom MessageAttributes. Custom attributes do NOT
    # propagate to delivery receipts. For production event joining,
    # capture response["MessageId"] from publish() and persist it on the
    # decision record, then join delivery logs to decisions on MessageId.
    # (SES behaves differently: the Tags parameter below does propagate to
    # SES engagement events via the configuration set.)
    sns_client.publish(
        PhoneNumber=phone,
        Message=message_body,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {
                "DataType": "String",
                "StringValue": "Transactional",  # Not "Promotional"; this is a reminder
            },
        },
    )

def _send_email(email: str, content: dict, reminder_id: str) -> None:
    """Send an email reminder via SES with reminder_id tag for event linkage."""
    subject = "Appointment reminder"
    html_body = f"""
    <p>Hi {content['patient_first_name']},</p>
    <p>This is a reminder of your appointment with
    Dr. {content['provider_last_name']} on {content['appt_datetime_local']}.</p>
    <p><a href="{content['confirm_url']}">Confirm your appointment</a></p>
    <p><a href="{content['confirm_url']}?action=unsubscribe">Unsubscribe</a></p>
    """
    text_body = (
        f"Hi {content['patient_first_name']},\n\n"
        f"Reminder: appointment with Dr. {content['provider_last_name']} "
        f"on {content['appt_datetime_local']}.\n\n"
        f"Confirm: {content['confirm_url']}\n"
    )

    # SES.SendEmail with Tags attaches the reminder_id to every engagement
    # event (delivery, open, click, bounce, complaint) that the configuration
    # set publishes. That is the link that makes the feedback loop possible.
    ses_client.send_email(
        Source=SES_FROM_ADDRESS,
        Destination={"ToAddresses": [email]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html_body, "Charset": "UTF-8"},
                "Text": {"Data": text_body, "Charset": "UTF-8"},
            },
        },
        ConfigurationSetName=SES_CONFIGURATION_SET,
        Tags=[{"Name": "reminder_id", "Value": reminder_id}],
    )

def _format_local_time(iso_string: str, tz_name: str) -> str:
    """Format an ISO timestamp as a patient-friendly local time string."""
    dt = datetime.datetime.fromisoformat(iso_string)
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    # Example output: "Friday, May 15 at 02:30 PM EDT"
    # Note: %-d / %-I (no-pad) are POSIX extensions that work on Linux
    # (Lambda runtime) and macOS but raise ValueError on Windows. Use
    # zero-padded %d / %I for cross-platform portability.
    return local_dt.strftime("%A, %B %d at %I:%M %p %Z")
```

---

## Step 5: Close the Feedback Loop

*The pseudocode calls this `process_engagement_event(event)`. Engagement events (delivered, opened, confirmed, no-show, kept) arrive on an event bus. Each event carries the reminder_id set in Step 4. We look up the decision, compute the reward, and update the Beta posterior. This is the step most teams under-invest in, and it is the step that makes the bandit actually learn.*

```python
def process_engagement_event(event: dict) -> None:
    """
    Update the bandit posterior based on an engagement event.

    Expected event shape (example):
      {
        "reminder_id": "b24f1ac0-7d29-4e31-9e15-a8f40e7f2180",
        "event_type": "PATIENT_CONFIRMED" | "APPOINTMENT_KEPT"
                    | "APPOINTMENT_NO_SHOW" | "DELIVERED" | "OPENED",
        "timestamp": "2026-05-04T14:02:00Z"
      }

    Rewards are binary: +1 for confirmation or kept appointment, 0 for
    no-show. Intermediate events (delivered, opened) are tracked for
    monitoring but do NOT update the bandit. The bandit's reward is the
    business outcome (did the patient show up), not the intermediate
    engagement signal. Conflating the two is how you end up optimizing
    for clicks instead of outcomes.
    """
    reminder_id = event.get("reminder_id")
    event_type = event.get("event_type")

    if not reminder_id or not event_type:
        logger.warning("Engagement event missing reminder_id or event_type: %s", event)
        return

    # Look up the original decision for this reminder. If the decision
    # isn't found, log and skip: the reminder_id is malformed or the
    # event predates decision logging.
    decisions_table = dynamodb.Table(DECISIONS_TABLE)
    response = decisions_table.get_item(Key={"reminder_id": reminder_id})
    decision = response.get("Item")
    if decision is None:
        logger.warning("No decision found for reminder_id=%s", reminder_id)
        return

    # Map event types to rewards. Only business-outcome events get a reward.
    reward = None
    if event_type in ("PATIENT_CONFIRMED", "APPOINTMENT_KEPT"):
        reward = 1
    elif event_type == "APPOINTMENT_NO_SHOW":
        reward = 0
    # Intermediate events (DELIVERED, OPENED, CLICKED, BOUNCED, COMPLAINED)
    # are valuable for monitoring but do NOT update the bandit posterior.
    # We still emit them as metrics below.

    # Emit the event as a CloudWatch metric, sliced by channel. This is
    # what powers the channel-performance and fairness dashboards.
    _emit_event_metric(decision["channel"], event_type)

    if reward is None:
        # Intermediate event: metric emitted, no bandit update.
        return

    # Update the Beta-Binomial posterior for this (patient, channel) pair.
    # This is the entire math of Thompson sampling: increment alpha on
    # success, beta on failure. DynamoDB's ADD action is atomic, so even
    # concurrent updates to the same arm are race-free.
    #
    # One subtlety: if this is the first observation for this (patient, channel)
    # pair, the item doesn't exist yet and we want to seed it with the cold-start
    # prior PLUS the current observation. DynamoDB's ADD on a non-existent
    # attribute starts from 0, which would ignore our prior. The if_not_exists
    # trick below handles the seeding atomically.
    bandit_table = dynamodb.Table(BANDIT_TABLE)
    patient_id = decision["patient_id"]
    channel = decision["channel"]

    update_expression = (
        "SET alpha = if_not_exists(alpha, :prior_alpha) + :inc_alpha, "
        "    beta = if_not_exists(beta, :prior_beta) + :inc_beta, "
        "    last_updated = :ts"
    )
    expression_attribute_values = {
        ":prior_alpha": COLD_START_PRIOR_ALPHA,
        ":prior_beta": COLD_START_PRIOR_BETA,
        ":inc_alpha": Decimal("1") if reward == 1 else Decimal("0"),
        ":inc_beta": Decimal("1") if reward == 0 else Decimal("0"),
        ":ts": datetime.datetime.now(timezone.utc).isoformat(),
    }

    bandit_table.update_item(
        Key={"patient_id": patient_id, "channel": channel},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attribute_values,
    )

    # Emit the reward as a metric, sliced by channel. Production systems
    # also slice by cohort (age band, visit type, insurance) to catch
    # subgroup disparities. Slicing by patient-identifying dimensions in
    # CloudWatch is tricky because high-cardinality dimensions balloon
    # metric costs; use low-cardinality cohort buckets instead.
    cloudwatch_client.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": "reminder_reward",
            "Value": reward,
            "Unit": "None",
            "Dimensions": [
                {"Name": "channel", "Value": channel},
            ],
        }],
    )

    logger.info(
        "Updated bandit: patient=%s channel=%s reward=%d event=%s",
        patient_id, channel, reward, event_type,
    )

def _emit_event_metric(channel: str, event_type: str) -> None:
    """Emit a count metric for an engagement event, sliced by channel and type."""
    cloudwatch_client.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": "engagement_event",
            "Value": 1,
            "Unit": "Count",
            "Dimensions": [
                {"Name": "channel", "Value": channel},
                {"Name": "event_type", "Value": event_type},
            ],
        }],
    )
```

---

## Putting It All Together

Here is the full reminder pipeline assembled. In production these functions live in separate Lambdas (appointment-event handler, recommender, engagement-event consumer); this example runs them inline so you can trace a single reminder end to end.

```python
def run_end_to_end_example():
    """
    Demonstrates the full reminder pipeline with synthetic data.

    Flow:
      1. Seed a synthetic patient in DynamoDB
      2. Create an appointment and schedule the reminders
      3. Simulate a schedule firing: pick a channel and dispatch
      4. Simulate an engagement event: update the bandit

    This is NOT how the system runs in production. Each step is triggered
    by a different event source (EHR webhook, EventBridge schedule firing,
    SES/SNS engagement event). The example just chains them together for
    clarity.
    """
    # --- Setup: seed a synthetic patient ---
    patient_id = "pat-synthetic-001"
    patients_table = dynamodb.Table(PATIENT_TABLE)
    patients_table.put_item(Item={
        "patient_id": patient_id,
        "first_name": "Jordan",
        "phone": "+15555551234",
        "email": "jordan@example.com",
        "timezone": "America/New_York",
        "sms_consent": True,
        "voice_consent": False,
        "opt_outs": [],
        "portal_last_login": (
            datetime.datetime.now(timezone.utc) - timedelta(days=14)
        ).isoformat(),
    })

    # --- Step 1: Appointment is booked ---
    appointment = {
        "id": "appt-synthetic-999",
        "patient_id": patient_id,
        "provider_last_name": "Smith",
        "start_iso": (
            datetime.datetime.now(timezone.utc) + timedelta(days=2, hours=3)
        ).isoformat(),
        "patient_timezone": "America/New_York",
    }
    print("Step 1: Scheduling reminders for appointment...")
    schedules = on_appointment_created(appointment)
    print(f"  Created {len(schedules)} schedule(s): {schedules}")

    # --- Step 2-4: Simulate a schedule firing ---
    # In production, EventBridge Scheduler invokes the recommender Lambda
    # with this payload at the right moment. Here we just call directly.
    print("\nStep 2: Fetching eligible channels...")
    now_utc = datetime.datetime.now(timezone.utc)
    eligible, patient = get_eligible_channels(patient_id, now_utc)
    print(f"  Eligible: {eligible}")

    print("\nStep 3: Thompson sampling to select channel...")
    selected_channel, scores = score_and_select(patient_id, eligible)
    print(f"  Selected: {selected_channel}")
    print(f"  Scores: {scores}")

    print("\nStep 4: Composing and dispatching reminder...")
    reminder_id = dispatch(patient, appointment, selected_channel, scores)
    print(f"  Dispatched reminder_id={reminder_id}")

    # --- Step 5: Simulate an engagement event ---
    # In production, this arrives asynchronously from SES, SNS, or the
    # appointment outcome feed from the EHR.
    print("\nStep 5: Simulating PATIENT_CONFIRMED event...")
    process_engagement_event({
        "reminder_id": reminder_id,
        "event_type": "PATIENT_CONFIRMED",
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    })
    print("  Bandit posterior updated. Alpha for this arm +1.")

if __name__ == "__main__":
    # This example assumes the three DynamoDB tables already exist:
    #   - patient-profile    (partition key: patient_id)
    #   - bandit-state       (partition key: patient_id, sort key: channel)
    #   - reminder-decisions (partition key: reminder_id)
    # And that SES/SNS origination identities are configured.
    #
    # Without those, the boto3 calls will fail. Stand up the tables with
    # aws dynamodb create-table (or CDK/CloudFormation) before running.
    run_end_to_end_example()
```

---

## The Gap Between This and Production

This example demonstrates the Thompson-sampling channel-optimization pattern end to end. Run it against a synthetic patient and it will schedule reminders, filter by hard constraints, select a channel, dispatch (email and SMS branches at least), and update the bandit when an engagement event arrives. The distance between this and a production deployment is significant. Here is where it lives.

**Consent and opt-out management is its own service.** The example treats `sms_consent`, `voice_consent`, and `opt_outs` as fields on the patient profile. In production you need a consent ledger that records every consent grant, every revocation, the channel and timestamp of each event, and the source of truth (patient portal, registration form, STOP reply, unsubscribe click). TCPA violations are typically $500 to $1,500 per message, statutory. CAN-SPAM is lower per-incident but still real. The consent ledger is first-class infrastructure, not a DynamoDB attribute.

**Delivery events and reward joining need real plumbing.** The example's `process_engagement_event` accepts a dict and trusts the reminder_id field. In production, engagement events arrive from at least three different sources in three different formats: SES publishes to SNS topics (or EventBridge) with its own payload shape, SNS SMS publishes delivery receipts that require separate configuration to even emit the reminder_id, and appointment outcomes come from your scheduling system in whatever format it happens to use. Normalizing those into a single event schema is a dedicated service, typically a Lambda per source that transforms and forwards to Kinesis or EventBridge.

**Cohort-level cold-start priors are a separate pipeline.** The example uses a single system-wide Beta(2, 2) prior. That is fine for illustration and terrible for production. A real system computes per-cohort priors offline (an aggregation over historical reminder outcomes sliced by age band, visit type, prior engagement, language preference) and stores them in a small lookup table. That pipeline has to be careful about fairness (don't use proxies that encode disparities), privacy (k-anonymity thresholds so small cohorts don't leak PHI), and recency (refresh at least quarterly).

**DynamoDB schema design matters a lot.** The example uses simple single-attribute keys. Production needs access patterns for "all open decisions for this appointment" (needed for Step 1b cancellation), "all reminders for this patient in the last 30 days" (needed for engagement dashboards), and "channel-level aggregate metrics" (needed for the fairness dashboard). Design GSIs around these access patterns before you go live. A composite sort key like `{decision_time}#{channel}` opens up time-range queries per patient without a full scan.

**VPC endpoints and encryption are required, not optional.** The example makes API calls over the public AWS endpoints. A production Lambda handling PHI runs inside a VPC with private subnets and VPC endpoints for DynamoDB, SNS, SES, Scheduler, and CloudWatch Logs. All three DynamoDB tables should be encrypted at rest with a customer-managed KMS key (not the AWS-owned default), and all CloudWatch log groups should be KMS-encrypted because Lambda logs will inevitably include PHI fragments in exception traces.

**Idempotency on the recommender.** EventBridge Scheduler delivers at-least-once. If your recommender Lambda fails partway through (after logging the decision but before dispatching), Scheduler can re-fire and you could dispatch the same reminder twice. Use a deterministic key (`appointment_id + offset_hours`) to check whether a decision for this (appointment, offset) already exists in the decisions table. If it does, return early. The example doesn't do this.

**Rate limits and burst handling.** Monday morning is a reminder stampede: every appointment scheduled for the week gets its T-72h reminder fired within a narrow window. SES has a sending rate limit (per second, per account), SNS SMS has a per-origination-number throughput, and DynamoDB tables have per-partition write limits. For the volumes a mid-size practice sees, none of this is a problem; at health-system scale, you need queueing (SQS in front of the recommender) and sending-rate-aware dispatch logic.

**Fairness monitoring with actual humans.** The example emits a `reminder_reward` metric dimensioned by channel. Production should also dimension it by low-cardinality cohort (age band, preferred-language bucket, primary care panel) so the fairness dashboard can surface subgroup regressions. And someone needs to look at that dashboard. Monthly, not yearly. "The dashboard exists" and "the dashboard is acted upon" are different sentences.

**True outcome vs. proxy reward.** The example treats PATIENT_CONFIRMED and APPOINTMENT_KEPT identically. In practice, a confirmation is a fast proxy for the true outcome (show rate) that takes days to arrive. The right pattern is: update the bandit immediately on the fast proxy, then retrospectively correct (decrement the success and increment the failure) if the appointment ended up being a no-show despite the confirmation. The example skips the correction step, which is fine for a Beta-Binomial where counts are small, but matters at production scale.

**Contact flow for voice and push infrastructure.** The example stubs out the voice and portal_push branches with log messages. Voice dispatch through Amazon Connect requires a contact flow that handles "press 1 to confirm," DTMF response capture, transcript retention under the BAA, and at least cursory call recording policy. Push dispatch assumes you have a mobile app with a registered push endpoint per patient. Both are meaningful engineering efforts in their own right.

**Synthetic data and testing.** There are no tests. A production pipeline has: unit tests for the Thompson-sampling math (sampling from known posteriors produces the expected argmax distribution), integration tests that exercise the DynamoDB + Scheduler round-trip, regression tests that confirm opt-outs are honored even when model scores prefer the opted-out channel, and load tests at expected burst traffic. Tests should use synthetic patients exclusively; never use real PHI in non-production environments.

**Alert on bandit staleness.** If the engagement-event consumer falls behind or silently fails, the bandit state stops updating and the model slowly drifts toward its initial posterior. Monitor the lag between dispatch and last-update for each (patient, channel) arm and alert when it exceeds a threshold.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.1: Appointment Reminder Channel Optimization](chapter04.01-appointment-reminder-channel-optimization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
