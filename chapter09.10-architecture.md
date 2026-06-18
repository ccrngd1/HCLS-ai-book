# Recipe 9.10 Architecture and Implementation: Multi-Modal Imaging Fusion and Analysis

*Companion to [Recipe 9.10: Multi-Modal Imaging Fusion and Analysis](chapter09.10-multi-modal-imaging-fusion-analysis). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## Why These Services

**Amazon S3 for DICOM storage and processing pipeline.** Medical imaging generates massive data volumes. A single PET-CT study can be 500+ MB of DICOM files. S3 provides the durable, encrypted, high-throughput storage needed to receive studies from PACS, stage them for processing, and retain results. S3 event notifications trigger the processing pipeline when a complete study arrives. Lifecycle policies handle archival of processed studies to cheaper storage tiers.

**Amazon SageMaker for ML model hosting and batch inference.** The registration and fusion models (deep learning-based deformable registration, multi-modal segmentation networks) need GPU compute. SageMaker provides managed GPU instances for both training and inference. For batch processing (nightly fusion runs on new studies), SageMaker Processing Jobs or Batch Transform handle the compute without persistent infrastructure. For near-real-time clinical use, SageMaker endpoints with GPU-backed instances provide consistent latency.

**AWS Step Functions for pipeline orchestration.** The fusion pipeline is a multi-step workflow with conditional logic: registration might succeed or fail, the fusion approach depends on which modalities are available, and quality checks gate progression. Step Functions models this as a state machine with error handling, retries, and parallel execution branches (e.g., preprocessing multiple modalities simultaneously).

**AWS Lambda for lightweight coordination tasks.** DICOM parsing, metadata extraction, study completeness checks, notification dispatch, and result packaging are short-lived tasks that fit Lambda's execution model. Lambda handles the glue between pipeline stages while SageMaker handles the heavy compute.

**Amazon DynamoDB for study tracking and metadata.** Track pipeline state: which studies are in progress, which completed, which failed. Store registration quality metrics, fusion parameters used, and audit records. Point lookups by study ID support the clinical workflow where a radiologist checks whether fusion results are ready.

**Amazon HealthLake or S3 + custom indexing for DICOM management.** For DICOM study management, evaluate HealthLake Imaging for native DICOM storage and retrieval, or build a custom indexing layer on S3 if your query patterns (DICOM-RT cross-references, multi-modal series linking) exceed what HealthLake supports natively.

## Architecture Diagram

```mermaid
flowchart TD
    A[PACS / Modality] -->|DICOM Send| B[S3 Bucket\ndicom-incoming/]
    B -->|S3 Event| C[Lambda\nstudy-completeness-check]
    C -->|Study Complete| D[Step Functions\nfusion-pipeline]
    
    D --> E[Lambda\nDICOM Parse &\nPreprocessing]
    E --> F[SageMaker Processing\nRegistration]
    F --> G{Registration\nQuality Check}
    G -->|Pass| H[SageMaker Processing\nFusion & Analysis]
    G -->|Fail| I[SNS Alert\nManual Review]
    H --> J[Lambda\nResult Packaging\nDICOM-RT/SEG]
    J --> K[S3 Bucket\nfusion-results/]
    K --> L[PACS / Treatment\nPlanning System]
    
    D -.->|State Tracking| M[DynamoDB\npipeline-state]
    
    style B fill:#f9f,stroke:#333
    style F fill:#ff9,stroke:#333
    style H fill:#ff9,stroke:#333
    style M fill:#9ff,stroke:#333
```

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon S3, AWS Lambda, AWS Step Functions, Amazon SageMaker, Amazon DynamoDB, Amazon SNS, Amazon CloudWatch |
| **IAM Permissions** | `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateProcessingJob`, `sagemaker:InvokeEndpoint`, `states:StartExecution`, `dynamodb:PutItem`, `dynamodb:GetItem`, `sns:Publish` |
| **BAA** | AWS BAA signed (required: DICOM images are PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest; SageMaker: volume encryption with KMS; all transit over TLS |
| **VPC** | Production: SageMaker and Lambda in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime. PACS connectivity via Direct Connect or VPN to VPC. |
| **CloudTrail** | Enabled: log all S3, SageMaker, and Step Functions API calls for HIPAA audit trail |
| **GPU Instances** | SageMaker: ml.g5.xlarge or ml.g5.2xlarge for registration and fusion inference. Training: ml.g5.12xlarge or ml.p4d.24xlarge for multi-modal model training |
| **Sample Data** | BraTS (Brain Tumor Segmentation) challenge data for brain multi-modal MRI. TCIA (The Cancer Imaging Archive) for PET-CT datasets. Never use real patient imaging in dev. |
| **Cost Estimate** | Per study: ~$0.50 storage + $1.00-5.00 SageMaker GPU compute (registration + fusion) + $0.10 Lambda/Step Functions. Varies heavily with image resolution and model complexity. |

## Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon S3** | DICOM storage for incoming studies, intermediate results, and fusion outputs |
| **AWS Lambda** | DICOM parsing, study completeness detection, metadata extraction, result packaging |
| **AWS Step Functions** | Orchestrate multi-step fusion pipeline with branching logic and error handling |
| **Amazon SageMaker** | GPU compute for registration models, fusion inference, and segmentation |
| **Amazon DynamoDB** | Pipeline state tracking, study metadata, quality metrics |
| **Amazon SNS** | Alert on pipeline failures requiring manual intervention |
| **AWS KMS** | Encryption key management for PHI at rest |
| **Amazon CloudWatch** | Monitoring, metrics, and alarms for pipeline health |

## Pseudocode Walkthrough

**Step 1: Study completeness detection.** When DICOM files arrive from PACS (typically pushed via DICOM C-STORE), they land in S3 one file at a time. A study might have 800 DICOM files across multiple series (the CT series, the PET series, each with hundreds of slices). The pipeline can't start processing until the entire study is present. This step monitors incoming files, groups them by study and series using DICOM metadata (StudyInstanceUID, SeriesInstanceUID), and triggers the pipeline only when all expected series are complete. Without this gate, you'd start processing an incomplete volume and produce garbage results.

```pseudocode
FUNCTION check_study_completeness(new_file_key):
    // Extract DICOM metadata from the newly arrived file
    dicom_header = parse DICOM header from S3 object at new_file_key
    study_uid    = dicom_header.StudyInstanceUID
    series_uid   = dicom_header.SeriesInstanceUID
    instance_num = dicom_header.InstanceNumber
    total_slices = dicom_header.NumberOfFrames OR infer from DICOM series metadata

    // Update the tracking record for this series
    update DynamoDB "study-tracker" record:
        key          = study_uid + "/" + series_uid
        received     = received + 1
        last_updated = current UTC timestamp

    // Check if ALL series for this study are complete
    all_series = query DynamoDB for all records matching study_uid
    
    FOR each series_record in all_series:
        IF series_record.received < series_record.expected_slices:
            RETURN "still_waiting"  // not all slices arrived yet
    
    // All series complete. Trigger the fusion pipeline.
    start Step Functions execution with:
        study_uid = study_uid
        series_list = [series metadata for each complete series]
        s3_prefix = derive S3 path prefix from study_uid
    
    RETURN "pipeline_triggered"
```

**Step 2: DICOM parsing and preprocessing.** Once a complete study is confirmed, each modality series needs to be converted from raw DICOM slices into a 3D volume suitable for registration algorithms. This means sorting slices by position, assembling them into a volumetric array, extracting the spatial transform (the affine matrix that maps voxel indices to patient coordinates), and applying modality-specific corrections. CT needs no correction beyond reading Hounsfield units. MRI may need bias field correction. PET needs SUV normalization using patient weight and tracer injection dose/time from DICOM headers. Skip the preprocessing and your registration will either fail outright or produce subtly wrong results that look plausible but place structures in the wrong locations.

```pseudocode
FUNCTION preprocess_modality(series_dicom_files, modality_type):
    // Sort DICOM slices by spatial position to assemble the 3D volume correctly
    sorted_slices = sort series_dicom_files by ImagePositionPatient z-coordinate

    // Build the 3D volume: stack 2D slices into a volumetric array
    volume = assemble 3D numpy array from sorted_slices pixel data
    
    // Extract the spatial mapping: voxel coordinates to patient coordinates
    // This affine matrix encodes voxel size, orientation, and position
    affine_matrix = compute from:
        ImagePositionPatient   (origin of the first slice)
        ImageOrientationPatient (row and column direction cosines)
        PixelSpacing           (in-plane voxel size)
        SliceThickness         (between-slice distance)

    // Apply modality-specific preprocessing
    IF modality_type == "CT":
        // CT values are already in Hounsfield units. Clip to relevant range.
        volume = clip volume to [-1024, 3072]  // air to dense bone

    ELSE IF modality_type == "PET":
        // Convert raw counts to Standardized Uptake Values (SUV)
        // SUV normalizes for patient weight and injected dose
        patient_weight = dicom_header.PatientWeight  // kg
        injected_dose  = dicom_header.RadiopharmaceuticalInformationSequence.RadionuclideTotalDose
        decay_time     = compute from injection time to scan time
        decay_corrected_dose = injected_dose * exp(-decay_constant * decay_time)
        volume = volume * patient_weight / decay_corrected_dose  // now in SUV units

    ELSE IF modality_type == "MR":
        // Bias field correction: remove intensity non-uniformity from RF coil
        // N4ITK algorithm estimates and removes the smooth bias field
        bias_field = estimate N4ITK bias field from volume
        volume = volume / bias_field  // corrected intensities

    RETURN {
        volume: volume,           // 3D array of processed voxel values
        affine: affine_matrix,    // spatial transform to patient coordinates
        modality: modality_type,  // for downstream processing decisions
        metadata: relevant DICOM header fields  // for audit and result packaging
    }
```

**Step 3: Registration.** This is the most critical step. Align all modalities to a common reference frame so that the same anatomical point has the same coordinates in every volume. The reference modality is typically the one with highest spatial resolution or the one used for treatment planning (often CT in radiation oncology). Registration proceeds in two phases: rigid alignment first (fast, handles gross positioning differences), then deformable registration if the anatomy has changed between acquisitions. The quality of this step determines everything downstream. A 3mm error here means the PET hotspot you overlay on the MRI is pointing at the wrong brain structure.

```pseudocode
FUNCTION register_to_reference(moving_volume, reference_volume, anatomy_type):
    // Phase 1: Rigid registration
    // Find the optimal rotation (3 angles) and translation (3 shifts)
    // that best aligns the moving image to the reference
    rigid_transform = optimize rigid alignment:
        metric     = mutual information  // works across modalities because it measures
                                         // statistical dependency, not pixel similarity
        optimizer  = gradient descent with multi-resolution pyramid
        moving     = moving_volume
        fixed      = reference_volume
    
    // Apply rigid transform to get initial alignment
    rigidly_aligned = resample moving_volume using rigid_transform
    
    // Phase 2: Deformable registration (if anatomy type requires it)
    IF anatomy_type in ["abdomen", "thorax", "pelvis", "breast"]:
        // Non-rigid anatomy needs deformable registration
        // Compute a displacement field: for every voxel, how far to shift
        deformation_field = compute deformable registration:
            method     = deep learning (VoxelMorph-style) OR classical (B-spline)
            moving     = rigidly_aligned
            fixed      = reference_volume
            regularization = diffusion penalty  // prevents physically impossible folds
        
        registered_volume = warp rigidly_aligned using deformation_field
        total_transform   = compose(rigid_transform, deformation_field)
    
    ELSE:
        // Rigid anatomy (brain in skull, spine segments): rigid is sufficient
        registered_volume = rigidly_aligned
        total_transform   = rigid_transform
    
    // Quality assessment: check that the registration is actually good
    quality_metrics = compute:
        mutual_information(registered_volume, reference_volume)
        dice_coefficient of landmark structures if available
        jacobian_determinant of deformation_field  // negative values mean folding (bad)
    
    RETURN {
        registered_volume: registered_volume,
        transform: total_transform,
        quality_metrics: quality_metrics,
        passed_qc: quality_metrics meet threshold criteria
    }
```

**Step 4: Multi-modal fusion and analysis.** With all modalities registered to the same coordinate frame, combine their information for the target clinical task. The fusion approach depends on what you're trying to accomplish. For automated segmentation (e.g., delineating tumor extent), the state-of-the-art is a deep learning model that takes all modalities as input channels and outputs a voxel-wise segmentation map. For treatment planning support, the fusion might propagate structure contours from one modality to another. For radiomics (quantitative feature extraction), the fusion extracts features from each modality independently but in the same spatial regions. Each approach produces different outputs, but they all depend on accurate registration from Step 3.

```pseudocode
FUNCTION fuse_and_analyze(registered_volumes, clinical_task):
    // Stack all registered modalities as channels of a multi-channel volume
    // Example: 4-channel input for brain tumor segmentation (T1, T1ce, T2, FLAIR)
    multi_channel_volume = stack [vol.registered_volume for vol in registered_volumes]
    
    IF clinical_task == "segmentation":
        // Run multi-modal segmentation model
        // Input: N-channel volume (one channel per modality)
        // Output: voxel-wise label map (background, tumor core, enhancing, edema, etc.)
        segmentation_map = invoke SageMaker endpoint:
            model    = multi-modal-segmentation-model
            input    = multi_channel_volume
            metadata = { modality_order: [list of modality types in channel order] }
        
        // Post-process: connected component analysis, remove small islands
        cleaned_segmentation = remove components smaller than min_volume_threshold
        
        // Compute volumetric measurements from segmentation
        volumes = compute volume in mL for each label class
        
        RETURN {
            segmentation: cleaned_segmentation,
            volumes: volumes,
            confidence_map: model softmax outputs per voxel
        }
    
    ELSE IF clinical_task == "treatment_planning_support":
        // Propagate structures from MRI to CT planning scan using registration transform
        // Clinician contours on MRI (better soft tissue contrast)
        // Treatment planning happens on CT (needed for dose calculation)
        mri_contours = load existing contours from MRI study
        ct_contours  = transform mri_contours using inverse registration transform
        
        // Also compute metabolic tumor volume from PET
        pet_volume = registered_volumes["PET"].registered_volume
        metabolic_active = threshold pet_volume at SUV > 2.5  // common clinical threshold
        
        RETURN {
            propagated_contours: ct_contours,
            metabolic_volume: metabolic_active,
            biological_target_volume: intersection of anatomical and metabolic volumes
        }
    
    ELSE IF clinical_task == "radiomics":
        // Extract quantitative features from each modality within defined ROIs
        roi_mask = load region of interest (from segmentation or manual contour)
        
        features = empty map
        FOR each modality_vol in registered_volumes:
            modality_features = extract radiomic features:
                first_order   = [mean, std, skewness, kurtosis, entropy]
                shape         = [volume, surface_area, sphericity, compactness]
                texture       = [GLCM, GLRLM, GLSZM features]
                from volume   = modality_vol.registered_volume
                within mask   = roi_mask
            features[modality_vol.modality] = modality_features
        
        RETURN { radiomic_features: features }
```

**Step 5: Result packaging and delivery.** The fusion and analysis results need to get back into the clinical workflow, which means packaging them in DICOM-compatible formats and pushing them to PACS or the treatment planning system. Segmentation maps become DICOM-RT Structure Sets (for radiation oncology) or DICOM SEG objects (for general imaging). Quantitative measurements become DICOM-SR (Structured Reports). The registered and fused volumes become new DICOM series linked to the original study. This packaging step is what makes the computational results clinically usable rather than trapped in a research pipeline.

```pseudocode
FUNCTION package_and_deliver(analysis_results, original_study_metadata):
    // Package segmentation as DICOM-RT Structure Set
    IF "segmentation" in analysis_results:
        rt_struct = create DICOM-RT Structure Set:
            referenced_study     = original_study_metadata.StudyInstanceUID
            referenced_series    = reference CT series UID
            structures           = convert each label to a set of contour points per slice
            structure_names      = ["GTV_MRI", "CTV_metabolic", "Edema", ...]
            structure_colors     = [red, green, blue, ...]  // display colors
            manufacturer         = "AI Fusion Pipeline v1.0"
            approval_status      = "UNAPPROVED"  // clinician must verify
    
    // Package measurements as DICOM Structured Report
    IF "volumes" in analysis_results:
        dicom_sr = create DICOM-SR:
            measurement_groups = [
                { concept: "Tumor Volume", value: volumes["tumor_core"], unit: "mL" },
                { concept: "Metabolic Volume", value: volumes["metabolic"], unit: "mL" },
                ...
            ]
            referenced_study = original_study_metadata.StudyInstanceUID
    
    // Store results in S3
    result_prefix = "fusion-results/" + study_uid + "/"
    upload rt_struct, dicom_sr, and registered volumes to S3 at result_prefix
    
    // Push to PACS via DICOM C-STORE or DICOMweb STOW-RS
    send results to PACS endpoint
    
    // Update pipeline tracking
    update DynamoDB "pipeline-state":
        study_uid = study_uid
        status    = "completed"
        result_s3 = result_prefix
        completed_at = current UTC timestamp
        quality_metrics = registration and analysis quality scores
    
    RETURN { status: "delivered", result_location: result_prefix }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter09.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

## Expected Results

**Sample output for a brain tumor PET-MRI-CT fusion study:**

```json
{
  "study_uid": "1.2.840.113619.2.378.3596.2847512.20260301",
  "pipeline_id": "fusion-20260301-00047",
  "modalities_fused": ["MR_T1", "MR_T1CE", "MR_T2", "MR_FLAIR", "PET_FDG", "CT"],
  "registration_quality": {
    "MR_T1_to_CT": { "mutual_information": 1.42, "landmark_error_mm": 0.8, "status": "pass" },
    "PET_to_CT": { "mutual_information": 1.15, "landmark_error_mm": 1.2, "status": "pass" }
  },
  "segmentation": {
    "tumor_core_volume_mL": 14.7,
    "enhancing_tumor_volume_mL": 8.2,
    "edema_volume_mL": 42.3,
    "metabolic_tumor_volume_mL": 11.9,
    "mean_confidence": 0.89
  },
  "outputs": {
    "rt_structure_set": "fusion-results/study-047/RT_STRUCT.dcm",
    "registered_pet": "fusion-results/study-047/PET_registered/",
    "segmentation_nifti": "fusion-results/study-047/segmentation.nii.gz",
    "structured_report": "fusion-results/study-047/SR_measurements.dcm"
  },
  "processing_time_seconds": 187,
  "gpu_instance_type": "ml.g5.2xlarge"
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency (brain, rigid) | 2-5 minutes |
| End-to-end latency (abdomen, deformable) | 8-15 minutes |
| Registration accuracy (brain) | 0.5-1.5 mm target registration error |
| Registration accuracy (abdomen) | 2-5 mm target registration error |
| Segmentation Dice (brain tumor) | 0.82-0.91 (whole tumor) |
| Cost per study (brain) | ~$2.50 (GPU time dominates) |
| Cost per study (abdomen, deformable) | ~$5.00-8.00 |
| Throughput | ~30-50 studies/day per ml.g5.2xlarge |

**Where it struggles:** Non-rigid abdominal anatomy with large respiratory or bowel motion between scans. Studies with significant time gaps where tumor growth invalidates the registration assumption. Rare modality combinations not well-represented in training data. Edge cases where automated registration converges to a local minimum (producing obviously wrong but algorithmically "stable" alignments).

---

## Why This Isn't Production-Ready

**FDA regulatory pathway.** If this system's outputs influence clinical decisions (treatment planning contours, diagnostic segmentation), it likely requires FDA clearance as a Class II medical device. The 510(k) pathway requires demonstrated substantial equivalence to a predicate device, plus clinical validation studies. This recipe covers the technical architecture, not the regulatory journey, which adds 12-24 months and significant cost.

**Clinical validation.** Before any clinician uses AI-generated contours for treatment planning, the institution needs a validation study: compare AI contours against expert-drawn contours across a representative dataset, measure agreement metrics (Dice, Hausdorff distance), and establish that the AI output is within inter-observer variability. A cookbook recipe cannot substitute for this.

**DICOM conformance.** The DICOM standard for RT Structure Sets, SEG objects, and Structured Reports is complex. Subtle conformance errors (wrong referenced frame of reference, incorrect contour encoding) will cause treatment planning systems to reject or misinterpret the data. Production systems need rigorous DICOM conformance testing against target systems.

**Failure detection and graceful degradation.** Registration can silently fail: the algorithm reports convergence but the alignment is wrong. Production systems need automated quality checks (landmark verification, anatomical plausibility tests) and clear escalation paths when quality thresholds aren't met. The Step Functions workflow should never silently produce and deliver bad results.

---

## Variations and Extensions

**Intraoperative fusion for surgical navigation.** Register preoperative imaging (MRI, CT) to intraoperative views (ultrasound, stereoscopic camera) in near-real-time. The challenge intensifies because the anatomy deforms during surgery (brain shift, organ retraction). Requires sub-second update rates and tolerance for partial views. The architecture shifts from batch processing to streaming inference with SageMaker endpoints behind low-latency networking.

**Longitudinal fusion for treatment response assessment.** Rather than fusing modalities from a single time point, fuse the same modality across time points (baseline vs. post-treatment) to quantify change. Align baseline and follow-up scans, compute voxel-wise change maps, and classify regions as responding, stable, or progressing. Adds temporal registration challenges and needs RECIST/RANO response criteria implementation.

**Federated multi-modal model training.** Training fusion models requires multi-modal datasets that are rare and expensive to curate. Federated learning allows training across institutions without centralizing PHI. Each site trains on its local data and shares model weight updates. The architecture adds a federated aggregation server (potentially using SageMaker's built-in federated training capabilities or custom orchestration) while keeping imaging data at the source institution.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Processing Jobs](https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html)
- [Amazon SageMaker Real-time Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)

**External Resources:**
- [The Cancer Imaging Archive (TCIA)](https://www.cancerimagingarchive.net/): Public datasets for multi-modal medical imaging research
- [BraTS Challenge](https://www.synapse.org/brats): Brain tumor segmentation challenge with multi-modal MRI data
- [VoxelMorph](https://voxelmorph.net/): Deep learning framework for deformable medical image registration
- [MONAI (Medical Open Network for AI)](https://monai.io/): PyTorch-based framework for medical image analysis including registration and segmentation
- [DICOM Standard](https://www.dicomstandard.org/): Official DICOM specification for medical imaging interoperability

**AWS Solutions and Blogs:**
- [Medical Image Analysis on AWS](https://aws.amazon.com/solutions/implementations/medical-image-analysis-on-aws/): Reference architecture for medical imaging workloads on AWS

- [Build a medical image analysis pipeline on AWS](https://aws.amazon.com/blogs/machine-learning/): Blog posts covering SageMaker-based medical imaging pipelines

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 8-12 weeks | Rigid registration + alpha blending overlay for brain imaging. Manual QC. Limited modality support. |
| **Production-ready** | 6-9 months | Deformable registration, automated QC, multi-modality segmentation, DICOM-RT output, PACS integration, clinical validation study. |
| **With variations** | 12-18 months | Intraoperative navigation, longitudinal response tracking, federated training across institutions, FDA submission preparation. |

---

---

*← [Main Recipe 9.10](chapter09.10-multi-modal-imaging-fusion-analysis) · [Python Example](chapter09.10-python-example) · [Chapter Preface](chapter09-preface)*
