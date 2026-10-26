# TrafficShield M14.2.2 — Deterministic Feature-by-Feature Runtime Trace

**Document ID:** TS-M14-2-2-TRACE  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Side-by-side feature trace of deterministic PCAP replay sample (Flow 1 from `data/captures/sample_traffic.pcap`) comparing raw input, intermediate DataFrame, transformed array, and XGBoost booster attribution.

---

## 1. Trace Pipeline Description

The deterministic flow extracted from `data/captures/sample_traffic.pcap` has 5-tuple:
`10.x.x.x:54321 -> 192.168.x.x:443 / TCP` (6 packets, 240 wire bytes, duration = 0.20s).

The pipeline executes through:
1. `UnidirectionalFlowBuilder.finalize()` $\implies$ Raw Flow Dictionary.
2. `ProductionInferenceService.validate_and_prepare_input()` $\implies$ Policy-checked 13-feature DataFrame.
3. `TrafficShieldPreprocessor.transform_df()` / `transform()` $\implies$ Transformed $(1, 13)$ feature matrix aligned by `feature_names_out_`.
4. `OptunaTuned_XGBoost.predict_proba()` $\implies$ Prediction probability score.

---

## 2. Side-by-Side Feature-by-Feature Verification Table

The table below maps every feature by its **authoritative output column name and index** (`feature_names_out_`):

| Out Idx | Feature Name | Raw Value ($x$) | Center ($Q_{50}$) | Scale ($\text{IQR}$) | Exact Mathematical Calculation | Transformed Value ($z$) | Dtype |
|:---:|:---|:---:|:---:|:---:|:---|:---:|:---:|
| **0** | `duration_seconds` | `0.2` | `0.033008` | `0.573189` | $\frac{0.2 - 0.033008}{0.573189}$ | `0.291338` | `float64` |
| **1** | `fwd_bytes` | `240.0` | `1540.0` | `3210.0` | $\frac{240.0 - 1540.0}{3210.0}$ | `-0.404984` | `float64` |
| **2** | `sttl` | `64.0` | `31.0` | `1.0` | $\frac{64.0 - 31.0}{1.0}$ | `33.000000` | `float64` |
| **3** | `sload` | `7999.9981` | `505836.5625` | `821728.5234` | $\frac{7999.9981 - 505836.5625}{821728.5234}$ | `-0.605841` | `float64` |
| **4** | `fwd_packets` | `6.0` | `16.0` | `32.0` | $\frac{6.0 - 16.0}{32.0}$ | `-0.312500` | `float64` |
| **5** | `swin` | `65535.0` | `255.0` | `1.0` | $\frac{65535.0 - 255.0}{1.0}$ | `65280.000000` | `float64` |
| **6** | `smeansz` | `40.0` | `73.0` | `56.0` | $\frac{40.0 - 73.0}{56.0}$ | `-0.589286` | `float64` |
| **7** | `sjit` | `0.0` | `61.735433` | `1565.59807` | $\frac{0.0 - 61.735433}{1565.59807}$ | `-0.039432` | `float64` |
| **8** | `sintpkt` | `40.0` | `1.219467` | `23.842038` | $\frac{40.0 - 1.219467}{23.842038}$ | `1.626561` | `float64` |
| **9** | `packet_rate` | `30.0` | `856.026965` | `1923.41034` | $\frac{30.0 - 856.026965}{1923.41034}$ | `-0.429460` | `float64` |
| **10** | `byte_rate` | `1200.0` | `81382.4446` | `134532.2501` | $\frac{1200.0 - 81382.4446}{134532.2501}$ | `-0.596009` | `float64` |
| **11** | `bytes_per_packet`| `40.0` | `73.0` | `56.7357143` | $\frac{40.0 - 73.0}{56.7357143}$ | `-0.581644` | `float64` |
| **12** | `is_sm_ips_ports` | `0.0` | *N/A* | *N/A* | $\text{Identity: } x \to x$ | `0.000000` | `float64` |

---

## 3. Root-Cause Explanation of the `0.074747` Inconsistency

In `reports/m14_2_1_contract_reconciliation/runtime_inference_trace.md`, Section 2.4 presented:

```
Output Array:
Shape: (1, 13)
Values:
[[ 0.291338, -0.404984,  0.000000, -0.077977, -0.222222,  0.999985,
  -0.581644, -0.000000,  0.518712,  0.074747, -0.404984, -0.581644,
   0.000000 ]]
```

### The Discrepancy Explained:
1. **Report Transcription Erratum:** When the developer script executed `print('transformed values:\n', transformed)` in the previous session, Pandas formatted the output by displaying the first 2 columns and last 2 columns with middle columns truncated (`duration_seconds fwd_bytes ... bytes_per_packet is_sm_ips_ports`).
2. The report author manually reconstructed an array block for markdown documentation rather than printing the un-truncated array `transformed_arr[0]`. In doing so, estimated placeholder floats were transcribed for intermediate positions, including `0.074747` at position 9.
3. **Trace-Labeling / Index Confusion:** In the input schema (`REQUIRED_BASE_FEATURES` / `feature_names_in_`), `is_sm_ips_ports` was item #10 (0-indexed position 9). A reviewer comparing the input list with the transcribed array erroneously associated position 9 (`0.074747`) with `is_sm_ips_ports`.
4. **Physical Reality:**
   - As proven above, `is_sm_ips_ports` occupies **index 12** of the output array, and its actual value is **`0.000000`**.
   - Output position 9 is **`packet_rate`**, whose true transformed value is **`-0.429460`**.
   - The value `0.074747` was an erroneous transcription placeholder in the report text, **not an output of the preprocessor or any model component**.

---

## 4. End-to-End Prediction Verification

Passing the exact transformed matrix (with `is_sm_ips_ports = 0.0` at index 12) into `production_detector.joblib`:

- **Model:** `OptunaTuned_XGBoost` (`XGBClassifier`)
- **Evaluated Vector:** `[0.291338, -0.404984, 33.000000, -0.605841, -0.312500, 65280.000000, -0.589286, -0.039432, 1.626561, -0.429460, -0.596009, -0.581644, 0.000000]`
- **Probability Output ($P(\text{anomaly})$):** $\mathbf{0.368135}$
- **Decision Threshold:** $\tau = 0.50$
- **Classification:** **`is_anomaly = False`** (Risk Level: **`LOW`**)
- **Deterministic Repeatability:** 100 iterations of `predict_single(flow)` yield identical probability $0.368135$.
