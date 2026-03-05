# Category 9: Computer Vision / Medical Imaging

**Healthcare Use Cases — Simple → Complex**

---

## 9.1 Image Quality Assessment (Simple)

**What:** Automatically assess whether medical images (X-rays, photos, scans) meet quality thresholds before interpretation or storage.

**Why simple:** Binary/categorical outcome. Doesn't require clinical interpretation. Catches problems early in workflow. Training data from rejected images. Low-stakes rejection (just retake).

---

## 9.2 Patient Photo Verification (Simple)

**What:** Match patient photos to stored images for identity verification at check-in or telehealth sessions.

**Why simple:** Standard face recognition techniques. Not diagnosing anything. Errors caught by staff. Supports workflow efficiency and fraud prevention.

---

## 9.3 Wound Photography Measurement (Simple-Medium)

**What:** Measure wound dimensions (length, width, area) from standardized photographs for healing tracking.

**Why this complexity:** Requires reference marker for scale. Lighting and angle variations affect accuracy. Longitudinal tracking requires consistency. Supports nursing documentation.

---

## 9.4 Dermatology Lesion Triage (Medium)

**What:** Classify skin lesion photos as benign, suspicious, or urgent to prioritize dermatology referrals.

**Why medium:** Triage only, not diagnosis. FDA regulatory considerations. Must work across skin tones (bias risk). Supports access in underserved areas. Photo quality varies (patient-submitted).

---

## 9.5 Chest X-Ray Triage (Medium)

**What:** Flag chest X-rays with critical findings (pneumothorax, large effusion, cardiomegaly) for priority radiologist review.

**Why medium:** Worklist prioritization, not final diagnosis. Well-studied problem with public datasets. FDA-cleared products exist. Must integrate with PACS workflow.

---

## 9.6 Diabetic Retinopathy Screening (Medium-Complex)

**What:** Grade retinal images for diabetic retinopathy severity to identify patients needing ophthalmology referral.

**Why this complexity:** FDA-regulated diagnostic use. Must perform across camera types and image quality. Screening at scale in primary care. Grading scale is clinical standard.

---

## 9.7 Radiology AI Triage (Multi-Modality) (Complex)

**What:** Detect and flag critical findings across multiple imaging modalities (CT, MRI, X-ray) for radiologist prioritization.

**Why complex:** Each modality has different characteristics. Multiple finding types per modality. Must integrate with existing radiologist workflow. FDA regulatory pathway per indication.

---

## 9.8 Pathology Slide Analysis (Complex)

**What:** Assist pathologists in analyzing digitized tissue slides — identifying regions of interest, quantifying features, suggesting diagnoses.

**Why complex:** Gigapixel images. Subtle morphological distinctions. Pathologist workflow integration critical. Multiple cancer types and grading systems. High-stakes diagnostic support.

---

## 9.9 Surgical Video Analysis (Complex)

**What:** Analyze intraoperative video for phase recognition, tool detection, anatomy identification, or complication prediction.

**Why complex:** Real-time processing requirements. Occlusion and artifacts common. Must handle surgical variation. Research-stage for most applications. OR integration challenges.

---

## 9.10 Multi-Modal Imaging Fusion and Analysis (Complex)

**What:** Combine multiple imaging modalities (e.g., PET-CT, MRI + ultrasound) for integrated interpretation and treatment planning.

**Why complex:** Registration across modalities. Different spatial/temporal resolutions. Requires specialty-specific clinical knowledge. Treatment planning integration. Radiation oncology, surgical planning use cases.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Regulatory pathway | FDA clearance adds time/cost |
| Diagnostic vs. triage | Diagnosis has higher bar |
| Workflow integration | PACS/RIS integration is work |
| Image characteristics | Modality-specific challenges |
| Bias/equity | Must work across populations |
| Real-time requirements | OR/procedure use adds latency constraints |

---

*Category 9 complete. Next: Category 10 (Speech / Voice AI)*
