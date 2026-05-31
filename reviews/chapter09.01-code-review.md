# Code Review: Recipe 9.1 - Image Quality Assessment

**Reviewed:** `chapter09.01-python-example.md`
**Against:** `chapter09.01-image-quality-assessment.md`
**Severity levels:** ERROR (code won't work), WARNING (misleading), NOTE (improvement)

---

## Verdict: PASS

The Python companion is well-structured, pedagogically sound, and faithfully implements all 5 pseudocode steps from the main recipe. The code would run correctly given the stated prerequisites (a deployed SageMaker endpoint and properly configured AWS resources). DynamoDB uses Decimal correctly. S3 paths have no leading slashes. boto3 API calls use correct method names and parameter structures.

---

## Findings

### WARNING 1: Laplacian convolution loop is O(n^2) and will be extremely slow on 512x512 images

**Location:** `compute_laplacian_variance()`, the nested for-loop convolution

The manual nested loop convolution over a 512x512 image (262,144 iterations, each doing a 3x3 multiply-and-sum) will take several seconds in pure Python/numpy with per-element indexing. While the code explicitly notes this is for clarity and points to `cv2.Laplacian` for production, a learner copying this code will experience painfully slow execution that might make them think the approach is fundamentally slow.

**Fix:** Consider using `scipy.ndimage.convolve` or `np.correlate2d` as a middle ground that's still pure-Python-ecosystem but runs in compiled C under the hood. Or add a comment with an explicit timing warning: "This loop takes ~5-10 seconds on a 512x512 image. Production uses cv2.Laplacian which runs in milliseconds."

---

### WARNING 2: SNS `Message` field sends JSON with float, not Decimal

**Location:** `store_and_alert()`, the `sns_client.publish()` call

The `alert_message` dict includes `"score": decision_result["overall_score"]` which is a Python float. While SNS `Message` is a string (via `json.dumps`) so this won't error, it's inconsistent with the careful Decimal handling for DynamoDB in the same function. A learner might wonder why floats are OK here but not for DynamoDB.

**Fix:** Add a brief comment explaining: "SNS Message is a JSON string, so floats are fine here. DynamoDB's resource layer requires Decimal for numeric attributes specifically."

---

### NOTE 1: The `__main__` block S3 key includes the bucket name as a prefix

**Location:** Bottom of the file, `assess_image_quality()` call

```python
key="imaging-inbox/2026/03/15/study-00891.dcm",
```

The key starts with `imaging-inbox/` which is also the bucket name. This is technically valid (S3 keys can contain anything), but a learner might think the key must repeat the bucket name. The main recipe's expected results section shows the same pattern (`"source_key": "imaging-inbox/2026/03/15/study-00891.dcm"`), so this is consistent with the recipe. Just noting it could confuse someone new to S3's bucket/key model.

**Fix:** No change required for consistency with the main recipe. Optionally change to `key="studies/2026/03/15/study-00891.dcm"` to avoid the appearance of bucket-name repetition.

---

### NOTE 2: `np.random.seed(hash(key) % (2**32))` for reproducible simulation

**Location:** `receive_image()`, synthetic image generation

Using `hash()` is not deterministic across Python sessions (Python randomizes hash seeds by default since 3.3). The simulated image will differ between runs unless `PYTHONHASHSEED` is set. This doesn't affect correctness for a teaching example, but a learner running the code twice might get different quality scores.

**Fix:** Consider using a fixed seed or `hashlib.md5(key.encode()).hexdigest()[:8]` converted to int for cross-session reproducibility. Or add a comment noting the non-determinism.

---

### NOTE 3: Good use of Decimal for DynamoDB

**Location:** `store_and_alert()`, the `record` dict construction

The code correctly wraps all numeric values in `Decimal(str(round(value, 4)))` and the "Gap to Production" section explicitly calls out this requirement. This is a common boto3 pitfall handled well.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Python Implementation | Match? |
|----------------|----------------------|--------|
| Step 1: `receive_image(bucket, key)` | `receive_image()` downloads from S3, simulates DICOM parsing | Yes |
| Step 2: `compute_basic_metrics(pixel_array)` | `compute_basic_metrics()` computes blur, exposure, noise, sanity checks | Yes |
| Step 3: `assess_quality_ml(pixel_array, basic_metrics, modality)` | `assess_quality_ml()` invokes SageMaker endpoint | Yes |
| Step 4: `apply_decision(quality_result, modality, body_part)` | `apply_decision()` applies three-tier thresholds | Yes |
| Step 5: `store_and_alert(image_info, decision_result)` | `store_and_alert()` writes DynamoDB + publishes SNS | Yes |
| Fast-reject logic (blank/saturated/blur) | Present in `assess_image_quality()` orchestrator | Yes |

The Python adds a fast-reject path for severe blur (score < BLUR_THRESHOLD) that assigns a hardcoded 0.2 overall score. The pseudocode doesn't explicitly show this path, but the main recipe's prose describes it ("Rule-based checks catch the obvious failures fast... before you spend compute on ML inference"). This is a reasonable pedagogical addition that demonstrates the concept described in the recipe text.

---

## boto3 API Accuracy

| API Call | Method | Parameters | Response Parsing | Correct? |
|----------|--------|------------|-----------------|----------|
| S3 GetObject | `s3_client.get_object(Bucket=, Key=)` | Correct params | `response["Body"].read()` | Yes |
| SageMaker InvokeEndpoint | `sagemaker_runtime.invoke_endpoint(EndpointName=, ContentType=, Body=)` | Correct params | `response["Body"].read().decode()` | Yes |
| DynamoDB PutItem | `table.put_item(Item=)` | Correct (resource layer) | N/A | Yes |
| SNS Publish | `sns_client.publish(TopicArn=, Subject=, Message=)` | Correct params | N/A | Yes |

All boto3 calls use current, correct method names and parameter structures.

---

## Summary

Strong Python companion that faithfully translates the recipe's pseudocode into working code. Comments are generous and explain the "why" effectively. The logical flow builds understanding progressively. The "Gap to Production" section is thorough and honest about limitations. The two warnings are minor pedagogical concerns, not correctness issues.

---

*Reviewed 2026-05-31*
