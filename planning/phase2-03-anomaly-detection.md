# Category 3: Anomaly Detection

**Healthcare Use Cases — Simple → Complex**

---

## 3.1 Duplicate Claim Detection (Simple)

**What:** Flag claims that appear to be duplicates based on patient, provider, service date, and procedure codes.

**Why simple:** Well-defined rules with ML enhancement for fuzzy matching. Low false-positive cost (just triggers review). Historical data abundant. Batch processing acceptable.

---

## 3.2 Patient No-Show Pattern Detection (Simple)

**What:** Identify patients with unusual no-show patterns that deviate from their historical behavior or population norms.

**Why simple:** Clear outcome metric (showed vs. didn't). Low-stakes intervention (reminder call). Patterns relatively stable. Well-understood features.

---

## 3.3 Billing Code Anomalies (Simple-Medium)

**What:** Detect unusual billing patterns — codes rarely used by a provider, unlikely code combinations, or charges outside typical ranges.

**Why this complexity:** Requires provider-specific baselines. Must balance sensitivity (catch fraud) with specificity (avoid harassment of legitimate variation). Some patterns are rare but valid.

---

## 3.4 Medication Dispensing Anomalies (Medium)

**What:** Flag unusual medication dispensing events — wrong dose for patient weight, unusual frequency, controlled substance patterns.

**Why medium:** Patient safety implications. Must account for legitimate clinical variation. Real-time alerting preferred but adds complexity. Integration with pharmacy systems required.

---

## 3.5 Lab Result Outlier Detection (Medium)

**What:** Identify lab results that are statistical outliers for a patient's history or clinically implausible, suggesting collection or processing errors.

**Why medium:** Must understand patient-specific baselines. Some outliers are clinically real (acute events). Delta checks and critical value rules interact. Impacts clinical workflow.

---

## 3.6 Healthcare Fraud/Waste/Abuse Detection (Medium-Complex)

**What:** Identify providers, facilities, or patients exhibiting patterns consistent with fraud (upcoding, unbundling, phantom billing, kickbacks).

**Why this complexity:** Adversarial environment — bad actors adapt. Requires sophisticated behavioral baselines. False positives have legal/reputational consequences. Investigation workflows needed.

---

## 3.7 Patient Deterioration Early Warning (Complex)

**What:** Detect subtle patterns in vitals, labs, and nursing notes that precede clinical deterioration (sepsis, respiratory failure, cardiac events).

**Why complex:** Time-critical — minutes matter. Must minimize both false positives (alert fatigue) and false negatives (missed events). Multi-signal integration. ICU vs. floor have different baselines. Requires clinical workflow integration for response.

---

## 3.8 Readmission Risk Anomaly Detection (Complex)

**What:** Identify patients whose post-discharge trajectory deviates from expected recovery patterns, suggesting elevated readmission risk.

**Why complex:** Requires continuous monitoring (RPM, patient-reported data). Baseline establishment is patient-specific. Intervention resources are limited — must prioritize. Causality vs. correlation challenges.

---

## 3.9 Cybersecurity / Access Pattern Anomalies (Complex)

**What:** Detect unusual EHR access patterns that may indicate insider threats, compromised credentials, or privacy breaches.

**Why complex:** High-dimensional behavior space. Must distinguish malicious from unusual-but-legitimate. Real-time detection needed. False positives disrupt clinical work. HIPAA breach implications.

---

## 3.10 Epidemic / Outbreak Detection (Complex)

**What:** Identify emerging disease clusters or unusual syndrome patterns in population data before official recognition.

**Why complex:** Signal-to-noise ratio is low. Must distinguish outbreaks from seasonal variation. Geographic and demographic confounders. Public health coordination required. Time-sensitive but high false-positive cost.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Time criticality | Real-time needs add latency constraints |
| Alert fatigue potential | High FP rate = ignored alerts |
| Adversarial environment | Fraudsters adapt to detection |
| Baseline establishment | Patient-specific baselines are harder |
| Intervention resources | Must prioritize when capacity limited |
| Regulatory/legal exposure | FP in fraud detection has consequences |

---

*Category 3 complete. Next: Category 4 (Personalization / Recommendation)*
