# Recipe 3.10 Architecture and Implementation: Epidemic / Outbreak Detection

*Companion to [Recipe 3.10: Epidemic / Outbreak Detection](chapter03.10-epidemic-outbreak-detection). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Kinesis Data Streams for the encounter and lab event backbone.** Clinical encounter feeds, lab feeds, and auxiliary-source feeds flow into Kinesis streams as they're produced. Kinesis handles the volume (a state-level surveillance system might process millions of encounter events per day across all participating facilities), provides ordered delivery for time-series analysis, supports replay for backfill and retraining, and integrates cleanly with the downstream Lambda and analytics components.

**AWS Lambda for ingest, normalization, and syndrome classification.** Each source type (HL7 v2 ADT feeds, HL7 v2 lab feeds, FHIR encounter feeds, NWSS wastewater feeds, eCR feeds, NHSN feeds) has its own Lambda that pulls or receives the source-specific format and writes canonical events. Downstream Lambdas perform geocoding, demographic stratification, and syndrome classification. Lambda's auto-scaling fits the bursty pattern of clinical encounter data well.

**Amazon Comprehend Medical for chief-complaint and triage-note NLP.** Free-text chief complaints carry signal that ICD codes miss in real time. Comprehend Medical extracts conditions, anatomy, medications, and signs/symptoms. Combined with rules-based syndromic classification, it provides higher-fidelity syndrome assignment than structured data alone.

**Amazon SageMaker for syndrome classifier training and hosting.** Custom syndrome classifiers (especially for organization-specific syndrome categories or sentinel-event triggers) train as SageMaker Training Jobs and deploy to SageMaker endpoints. SageMaker Feature Store provides online and offline feature consistency.

**Amazon DynamoDB for the cell state and cluster state stores.** Per-cell state (current count, baseline expected, recent flag history) and per-cluster state (open investigations, suppression status, evidence pointers) live in DynamoDB. Single-digit-millisecond reads on cell lookup; DynamoDB streams trigger downstream re-evaluation when cells update.

**Amazon Timestream for time-series cell counts and baselines.** Per-cell time-series of counts, baselines, and detector scores are time-series data. Timestream's storage and query model fit; magnetic-tier retention covers the multi-year baseline window cost-effectively. 

**Amazon Location Service for geocoding.** Patient address fields (where authority and configuration permit) get geocoded to coordinates and to administrative geographies (census tract, ZIP code tabulation area, county). Combined with custom geography reference data (sewersheds, school districts, hospital catchments) for the multi-resolution geographic stratification.

**Amazon Aurora PostgreSQL with PostGIS for geographic operations.** The geography hierarchy and the geographic operations (point-in-polygon for assigning encounters to administrative areas, polygon-overlap for cluster aggregation, distance computations for cross-jurisdiction routing) fit PostGIS naturally. Aurora provides managed Postgres with HIPAA eligibility.

**Amazon Neptune for the contact and exposure graph (when used).** Contact tracing and exposure-network modeling fit the property-graph model. Less central than for Recipe 3.9, but useful when contact-tracing investigations or exposure-network analyses are part of the surveillance program. 

**Amazon OpenSearch Service for case search, line list, and surveillance analytics.** Surveillance line-list data, encounter-search archives, and the searchable history of clusters and investigations live in OpenSearch. OpenSearch supports the kind of ad-hoc query the surveillance team needs ("show me every fever-respiratory ED visit in this ZIP in the last 14 days," "show me every confirmed Salmonella case in the state for the last 90 days, sorted by serotype").

**AWS Batch and Amazon SageMaker Processing for SaTScan and other compute-heavy aberration detection.** SaTScan is a compiled tool that can run as a containerized batch job on AWS Batch. SageMaker Processing handles the regression-based detectors and the time-series modeling at scale. Both fit the daily-cadence "run all the detectors against today's data" pattern.

**AWS Step Functions for orchestration.** The daily surveillance run, the cluster-building pipeline, and the periodic retraining are multi-step workflows. Step Functions handles orchestration with retry and error handling.

**Amazon Bedrock for cluster narrative generation.** The cluster builder hands the structured evidence to a Bedrock-hosted LLM that produces the investigator-facing narrative ("A spatiotemporal cluster of 14 fever-respiratory ED visits in census tracts 36055-001100 through 36055-001400 over the past 7 days. Pediatric (under 12) cases account for 11 of 14. Geographic centroid is within 0.4 miles of three elementary schools. No lab-confirmed pathogen in the cluster yet; respiratory panels pending on 4 cases. Compared to the historical baseline for these tracts and this week, the observed count exceeds the 99th percentile."). Decision support, not decision-making. 

**Amazon SageMaker Model Monitor.** Continuously monitors data drift, prediction drift, and (with labels) model quality. Critical for catching baseline drift caused by EHR upgrades, behavioral shifts, demographic changes, or COVID-era reset effects.

**Amazon EventBridge for routing.** Detector outputs publish to EventBridge with cluster context and case-class metadata. Subscribers include the cluster builder, the eCR/NEDSS connector, the audit logger, and the metrics collector.

**Amazon API Gateway and AWS AppSync for the surveillance UI.** The surveillance team's case queue UI consumes data through AppSync (GraphQL flexibility for cluster-detail views with related geographic, temporal, and demographic data) or API Gateway (simpler integrations). When the organization uses ESSENCE or another surveillance product, integration is API-driven.

**AWS Glue and Amazon Athena for the data lake.** Historical encounters, baselines, cluster outcomes, and surveillance archives live in S3 partitioned by date and source. Glue catalogs the schema; Athena provides SQL access for ad-hoc analysis and retraining feature extraction. Athena geospatial functions support some geographic analyses without lifting data into Aurora/PostGIS.

**Amazon QuickSight for surveillance dashboards.** Public-facing dashboards (with appropriate suppression rules), internal surveillance team dashboards (full detail), and leadership briefing dashboards (high-level trends and indicators). Geospatial visualizations through QuickSight or external tools (Mapbox, Esri) integrated through QuickSight embedding.

**Amazon S3 for the data lake and surveillance archive.** Partitioned by date and event source, encrypted with customer-managed KMS keys. Used by SageMaker for training, Athena for ad-hoc analysis, and as the long-term archive for compliance and historical-baseline retention.

**AWS IAM Identity Center.** Workforce single sign-on for the surveillance UI, integrated with the public health agency's identity provider. Per-role permissions: surveillance epidemiologists (read access to clusters, write access to outcomes), surveillance leadership (read access plus reporting), data-science team (training-data access with appropriate de-identification), operations team (pipeline monitoring without case-data access). Cross-organizational users (state health department staff accessing local-jurisdiction data, CDC staff accessing state data) get access through federation with appropriate scoping.

**Amazon CloudWatch and AWS X-Ray.** Pipeline health, ingest latency, end-to-end traces. Latency budgets matter: time from "patient arrives at ED" to "encounter scored in surveillance pipeline" is part of the operational metric. Most surveillance programs target same-day or next-day inclusion of new encounters.

**AWS CloudTrail.** Audit logging on every PHI-bearing store and every API call against the case management system.

**AWS KMS.** Customer-managed keys on every PHI-bearing store: Kinesis, DynamoDB, Aurora, Neptune, Timestream, S3, OpenSearch, SageMaker volumes and Feature Store. Public health authority data-handling rules often require additional controls beyond standard HIPAA.

**AWS Secrets Manager.** Source-system credentials (HL7 feed authentication, FHIR API tokens, NWSS access keys, eCR endpoint credentials, NHSN credentials), and external-system integration credentials.

### Architecture Diagram

```mermaid
flowchart TB
    A[ED encounter feeds<br/>HL7 v2 ADT,<br/>FHIR Encounter] --> B[AWS Lambda<br/>encounter-ingest]
    C[Lab feeds<br/>HL7 v2 ORU,<br/>state PHL] --> D[AWS Lambda<br/>lab-ingest]
    E[Wastewater feeds<br/>NWSS, direct] --> F[AWS Lambda<br/>wastewater-ingest]
    G[Pharmacy /<br/>OTC sales feeds] --> H[AWS Lambda<br/>pharmacy-ingest]
    I[School<br/>absenteeism] --> J[AWS Lambda<br/>absenteeism-ingest]
    K[eCR / NEDSS<br/>case feeds] --> L[AWS Lambda<br/>case-ingest]

    B --> M[Amazon Kinesis<br/>surveillance-events]
    D --> M
    F --> M
    H --> M
    J --> M
    L --> M

    M --> N[AWS Lambda<br/>event-normalizer]
    N --> O[AWS Lambda<br/>geocoding<br/>+ Amazon Location]
    O --> P[AWS Lambda<br/>syndrome-classifier]
    P --> Q[Amazon Comprehend<br/>Medical]
    P --> R[SageMaker Endpoint<br/>syndrome-NLP-model]

    P --> S[(Amazon DynamoDB<br/>cell-state)]
    P --> T[(Amazon Timestream<br/>cell-time-series)]
    P --> U[(Amazon S3<br/>raw-events lake)]
    P --> V[(Amazon OpenSearch<br/>line-list-search)]
    P --> W[(Amazon Aurora<br/>PostGIS geography)]

    T --> X[AWS Step Functions<br/>daily-surveillance-run]
    X --> Y[AWS Lambda<br/>baseline-computer]
    X --> Z[AWS Batch<br/>SaTScan-runner]
    X --> AA[SageMaker Processing<br/>regression-detectors]
    X --> AB[AWS Lambda<br/>control-chart-detectors]
    X --> AC[AWS Lambda<br/>multi-source-fusion]

    Y --> AD[(Amazon S3<br/>baseline-store)]
    Z --> AE[AWS Lambda<br/>cluster-aggregator]
    AA --> AE
    AB --> AE
    AC --> AE

    AE --> AF[AWS Lambda<br/>cluster-builder]
    AF --> AG[Amazon Bedrock<br/>narrative-LLM]
    AF --> AH[(Amazon DynamoDB<br/>cluster-state)]
    AF --> AI[Amazon EventBridge<br/>cluster-bus]

    AI --> AJ[Surveillance Team<br/>UI<br/>AppSync/API Gateway]
    AI --> AK[eCR / NEDSS<br/>connector]
    AI --> AL[(OpenSearch<br/>cluster-index)]
    AI --> AM[NSSP / NORS /<br/>NHSN connector]

    AN[Investigator<br/>adjudication] --> AO[AWS Lambda<br/>outcome-capture]
    AO --> AH
    AO --> AL
    AO --> AP[(Amazon S3<br/>training-labels)]

    AP --> AQ[SageMaker Training<br/>+ Model Monitor]
    AQ --> R

    AL --> AR[Amazon Athena]
    U --> AR
    AR --> AS[Amazon QuickSight<br/>surveillance dashboards]

    AT[CloudTrail<br/>data events] -.-> S
    AT -.-> T
    AT -.-> U
    AT -.-> V
    AT -.-> W
    AT -.-> AH
    AT -.-> AL
    AT -.-> AP

    style S fill:#9ff,stroke:#333
    style T fill:#9ff,stroke:#333
    style W fill:#9ff,stroke:#333
    style AH fill:#f9f,stroke:#333
    style AL fill:#f9f,stroke:#333
    style R fill:#ffc,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Kinesis Data Streams, AWS Lambda, Amazon DynamoDB, Amazon Aurora PostgreSQL (PostGIS), Amazon Neptune (optional), Amazon Timestream, Amazon OpenSearch Service, Amazon S3, Amazon SageMaker (Training, Hosting, Feature Store, Processing, Model Monitor, Model Registry), Amazon Comprehend Medical, Amazon Bedrock, Amazon Location Service, Amazon EventBridge, AWS Step Functions, AWS Batch, AWS AppSync, Amazon API Gateway, AWS Glue, Amazon Athena, Amazon QuickSight, AWS IAM Identity Center, AWS Secrets Manager, AWS KMS, AWS CloudTrail, Amazon CloudWatch, AWS X-Ray. |
| **IAM Permissions** | Least-privilege per role. Ingest Lambdas write to the event stream and read from clinical-source endpoints. Detection Lambdas read from cell state and write scores. Cluster builder reads scores and assembles clusters. Surveillance epidemiologists read cluster data and write outcomes only. Data science roles can train and deploy with appropriate de-identification of training data. No `*` permissions; every action scoped to specific resources. |
| **BAA and Public Health Data Use Agreements** | Signed AWS BAA. All services configured per BAA requirements. Each clinical data source must have its own data-sharing arrangement (BAA, Data Use Agreement, public health authority memorandum). For state-level surveillance, the legal authority typically derives from state public health statutes; for institutional surveillance, from the institution's own privacy authority. See the [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/). |
| **Encryption** | Customer-managed KMS keys on every PHI-bearing store: Kinesis, DynamoDB, Aurora, Neptune, Timestream, S3, OpenSearch, SageMaker (volumes, Feature Store, model artifacts). TLS 1.2 or higher in transit. Encounter payloads include PHI (patient identifier, demographics, address) and clinical data; both categories must be protected. Suppressed-cell rules apply at the publication layer for any data products distributed beyond the surveillance team. |
| **VPC** | Production deployment in a VPC with VPC endpoints for S3, DynamoDB, KMS, Comprehend Medical, Bedrock, Aurora, Neptune, SageMaker runtime, EventBridge, and Step Functions. Lambdas that touch PHI run in the VPC. Source-system integrations (HL7 feeds, FHIR endpoints) typically use site-to-site VPN or Direct Connect, depending on the source's deployment topology. |
| **CloudTrail and Data Events** | Enabled with data events on every PHI-bearing store, on the case management indexes, and on the model endpoints. Log retention per organizational policy and applicable regulations (some surveillance programs require multi-year retention for outbreak investigation records and longer for nationally notifiable conditions). |
| **Public Health Authority Coordination** | The surveillance program must operate under an explicit legal authority. State public health statutes, institutional privacy policies, and intergovernmental agreements should all be in place before the system goes live. Coordination with the state public health department, local health departments, and (for institutional programs) hospital privacy officers must be established. |
| **Clinical Data Source Integrations** | HL7 v2 feeds from EDs, urgent care facilities, and hospital ADT systems are the primary source; coordination with each source institution and (where applicable) state-level data aggregators is required. FHIR-based feeds are emerging but coverage varies. eCR integration follows the eCR Now framework and the AIMS platform; rollout is increasing but not universal. Plan for parallel multi-quarter integration projects per source class. |
| **Geographic Reference Data** | Census tract boundaries (TIGER/Line shapefiles), ZIP code tabulation areas, county boundaries, school district boundaries, sewershed boundaries (where wastewater surveillance is in scope), hospital service areas. Refresh annually; some boundaries change with the decennial census and with administrative changes. |
| **Sample Data** | Synthetic data generators exist for syndromic surveillance (the BARDA-funded synthetic generators, academic research datasets) but produce data that's structurally simpler than real EHR feeds. Pseudonymization for development is essential; the relationship structure (which patients live in which tracts, which providers see which patients) must be preserved while identifiers are replaced. The CDC NSSP provides aggregate data products (with appropriate access controls) that can support algorithm development without exposing PHI. |
| **Cost Estimate** | For a state-level surveillance system covering a population of 5-10 million across 100-500 facilities: Kinesis ingest: ~$500-1,500/month. Lambda for ingest, normalization, classification, detection: ~$2,000-5,000/month. DynamoDB cell-state and cluster-state: ~$500-1,500/month. Aurora PostGIS: ~$700-2,500/month. Timestream cell time-series: ~$300-800/month. OpenSearch line-list and cluster index: ~$2,000-6,000/month (scales with retention; many programs retain multiple years online). AWS Batch for SaTScan and other heavy detectors: ~$300-1,000/month. SageMaker endpoints (modest instance class for daily-cadence scoring): ~$500-1,500/month. SageMaker training and Model Monitor: ~$200-500/month. Comprehend Medical for chief-complaint NLP: ~$500-2,000/month (scales with encounter volume). Bedrock for cluster narratives: ~$200-700/month. S3, supporting services: ~$300-700/month. Total infrastructure: typically $8,000-22,000/month for a state-level deployment. Public health staffing (epidemiologists, data analysts, communications) is the dominant program cost; one experienced epidemiologist's loaded cost can equal several months of infrastructure. The infrastructure pays for itself by detecting one or two outbreaks earlier; the cost of a delayed outbreak response (extended community spread, healthcare system strain, mortality) substantially exceeds typical surveillance infrastructure costs.  |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Kinesis Data Streams** | Canonical surveillance-event stream |
| **AWS Lambda (encounter-ingest)** | ED and urgent-care encounter ingestion (HL7 v2, FHIR) |
| **AWS Lambda (lab-ingest)** | Laboratory result ingestion from hospital labs and state public health labs |
| **AWS Lambda (wastewater-ingest)** | NWSS and direct-source wastewater pathogen-concentration data |
| **AWS Lambda (pharmacy-ingest)** | Pharmacy and OTC product-sales data (where available and authorized) |
| **AWS Lambda (absenteeism-ingest)** | School absenteeism and ILI clinic-visit data |
| **AWS Lambda (case-ingest)** | eCR and NEDSS notifiable-condition case ingestion |
| **AWS Lambda (event-normalizer)** | Canonical event format, identifier resolution, deduplication |
| **AWS Lambda (geocoding)** | Address-to-tract/ZIP/county/sewershed assignment using Amazon Location and reference geography |
| **AWS Lambda (syndrome-classifier)** | Rules-based plus ML syndrome classification |
| **Amazon Comprehend Medical** | Free-text chief-complaint and triage-note entity extraction |
| **AWS Lambda (baseline-computer)** | Per-cell baseline expected counts with seasonality and trend |
| **AWS Lambda (control-chart-detectors)** | CUSUM, EWMA, Shewhart per-cell aberration detection |
| **AWS Batch (SaTScan-runner)** | Spatial and spatiotemporal scan-statistic clustering |
| **SageMaker Processing (regression-detectors)** | Farrington Flexible and negative-binomial GLM-based detection |
| **AWS Lambda (multi-source-fusion)** | Combine clinical, wastewater, pharmacy, and auxiliary signals |
| **AWS Lambda (cluster-aggregator)** | Group flagged cells into spatiotemporal clusters |
| **AWS Lambda (cluster-builder)** | Assemble cluster evidence; line list, geographic visualization, narrative LLM |
| **AWS Lambda (outcome-capture)** | Record investigator adjudications and feed the label store |
| **Amazon DynamoDB (cell-state)** | Per-cell current state, baseline summary, recent flag history |
| **Amazon DynamoDB (cluster-state)** | Open and recently-closed cluster state, suppression rules |
| **Amazon Aurora PostgreSQL (PostGIS)** | Geographic reference data and geographic operations |
| **Amazon Neptune** | Optional: contact and exposure graph for contact-tracing-driven analyses |
| **Amazon Timestream** | Time-series of per-cell counts, baselines, and detector scores |
| **Amazon OpenSearch Service** | Searchable line list and cluster archive; surveillance ad-hoc queries |
| **Amazon S3** | Raw event lake, baseline store, training data, label store |
| **Amazon SageMaker Endpoint (syndrome-NLP-model)** | Custom syndrome classification beyond Comprehend Medical |
| **Amazon SageMaker Training and Model Registry** | Periodic retraining and versioning of classifiers and detection models |
| **Amazon SageMaker Feature Store** | Online and offline feature consistency for training and scoring |
| **Amazon SageMaker Model Monitor** | Data drift, prediction drift, and quality drift monitoring |
| **Amazon Bedrock** | Investigator-facing cluster-narrative generation |
| **Amazon Location Service** | Geocoding and reverse-geocoding for encounter addresses |
| **Amazon EventBridge** | Routes scoring and cluster events to subscribers (case queue, eCR connector, archive) |
| **AWS AppSync / API Gateway** | Surveillance team UI back end |
| **AWS Step Functions** | Daily surveillance run orchestration |
| **AWS Glue + Amazon Athena** | Data lake catalog and SQL-over-S3 for ad-hoc analysis |
| **Amazon QuickSight** | Surveillance dashboards (internal full-detail, leadership briefing, public with suppression) |
| **AWS IAM Identity Center** | Surveillance team SSO and federation with public health agency identity |
| **AWS Secrets Manager** | Source-system and downstream-integration credentials |
| **AWS KMS** | Customer-managed keys for every PHI-bearing store |
| **AWS CloudTrail** | Audit logging on every store and every API operation |
| **Amazon CloudWatch + AWS X-Ray** | Pipeline health, ingest latency, end-to-end traces |

---

### Pseudocode Walkthrough

The pipeline runs continuously for ingest and on a daily cadence for the heavyweight detectors. The pseudocode below walks through the principal stages: encounter ingest and syndrome classification, baseline computation, the detector bank, multi-source fusion, cluster building, and outcome capture. Each stage is independently deployable; the operational pattern is to stand each up, validate it against historical data, and then connect them.

**Step 1: Ingest a clinical encounter and produce a canonical event.** Source feeds arrive in vendor-specific formats (HL7 v2 ADT and ORU, FHIR Encounter and Observation, eCR documents). The ingester translates each into a canonical surveillance event with consistent fields and identifier semantics.

```
FUNCTION ingest_encounter(raw_message, source_id):
    // Parse the source-specific format. Each source class has its own parser.
    parsed = parse_by_source(raw_message, source_id)
    // parsed includes: encounter_id, patient_identifier, encounter_type
    //                  (ED, urgent care, inpatient), arrival_at, discharge_at,
    //                  facility_id, chief_complaint_text, triage_note_text,
    //                  diagnosis_codes (final and admit), demographics,
    //                  patient_address (residence), encounter_address (facility)

    // De-identify aggressively at ingest. Surveillance does not need direct
    // identifiers in the analytic store; PHI lives in a separate, tightly
    // controlled case-detail store accessed only by authorized epidemiologists.
    canonical = {
        event_id:            generate_event_id(),
        source_id:           source_id,
        source_event_id:     parsed.encounter_id,
        observed_at:         parsed.arrival_at,
        ingested_at:         NOW(),
        encounter_type:      parsed.encounter_type,
        facility_id:         parsed.facility_id,
        // Patient identifier is replaced with a pseudonymized surveillance ID.
        // The mapping is stored in a separate, access-controlled service.
        surveillance_pid:    pseudonymize(parsed.patient_identifier),
        chief_complaint:     parsed.chief_complaint_text,
        triage_note:         parsed.triage_note_text,
        diagnoses_admit:     parsed.diagnosis_codes.admit,
        diagnoses_final:     parsed.diagnosis_codes.final,
        age_years:           parsed.demographics.age,
        age_group:           bucket_age(parsed.demographics.age),
        sex:                  parsed.demographics.sex,
        race_ethnicity:      parsed.demographics.race_ethnicity,
        residence_address:   parsed.patient_address,    // for geocoding only
        residence_zip:       parsed.patient_address.zip
    }

    // Append to the canonical surveillance-event stream.
    Kinesis.PutRecord(
        stream_name = "surveillance-events",
        partition_key = canonical.surveillance_pid,
        data        = canonical
    )

    // Persist the raw event in the lake for replay and audit.
    S3.PutObject(
        bucket = "surveillance-raw-events",
        key    = f"source={source_id}/year={year(NOW())}/month={month(NOW())}/{canonical.event_id}.json",
        body   = parsed
    )

    return canonical.event_id
```

**Step 2: Geocode the encounter and assign it to multi-resolution geographies.** Patient residence is geocoded once (cached on subsequent visits) and assigned to the relevant administrative geographies. Multi-resolution geocoding lets the detectors run at different scales in parallel.

```
FUNCTION geocode_and_stratify(canonical_event):
    // Geocode the residence address. Cache the result keyed on the
    // address hash so repeat encounters from the same patient don't
    // re-geocode unnecessarily.
    address_hash = hash(canonical_event.residence_address)
    cached = DynamoDB.GetItem(
        table = "address-geocode-cache",
        key   = { address_hash: address_hash }
    )
    IF cached:
        coords = cached.coords
        admin_geographies = cached.admin_geographies
    ELSE:
        coords = AmazonLocation.SearchPlaceIndexForText(
            text = format_address(canonical_event.residence_address)
        )
        // Spatial joins against geographic reference data in PostGIS.
        admin_geographies = Aurora.PostGIS.SpatialJoin(
            point = coords,
            layers = ["census_tract", "zcta", "county", "school_district",
                       "sewershed", "hospital_service_area"]
        )
        DynamoDB.PutItem(
            table = "address-geocode-cache",
            item  = {
                address_hash:       address_hash,
                coords:             coords,
                admin_geographies:  admin_geographies,
                geocoded_at:        NOW()
            }
        )

    // Attach geographies to the event.
    canonical_event.coords            = coords
    canonical_event.census_tract      = admin_geographies.census_tract
    canonical_event.zcta              = admin_geographies.zcta
    canonical_event.county            = admin_geographies.county
    canonical_event.school_district   = admin_geographies.school_district
    canonical_event.sewershed         = admin_geographies.sewershed
    canonical_event.hospital_service_area = admin_geographies.hospital_service_area

    return canonical_event
```

**Step 3: Classify the encounter into syndromic categories.** Structured-data rules plus NLP on the chief complaint and triage note produce a multi-label syndromic classification. NSSP's syndromic categories are the standard target taxonomy; organization-specific categories can be added.

```
FUNCTION classify_syndrome(canonical_event):
    syndromes = set()

    // Structured-data rules: ICD-10 patterns map to syndromic categories.
    FOR each code in canonical_event.diagnoses_admit + canonical_event.diagnoses_final:
        FOR each rule in ICD_TO_SYNDROME_RULES:
            IF code matches rule.pattern:
                syndromes.add(rule.syndrome)

    // NLP on the chief complaint and triage notes.
    free_text = (canonical_event.chief_complaint or "") + " " + (canonical_event.triage_note or "")
    IF free_text.strip():
        // Comprehend Medical extracts conditions, signs, and symptoms.
        cm_response = ComprehendMedical.DetectEntitiesV2(text = free_text)

        // Map detected entities to syndromic categories.
        FOR each entity in cm_response.entities:
            IF entity.category in ["MEDICAL_CONDITION", "SIGN_SYMPTOM"]:
                FOR each rule in ENTITY_TO_SYNDROME_RULES:
                    IF entity.text.lower() matches rule.pattern OR entity.code in rule.codes:
                        syndromes.add(rule.syndrome)

        // Custom syndrome classifier handles patterns the rules miss.
        // Trained on labeled chief complaints; fine-tuned periodically on
        // adjudicated cases.
        custom_predictions = SageMaker.Endpoint.Invoke(
            endpoint_name = "syndrome-classifier-v3",
            payload       = { text: free_text, age_group: canonical_event.age_group }
        )
        FOR each prediction in custom_predictions:
            IF prediction.confidence > SYNDROME_CONFIDENCE_THRESHOLD:
                syndromes.add(prediction.syndrome)

    // Lab-confirmed pathogens promote the encounter to specific
    // pathogen-level syndrome categories. (Lab events arrive on a separate
    // stream; this is the encounter-side hook.)
    lab_results = lookup_recent_lab_results(canonical_event.surveillance_pid,
                                             window_days = 14)
    FOR each lab in lab_results:
        IF lab.result_positive:
            FOR each rule in PATHOGEN_TO_SYNDROME_RULES:
                IF lab.pathogen in rule.pathogens:
                    syndromes.add(rule.syndrome)

    canonical_event.syndromes = list(syndromes)
    return canonical_event
```

**Step 4: Update per-cell counters across the geography x demographic x syndrome x time grid.** Each event increments the relevant cell counters, which are the substrate for aberration detection.

```
FUNCTION update_cell_counters(canonical_event):
    // Build the cell key set: every combination of geography x stratification
    // x syndrome the event participates in. A single event might update
    // dozens of cells.
    cell_keys = []
    FOR each geo in [canonical_event.census_tract, canonical_event.zcta,
                      canonical_event.county, canonical_event.school_district,
                      canonical_event.sewershed]:
        IF geo is null: continue
        FOR each strat in stratifications_for(canonical_event):
            // Stratifications include: all-ages, age-group, sex,
            // race-ethnicity (where reliably collected), insurance category.
            FOR each syndrome in canonical_event.syndromes:
                FOR each window in [1d, 7d, 14d, 28d]:
                    cell_keys.append({
                        geo:       geo,
                        strat:     strat,
                        syndrome:  syndrome,
                        window:    window
                    })

    FOR each cell_key in cell_keys:
        // Atomic increment in DynamoDB; the cell-state table tracks
        // current rolling-window count, last update, and recent flag history.
        DynamoDB.UpdateItem(
            table = "cell-state",
            key   = cell_key,
            update_expression = "ADD count :one SET last_event_at = :now",
            attribute_values  = { ":one": 1, ":now": NOW() }
        )

        // Append to the time-series store for baseline computation.
        Timestream.WriteRecords(
            database = "surveillance",
            table    = "cell-time-series",
            records  = [{
                dimensions: cell_key,
                measure_name:  "count_increment",
                measure_value: 1,
                time:          canonical_event.observed_at
            }]
        )

    return cell_keys
```

**Step 5: Compute baseline expected counts per cell.** Daily (or weekly) job that recomputes per-cell baselines using historical data with seasonal, trend, and day-of-week terms. Hierarchical pooling stabilizes small cells.

```
FUNCTION compute_baselines(reference_date):
    // Load multi-year history for every cell from Timestream.
    cells = enumerate_active_cells()

    FOR each cell in cells:
        history = Timestream.Query(f"""
            SELECT bin(time, 1d) AS day, sum(measure_value) AS count
            FROM surveillance.cell_time_series
            WHERE geo = '{cell.geo}'
              AND strat = '{cell.strat}'
              AND syndrome = '{cell.syndrome}'
              AND window = '1d'
              AND time BETWEEN '{reference_date - 5_years}' AND '{reference_date}'
            GROUP BY bin(time, 1d)
        """)

        // Negative binomial regression with seasonal harmonics (annual and
        // weekly), trend term, and day-of-week effects. Hierarchical pooling
        // borrows strength from the parent geography for small cells.
        IF len(history) < MIN_HISTORY_DAYS or sum(history.count) < MIN_HISTORY_COUNT:
            // Use parent geography's model with cell-specific offset.
            parent_model = get_parent_baseline_model(cell)
            cell_baseline = downscale_parent(parent_model, cell)
            baseline_source = "parent_pooled"
        ELSE:
            cell_baseline = fit_negative_binomial_glm(
                counts        = history.count,
                dates         = history.day,
                seasonal_terms = ["annual_harmonic_1", "annual_harmonic_2",
                                   "weekly_harmonic"],
                trend_term     = "linear",
                dow_term       = "categorical",
                exclude_dates  = known_outbreak_dates(cell)   // avoid contamination
            )
            baseline_source = "cell_specific"

        // Per-day expected count, plus 95th and 99th percentile prediction
        // intervals, are persisted for the next reference_date window.
        S3.PutObject(
            bucket = "surveillance-baseline-store",
            key    = f"baseline/{cell.geo}/{cell.strat}/{cell.syndrome}/{reference_date}.json",
            body   = {
                cell:               cell,
                expected_per_day:   cell_baseline.predict_next_window(),
                upper_95:            cell_baseline.upper_95(),
                upper_99:            cell_baseline.upper_99(),
                model_summary:       cell_baseline.summary,
                source:              baseline_source,
                computed_at:         NOW()
            }
        )

        // Update DynamoDB cell-state with the latest expected counts.
        DynamoDB.UpdateItem(
            table = "cell-state",
            key   = cell,
            update_expression = "SET expected = :e, upper_95 = :u95, upper_99 = :u99",
            attribute_values  = {
                ":e":   cell_baseline.predict_today(),
                ":u95": cell_baseline.upper_95_today(),
                ":u99": cell_baseline.upper_99_today()
            }
        )
```

**Step 6: Run the detector bank.** Each detector runs against the cell time series and produces per-cell or per-cluster scores. Multiple detectors run in parallel; their outputs are combined later.

```
FUNCTION run_detector_bank(reference_date):
    detector_results = []

    // Detector A: control charts (CUSUM, EWMA) per cell.
    cells = enumerate_active_cells()
    FOR each cell in cells:
        recent_counts = Timestream.Query_RecentCounts(cell, window_days = 60)
        baseline      = load_baseline(cell, reference_date)

        cusum_score = compute_cusum(
            observed = recent_counts,
            expected = baseline.expected_per_day,
            sigma    = baseline.std_per_day,
            k        = CUSUM_REFERENCE_K,
            h        = CUSUM_DECISION_H
        )
        ewma_score = compute_ewma(
            observed   = recent_counts,
            expected   = baseline.expected_per_day,
            sigma      = baseline.std_per_day,
            lambda_val = EWMA_LAMBDA,
            limit      = EWMA_CONTROL_LIMIT
        )
        detector_results.append({
            detector:   "control_chart",
            cell:       cell,
            cusum:      cusum_score,
            ewma:       ewma_score,
            flagged:    (cusum_score.signal or ewma_score.signal),
            reference_date: reference_date
        })

    // Detector B: Farrington Flexible regression-based aberration.
    FOR each cell in cells:
        farrington_result = SageMaker.Processing.Run(
            container       = "farrington-flexible-runner",
            inputs          = { cell: cell, reference_date: reference_date,
                                history_days: 5 * 365 }
        )
        detector_results.append({
            detector:   "farrington_flexible",
            cell:       cell,
            score:      farrington_result.exceedance_score,
            flagged:    farrington_result.exceedance > 0,
            reference_date: reference_date
        })

    // Detector C: spatial scan statistic across cells.
    FOR each scan_geography in ["county_zcta", "state_tract"]:
        satscan_result = AWS.Batch.SubmitJob(
            job_definition = "satscan-spatial-runner",
            parameters     = {
                geography: scan_geography,
                reference_date: reference_date,
                method: "poisson",
                max_window_pct: 25
            }
        )
        FOR each cluster in satscan_result.significant_clusters:
            detector_results.append({
                detector:   "satscan_spatial",
                cluster:    cluster,
                p_value:    cluster.p_value,
                rr:         cluster.relative_risk,
                flagged:    cluster.p_value < SCAN_PVALUE_THRESHOLD,
                reference_date: reference_date
            })

    // Detector D: spatiotemporal scan (space-time permutation).
    FOR each scan_geography in ["county_zcta", "state_tract"]:
        st_result = AWS.Batch.SubmitJob(
            job_definition = "satscan-spacetime-runner",
            parameters     = {
                geography: scan_geography,
                reference_date: reference_date,
                method: "space_time_permutation",
                max_temporal_window_days: 14
            }
        )
        FOR each cluster in st_result.significant_clusters:
            detector_results.append({
                detector:   "satscan_spacetime",
                cluster:    cluster,
                p_value:    cluster.p_value,
                rr:         cluster.relative_risk,
                flagged:    cluster.p_value < SCAN_PVALUE_THRESHOLD,
                reference_date: reference_date
            })

    // Detector E: cross-syndrome correlation.
    FOR each geo in active_geographies():
        corr_result = compute_cross_syndrome_correlation(
            geo            = geo,
            reference_date = reference_date,
            syndrome_pairs = SURVEILLANCE_SYNDROME_PAIRS
        )
        IF corr_result.has_concurrent_signal:
            detector_results.append({
                detector:    "cross_syndrome",
                geo:         geo,
                pair:        corr_result.pair,
                co_score:    corr_result.score,
                flagged:     corr_result.score > CROSS_SYNDROME_THRESHOLD,
                reference_date: reference_date
            })

    // Persist detector outputs.
    FOR each result in detector_results:
        EventBridge.PutEvent(
            bus = "surveillance-events",
            source = "detector-bank",
            detail_type = "DetectorResult",
            detail = result
        )
        OpenSearch.Index("detector-results", result)

    return detector_results
```

**Step 7: Run auxiliary-source detectors and fuse signals.** Wastewater, pharmacy, school absenteeism, and other auxiliary sources have their own detectors; the fusion layer combines signals from multiple sources into per-cluster composite scores.

```
FUNCTION run_auxiliary_and_fuse(reference_date, clinical_results):
    auxiliary_results = []

    // Wastewater anomaly detection per sewershed and pathogen.
    FOR each sewershed in NWSS_active_sewersheds():
        FOR each pathogen in NWSS_pathogens():
            ww_history = load_ww_concentration_history(sewershed, pathogen)
            ww_baseline = fit_ww_baseline(ww_history)
            current     = current_ww_concentration(sewershed, pathogen, reference_date)

            ww_score = standardized_anomaly(current, ww_baseline)
            IF ww_score > WW_ANOMALY_THRESHOLD:
                auxiliary_results.append({
                    detector:       "wastewater",
                    sewershed:       sewershed,
                    pathogen:        pathogen,
                    anomaly_score:   ww_score,
                    flagged:         true,
                    reference_date:  reference_date
                })

    // Pharmacy spike detection (where data is available).
    FOR each (geo, drug_class) in pharmacy_active_combos():
        rx_history  = load_rx_history(geo, drug_class)
        rx_baseline = fit_rx_baseline(rx_history)
        current     = current_rx_volume(geo, drug_class, reference_date)
        rx_score = (current - rx_baseline.expected) / rx_baseline.std
        IF rx_score > RX_SPIKE_THRESHOLD:
            auxiliary_results.append({
                detector:    "pharmacy_spike",
                geo:         geo,
                drug_class:  drug_class,
                spike_score: rx_score,
                flagged:     true,
                reference_date: reference_date
            })

    // School absenteeism (where data is shared).
    FOR each district in absenteeism_active_districts():
        abs_history  = load_absenteeism_history(district)
        abs_baseline = fit_absenteeism_baseline(abs_history)
        current      = current_absenteeism_rate(district, reference_date)
        abs_score    = (current - abs_baseline.expected) / abs_baseline.std
        IF abs_score > ABSENTEEISM_THRESHOLD:
            auxiliary_results.append({
                detector:        "school_absenteeism",
                district:        district,
                absenteeism_score: abs_score,
                flagged:         true,
                reference_date:  reference_date
            })

    // Fusion: combine clinical, auxiliary signals at the geography x window
    // level. Concordant signals across sources elevate the composite score.
    fused_signals = []
    FOR each candidate_geo_window in candidate_geo_windows(clinical_results, auxiliary_results):
        clinical_signal   = max_score_for(clinical_results, candidate_geo_window)
        wastewater_signal = max_score_for(auxiliary_results, candidate_geo_window, "wastewater")
        pharmacy_signal   = max_score_for(auxiliary_results, candidate_geo_window, "pharmacy_spike")
        absenteeism_signal = max_score_for(auxiliary_results, candidate_geo_window, "school_absenteeism")

        // Decision-level fusion: weighted combination with concordance bonus.
        composite = (
            FUSION_WEIGHTS.clinical    * clinical_signal
          + FUSION_WEIGHTS.wastewater  * wastewater_signal
          + FUSION_WEIGHTS.pharmacy    * pharmacy_signal
          + FUSION_WEIGHTS.absenteeism * absenteeism_signal
        )
        concordance_bonus = count_concordant_sources(
            clinical_signal, wastewater_signal,
            pharmacy_signal, absenteeism_signal,
            threshold = CONCORDANCE_SIGNAL_THRESHOLD
        ) * CONCORDANCE_BONUS_PER_SOURCE
        composite_with_concordance = composite + concordance_bonus

        // Calibrate per cohort.
        calibrated = apply_fusion_calibration(
            score    = composite_with_concordance,
            cohort   = (candidate_geo_window.geo_class,
                        candidate_geo_window.syndrome_class),
            calibration = FUSION_CALIBRATION
        )

        fused_signals.append({
            geo_window:           candidate_geo_window,
            clinical_signal:      clinical_signal,
            wastewater_signal:    wastewater_signal,
            pharmacy_signal:      pharmacy_signal,
            absenteeism_signal:   absenteeism_signal,
            composite_raw:        composite,
            concordance_bonus:    concordance_bonus,
            composite_calibrated: calibrated,
            reference_date:       reference_date
        })

    return fused_signals
```

**Step 8: Build cluster candidates from fused signals.** The cluster builder groups geographically and temporally adjacent flagged cells into cluster candidates, attaches the line list and supporting evidence, generates the LLM narrative, and applies suppression rules against open and recently-resolved clusters.

```
FUNCTION build_clusters(fused_signals, reference_date):
    // Aggregate adjacent flagged cells into proto-clusters using spatial
    // adjacency on the geography hierarchy and temporal proximity.
    proto_clusters = aggregate_adjacent_flags(
        signals               = fused_signals,
        spatial_adjacency_db   = AuroraPostGIS,
        temporal_window_days   = CLUSTER_TEMPORAL_WINDOW
    )

    cluster_candidates = []
    FOR each proto in proto_clusters:
        // Suppress against open clusters covering the same geography x syndrome.
        existing_cluster = find_existing_open_cluster(proto)
        IF existing_cluster:
            update_existing_cluster(existing_cluster, proto)
            continue

        // Suppress against recently-resolved false-alarm patterns.
        IF check_recent_dismissal(proto, reason_class = "false_alarm"):
            log_suppression(proto, reason = "matches_recent_dismissal")
            continue

        // Assemble the line list. Pull the per-encounter data from the
        // case-detail store under appropriate authority.
        line_list = LineListService.Build(
            geographies   = proto.geographies,
            syndromes     = proto.syndromes,
            window_start  = proto.window_start,
            window_end    = proto.window_end,
            authority     = "surveillance"
        )

        // Compute cluster-level stats.
        observed = len(line_list)
        expected = sum_of_expected_for(proto.geographies, proto.syndromes,
                                         proto.window_start, proto.window_end)
        relative_risk = observed / max(expected, 1.0)
        excess        = max(0, observed - expected)

        // Demographic distribution of cases.
        demographic_breakdown = summarize_demographics(line_list)

        // Geographic visualization payload (for the surveillance UI).
        geo_visualization = build_geo_payload(
            line_list_coords = [case.coords for case in line_list],
            heatmap_resolution = "h3_level_8"
        )

        // Lab and genomic context (where available).
        lab_context     = lookup_lab_results_for_cases(line_list, days = 14)
        genomic_context = lookup_genomic_clusters(lab_context)

        // LLM narrative for investigator review. Structured prompt with
        // pre-extracted evidence; the LLM does not generate facts, it
        // narrates the structured data.
        narrative_prompt = build_cluster_narrative_prompt({
            geographies:       proto.geographies,
            syndromes:         proto.syndromes,
            window:            (proto.window_start, proto.window_end),
            observed:          observed,
            expected:          expected,
            relative_risk:     relative_risk,
            demographic_breakdown: demographic_breakdown,
            lab_context:       lab_context,
            genomic_context:   genomic_context,
            multi_source_concordance: proto.signal_summary
        })
        bedrock_response = Bedrock.InvokeModel(
            model_id = "anthropic.claude-XX",  // HIPAA-eligible per current eligibility
            body     = { prompt: narrative_prompt, max_tokens: 800, temperature: 0.0 }
        )
        narrative = parse_bedrock_response(bedrock_response)

        // Build the cluster record.
        cluster = {
            cluster_id:           generate_cluster_id(),
            opened_at:            NOW(),
            reference_date:        reference_date,
            geographies:          proto.geographies,
            syndromes:            proto.syndromes,
            window_start:         proto.window_start,
            window_end:           proto.window_end,
            observed:             observed,
            expected:             expected,
            relative_risk:        relative_risk,
            excess:               excess,
            composite_score:      proto.composite_calibrated,
            multi_source_concordance: proto.signal_summary,
            line_list:            line_list_summary(line_list),  // de-identified summary
            line_list_pointer:    persist_line_list(line_list),  // PHI-bearing detail
            demographic_breakdown: demographic_breakdown,
            geo_visualization:    geo_visualization,
            lab_context:          lab_context,
            genomic_context:      genomic_context,
            narrative:            narrative,
            tier:                  tier_from_composite(proto.composite_calibrated),
            status:                "open_for_review",
            assigned_to:           null,
            outcome:               null
        }

        DynamoDB.PutItem(table = "cluster-state", item = cluster)
        OpenSearch.Index("cluster-index", cluster)

        EventBridge.PutEvent(
            bus = "surveillance-events",
            source = "cluster-builder",
            detail_type = "ClusterOpened",
            detail = {
                cluster_id:       cluster.cluster_id,
                tier:             cluster.tier,
                composite_score:  cluster.composite_score,
                geographies:      cluster.geographies,
                syndromes:        cluster.syndromes
            }
        )

        cluster_candidates.append(cluster)

    return cluster_candidates
```

**Step 9: Capture investigation outcomes and feed the learning loop.** Public health epidemiologists adjudicate clusters in the surveillance UI. Outcomes flow back to update suppression rules, recalibrate fusion weights, and (when enough labels accumulate) retrain syndrome classifiers and detection models.

```
FUNCTION on_investigator_action(action):
    cluster = DynamoDB.GetItem(
        table = "cluster-state",
        key   = { cluster_id: action.cluster_id }
    )

    cluster.outcome           = action.outcome
    // outcome: confirmed_outbreak, false_alarm, indeterminate,
    //          continuing_investigation, hai_cluster, foodborne_cluster,
    //          respiratory_pathogen, sti_cluster, environmental_exposure
    cluster.outcome_subtype   = action.outcome_subtype
    cluster.outcome_notes     = action.notes
    cluster.outcome_at         = NOW()
    cluster.assigned_to        = action.investigator_id
    cluster.status             = "closed" if action.outcome != "continuing_investigation" else "active_investigation"

    // Confirmed outbreaks trigger downstream workflows.
    IF action.outcome == "confirmed_outbreak":
        // Notifiable conditions go to NEDSS / eCR / NORS / NHSN as appropriate.
        IF cluster.condition in NOTIFIABLE_CONDITIONS:
            initiate_external_reporting(cluster)

        // Cross-jurisdictional coordination.
        IF cluster.crosses_jurisdictions:
            notify_neighboring_jurisdictions(cluster)

        // Response coordination workflow.
        initiate_response_coordination(cluster)

    IF action.outcome == "false_alarm":
        // Add a suppression rule keyed on the cluster's signature.
        add_suppression_rule(
            geographies   = cluster.geographies,
            syndromes     = cluster.syndromes,
            reason         = action.dismissal_reason,
            valid_until    = NOW() + DISMISSAL_VALIDITY_PERIOD
        )

    DynamoDB.PutItem(table = "cluster-state", item = cluster)
    OpenSearch.Index("cluster-index", cluster)

    // Persist the label for retraining.
    label_record = {
        cluster_id:           cluster.cluster_id,
        feature_snapshot:     cluster_feature_snapshot(cluster),
        composite_score:      cluster.composite_score,
        outcome:              cluster.outcome,
        outcome_subtype:      cluster.outcome_subtype,
        outcome_at:           cluster.outcome_at,
        time_to_adjudication:  cluster.outcome_at - cluster.opened_at,
        geographies:          cluster.geographies,
        syndromes:            cluster.syndromes
    }
    S3.PutObject(
        bucket = "surveillance-training-labels",
        key    = f"labels/year={year(cluster.outcome_at)}/month={month(cluster.outcome_at)}/{cluster.cluster_id}.json",
        body   = label_record
    )

    EventBridge.PutEvent(
        bus = "surveillance-events",
        source = "outcome-capture",
        detail_type = "ClusterClosed",
        detail = label_record
    )
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter03.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample cluster candidate (high-tier, multi-source concordance):**

```json
{
  "cluster_id": "CL-2026-10-23-000412",
  "opened_at": "2026-10-23T06:14:08Z",
  "reference_date": "2026-10-23",
  "geographies": [
    { "type": "census_tract", "id": "36055-001100" },
    { "type": "census_tract", "id": "36055-001200" },
    { "type": "census_tract", "id": "36055-001300" },
    { "type": "census_tract", "id": "36055-001400" }
  ],
  "syndromes": ["fever_respiratory", "ili"],
  "window_start": "2026-10-16",
  "window_end": "2026-10-23",
  "observed": 23,
  "expected": 6.4,
  "relative_risk": 3.59,
  "excess": 16.6,
  "composite_score": 0.91,
  "multi_source_concordance": {
    "clinical_syndromic": 0.88,
    "wastewater": 0.74,
    "school_absenteeism": 0.69,
    "pharmacy_spike": null,
    "concordant_sources": 3
  },
  "demographic_breakdown": {
    "age_group_under_5":     3,
    "age_group_5_17":        12,
    "age_group_18_49":       6,
    "age_group_50_64":       1,
    "age_group_65_plus":     1,
    "sex_female":            13,
    "sex_male":              10,
    "race_ethnicity_distribution": "matches_tract_demographics_within_expected_range"
  },
  "lab_context": {
    "respiratory_panels_run":       8,
    "respiratory_panels_positive":  2,
    "positives_by_pathogen": {
      "rhinovirus":          1,
      "rsv":                 1
    },
    "panels_pending":               4,
    "novel_pathogen_signals":       0,
    "pcr_panel_negative_with_clinical_picture": 6
  },
  "genomic_context": {
    "sequencing_in_progress":  true,
    "preliminary_clusters":    [],
    "alerting_signal":         "no_genomic_cluster_yet_identified"
  },
  "narrative": "A spatiotemporal cluster of 23 fever-respiratory and ILI ED visits across census tracts 36055-001100 through 36055-001400 over the past 7 days. The observed count is 3.6 times the historical baseline for these tracts and this calendar week, with an excess of approximately 17 cases. Cases are demographically skewed toward school-aged children (5-17) who account for 12 of 23 cases. The geographic centroid is within 0.4 miles of three elementary schools serving the affected tracts. Wastewater surveillance from the watershed serving these tracts shows a 1.8x increase in non-pathogen-specific viral RNA concentration over the past 10 days. School-district absenteeism is 18 percent over the past 5 school days, compared to a 5-year baseline of 7.5 percent for this week. Respiratory panels have been run on 8 of 23 cases; 2 are positive for routine seasonal pathogens (1 rhinovirus, 1 RSV) and 6 are negative despite a clinical picture suggestive of viral respiratory infection. 4 panels are pending. No genomic-cluster signal has been identified yet; sequencing is in progress on the panel-negative cases. Clinical, wastewater, and absenteeism signals are concordant. Recommended for surveillance team same-day review and coordination with the local health department on the school-district context.",
  "tier": "tier_1",
  "status": "open_for_review",
  "assigned_to": null
}
```

**Sample dismissed cluster (false alarm, data-quality root cause):**

```json
{
  "cluster_id": "CL-2026-10-22-000388",
  "outcome": "false_alarm",
  "outcome_subtype": "data_quality_artifact",
  "outcome_notes": "Apparent spatiotemporal cluster of GI syndrome in census tracts 36055-002100 through 36055-002400 between October 18 and October 22 was determined to be a data-quality artifact. Two of the four contributing facilities had a coding-mapping change on October 17 that reclassified a previously distinct chief-complaint category into the GI syndromic category. The change inflated GI counts by approximately 40 percent at those facilities for the affected window. The actual GI rate, after excluding the affected facilities, is consistent with the historical baseline. Adding suppression rule for these four tracts plus the GI syndrome through the remainder of the chief-complaint mapping rollout (estimated three weeks). Coordination ticket opened with the source-data feed team to update the chief-complaint mapping to align with the new coding. No public health concern at this time.",
  "investigator_id": "EPI-022",
  "outcome_at": "2026-10-22T15:33:41Z",
  "time_to_adjudication_hours": 9.2,
  "suppression_rule_added": "GI_SYNDROME -> TRACTS_36055-002100_THROUGH_36055-002400 for 21 days"
}
```

**Sample confirmed outbreak (Salmonella, multi-jurisdictional):**

```json
{
  "cluster_id": "CL-2026-08-04-000119",
  "outcome": "confirmed_outbreak",
  "outcome_subtype": "foodborne_salmonella",
  "outcome_notes": "Lab-confirmed cluster of 47 Salmonella Enteritidis cases across 7 counties, all genomically clustered (PulseNet hqSNP analysis, 0-3 SNP differences). Investigation in progress; preliminary epidemiologic interviews implicate a common ready-to-eat food product distributed through three regional grocery chains. Coordination with state PHL, FDA, and neighboring state health departments. NORS report submitted; food-product traceback in progress with FDA. Public health advisory issued to the affected regions. Continuing through outbreak control: case finding through provider notifications, retail-product recall coordination, and follow-up testing on suspect product samples.",
  "investigator_id": "EPI-007",
  "outcome_at": "2026-08-05T11:14:00Z",
  "time_to_adjudication_hours": 26.3,
  "external_reporting": {
    "nors_report_id":    "NORS-2026-NY-014",
    "pulsenet_cluster_id": "PNUSAS123456",
    "fda_traceback_initiated": true
  }
}
```

**Performance benchmarks (illustrative; measure against your own data):**

| Metric | Rules + control charts only | + Regression (Farrington Flexible) | + Spatial scan (SaTScan) | + Multi-source fusion | LLM-assisted triage |
|--------|----------------------------|-----------------------------------|--------------------------|----------------------|---------------------|
| Daily flagged-cell volume (state-wide) | 200-600 | 300-800 | 250-700 | 200-500 | similar |
| Daily cluster candidates after aggregation and suppression | 20-60 | 25-70 | 20-60 | 15-45 | 10-30 |
| Surveillance team throughput per epidemiologist-day | 5-12 | 5-12 | 5-12 | 5-12 | 10-20 (with LLM triage time savings) |
| Confirmed-outbreak rate at top tier | 5-12% | 5-15% | 8-18% | 12-25% | 15-30% |
| False-alarm rate at top tier | 50-70% | 45-65% | 40-60% | 30-50% | 25-45% |
| Lead time vs. clinician recognition (median) | 1-3 days | 2-5 days | 3-7 days | 5-10 days | 5-10 days |
| Median time-to-detection for confirmed outbreaks (cases at flag) | 8-15 cases | 6-12 cases | 4-10 cases | 3-7 cases | 3-7 cases |
| Subgroup precision range across syndrome categories | ±0.05-0.20 | ±0.05-0.15 | ±0.04-0.12 | ±0.04-0.10 | ±0.04-0.10 |
| End-to-end latency (encounter ingest to surveillance score) | <30 minutes | <30 minutes | <2 hours (daily SaTScan) | <2 hours | <2 hours |

These ranges are directional, derived from typical state-level surveillance program performance reported in the syndromic surveillance literature (Buehler et al., the ESSENCE evaluation literature). Specific figures vary substantially by jurisdiction size, source-feed coverage, syndrome mix, baseline data quality, and surveillance team staffing. Replace with measured numbers from your own validation before using for program planning.

**Where it struggles:**

- **Year-one programs.** A program in its first surveillance season has limited historical baseline data, no cohort calibration, and an unfamiliar review tempo. Expect higher false-alarm rates and slower review cadence during the first 6-12 months. Plan for it in the rollout schedule.
- **Novel pathogens.** A pathogen the surveillance system hasn't seen before (a novel variant, an emerging zoonotic, an imported tropical pathogen) often presents as a non-specific syndromic signal first. The detector flags the syndromic anomaly; the lab and genomics work that identifies the agent comes later. The surveillance team has to investigate the syndromic signal without immediate diagnostic clarity.
- **Year-over-year shifts.** A flu season that starts six weeks early, an RSV resurgence after a quiet year, a behavioral shift in care-seeking, a structural change in care delivery (telehealth expansion, urgent-care growth, retail-clinic adoption) all create year-over-year baseline mismatches. The detector either over-flags during the transition (every week looks like an outbreak) or under-flags (the baseline absorbs the shift and signals weaken).
- **Small-cell instability.** Cells with low historical counts are unstable; a baseline of 2 cases per week with a sample standard deviation of 1.2 has an upper-95 of 4 or 5, which trivially gets exceeded. Hierarchical pooling helps but doesn't eliminate the issue. Programs that try to detect at very fine spatial granularity end up with noise-dominated cells that flag constantly.
- **Multi-jurisdictional cluster invisibility.** A cluster centered on a regional airport, a multi-state distribution event, or a cross-border cluster can be invisible to any single jurisdiction's detector. Federated detection helps but requires coordination patterns that don't exist uniformly across the country.
- **Sub-clinical and pre-symptomatic infection.** Wastewater surveillance and wearable signals capture some of this, but most of the infection picture is invisible until symptoms drive care-seeking. The detector is fundamentally lagged by the incubation period and the care-seeking interval.
- **Care-seeking behavior shifts.** A storm, a holiday, news coverage of an unrelated story, a major sporting event, an urgent-care chain opening or closing in the area, or a structural shift in insurance coverage can all swing care-seeking volumes by 10-30 percent over short periods. The detector either flags these as outbreaks (false alarm) or absorbs them into the baseline (concealing real signals).
- **Coding latency for the early cases.** The first cases of a novel outbreak are usually coded with whatever ICD code the chief complaint suggests. Final diagnostic codes appear hours or days later, sometimes weeks later for conditions requiring confirmatory testing. Real-time detection has to lean on chief complaints and triage notes, where NLP error rates are non-trivial.
- **Suppressed-cell rules constrain publication.** Counts below the suppression threshold (typically 5 or 10, depending on jurisdiction) cannot be published in geographic detail without re-identification risk. This affects the public-facing dashboard, the cross-jurisdictional information products, and the press communication packages. The internal investigation has full detail; the published version may show only aggregated geography.
- **Holiday and special-event effects.** The week of Thanksgiving, the week between Christmas and New Year's, the days surrounding major sporting events all have unusual care-seeking patterns. Programs that don't model these explicitly produce predictable false alarms during these windows.
- **The underfunded-public-health reality.** Investigation capacity is the binding constraint. A surveillance system that detects perfectly but flags more clusters than the public health team can investigate produces no operational value because the alerts that matter are buried in alerts that don't.

---

## Why This Isn't Production-Ready

The pseudocode shows the shape. A production surveillance program closes several gaps the recipe leaves intentionally light.

**Public health governance is the program.** Same lesson as Recipes 3.6, 3.7, 3.8, and 3.9. The detection pipeline is maybe 25% of the work; the public health authority, the investigation procedures, the laboratory coordination, the cross-jurisdictional protocols, the response planning, and the public communication infrastructure are the other 75%. A pipeline without an active surveillance program, a defined investigation methodology, and a clear response chain will produce alerts that don't lead to outcomes. Build the program before the technology.

**Legal authority must be explicit.** The surveillance program must operate under a defined legal authority: state public health statute, institutional privacy authority, intergovernmental agreement, or some combination. Operating without that authority is both legally risky and operationally fragile. Coordinate with the state public health legal team before going live.

**Source-feed integrations are multi-quarter projects.** HL7 v2 ADT and ORU feeds, FHIR Encounter and Observation feeds, eCR document feeds, and NHSN feeds each have their own configuration, throughput, and latency characteristics. Plan for 3-9 months of integration work per source class, plus ongoing maintenance as upstream systems upgrade. Test integration completeness: missing encounter types, sampled feeds (some configurations sample rather than send everything), latency variability, and identifier-stability issues are common gotchas.

**Geographic reference data is its own data engineering project.** Census tract boundaries shift with the decennial census; school district boundaries change with redistricting; sewershed boundaries are operational rather than administrative; hospital service areas evolve with merger activity. Maintain a versioned geographic-reference dataset, refresh annually, and reconcile against historical baselines when boundaries change.

**Syndrome taxonomy must be governed.** NSSP's syndromic categories are a starting point, not an end-state. Organization-specific categories (sentinel-event triggers, jurisdiction-specific concerns, emerging-pathogen categories) need explicit definition, versioning, and validation. Changes to the syndrome taxonomy invalidate historical baselines for the changed categories; plan for the recomputation cost and the operational disruption.

**NLP on chief complaints needs continuous validation.** The accuracy of syndromic classification depends on the chief-complaint text and the NLP model's handling of it. EHR upgrades, chief-complaint template changes, triage-process changes, and provider documentation patterns all shift the input distribution. Validate NLP performance quarterly against a held-out labeled set and retrain when drift is detected.

**Case-detail PHI store separation is critical.** Surveillance analytic data should be aggregated to cells; the case-detail data with patient identifiers should live in a separate store with its own access controls. Investigators access case detail under specific authority; the analytic pipeline operates on de-identified or pseudonymized data. The architectural separation is a privacy-by-design requirement that's easy to skip and hard to retrofit.

**Cross-jurisdictional coordination must be tested before it's needed.** When an outbreak crosses jurisdictional lines, the detection system, the case-management workflow, and the public messaging all have to span jurisdictions. Tabletop the cross-jurisdictional protocols quarterly; the first time you exercise them shouldn't be the first time you need them.

**Lab integration is its own program.** State public health labs, hospital microbiology labs, and commercial reference labs each have their own data formats and integration mechanisms. Lab data is the highest-fidelity surveillance signal because it's pathogen-specific, but the integration work is substantial. Plan for parallel multi-quarter integration with each lab class. Genomic data integration (PulseNet, NCBI Pathogen Detection, organization-specific sequencing) adds another layer of integration complexity.

**eCR and NEDSS integration follow public health interoperability frameworks.** The eCR Now framework, the AIMS platform, the NEDSS Base System (NBS) and NEDSS-compatible products (Maven, Trisano, etc.) define how clinical systems and public health authorities exchange notifiable-condition data. Coverage is increasing but uneven. Plan for both eCR-integrated sources and legacy reporting channels (faxed and phoned-in reports for some conditions and jurisdictions).

**Wastewater integration is non-trivial when it's part of the program.** NWSS provides a national framework, but most local programs work directly with sample-processing labs and may use multiple labs across a sewershed network. Wastewater data has its own quality issues: sample collection variability, normalization considerations (against population estimates, against sewershed flow rates, against indicator pathogens like PMMoV), pathogen-specific concentration dynamics, and reporting cadence. Don't underestimate the analytic complexity of converting wastewater concentrations into a usable surveillance signal.

**Investigation-team capacity sets the operational ceiling.** A state surveillance team with a few dozen epidemiologists for a population of millions can investigate 10-30 clusters per day, not 100. Threshold tuning should match the team's actual throughput. A precision improvement that produces a queue larger than the team can review is not an improvement. Plan to retune thresholds quarterly as the program evolves and as team capacity changes.

**Equity and subgroup performance audits are mandatory.** Track flag rates, cluster-confirmation rates, and time-to-investigation by demographic group, geography, language, insurance category, and rurality. Wide variation warrants investigation. Surveillance systems that flag clusters disproportionately in some communities or under-flag in others reproduce existing inequities in care access and outbreak response.

**Public communication infrastructure must precede deployment.** When a confirmed outbreak warrants public notification, the communication infrastructure (health advisories, press releases, public dashboards, multilingual messaging, social media coordination) needs to be in place. Programs that detect outbreaks faster than they can communicate them produce situations where the press finds out before the public health team is ready, which damages program credibility.

**Notifiable-condition reporting integration is its own engineering effort.** NEDSS, NORS, NHSN, NMI, and (for some conditions) bilateral reporting to neighboring jurisdictions or international bodies each have their own protocols, data formats, and reporting cadences. Build reporting integration into the cluster-builder workflow rather than retrofitting it.

**Suppression-rule lifecycle management.** Suppression rules accumulate. After a few years of operation, the suppression-rule store can contain thousands of entries, some still valid, some stale, some legitimately superseded. Build a suppression-rule audit and renewal process from the start; without it, the system either over-suppresses (concealing real signals) or under-suppresses (re-flagging known patterns).

**Decommissioning criteria.** Pre-approved criteria for when specific detector classes get tuned, suppressed, or retired. Without pre-approved criteria, every tuning conversation becomes a political conversation; with them, it's a public-health-effectiveness decision driven by data.

**Disaster recovery and continuity.** Multi-AZ deployment for the active components is the minimum. The fallback during system outage is the manual surveillance process: weekly aggregate reports from facilities, manual review by the surveillance team, and the legacy NSSP/ESSENCE process. Both should be documented and exercised, because the system will be down sometime and outbreak risk doesn't pause.

**Vendor-tool considerations.** Many surveillance programs use ESSENCE (through NSSP/BioSense), commercial NEDSS-compatible products (Maven, Trisano), or specialized infection-prevention products (Theradoc, MedMined, VigiLanz, others) for parts of the workflow. The decision to build versus buy versus extend depends on existing tooling, the organization's engineering capacity, and the specific patterns the program needs to support. Many programs run a hybrid: ESSENCE through NSSP for the bulk of syndromic surveillance plus AWS-native components for organization-specific patterns, advanced analytics, and integration with auxiliary data sources. Honest framing matters: this recipe describes the underlying patterns, not a competitor to NSSP/BioSense or commercial products.

**Records retention and legal hold.** Surveillance data, case data, and outbreak investigation records must be retained per applicable retention policies, and may be subject to legal hold during active investigations or litigation. Public health investigation records often have multi-year retention requirements. Build retention and legal-hold capabilities into the storage layer from the start; retrofitting them later is painful.

**Self-monitoring of the surveillance system.** The surveillance system itself contains highly sensitive data: encounter detail, line lists, investigation histories, demographic distributions. Access to the surveillance system must be tightly controlled, fully audited, and regularly reviewed. The system should monitor itself: an investigator's access to case detail is itself an audit event, and access patterns within the surveillance system warrant the same scrutiny applied to clinical EHRs.

---

## Variations and Extensions

**ESSENCE / NSSP / BioSense integration rather than replacement.** The most common variation is using AWS-native components to extend rather than replace ESSENCE through NSSP. ESSENCE handles the bulk of standard syndromic surveillance with established methodology and a well-known interface; the AWS-native layer handles organization-specific syndromes, advanced multi-source fusion, LLM-assisted triage, and integration with auxiliary data sources NSSP doesn't support. Many state programs operate this way: NSSP/ESSENCE for the federal-aligned syndromic surveillance plus organization-specific extensions for state-priority work.

**Hospital-level HAI surveillance.** The same architectural patterns apply at the hospital scale, with different data sources (NHSN feeds, microbiology, antibiotic stewardship data, OR scheduling, staff assignments) and different geographic units (units, ORs, procedures, devices). The detection patterns (control charts on standardized infection ratios, scan statistics on procedure-team graphs, genomic clustering for HAI strains) are conceptually similar to community-level outbreak detection. Many academic medical centers run institutional HAI surveillance alongside (or in coordination with) the public health programs.

**Genomic-cluster integrated surveillance.** Tighter integration with sequencing results: PulseNet-style genomic-cluster detection for foodborne pathogens, SARS-CoV-2-style variant tracking, TB strain typing, healthcare-associated infection genomics. Requires close coordination with the sequencing lab (state PHL, hospital lab, or commercial reference lab) and the bioinformatics team. The resulting signal is high-fidelity; the integration work is substantial.

**Wastewater-led surveillance.** A variation where wastewater is the primary surveillance signal and clinical surveillance is the confirmatory signal. Useful for pathogens where wastewater leads clinical by enough to matter (SARS-CoV-2 was the canonical case). Requires reliable wastewater sampling, processing capacity, and the analytic infrastructure to convert concentrations into a usable surveillance signal.

**Wearable-aggregate signal integration.** Population-level deviations in resting heart rate, sleep, and activity from consumer wearables (Fitbit, Apple Watch, Oura, Garmin) can lead clinical signals by days. The Stanford wearable surveillance work, the DETECT Study, and several research programs have demonstrated the signal. Operationally early-stage in 2026; aggregation, privacy, and partnership patterns are still evolving. 

**LLM-assisted investigation copilot.** An LLM-driven copilot for surveillance epidemiologists that can answer questions about a cluster ("show me every fever-respiratory ED visit in this ZIP in the last 14 days," "what's the historical pattern for this syndrome in this season"), retrieve evidence on demand, and assist with note drafting. Distinct from the cluster-narrative LLM, which compiles the initial summary. Emerging in 2026; substantial productivity potential.

**Cross-jurisdictional federated surveillance.** A federated detection model where each jurisdiction runs its own surveillance and shares higher-level signals upstream. State health departments aggregate from local; CDC aggregates from states; international surveillance (WHO, ECDC, Africa CDC, others) aggregates from national. The federation pattern preserves jurisdictional control while enabling cross-boundary cluster detection. Architectural complexity is real; the legal and operational frameworks vary by region.

**Climate and weather-aware surveillance.** Some pathogens (vector-borne, waterborne, heat-illness) are tightly coupled to weather. Integrating weather and climate data into the baseline (so the detector knows that a heat wave is in progress when heat-illness counts spike) reduces false alarms during predictable weather events and surfaces real anomalies. Useful for vector-borne disease surveillance (West Nile, EEE, Powassan, dengue, malaria), waterborne disease surveillance (cholera, leptospirosis), and heat-illness surveillance.

**One Health surveillance integration.** Combining human, animal, and environmental surveillance for zoonotic disease detection. Integration with veterinary surveillance (USDA APHIS), wildlife surveillance (state wildlife agencies, USGS), and environmental monitoring (EPA, state DEP) catches emerging zoonotic threats earlier than human-only surveillance. Operationally complex; the data-sharing patterns across federal agencies and state organizations are bespoke.

**Mass-gathering surveillance.** Temporary intensified surveillance around large events (sporting events, conventions, religious gatherings, music festivals) and post-disaster contexts. Sub-daily aggregation, more aggressive threshold sensitivity, and specific syndromic categories (foodborne, heat illness, injury, mental health) appropriate to the event type. Operationally well-defined; CDC and academic programs have established protocols.

**Pharmacy-based surveillance.** OTC product sales (where the data is shared, typically through retail-pharmacy partnerships), prescription-fill data for antiviral and antibiotic agents, and over-the-counter rapid-test sales (where available, especially post-pandemic). Useful for influenza-like illness surveillance, and increasingly for COVID-19 detection given the over-the-counter testing landscape.

**Provider-network and telehealth surveillance.** Integrating telehealth visit data into the surveillance system. Telehealth visits often have different geographic semantics (the patient's home, not the clinic location) and different clinical-data completeness. The integration provides additional coverage for populations and geographies that don't otherwise show up in ED-based surveillance.

**Death-certificate surveillance.** State vital records data integrated with surveillance for excess-mortality detection. Lagged compared to syndromic data (death certificates take days to weeks to be filed and processed) but provides a different and important signal. Excess mortality during the early COVID-19 pandemic was a leading indicator that complemented case counts.

**Syndromic surveillance for non-communicable conditions.** The same machinery applied to non-communicable conditions: opioid overdose surveillance, suicide-attempt surveillance, intimate-partner violence surveillance, environmental-exposure surveillance. Different syndrome taxonomies, different geographic and demographic considerations, different response infrastructures. The architectural pattern transfers; the operational program is distinct.

**Privacy-preserving multi-organization surveillance.** Federated learning, secure multi-party computation, and differential privacy approaches that allow cross-organization surveillance without raw-data sharing. Operationally early-stage in healthcare surveillance; the research is active and a few pilots exist. Useful for cross-state cluster detection and for surveillance involving sensitive populations where data-sharing is legally constrained.

**Conversational AI for the public.** A patient-facing chatbot that allows individuals to report symptoms anonymously and aggregates the reports for public health surveillance. Provides a complementary signal to provider-based surveillance because it captures people who don't seek care. Privacy considerations are significant; the surveillance value depends on participation rates that are hard to predict.

**Patient-facing transparency on outbreaks.** Public-facing dashboards that show current outbreak status (with appropriate suppression) and historical patterns, integrated with the patient portal so individuals can see whether elevated activity is occurring in their area. Operationally early-stage but consistent with broader patient-rights movements toward health-data transparency.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [Amazon Aurora PostgreSQL User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html)
- [Amazon Timestream Developer Guide](https://docs.aws.amazon.com/timestream/latest/developerguide/what-is-timestream.html)
- [Amazon OpenSearch Service Developer Guide](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/what-is.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Processing](https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon Location Service Developer Guide](https://docs.aws.amazon.com/location/latest/developerguide/welcome.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS Batch User Guide](https://docs.aws.amazon.com/batch/latest/userguide/what-is-batch.html)
- [AWS AppSync Developer Guide](https://docs.aws.amazon.com/appsync/latest/devguide/welcome.html)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): time-series forecasting, anomaly detection, and Processing-job examples relevant to baseline computation and detection.
- [`aws-samples`](https://github.com/aws-samples): search for "FHIR," "HL7," "geospatial analytics," "Athena geospatial," and "public health" for adjacent integration and analytics patterns.

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter by Healthcare and AI/ML): healthcare reference architectures.
- [AWS Industries Blog (Healthcare and Life Sciences)](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AWS architectures and customer stories.
- [AWS Public Sector Blog](https://aws.amazon.com/blogs/publicsector/): government and public-sector use cases including some public health surveillance work.
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search for "anomaly detection," "time series," and "geospatial analytics" for technique deep-dives.

**Public Health and Surveillance References:**
- [CDC National Syndromic Surveillance Program (NSSP)](https://www.cdc.gov/nssp/): the federal program coordinating ED-based syndromic surveillance.
- [CDC BioSense Platform](https://www.cdc.gov/nssp/biosense/index.html): the NSSP's hosted analytics platform used by participating jurisdictions.
- [ESSENCE (JHUAPL)](https://www.jhuapl.edu/work/projects-and-missions/essence): the analytical engine used by NSSP and many state and local programs.
- [CDC NEDSS](https://www.cdc.gov/nedss/): the National Electronic Disease Surveillance System framework for state-level case management.
- [CDC eCR Now](https://ecr.aimsplatform.org/): the electronic case reporting framework and AIMS platform.
- [CDC National Notifiable Diseases Surveillance System (NNDSS)](https://www.cdc.gov/nndss/): the federal nationally notifiable diseases system.
- [CDC NORS (National Outbreak Reporting System)](https://www.cdc.gov/nors/): waterborne, foodborne, and enteric outbreak reporting.
- [CDC NHSN (National Healthcare Safety Network)](https://www.cdc.gov/nhsn/): healthcare-associated infection surveillance.
- [CDC National Wastewater Surveillance System (NWSS)](https://www.cdc.gov/nwss/wastewater-surveillance.html): wastewater-based surveillance.
- [CDC PulseNet](https://www.cdc.gov/pulsenet/): the molecular subtyping network for foodborne disease surveillance.
- [Council of State and Territorial Epidemiologists (CSTE)](https://www.cste.org/): notifiable-disease list and surveillance methodology coordination.
- [Association of Public Health Laboratories (APHL)](https://www.aphl.org/): public health laboratory coordination including AIMS platform.
- [SaTScan](https://www.satscan.org/): the canonical spatial and spatiotemporal scan-statistic software.
- [Nextstrain](https://nextstrain.org/): real-time tracking of pathogen evolution and genomic-cluster surveillance.

**Regulatory and Compliance References:**
- [HIPAA Privacy Rule, Public Health Exception (45 CFR 164.512(b))](https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164/subpart-E/section-164.512#p-164.512(b)): the regulatory basis for public-health-authority access to PHI.
- [State Public Health Statutes](https://www.cdc.gov/phlp/publications/topic/index.html): jurisdiction-specific authorities; varies by state.
- [HHS Office for Civil Rights (OCR) Public Health Guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/public-health/index.html): OCR guidance on the public health exception.

**Industry Frameworks and Standards:**
- [HL7 v2 ADT and ORU](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185): the dominant clinical-encounter and lab-result data formats.
- [HL7 FHIR](https://www.hl7.org/fhir/): the modern interoperability standard underpinning eCR and emerging surveillance integrations.
- [LOINC](https://loinc.org/): laboratory test and observation codes.
- [SNOMED CT](https://www.snomed.org/): clinical terminology.
- [ICD-10-CM](https://www.cdc.gov/nchs/icd/icd10cm.htm): diagnosis coding.
- [CDC NNDSS Message Mapping Guides (MMGs)](https://www.cdc.gov/nndss/data-and-resources/surveillance-message-mapping-guides.html): CDC standards for surveillance message structure and case-notification formatting. 

**Academic and Industry Literature:**

- [`R/surveillance` package](https://cran.r-project.org/package=surveillance): the canonical R package for outbreak detection methodology, including Farrington Flexible and related algorithms.
- [SaTScan documentation](https://www.satscan.org/): user guide and methodology references for spatial and spatiotemporal scan statistics.
- Farrington, C.P., Andrews, N.J., Beale, A.D., Catchpole, M.A. (1996). "A statistical algorithm for the early detection of outbreaks of infectious disease." *Journal of the Royal Statistical Society: Series A*, 159(3), 547-563.
- Noufaily, A., Enki, D.G., Farrington, P., Garthwaite, P., Andrews, N., Charlett, A. (2013). "An improved algorithm for outbreak detection in multiple surveillance systems." *Statistics in Medicine*, 32(7), 1206-1222.
- Kulldorff, M. (1997). "A spatial scan statistic." *Communications in Statistics: Theory and Methods*, 26(6), 1481-1496.
- Kulldorff, M., Heffernan, R., Hartman, J., Assuncao, R., Mostashari, F. (2005). "A space-time permutation scan statistic for disease outbreak detection." *PLoS Medicine*, 2(3), e59.
- Buehler, J.W., Hopkins, R.S., Overhage, J.M., Sosin, D.M., Tong, V. (2004). "Framework for evaluating public health surveillance systems for early detection of outbreaks." *MMWR Recommendations and Reports*, 53(RR-5), 1-11.

**Operational and Vendor References (informational; not endorsements):**
- [Maven (Conduent)](https://www.conduent.com/government/health/disease-surveillance/): commercial NEDSS-compatible surveillance platform.
- [Trisano](https://www.trisano.org/): open-source NEDSS-compatible surveillance platform.
- [BlueDot](https://bluedot.global/): commercial outbreak intelligence platform.
- [HealthMap](https://healthmap.org/en/): outbreak news monitoring.

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single state-level ED encounter feed (HL7 v2 ADT through state aggregator), control-chart and Farrington Flexible detection on 4-6 syndromes at the county level, manual surveillance team queue, basic governance, parallel comparison with the existing NSSP/ESSENCE process | 6-12 months |
| Production-ready | Statewide ED and urgent-care feeds (or institutional equivalent), lab feed integration, eCR/NEDSS integration for notifiable conditions, syndrome classification with Comprehend Medical and a custom NLP model, multi-resolution geographic stratification, control-chart plus regression-based plus spatial-scan detection, multi-source fusion with at least wastewater and one auxiliary source, LLM-assisted cluster narrative, surveillance UI, full surveillance program governance with cross-jurisdictional protocols, retraining pipeline, public-facing dashboards with suppression, NSSP and CSTE reporting integration | 18-30 months |
| With variations | Additional states/jurisdictions, genomic-cluster integration, wearable-aggregate signal integration, conversational AI investigator copilot, patient-facing transparency dashboards, federated cross-jurisdictional surveillance, One Health integration with veterinary and environmental surveillance, climate and weather-aware baseline modeling, mass-gathering temporary surveillance overlays, advanced equity audits with formalized disparate-impact analysis | 24-60 months beyond production-ready |

---

---

*← [Main Recipe 3.10](chapter03.10-epidemic-outbreak-detection) · [Python Example](chapter03.10-python-example) · [Chapter Preface](chapter03-preface)*
