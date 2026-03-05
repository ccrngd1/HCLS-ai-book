# Expert Review: Recipe 1.7 - Prescription Label OCR

**Reviewer:** Technical Expert Panel (Security · Architecture · Networking)
**Date:** 2026-03-05
**Verdict:** APPROVE WITH REQUIRED FIXES
**Blocking Issues:** 4 (PHI in logs, cost discrepancy, SIG punctuation, RxNorm concept type missing)
**Advisory Issues:** 9

---

## Executive Summary

Recipe 1.7 is well-structured and covers the happy path thoroughly. The pharmacy domain explanation is strong, and the "Why This Isn't Production-Ready" section demonstrates good self-awareness. However, the recipe has a meaningful gap between its cost model and its code (Comprehend Medical text volume), leaves PHI logging unaddressed, underspecifies the SIG parser in ways that will cause production failures, and omits RxNorm concept type guidance that downstream systems will need. Four items require resolution before publication. Nine advisory items should be addressed or explicitly accepted as known gaps.

---

## Security Review

### BLOCKER S-1: PHI Leaking into CloudWatch Logs

**Finding:** The recipe instructs developers to use CloudWatch for "Logs, metrics, and alarms" but provides no guidance on what must NOT be logged. The Lambda orchestrator processes patient name, medication, dosage, prescriber, pharmacy, and Rx number. A developer following this recipe will naturally log intermediate values for debugging. Every `print()` or `logger.info()` call with an extracted field writes PHI to CloudWatch, which requires the same KMS encryption controls as S3 and DynamoDB. The recipe does not mention CloudWatch log group encryption, PHI log sanitization, or the requirement to disable detailed debug logging in production.

**Fix:** Add an explicit warning box in the Prerequisites section:

> WARNING: Lambda log output is PHI in this pipeline. All CloudWatch log groups for this function must use KMS encryption (via the `kmsKeyId` parameter on the log group). In production, structured logging must redact or omit extracted field values. Log only non-PHI signals: image key suffix (not path), confidence score ranges, boolean flags, latency, error codes. A code comment in the walkthrough saying "# do not log field values in production" is not optional.

Add the CloudWatch Logs VPC endpoint to the VPC section alongside the existing guidance about the endpoint being required for private subnets. That section is already good; extend it to require the KMS key on the log group.

---

### BLOCKER S-2: Mobile Photo EXIF Metadata Contains PHI

**Finding:** Prescription label photos taken on member smartphones carry EXIF metadata: GPS coordinates (home address), device model, timestamp, and sometimes the device's advertising identifier. This metadata is stored unmodified in S3 when the image is uploaded. GPS coordinates at pharmacy label capture time are likely the member's home address, which is PHI under HIPAA's Safe Harbor identifiers. The recipe does not mention EXIF stripping.

**Fix:** Add a preprocessing step in the pipeline (before or at S3 ingest) that strips EXIF metadata. In the mobile app layer, this can be done before upload (preferred). In the Lambda, it can be done before passing the image to Textract. Libraries: Python Pillow (`Image.open()` then `Image.save()` without copying EXIF info), or `piexif` for surgical removal. Add a note in the Prerequisites section that the S3 presigned URL upload flow should be accompanied by client-side EXIF removal, with Lambda-side stripping as a defense-in-depth fallback.

---

### Advisory S-3: No S3 Image Retention Policy

**Finding:** Prescription label images (raw photos of PHI) are stored in S3 indefinitely. There is no mention of S3 lifecycle rules to expire or transition raw images after confirmed processing. Retaining raw label images long-term expands the PHI surface area unnecessarily. Once a label is successfully processed and the structured record written to DynamoDB, the original image serves only audit or reprocessing purposes.

**Fix:** Add an S3 lifecycle policy recommendation in Prerequisites: transition raw images to S3 Glacier Instant Retrieval after 90 days, and delete after the organization's HIPAA retention period (typically 6 years from date of service for patient records). If the image is needed for appeal or audit, the DynamoDB record with confidence scores and raw extracted values is sufficient; the image itself is the riskiest artifact.

---

### Advisory S-4: RxNorm Confidence Threshold Too Low for Clinical Safety Pipelines

**Finding:** The recipe sets `RXNORM_CONFIDENCE_THRESHOLD = 0.70` and correctly notes this is a starting point to calibrate. However, the text does not quantify the clinical safety risk of a wrong RxNorm mapping at 70% confidence. Comprehend Medical's own published benchmarks show a non-trivial false-positive rate below 80% confidence. A wrong RxNorm concept passed to a drug interaction checker produces a false safety signal that a clinician must investigate, or worse, a missed interaction if the wrong concept silently routes around a real one.

**Fix:** Change the default threshold to 0.85 and add an explicit note:

> For any downstream use case that touches clinical decision support (drug interaction checking, formulary matching, dose range checking), use 0.85 or higher. The 0.70 threshold is appropriate only for informational display where a member sees the result and can correct it. Document your threshold choice and its rationale in your risk assessment.

---

### Advisory S-5: API Gateway TLS Enforcement Not Stated

**Finding:** The recipe mentions "Expose via API" and "put API Gateway in front" for synchronous use but never states that the API must enforce TLS 1.2+. The structured medication record returned by API Gateway contains PHI. The API cannot permit HTTP (unencrypted) traffic.

**Fix:** Add to the Prerequisites table: "API Gateway: minimum TLS policy set to TLS_1_2 on the custom domain; HTTP endpoint disabled; all traffic encrypted in transit."

---

## Architecture Review

### BLOCKER A-1: Comprehend Medical Text Input Contradicts Cost Estimate

**Finding:** The pseudocode in Step 5 passes only `drug_name + " " + dosage` to Comprehend Medical. "Amoxicillin 500mg" is 18 characters. At the current Comprehend Medical pricing of $0.01 per 100 characters with a 100-character minimum per request, that call costs $0.01, not the $0.03-$0.05 stated in the Prerequisites cost estimate. The cost estimate calculates against "a typical label runs 300-500 characters," but the code does not send 300-500 characters.

There are two ways to resolve this. Either the code is right and the cost estimate is wrong (actual Comprehend Medical cost per label is ~$0.01, total pipeline ~$0.06), or the cost estimate is right and the code should pass the full reconstructed label text to Comprehend Medical for better entity context (which would also improve RxNorm accuracy).

Passing only drug name + dosage is the weaker choice architecturally. Comprehend Medical's entity model performs better with surrounding clinical context: route, frequency, and indication text help disambiguate similar drug names and confirm the correct dosage form. Passing the full normalized label text (all key-value pairs concatenated) gives the model the context it was trained on.

**Fix:** Update Step 5 to assemble and pass the full normalized label text:

```
medication_text = concatenate all values from normalized_fields
                  into a single text passage
// e.g., "Drug: Amoxicillin 500mg Directions: Take 1 CAP PO TID x 7d
//         Prescriber: Dr. Sarah Chen Refills: 0 NDC: 00093-4155-21"
```

Then update the cost estimate: Comprehend Medical charge is $0.03-$0.05 for 300-500 characters of full label text. Total pipeline cost ~$0.08-$0.10. This aligns the code with the estimate and improves NLP accuracy in one change.

---

### BLOCKER A-2: SIG Decoder Fails on Punctuation-Attached Abbreviations

**Finding:** The `decode_sig()` function splits on whitespace and does a direct lowercase lookup. Real prescription labels produce tokens like "BID." (period for end of sentence), "PRN/pain" (slash-separated), "1-2 tabs" (count range with hyphen), "q4-6h" (range frequency), and "BID;" (semicolon separator). None of these tokenize to clean dictionary keys. "bid." != "bid" fails the lookup silently, and the literal "BID." passes through to the output unchanged instead of being decoded to "twice daily."

Additionally, the decoder does not handle the "x" duration prefix. "x 14d" should decode to "for 14 days" but "x" is not in the codebook, so it passes through as literal "x."

**Fix:** Modify `decode_sig()` to strip trailing and leading punctuation before lookup:

```
FUNCTION decode_sig(raw_sig):
    words = split raw_sig on whitespace
    decoded = []
    FOR each word in words:
        clean = strip leading and trailing punctuation from word
        lookup = lowercase(clean)
        IF lookup == "x":
            append "for" to decoded
        ELSE IF lookup is in SIG_CODES:
            append SIG_CODES[lookup] to decoded
        ELSE:
            append word to decoded  // preserve original with punctuation for unknown tokens
    RETURN join decoded with single space
```

Also add these missing high-frequency entries to `SIG_CODES`:

```
// Missing route codes
"im":    "by intramuscular injection",
"iv":    "intravenously",
"sq":    "subcutaneously",
"subq":  "subcutaneously",
"opth":  "in the eye",
"od":    "in the right eye",
"os":    "in the left eye",
"ou":    "in both eyes",

// Missing frequency codes
"qw":    "once weekly",
"q2w":   "every 2 weeks",
"qm":    "once monthly",
"qam":   "every morning",
"qpm":   "every evening",

// Missing duration/timing helpers
"x":     "for",
"wk":    "week",
"wks":   "weeks",
"mo":    "month",
"d":     "day",

// Missing contextual
"nte":   "not to exceed",
"daw":   "dispense as written"
```

The text says "about 150 common abbreviations cover the vast majority." The current codebook has 35 entries. That gap is not acceptable to leave undisclosed. Add a callout box noting the 35-entry codebook is illustrative and that production deployment requires expanding to a full reference set (NCPDP, USP references are already cited in the recipe).

---

### Advisory A-3: RxNorm Concept Type (TTY) Not Returned or Filtered

**Finding:** The recipe returns `rxnorm_id` and `description` but not the RxNorm term type (TTY). RxNorm concepts include ingredient-level (IN: "amoxicillin"), clinical drug (SCD: "amoxicillin 500 MG oral capsule"), branded drug (SBD: "Amoxil 500 MG oral capsule"), and clinical drug pack (GPCK/BPCK). Downstream systems need the TTY to know what they received. A drug interaction checker operates at the IN level. A formulary system needs SCD or SBD. A medication reconciliation tool needs SCD at minimum. Without TTY, downstream consumers have to re-query RxNorm to determine concept type, which adds latency and complexity.

**Fix:** Add `concept_type` to the returned mapping object:

```
{
    detected_text:   entity.Text,
    rxnorm_id:       concept.Code,
    description:     concept.Description,
    concept_type:    concept.Type,    // e.g., "SCD", "IN", "SBD"
    confidence:      round(concept.Score, 3)
}
```

Add a note in the "RxNorm concept selection" paragraph of "Why This Isn't Production-Ready" that recommends filtering by TTY based on downstream use case, with examples: prefer SCD for clinical use, IN for interaction checking.

---

### Advisory A-4: Synchronous and Asynchronous Patterns Are Conflated

**Finding:** The architecture uses an S3 event trigger (inherently asynchronous: Lambda runs after the upload completes, not while the member waits). The text then says "For member-facing synchronous use (upload image, get structured record back immediately), put API Gateway in front." These are two entirely different deployment topologies and the recipe presents them as if one modifies the other. In the async S3-event model, the member's app uploads and waits for... what? Polling? A webhook callback? A push notification? This is not described.

**Fix:** Add a short "Deployment Topology" section with two explicit patterns:

> **Synchronous (member-facing):** Member app sends image via POST to API Gateway, which invokes Lambda directly. Lambda calls Textract and Comprehend Medical, assembles the record, writes to DynamoDB, and returns the structured JSON in the HTTP response. Latency: 2-5 seconds. The S3 upload is still performed inside Lambda (for audit trail), but S3 events are not the trigger.

> **Asynchronous (bulk/background):** Member app uploads directly to S3 via presigned URL. S3 event triggers Lambda. Result is written to DynamoDB. Member app polls a status endpoint or receives a push notification when the record is ready.

The architecture diagram shows the async model. Note that explicitly.

---

### Advisory A-5: No Retry Logic for Transient API Failures

**Finding:** The pseudocode calls Textract and Comprehend Medical sequentially with no retry handling. Both services can return transient throttling errors (`ThrottlingException`, `ProvisionedThroughputExceededException`) and transient service errors. Without retry with exponential backoff, a single throttle causes the Lambda to fail, which goes to the DLQ (if configured) and requires manual reprocessing or SQS retry.

**Fix:** Add a note that all AWS API calls in this pipeline should use the SDK's built-in retry configuration with exponential backoff. For boto3: configure `botocore.config.Config(retries={'max_attempts': 3, 'mode': 'adaptive'})` on the client. Add this to the Prerequisites table as a reminder.

---

### Advisory A-6: NDC Segment Structure Validation Missing

**Finding:** The NDC validation step correctly strips hyphens and checks for 10-11 numeric digits. However, it does not validate segment structure. NDC codes follow a specific segment format (5-4-2 labeler-product-package is the most common, but 5-3-2 and 4-4-2 variants exist). The zero-padded 11-digit representation used by most payers and PBMs adds a leading zero to the labeler segment. A label printing "071-0155-23" is an NDC with a missing leading zero in the labeler segment; the cleaned value "071015523" is 9 digits and fails the current format check correctly, but "0071-0155-23" cleans to "0071015523" (10 digits, valid format) while still representing a specific segment structure that should be preserved. The sample output shows `"ndc_normalized": "00093415521"` (11 digits), which suggests zero-padding is applied somewhere, but the pseudocode does not show this logic.

**Fix:** Add explicit zero-padding to the NDC normalization step, normalizing all extracted NDCs to the 11-digit zero-padded standard:

```
FUNCTION normalize_ndc_to_11digit(ndc_raw):
    // Remove hyphens and spaces
    ndc_clean = remove all hyphens and spaces from ndc_raw

    IF ndc_clean matches "^[0-9]{10}$":
        // Ambiguous: could be 5-4-1, 4-4-2, or 5-3-2 without hyphens
        // Use original hyphenated format to determine segment boundaries
        // then zero-pad each segment to canonical 5-4-2 representation
        ... (segment detection logic using original hyphens)
        RETURN zero_padded_11digit

    ELSE IF ndc_clean matches "^[0-9]{11}$":
        RETURN ndc_clean

    ELSE:
        RETURN { valid: false, error: "NDC format not recognized" }
```

And link to the FDA NDC normalization guide for the segment padding rules.

---

## Networking Review

### Advisory N-1: VPC Interface Endpoint Costs Omitted

**Finding:** The Prerequisites section correctly lists VPC endpoints for S3, Textract, Comprehend Medical, DynamoDB, and CloudWatch Logs (5 endpoints total for a private Lambda). VPC Interface endpoints (Textract, Comprehend Medical, CloudWatch Logs) are priced at $0.01 per AZ per hour each. S3 and DynamoDB use Gateway endpoints (free). For a production deployment spanning 2 AZs with 3 interface endpoints:

```
3 endpoints x 2 AZs x $0.01/hr x 730 hrs/month = $43.80/month fixed overhead
```

This is independent of label volume. At 1,000 labels/month, the endpoint cost per label is $0.044, which nearly doubles the stated per-label cost of $0.08. At 100,000 labels/month, it is $0.0004 per label and negligible. The cost estimate is misleading at low volumes.

**Fix:** Add a cost footnote in the Prerequisites table:

> Note: VPC Interface endpoints for Textract, Comprehend Medical, and CloudWatch Logs add ~$44/month fixed overhead in a 2-AZ deployment. This cost is volume-independent. Below ~10,000 labels/month, endpoint overhead is material; above 100,000 labels/month, it is negligible. Factor this into the build-vs-share decision if this is a low-volume deployment.

---

### Advisory N-2: Member App Upload Path Not Defined

**Finding:** The architecture shows the member app uploading a photo to S3, but the recipe does not specify the upload mechanism. Two common patterns exist: (1) the app POSTs the image to API Gateway, which passes it to Lambda, which writes to S3; or (2) the backend generates a presigned S3 URL, the app uploads directly to S3 using that URL, and S3 event triggers Lambda. Pattern 1 sends PHI through API Gateway and Lambda before it hits S3. Pattern 2 means the presigned URL generation endpoint must be authenticated and the URL must have a short expiry (5-15 minutes). Neither is documented.

**Fix:** Specify the upload mechanism explicitly. The recommended pattern for mobile PHI upload is presigned URL with short expiry, scoped to a single object key, generated by an authenticated API endpoint. Add this to the architecture walkthrough under "Capture." Specify that the presigned URL generation endpoint must require a valid member authentication token (not be publicly accessible).

---

## Cost Estimate Verification

Current AWS pricing (verified 2026-03-05):

| Component | Chapter States | Actual Price | Status |
|---|---|---|---|
| Textract AnalyzeDocument (FORMS) | $0.05/page | $0.05/page (first 1M pages/month) | CORRECT |
| Comprehend Medical DetectEntitiesV2 | $0.01/100 chars | $0.01/unit (1 unit = 100 chars, 1-unit minimum) | CORRECT (unit pricing) |
| CM cost per label (code as written) | $0.03-$0.05 | $0.01 (drug_name + dosage only, ~18 chars) | INCORRECT - code sends ~18 chars, not 300-500 |
| CM cost per label (full text) | $0.03-$0.05 | $0.03-$0.05 (300-500 chars) | Correct IF code is updated per A-1 |
| Total per label | $0.08 | $0.06 (code as written) or $0.08-$0.10 (after fix) | Resolve per A-1 |
| VPC endpoint overhead | Not mentioned | ~$44/month fixed | Missing (see N-1) |
| Lambda + DynamoDB | "Negligible" | Negligible at reasonable scale | Acceptable |

The header says "~$0.08 per label." If A-1 is not fixed (code continues to pass only drug name + dosage), the correct header estimate is ~$0.06 per label. If A-1 is fixed (full label text passed), $0.08-$0.10 is correct. Either way, the current state is inconsistent.

---

## RxNorm Mapping Accuracy: Deeper Notes

The stated accuracy range of 88-96% for RxNorm mapping deserves qualification in the text.

**Cascading error problem:** The 88-96% range applies to clean clinical text input. In this pipeline, the input to Comprehend Medical is OCR output, which introduces character-level noise. An OCR confidence of 93% on "Lisinopril" produces an occasional "Lisinopni|" or "Lisin0pril" that the NLP model may not recognize or may map to a different compound. The stated accuracy benchmark likely comes from CM's own evaluation on clinical notes; real-world prescription OCR output will degrade it by 2-5 points depending on image quality.

**Suggested fix:** Add a note in the performance benchmarks table: "RxNorm mapping accuracy assumes clean OCR output. For curved or worn labels (75-90% field extraction accuracy), end-to-end RxNorm mapping accuracy may fall below 85% without image quality preprocessing." This sets realistic expectations and drives the UX guidance recommendation earlier in the recipe.

**Concept type gap:** As noted in A-3, the concept type is not returned. Without TTY, it is not possible to tell from the recipe's output whether the 88-96% accuracy refers to ingredient-level (IN) mapping, clinical drug (SCD) mapping, or both. These have meaningfully different accuracy profiles, with ingredient-level mapping being higher. This should be noted in the benchmarks.

---

## SIG Decoding Completeness: Gap Assessment

The text acknowledges a gap ("about 150 common abbreviations") against the 35-entry codebook. Additional abbreviations missing from current implementation that will appear in real prescription labels:

**Routes (high frequency):** IM (intramuscular), IV (intravenous), SQ/SubQ (subcutaneous), Opth (ophthalmic), OU/OD/OS (bilateral/right/left eye), top (topical - present in text, missing from code), patch, spray, puff, neb (nebulized).

**Frequencies (high frequency):** QW/QWK (weekly), Q2W/Q2WK (every 2 weeks), QM/QMO (monthly), QAM (every morning), QPM (every evening), Q24H (every 24 hours), Q48H (every 48 hours).

**Duration markers:** x (for - as in "x 14d"), d/day (day), wk/wks (week/weeks), mo/mos (month/months).

**Clinical context abbreviations commonly appearing in directions fields:** NTE (not to exceed), MDD (maximum daily dose), DAW (dispense as written), c (with, from Latin "cum"), s (without, from Latin "sine").

The QD/QID ambiguity mentioned in the text is real and the pseudocode does not address it. At the character level, an OCR misread of "QID" (4x/day) as "QD" (1x/day) produces a 4-fold dosing undercount. A mitigation is to check for this specific pair: if context includes a numeric count greater than 1 (e.g., "Take 2") and the frequency decoded to "once daily," flag for human review. Add this edge case to the "where it struggles" section.

---

## Issues Summary

| ID | Severity | Category | Issue |
|---|---|---|---|
| S-1 | BLOCKER | Security | PHI in CloudWatch logs, no log sanitization guidance |
| S-2 | BLOCKER | Security | EXIF metadata (GPS/device) not stripped from mobile photos |
| A-1 | BLOCKER | Architecture | Comprehend Medical text input contradicts cost estimate |
| A-2 | BLOCKER | Architecture | SIG decoder fails on punctuation-attached tokens; 115-abbreviation gap |
| S-3 | Advisory | Security | No S3 image retention/lifecycle policy |
| S-4 | Advisory | Security | RxNorm confidence threshold 70% too low for clinical safety use |
| S-5 | Advisory | Security | API Gateway TLS enforcement not stated |
| A-3 | Advisory | Architecture | RxNorm TTY (concept type) not returned; downstream systems need it |
| A-4 | Advisory | Architecture | Sync vs. async deployment topologies conflated |
| A-5 | Advisory | Architecture | No retry/backoff guidance for Textract and CM API calls |
| A-6 | Advisory | Architecture | NDC zero-padding and segment normalization not implemented |
| N-1 | Advisory | Networking | VPC interface endpoint fixed cost (~$44/month) missing from estimate |
| N-2 | Advisory | Networking | Member app upload path (presigned URL vs. API proxy) not defined |

---

## What the Recipe Does Well

- The pharmacy domain explanation is excellent: NDC vs. RxNorm distinction is clear and correctly motivated.
- The SIG codebook table in the domain section is genuinely useful as a reference.
- "Why This Isn't Production-Ready" is honest and covers DLQ, idempotency, NDC validation gap, and days supply handling. This section earns trust.
- VPC endpoint guidance is more complete than most recipes in this genre: the CloudWatch Logs endpoint catch is a real gotcha that teams routinely miss.
- BAA prerequisite is prominently listed.
- The related recipes section correctly threads the pipeline: 1.1 for structure, 1.3 for Comprehend Medical NLP, 3.3 for full reconciliation.
- The "Honest Take" section on curved labels, SIG maintenance, and RxNorm threshold calibration is practical and worth keeping.

---

*Review completed 2026-03-05. All issues require author response before publication. Blockers require code or text change; advisories require either a fix or an explicit "accepted gap" callout in the recipe.*
