# Recipe 13.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 13.9. It shows one way you could translate those concepts into working Python code using boto3 and the Neptune graph database. It is not production-ready. The real pipeline would handle millions of articles, custom-trained transformer models, and sophisticated conflict resolution. Think of this as the sketch on the whiteboard: useful for understanding the shape of the solution, not something you'd point at PubMed and let rip on Monday morning.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests gremlinpython opensearch-py
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehend:DetectEntitiesV2` (for biomedical NER)
- `sagemaker:InvokeEndpoint` (for custom relation extraction model)
- `s3:GetObject`, `s3:PutObject` (for the document lake)
- `sqs:SendMessage` (for the human review queue)

For Neptune, you'll need network access to the cluster endpoint (Neptune lives in a VPC, so your code must run inside that VPC or use a bastion/VPN). Neptune uses IAM authentication or VPC-level access control rather than traditional credentials.

For OpenSearch, you'll need the domain endpoint and appropriate IAM permissions (`es:ESHttp*`).

---

## Config and Constants

These go at the top of your module. They define the scoring weights, thresholds, and connection details that the pipeline uses. In production, these would live in environment variables or AWS Systems Manager Parameter Store.

```python
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import requests
from botocore.config import Config

# Structured logging. Never log extracted PHI or full article text.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS service calls. Adaptive mode handles throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Service clients ---
comprehend_medical = boto3.client("comprehend-medical", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
sqs = boto3.client("sqs", config=BOTO3_RETRY_CONFIG)

# --- Configuration ---
DOCUMENT_BUCKET = "literature-knowledge-graph-documents"
SAGEMAKER_RE_ENDPOINT = "bio-relation-extraction"  # your deployed RE model endpoint
NEPTUNE_ENDPOINT = "your-neptune-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_PORT = 8182
OPENSEARCH_ENDPOINT = "https://your-opensearch-domain.us-east-1.es.amazonaws.com"
REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/literature-kg-review"

# --- NER confidence threshold ---
# Entities below this score are discarded. 0.75 is a reasonable starting point
# for biomedical text. Lower it if you're missing too many entities; raise it
# if your graph is getting noisy.
NER_CONFIDENCE_THRESHOLD = 0.75

# --- Relation extraction confidence threshold ---
# Relations below this score are discarded. 0.70 balances precision and recall
# for biomedical RE. In production, you'd tune this against a held-out test set.
RE_CONFIDENCE_THRESHOLD = 0.70

# --- Evidence scoring weights ---
# These weights reflect the hierarchy of evidence in biomedical research.
# A meta-analysis of RCTs is the gold standard. A single case report is
# interesting but not strong evidence. These weights multiply with the
# NLP confidence score to produce a final evidence grade.
STUDY_TYPE_WEIGHTS = {
    "meta-analysis": 1.0,
    "systematic-review": 0.95,
    "rct": 0.9,
    "cohort": 0.7,
    "case-control": 0.6,
    "case-report": 0.3,
    "review": 0.5,
    "unknown": 0.4,
}

# Section weights: findings in Results carry more weight than Discussion speculation.
SECTION_WEIGHTS = {
    "results": 1.0,
    "abstract": 0.8,
    "discussion": 0.7,
    "methods": 0.6,
    "introduction": 0.4,
}

# --- Entity normalization lookup (simplified) ---
# In production, this would be a full UMLS/RxNorm/HGNC lookup service.
# Here we show the pattern with a small sample dictionary.
DRUG_SYNONYMS = {
    "metformin": {"id": "RxNorm:6809", "label": "metformin"},
    "glucophage": {"id": "RxNorm:6809", "label": "metformin"},
    "metformin hydrochloride": {"id": "RxNorm:6809", "label": "metformin"},
    "warfarin": {"id": "RxNorm:11289", "label": "warfarin"},
    "coumadin": {"id": "RxNorm:11289", "label": "warfarin"},
    "ibuprofen": {"id": "RxNorm:5640", "label": "ibuprofen"},
}

DISEASE_SYNONYMS = {
    "type 2 diabetes": {"id": "SNOMED:44054006", "label": "type 2 diabetes mellitus"},
    "type 2 diabetes mellitus": {"id": "SNOMED:44054006", "label": "type 2 diabetes mellitus"},
    "t2dm": {"id": "SNOMED:44054006", "label": "type 2 diabetes mellitus"},
    "breast cancer": {"id": "SNOMED:254837009", "label": "breast cancer"},
    "breast carcinoma": {"id": "SNOMED:254837009", "label": "breast cancer"},
    "hypertension": {"id": "SNOMED:38341003", "label": "hypertension"},
}

GENE_SYNONYMS = {
    "cyp2d6": {"id": "HGNC:2625", "label": "CYP2D6"},
    "brca1": {"id": "HGNC:1100", "label": "BRCA1"},
    "brca2": {"id": "HGNC:1101", "label": "BRCA2"},
    "oct1": {"id": "HGNC:8583", "label": "SLC22A1"},
    "slc22a1": {"id": "HGNC:8583", "label": "SLC22A1"},
}
```

---

## Step 1: Fetch Articles from PubMed

*The pseudocode calls this `fetch_new_articles(last_watermark)`. It queries PubMed's E-utilities API for recently published articles matching our topic filters, then stores the raw XML in S3 for downstream processing.*

```python
# PubMed E-utilities base URL. This is a free, public API maintained by NCBI.
# Rate limit: 3 requests/second without an API key, 10/second with one.
# Get a free API key at https://www.ncbi.nlm.nih.gov/account/settings/
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_API_KEY = None  # Set this to your NCBI API key for higher rate limits

def fetch_new_articles(last_watermark: str, max_results: int = 100) -> list[dict]:
    """
    Query PubMed for articles published since the last watermark date.

    This function searches for pharmacogenomics and drug-disease literature,
    fetches metadata and abstracts, and stores raw XML in S3.

    Args:
        last_watermark: Date string in YYYY/MM/DD format. Only articles
                        published after this date are fetched.
        max_results:    Maximum articles to fetch per call. PubMed caps at 10,000
                        per query; use pagination for larger batches.

    Returns:
        List of article metadata dicts with keys: pmid, title, abstract, pub_date, mesh_terms
    """

    # Step 1a: Search for matching article IDs
    # The query targets pharmacogenomics and drug-disease literature.
    # PDAT is the publication date field in PubMed's query syntax.
    search_params = {
        "db": "pubmed",
        "term": (
            "(pharmacogenomics OR drug-disease interaction OR gene-phenotype) "
            f"AND {last_watermark}[PDAT] : 3000[PDAT]"
        ),
        "retmax": max_results,
        "retmode": "json",
        "sort": "pub_date",
    }
    if PUBMED_API_KEY:
        search_params["api_key"] = PUBMED_API_KEY

    search_response = requests.get(
        f"{PUBMED_BASE_URL}/esearch.fcgi", params=search_params
    )
    search_response.raise_for_status()
    search_data = search_response.json()

    pmids = search_data.get("esearchresult", {}).get("idlist", [])
    logger.info("Found %d new articles since %s", len(pmids), last_watermark)

    if not pmids:
        return []

    # Step 1b: Fetch full metadata and abstracts for each article
    # efetch returns structured XML with title, abstract, MeSH terms, etc.
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    if PUBMED_API_KEY:
        fetch_params["api_key"] = PUBMED_API_KEY

    fetch_response = requests.get(
        f"{PUBMED_BASE_URL}/efetch.fcgi", params=fetch_params
    )
    fetch_response.raise_for_status()
    raw_xml = fetch_response.text

    # Store the raw XML in S3 for reprocessing capability.
    # When you improve your NLP models later, you can re-run the pipeline
    # against this stored corpus without re-fetching from PubMed.
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
    s3_key = f"documents/pubmed/batch-{timestamp}.xml"
    s3.put_object(
        Bucket=DOCUMENT_BUCKET,
        Key=s3_key,
        Body=raw_xml.encode("utf-8"),
        ContentType="application/xml",
    )
    logger.info("Stored raw XML at s3://%s/%s", DOCUMENT_BUCKET, s3_key)

    # Step 1c: Parse the XML into structured article records.
    # In production, use xml.etree.ElementTree or lxml for proper XML parsing.
    # Here we show the pattern with a simplified parser.
    articles = parse_pubmed_xml(raw_xml)

    return articles

def parse_pubmed_xml(xml_text: str) -> list[dict]:
    """
    Parse PubMed XML into structured article records.

    This is a simplified parser that extracts the fields we need.
    Production code would use lxml with proper namespace handling.
    """
    import xml.etree.ElementTree as ET

    articles = []
    root = ET.fromstring(xml_text)

    for article_elem in root.findall(".//PubmedArticle"):
        pmid_elem = article_elem.find(".//PMID")
        title_elem = article_elem.find(".//ArticleTitle")
        abstract_elem = article_elem.find(".//AbstractText")

        # Extract MeSH terms for study type classification later
        mesh_terms = []
        for mesh in article_elem.findall(".//MeshHeading/DescriptorName"):
            mesh_terms.append(mesh.text)

        # Extract publication types (used for evidence grading)
        pub_types = []
        for pt in article_elem.findall(".//PublicationType"):
            pub_types.append(pt.text)

        articles.append({
            "pmid": pmid_elem.text if pmid_elem is not None else None,
            "title": title_elem.text if title_elem is not None else "",
            "abstract": abstract_elem.text if abstract_elem is not None else "",
            "mesh_terms": mesh_terms,
            "pub_types": pub_types,
            "pub_date": extract_pub_date(article_elem),
        })

    return [a for a in articles if a["pmid"] and a["abstract"]]

def extract_pub_date(article_elem) -> str:
    """Extract publication date from PubMed XML article element."""
    year = article_elem.find(".//PubDate/Year")
    month = article_elem.find(".//PubDate/Month")
    day = article_elem.find(".//PubDate/Day")
    parts = []
    if year is not None:
        parts.append(year.text)
    if month is not None:
        parts.append(month.text.zfill(2))
    if day is not None:
        parts.append(day.text.zfill(2))
    return "/".join(parts) if parts else "unknown"
```

---

## Step 2: Sentence Segmentation

*The pseudocode calls this `parse_and_segment(document_s3_key)`. It splits article abstracts into individual sentences, tagging each with its source location for provenance tracking.*

```python
def segment_into_sentences(article: dict) -> list[dict]:
    """
    Split an article's abstract into individual sentences with metadata.

    Biomedical text has tricky sentence boundaries: "Fig. 2", "et al.",
    "p < 0.05" all contain periods that aren't sentence endings. A proper
    implementation would use a biomedical sentence splitter like SciSpacy's
    sentencizer. Here we use a simplified approach for illustration.

    Args:
        article: Dict with keys pmid, title, abstract, mesh_terms, pub_types

    Returns:
        List of sentence dicts, each with text, source metadata, and position.
    """
    # In production, use scispacy or a biomedical-trained sentence splitter.
    # The naive split on ". " fails on abbreviations. This simplified version
    # handles the most common biomedical abbreviations.
    abstract = article["abstract"]
    if not abstract:
        return []

    # Simple sentence splitting (production would use scispacy)
    # Replace common abbreviations to protect their periods
    protected = abstract
    abbreviations = ["et al.", "Fig.", "vs.", "i.e.", "e.g.", "Dr.", "approx."]
    for abbr in abbreviations:
        protected = protected.replace(abbr, abbr.replace(".", "<DOT>"))

    # Split on sentence-ending punctuation followed by space and uppercase
    raw_sentences = []
    current = ""
    for char in protected:
        current += char
        if char in ".!?" and len(current.strip()) > 10:
            raw_sentences.append(current.strip())
            current = ""
    if current.strip():
        raw_sentences.append(current.strip())

    # Restore protected periods and build sentence records
    sentences = []
    for i, sent in enumerate(raw_sentences):
        restored = sent.replace("<DOT>", ".")
        if len(restored.split()) < 4:
            continue  # skip fragments too short to contain a relationship

        sentences.append({
            "text": restored,
            "pmid": article["pmid"],
            "section": "abstract",  # for abstract-only processing
            "position": i,
            "sentence_id": f"{article['pmid']}:abstract:{i}",
        })

    return sentences
```

---

## Step 3: Named Entity Recognition with Comprehend Medical

*The pseudocode calls this `extract_entities(sentences)`. It sends each sentence through Amazon Comprehend Medical to identify drugs, diseases, genes, and other biomedical entities.*

```python
def extract_entities(sentences: list[dict]) -> list[dict]:
    """
    Run biomedical NER on each sentence using Amazon Comprehend Medical.

    Comprehend Medical identifies: MEDICATION, MEDICAL_CONDITION,
    TEST_TREATMENT_PROCEDURE, ANATOMY, and their attributes (dosage,
    frequency, negation). For gene/variant entities, you'd supplement
    with a custom SageMaker model. Here we show the Comprehend Medical
    pattern.

    Args:
        sentences: List of sentence dicts from segment_into_sentences()

    Returns:
        List of entity mention dicts with type, confidence, position, and traits.
    """
    all_entities = []

    for sentence in sentences:
        text = sentence["text"]

        # Comprehend Medical has a 20,000 character limit per call.
        # Individual sentences are well under this, but check anyway.
        if len(text) > 20000:
            logger.warning("Sentence too long for Comprehend Medical, skipping: %s", sentence["sentence_id"])
            continue

        # Call Comprehend Medical's DetectEntitiesV2 API.
        # This is the newer version that returns richer entity attributes.
        response = comprehend_medical.detect_entities_v2(Text=text)

        for entity in response.get("Entities", []):
            # Apply confidence threshold. Low-confidence detections
            # introduce noise that propagates through the entire pipeline.
            if entity["Score"] < NER_CONFIDENCE_THRESHOLD:
                continue

            # Check for negation trait. Comprehend Medical flags negated
            # entities (e.g., "no evidence of diabetes") with a NEGATION trait.
            is_negated = any(
                trait["Name"] == "NEGATION" and trait["Score"] > 0.8
                for trait in entity.get("Traits", [])
            )

            all_entities.append({
                "text": entity["Text"],
                "type": entity["Category"],  # MEDICATION, MEDICAL_CONDITION, etc.
                "subtype": entity.get("Type", ""),  # GENERIC_NAME, DX_NAME, etc.
                "score": entity["Score"],
                "begin_offset": entity["BeginOffset"],
                "end_offset": entity["EndOffset"],
                "is_negated": is_negated,
                "sentence_id": sentence["sentence_id"],
                "sentence_text": text,
                "pmid": sentence["pmid"],
                "section": sentence["section"],
            })

    logger.info("Extracted %d entities from %d sentences", len(all_entities), len(sentences))
    return all_entities
```

---

## Step 4: Relation Extraction

*The pseudocode calls this `extract_relations(sentences, entity_mentions)`. It takes entity pairs within the same sentence and classifies the relationship between them using a custom SageMaker-hosted model.*

```python
# Valid entity pair combinations for relation extraction.
# Not all entity type pairs can have meaningful relationships.
# This filter prevents wasting inference calls on impossible pairs.
VALID_PAIR_TYPES = {
    ("MEDICATION", "MEDICAL_CONDITION"),  # drug-disease relationships
    ("MEDICAL_CONDITION", "MEDICATION"),
    ("MEDICATION", "MEDICATION"),          # drug-drug interactions
    ("MEDICATION", "GENE_OR_VARIANT"),     # pharmacogenomics
    ("GENE_OR_VARIANT", "MEDICAL_CONDITION"),  # gene-disease associations
    ("MEDICAL_CONDITION", "MEDICAL_CONDITION"),  # disease-disease comorbidity
}

def extract_relations(entity_mentions: list[dict]) -> list[dict]:
    """
    Classify relationships between entity pairs in the same sentence.

    For each sentence containing two or more entities, generate candidate
    pairs and send them to the relation extraction model. The model returns
    a relationship type (treats, causes, inhibits, associated_with, etc.)
    along with confidence and negation/speculation flags.

    Args:
        entity_mentions: List of entity dicts from extract_entities()

    Returns:
        List of extracted triple dicts ready for normalization.
    """
    # Group entities by sentence
    entities_by_sentence = {}
    for entity in entity_mentions:
        sid = entity["sentence_id"]
        if sid not in entities_by_sentence:
            entities_by_sentence[sid] = []
        entities_by_sentence[sid].append(entity)

    extracted_triples = []

    for sentence_id, entities in entities_by_sentence.items():
        # Need at least 2 entities in a sentence to form a pair
        if len(entities) < 2:
            continue

        # Generate valid candidate pairs
        for i, entity_a in enumerate(entities):
            for entity_b in entities[i + 1:]:
                pair_types = (entity_a["type"], entity_b["type"])
                if pair_types not in VALID_PAIR_TYPES:
                    continue

                # Call the relation extraction model hosted on SageMaker.
                # The model expects the sentence with entity markers inserted.
                prediction = call_relation_extraction_model(
                    sentence_text=entity_a["sentence_text"],
                    entity_a=entity_a,
                    entity_b=entity_b,
                )

                if prediction is None:
                    continue

                if (
                    prediction["confidence"] >= RE_CONFIDENCE_THRESHOLD
                    and prediction["relation_type"] != "NO_RELATION"
                ):
                    extracted_triples.append({
                        "subject": entity_a["text"],
                        "subject_type": entity_a["type"],
                        "predicate": prediction["relation_type"],
                        "object": entity_b["text"],
                        "object_type": entity_b["type"],
                        "confidence": prediction["confidence"],
                        "is_negated": prediction.get("is_negated", entity_a["is_negated"]),
                        "is_speculative": prediction.get("is_speculative", False),
                        "source_sentence": entity_a["sentence_text"],
                        "source_pmid": entity_a["pmid"],
                        "source_section": entity_a["section"],
                    })

    logger.info("Extracted %d relations from %d sentences", len(extracted_triples), len(entities_by_sentence))
    return extracted_triples

def call_relation_extraction_model(
    sentence_text: str, entity_a: dict, entity_b: dict
) -> dict | None:
    """
    Call the SageMaker-hosted relation extraction model.

    The model is a BioBERT or PubMedBERT transformer fine-tuned on
    biomedical relation extraction datasets (BioRED, ChemProt).
    It expects input with entity markers: [E1]...[/E1] and [E2]...[/E2].

    Returns:
        Dict with relation_type, confidence, is_negated, is_speculative.
        None if the model call fails.
    """
    # Insert entity markers into the sentence text.
    # The model uses these markers to identify which entities to classify.
    marked_text = sentence_text
    # Insert markers for entity_b first (higher offset) to preserve positions
    if entity_b["begin_offset"] > entity_a["begin_offset"]:
        marked_text = (
            marked_text[:entity_b["begin_offset"]]
            + "[E2]" + entity_b["text"] + "[/E2]"
            + marked_text[entity_b["end_offset"]:]
        )
        marked_text = (
            marked_text[:entity_a["begin_offset"]]
            + "[E1]" + entity_a["text"] + "[/E1]"
            + marked_text[entity_a["end_offset"]:]
        )
    else:
        marked_text = (
            marked_text[:entity_a["begin_offset"]]
            + "[E1]" + entity_a["text"] + "[/E1]"
            + marked_text[entity_a["end_offset"]:]
        )
        marked_text = (
            marked_text[:entity_b["begin_offset"]]
            + "[E2]" + entity_b["text"] + "[/E2]"
            + marked_text[entity_b["end_offset"]:]
        )

    payload = json.dumps({
        "text": marked_text,
        "entity_a_type": entity_a["type"],
        "entity_b_type": entity_b["type"],
    })

    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_RE_ENDPOINT,
            ContentType="application/json",
            Body=payload,
        )
        result = json.loads(response["Body"].read().decode("utf-8"))
        return result
    except Exception as e:
        logger.error("RE model invocation failed: %s", str(e))
        return None
```

---

## Step 5: Entity Normalization

*The pseudocode calls this `normalize_entities(triples)`. It maps extracted entity surface forms to canonical identifiers in standard biomedical ontologies (RxNorm, SNOMED CT, HGNC).*

```python
def normalize_entities(triples: list[dict]) -> list[dict]:
    """
    Map extracted entity mentions to canonical ontology identifiers.

    "Metformin," "Glucophage," and "metformin hydrochloride" all become
    RxNorm:6809. Without this step, your graph would have separate nodes
    for each surface form, fragmenting the knowledge.

    In production, this would call a UMLS API or a local lookup service
    built from the UMLS Metathesaurus. Here we use the simplified lookup
    dictionaries defined in the config section.

    Args:
        triples: List of extracted triple dicts from extract_relations()

    Returns:
        List of normalized triple dicts with canonical IDs, or empty if
        normalization failed for either entity.
    """
    normalized = []

    for triple in triples:
        subject_canonical = normalize_single_entity(
            triple["subject"], triple["subject_type"]
        )
        object_canonical = normalize_single_entity(
            triple["object"], triple["object_type"]
        )

        # Only keep triples where both entities resolved to canonical IDs.
        # Unnormalized entities would create orphan nodes that can't be
        # connected to anything else in the graph.
        if subject_canonical is None or object_canonical is None:
            logger.debug(
                "Skipping triple: could not normalize '%s' or '%s'",
                triple["subject"], triple["object"],
            )
            continue

        normalized.append({
            "subject_id": subject_canonical["id"],
            "subject_label": subject_canonical["label"],
            "subject_type": triple["subject_type"],
            "predicate": triple["predicate"],
            "object_id": object_canonical["id"],
            "object_label": object_canonical["label"],
            "object_type": triple["object_type"],
            "confidence": triple["confidence"],
            "is_negated": triple["is_negated"],
            "is_speculative": triple["is_speculative"],
            "provenance": {
                "pmid": triple["source_pmid"],
                "sentence": triple["source_sentence"],
                "section": triple["source_section"],
            },
        })

    logger.info("Normalized %d of %d triples", len(normalized), len(triples))
    return normalized

def normalize_single_entity(text: str, entity_type: str) -> dict | None:
    """
    Look up a single entity in the appropriate ontology dictionary.

    Tries exact match first (fast, reliable), then lowercase match.
    Production would add fuzzy matching and embedding-based similarity.

    Returns:
        Dict with 'id' and 'label' keys, or None if not found.
    """
    # Select lookup table based on entity type
    if entity_type == "MEDICATION":
        lookup = DRUG_SYNONYMS
    elif entity_type == "MEDICAL_CONDITION":
        lookup = DISEASE_SYNONYMS
    elif entity_type == "GENE_OR_VARIANT":
        lookup = GENE_SYNONYMS
    else:
        return None  # unsupported entity type for this example

    # Try exact lowercase match
    normalized_text = text.lower().strip()
    if normalized_text in lookup:
        return lookup[normalized_text]

    # In production: try fuzzy match, then embedding similarity
    # For this example, we just return None for unmatched entities
    return None
```

---

## Step 6: Evidence Grading

*The pseudocode calls this `grade_and_resolve(normalized_triples, existing_graph)`. It scores each triple based on source quality and detects conflicts with existing graph edges.*

```python
def grade_evidence(normalized_triples: list[dict], article_metadata: dict) -> list[dict]:
    """
    Assign evidence scores to each extracted triple based on source quality.

    The score combines: study type weight (RCT > case report), NLP extraction
    confidence, and section weight (Results > Discussion). This produces a
    single number between 0 and 1 that represents how much you should trust
    this particular extraction.

    Args:
        normalized_triples: List of normalized triple dicts
        article_metadata:   Dict mapping PMID to article metadata (pub_types, etc.)

    Returns:
        Same triples with evidence_score added to each.
    """
    scored = []

    for triple in normalized_triples:
        pmid = triple["provenance"]["pmid"]
        metadata = article_metadata.get(pmid, {})

        # Classify study type from publication types
        study_type = classify_study_type(metadata.get("pub_types", []))

        # Calculate composite evidence score
        study_weight = STUDY_TYPE_WEIGHTS.get(study_type, 0.4)
        section_weight = SECTION_WEIGHTS.get(triple["provenance"]["section"], 0.5)
        nlp_confidence = triple["confidence"]

        evidence_score = study_weight * section_weight * nlp_confidence

        triple["evidence_score"] = round(evidence_score, 4)
        triple["study_type"] = study_type
        scored.append(triple)

    return scored

def classify_study_type(pub_types: list[str]) -> str:
    """
    Determine study type from PubMed publication type annotations.

    PubMed tags articles with publication types like "Randomized Controlled Trial",
    "Meta-Analysis", "Case Reports", etc. We map these to our evidence hierarchy.
    """
    pub_types_lower = [pt.lower() for pt in pub_types]

    if "meta-analysis" in pub_types_lower:
        return "meta-analysis"
    if "systematic review" in pub_types_lower:
        return "systematic-review"
    if "randomized controlled trial" in pub_types_lower:
        return "rct"
    if "cohort study" in pub_types_lower or "observational study" in pub_types_lower:
        return "cohort"
    if "case-control study" in pub_types_lower:
        return "case-control"
    if "case reports" in pub_types_lower:
        return "case-report"
    if "review" in pub_types_lower:
        return "review"
    return "unknown"

def detect_conflicts(scored_triples: list[dict], existing_edges: list[dict]) -> list[dict]:
    """
    Check new triples against existing graph edges for contradictions.

    A contradiction occurs when the same entity pair has opposing assertions:
    e.g., one paper says "drug X treats disease Y" and another says
    "drug X does NOT treat disease Y" (negated relationship).

    Conflicts above a threshold on both sides go to the human review queue.

    Args:
        scored_triples: New triples with evidence scores
        existing_edges: Current edges from Neptune for the same entity pairs

    Returns:
        Triples with status field: "READY" or "PENDING_REVIEW"
    """
    # Build lookup of existing edges by entity pair
    existing_by_pair = {}
    for edge in existing_edges:
        pair_key = f"{edge['subject_id']}:{edge['object_id']}:{edge['predicate']}"
        existing_by_pair[pair_key] = edge

    for triple in scored_triples:
        pair_key = f"{triple['subject_id']}:{triple['object_id']}:{triple['predicate']}"

        if pair_key in existing_by_pair:
            existing = existing_by_pair[pair_key]
            # Check for negation conflict
            if triple["is_negated"] != existing.get("is_negated", False):
                # Contradiction detected. Send to human review.
                triple["status"] = "PENDING_REVIEW"
                triple["conflict_with"] = existing
                send_to_review_queue(triple, existing)
                continue

        triple["status"] = "READY"

    return scored_triples

def send_to_review_queue(new_triple: dict, existing_edge: dict):
    """Send a conflicting triple to the SQS review queue for human adjudication."""
    message = {
        "conflict_type": "CONTRADICTORY_ASSERTION",
        "new_triple": {
            "subject": new_triple["subject_label"],
            "predicate": new_triple["predicate"],
            "object": new_triple["object_label"],
            "is_negated": new_triple["is_negated"],
            "evidence_score": new_triple["evidence_score"],
            "source_pmid": new_triple["provenance"]["pmid"],
            "source_sentence": new_triple["provenance"]["sentence"],
        },
        "existing_edge": {
            "subject": existing_edge.get("subject_label", ""),
            "predicate": existing_edge.get("predicate", ""),
            "object": existing_edge.get("object_label", ""),
            "is_negated": existing_edge.get("is_negated", False),
            "evidence_score": existing_edge.get("evidence_score", 0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    sqs.send_message(
        QueueUrl=REVIEW_QUEUE_URL,
        MessageBody=json.dumps(message),
    )
    logger.info("Sent conflict to review queue: %s vs existing", new_triple["subject_label"])
```

---

## Step 7: Graph Insertion into Neptune

*The pseudocode calls this `insert_into_graph(scored_triples)`. It upserts nodes and edges into Amazon Neptune, accumulating evidence when the same relationship is extracted from multiple papers.*

```python
from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver.serializer import GraphSONSerializersV2d0

# Neptune connection. In production, use IAM authentication via
# the neptune-python-utils library or SigV4 signing.
# This example uses the basic Gremlin client for clarity.
neptune_gremlin_client = None

def get_neptune_client():
    """Lazy-initialize the Neptune Gremlin client."""
    global neptune_gremlin_client
    if neptune_gremlin_client is None:
        neptune_gremlin_client = gremlin_client.Client(
            f"wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin",
            "g",
            message_serializer=GraphSONSerializersV2d0(),
        )
    return neptune_gremlin_client

def insert_into_graph(scored_triples: list[dict]):
    """
    Insert approved triples into Neptune as graph edges between entity nodes.

    For each triple:
    1. Upsert the subject node (create if new, update timestamp if exists)
    2. Upsert the object node
    3. Check if this exact edge already exists
    4. If exists: accumulate evidence (add provenance, update score)
    5. If new: create the edge with full metadata

    Args:
        scored_triples: List of triples with status "READY" or "PENDING_REVIEW"
    """
    client = get_neptune_client()
    inserted = 0
    updated = 0

    for triple in scored_triples:
        if triple["status"] != "READY":
            continue

        # Upsert subject node
        upsert_node(
            client,
            node_id=triple["subject_id"],
            label=triple["subject_label"],
            node_type=triple["subject_type"],
        )

        # Upsert object node
        upsert_node(
            client,
            node_id=triple["object_id"],
            label=triple["object_label"],
            node_type=triple["object_type"],
        )

        # Check for existing edge between these nodes with same predicate
        existing = find_existing_edge(
            client,
            subject_id=triple["subject_id"],
            object_id=triple["object_id"],
            predicate=triple["predicate"],
            is_negated=triple["is_negated"],
        )

        if existing:
            # Edge exists: accumulate evidence from this new source
            update_edge_evidence(client, existing, triple)
            updated += 1
        else:
            # New edge: create it with full metadata
            create_edge(client, triple)
            inserted += 1

    logger.info("Graph update complete: %d inserted, %d updated", inserted, updated)

def upsert_node(client, node_id: str, label: str, node_type: str):
    """
    Create a node if it doesn't exist, or update its timestamp if it does.

    Neptune Gremlin uses the fold/coalesce/unfold pattern for upserts.
    """
    now = datetime.now(timezone.utc).isoformat()

    # The fold().coalesce().unfold() pattern is Neptune's idiomatic upsert.
    # If the vertex exists, update it. If not, create it.
    query = (
        "g.V().has('entity', 'entity_id', entity_id)"
        ".fold()"
        ".coalesce("
        "  unfold().property('updated_at', now),"
        "  addV('entity').property('entity_id', entity_id)"
        "    .property('label_text', label)"
        "    .property('entity_type', node_type)"
        "    .property('created_at', now)"
        "    .property('updated_at', now)"
        ")"
    )

    client.submit(
        query,
        bindings={
            "entity_id": node_id,
            "label": label,
            "node_type": node_type,
            "now": now,
        },
    )

def find_existing_edge(client, subject_id: str, object_id: str, predicate: str, is_negated: bool) -> dict | None:
    """Check if an edge already exists between two nodes with the same predicate."""
    query = (
        "g.V().has('entity', 'entity_id', subject_id)"
        ".outE('relationship').has('predicate', predicate).has('is_negated', is_negated)"
        ".where(inV().has('entity_id', object_id))"
        ".valueMap(true).toList()"
    )

    result = client.submit(
        query,
        bindings={
            "subject_id": subject_id,
            "object_id": object_id,
            "predicate": predicate,
            "is_negated": is_negated,
        },
    ).all().result()

    if result:
        return result[0]
    return None

def create_edge(client, triple: dict):
    """Create a new edge in Neptune with full provenance metadata."""
    now = datetime.now(timezone.utc).isoformat()
    provenance_json = json.dumps([triple["provenance"]])

    query = (
        "g.V().has('entity', 'entity_id', subject_id)"
        ".addE('relationship')"
        ".to(g.V().has('entity', 'entity_id', object_id))"
        ".property('predicate', predicate)"
        ".property('is_negated', is_negated)"
        ".property('is_speculative', is_speculative)"
        ".property('evidence_score', evidence_score)"
        ".property('support_count', 1)"
        ".property('provenance', provenance_json)"
        ".property('first_seen', now)"
        ".property('last_updated', now)"
        ".property('status', 'ACTIVE')"
        ".property('validation_status', 'machine_extracted')"
    )

    client.submit(
        query,
        bindings={
            "subject_id": triple["subject_id"],
            "object_id": triple["object_id"],
            "predicate": triple["predicate"],
            "is_negated": triple["is_negated"],
            "is_speculative": triple["is_speculative"],
            "evidence_score": triple["evidence_score"],
            "provenance_json": provenance_json,
            "now": now,
        },
    )

def update_edge_evidence(client, existing_edge: dict, new_triple: dict):
    """Add new provenance to an existing edge and recalculate evidence score."""
    now = datetime.now(timezone.utc).isoformat()

    # In production, you'd fetch the existing provenance list, append,
    # and recalculate the aggregate score. Here we show the update pattern.
    # Neptune doesn't support array append natively in Gremlin, so you'd
    # typically store provenance as a JSON string and parse/update it.
    query = (
        "g.E(edge_id)"
        ".property('support_count', new_count)"
        ".property('evidence_score', new_score)"
        ".property('last_updated', now)"
    )

    # Simple evidence aggregation: average of all supporting evidence scores
    old_count = existing_edge.get("support_count", [1])[0] if isinstance(existing_edge.get("support_count"), list) else existing_edge.get("support_count", 1)
    old_score = existing_edge.get("evidence_score", [0.5])[0] if isinstance(existing_edge.get("evidence_score"), list) else existing_edge.get("evidence_score", 0.5)

    new_count = old_count + 1
    new_score = ((old_score * old_count) + new_triple["evidence_score"]) / new_count

    edge_id = existing_edge.get("id", existing_edge.get("T.id"))

    client.submit(
        query,
        bindings={
            "edge_id": edge_id,
            "new_count": new_count,
            "new_score": round(new_score, 4),
            "now": now,
        },
    )
```

---

## Step 8: Querying the Knowledge Graph

*This isn't in the pseudocode as a pipeline step, but it's what makes the whole thing useful. Once you've built the graph, you need to query it.*

```python
def query_drug_relationships(drug_label: str, max_results: int = 10) -> list[dict]:
    """
    Query the knowledge graph for all relationships involving a specific drug.

    This is the kind of query a clinician or researcher would run:
    "What does the literature say about metformin?"

    Args:
        drug_label: The canonical drug name (e.g., "metformin")
        max_results: Maximum relationships to return

    Returns:
        List of relationship dicts with subject, predicate, object, and evidence.
    """
    client = get_neptune_client()

    # Find all outgoing edges from this drug node
    query = (
        "g.V().has('entity', 'label_text', drug_label)"
        ".outE('relationship')"
        ".order().by('evidence_score', decr)"
        ".limit(max_results)"
        ".project('predicate', 'target', 'evidence_score', 'support_count', 'is_negated')"
        ".by(values('predicate'))"
        ".by(inV().values('label_text'))"
        ".by(values('evidence_score'))"
        ".by(values('support_count'))"
        ".by(values('is_negated'))"
        ".toList()"
    )

    results = client.submit(
        query,
        bindings={"drug_label": drug_label, "max_results": max_results},
    ).all().result()

    return results

def find_path_between_entities(entity_a_id: str, entity_b_id: str, max_hops: int = 3) -> list[dict]:
    """
    Find shortest paths between two entities in the knowledge graph.

    This answers questions like: "Is there a known connection between
    gene X and disease Y?" The path might go through intermediate nodes
    (gene -> protein -> pathway -> disease).

    Args:
        entity_a_id: Canonical ID of the starting entity
        entity_b_id: Canonical ID of the target entity
        max_hops:    Maximum path length to search

    Returns:
        List of paths, each containing the sequence of nodes and edges.
    """
    client = get_neptune_client()

    query = (
        "g.V().has('entity', 'entity_id', start_id)"
        ".repeat(bothE('relationship').otherV().simplePath())"
        ".until(has('entity_id', end_id).or().loops().is(max_hops))"
        ".has('entity_id', end_id)"
        ".path()"
        ".limit(5)"
        ".toList()"
    )

    results = client.submit(
        query,
        bindings={
            "start_id": entity_a_id,
            "end_id": entity_b_id,
            "max_hops": max_hops,
        },
    ).all().result()

    return results
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Step Functions state machine would orchestrate, or what you'd call for a batch processing run.

```python
def process_literature_batch(last_watermark: str, max_articles: int = 50) -> dict:
    """
    Run the full literature-to-knowledge-graph pipeline for a batch of articles.

    This is the main entry point. In production, EventBridge would trigger
    this on a schedule (daily or hourly), and Step Functions would orchestrate
    the individual steps with error handling and retries.

    Args:
        last_watermark: Date string (YYYY/MM/DD) for incremental fetching
        max_articles:   Maximum articles to process in this batch

    Returns:
        Summary dict with counts of articles processed, triples extracted, etc.
    """
    print(f"=== Literature KG Pipeline: fetching since {last_watermark} ===")

    # Step 1: Fetch new articles from PubMed
    print("Step 1: Fetching articles from PubMed...")
    articles = fetch_new_articles(last_watermark, max_results=max_articles)
    print(f"  Fetched {len(articles)} articles")

    if not articles:
        print("  No new articles found. Done.")
        return {"articles": 0, "triples": 0, "inserted": 0}

    # Build metadata lookup for evidence grading later
    article_metadata = {a["pmid"]: a for a in articles}

    # Step 2: Segment articles into sentences
    print("Step 2: Segmenting into sentences...")
    all_sentences = []
    for article in articles:
        sentences = segment_into_sentences(article)
        all_sentences.extend(sentences)
    print(f"  Generated {len(all_sentences)} sentences")

    # Step 3: Extract entities with Comprehend Medical
    print("Step 3: Running NER with Comprehend Medical...")
    entities = extract_entities(all_sentences)
    print(f"  Found {len(entities)} entities")

    # Step 4: Extract relations between entity pairs
    print("Step 4: Extracting relations...")
    triples = extract_relations(entities)
    print(f"  Extracted {len(triples)} relations")

    # Step 5: Normalize entities to canonical IDs
    print("Step 5: Normalizing entities...")
    normalized = normalize_entities(triples)
    print(f"  Normalized {len(normalized)} triples (dropped {len(triples) - len(normalized)})")

    # Step 6: Grade evidence and detect conflicts
    print("Step 6: Grading evidence...")
    scored = grade_evidence(normalized, article_metadata)
    scored = detect_conflicts(scored, existing_edges=[])  # empty for first run
    ready_count = sum(1 for t in scored if t["status"] == "READY")
    review_count = sum(1 for t in scored if t["status"] == "PENDING_REVIEW")
    print(f"  Ready: {ready_count}, Pending review: {review_count}")

    # Step 7: Insert into Neptune
    print("Step 7: Inserting into Neptune...")
    insert_into_graph(scored)
    print("  Done.")

    summary = {
        "articles_processed": len(articles),
        "sentences_segmented": len(all_sentences),
        "entities_extracted": len(entities),
        "relations_extracted": len(triples),
        "triples_normalized": len(normalized),
        "triples_inserted": ready_count,
        "triples_pending_review": review_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n=== Pipeline complete ===")
    print(json.dumps(summary, indent=2))
    return summary

# Example: run the pipeline
if __name__ == "__main__":
    result = process_literature_batch(
        last_watermark="2026/05/01",
        max_articles=10,  # small batch for testing
    )
```

---

## The Gap Between This and Production

This example demonstrates the shape of the pipeline. Run it against PubMed and it will fetch articles, extract entities, classify relations, and insert triples into Neptune. But there's a significant distance between this sketch and a system you'd trust with biomedical knowledge. Here's where that gap lives:

**Custom model training.** The relation extraction step calls a SageMaker endpoint, but we didn't show how to train that model. In reality, you'd fine-tune PubMedBERT on the BioRED corpus (or ChemProt for drug-protein interactions), evaluate on a held-out test set, and iterate until precision exceeds 75%. This is weeks of ML engineering work.

**Entity normalization at scale.** Our lookup dictionaries have a dozen entries. The real UMLS Metathesaurus has over 4 million concepts and 15 million concept names. You'd build a dedicated normalization service backed by an Elasticsearch index of UMLS terms, with fuzzy matching, abbreviation expansion, and embedding-based similarity for novel terms. The UMLS license is free but requires registration.

**Full-text processing.** We only process abstracts here. Full-text articles from PubMed Central yield 5-10x more relationships per article, but they also require section parsing, figure/table handling, and reference resolution. The XML structure of PMC articles is well-defined but complex.

**Error handling and retries.** Every external call (PubMed API, Comprehend Medical, SageMaker, Neptune) can fail. Production code wraps each in try/except with exponential backoff, dead-letter queues for persistent failures, and alerting when error rates spike. A single failed article shouldn't crash the batch. The architecture companion describes the DLQ pattern in detail: when a Step Functions execution fails after retries, the article ID and failure metadata land in an SQS dead letter queue with a CloudWatch alarm on queue depth and a reprocessor Lambda for replay.

**Rate limiting.** PubMed's API allows 3 requests/second without a key, 10/second with one. Comprehend Medical has per-account throttling limits. SageMaker endpoints have invocation limits based on instance type. Your pipeline needs to respect all of these, ideally with a token bucket or semaphore pattern.

**Batch processing with Step Functions.** The `process_literature_batch` function here is synchronous. Production uses Step Functions to orchestrate: parallel NER across sentences, fan-out/fan-in for relation extraction, and separate error handling for each step. This lets you process thousands of articles per hour without timeout issues.

**Neptune bulk loading.** For initial graph population (millions of triples), Neptune's bulk loader (from S3 CSV/JSON) is orders of magnitude faster than individual Gremlin queries. Use the Gremlin approach for incremental updates; use bulk loading for backfill.

**Graph versioning.** Production systems track which model version produced each extraction, enabling selective reprocessing when models improve. Store model version as edge metadata. When you deploy a better RE model, you can re-extract from the document lake and compare results.

**Monitoring and observability.** You need dashboards showing: articles processed per day, extraction precision (sampled), normalization coverage (% of entities that resolve), conflict rate, graph growth rate, and query latency. CloudWatch custom metrics and a Grafana dashboard are the standard approach.

**Human review workflow.** The SQS queue for conflicts needs a frontend where domain experts can adjudicate. They see the conflicting assertions, the source sentences, and the evidence scores, then decide which to accept. Their decisions feed back into the system as training signal for future conflict resolution.

**Testing.** You need: unit tests for each pipeline step with mocked AWS responses, integration tests against a small Neptune cluster with known test data, and a gold-standard evaluation set of manually annotated articles where you know the correct triples. Run the evaluation set after every model update to catch regressions.

**Security and compliance.** Published literature is generally not PHI, but clinical trial results may reference cohort-level patient data. Ensure your VPC configuration, encryption settings, and access controls meet your organization's data governance requirements. Neptune audit logging should be enabled for all queries. The architecture companion adds a PHI screening step for case reports and clinical trial articles: sentences with detected PHI get redacted before being stored as provenance in Neptune or OpenSearch.

**Retraction monitoring.** Papers get retracted. When a retracted paper contributed to your knowledge graph, the relationships it supports may be invalid. The architecture companion describes a retraction monitoring Lambda that checks PubMed daily for newly retracted articles, flags affected edges, and recalculates evidence scores excluding retracted sources. Without this, retracted findings persist in your graph and can influence clinical queries.

**Edge validation workflow.** Every edge in the graph carries a `validation_status` field (machine_extracted, human_validated, human_rejected). Clinical applications should filter on `validation_status = "human_validated"` or require `evidence_score >= 0.85 AND support_count >= 3`. Building the human review UI and workflow to populate this field is a separate engineering effort not shown here.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.9](chapter13.09-literature-derived-knowledge-graph) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
