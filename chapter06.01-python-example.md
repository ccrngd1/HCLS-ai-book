# Recipe 6.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 6.1. It's meant to show one way you could translate geographic patient clustering concepts into working Python code. It is not production-ready. There's no error handling, no retry logic, no input validation. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy against 200,000 real patient records on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few scientific computing libraries:

```bash
pip install boto3 numpy scikit-learn
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `geo:SearchPlaceIndexForText` and `geo:BatchSearchPlaceIndexForText` (Amazon Location Service geocoding)
- `s3:GetObject` and `s3:PutObject` (reading address data, writing results)
- `dynamodb:PutItem` and `dynamodb:BatchWriteItem` (storing cluster assignments and metadata)

You'll also need an Amazon Location Service Place Index created in your account. The Place Index is the resource that actually performs geocoding. Create one in the console or via CLI with a data provider (Esri or HERE).

---

## Config and Constants

These go at the top of your module. They're configuration, not logic. Readers should see the knobs before the functions that use them.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
from botocore.config import Config
from sklearn.cluster import DBSCAN

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log patient addresses or coordinates.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Adaptive mode uses exponential backoff
# with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Geocoding Configuration ---

# The name of your Amazon Location Service Place Index.
# Create this in the AWS console or via CLI before running this code.
PLACE_INDEX_NAME = "patient-geocoding-index"

# Confidence threshold for geocoding results. Below this, the coordinate
# is too uncertain to trust for clustering. Route to manual review instead.
GEOCODE_CONFIDENCE_THRESHOLD = 0.85

# Batch size for Location Service. The API supports up to 50 addresses per call.
GEOCODE_BATCH_SIZE = 50

# --- Clustering Configuration ---

# DBSCAN epsilon: maximum distance (in km) between two points to be neighbors.
# 3 km is roughly "within a 5-minute drive in suburban areas."
# Smaller = tighter clusters, more noise. Larger = looser clusters.
EPSILON_KM = 3.0

# DBSCAN min_samples: minimum patients to form a cluster core.
# 100 means only areas with real population density become clusters.
MIN_SAMPLES = 100

# --- Service Area Bounding Box ---
# Define the geographic bounds of your service area.
# Points outside this box are excluded from clustering.
# This example uses a bounding box around the Cincinnati, OH metro area.
BOUNDING_BOX = {
    "min_lat": 38.8,
    "max_lat": 39.4,
    "min_lon": -84.9,
    "max_lon": -84.2,
}

# --- Storage Configuration ---
DYNAMODB_PATIENT_TABLE = "patient-clusters"
DYNAMODB_METADATA_TABLE = "cluster-metadata"
S3_RESULTS_BUCKET = "my-cluster-results"
```

---

## Synthetic Data Generation

Since we can't use real patient data in examples (PHI, obviously), here's a function that generates realistic-looking patient records with addresses scattered around a metro area. In production, you'd pull this from your EHR extract or enrollment file.

```python
import random
from datetime import date

def generate_synthetic_patients(num_patients: int = 1000) -> list[dict]:
    """
    Generate synthetic patient records with addresses in the Cincinnati metro area.

    This creates fake but realistic-looking data for testing the pipeline.
    The addresses are fictional. The geographic distribution mimics real
    population patterns: denser in the urban core, sparser in the suburbs.

    In production, this function is replaced by a query against your EHR or
    enrollment database. The output schema should match what's shown here.
    """
    # Cluster centers representing population density hotspots.
    # Real populations aren't uniformly distributed; they clump around
    # town centers, transit hubs, and commercial areas.
    density_centers = [
        (39.10, -84.51, 0.30),   # downtown Cincinnati (high density)
        (39.16, -84.46, 0.20),   # Norwood/Xavier area
        (39.05, -84.67, 0.15),   # western suburbs
        (39.25, -84.55, 0.10),   # northern suburbs (Sharonville)
        (38.95, -84.35, 0.10),   # eastern Kentucky side
        (39.20, -84.37, 0.08),   # Loveland/Milford area
        (39.07, -84.32, 0.07),   # far east (sparse)
    ]

    payers = ["Medicare", "Commercial", "Medicaid", "Self-Pay"]
    payer_weights = [0.30, 0.45, 0.18, 0.07]

    patients = []
    for i in range(num_patients):
        # Pick a density center weighted by population share
        center_lat, center_lon, weight = random.choices(
            density_centers, weights=[c[2] for c in density_centers]
        )[0]

        # Scatter around the center with Gaussian noise.
        # Standard deviation of ~0.02 degrees is roughly 2 km.
        lat = center_lat + random.gauss(0, 0.02)
        lon = center_lon + random.gauss(0, 0.025)

        # Generate a plausible age (skewed older for healthcare populations)
        age = max(0, min(100, int(random.gauss(55, 18))))

        patients.append({
            "patient_id": f"PAT-{i:06d}",
            "address_line_1": f"{random.randint(100, 9999)} {random.choice(['Main', 'Oak', 'Elm', 'Park', 'Highland', 'River', 'Valley'])} {random.choice(['St', 'Ave', 'Dr', 'Rd', 'Blvd'])}",
            "city": random.choice(["Cincinnati", "Norwood", "Sharonville", "Loveland", "Florence"]),
            "state": random.choice(["OH", "OH", "OH", "OH", "KY"]),
            "zip_code": random.choice(["45202", "45203", "45206", "45219", "45220", "45241", "45140", "41042"]),
            "date_of_birth": date(2026 - age, random.randint(1, 12), random.randint(1, 28)).isoformat(),
            "primary_payer": random.choices(payers, weights=payer_weights)[0],
            "visit_count_12mo": max(0, int(random.gauss(4, 3))),
            "last_visit_date": date(2026, random.randint(1, 5), random.randint(1, 28)).isoformat(),
            # Pre-computed coordinates for the synthetic data.
            # In production, these come from the geocoding step (Step 2).
            "_synthetic_lat": lat,
            "_synthetic_lon": lon,
            "is_po_box": random.random() < 0.05,  # 5% PO Boxes
        })

    return patients
```

---

## Step 1: Extract and Prepare Address Data

*The pseudocode calls this `extract_patient_addresses(source_connection)`. It pulls patient records and applies basic quality filtering before geocoding.*

```python
def extract_patient_addresses(patients: list[dict]) -> list[dict]:
    """
    Apply basic quality filtering to patient records before geocoding.

    In production, this function would query your EHR or data warehouse.
    Here, it takes the synthetic data and filters out records that would
    waste geocoding API calls (missing addresses, known PO Boxes flagged
    for special handling).

    Args:
        patients: Raw patient records from your source system.

    Returns:
        Cleaned records ready for geocoding. PO Boxes are flagged but retained.
    """
    cleaned = []
    po_box_count = 0

    for record in patients:
        # Skip records with no address (can't geocode nothing)
        if not record.get("address_line_1"):
            continue

        # Standardize state abbreviation (already done in synthetic data,
        # but in production you'd handle "Ohio" -> "OH" here)
        record["state"] = record["state"].upper().strip()

        # Flag PO Boxes. They geocode to the post office, not the patient's home.
        if record.get("is_po_box"):
            po_box_count += 1

        cleaned.append(record)

    logger.info(
        "Extracted %d records. %d PO Boxes flagged.", len(cleaned), po_box_count
    )
    return cleaned
```

---

## Step 2: Geocode Addresses to Coordinates

*The pseudocode calls this `geocode_addresses(records, place_index_name)`. It sends addresses to Amazon Location Service in batches and returns coordinates with confidence scores.*

```python
# Create a Location Service client.
location_client = boto3.client("location", config=BOTO3_RETRY_CONFIG)


def geocode_addresses(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Convert patient addresses to latitude/longitude coordinates using
    Amazon Location Service batch geocoding.

    Processes addresses in batches of 50 (the API limit). Each result
    includes a relevance score that we use as a confidence gate: low-relevance
    results get routed to a "failed" list rather than silently included
    with bad coordinates.

    Args:
        records: Patient records with address fields populated.

    Returns:
        Tuple of (geocoded_records, failed_records).
        Geocoded records have latitude and longitude populated.
        Failed records have a failure reason attached.
    """
    geocoded = []
    failed = []

    # Process in batches of GEOCODE_BATCH_SIZE
    for batch_start in range(0, len(records), GEOCODE_BATCH_SIZE):
        batch = records[batch_start : batch_start + GEOCODE_BATCH_SIZE]

        # Build the batch request. Each entry is a full address string.
        search_texts = []
        for record in batch:
            full_address = (
                f"{record['address_line_1']}, "
                f"{record['city']}, {record['state']} {record['zip_code']}"
            )
            search_texts.append(full_address)

        # Call Amazon Location Service batch geocoding API.
        # Each text entry gets its own result in the response.
        response = location_client.search_place_index_for_suggestions(
            IndexName=PLACE_INDEX_NAME,
            Text=search_texts[0],  # Note: for true batch, use the loop below
        )

        # In practice, you'd call SearchPlaceIndexForText per address or use
        # a batch pattern. Amazon Location Service doesn't have a native batch
        # geocode API as of early 2026, so you loop through individually or
        # use concurrent requests. Here's the per-address pattern:
        for record, address_text in zip(batch, search_texts):
            try:
                geo_response = location_client.search_place_index_for_text(
                    IndexName=PLACE_INDEX_NAME,
                    Text=address_text,
                    MaxResults=1,
                )

                results = geo_response.get("Results", [])
                if not results:
                    record["geocode_failure_reason"] = "no_results"
                    failed.append(record)
                    continue

                # The first result is the best match.
                place = results[0]["Place"]
                relevance = results[0].get("Relevance", 0.0)

                if relevance >= GEOCODE_CONFIDENCE_THRESHOLD:
                    # Coordinates are returned as [longitude, latitude] (GeoJSON order)
                    record["longitude"] = place["Geometry"]["Point"][0]
                    record["latitude"] = place["Geometry"]["Point"][1]
                    record["geocode_confidence"] = relevance
                    geocoded.append(record)
                else:
                    record["geocode_confidence"] = relevance
                    record["geocode_failure_reason"] = "low_confidence"
                    failed.append(record)

            except Exception as e:
                # In production: specific exception handling for throttling,
                # service errors, and malformed addresses.
                record["geocode_failure_reason"] = str(e)
                failed.append(record)

    logger.info(
        "Geocoded %d successfully. %d below confidence threshold or failed.",
        len(geocoded),
        len(failed),
    )
    return geocoded, failed


def geocode_addresses_synthetic(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Bypass version that uses pre-computed synthetic coordinates.

    Use this for local testing without making real API calls.
    In production, use geocode_addresses() above.
    """
    geocoded = []
    failed = []

    for record in records:
        if "_synthetic_lat" in record and "_synthetic_lon" in record:
            record["latitude"] = record["_synthetic_lat"]
            record["longitude"] = record["_synthetic_lon"]
            record["geocode_confidence"] = 0.95
            geocoded.append(record)
        else:
            record["geocode_failure_reason"] = "no_synthetic_coords"
            failed.append(record)

    logger.info(
        "Synthetic geocoding: %d success, %d failed.", len(geocoded), len(failed)
    )
    return geocoded, failed
```

---

## Step 3: Clean and Filter Coordinates

*The pseudocode calls this `clean_coordinates(geocoded_records, bounding_box)`. It removes invalid coordinates and points outside the service area.*

```python
def clean_coordinates(
    geocoded_records: list[dict], bounding_box: dict
) -> tuple[list[dict], list[dict]]:
    """
    Filter geocoded records to remove invalid or out-of-bounds coordinates.

    Catches two common problems:
    1. Null Island (0, 0): geocoder returned a default instead of admitting failure.
    2. Out-of-bounds: patient address resolved to somewhere outside your service area
       (moved away, data entry error, or geocoder matched wrong city).

    Args:
        geocoded_records: Records with latitude/longitude populated.
        bounding_box: Dict with min_lat, max_lat, min_lon, max_lon.

    Returns:
        Tuple of (cleaned, excluded) record lists.
    """
    cleaned = []
    excluded = []

    for record in geocoded_records:
        lat = record["latitude"]
        lon = record["longitude"]

        # Check for null island (0, 0) which means geocoding silently failed
        if lat == 0 and lon == 0:
            record["exclusion_reason"] = "null_island"
            excluded.append(record)
            continue

        # Check bounding box
        if (
            lat < bounding_box["min_lat"]
            or lat > bounding_box["max_lat"]
            or lon < bounding_box["min_lon"]
            or lon > bounding_box["max_lon"]
        ):
            record["exclusion_reason"] = "outside_service_area"
            excluded.append(record)
            continue

        cleaned.append(record)

    logger.info(
        "Retained %d points. Excluded %d (null island or out of bounds).",
        len(cleaned),
        len(excluded),
    )
    return cleaned, excluded
```

---

## Step 4: Run the Clustering Algorithm

*The pseudocode calls this `cluster_patients(cleaned_records)`. This is the core analytical step: DBSCAN with Haversine distance on the cleaned coordinates.*

```python
def cluster_patients(cleaned_records: list[dict]) -> tuple[list[dict], int]:
    """
    Run DBSCAN clustering on patient coordinates using Haversine distance.

    DBSCAN finds clusters of arbitrary shape without requiring you to
    pre-specify the number of clusters. It uses two parameters:
    - epsilon: max distance between neighbors (converted to radians for Haversine)
    - min_samples: minimum points to form a dense region

    Points that don't belong to any cluster get label -1 ("noise").
    These are isolated patients in low-density areas.

    Args:
        cleaned_records: Records with valid latitude/longitude.

    Returns:
        Tuple of (records_with_cluster_ids, num_clusters).
        Each record gets a cluster_id field (-1 for noise).
    """
    # Extract coordinates as a numpy array.
    # DBSCAN with haversine metric expects [latitude, longitude] in RADIANS.
    coordinates = np.array(
        [[record["latitude"], record["longitude"]] for record in cleaned_records]
    )
    coordinates_radians = np.radians(coordinates)

    # Convert epsilon from km to radians.
    # Earth's mean radius is approximately 6371 km.
    epsilon_radians = EPSILON_KM / 6371.0

    # Run DBSCAN.
    # metric="haversine" computes great-circle distance (accounts for Earth's curvature).
    # This is critical for geographic data. Euclidean distance would distort
    # at higher latitudes because longitude degrees shrink toward the poles.
    clustering = DBSCAN(
        eps=epsilon_radians,
        min_samples=MIN_SAMPLES,
        metric="haversine",
        algorithm="ball_tree",  # required for haversine metric
    )
    labels = clustering.fit_predict(coordinates_radians)

    # Assign cluster labels back to records.
    for record, label in zip(cleaned_records, labels):
        record["cluster_id"] = int(label)

    # Count results
    unique_labels = set(labels)
    num_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    noise_count = int(np.sum(labels == -1))

    logger.info(
        "Found %d clusters. %d noise points (%.1f%%).",
        num_clusters,
        noise_count,
        100.0 * noise_count / len(labels) if labels.size > 0 else 0,
    )
    return cleaned_records, num_clusters
```

---

## Step 5: Enrich Clusters with Metadata

*The pseudocode calls this `enrich_clusters(clustered_records, num_clusters)`. It computes summary statistics for each cluster to make them actionable.*

```python
def enrich_clusters(
    clustered_records: list[dict], num_clusters: int
) -> dict[int, dict]:
    """
    Compute summary statistics for each cluster.

    A cluster is just a set of coordinates until you attach meaning.
    This step computes: centroid, patient count, demographic breakdown,
    utilization patterns, and geographic spread. These enrichments transform
    "there's a dense area here" into actionable intelligence for strategy teams.

    Args:
        clustered_records: Records with cluster_id assigned.
        num_clusters: Number of clusters found (excluding noise).

    Returns:
        Dict mapping cluster_id to metadata dict.
    """
    from collections import Counter

    cluster_metadata = {}

    for cluster_id in range(num_clusters):
        # Get all patients in this cluster
        members = [r for r in clustered_records if r["cluster_id"] == cluster_id]

        if not members:
            continue

        # Geographic centroid (average lat/lon)
        lats = [m["latitude"] for m in members]
        lons = [m["longitude"] for m in members]
        centroid_lat = sum(lats) / len(lats)
        centroid_lon = sum(lons) / len(lons)

        # Geographic spread: max distance from centroid to any member (in km)
        max_distance_km = 0.0
        for m in members:
            # Haversine distance from centroid
            dlat = np.radians(m["latitude"] - centroid_lat)
            dlon = np.radians(m["longitude"] - centroid_lon)
            a = (
                np.sin(dlat / 2) ** 2
                + np.cos(np.radians(centroid_lat))
                * np.cos(np.radians(m["latitude"]))
                * np.sin(dlon / 2) ** 2
            )
            dist_km = 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
            max_distance_km = max(max_distance_km, dist_km)

        # Demographics
        ages = []
        for m in members:
            try:
                birth_year = int(m["date_of_birth"][:4])
                ages.append(2026 - birth_year)
            except (ValueError, TypeError):
                pass
        avg_age = sum(ages) / len(ages) if ages else 0

        # Payer mix
        payer_counts = Counter(m["primary_payer"] for m in members)
        total = len(members)
        payer_mix = {payer: round(count / total, 2) for payer, count in payer_counts.items()}

        # Utilization
        visits = [m.get("visit_count_12mo", 0) for m in members]
        avg_visits = sum(visits) / len(visits) if visits else 0
        pct_disengaged = sum(1 for v in visits if v == 0) / len(visits) if visits else 0

        # Top ZIP codes
        zip_counts = Counter(m["zip_code"] for m in members)
        top_zips = [z for z, _ in zip_counts.most_common(5)]

        cluster_metadata[cluster_id] = {
            "cluster_id": cluster_id,
            "patient_count": len(members),
            "centroid": {"latitude": round(centroid_lat, 4), "longitude": round(centroid_lon, 4)},
            "radius_km": round(max_distance_km, 2),
            "avg_age": round(avg_age, 1),
            "payer_mix": payer_mix,
            "avg_visits_12mo": round(avg_visits, 1),
            "pct_disengaged": round(pct_disengaged, 2),
            "top_zip_codes": top_zips,
        }

    return cluster_metadata
```

---

## Step 6: Store Results

*The pseudocode calls this `store_results(clustered_records, cluster_metadata)`. It writes per-patient cluster assignments and cluster-level metadata to DynamoDB.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)


def store_results(clustered_records: list[dict], cluster_metadata: dict) -> None:
    """
    Persist cluster assignments and metadata to DynamoDB and S3.

    Two storage targets serve different access patterns:
    - DynamoDB: fast point lookups ("which cluster is patient X in?")
    - S3 (JSON): bulk analytical queries via Athena, archival

    Args:
        clustered_records: Records with cluster_id assigned.
        cluster_metadata: Enriched metadata per cluster.
    """
    patient_table = dynamodb.Table(DYNAMODB_PATIENT_TABLE)
    metadata_table = dynamodb.Table(DYNAMODB_METADATA_TABLE)
    timestamp = datetime.datetime.now(timezone.utc).isoformat()

    # Write per-patient cluster assignments to DynamoDB.
    # Using batch_writer for efficiency (batches of 25 automatically).
    with patient_table.batch_writer() as batch:
        for record in clustered_records:
            batch.put_item(
                Item={
                    "patient_id": record["patient_id"],
                    "cluster_id": record["cluster_id"],
                    # DynamoDB requires Decimal for numbers, not float.
                    "latitude": Decimal(str(round(record["latitude"], 6))),
                    "longitude": Decimal(str(round(record["longitude"], 6))),
                    "computed_at": timestamp,
                }
            )

    # Write cluster metadata to DynamoDB.
    for cluster_id, metadata in cluster_metadata.items():
        # Convert all floats to Decimal for DynamoDB compatibility.
        item = {
            "cluster_id": cluster_id,
            "patient_count": metadata["patient_count"],
            "centroid_lat": Decimal(str(metadata["centroid"]["latitude"])),
            "centroid_lon": Decimal(str(metadata["centroid"]["longitude"])),
            "radius_km": Decimal(str(metadata["radius_km"])),
            "avg_age": Decimal(str(metadata["avg_age"])),
            "avg_visits_12mo": Decimal(str(metadata["avg_visits_12mo"])),
            "pct_disengaged": Decimal(str(metadata["pct_disengaged"])),
            "top_zip_codes": metadata["top_zip_codes"],
            "payer_mix": json.dumps(metadata["payer_mix"]),
            "computed_at": timestamp,
        }
        metadata_table.put_item(Item=item)

    # Also write full results to S3 as JSON for Athena queries.
    date_prefix = datetime.date.today().isoformat()
    s3_client.put_object(
        Bucket=S3_RESULTS_BUCKET,
        Key=f"cluster-results/{date_prefix}/cluster-summaries.json",
        Body=json.dumps(cluster_metadata, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    logger.info(
        "Stored %d patient assignments and %d cluster summaries.",
        len(clustered_records),
        len(cluster_metadata),
    )
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler or SageMaker Processing Job would call.

```python
def run_geographic_clustering_pipeline(use_synthetic: bool = True) -> dict:
    """
    Run the full geographic patient clustering pipeline.

    Args:
        use_synthetic: If True, use synthetic data and skip real API calls.
                       Set to False when running against real data with
                       Location Service configured.

    Returns:
        Dict with cluster metadata and summary statistics.
    """
    # Generate or load patient data
    logger.info("Step 1: Extracting patient addresses")
    if use_synthetic:
        raw_patients = generate_synthetic_patients(num_patients=2000)
    else:
        # In production: query your EHR/enrollment database here
        raise NotImplementedError("Replace with your data source query")

    cleaned_patients = extract_patient_addresses(raw_patients)
    logger.info("  %d records after quality filtering", len(cleaned_patients))

    # Geocode addresses to coordinates
    logger.info("Step 2: Geocoding addresses")
    if use_synthetic:
        geocoded, failed = geocode_addresses_synthetic(cleaned_patients)
    else:
        geocoded, failed = geocode_addresses(cleaned_patients)
    logger.info("  %d geocoded, %d failed", len(geocoded), len(failed))

    # Clean and filter coordinates
    logger.info("Step 3: Cleaning coordinates")
    cleaned, excluded = clean_coordinates(geocoded, BOUNDING_BOX)
    logger.info("  %d retained, %d excluded", len(cleaned), len(excluded))

    # Run DBSCAN clustering
    logger.info("Step 4: Running DBSCAN clustering")
    clustered, num_clusters = cluster_patients(cleaned)
    logger.info("  Found %d clusters", num_clusters)

    # Enrich clusters with metadata
    logger.info("Step 5: Enriching clusters with metadata")
    metadata = enrich_clusters(clustered, num_clusters)
    for cid, meta in metadata.items():
        logger.info(
            "  Cluster %d: %d patients, radius %.1f km, avg age %.0f",
            cid,
            meta["patient_count"],
            meta["radius_km"],
            meta["avg_age"],
        )

    # Store results (skip in synthetic mode to avoid needing real AWS resources)
    if not use_synthetic:
        logger.info("Step 6: Storing results")
        store_results(clustered, metadata)
    else:
        logger.info("Step 6: Skipping storage (synthetic mode)")

    # Summary
    total_clustered = sum(1 for r in clustered if r["cluster_id"] != -1)
    total_noise = sum(1 for r in clustered if r["cluster_id"] == -1)

    summary = {
        "total_patients_processed": len(cleaned),
        "num_clusters": num_clusters,
        "patients_in_clusters": total_clustered,
        "noise_points": total_noise,
        "noise_percentage": round(100.0 * total_noise / len(cleaned), 1) if cleaned else 0,
        "cluster_metadata": metadata,
    }

    return summary


# Run the pipeline with synthetic data
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    results = run_geographic_clustering_pipeline(use_synthetic=True)

    print("\n" + "=" * 60)
    print("GEOGRAPHIC PATIENT CLUSTERING RESULTS")
    print("=" * 60)
    print(f"Total patients processed: {results['total_patients_processed']}")
    print(f"Clusters found: {results['num_clusters']}")
    print(f"Patients in clusters: {results['patients_in_clusters']}")
    print(f"Noise points: {results['noise_points']} ({results['noise_percentage']}%)")
    print("\nCluster Details:")
    print("-" * 60)

    for cid, meta in results["cluster_metadata"].items():
        print(f"\n  Cluster {cid}:")
        print(f"    Patients: {meta['patient_count']}")
        print(f"    Centroid: ({meta['centroid']['latitude']}, {meta['centroid']['longitude']})")
        print(f"    Radius: {meta['radius_km']} km")
        print(f"    Avg Age: {meta['avg_age']}")
        print(f"    Avg Visits (12mo): {meta['avg_visits_12mo']}")
        print(f"    Disengaged: {meta['pct_disengaged'] * 100:.0f}%")
        print(f"    Top ZIPs: {meta['top_zip_codes']}")
        print(f"    Payer Mix: {meta['payer_mix']}")
```

---

## The Gap Between This and Production

This example works. Run it with synthetic data and it will produce meaningful clusters with enriched metadata. But there's a meaningful distance between "works in a script" and "runs monthly against 200,000 real patient records." Here's where that gap lives:

**Error handling.** Right now, if Location Service returns an error or DynamoDB throttles, the pipeline crashes. A production system wraps every external call in try/except blocks with specific handling for throttling (back off and retry), service unavailability (fail gracefully, log, alert), and malformed responses (skip the record, don't crash the batch).

**Retries and backoff.** The boto3 retry config handles basic throttling, but for a 200,000-address geocoding run, you'll hit Location Service rate limits. Production code implements explicit rate limiting (e.g., 50 requests/second with a token bucket) on top of boto3's built-in retries. Without this, you'll get throttled and your retries will compound the problem.

**Input validation.** This code trusts its inputs completely. A production system validates that addresses are non-empty strings, that coordinates are within valid ranges (-90 to 90 latitude, -180 to 180 longitude), and that patient IDs are unique before processing.

**Logging.** The `logger.info()` calls here are minimal. A real system uses structured JSON logging with consistent fields: pipeline_run_id, step_name, record_count, duration_ms, error_count. This is what your on-call engineer queries in CloudWatch Logs Insights when the pipeline fails at 3am.

**IAM least-privilege.** The IAM role for this workload should have exactly: `geo:SearchPlaceIndexForText` scoped to your specific Place Index ARN, `s3:GetObject` and `s3:PutObject` scoped to specific bucket prefixes, `dynamodb:PutItem` and `dynamodb:BatchWriteItem` scoped to the two specific tables. Not `geo:*`. Not `s3:*`.

**VPC configuration.** In production, this runs inside a VPC with private subnets. S3 and DynamoDB get VPC endpoints (gateway type, free). Location Service calls go through a NAT Gateway since there's no VPC endpoint for it as of early 2026. Patient coordinates are PHI and should never traverse the public internet unnecessarily.

**Encryption key management.** This example uses default encryption. Production uses KMS customer-managed keys (CMKs) for the S3 bucket and DynamoDB tables, with key rotation enabled and CloudTrail logging every key usage event.

**DynamoDB data types.** This example already wraps numeric values in `Decimal()` (DynamoDB's requirement), but be aware that any new numeric fields you add must also use `Decimal`. The boto3 DynamoDB resource layer raises a `TypeError` on raw floats in `put_item` calls. The `str()` wrapper before `Decimal()` avoids floating-point representation artifacts (e.g., `Decimal(0.1)` gives you `0.1000000000000000055511151231257827021181583404541015625`, but `Decimal("0.1")` gives you `0.1`).

**Geocoding cost management.** At $0.50 per 1,000 requests, geocoding 200,000 addresses costs ~$100. That's fine for a one-time run, but if you're refreshing weekly, you want incremental geocoding: only geocode new or changed addresses, cache results for stable addresses. A simple "last_geocoded_at" timestamp per patient record enables this.

**Parameter tuning.** The DBSCAN parameters (epsilon=3km, min_samples=100) are reasonable defaults for suburban areas. But your service area might span dense urban cores and sparse rural regions that need different parameters. Consider running HDBSCAN instead (which handles varying density) or running DBSCAN multiple times with different parameters and presenting stakeholders with the sensitivity analysis.

**Temporal refresh.** This pipeline produces a point-in-time snapshot. Patient populations shift: new housing developments, employer relocations, seasonal residents. Build this as a scheduled pipeline (monthly or quarterly) with versioned outputs so you can track how clusters evolve over time.

**Testing.** There are no tests here. A production pipeline has unit tests for the clustering logic (with known synthetic data that should produce specific cluster counts), integration tests against real Location Service calls with known addresses, and regression tests that verify cluster stability across parameter changes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 6.1](chapter06.01-geographic-patient-clustering) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
