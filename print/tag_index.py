#!/usr/bin/env python3
"""Generate Appendix B: a tag index with page numbers, derived at build time.

Replaces the hand-curated index-terms.json index. Two reasons:

  * A hand-maintained index drifts. This one cannot: it reads the ## Tags section
    of every recipe on every build.
  * The curated index pointed at recipe *numbers* across all 152 recipes, but only
    15 are in the printed book, so a reader got "5.5, 5.8, 5.9" with no way to
    reach a page. This gives the page for recipes that are in the book, and keeps
    the digital-edition pointers for the rest.

Page numbers come from build/toc-pagemap.json, which the two-pass PDF render
produces. On a first pass the file is absent and entries render without pages;
the second pass fills them in. Because the appendices sit at the back of the
book, their own length does not move the recipe pages they cite, so the two-pass
result is stable.

Importable by print/build.py; also runnable standalone to inspect the output:
  python3 print/tag_index.py            # markdown to stdout
  python3 print/tag_index.py --stats
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict

# A tag carried by most recipes cannot help a reader find anything, so it is
# listed as pervasive rather than enumerated. The curated index this replaces made
# the same call. Note this is a *presentation* limit on an index entry, not a limit
# on the underlying tags, which stay complete on every recipe.
PERVASIVE_SHARE = 0.40
MAX_ENUMERATED = 12

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TAGS_BLOCK = re.compile(r"^## Tags\s*\n(.+?)(?=\n##|\n---|\Z)", re.S | re.M)
COMPANION = re.compile(
    r"-(todo|architecture|python-example|preface|index|executive-summary)\.md$"
)

# Tags whose display name is not simply the tag title-cased.
DISPLAY = {
    "42-cfr-part-2": "42 CFR Part 2",
    "a2i": "Amazon Augmented AI (A2I)",
    "adt": "ADT feed",
    "api-gateway": "Amazon API Gateway",
    "appsync": "AWS AppSync",
    "athena": "Amazon Athena",
    "aurora-pgvector": "Amazon Aurora (pgvector)",
    "aws-batch": "AWS Batch",
    "bedrock": "Amazon Bedrock",
    "bedrock-agents": "Amazon Bedrock Agents",
    "bedrock-guardrails": "Amazon Bedrock Guardrails",
    "bedrock-knowledge-bases": "Amazon Bedrock Knowledge Bases",
    "bipa": "BIPA (biometric privacy)",
    "chime-sdk": "Amazon Chime SDK",
    "cloudtrail": "AWS CloudTrail",
    "cloudwatch": "Amazon CloudWatch",
    "cnn": "Convolutional neural networks",
    "cognito": "Amazon Cognito",
    "comprehend": "Amazon Comprehend",
    "comprehend-medical": "Amazon Comprehend Medical",
    "connect": "Amazon Connect",
    "cpt": "CPT codes",
    "cures-act": "21st Century Cures Act",
    "dicom": "DICOM",
    "dynamodb": "Amazon DynamoDB",
    "ehr-integration": "EHR integration",
    "elasticache": "Amazon ElastiCache",
    "eventbridge": "Amazon EventBridge",
    "fda-pathway": "FDA regulatory pathway",
    "fhir": "FHIR",
    "gnn": "Graph neural networks",
    "glue": "AWS Glue",
    "healthimaging": "AWS HealthImaging",
    "healthlake": "AWS HealthLake",
    "healthscribe": "AWS HealthScribe",
    "hedis": "HEDIS measures",
    "hipaa": "HIPAA",
    "hl7": "HL7 v2",
    "icd-10": "ICD-10 coding",
    "icu": "Intensive care",
    "kinesis": "Amazon Kinesis",
    "kinesis-firehose": "Amazon Data Firehose",
    "kms": "AWS KMS",
    "lake-formation": "AWS Lake Formation",
    "lambda": "AWS Lambda",
    "lex": "Amazon Lex",
    "llm": "Large language models",
    "location-service": "Amazon Location Service",
    "loinc": "LOINC",
    "ncpdp": "NCPDP",
    "ndc": "NDC codes",
    "ner": "Named entity recognition",
    "neptune": "Amazon Neptune",
    "nlp": "Natural language processing",
    "no-surprises-act": "No Surprises Act",
    "nova": "Amazon Nova",
    "ocr": "Optical character recognition",
    "opensearch": "Amazon OpenSearch",
    "opensearch-serverless": "Amazon OpenSearch Serverless",
    "phi-handling": "PHI handling",
    "pinpoint": "Amazon Pinpoint",
    "polly": "Amazon Polly",
    "quicksight": "Amazon QuickSight",
    "rag": "Retrieval-augmented generation",
    "rekognition": "Amazon Rekognition",
    "rxnorm": "RxNorm",
    "s3": "Amazon S3",
    "sagemaker": "Amazon SageMaker",
    "sagemaker-clarify": "Amazon SageMaker Clarify",
    "sagemaker-model-monitor": "Amazon SageMaker Model Monitor",
    "sdoh": "Social determinants of health",
    "secrets-manager": "AWS Secrets Manager",
    "smart-on-fhir": "SMART on FHIR",
    "snomed": "SNOMED CT",
    "sns": "Amazon SNS",
    "sqs": "Amazon SQS",
    "step-functions": "AWS Step Functions",
    "textract": "Amazon Textract",
    "timestream": "Amazon Timestream",
    "transcribe-medical": "Amazon Transcribe Medical",
    "waf": "AWS WAF",
    "x12": "X12 EDI",
}


def display(tag: str) -> str:
    if tag in DISPLAY:
        return DISPLAY[tag]
    return tag.replace("-", " ")[:1].upper() + tag.replace("-", " ")[1:]


def recipe_tags() -> dict[str, list[str]]:
    """Map recipe number ("10.7") -> its tags, across all recipes in the repo."""
    out: dict[str, list[str]] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "chapter*.md"))):
        name = os.path.basename(path)
        if COMPANION.search(name):
            continue
        m = re.match(r"chapter(\d+)\.(\d+)-", name)
        if not m:
            continue
        num = f"{int(m.group(1))}.{int(m.group(2))}"
        with open(path, encoding="utf-8") as fh:
            block = TAGS_BLOCK.search(fh.read())
        if block:
            out[num] = [t.lower() for t in re.findall(r"`([^`]+)`", block.group(1))]
    return out


def load_pagemap() -> dict[str, int]:
    try:
        with open(os.path.join(HERE, "build", "toc-pagemap.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        return {}


def build(built: list[dict], url: str) -> tuple[str, str] | None:
    """Return ("backmatter index", markdown) for Appendix B."""
    tags_by_recipe = recipe_tags()
    if not tags_by_recipe:
        return None
    pagemap = load_pagemap()

    # recipe number -> (print chapter, page) for the recipes actually in this book
    in_book: dict[str, tuple[int, str]] = {}
    for b in built:
        in_book[str(b["recipe"])] = (b["print_chapter"],
                                     str(pagemap.get(str(b["print_chapter"]), "")))

    entries: dict[str, dict[str, list]] = defaultdict(lambda: {"here": [], "online": []})
    for num, tags in tags_by_recipe.items():
        for t in tags:
            if num in in_book:
                entries[t]["here"].append((in_book[num][0], in_book[num][1], num))
            else:
                entries[t]["online"].append(num)

    def rnum(s: str) -> tuple[int, int]:
        a, b = s.split("."); return (int(a), int(b))

    out = ["# Appendix B: Topic and Service Index", ""]
    out.append(
        "Every topic, technique, and service tagged across the cookbook. **Bold page "
        "numbers** locate the chapters printed in this book. Entries also list the "
        "recipes that cover the same topic in the digital edition, by recipe number; "
        f"find those at {url}. Generated from the recipe tags on every build, so it "
        "cannot drift from the text."
    )
    out.append("")

    # Split off the pervasive tags before rendering entries.
    total = len(tags_by_recipe)
    pervasive = sorted(
        (t for t in entries
         if (len(entries[t]["here"]) + len(entries[t]["online"])) / total >= PERVASIVE_SHARE),
        key=lambda t: display(t).lower(),
    )
    if pervasive:
        names = ", ".join(display(t) for t in pervasive)
        out += [
            f"*Carried by most recipes and therefore not enumerated below: {names}.*",
            "",
        ]
    for t in pervasive:
        del entries[t]

    group = None
    for tag in sorted(entries, key=lambda t: display(t).lower()):
        name = display(tag)
        first = name[0].upper()
        g = "0-9" if first.isdigit() else first
        if g != group:
            group = g
            out += [f"### {g}", ""]

        here = sorted(entries[tag]["here"])
        online = sorted(entries[tag]["online"], key=rnum)
        parts = []
        for chap, page, num in here:
            parts.append(f"**{page}** (Chapter {chap})" if page else f"Chapter {chap}")
        line = f"**{name}** "
        line += ", ".join(parts) if parts else ""
        if online:
            tail = "also " if parts else "digital edition only: "
            shown = online[:MAX_ENUMERATED]
            more = len(online) - len(shown)
            listing = ", ".join(shown) + (f", and {more} more" if more else "")
            line += ("; " if parts else "") + tail + listing
        out += [line.strip(), ""]

    return ("backmatter index", "\n".join(out))


def _stats() -> None:
    t = recipe_tags()
    pm = load_pagemap()
    allt = {x for v in t.values() for x in v}
    print(f"  recipes with tags : {len(t)}")
    print(f"  distinct tags     : {len(allt)}")
    print(f"  pagemap entries   : {len(pm)}")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        _stats()
    else:
        man = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
        built = [dict(f, recipe=f["recipe"]) for f in man["flagship"]]
        res = build(built, man.get("digital_edition_url", ""))
        print(res[1] if res else "(no output)")
