# Recipe 13.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.4. It shows one way you could translate drug interaction knowledge graph concepts into working Python code using boto3 and Neptune's openCypher endpoint. It is not production-ready. There's no connection pooling, no retry logic, no input validation, no proper error handling. Think of it as the sketchpad version: useful for understanding how drug interaction data flows into a graph and how mechanism-based traversal queries work, not something you'd deploy to a pharmacy system on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests redis
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for Neptune (`neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery` scoped to your cluster), S3 (`s3:GetObject` on the source data bucket), Comprehend Medical (`comprehend:DetectEntitiesV2`, `comprehend:InferRxNorm`), and network access to Neptune from within your VPC.

Neptune doesn't use IAM for query authentication by default (it uses VPC-level network isolation). If you've enabled IAM auth on your cluster, you'll need to sign requests with SigV4. This example assumes VPC network access without IAM auth for simplicity.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These constants define the Neptune endpoint, the graph schema for drug interactions, and the severity classification logic that determines which interactions actually matter clinically.

```python
import boto3
import json
import hashlib
import logging
import requests
import redis
from itertools import combinations

# Configure logging. In production, use structured JSON logging
# for CloudWatch Logs Insights queries.
# PHI Safety: Patient medication lists are PHI. Never log specific
# patient medication combinations or patient identifiers.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Neptune cluster endpoint. Use the writer endpoint for loads,
# reader endpoint for queries. In production, separate these.
#
# Neptune runs inside your VPC. This code must execute from within
# the same VPC (Lambda in VPC, EC2, ECS, etc.) to reach it.
NEPTUNE_WRITER_ENDPOINT = "your-neptune-cluster.cluster-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_READER_ENDPOINT = "your-neptune-cluster.cluster-ro-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_PORT = 8182

# Neptune exposes openCypher queries via HTTPS POST to this path.
NEPTUNE_WRITER_URL = f"https://{NEPTUNE_WRITER_ENDPOINT}:{NEPTUNE_PORT}/openCypher"
NEPTUNE_READER_URL = f"https://{NEPTUNE_READER_ENDPOINT}:{NEPTUNE_PORT}/openCypher"

# S3 bucket for staging source data files (RxNorm, DrugBank, FDA SPL).
SOURCE_BUCKET = "my-ddi-source-data"

# AWS region for all service calls.
AWS_REGION = "us-east-1"

# Redis endpoint for caching interaction query results.
REDIS_HOST = "your-redis-cluster.xxxxxxxxxxxx.use1.cache.amazonaws.com"
REDIS_PORT = 6379

# Cache TTL: 7 days. Interaction knowledge base updates weekly.
# Flush cache explicitly when new source data is loaded.
CACHE_TTL_SECONDS = 604800

# Clinical significance threshold. Interactions scoring below this
# are suppressed from clinical alerts. This is the single most important
# tuning parameter for alert fatigue. Start conservative (low threshold,
# more alerts) and raise it as you validate the scoring model.
#
# 0.3 is deliberately permissive for a new system. Production systems
# with validated scoring typically use 0.4-0.6.
SIGNIFICANCE_THRESHOLD = 0.3

# Severity weights for scoring. These multiply with evidence quality
# and patient context factors to produce the final significance score.
SEVERITY_WEIGHTS = {
    "Contraindicated": 1.0,
    "Major": 0.85,
    "Moderate": 0.5,
    "Minor": 0.2,
}

# Evidence level weights. An interaction supported by an RCT gets
# more weight than one based on a single case report.
EVIDENCE_WEIGHTS = {
    "Established": 1.0,    # Multiple controlled studies
    "Probable": 0.8,       # Strong pharmacological basis + clinical evidence
    "Suspected": 0.5,      # Pharmacological basis, limited clinical evidence
    "Possible": 0.3,       # Case reports or theoretical only
    "Inferred": 0.4,       # Mechanism-based inference (no direct evidence for this pair)
}

# Inhibition strength multipliers for mechanism-based inference.
# A strong CYP inhibitor (like ketoconazole for CYP3A4) causes much
# larger substrate concentration increases than a weak one (like cimetidine).
INHIBITION_STRENGTH_MULTIPLIERS = {
    "strong": 1.0,
    "moderate": 0.6,
    "weak": 0.3,
}

# Node labels in our graph schema.
NODE_LABELS = {
    "drug": "Drug",
    "enzyme": "Enzyme",
    "transporter": "Transporter",
    "clinical_effect": "ClinicalEffect",
    "evidence": "Evidence",
}

# Edge types connecting our nodes.
EDGE_TYPES = {
    "substrate_of": "SUBSTRATE_OF",
    "inhibits": "INHIBITS",
    "induces": "INDUCES",
    "interacts_with": "INTERACTS_WITH",
    "contributes_to": "CONTRIBUTES_TO",
    "supported_by": "SUPPORTED_BY",
    "has_ingredient": "HAS_INGREDIENT",
    "tradename_of": "TRADENAME_OF",
}
```

---

## Step 1: Ingest and Normalize Drug Data from RxNorm

*The pseudocode calls this `ingest_rxnorm(rxnorm_file_path)`. It reads the RxNorm RRF files (pipe-delimited relational files from the NLM UMLS distribution) and loads drug concept nodes into Neptune. RxNorm provides the canonical drug identifiers that anchor the entire graph. Without these, you can't reliably link interaction data from different sources because everyone calls drugs by different names.*

```python
s3_client = boto3.client("s3", region_name=AWS_REGION)


def run_opencypher_query(query: str, parameters: dict = None, use_writer: bool = False) -> dict:
    """
    Execute an openCypher query against Neptune and return the response.

    Neptune's openCypher endpoint accepts POST requests with the query
    as a form parameter. Parameters are passed as a JSON-encoded string.

    Args:
        query: openCypher query string (MATCH, MERGE, CREATE, etc.)
        parameters: Dict of query parameters (referenced as $param_name in query)
        use_writer: If True, send to writer endpoint (for mutations).
                    If False, send to reader endpoint (for queries).

    Returns:
        Parsed JSON response from Neptune.
    """
    url = NEPTUNE_WRITER_URL if use_writer else NEPTUNE_READER_URL

    payload = {"query": query}
    if parameters:
        payload["parameters"] = json.dumps(parameters)

    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()


def ingest_rxnorm_concepts(bucket: str, key: str) -> int:
    """
    Parse RxNorm RXNCONSO.RRF and load drug concept nodes into Neptune.

    RxNorm's RXNCONSO file contains one row per concept-name pair. Each row
    has a CUI (concept unique identifier), a term type (TTY), and the name string.
    We care about specific term types:

      IN  = Ingredient (the actual molecule, e.g., "warfarin")
      BN  = Brand Name (e.g., "Coumadin")
      SCD = Semantic Clinical Drug (ingredient + strength + dose form)
      SBD = Semantic Branded Drug (brand + strength + dose form)

    We load IN and BN as primary drug nodes. SCD/SBD become linked nodes
    that let us resolve specific formulations back to their ingredient.

    The RRF format is pipe-delimited with these columns:
    RXCUI|LAT|TS|LUI|STT|SUI|ISPREF|RXAUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|...

    We only want rows where SAB (source abbreviation) = "RXNORM" to avoid
    duplicates from other vocabularies included in the file.

    Args:
        bucket: S3 bucket containing the RxNorm download
        key: S3 key to RXNCONSO.RRF

    Returns:
        Count of drug nodes loaded.
    """
    logger.info(f"Loading RxNorm concepts from s3://{bucket}/{key}")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    # Term types we want as primary drug nodes.
    target_ttys = {"IN", "BN", "SCD", "SBD"}
    nodes_loaded = 0

    for line in content.strip().split("\n"):
        fields = line.split("|")
        if len(fields) < 15:
            continue

        rxcui = fields[0]
        sab = fields[11]   # Source abbreviation
        tty = fields[12]   # Term type
        name = fields[14]  # The actual drug name string

        # Only load RXNORM-sourced entries to avoid duplicates.
        if sab != "RXNORM":
            continue

        if tty not in target_ttys:
            continue

        # MERGE ensures we don't create duplicates if we re-run the load.
        # Properties get updated on each run (name might change between versions).
        query = """
        MERGE (d:Drug {rxcui: $rxcui})
        SET d.name = $name,
            d.term_type = $tty,
            d.source = 'RxNorm',
            d.last_updated = $today
        """
        run_opencypher_query(
            query,
            parameters={
                "rxcui": rxcui,
                "name": name,
                "tty": tty,
                "today": str(date.today()),
            },
            use_writer=True,
        )
        nodes_loaded += 1

        if nodes_loaded % 1000 == 0:
            logger.info(f"  Loaded {nodes_loaded} drug nodes...")

    logger.info(f"RxNorm ingestion complete. {nodes_loaded} nodes loaded.")
    return nodes_loaded


def ingest_rxnorm_relationships(bucket: str, key: str) -> int:
    """
    Parse RxNorm RXNREL.RRF and load drug-to-drug relationships into Neptune.

    RXNREL contains relationships between concepts. The ones we care about:
      - has_ingredient: links SCD/SBD to their IN (ingredient)
      - tradename_of: links BN to IN
      - isa: hierarchical "is-a" relationships

    These let us resolve "Coumadin 5mg tablet" -> "warfarin" so that
    interaction checks work regardless of whether the EHR sends us a
    brand name, generic, or specific formulation.

    RXNREL format: RXCUI1|RXAUI1|STYPE1|REL|RXCUI2|RXAUI2|STYPE2|RELA|RUI|...

    Args:
        bucket: S3 bucket containing the RxNorm download
        key: S3 key to RXNREL.RRF

    Returns:
        Count of relationship edges loaded.
    """
    logger.info(f"Loading RxNorm relationships from s3://{bucket}/{key}")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    # Relationship types we want to load.
    target_relas = {"has_ingredient", "tradename_of", "isa"}
    edges_loaded = 0

    for line in content.strip().split("\n"):
        fields = line.split("|")
        if len(fields) < 10:
            continue

        rxcui1 = fields[0]
        rxcui2 = fields[4]
        rela = fields[7]  # Relationship attribute (the specific relationship type)

        if rela not in target_relas:
            continue

        # Map RxNorm relationship names to our graph edge types.
        edge_type = EDGE_TYPES.get(rela.lower(), rela.upper())

        query = f"""
        MATCH (a:Drug {{rxcui: $rxcui1}})
        MATCH (b:Drug {{rxcui: $rxcui2}})
        MERGE (a)-[r:{edge_type}]->(b)
        SET r.source = 'RxNorm',
            r.last_updated = $today
        """
        run_opencypher_query(
            query,
            parameters={
                "rxcui1": rxcui1,
                "rxcui2": rxcui2,
                "today": str(date.today()),
            },
            use_writer=True,
        )
        edges_loaded += 1

    logger.info(f"RxNorm relationships loaded. {edges_loaded} edges.")
    return edges_loaded
```

---

## Step 2: Load Enzyme and Transporter Relationships from DrugBank

*The pseudocode calls this `ingest_drugbank_mechanisms(drugbank_xml_path)`. DrugBank provides the mechanistic layer: which enzymes metabolize which drugs, and whether a drug is a substrate, inhibitor, or inducer of each enzyme. This is the data that enables mechanism-based inference (finding interactions that nobody has explicitly curated as a pair).*

```python
import xml.etree.ElementTree as ET


def ingest_drugbank_mechanisms(bucket: str, key: str) -> int:
    """
    Parse DrugBank XML and load enzyme/transporter relationships into Neptune.

    DrugBank's full database XML contains a <drug> element for each drug entry.
    Within each drug, <enzymes>, <transporters>, and <carriers> sections list
    the proteins that interact with that drug, along with the action type
    (substrate, inhibitor, inducer) and supporting references.

    The critical insight: if Drug A is a SUBSTRATE of CYP2C9, and Drug B
    INHIBITS CYP2C9, then Drug B will increase Drug A's plasma concentration.
    We don't need someone to have explicitly curated "Drug A interacts with
    Drug B" if we know their enzyme relationships.

    DrugBank XML structure (simplified):
    <drug>
      <drugbank-id>DB00001</drugbank-id>
      <name>Lepirudin</name>
      <enzymes>
        <enzyme>
          <id>BE0000017</id>
          <name>Cytochrome P450 2C9</name>
          <actions><action>substrate</action></actions>
          <references>...</references>
          <known-action>yes</known-action>
          <inhibition-strength>N/A</inhibition-strength>
        </enzyme>
      </enzymes>
    </drug>

    Note: DrugBank requires a license for commercial use. The academic
    version is free but has restrictions. Check their terms before deploying.

    Args:
        bucket: S3 bucket containing the DrugBank XML export
        key: S3 key to the full_database.xml file

    Returns:
        Count of mechanism edges loaded.
    """
    logger.info(f"Loading DrugBank mechanisms from s3://{bucket}/{key}")

    # DrugBank XML is large (1-2 GB). In production, use streaming XML parsing
    # (iterparse) instead of loading the entire tree into memory.
    # This simplified version loads it all for clarity.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    root = ET.fromstring(content)
    # DrugBank uses a namespace. All elements are prefixed.
    ns = {"db": "http://www.drugbank.ca"}

    edges_loaded = 0

    for drug_elem in root.findall("db:drug", ns):
        drug_name = drug_elem.findtext("db:name", default="", namespaces=ns)
        drugbank_id = drug_elem.findtext("db:drugbank-id[@primary='true']", default="", namespaces=ns)

        # We need to map DrugBank entries to RxNorm CUIs.
        # DrugBank includes external identifiers including RxNorm.
        rxcui = None
        ext_ids = drug_elem.find("db:external-identifiers", ns)
        if ext_ids is not None:
            for ext_id in ext_ids.findall("db:external-identifier", ns):
                resource = ext_id.findtext("db:resource", default="", namespaces=ns)
                if resource == "RxCUI":
                    rxcui = ext_id.findtext("db:identifier", default="", namespaces=ns)
                    break

        if not rxcui:
            # No RxNorm mapping. We can't link this to our drug nodes.
            # In production, you'd maintain a separate mapping table for these.
            continue

        # Process enzyme relationships.
        enzymes_elem = drug_elem.find("db:enzymes", ns)
        if enzymes_elem is not None:
            for enzyme_elem in enzymes_elem.findall("db:enzyme", ns):
                edges_loaded += _load_protein_relationship(
                    rxcui, enzyme_elem, "Enzyme", ns
                )

        # Process transporter relationships.
        transporters_elem = drug_elem.find("db:transporters", ns)
        if transporters_elem is not None:
            for transporter_elem in transporters_elem.findall("db:transporter", ns):
                edges_loaded += _load_protein_relationship(
                    rxcui, transporter_elem, "Transporter", ns
                )

    logger.info(f"DrugBank mechanisms loaded. {edges_loaded} edges.")
    return edges_loaded


def _load_protein_relationship(rxcui: str, protein_elem, protein_type: str, ns: dict) -> int:
    """
    Helper: load a single drug-protein relationship into Neptune.

    Creates the protein node (enzyme or transporter) if it doesn't exist,
    then creates the typed edge (SUBSTRATE_OF, INHIBITS, or INDUCES)
    between the drug and the protein.

    Args:
        rxcui: The drug's RxNorm CUI (already in our graph)
        protein_elem: XML element for the enzyme/transporter
        protein_type: "Enzyme" or "Transporter"
        ns: XML namespace dict

    Returns:
        1 if an edge was loaded, 0 if skipped.
    """
    protein_id = protein_elem.findtext("db:id", default="", namespaces=ns)
    protein_name = protein_elem.findtext("db:name", default="", namespaces=ns)

    if not protein_id or not protein_name:
        return 0

    # Get the action type (substrate, inhibitor, inducer).
    actions_elem = protein_elem.find("db:actions", ns)
    if actions_elem is None:
        return 0

    action = actions_elem.findtext("db:action", default="", namespaces=ns).lower()

    # Map DrugBank action terms to our edge types.
    action_to_edge = {
        "substrate": "SUBSTRATE_OF",
        "inhibitor": "INHIBITS",
        "inducer": "INDUCES",
    }

    edge_type = action_to_edge.get(action)
    if not edge_type:
        return 0  # Unknown action type (e.g., "unknown", "binder")

    # Get inhibition strength if available (only relevant for inhibitors).
    strength = protein_elem.findtext("db:inhibition-strength", default="unknown", namespaces=ns)
    if strength == "N/A":
        strength = "unknown"

    # Create the protein node (MERGE = create if not exists).
    protein_query = f"""
    MERGE (p:{protein_type} {{protein_id: $protein_id}})
    SET p.name = $name,
        p.source = 'DrugBank',
        p.last_updated = $today
    """
    run_opencypher_query(
        protein_query,
        parameters={
            "protein_id": protein_id,
            "name": protein_name,
            "today": str(date.today()),
        },
        use_writer=True,
    )

    # Create the relationship edge between drug and protein.
    edge_query = f"""
    MATCH (d:Drug {{rxcui: $rxcui}})
    MATCH (p:{protein_type} {{protein_id: $protein_id}})
    MERGE (d)-[r:{edge_type}]->(p)
    SET r.strength = $strength,
        r.source = 'DrugBank',
        r.last_updated = $today
    """
    run_opencypher_query(
        edge_query,
        parameters={
            "rxcui": rxcui,
            "protein_id": protein_id,
            "strength": strength,
            "today": str(date.today()),
        },
        use_writer=True,
    )

    return 1
```

---

## Step 3: Extract Interactions from FDA Drug Labels

*The pseudocode calls this `extract_fda_label_interactions(spl_xml_path)`. FDA Structured Product Labeling files contain a "Drug Interactions" section with semi-structured text. We use Amazon Comprehend Medical to extract medication entities from that text, then create graph edges representing the FDA-reviewed interactions.*

```python
comprehend_medical_client = boto3.client("comprehendmedical", region_name=AWS_REGION)


def extract_fda_label_interactions(bucket: str, key: str) -> int:
    """
    Parse an FDA SPL XML file, extract the Drug Interactions section,
    use Comprehend Medical to identify medication entities, and load
    the resulting interaction edges into Neptune.

    FDA SPL files are XML documents with a specific structure. The drug
    interactions section has a code attribute of "34073-7" (LOINC code
    for "Drug interactions"). The text within that section describes
    known interactions in natural language.

    Comprehend Medical's DetectEntitiesV2 API identifies medication mentions
    and their attributes (dosage, frequency, route). InferRxNorm links those
    mentions to RxNorm CUIs so we can connect them to our graph.

    This is where the graph gets its "Established" evidence level edges.
    FDA-reviewed interaction information is the gold standard for US-marketed drugs.

    Args:
        bucket: S3 bucket containing FDA SPL XML files
        key: S3 key to a specific SPL XML file

    Returns:
        Count of interaction edges loaded from this label.
    """
    logger.info(f"Processing FDA label: s3://{bucket}/{key}")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    # Parse the SPL XML to find the drug interactions section.
    root = ET.fromstring(content)
    # SPL uses HL7 namespace.
    ns = {"hl7": "urn:hl7-org:v3"}

    # Find the subject drug (the drug this label is for).
    subject_name = root.findtext(".//hl7:manufacturedProduct/hl7:name", default="", namespaces=ns)

    # Find the Drug Interactions section by LOINC code.
    interaction_section = None
    for section in root.findall(".//hl7:section", ns):
        code_elem = section.find("hl7:code", ns)
        if code_elem is not None and code_elem.get("code") == "34073-7":
            interaction_section = section
            break

    if interaction_section is None:
        logger.info(f"  No drug interactions section found in {key}")
        return 0

    # Extract all text from the interactions section.
    interaction_text = _extract_section_text(interaction_section, ns)

    if not interaction_text or len(interaction_text) < 20:
        return 0

    # Use Comprehend Medical to find medication entities in the text.
    # The API has a 20,000 character limit per call. Split if needed.
    medication_entities = _extract_medications_from_text(interaction_text)

    # Get the RxNorm CUI for the subject drug.
    subject_rxcui = _infer_rxnorm_cui(subject_name)
    if not subject_rxcui:
        logger.warning(f"  Could not resolve subject drug to RxNorm: {subject_name}")
        return 0

    edges_loaded = 0

    for entity in medication_entities:
        # Skip if it's the subject drug itself (labels mention their own drug).
        if entity["rxcui"] == subject_rxcui:
            continue

        # Create a direct INTERACTS_WITH edge between the two drugs.
        # FDA label = Established evidence level.
        query = """
        MATCH (a:Drug {rxcui: $rxcui_a})
        MATCH (b:Drug {rxcui: $rxcui_b})
        MERGE (a)-[r:INTERACTS_WITH]-(b)
        SET r.source = 'FDA_SPL',
            r.evidence_level = 'Established',
            r.label_text = $context,
            r.last_updated = $today
        """
        run_opencypher_query(
            query,
            parameters={
                "rxcui_a": subject_rxcui,
                "rxcui_b": entity["rxcui"],
                "context": entity.get("context", "")[:500],  # Truncate for storage
                "today": str(date.today()),
            },
            use_writer=True,
        )
        edges_loaded += 1

    logger.info(f"  Loaded {edges_loaded} interaction edges from {subject_name} label.")
    return edges_loaded


def _extract_section_text(section_elem, ns: dict) -> str:
    """
    Recursively extract all text content from an SPL section element.
    SPL sections contain nested <paragraph>, <list>, <item> elements.
    """
    texts = []
    for elem in section_elem.iter():
        if elem.text:
            texts.append(elem.text.strip())
        if elem.tail:
            texts.append(elem.tail.strip())
    return " ".join(t for t in texts if t)


def _extract_medications_from_text(text: str) -> list[dict]:
    """
    Use Comprehend Medical to extract medication entities from text
    and resolve them to RxNorm CUIs.

    Comprehend Medical's DetectEntitiesV2 identifies MEDICATION entities
    with attributes like dosage, route, and frequency. We then use
    InferRxNorm to link each medication mention to its RxNorm concept.

    Args:
        text: Natural language text containing medication mentions.

    Returns:
        List of dicts with keys: name, rxcui, confidence, context
    """
    medications = []

    # Comprehend Medical has a 20,000 character limit per request.
    # Split text into chunks if needed.
    chunks = [text[i:i + 19000] for i in range(0, len(text), 19000)]

    for chunk in chunks:
        # Step 1: Detect medication entities.
        detect_response = comprehend_medical_client.detect_entities_v2(Text=chunk)

        for entity in detect_response.get("Entities", []):
            if entity["Category"] != "MEDICATION":
                continue
            if entity["Score"] < 0.7:
                continue  # Low confidence, skip

            med_name = entity["Text"]

            # Step 2: Resolve to RxNorm CUI.
            rxcui = _infer_rxnorm_cui(med_name)
            if not rxcui:
                continue

            # Grab surrounding context for the label_text property.
            start = max(0, entity["BeginOffset"] - 100)
            end = min(len(chunk), entity["EndOffset"] + 100)
            context = chunk[start:end]

            medications.append({
                "name": med_name,
                "rxcui": rxcui,
                "confidence": entity["Score"],
                "context": context,
            })

    return medications


def _infer_rxnorm_cui(medication_text: str) -> str | None:
    """
    Use Comprehend Medical InferRxNorm to resolve a medication name
    to its RxNorm CUI.

    InferRxNorm takes free text and returns the best-matching RxNorm
    concepts with confidence scores. We take the top result if it's
    above our confidence threshold.

    Args:
        medication_text: Drug name string (e.g., "warfarin", "Coumadin 5mg")

    Returns:
        RxNorm CUI string, or None if no confident match.
    """
    try:
        response = comprehend_medical_client.infer_rx_norm(Text=medication_text)
    except Exception as e:
        logger.warning(f"  InferRxNorm failed for '{medication_text}': {e}")
        return None

    entities = response.get("Entities", [])
    if not entities:
        return None

    # Take the top-scoring concept.
    top = entities[0]
    if top.get("Score", 0) < 0.7:
        return None

    # RxNorm concepts are in the RxNormConcepts list.
    concepts = top.get("RxNormConcepts", [])
    if not concepts:
        return None

    # Prefer ingredient-level concepts (TTY = "IN") for interaction matching.
    for concept in concepts:
        if concept.get("Score", 0) >= 0.7:
            return concept.get("Code")

    return None
```

---

## Step 4: Build the Interaction Query Engine

*The pseudocode calls this `check_interactions(medication_list, patient_context)`. This is the core clinical function. Given a patient's medication list, it traverses the graph to find interaction paths using two strategies: direct curated edges (fast, catches known pairs) and mechanism-based inference (catches interactions that nobody has explicitly curated). It then scores each interaction by clinical significance and returns ranked results.*

```python
def check_interactions(medication_list: list[dict], patient_context: dict = None) -> dict:
    """
    Check a patient's medication list for drug-drug interactions.

    This is the function that clinical systems call at the point of prescribing.
    It combines two strategies:

    1. Direct lookup: Check for explicitly curated INTERACTS_WITH edges between
       drug pairs. These come from FDA labels, DrugBank, and other curated sources.
       Fast and high-confidence, but only catches known pairs.

    2. Mechanism-based inference: Find drugs that share enzyme/transporter targets
       with conflicting relationships (one is a substrate, the other is an inhibitor
       or inducer of the same enzyme). This catches interactions that haven't been
       explicitly curated but are pharmacologically predictable.

    Args:
        medication_list: List of dicts, each with at minimum:
            - rxcui: RxNorm CUI for the drug
            - name: Drug name (for display)
            Optional (improve scoring):
            - dose: Current dose
            - frequency: Dosing frequency
            - duration_days: How long the patient has been on this drug

        patient_context: Optional dict with patient factors that modulate
            interaction severity:
            - age: Patient age in years
            - renal_function: eGFR value (mL/min/1.73m2)
            - hepatic_function: "normal", "mild_impairment", "moderate_impairment", "severe_impairment"
            - weight_kg: Patient weight

    Returns:
        Dict with interaction results, counts, and processing metadata.
    """
    if patient_context is None:
        patient_context = {}

    all_interactions = []

    # Generate all unique pairs from the medication list.
    med_pairs = list(combinations(medication_list, 2))
    logger.info(f"Checking {len(med_pairs)} medication pairs for interactions.")

    # Strategy 1: Direct curated interaction edges.
    for med_a, med_b in med_pairs:
        direct_results = _check_direct_interactions(med_a["rxcui"], med_b["rxcui"])
        for result in direct_results:
            result["drug_a"] = med_a
            result["drug_b"] = med_b
            all_interactions.append(result)

    # Strategy 2: Mechanism-based inference.
    # First, get enzyme/transporter targets for each drug.
    drug_targets = {}
    for med in medication_list:
        drug_targets[med["rxcui"]] = _get_drug_targets(med["rxcui"])

    # Check for conflicting relationships on shared targets.
    for med_a, med_b in med_pairs:
        inferred = _check_mechanism_interactions(
            med_a, med_b,
            drug_targets.get(med_a["rxcui"], []),
            drug_targets.get(med_b["rxcui"], []),
        )
        all_interactions.extend(inferred)

    # Score each interaction by clinical significance.
    scored = []
    for interaction in all_interactions:
        score = _calculate_significance_score(interaction, patient_context)
        interaction["score"] = score
        interaction["recommendation"] = _generate_recommendation(interaction)
        scored.append(interaction)

    # Sort by score descending (most clinically significant first).
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Split into significant (alert-worthy) and suppressed.
    significant = [i for i in scored if i["score"] >= SIGNIFICANCE_THRESHOLD]
    suppressed = [i for i in scored if i["score"] < SIGNIFICANCE_THRESHOLD]

    return {
        "interactions": significant,
        "suppressed_interactions": suppressed,
        "pairs_evaluated": len(med_pairs),
        "total_found": len(all_interactions),
        "total_significant": len(significant),
    }


def _check_direct_interactions(rxcui_a: str, rxcui_b: str) -> list[dict]:
    """
    Query Neptune for direct INTERACTS_WITH edges between two drugs.

    These edges come from curated sources (FDA labels, DrugBank, MED-RT).
    They represent explicitly documented interactions with evidence.
    """
    query = """
    MATCH (a:Drug {rxcui: $rxcui_a})-[r:INTERACTS_WITH]-(b:Drug {rxcui: $rxcui_b})
    RETURN r.source AS source,
           r.evidence_level AS evidence_level,
           r.severity AS severity,
           r.mechanism AS mechanism,
           r.clinical_effect AS clinical_effect,
           r.label_text AS label_text
    """
    response = run_opencypher_query(
        query,
        parameters={"rxcui_a": rxcui_a, "rxcui_b": rxcui_b},
    )

    results = []
    for record in response.get("results", []):
        results.append({
            "type": "direct",
            "source": record.get("source", "Unknown"),
            "evidence_level": record.get("evidence_level", "Suspected"),
            "severity": record.get("severity", "Moderate"),
            "mechanism": record.get("mechanism", "Unknown"),
            "clinical_effect": record.get("clinical_effect", ""),
            "label_text": record.get("label_text", ""),
        })

    return results


def _get_drug_targets(rxcui: str) -> list[dict]:
    """
    Get all enzyme and transporter relationships for a drug.

    Returns a list of targets with the relationship type (SUBSTRATE_OF,
    INHIBITS, INDUCES) and strength.
    """
    query = """
    MATCH (d:Drug {rxcui: $rxcui})-[r]->(t)
    WHERE t:Enzyme OR t:Transporter
    RETURN t.protein_id AS target_id,
           t.name AS target_name,
           type(r) AS relationship,
           r.strength AS strength,
           labels(t)[0] AS target_type
    """
    response = run_opencypher_query(query, parameters={"rxcui": rxcui})

    targets = []
    for record in response.get("results", []):
        targets.append({
            "target_id": record.get("target_id"),
            "target_name": record.get("target_name"),
            "relationship": record.get("relationship"),
            "strength": record.get("strength", "unknown"),
            "target_type": record.get("target_type"),
        })

    return targets


def _check_mechanism_interactions(
    med_a: dict, med_b: dict,
    targets_a: list[dict], targets_b: list[dict],
) -> list[dict]:
    """
    Infer interactions based on shared enzyme/transporter targets.

    The logic: if Drug A is a SUBSTRATE_OF enzyme X, and Drug B INHIBITS
    enzyme X, then Drug B will reduce the metabolism of Drug A, increasing
    its plasma concentration. This is a pharmacokinetic interaction.

    Similarly, if Drug B INDUCES enzyme X, it will increase metabolism of
    Drug A, potentially reducing its therapeutic effect.

    We check both directions (A affects B, B affects A) for each shared target.
    """
    interactions = []

    # Build lookup maps for each drug's targets.
    targets_a_by_id = {t["target_id"]: t for t in targets_a}
    targets_b_by_id = {t["target_id"]: t for t in targets_b}

    # Find shared targets (both drugs interact with the same enzyme/transporter).
    shared_target_ids = set(targets_a_by_id.keys()) & set(targets_b_by_id.keys())

    for target_id in shared_target_ids:
        rel_a = targets_a_by_id[target_id]
        rel_b = targets_b_by_id[target_id]

        # Case 1: A is substrate, B inhibits -> B increases A's levels.
        if rel_a["relationship"] == "SUBSTRATE_OF" and rel_b["relationship"] == "INHIBITS":
            interactions.append({
                "drug_a": med_a,
                "drug_b": med_b,
                "type": "inferred",
                "mechanism": "PK_ENZYME_INHIBITION",
                "target_name": rel_a["target_name"],
                "inhibitor_strength": rel_b["strength"],
                "evidence_level": "Inferred",
                "severity": _infer_severity_from_strength(rel_b["strength"]),
                "clinical_effect": (
                    f"{med_b['name']} inhibits {rel_a['target_name']}, "
                    f"which metabolizes {med_a['name']}. "
                    f"This may increase {med_a['name']} plasma levels."
                ),
            })

        # Case 2: A is substrate, B induces -> B decreases A's levels.
        if rel_a["relationship"] == "SUBSTRATE_OF" and rel_b["relationship"] == "INDUCES":
            interactions.append({
                "drug_a": med_a,
                "drug_b": med_b,
                "type": "inferred",
                "mechanism": "PK_ENZYME_INDUCTION",
                "target_name": rel_a["target_name"],
                "evidence_level": "Inferred",
                "severity": "Moderate",
                "clinical_effect": (
                    f"{med_b['name']} induces {rel_a['target_name']}, "
                    f"which may decrease {med_a['name']} plasma levels "
                    f"and reduce therapeutic effect."
                ),
            })

        # Case 3: B is substrate, A inhibits -> A increases B's levels.
        if rel_b["relationship"] == "SUBSTRATE_OF" and rel_a["relationship"] == "INHIBITS":
            interactions.append({
                "drug_a": med_b,
                "drug_b": med_a,
                "type": "inferred",
                "mechanism": "PK_ENZYME_INHIBITION",
                "target_name": rel_b["target_name"],
                "inhibitor_strength": rel_a["strength"],
                "evidence_level": "Inferred",
                "severity": _infer_severity_from_strength(rel_a["strength"]),
                "clinical_effect": (
                    f"{med_a['name']} inhibits {rel_b['target_name']}, "
                    f"which metabolizes {med_b['name']}. "
                    f"This may increase {med_b['name']} plasma levels."
                ),
            })

        # Case 4: B is substrate, A induces -> A decreases B's levels.
        if rel_b["relationship"] == "SUBSTRATE_OF" and rel_a["relationship"] == "INDUCES":
            interactions.append({
                "drug_a": med_b,
                "drug_b": med_a,
                "type": "inferred",
                "mechanism": "PK_ENZYME_INDUCTION",
                "target_name": rel_b["target_name"],
                "evidence_level": "Inferred",
                "severity": "Moderate",
                "clinical_effect": (
                    f"{med_a['name']} induces {rel_b['target_name']}, "
                    f"which may decrease {med_b['name']} plasma levels "
                    f"and reduce therapeutic effect."
                ),
            })

    return interactions


def _infer_severity_from_strength(inhibition_strength: str) -> str:
    """Map inhibition strength to a severity estimate for inferred interactions."""
    strength_to_severity = {
        "strong": "Major",
        "moderate": "Moderate",
        "weak": "Minor",
        "unknown": "Moderate",  # Conservative default
    }
    return strength_to_severity.get(inhibition_strength, "Moderate")


def _calculate_significance_score(interaction: dict, patient_context: dict) -> float:
    """
    Calculate a clinical significance score for an interaction.

    The score combines:
    - Severity weight (how dangerous is this type of interaction?)
    - Evidence weight (how confident are we this interaction is real?)
    - Inhibition strength (for mechanism-based: how strong is the effect?)
    - Patient factors (age, organ function modify the risk)

    Score range: 0.0 to 1.0. Higher = more clinically significant.
    """
    severity = interaction.get("severity", "Moderate")
    evidence = interaction.get("evidence_level", "Suspected")

    base_score = SEVERITY_WEIGHTS.get(severity, 0.5)
    evidence_multiplier = EVIDENCE_WEIGHTS.get(evidence, 0.5)

    score = base_score * evidence_multiplier

    # For inferred interactions, factor in inhibition strength.
    if interaction.get("type") == "inferred":
        strength = interaction.get("inhibitor_strength", "unknown")
        strength_mult = INHIBITION_STRENGTH_MULTIPLIERS.get(strength, 0.5)
        score *= strength_mult

    # Patient context modifiers.
    age = patient_context.get("age")
    if age and age > 75:
        # Elderly patients have reduced clearance. Interactions hit harder.
        score *= 1.15

    hepatic = patient_context.get("hepatic_function", "normal")
    if hepatic in ("moderate_impairment", "severe_impairment"):
        # Impaired liver function means CYP-mediated interactions are amplified.
        if "ENZYME" in interaction.get("mechanism", ""):
            score *= 1.2

    # Cap at 1.0.
    return min(score, 1.0)


def _generate_recommendation(interaction: dict) -> str:
    """
    Generate a brief clinical recommendation based on the interaction type.

    In production, these would come from a curated recommendation database
    or clinical decision support rules. This is a simplified placeholder
    that demonstrates the pattern.
    """
    mechanism = interaction.get("mechanism", "")
    severity = interaction.get("severity", "Moderate")
    target = interaction.get("target_name", "")

    if severity == "Contraindicated":
        return "Avoid combination. Consider therapeutic alternative."

    if mechanism == "PK_ENZYME_INHIBITION":
        drug_a_name = interaction.get("drug_a", {}).get("name", "substrate drug")
        return (
            f"Monitor for increased {drug_a_name} effects. "
            f"Consider dose reduction or enhanced monitoring. "
            f"Mechanism: {target} inhibition."
        )

    if mechanism == "PK_ENZYME_INDUCTION":
        drug_a_name = interaction.get("drug_a", {}).get("name", "substrate drug")
        return (
            f"Monitor for decreased {drug_a_name} efficacy. "
            f"Consider dose increase or therapeutic drug monitoring. "
            f"Mechanism: {target} induction."
        )

    return "Monitor patient. Review clinical significance for this combination."
```

---

## Step 5: Cache and Serve Results

*The pseudocode calls this `serve_interaction_check(request)`. Clinical systems need sub-second response times. We cache the raw interaction paths (before patient-specific scoring) so that repeated checks for common drug combinations skip the graph traversal entirely. Patient-specific scoring is fast (just arithmetic), so we apply it fresh each time.*

```python
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def serve_interaction_check(request: dict) -> dict:
    """
    Entry point for clinical system interaction checks. Handles caching
    to ensure sub-second response times for common drug combinations.

    The caching strategy: we cache the raw interaction paths (the graph
    traversal results) keyed by the sorted set of RxCUIs. Patient context
    is NOT part of the cache key because it varies per patient. We re-apply
    patient-specific scoring on every request, which is fast (just math).

    This means a cache hit still produces patient-specific results. The
    expensive part (graph traversal) is cached; the cheap part (scoring)
    runs fresh.

    Args:
        request: Dict with:
            - medications: List of medication dicts (rxcui, name, dose, etc.)
            - patient_context: Optional patient factors dict

    Returns:
        Interaction check results (same format as check_interactions).
    """
    medications = request.get("medications", [])
    patient_context = request.get("patient_context", {})

    if len(medications) < 2:
        return {
            "interactions": [],
            "suppressed_interactions": [],
            "pairs_evaluated": 0,
            "total_found": 0,
            "total_significant": 0,
            "cache_hit": False,
        }

    # Generate cache key from sorted RxCUIs.
    # Sorting ensures the same drug set always produces the same key
    # regardless of the order they were submitted.
    sorted_rxcuis = sorted(m["rxcui"] for m in medications)
    cache_key = "ddi:" + "_".join(sorted_rxcuis)

    # Check cache for raw interaction paths.
    cached = redis_client.get(cache_key)

    if cached:
        # Cache hit. Re-score with this patient's context.
        raw_interactions = json.loads(cached)
        logger.info(f"Cache hit for {cache_key}. Re-scoring {len(raw_interactions)} interactions.")

        scored = []
        for interaction in raw_interactions:
            score = _calculate_significance_score(interaction, patient_context)
            interaction["score"] = score
            interaction["recommendation"] = _generate_recommendation(interaction)
            scored.append(interaction)

        scored.sort(key=lambda x: x["score"], reverse=True)
        significant = [i for i in scored if i["score"] >= SIGNIFICANCE_THRESHOLD]
        suppressed = [i for i in scored if i["score"] < SIGNIFICANCE_THRESHOLD]

        return {
            "interactions": significant,
            "suppressed_interactions": suppressed,
            "pairs_evaluated": len(list(combinations(medications, 2))),
            "total_found": len(raw_interactions),
            "total_significant": len(significant),
            "cache_hit": True,
        }

    # Cache miss. Run full graph traversal.
    logger.info(f"Cache miss for {cache_key}. Running full interaction check.")
    result = check_interactions(medications, patient_context)

    # Cache the raw interactions (before patient-specific scoring).
    # We store all found interactions, not just significant ones,
    # because significance depends on patient context which varies.
    all_interactions = result["interactions"] + result["suppressed_interactions"]

    # Strip patient-specific fields before caching.
    cacheable = []
    for interaction in all_interactions:
        cache_entry = {k: v for k, v in interaction.items() if k not in ("score", "recommendation")}
        cacheable.append(cache_entry)

    redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(cacheable, default=str))

    result["cache_hit"] = False
    return result


def invalidate_cache():
    """
    Flush the interaction cache. Call this after loading new source data
    into the graph to ensure queries reflect the latest knowledge.

    In production, you'd use a more targeted approach: track which drugs
    were affected by the update and only invalidate cache keys containing
    those RxCUIs. But for weekly full rebuilds, flushing everything is simpler.
    """
    # SCAN for all keys with our prefix and delete them.
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match="ddi:*", count=100)
        if keys:
            redis_client.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break

    logger.info(f"Cache invalidated. {deleted} keys deleted.")
```

---

## Full Pipeline: Putting It All Together

This assembles all the steps into a runnable pipeline. The ingestion pipeline loads source data into the graph. The query function checks medications for interactions.

```python
def run_ingestion_pipeline():
    """
    Full ingestion pipeline: load all source data into the interaction graph.

    In production, this runs on a schedule (weekly for most sources).
    Each source has its own Lambda function; this combines them for
    demonstration purposes.
    """
    print("=" * 60)
    print("DRUG-DRUG INTERACTION KNOWLEDGE BASE - INGESTION PIPELINE")
    print("=" * 60)

    # Step 1: Load RxNorm drug concepts and relationships.
    print("\n[Step 1] Loading RxNorm drug concepts...")
    nodes = ingest_rxnorm_concepts(SOURCE_BUCKET, "rxnorm/RXNCONSO.RRF")
    print(f"  -> {nodes} drug nodes loaded")

    print("\n[Step 1b] Loading RxNorm relationships...")
    edges = ingest_rxnorm_relationships(SOURCE_BUCKET, "rxnorm/RXNREL.RRF")
    print(f"  -> {edges} relationship edges loaded")

    # Step 2: Load DrugBank enzyme/transporter mechanisms.
    print("\n[Step 2] Loading DrugBank mechanisms...")
    mechanisms = ingest_drugbank_mechanisms(SOURCE_BUCKET, "drugbank/full_database.xml")
    print(f"  -> {mechanisms} mechanism edges loaded")

    # Step 3: Process FDA labels for curated interactions.
    # In production, you'd iterate over all SPL files in the bucket.
    print("\n[Step 3] Processing FDA SPL labels...")
    # Example: process a single label for demonstration.
    fda_edges = extract_fda_label_interactions(SOURCE_BUCKET, "fda-spl/warfarin.xml")
    print(f"  -> {fda_edges} interaction edges from FDA labels")

    # Invalidate cache after loading new data.
    print("\n[Cache] Invalidating interaction cache...")
    invalidate_cache()

    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)


def run_interaction_check_demo():
    """
    Demonstrate the interaction checking query path.

    This simulates what happens when a physician orders a new medication
    for a patient who is already on several drugs.
    """
    print("\n" + "=" * 60)
    print("DRUG-DRUG INTERACTION CHECK - DEMO")
    print("=" * 60)

    # Simulated patient medication list.
    # This is the classic scenario from the recipe: a patient on warfarin
    # with multiple co-medications.
    medications = [
        {"rxcui": "11289", "name": "warfarin", "dose": "5mg", "frequency": "daily"},
        {"rxcui": "519", "name": "amiodarone", "dose": "200mg", "frequency": "daily"},
        {"rxcui": "6851", "name": "metoprolol", "dose": "50mg", "frequency": "twice daily"},
        {"rxcui": "29046", "name": "lisinopril", "dose": "10mg", "frequency": "daily"},
        {"rxcui": "83367", "name": "atorvastatin", "dose": "40mg", "frequency": "daily"},
    ]

    # Patient context for severity scoring.
    patient_context = {
        "age": 72,
        "renal_function": 55,  # eGFR mL/min/1.73m2 (mild impairment)
        "hepatic_function": "normal",
        "weight_kg": 78,
    }

    print(f"\nPatient medications ({len(medications)}):")
    for med in medications:
        print(f"  - {med['name']} {med['dose']} {med['frequency']}")

    print(f"\nPatient context: age={patient_context['age']}, "
          f"eGFR={patient_context['renal_function']}, "
          f"hepatic={patient_context['hepatic_function']}")

    # Run the interaction check.
    request = {
        "medications": medications,
        "patient_context": patient_context,
    }

    print("\nChecking interactions...")
    result = serve_interaction_check(request)

    print(f"\nResults:")
    print(f"  Pairs evaluated: {result['pairs_evaluated']}")
    print(f"  Total interactions found: {result['total_found']}")
    print(f"  Clinically significant: {result['total_significant']}")
    print(f"  Cache hit: {result['cache_hit']}")

    if result["interactions"]:
        print(f"\n--- SIGNIFICANT INTERACTIONS ---")
        for i, interaction in enumerate(result["interactions"], 1):
            drug_a = interaction.get("drug_a", {}).get("name", "?")
            drug_b = interaction.get("drug_b", {}).get("name", "?")
            print(f"\n  [{i}] {drug_a} + {drug_b}")
            print(f"      Severity: {interaction.get('severity', '?')}")
            print(f"      Mechanism: {interaction.get('mechanism', '?')}")
            print(f"      Evidence: {interaction.get('evidence_level', '?')}")
            print(f"      Score: {interaction.get('score', 0):.2f}")
            print(f"      Effect: {interaction.get('clinical_effect', '?')}")
            print(f"      Recommendation: {interaction.get('recommendation', '?')}")

    if result["suppressed_interactions"]:
        print(f"\n--- SUPPRESSED (below threshold {SIGNIFICANCE_THRESHOLD}) ---")
        for interaction in result["suppressed_interactions"][:3]:
            drug_a = interaction.get("drug_a", {}).get("name", "?")
            drug_b = interaction.get("drug_b", {}).get("name", "?")
            print(f"  - {drug_a} + {drug_b}: score={interaction.get('score', 0):.2f}")


if __name__ == "__main__":
    # Uncomment the pipeline you want to run:

    # Run the ingestion pipeline (loads source data into Neptune):
    # run_ingestion_pipeline()

    # Run an interaction check demo (queries the graph):
    run_interaction_check_demo()
```

---

## Gap to Production

This example demonstrates the shape of a drug interaction knowledge graph system. Here's what you'd need to add before deploying it to a pharmacy or EHR:

**Error handling and retries.** Every Neptune query, S3 read, Comprehend Medical call, and Redis operation can fail. Production code needs exponential backoff with jitter (use `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})`), circuit breakers for Neptune connectivity issues, and graceful degradation (if the cache is down, skip it and query Neptune directly).

**Connection pooling.** This example creates a new HTTPS connection for every Neptune query. In production, use a session with connection pooling (`requests.Session()`) or the Neptune Python driver with connection reuse. For Lambda, connections persist across warm invocations within the same execution environment.

**Input validation.** The interaction check endpoint needs to validate that RxCUIs are well-formed, medication lists aren't absurdly long (cap at 30-50 medications to prevent quadratic blowup), and patient context values are within reasonable ranges. Malformed input should return a 400, not crash the Lambda.

**Structured logging.** Replace print statements with structured JSON logging. Log query latency, cache hit rates, interaction counts, and graph traversal depth. Never log patient medication lists (PHI). Log anonymized metrics only: "checked 5 medications, found 2 significant interactions, latency 145ms."

**IAM least-privilege.** The query Lambda needs only `neptune-db:ReadDataViaQuery`. The ingestion Lambdas need `neptune-db:WriteDataViaQuery` and `s3:GetObject`. Separate the roles. Use resource-level ARN scoping for Neptune permissions.

**VPC and networking.** Neptune requires VPC deployment. Lambda functions must be in the same VPC with security groups allowing outbound to Neptune (port 8182) and ElastiCache (port 6379). Add VPC endpoints for S3 (gateway type), Comprehend Medical (interface type), CloudWatch Logs, and KMS to avoid NAT Gateway costs and latency.

**KMS encryption.** Use customer-managed KMS keys (CMKs) for Neptune encryption at rest, S3 bucket encryption, and ElastiCache at-rest encryption. Enable in-transit encryption for ElastiCache. All API traffic should be TLS 1.2+.

**Neptune bulk loading.** This example uses individual MERGE queries for loading, which is fine for small datasets but painfully slow for the full RxNorm (800K+ concepts). Production ingestion should format data as Neptune bulk load CSVs, upload to S3, and use the Neptune Loader API (`POST /loader`) for initial loads. Use individual queries only for incremental updates.

**Deduplication and conflict resolution.** When multiple sources disagree about an interaction's severity (DrugBank says "Moderate," FDA label implies "Major"), you need reconciliation logic. Common approach: take the highest severity from any authoritative source, but track all source assessments so clinicians can see the range.

**Graph versioning and audit trail.** Every edge should carry a `version` property indicating which source data version created it. When a clinician asks "why did the system flag this?", you need to trace back to the specific source file, version, and extraction logic that produced that edge. Store source file S3 version IDs alongside graph edges.

**Testing.** Unit tests for each parsing function with known-good source file snippets. Integration tests that load a small reference dataset and verify expected interaction paths are found. Regression tests with a curated set of "must-catch" interactions (warfarin + fluconazole, methotrexate + NSAIDs, etc.) and "must-not-alert" pairs (clinically insignificant combinations that would cause alert fatigue).

**Monitoring and alerting.** CloudWatch alarms for: query latency exceeding 500ms (p99), cache hit rate dropping below 80%, Neptune CPU exceeding 70%, ingestion pipeline failures. Dashboard showing: daily query volume, top-queried drug combinations, override rates (if integrated with EHR feedback), and graph size metrics.

**Clinical validation.** Before go-live, have clinical pharmacists review a sample of the system's output against known interaction databases (FDB, Medi-Span). Measure sensitivity (does it catch known major interactions?) and specificity (does it avoid alerting on clinically insignificant pairs?). The 90-96% override rate in existing systems is your benchmark to beat.

---

*← [Recipe 13.4: Drug-Drug Interaction Knowledge Base](chapter13.04-drug-drug-interaction-knowledge-base) | [Chapter 13 Index](chapter13-index) | [Recipe 13.5: Clinical Pathway / Protocol Modeling](chapter13.05-clinical-pathway-protocol-modeling) →*
