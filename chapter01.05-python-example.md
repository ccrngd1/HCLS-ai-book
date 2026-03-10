# Recipe 1.5: Claims Attachment Processing: Python Example 

> **This is an illustrative implementation, not a production-ready deployment.**
> It demonstrates the patterns from the pseudocode walkthrough using boto3.
> A real deployment needs the additions listed in the "Gap to Production" section at the end.
> Start here to understand the concepts. Don't ship this as-is.

---

## Setup

```bash
pip install boto3
```

You'll also need:
- An AWS account with Bedrock, Textract, Comprehend Medical, DynamoDB, SNS, and S3 configured
- Nova Lite and Claude Sonnet 4.6 enabled in Bedrock Model Access (us-east-1)
- A signed AWS BAA covering PHI processing
- IAM permissions: `bedrock:InvokeModel`, `textract:StartDocumentAnalysis`, `textract:GetDocumentAnalysis`,
  `comprehendmedical:InferICD10CM`, `dynamodb:PutItem`, `s3:GetObject`, `s3:PutObject`, `s3:PutObjectRetention` 

---

## Configuration

```python
import boto3
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional
from botocore.config import Config  # [EDITOR: review fix P1-6] Added for retry configuration

# -------------------------------------------------------------------------
# Model IDs
# Cross-region inference profiles route to best available region automatically.
# Always pin to specific version ARNs in production (no "latest" aliases).
# -------------------------------------------------------------------------
BOUNDARY_DETECTION_MODEL  = "us.amazon.nova-lite-v1:0"           # Tier 1: cheap, binary question
CLASSIFICATION_MODEL      = "us.amazon.nova-lite-v1:0"           # Tier 1: structured document context
CLINICAL_EXTRACTION_MODEL = "us.anthropic.claude-sonnet-4-6-v1:0"  # Tier 3: clinical reasoning
CLAIM_MATCHING_MODEL      = "us.anthropic.claude-sonnet-4-6-v1:0"  # Tier 3: CPT code reasoning

# -------------------------------------------------------------------------
# Retry configuration
# -------------------------------------------------------------------------
# [EDITOR: review fix P1-6] Added retry config. This recipe makes ~40 Bedrock calls per
# package. ThrottlingException is expected, not exceptional, at burst processing volumes.
# adaptive mode implements exponential backoff with jitter automatically.
# Apply to every boto3 client that touches Bedrock or Comprehend Medical.
BOTO3_RETRY_CONFIG = Config(
    retries={
        "max_attempts": 3,
        "mode":         "adaptive"   # exponential backoff with jitter; handles ThrottlingException
    }
)

# -------------------------------------------------------------------------
# Thresholds
# -------------------------------------------------------------------------
BOUNDARY_CONFIDENCE_THRESHOLD       = 0.60  # Below this: flag for review
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.70  # Below this: route to review queue
CLAIM_MATCH_CONFIDENCE_THRESHOLD    = 0.80  # Below this: "needs_review", not "supported"

# -------------------------------------------------------------------------
# System prompts
# These are defined once and reused across calls.
# At scale, prompt caching on these system prompts cuts input costs by ~90%.
# -------------------------------------------------------------------------
BOUNDARY_DETECTION_SYSTEM_PROMPT = """
You are a healthcare document analyst. Your job is to determine whether two consecutive
pages from a claims attachment PDF belong to the same logical document.

A claims attachment package contains multiple distinct documents faxed together:
operative reports, pathology reports, discharge summaries, EOBs, therapy notes,
billing statements, and others. Your job is to detect where one document ends
and the next begins.

Return ONLY a valid JSON object with these fields:
{
  "same_document": <true or false>,
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one to two sentences explaining your determination>",
  "signals_detected": ["<list any signals you used: title_change, header_change,
                        page_restart, date_discontinuity, format_shift, content_type_change>"]
}

Common boundary signals to evaluate:
- Title lines: Does either page have a document title (OPERATIVE REPORT, PATHOLOGY REPORT,
  DISCHARGE SUMMARY, EXPLANATION OF BENEFITS) near the top?
- Header changes: Does the facility name, department, or document template change?
- Page number restart: Does page 2 show "Page 1 of N"?
- Date discontinuity: Does the primary date change by more than a few days?
- Content type shift: Does the text shift from clinical narrative to financial tables?

Be conservative: when in doubt, return same_document: true. A missed boundary causes
extraction errors. A false boundary just splits a document, which is less harmful.
""".strip()

DOCUMENT_CLASSIFICATION_SYSTEM_PROMPT = """
You are a healthcare document classifier for claims attachment processing.

Return ONLY a valid JSON object with these fields:
{
  "doc_type": "<one of: operative_report, pathology_report, eob, discharge_summary,
               therapy_notes, billing_statement, other>",
  "confidence": <0.0 to 1.0>,
  "primary_date": "<most prominent date in YYYY-MM-DD format, or null>",
  "reasoning": "<one sentence explaining your classification>"
}

Document types:
- operative_report: surgical procedure narrative with preoperative/postoperative diagnosis,
  procedure performed, anesthesia, findings, and surgeon attestation.
- pathology_report: specimen analysis with gross description, microscopic findings, diagnosis.
- eob: Explanation of Benefits with billed/allowed/paid columns and service lines.
- discharge_summary: full hospital episode covering admitting diagnosis through discharge.
- therapy_notes: PT/OT/ST visit documentation, usually 1-2 pages per visit.
- billing_statement: provider itemized charges with revenue codes and account balance.
- other: consent forms, referral letters, administrative documents.

Confidence 0.9+ only if classification is unambiguous. 0.7-0.89 for likely. Below 0.7 for uncertain.
""".strip()

CLINICAL_EXTRACTION_SYSTEM_PROMPT = """
You are a clinical documentation analyst reviewing a claims attachment document.
Extract all clinically and administratively relevant information.

Return ONLY a valid JSON object with this structure:
{
  "document_summary": "<one to two sentences describing this document>",
  "diagnoses": ["<primary and secondary diagnoses as documented>"],
  "procedures_performed": ["<procedures or treatments documented, with laterality if present>"],
  "explicit_cpt_codes": ["<CPT codes explicitly written as numbers in the document>"],
  "service_dates": ["<all dates of service in YYYY-MM-DD format>"],
  "provider_name": "<treating or performing provider name, or empty string>",
  "provider_npi": "<NPI number if present, or empty string>",
  "facility": "<facility or practice name, or empty string>",
  "specimens_sent": ["<specimens sent to pathology, or empty list>"],
  "clinical_findings": "<key clinical findings, lab values, or imaging results>",
  "confidence": <0.0 to 1.0>
}

Extract only what is explicitly stated. Use empty strings or empty lists for absent fields.
For explicit_cpt_codes, include only 5-digit codes explicitly written (e.g., '27447').
""".strip()

CLAIM_MATCHING_SYSTEM_PROMPT = """
You are a medical claims analyst determining which claim line items are supported
by clinical documentation.

A claim line is "supported" when:
1. The document describes a procedure consistent with the CPT code, AND
2. The service date is consistent with the claim line date (within 1 day for single-day
   services; within the admission span for inpatient services).

Return ONLY a valid JSON object with this structure:
{
  "line_assessments": [
    {
      "line_number": <integer>,
      "cpt_code": "<CPT code>",
      "supported": <true or false>,
      "confidence": <0.0 to 1.0>,
      "match_type": "<exact_cpt | procedure_match | date_only | no_match>",
      "match_reasoning": "<your reasoning about why this document supports or does not
                          support this line item, based on the extracted document summary>",
      "evidence_type": "llm_synthesis",
      "date_consistent": <true, false, or null if not determinable>
    }
  ]
}

match_type values:
- exact_cpt: the CPT code number appears explicitly in the document
- procedure_match: document describes a procedure consistent with the CPT (clinical knowledge)
- date_only: date matches but procedure link is uncertain
- no_match: document does not support this claim line

In match_reasoning, explain your assessment using the document summary provided.
Do not use quotation marks as if citing verbatim text from the original document;
the summary you received is an LLM extraction, not a direct transcript.
If a claim line is not supported, state what documentation would be needed.
""".strip()
# [EDITOR: review fix P1-4] Renamed supporting_evidence to match_reasoning and added
# evidence_type: "llm_synthesis". The claim-matching LLM receives a summarized extraction,
# not the original OCR text. Any evidence it surfaces is LLM-reconstructed from that
# summary, not a verbatim quote from the document. Labeling it match_reasoning and
# setting evidence_type to "llm_synthesis" makes this explicit for downstream consumers
# and claims examiners auditing automated decisions.
```

---

## Step 3: Group Textract Blocks by Page

```python
def group_blocks_by_page(all_blocks: list[dict]) -> dict[int, dict]:
    """
    Group Textract blocks by page number and extract per-page metadata.

    This is the same function as Recipe 1.4, with one addition: extract_header_region.
    The header text feeds directly into the boundary detection prompt.
    """
    pages = {}

    for block in all_blocks:
        page_num = block.get('Page', 1)

        if page_num not in pages:
            pages[page_num] = {
                'page_num':      page_num,
                'blocks':        [],
                'text':          '',
                'header_text':   '',
                'has_tables':    False,
                'has_forms':     False,
                'layout_blocks': []
            }

        pages[page_num]['blocks'].append(block)

        if block['BlockType'] == 'LINE':
            pages[page_num]['text'] += block['Text'] + '\n'

            # Extract header region: top 15% of page by vertical position.
            # Textract bounding boxes are normalized: 0.0 = top, 1.0 = bottom.
            top = block.get('Geometry', {}).get('BoundingBox', {}).get('Top', 1.0)
            if top < 0.15:
                pages[page_num]['header_text'] += block['Text'] + '\n'

        elif block['BlockType'] == 'TABLE':
            pages[page_num]['has_tables'] = True

        elif block['BlockType'] == 'KEY_VALUE_SET':
            pages[page_num]['has_forms'] = True

        elif block['BlockType'].startswith('LAYOUT_'):
            pages[page_num]['layout_blocks'].append(block)

    return pages
```

---

## Step 4: LLM Boundary Detection

```python
def detect_boundary_at_page_pair(
    page_n: dict,
    page_n_plus_1: dict,
    bedrock_client,
    model_id: str = BOUNDARY_DETECTION_MODEL
) -> dict:
    """
    Ask Nova Lite: are these two consecutive pages from the same document?

    We send only the first 1500 characters of each page. That's enough for the
    model to see the title lines, headers, and opening content that signal a
    boundary. Sending full pages would increase token costs with no accuracy benefit.
    """
    # Build the comparison message
    def page_block(page: dict) -> str:
        header = page['header_text'].strip() or "(no header detected)"
        text   = page['text'][:1500].strip()
        return f"Page {page['page_num']}:\nHeader: {header}\nText:\n{text}"

    user_message = (
        page_block(page_n)
        + "\n\n---\n\n"
        + page_block(page_n_plus_1)
        + "\n\nDo these two pages belong to the same document?"
    )

    response = bedrock_client.converse(
        modelId=model_id,
        system=[{'text': BOUNDARY_DETECTION_SYSTEM_PROMPT}],
        messages=[{
            'role':    'user',
            'content': [{'text': user_message}]
        }],
        inferenceConfig={
            'maxTokens':   256,
            'temperature': 0   # Near-deterministic; we want consistency across runs
        }
    )

    response_text = response['output']['message']['content'][0]['text']

    # Parse JSON response with defensive error handling.
    # Language models don't guarantee valid JSON, so we wrap and retry.
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Strip any surrounding prose the model may have added (common edge case)
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            # If we can't parse it at all, assume same document (conservative fallback)
            print(f"  WARNING: Could not parse boundary response for pages "
                  f"{page_n['page_num']}/{page_n_plus_1['page_num']}. "
                  f"Defaulting to same_document=True.")
            result = {
                'same_document':    True,
                'confidence':       0.5,
                'reasoning':        'Parse error; defaulting to same document',
                'signals_detected': []
            }

    return result


def detect_all_boundaries(
    pages: dict[int, dict],
    bedrock_client,
    model_id: str = BOUNDARY_DETECTION_MODEL
) -> list[dict]:
    """
    Walk the page stream and detect document boundaries by comparing consecutive pairs.

    Returns a list of document segments, each with start_page, end_page, and the
    boundary signal that triggered the split.
    """
    segments    = []
    seg_start   = 1
    sorted_nums = sorted(pages.keys())

    print(f"Running boundary detection on {len(sorted_nums)} pages "
          f"({len(sorted_nums) - 1} page pairs)...")

    for i in range(len(sorted_nums) - 1):
        page_n        = pages[sorted_nums[i]]
        page_n_plus_1 = pages[sorted_nums[i + 1]]

        result = detect_boundary_at_page_pair(page_n, page_n_plus_1, bedrock_client, model_id)

        status = "NEW DOCUMENT" if not result['same_document'] else "same"
        # [EDITOR: Replaced em dash (—) separator with colon in f-string output.]
        # [EDITOR: review fix P1-5] Removed result['reasoning'] from print. Boundary reasoning
        # can echo clinical content from the page text (facility names, document titles, terms).
        # In Lambda, stdout writes to CloudWatch Logs. Log structural metadata only; omit
        # clinical content to keep logs PHI-free.
        print(f"  Pages {page_n['page_num']}/{page_n_plus_1['page_num']}: {status} "
              f"(conf={result['confidence']:.2f})")

        if not result['same_document']:
            # Close the current segment and start a new one
            segments.append({
                'start_page':       seg_start,
                'end_page':         page_n['page_num'],
                'boundary_signals': result['signals_detected'],
                'split_confidence': result['confidence'],
                'split_reasoning':  result['reasoning']
            })
            seg_start = page_n_plus_1['page_num']

    # Always close the final segment
    segments.append({
        'start_page':       seg_start,
        'end_page':         sorted_nums[-1],
        'boundary_signals': ['end_of_document'],
        'split_confidence': 1.0,
        'split_reasoning':  'Final segment in package'
    })

    print(f"\nDetected {len(segments)} document segments:")
    for seg in segments:
        print(f"  Pages {seg['start_page']}-{seg['end_page']} "
              f"(signals: {seg['boundary_signals']})")

    return segments
```

---

## Step 5: LLM Document Classification

```python
def classify_segment(
    segment: dict,
    pages: dict[int, dict],
    bedrock_client,
    model_id: str = CLASSIFICATION_MODEL
) -> dict:
    """
    Classify a logical document segment by sending its full aggregated text to Nova Lite.

    Recipe 1.4 classified individual pages. Here we classify whole documents.
    Full document context means the model sees the complete operative report vocabulary,
    not just page 5 of 6 in isolation.
    """
    # Aggregate text from all pages in this segment
    segment_text = ''
    has_tables   = False

    for page_num in range(segment['start_page'], segment['end_page'] + 1):
        if page_num in pages:
            segment_text += pages[page_num]['text'] + '\n'
            if pages[page_num]['has_tables']:
                has_tables = True

    # Note table presence; it's a strong EOB and billing statement signal
    table_note = "Note: This document contains one or more tables.\n\n" if has_tables else ""

    user_message = (
        table_note
        + f"Document text (pages {segment['start_page']} to {segment['end_page']}):\n\n"
        + segment_text[:4000]   # 4000 chars captures most documents' identifying content
    )

    response = bedrock_client.converse(
        modelId=model_id,
        system=[{'text': DOCUMENT_CLASSIFICATION_SYSTEM_PROMPT}],
        messages=[{
            'role':    'user',
            'content': [{'text': user_message}]
        }],
        inferenceConfig={
            'maxTokens':   256,
            'temperature': 0
        }
    )

    response_text = response['output']['message']['content'][0]['text']

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {
                'doc_type':    'other',
                'confidence':  0.0,
                'primary_date': None,
                'reasoning':   'Parse error; defaulting to other'
            }

    classified = {
        'start_page':       segment['start_page'],
        'end_page':         segment['end_page'],
        'doc_type':         result.get('doc_type', 'other'),
        'confidence':       result.get('confidence', 0.0),
        'primary_date':     result.get('primary_date'),
        'reasoning':        result.get('reasoning', ''),
        'boundary_signals': segment['boundary_signals']
    }

    # [EDITOR: Replaced em dash (—) separator with colon in f-string output.]
    # [EDITOR: review fix P1-5] Removed reasoning from print. Classification reasoning can
    # include document title text with facility name or patient identifiers. Log doc_type
    # and confidence only; omit reasoning to keep CloudWatch Logs PHI-free.
    print(f"  Pages {classified['start_page']}-{classified['end_page']}: "
          f"{classified['doc_type']} "
          f"(conf={classified['confidence']:.2f})")

    return classified


def classify_all_segments(
    segments: list[dict],
    pages: dict[int, dict],
    bedrock_client,
    model_id: str = CLASSIFICATION_MODEL
) -> list[dict]:
    print(f"\nClassifying {len(segments)} segments...")
    return [classify_segment(seg, pages, bedrock_client, model_id) for seg in segments]
```

---

## Step 6a: LLM Clinical Document Extraction

```python
def extract_clinical_document(
    segment: dict,
    pages: dict[int, dict],
    bedrock_client,
    comprehend_medical_client,
    model_id: str = CLINICAL_EXTRACTION_MODEL
) -> dict:
    """
    Extract structured clinical content from operative reports, pathology reports,
    discharge summaries, and therapy notes using Claude Sonnet 4.6.

    After LLM extraction, validates ICD-10 codes via Comprehend Medical.
    This hybrid follows Recipe 1.4's pattern: LLM extracts the concept,
    Comprehend Medical maps the authoritative code.
    """
    # [EDITOR: "Claude Sonnet" -> "Claude Sonnet 4.6" in docstring.]

    # Aggregate segment text
    segment_text = ''.join(
        pages[page_num]['text'] + '\n'
        for page_num in range(segment['start_page'], segment['end_page'] + 1)
        if page_num in pages
    )

    user_message = (
        f"Extract clinical information from this {segment['doc_type']} document:\n\n"
        + segment_text[:8000]   # 8000 chars covers most multi-page clinical documents
    )

    response = bedrock_client.converse(
        modelId=model_id,
        system=[{'text': CLINICAL_EXTRACTION_SYSTEM_PROMPT}],
        messages=[{
            'role':    'user',
            'content': [{'text': user_message}]
        }],
        inferenceConfig={
            'maxTokens':   1024,   # Clinical notes need more output room than classification
            'temperature': 0
        }
    )

    response_text  = response['output']['message']['content'][0]['text']

    try:
        llm_extraction = json.loads(response_text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            llm_extraction = json.loads(json_match.group())
        else:
            llm_extraction = {
                'document_summary':    'Parse error',
                'diagnoses':           [],
                'procedures_performed': [],
                'explicit_cpt_codes':  [],
                'service_dates':       [],
                'provider_name':       '',
                'provider_npi':        '',
                'facility':            '',
                'specimens_sent':      [],
                'clinical_findings':   '',
                'confidence':          0.0
            }

    # ICD-10 code validation via Comprehend Medical.
    # LLMs extract the diagnosis concept; Comprehend maps the authoritative code.
    # See Recipe 1.3 for full infer_icd10_codes implementation.
    icd10_codes   = []
    icd10_flagged = []

    diagnoses = llm_extraction.get('diagnoses', [])
    if diagnoses:
        diagnosis_text = '. '.join(diagnoses)
        # Comprehend Medical has a 20,000 char limit per call.
        # We truncate here as a safe ceiling; a production implementation
        # would split long inputs into overlapping 5000-char chunks.
        diagnosis_text = diagnosis_text[:5000]

        try:
            cm_response = comprehend_medical_client.infer_icd10_cm(Text=diagnosis_text)
            for entity in cm_response.get('Entities', []):
                for concept in entity.get('ICD10CMConcepts', []):
                    if concept['Score'] >= 0.80:
                        icd10_codes.append({
                            'icd10_code':  concept['Code'],
                            'description': concept['Description'],
                            'confidence':  round(concept['Score'], 3),
                            'source_text': entity['Text']
                        })
                    elif concept['Score'] >= 0.60:
                        icd10_flagged.append({
                            'icd10_code':  concept['Code'],
                            'description': concept['Description'],
                            'confidence':  round(concept['Score'], 3),
                            'source_text': entity['Text']
                        })
        except Exception as e:
            print(f"  WARNING: Comprehend Medical failed for segment "
                  f"{segment['start_page']}-{segment['end_page']}: {e}")

    return {
        'doc_type':       segment['doc_type'],
        'start_page':     segment['start_page'],
        'end_page':       segment['end_page'],
        'primary_date':   segment.get('primary_date'),
        'llm_extraction': llm_extraction,
        'icd10_codes':    icd10_codes,
        'icd10_flagged':  icd10_flagged,
        'confidence':     llm_extraction.get('confidence', 0.0) * 100
    }
```

---

## Step 6b: Textract Table Extraction for Financial Documents

```python
# EOB column mapping: canonical names to known header variants across payer templates.
# Financial documents (EOBs, billing statements) use Textract, not LLM.
# Textract is faster, cheaper, and more accurate for clean tabular data.
EOB_SERVICE_LINE_COLUMNS = {
    'service_date':           ['date of service', 'dos', 'service date', 'date'],
    'procedure_code':         ['procedure', 'cpt', 'procedure code', 'service code', 'hcpcs'],
    'billed_amount':          ['billed', 'billed amount', 'charge', 'submitted amount'],
    'allowed_amount':         ['allowed', 'allowed amount', 'contracted rate', 'negotiated rate'],
    'plan_paid':              ['plan paid', 'paid', 'insurance paid', 'plan payment'],
    'patient_responsibility': ['patient responsibility', 'patient owes', 'amount you owe',
                               'deductible + coinsurance']
}


def extract_financial_document(
    segment: dict,
    pages: dict[int, dict],
    block_map: dict
) -> dict:
    """
    Extract EOB or billing statement data via Textract table parsing.

    This does NOT use an LLM. Financial tabular data doesn't benefit from
    LLM reasoning; Textract handles it better and cheaper.
    (Same principle as Recipe 1.4's lab results extractor.)
    """
    service_lines = []

    for page_num in range(segment['start_page'], segment['end_page'] + 1):
        if page_num not in pages:
            continue

        page = pages[page_num]
        if not page['has_tables']:
            continue

        # Find TABLE blocks on this page
        for block in page['blocks']:
            if block['BlockType'] != 'TABLE':
                continue

            # Reconstruct the table as a list of rows
            table_rows = _reconstruct_table(block, block_map)
            if len(table_rows) < 2:
                continue  # Header only or empty; skip

            # Normalize header row to canonical column names
            headers   = [cell.lower().strip() for cell in table_rows[0]]
            col_map   = _normalize_columns(headers, EOB_SERVICE_LINE_COLUMNS)

            # Extract service lines from data rows
            for row in table_rows[1:]:
                line_item = {}
                for col_idx, canonical_name in col_map.items():
                    if col_idx < len(row):
                        line_item[canonical_name] = row[col_idx].strip()

                # Keep rows that have at least a service date and a billed amount.
                # This filters out sub-total rows and empty rows.
                if 'service_date' in line_item and 'billed_amount' in line_item:
                    service_lines.append(line_item)

    return {
        'doc_type':      segment['doc_type'],
        'start_page':    segment['start_page'],
        'end_page':      segment['end_page'],
        'primary_date':  segment.get('primary_date'),
        'service_lines': service_lines,
        'confidence':    90.0 if service_lines else 40.0
    }


def _reconstruct_table(table_block: dict, block_map: dict) -> list[list[str]]:
    """
    Reconstruct a Textract TABLE block into a list-of-lists.
    Each inner list is a row. Cells within a row are ordered by column index.
    """
    # Collect CELL blocks that belong to this table
    cells = {}  # (row_index, col_index) -> text

    for rel in table_block.get('Relationships', []):
        if rel['Type'] != 'CHILD':
            continue
        for cell_id in rel['Ids']:
            cell = block_map.get(cell_id, {})
            if cell.get('BlockType') != 'CELL':
                continue
            row_idx = cell['RowIndex']
            col_idx = cell['ColumnIndex']

            # Extract the cell text from its WORD children
            cell_text = ''
            for cell_rel in cell.get('Relationships', []):
                if cell_rel['Type'] != 'CHILD':
                    continue
                for word_id in cell_rel['Ids']:
                    word = block_map.get(word_id, {})
                    if word.get('BlockType') == 'WORD':
                        cell_text += word.get('Text', '') + ' '
            cells[(row_idx, col_idx)] = cell_text.strip()

    if not cells:
        return []

    max_row = max(r for r, c in cells)
    max_col = max(c for r, c in cells)

    rows = []
    for row_idx in range(1, max_row + 1):
        row = []
        for col_idx in range(1, max_col + 1):
            row.append(cells.get((row_idx, col_idx), ''))
        rows.append(row)

    return rows


def _normalize_columns(headers: list[str], column_map: dict) -> dict[int, str]:
    """Map header position indices to canonical column names."""
    col_mapping = {}
    for col_idx, header_text in enumerate(headers):
        for canonical_name, variants in column_map.items():
            if any(variant in header_text for variant in variants):
                col_mapping[col_idx] = canonical_name
                break
    return col_mapping
```

---

## Step 7: LLM Claim Line Matching

```python
def match_document_to_claim_lines(
    extraction: dict,
    claim_lines: list[dict],
    bedrock_client,
    model_id: str = CLAIM_MATCHING_MODEL
) -> list[dict]:
    """
    Ask Claude Sonnet 4.6: which claim lines does this document support?

    This is the capstone of the recipe. The model reasons from clinical knowledge:
    "cemented total condylar knee replacement" = CPT 27447, even without a lookup table.
    It returns match_reasoning explaining the assessment; evidence_type: "llm_synthesis"
    signals that this is the model's interpretation of the extracted summary, not a
    verbatim quote from the source document.
    """
    # [EDITOR: "Claude Sonnet" -> "Claude Sonnet 4.6" in docstring.]

    llm_data = extraction.get('llm_extraction', {})

    # Build a structured summary of the document for the model.
    # We send the extraction summary, not the raw page text, to keep the
    # claim matching prompt tight and costs predictable.
    doc_summary = (
        f"Document type: {extraction['doc_type']}\n"
        f"Pages: {extraction['start_page']}-{extraction['end_page']}\n"
        f"Primary date: {extraction.get('primary_date', 'unknown')}\n\n"
        f"Diagnoses: {'; '.join(llm_data.get('diagnoses', []))}\n"
        f"Procedures performed: {'; '.join(llm_data.get('procedures_performed', []))}\n"
        f"Explicit CPT codes in document: {', '.join(llm_data.get('explicit_cpt_codes', []))}\n"
        f"Provider: {llm_data.get('provider_name', 'unknown')}\n"
        f"Service dates: {', '.join(llm_data.get('service_dates', []))}\n"
        f"Key findings: {llm_data.get('clinical_findings', '')}\n"
    )

    claim_lines_text = "\nClaim line items to evaluate:\n"
    for line in claim_lines:
        claim_lines_text += (
            f"Line {line['line_number']}: CPT {line['cpt_code']} "
            f"({line['procedure_desc']}) "
            f"Date: {line['date_of_service']} "
            f"Provider NPI: {line.get('billing_npi', 'unknown')}\n"
        )

    user_message = (
        doc_summary
        + claim_lines_text
        + "\nFor each claim line, assess whether this document supports it."
    )

    response = bedrock_client.converse(
        modelId=model_id,
        system=[{'text': CLAIM_MATCHING_SYSTEM_PROMPT}],
        messages=[{
            'role':    'user',
            'content': [{'text': user_message}]
        }],
        inferenceConfig={
            'maxTokens':   1024,
            'temperature': 0
        }
    )

    response_text = response['output']['message']['content'][0]['text']

    try:
        result = json.loads(response_text)
        return result.get('line_assessments', [])
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result.get('line_assessments', [])
        print(f"  WARNING: Could not parse claim matching response for "
              f"segment {extraction['start_page']}-{extraction['end_page']}")
        return []


def match_all_documents_to_claim_lines(
    classified_segments: list[dict],
    extraction_results: list[dict],
    claim_lines: list[dict],
    bedrock_client,
    model_id: str = CLAIM_MATCHING_MODEL
) -> dict:
    """
    Accumulate claim line support across all documents in the package.

    Clinical documents go through LLM reasoning.
    EOBs and billing statements are checked for explicit CPT matches.
    """
    print(f"\nMatching {len(extraction_results)} documents to "
          f"{len(claim_lines)} claim lines...")

    # Initialize support tracking per claim line
    line_support = {}
    for line in claim_lines:
        line_support[line['line_number']] = {
            'assessments':   [],
            'final_status':  'no_documentation'
        }

    clinical_types = {'operative_report', 'pathology_report',
                      'discharge_summary', 'therapy_notes'}

    for extraction in extraction_results:
        doc_type = extraction['doc_type']

        if doc_type in clinical_types:
            # LLM reasoning for clinical documents
            assessments = match_document_to_claim_lines(
                extraction, claim_lines, bedrock_client, model_id
            )
            for assessment in assessments:
                line_num = assessment.get('line_number')
                if line_num in line_support:
                    line_support[line_num]['assessments'].append({
                        'doc_type':           doc_type,
                        'pages':              f"{extraction['start_page']}-{extraction['end_page']}",
                        'supported':          assessment.get('supported', False),
                        'confidence':         _to_decimal(assessment.get('confidence', 0.0)),
                        # [EDITOR: review fix P0-1] Explicit _to_decimal() at the deepest nesting
                        # level. assessment.get('confidence') is a float from LLM JSON output.
                        # DynamoDB will reject put_item with TypeError if float is written.
                        # _to_decimal() is now recursive so nested dicts/lists are also safe,
                        # but explicit conversion here documents intent at the critical call site.
                        'match_type':         assessment.get('match_type', 'no_match'),
                        'match_reasoning':    assessment.get('match_reasoning', ''),
                        'evidence_type':      assessment.get('evidence_type', 'llm_synthesis'),
                        'date_consistent':    assessment.get('date_consistent')
                    })

        elif doc_type in ('eob', 'billing_statement'):
            # Direct CPT match for financial documents (no LLM needed)
            for service_line in extraction.get('service_lines', []):
                procedure_code = service_line.get('procedure_code', '').strip()
                for claim_line in claim_lines:
                    if procedure_code == claim_line['cpt_code']:
                        line_support[claim_line['line_number']]['assessments'].append({
                            'doc_type':           doc_type,
                            'pages':              f"{extraction['start_page']}-{extraction['end_page']}",
                            'supported':          True,
                            'confidence':         _to_decimal(0.95),
                            'match_type':         'exact_cpt',
                            'match_reasoning':    f"Service line in {doc_type} shows CPT {procedure_code}",
                            'evidence_type':      'structured_data',
                            'date_consistent':    True
                        })

    # Determine final status for each claim line
    for line_num, support_data in line_support.items():
        assessments    = support_data['assessments']
        high_support   = [a for a in assessments if a['supported'] and a['confidence'] >= 0.80]
        medium_support = [a for a in assessments if a['supported'] and a['confidence'] >= 0.60]

        if high_support:
            support_data['final_status'] = 'supported'
        elif medium_support:
            support_data['final_status'] = 'needs_review'
        elif assessments:
            support_data['final_status'] = 'documentation_insufficient'
        else:
            support_data['final_status'] = 'no_documentation'

    # Summary
    for line_num, support_data in line_support.items():
        print(f"  Line {line_num}: {support_data['final_status']} "
              f"({len(support_data['assessments'])} document(s) assessed)")

    return line_support
```

---

## Step 8: Assemble the Unified Record

```python
def _to_decimal(value) -> Decimal:
    """
    Convert a float (or recursively convert a dict/list) to Decimal for DynamoDB.

    DynamoDB rejects Python float values and requires Decimal.
    Always convert via string to avoid floating-point representation errors:
    Decimal(str(0.956)) is exact; Decimal(0.956) is not.

    Accepts float, int, dict, or list. Recurses into nested structures so that
    deeply nested confidence values (e.g., inside claim_line_support.assessments)
    are converted without requiring explicit calls at each nesting level.
    """
    # [EDITOR: review fix P0-1] Extended _to_decimal() to recursively handle nested
    # dicts and lists. In v2, confidence values inside claim_line_support.assessments
    # were float (LLM JSON output), not Decimal. DynamoDB rejects the put_item with
    # TypeError: Float types are not supported. Fix: recurse into dicts and lists
    # so the helper covers all nesting depths without explicit per-field calls.
    if isinstance(value, float):
        return Decimal(str(value))
    elif isinstance(value, int):
        return Decimal(str(value))
    elif isinstance(value, dict):
        return {k: _to_decimal(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_to_decimal(item) for item in value]
    else:
        return value  # str, bool, None, Decimal already: pass through unchanged


def assemble_claims_attachment_record(
    attachment_key: str,
    claim_id: str,
    page_count: int,
    classified_segments: list[dict],
    extraction_results: list[dict],
    line_support: dict
) -> dict:
    """
    Assemble the final claims attachment record with deduplication.

    Confidence values are stored as Decimal for DynamoDB compatibility.
    All float confidence scores are converted via _to_decimal() before assembly.
    """

    record = {
        'attachment_key':          attachment_key,
        'claim_id':                claim_id,
        'extracted_at':            datetime.now(timezone.utc).isoformat(),
        'page_count':              page_count,
        'needs_review':            False,
        'documents_found':         len(classified_segments),
        'document_inventory':      [],
        'all_icd10_codes':         [],
        'all_conditions':          [],
        'all_procedures':          [],
        'eob_data':                [],
        'claim_line_support':      line_support,
        'unclassified_segments':   [],
        'low_confidence_segments': [],
        'unsupported_lines':       []
    }

    seen_icd10     = {}    # code -> entry with highest confidence
    seen_diagnoses  = set()
    seen_procedures = set()

    for segment, extraction in zip(classified_segments, extraction_results):
        # Build document inventory entry.
        # Convert confidence to Decimal for DynamoDB write compatibility.
        record['document_inventory'].append({
            'doc_type':                  segment['doc_type'],
            'pages':                     f"{segment['start_page']}-{segment['end_page']}",
            'confidence':                _to_decimal(segment['confidence']),
            'primary_date':              segment.get('primary_date'),
            'classification_reasoning':  segment.get('reasoning', '')
        })

        # Aggregate ICD-10 codes with deduplication (keep highest confidence per code)
        for code_entry in extraction.get('icd10_codes', []):
            code = code_entry['icd10_code']
            if code not in seen_icd10 or code_entry['confidence'] > seen_icd10[code]['confidence']:
                # Store with Decimal confidence for DynamoDB
                seen_icd10[code] = {
                    **code_entry,
                    'confidence': _to_decimal(code_entry['confidence'])
                }

        # Aggregate clinical concepts
        llm_data = extraction.get('llm_extraction', {})
        for dx in llm_data.get('diagnoses', []):
            normalized = dx.lower().strip()
            if normalized and normalized not in seen_diagnoses:
                seen_diagnoses.add(normalized)
                record['all_conditions'].append(dx)

        for proc in llm_data.get('procedures_performed', []):
            normalized = proc.lower().strip()
            if normalized and normalized not in seen_procedures:
                seen_procedures.add(normalized)
                record['all_procedures'].append(proc)

        # Collect financial document data
        if segment['doc_type'] in ('eob', 'billing_statement'):
            record['eob_data'].append(extraction)

        # Flag review cases
        if segment['doc_type'] == 'other':
            record['unclassified_segments'].append({
                'pages':  f"{segment['start_page']}-{segment['end_page']}",
                'reason': segment.get('reasoning', 'classified as other')
            })
            record['needs_review'] = True

        if segment['confidence'] < CLASSIFICATION_CONFIDENCE_THRESHOLD:
            record['low_confidence_segments'].append({
                'pages':      f"{segment['start_page']}-{segment['end_page']}",
                'doc_type':   segment['doc_type'],
                'confidence': _to_decimal(segment['confidence'])
            })
            record['needs_review'] = True

    # Flag unsupported claim lines
    for line_num, support_data in line_support.items():
        if support_data['final_status'] in ('no_documentation', 'documentation_insufficient'):
            record['unsupported_lines'].append(line_num)
            record['needs_review'] = True

    # Finalize deduplicated ICD-10 list, sorted by confidence (highest first)
    record['all_icd10_codes'] = sorted(
        seen_icd10.values(),
        key=lambda x: x['confidence'],
        reverse=True
    )

    return record
```

---

## Full Pipeline

```python
def run_claims_attachment_pipeline(
    attachment_key: str,
    claim_id: str,
    textract_blocks: list[dict],
    claim_lines: list[dict],
    region: str = 'us-east-1'
) -> dict:
    """
    Full end-to-end claims attachment processing pipeline.

    In a real deployment this runs as a Step Functions state machine, not a single function.
    The monolithic structure here is for readability; each major step would be its own Lambda.

    Args:
        attachment_key:  S3 key of the claims attachment PDF
        claim_id:        Claim ID linking this attachment to its claim line items
        textract_blocks: All blocks from a completed Textract async job
        claim_lines:     List of claim line items (from the 837 transaction or claims DB)
        region:          AWS region for Bedrock calls
    """
    bedrock  = boto3.client('bedrock-runtime', region_name=region, config=BOTO3_RETRY_CONFIG)
    comp_med = boto3.client('comprehendmedical', region_name=region, config=BOTO3_RETRY_CONFIG)
    # [EDITOR: review fix P1-6] Added BOTO3_RETRY_CONFIG to both clients.
    # This recipe makes ~40 Bedrock calls per package. ThrottlingException during burst
    # processing is expected at volume. adaptive mode handles exponential backoff automatically.

    print(f"\n{'='*60}")
    print(f"Processing attachment: {attachment_key}")
    print(f"Claim ID: {claim_id}")
    print(f"Total blocks from Textract: {len(textract_blocks)}")

    # Step 3: Group blocks by page
    print("\n[Step 3] Grouping Textract blocks by page...")
    pages     = group_blocks_by_page(textract_blocks)
    block_map = {block['Id']: block for block in textract_blocks}
    print(f"  {len(pages)} pages found")

    # Step 4: LLM boundary detection
    print("\n[Step 4] Running LLM boundary detection...")
    segments = detect_all_boundaries(pages, bedrock, BOUNDARY_DETECTION_MODEL)

    # Step 5: LLM document classification
    print("\n[Step 5] Classifying document segments...")
    classified_segments = classify_all_segments(segments, pages, bedrock, CLASSIFICATION_MODEL)

    # Step 6: Fan out to type-specific extractors
    print("\n[Step 6] Extracting content from each segment...")
    extraction_results = []
    clinical_types = {'operative_report', 'pathology_report', 'discharge_summary', 'therapy_notes'}
    financial_types = {'eob', 'billing_statement'}

    for segment in classified_segments:
        doc_type = segment['doc_type']
        print(f"  Extracting {doc_type} (pages {segment['start_page']}-{segment['end_page']})...")

        if doc_type in clinical_types:
            extraction = extract_clinical_document(
                segment, pages, bedrock, comp_med, CLINICAL_EXTRACTION_MODEL
            )
        elif doc_type in financial_types:
            extraction = extract_financial_document(segment, pages, block_map)
        else:
            # "other" type: preserve raw text, route to review
            extraction = {
                'doc_type':    doc_type,
                'start_page':  segment['start_page'],
                'end_page':    segment['end_page'],
                'primary_date': segment.get('primary_date'),
                'raw_text_preview': ''.join(
                    pages[p]['text'][:200]
                    for p in range(segment['start_page'], segment['end_page'] + 1)
                    if p in pages
                ),
                'confidence': 0.0
            }

        extraction_results.append(extraction)

    # Step 7: LLM claim line matching
    print("\n[Step 7] Matching documents to claim lines...")
    line_support = match_all_documents_to_claim_lines(
        classified_segments, extraction_results, claim_lines, bedrock, CLAIM_MATCHING_MODEL
    )

    # Step 8: Assemble the unified record
    print("\n[Step 8] Assembling claims attachment record...")
    record = assemble_claims_attachment_record(
        attachment_key      = attachment_key,
        claim_id            = claim_id,
        page_count          = len(pages),
        classified_segments = classified_segments,
        extraction_results  = extraction_results,
        line_support        = line_support
    )

    print(f"\n{'='*60}")
    print(f"Pipeline complete.")
    print(f"  Documents found: {record['documents_found']}")
    print(f"  Needs review:    {record['needs_review']}")
    if record['unsupported_lines']:
        print(f"  Unsupported lines: {record['unsupported_lines']}")
    if record['unclassified_segments']:
        print(f"  Unclassified segments: {len(record['unclassified_segments'])}")

    return record
```

---

## Gap to Production

This example demonstrates the core concepts. Here's the distance between this code and a real deployment.

**Error handling and retries.** Every Bedrock call needs exponential backoff with jitter. Bedrock returns throttling errors under load (`ThrottlingException`). Every Comprehend Medical call does too. This example configures `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` on both the `bedrock-runtime` and `comprehendmedical` clients; apply the same config to any additional clients you add. This recipe makes approximately 40 Bedrock calls per package, so adaptive retry is load-bearing, not cosmetic. The pipeline also needs a dead-letter queue on every Lambda: a package that silently disappears into a failed invocation delays a real claim.

**LLM output validation.** This code has basic JSON parse error handling, but a production system needs schema validation on the parsed output. The boundary detection response should have `same_document` (boolean), `confidence` (float 0-1), `reasoning` (string), `signals_detected` (list). Validate the types and ranges. If the model returns `confidence: "high"` instead of `confidence: 0.9`, the downstream code breaks silently. Use Pydantic or jsonschema for validation; fall back to human review on any schema violation.

**Prompt injection hardening.** Claims attachments are untrusted external documents. Apply Bedrock Guardrails to all Converse calls (`guardrailIdentifier`, `guardrailVersion` parameters). Strip control characters and unusual Unicode from page text before sending it to the model. Validate that extraction outputs look like clinical data, not instructions.

**Model version pinning.** Pin to specific model ARN versions, not aliases. When `us.anthropic.claude-sonnet-4-6-v1:0` is updated or deprecated, its behavior on your prompts may shift. Build a regression test suite on labeled packages. Run it before deploying any model version change.

**Step Functions integration.** The monolithic function above is illustrative. In production, each major step is its own Lambda: `claim-start`, `claim-retrieve`, `doc-segmenter`, `doc-classifier`, `extract-clinical`, `extract-financial`, `claim-matcher`, `claim-assembler`. Step Functions orchestrates them with a parallel state for the per-segment extraction, a merge state for the assembler, and error handlers per branch. Pass S3 references through Step Functions, not raw data: the 256 KB payload limit is easy to exceed.

**Comprehend Medical chunking.** `InferICD10CM` has a 20,000 character limit. This code truncates at 5,000 characters, which covers most single-document diagnosis sections. If you need ICD-10 coverage across an entire multi-page discharge summary, split the text into overlapping 5,000-character chunks, run each separately, and merge results (deduplicating codes that appear near chunk boundaries).

**Prompt caching for cost control.** All five system prompts in this code are reused across calls within a package and across packages. Bedrock prompt caching cuts input token costs by up to 90% on cache hits. At 300,000 packages per year, that's a meaningful line item. Enable caching on the system prompt content blocks by adding cache control hints in the Converse API request.

**PHI in log messages.** This example logs only structural metadata from Bedrock API calls: page numbers, document type, confidence values, and error types. Never log raw model output (`response_text`), LLM reasoning fields, or extracted clinical text. LLM responses to clinical extraction prompts can contain patient names, diagnoses, and medication lists drawn from the input document. Additionally: configure CloudWatch log groups for all Lambda functions with KMS encryption using a customer-managed key. Lambda does not encrypt log groups by default. Scope CloudWatch log group access to authorized personnel only.  

**DynamoDB Decimal requirement.** DynamoDB requires Python `Decimal` for floating-point numbers, not `float`. The `_to_decimal()` helper in this file now recurses into nested dicts and lists, so confidence values at any nesting depth are converted automatically. The most common trap is a nested `assessments` list inside `claim_line_support`: those `confidence` floats come directly from LLM JSON output and must be converted before `put_item`. If you extend the record schema with additional numeric fields, the recursive helper handles them as long as the top-level field is passed through it before writing to DynamoDB. 

**S3 Object Lock mode.** Use GOVERNANCE mode during development so you can delete test objects. COMPLIANCE mode is irrevocable: a retention lock set on a test object with the wrong date cannot be removed. Switch to COMPLIANCE mode only when deploying to production, only on the production bucket, only after confirming your retention configuration is correct.

**Idempotency.** The Lambda trigger for this pipeline fires on S3 events, which are at-least-once. Use conditional DynamoDB writes (`ConditionExpression='attribute_not_exists(claim_id)'`) to prevent duplicate records if the same package triggers the pipeline twice. Use the attachment key as the Step Functions execution name to prevent duplicate state machine runs.

**VPC and VPC endpoints.** All Lambdas in production should run in a VPC. Bedrock requires **two separate interface endpoints**: `com.amazonaws.REGION.bedrock-runtime` (Converse API, used by every Lambda in this pipeline) and `com.amazonaws.REGION.bedrock` (model management API, only needed if Lambda programmatically lists or enables models). A VPC with only `com.amazonaws.REGION.bedrock` will silently fail to route Converse calls through the private endpoint; in a no-egress HIPAA VPC this is deployment-breaking. Also add endpoints for Textract, Comprehend Medical, S3, DynamoDB, Step Functions, SNS, and CloudWatch Logs. PHI should not traverse the public internet.  

**IAM least-privilege.** The `bedrock:InvokeModel` permission in this example needs to be scoped to specific model ARNs, not `*`. The `comprehendmedical:InferICD10CM` permission should be similarly scoped. Each Lambda should have only the permissions it needs for its specific step.

---

*← [Recipe 1.5 Main Recipe](chapter01.05-claims-attachment-v3) · [Chapter 1 Index](chapter01-index)* 
