# TrafficShield M10.1 — Evidence Provenance Audit: CICIDS2017 Transfer Discrepancy

**Audit Date:** 2026-10-23  
**Auditor:** TrafficShield Autonomous Evaluation & Verification Engine  
**Target Milestone:** Milestone 10 (Cross-Dataset Generalization & Robustness)  
**Classification:** DATA PROVENANCE INVESTIGATION & INTEGRITY AUDIT  

---

## 1. Executive Summary & Problem Statement

In Milestone 10 documentation, two conflicting statements appeared simultaneously:
1. **Dataset Physical Inventory:** Formally verified and documented that the CICIDS2017 dataset is **entirely absent locally** (`0 MB` across `datasets/raw/cicids2017/` and `datasets/interim/cicids2017/`). Native Track A baseline training on official raw data was explicitly designated as `NOT RUN (Dataset absent locally)`.
2. **Track B Evaluation Claims:** In `verified_model_metrics.csv` and `cross_dataset_results.md`, a zero-shot cross-dataset evaluation of 10,000 flows was presented under the dataset label **`"CICIDS2017 Stream"`**, reporting:
   - `HistGradientBoosting_ZeroShot`: Accuracy = 71.31%, Precision = 14.26%, Recall = 18.20%, Specificity = 80.68%, F1 = 15.99%, Confusion Matrix = `[6858, 1642, 1227, 273]`.
   - `RandomForest_ZeroShot`: Accuracy = 58.32%, Precision = 19.67%, Recall = 57.67%, Specificity = 58.44%, F1 = 29.33%, Confusion Matrix = `[4967, 3533, 635, 865]`.

This investigation independently traced the provenance of every single row in that 10,000-flow evaluation to determine whether it originated from authentic CICIDS2017 data, a cached artifact, a synthetic fixture, or an untraceable source.

---

## 2. Forensic Trace of the 10,000 Input Flows

### 2.1 Code Execution Trace

Inspection of `scripts/run_m10_cross_dataset.py` lines 308–348 reveals the exact execution sequence:

```python
# scripts/run_m10_cross_dataset.py:310-323
logger.info("--- Step 6: Track A: CICIDS2017 Ingestion & Baseline Verification ---")
cic_adapter = CICIDS2017Adapter(chunk_size=10_000)

# Generate verified synthetic CICIDS2017 fixture (10,000 flows) for reproducible offline validation
synthetic_cic_df = cic_adapter.generate_synthetic_cicids_dataframe(
    n_samples=10_000, anomaly_ratio=0.15, random_seed=42
)
temp_cic_file = out_dir / "synthetic_cicids2017_fixture.csv"
synthetic_cic_df.to_csv(temp_cic_file, index=False)

cic_feats, cic_lbls, cic_meta = cic_adapter.load_unidirectional_dataframe(
    filepaths=[temp_cic_file],
    max_rows=10_000,
    include_rates=True,
)
temp_cic_file.unlink()  # Clean temporary fixture
```

### 2.2 Algorithmic Provenance of the Input Rows

The 10,000 rows were generated programmatically in-memory by `CICIDS2017Adapter.generate_synthetic_cicids_dataframe()` in `ingestion/adapters/cicids2017.py` (lines 193–290):
- **Random Generator:** NumPy pseudo-random number generator initialized with `rng = np.random.default_rng(42)`.
- **Target Ratio:** `anomaly_ratio = 0.15` (15% attacks, 85% normal).
- **Exact Row Breakdown:**
  - `n_norm = 8,500` flows labeled `"BENIGN"`.
  - `n_anom = 1,500` flows total, consisting of 750 labeled `"DoS Hulk"` and 750 labeled `"PortScan"`.
  - Total records = `10,000`.
- **Statistical Generation Distributions:**
  - Normal durations: $X \sim \text{Exponential}(\mu = 500,000\,\mu\text{s})$.
  - Normal packet counts: $X \sim \text{Poisson}(\lambda = 8) + 1$.
  - Normal byte volumes: $\text{packets} \times \text{Uniform}(40, 1460)$.
  - Anomaly durations: $X \sim \text{Exponential}(\mu = 50,000\,\mu\text{s})$.
  - Anomaly packet counts: $X \sim \text{Poisson}(\lambda = 120) + 10$.
  - Anomaly byte volumes: $\text{packets} \times \text{Uniform}(200, 1500)$.
- **Lifecycle:** The resulting DataFrame was written to a temporary CSV file (`reports/m10_cross_dataset/synthetic_cicids2017_fixture.csv`), parsed through the adapter's chunked parser to test ingestion compliance, and immediately deleted from disk via `temp_cic_file.unlink()`.

### 2.3 Verification Against Reported Confusion Matrices

The class totals in the reported confusion matrices reflect this exact synthetic breakdown:
- For `HistGradientBoosting_ZeroShot`:
  - $\text{Actual Negatives} = \text{TN} + \text{FP} = 6858 + 1642 = 8,500$.
  - $\text{Actual Positives} = \text{FN} + \text{TP} = 1227 + 273 = 1,500$.
  - $\text{Total Flows} = 8,500 + 1,500 = 10,000$.
- For `RandomForest_ZeroShot`:
  - $\text{Actual Negatives} = \text{TN} + \text{FP} = 4967 + 3533 = 8,500$.
  - $\text{Actual Positives} = \text{FN} + \text{TP} = 635 + 865 = 1,500$.
  - $\text{Total Flows} = 8,500 + 1,500 = 10,000$.

---

## 3. Provenance Classification Checklist

| Source Candidate | Verified? | Evidence / Findings |
|:---|:---:|:---|
| **Authentic CICIDS2017 Raw Traffic** | **NO** | `datasets/raw/cicids2017/` is empty / absent (0 MB). No raw PCAP or CICFlowMeter files exist locally. |
| **Previously Cached Real-Data Artifact** | **NO** | No cached `.parquet`, `.joblib`, or `.feather` containing real CICIDS2017 flows exists in the workspace. |
| **Synthetic Fixture** | **YES** | Traced to `generate_synthetic_cicids_dataframe(n_samples=10_000, anomaly_ratio=0.15, random_seed=42)` in `ingestion/adapters/cicids2017.py`. |
| **Transformed / Sampled Real Dataset** | **NO** | Data was generated purely from parametric probability distributions (Poisson, Exponential, Uniform). |
| **Untraceable / Hallucinated Source** | **NO** | Provenance is 100% deterministic and reproducible via random seed 42. |

---

## 4. Audit Verdict & Mandated Status

> [!CAUTION]
> **AUDIT VERDICT: UNVERIFIED AS REAL CICIDS2017 GENERALIZATION.**
> 
> The evaluation was conducted on an artificial synthetic test fixture created for adapter unit testing. 
> Labeling this dataset `"CICIDS2017 Stream"` in `verified_model_metrics.csv` and `cross_dataset_results.md` inadvertently implied empirical zero-shot evaluation on real-world CICIDS2017 network traffic.
> 
> Under TrafficShield's scientific integrity standards:
> 1. The result is marked **UNVERIFIED** as a measure of cross-dataset generalization.
> 2. The dataset identifier must be corrected from `"CICIDS2017 Stream"` to **`"Synthetic CICIDS2017 Fixture (Offline Adapter Validation)"`**.
> 3. Historical documentation must explicitly state that true cross-dataset performance on real CICIDS2017 requires acquiring the official raw data files.
