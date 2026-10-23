# TrafficShield M10.1 — Feature Count Reconciliation & Observability Audit

**Audit Date:** 2026-10-23  
**Auditor:** TrafficShield Autonomous Evaluation & Verification Engine  
**Milestone:** Milestone 10.1  
**Classification:** FEATURE POLICY & SCHEMA AUDIT  

---

## 1. Executive Summary

This audit reconciles all numerical discrepancies regarding feature accounting between the M10 report claims and the underlying codebase:
1. **The Claimed 24 Eligible CICIDS2017 Features:** Exactly reconciled as **20 raw forward-observable features** from `CICIDS_2017_SPECS` plus **4 derived rate/ratio features** generated during adapter loading.
2. **The Claimed "79+ Column Policy":** Reconciled. The codebase dictionary `CICIDS_2017_SPECS` contains **exactly 58 explicitly mapped specifications**. The reference to "79+" reflects the total columns in official raw CICFlowMeter CSV exports; unmapped columns are safely handled by programmatic fail-safe keyword rejections.
3. **The 107-Feature Compatibility Matrix:** Reconciled as exactly **49 UNSW-NB15 feature specifications** plus **58 CICIDS2017 feature specifications** ($49 + 58 = 107$ rows).
4. **Prohibition Integrity:** Formally verified that zero reverse-direction, bidirectional, label-derived, or future-dependent features can enter the model feature matrix.

---

## 2. Reconciliation of the 24 Eligible Features

When `CICIDS2017Adapter.load_unidirectional_dataframe(..., include_rates=True)` processes input records, it produces a feature matrix with **exactly 24 columns**:

### 2.1 The 20 Raw Forward-Observable Features (from `CICIDS_2017_SPECS`)

All 20 raw features satisfy `directionality == FORWARD_OBSERVABLE` and `field_role == FieldRole.FEATURE`:

| # | Raw CSV Column Name | Normalized Feature Name | Data Type | Timing | Physical Meaning |
|:---:|:---|:---|:---:|:---:|:---|
| 1 | `Flow Duration` | `duration_microseconds` | Numeric | Flow Completion | Duration of flow in microseconds |
| 2 | `Total Fwd Packets` | `fwd_packets` | Integer | Flow Completion | Total packets in forward direction |
| 3 | `Total Length of Fwd Packets` | `fwd_bytes` | Integer | Flow Completion | Total payload/packet bytes in forward direction |
| 4 | `Fwd Packet Length Max` | `fwd_pkt_len_max` | Numeric | Flow Completion | Maximum forward packet size |
| 5 | `Fwd Packet Length Min` | `fwd_pkt_len_min` | Numeric | Flow Completion | Minimum forward packet size |
| 6 | `Fwd Packet Length Mean` | `fwd_pkt_len_mean` | Numeric | Flow Completion | Mean forward packet size |
| 7 | `Fwd Packet Length Std` | `fwd_pkt_len_std` | Numeric | Flow Completion | Standard deviation of forward packet size |
| 8 | `Fwd IAT Total` | `fwd_iat_total` | Numeric | Flow Completion | Total time between forward packets |
| 9 | `Fwd IAT Mean` | `fwd_iat_mean` | Numeric | Flow Completion | Mean forward inter-arrival time |
| 10 | `Fwd IAT Std` | `fwd_iat_std` | Numeric | Flow Completion | Standard deviation of forward inter-arrival time |
| 11 | `Fwd IAT Max` | `fwd_iat_max` | Numeric | Flow Completion | Maximum forward inter-arrival time |
| 12 | `Fwd IAT Min` | `fwd_iat_min` | Numeric | Flow Completion | Minimum forward inter-arrival time |
| 13 | `Fwd PSH Flags` | `fwd_psh_flags` | Integer | Flow Completion | Cumulative PSH flags in forward direction |
| 14 | `Fwd URG Flags` | `fwd_urg_flags` | Integer | Flow Completion | Cumulative URG flags in forward direction |
| 15 | `Fwd Header Length` | `fwd_header_len` | Integer | Flow Completion | Forward IP/transport header byte total |
| 16 | `Fwd Packets/s` | `fwd_packets_per_sec` | Numeric | Flow Completion | Packets per second forward |
| 17 | `Avg Fwd Segment Size` | `avg_fwd_segment_size` | Numeric | Flow Completion | Mean segment size observed forward |
| 18 | `Init_Win_bytes_forward` | `init_win_bytes_forward` | Integer | Flow Prefix | TCP advertised window in initial forward SYN |
| 19 | `act_data_pkt_fwd` | `act_data_pkt_fwd` | Integer | Flow Completion | Forward packets containing at least 1 byte payload |
| 20 | `min_seg_size_forward` | `min_seg_size_forward` | Integer | Flow Prefix | Minimum segment size in forward direction |

*Note on Destination Port:* `Destination Port` is classified as `FORWARD_OBSERVABLE` but has `field_role == FieldRole.IDENTIFIER`. It is stripped from the model feature matrix and preserved in `meta_df["dst_port"]`.

### 2.2 The 4 Derived Forward-Observable Features (when `include_rates=True`)

To align with standard TrafficShield volumetric representations and enable cross-dataset subspace mapping, the adapter computes 4 derived columns:

| # | Derived Feature Name | Calculation Formula | Physical Meaning |
|:---:|:---|:---|:---|
| 21 | `duration_seconds` | `duration_microseconds / 1,000,000.0` | Flow duration in standard SI seconds |
| 22 | `packet_rate` | $\text{fwd\_packets} / \text{duration\_seconds}$ (or $0.0$ if $\text{dur} \le 0$) | Forward packet rate (packets/sec) |
| 23 | `byte_rate` | $\text{fwd\_bytes} / \text{duration\_seconds}$ (or $0.0$ if $\text{dur} \le 0$) | Forward byte throughput (bytes/sec) |
| 24 | `bytes_per_packet` | $\text{fwd\_bytes} / \text{fwd\_packets}$ (or $0.0$ if $\text{pkts} \le 0$) | Average observed forward packet size |

**Total:** $20 \text{ raw features} + 4 \text{ derived features} = 24 \text{ eligible features}$.

---

## 3. Reconciliation of "79-Column Policy" vs 58 Explicit Specs

In `ingestion/adapters/cicids2017_policy.py`, the module docstring mentions:
> *"Defines explicit, auditable directional classifications and availability timings for all 79+ fields produced by the CICFlowMeter tool on the CICIDS2017 dataset."*

### 3.1 Actual Count in `CICIDS_2017_SPECS`
Direct programmatic inspection shows `len(CICIDS_2017_SPECS) == 58`.

The 58 specifications are categorized as:
- **`forward_observable`:** 21 (20 features + 1 identifier)
- **`reverse_direction`:** 18 (e.g. `Total Backward Packets`, `Total Length of Bwd Packets`, `Bwd Packet Length Mean`, `Bwd IAT Mean`, `Init_Win_bytes_backward`)
- **`bidirectional_or_future_dependent`:** 18 (e.g. `Flow Bytes/s`, `Flow Packets/s`, `Flow IAT Mean`, `Packet Length Mean`, `SYN Flag Count`, `ACK Flag Count`, `Average Packet Size`)
- **`evaluation_label`:** 1 (`Label`)
- **Total:** $21 + 18 + 18 + 1 = 58$.

### 3.2 Where are the Remaining 21+ Columns?
Official CICIDS2017 CSV files exported from CICFlowMeter have between 79 and 85 columns depending on the day. The ~21 unmapped columns fall into three groups:
1. **Connection 5-Tuple Metadata (5 columns):** `Flow ID`, `Source IP`, `Source Port`, `Destination IP`, `Timestamp`.
2. **Subflow Volumetric Aggregates (4 columns):** `Subflow Fwd Packets`, `Subflow Fwd Bytes`, `Subflow Bwd Packets`, `Subflow Bwd Bytes`.
3. **Active/Idle Session Timers (8 columns):** `Active Mean`, `Active Std`, `Active Max`, `Active Min`, `Idle Mean`, `Idle Std`, `Idle Max`, `Idle Min`.
4. **Additional Transport Flags (4 columns):** `CWE Flag Count`, `ECE Flag Count`, `Fwd Avg Bytes/Bulk`, `Fwd Avg Packets/Bulk`.

### 3.3 Fail-Safe Guardrail Implementation
To ensure unmapped columns cannot bypass the policy, `audit_cicids2017_columns()` (lines 823–832) implements strict keyword fail-safe filtering:
```python
spec = CICIDS_2017_SPECS.get(raw_col)
if spec is None:
    if "bwd" in raw_col.lower() or "backward" in raw_col.lower():
        forbidden_found.append(raw_col)
    elif "label" in raw_col.lower():
        labels_found.append(raw_col)
    else:
        unknown_found.append(raw_col)  # Excluded from feature matrix
```
**Conclusion:** Any column not among the 58 explicit specifications is automatically excluded. However, the docstring and report claim of "79+ explicit specifications" was imprecise and must be corrected to **"58 explicitly mapped specifications with automated fail-safe rejection for unmapped columns"**.

---

## 4. Reconciliation of the 107-Feature Compatibility Matrix

The file `reports/m10_cross_dataset/feature_compatibility_matrix.csv` contains **exactly 107 rows**:

$$49 \text{ UNSW-NB15 specifications} + 58 \text{ CICIDS2017 specifications} = 107 \text{ total rows audited}$$

### Detailed Breakdown by Dataset and Status:

| Dataset | Status in Matrix | Count | Rationale / Explanation |
|:---|:---|:---:|:---|
| **CICIDS2017** | `ACCEPTED` | 20 | Forward-observable raw features with `FieldRole.FEATURE` |
| | `REJECTED_REVERSE` | 18 | Backward packets, backward bytes, Bwd IAT, return windows |
| | `REJECTED_BIDIRECTIONAL` | 18 | Bidirectional flow rates, bidirectional IAT, symmetric packet length stats |
| | `EXCLUDED_METADATA` | 1 | `Destination Port` (identifier, not input feature) |
| | `REJECTED_LABEL` | 1 | `Label` (ground truth attack target) |
| **CICIDS2017 Subtotal** | | **58** | **Exactly matches `len(CICIDS_2017_SPECS)`** |
| **UNSW-NB15** | `ACCEPTED` | 19 | Forward-observable raw features (`sbytes`, `dur`, `spkts`, `sttl`, etc.) |
| | `REJECTED_REVERSE` | 13 | Backward bytes (`dbytes`), backward packets (`dpkts`), `dttl`, `dload`, etc. |
| | `REJECTED_BIDIRECTIONAL` | 6 | Bidirectional state/ratio metrics (`tcprtt`, `synack`, `ackdat`, etc.) |
| | `EXCLUDED_IDENTIFIER` | 9 | `srcip`, `dstip`, `sport`, `dsport`, `proto`, `state`, timestamps |
| | `REJECTED_LABEL` | 2 | `label`, `attack_cat` |
| **UNSW-NB15 Subtotal** | | **49** | **Exactly matches `len(UNSW_NB15_SPECS)`** |
| **Grand Total** | | **107** | **Complete two-dataset unidirectional audit** |

---

## 5. Verification of Prohibition Rules

Every column classified as reverse-direction, bidirectional, or label-derived was audited against `get_eligible_cicids_model_features()` and `CICIDS2017Adapter.load_unidirectional_dataframe()`:
- **Zero reverse-direction columns** enter the eligible feature list.
- **Zero bidirectional rates or flags** enter the eligible feature list.
- **Zero labels** (`Label`, `attack_cat`, `label`) enter the feature matrix.
- `Destination Port` is stripped from features and isolated in metadata.

**Observability Integrity Status: VERIFIED AND INTACT.**
