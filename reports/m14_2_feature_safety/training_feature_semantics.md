# TrafficShield M14.2 — Training-Time Feature Semantics & Input Contract

**Milestone:** M14.2 — Feature Fidelity and Malformed-Packet Safety Gate  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED & MATHEMATICALLY CONFORMANT**  

---

## 1. Executive Summary

This report establishes the training-time feature semantics, mathematical definitions, units, and preprocessing transformations for all 13 features expected by TrafficShield's frozen production detector (`OptunaTuned_XGBoost`).

To ensure strict zero-leakage compliance, the model input contract was traced back to the original UNSW-NB15 dataset generation tools (Argus and Bro-IDS), the dataset adapter [`ingestion/adapters/unsw_nb15.py`](file:///D:/projects/trafficshield/ingestion/adapters/unsw_nb15.py), the directional feature policy [`ingestion/adapters/unsw_nb15_policy.py`](file:///D:/projects/trafficshield/ingestion/adapters/unsw_nb15_policy.py), and the preprocessing pipeline [`preprocessing/pipeline.py`](file:///D:/projects/trafficshield/preprocessing/pipeline.py).

---

## 2. Production Artifact Hashes & Immutability

The production model and preprocessor artifacts remain cryptographically untouched:

| Artifact | Path | SHA-256 Hash | Status |
| :--- | :--- | :--- | :---: |
| **Production Model** | `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **FROZEN / UNMODIFIED** |
| **Production Preprocessor** | `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **FROZEN / UNMODIFIED** |
| **Model Metadata** | `artifacts/models/production_detector.json` | `OptunaTuned_XGBoost` v1.0.0 (Threshold $\tau = 0.50$) | **VERIFIED** |

---

## 3. Comprehensive 13-Feature Contract Trace

The 13-feature contract consists of 10 base forward features and 3 derived rate features:

### 3.1 Base Forward Features (10)

1. **`duration_seconds` (`dur` in UNSW-NB15):**
   - *Source Definition:* Total record duration in seconds.
   - *Units:* Seconds (float).
   - *Training Value Range:* $[0.0, 59.999]$.
   - *Live Computation:* $\max(0.0, t_{\text{last}} - t_{\text{first}})$. For single-packet flows or simultaneous arrivals, $\text{duration} = 0.0$.
2. **`fwd_bytes` (`sbytes` in UNSW-NB15):**
   - *Source Definition:* Cumulative source-to-destination transaction bytes extracted by Argus from IPv4 Total Length (`ip.len`). Excludes Layer 2 Ethernet headers.
   - *Units:* Bytes (integer $\ge 20$).
   - *Live Computation:* $\sum \text{packet.byte\_length}$ (where `byte_length` is the verified 16-bit IPv4 Total Length).
3. **`sttl` (`sttl` in UNSW-NB15):**
   - *Source Definition:* Source-to-destination Time-to-Live header byte observed at the monitor.
   - *Units:* Discrete integer ($1 \le \text{TTL} \le 255$).
   - *Missing/Invalid Policy:* **Zero silent imputation.** If `sttl` is missing or $\le 0$, the flow is flagged as `is_compatible = False` (`INVALID_OR_MISSING_STTL`) and rejected from inference.
4. **`sload` (`Sload` in UNSW-NB15):**
   - *Source Definition:* Source bits per second computed by Argus across the $N-1$ packet inter-arrival intervals:
     $$\text{Sload} = \frac{(\text{Spkts} - 1) \times \text{smeansz} \times 8.0}{\text{dur}} \quad (\text{for } \text{dur} > 0, \text{Spkts} > 1)$$
     For single-packet flows ($N=1$) or $\text{dur}=0$, $\text{Sload} = 0.0$.
   - *Live Computation:* Aligned to Argus formula in [`ingestion/flow/flow_builder.py`](file:///D:/projects/trafficshield/ingestion/flow/flow_builder.py#L75).
5. **`fwd_packets` (`Spkts` in UNSW-NB15):**
   - *Source Definition:* Forward packet count.
   - *Units:* Integer ($\ge 1$).
   - *Live Computation:* Incremented by 1 for each validated forward packet envelope.
6. **`swin` (`swin` in UNSW-NB15):**
   - *Source Definition:* Source TCP window advertisement value.
   - *Units:* Discrete integer ($0 \le \text{window} \le 65535$).
   - *Live Computation:* TCP header window field. Defaults strictly to `0` for UDP, ICMP, and unadvertised TCP.
7. **`smeansz` (`smeansz` in UNSW-NB15):**
   - *Source Definition:* Mean forward packet size ($\text{sbytes} / \text{Spkts}$).
   - *Units:* Bytes (float).
   - *Live Computation:* `fwd_bytes / fwd_packets`.
8. **`sjit` (`Sjit` in UNSW-NB15):**
   - *Source Definition:* Source packet inter-arrival jitter in milliseconds. For $N \le 2$, $\text{Sjit} = 0.0$.
   - *Units:* Milliseconds (float $\ge 0.0$).
   - *Live Computation:* RFC 3550 exponential moving average ($J_i = J_{i-1} + (|D| - J_{i-1})/16$). Requires $N \ge 3$ packets.
9. **`sintpkt` (`Sintpkt` in UNSW-NB15):**
   - *Source Definition:* Mean inter-packet arrival time in milliseconds ($\text{dur} \times 1000.0 / (\text{Spkts} - 1)$).
   - *Units:* Milliseconds (float $\ge 0.0$). For $N \le 1$, $\text{Sintpkt} = 0.0$.
   - *Live Computation:* `(duration * 1000.0) / (pkts - 1)` if `pkts > 1` else `0.0`.
10. **`is_sm_ips_ports` (`is_sm_ips_ports` in UNSW-NB15):**
    - *Source Definition:* Binary Land attack indicator: 1 if source IP equals destination IP and source port equals destination port, else 0.
    - *Units:* Binary integer (0 or 1).
    - *Live Computation:* `1 if (src_ip == dst_ip and src_port == dst_port) else 0`.

### 3.2 Causal Derived Rates (3)

11. **`packet_rate`:** $\text{fwd\_packets} / \text{duration}$ (packets/sec). Clamped to `0.0` if $\text{duration} = 0.0$.
12. **`byte_rate`:** $\text{fwd\_bytes} / \text{duration}$ (bytes/sec). Clamped to `0.0` if $\text{duration} = 0.0$.
13. **`bytes_per_packet`:** $\text{fwd\_bytes} / \text{fwd\_packets}$ (bytes/pkt). Identical to `smeansz`.

---

## 4. Preprocessing & Scaler Contract

The frozen preprocessor `artifacts/models/production_preprocessor.joblib`:
- **Scaler:** `sklearn.preprocessing.RobustScaler` fitted strictly on training partition (Day 1).
- **Transformation:** Computes $(x - \text{median}) / \text{IQR}$ across the 12 numeric features.
- **Categorical / Boolean Handling:** `is_sm_ips_ports` passes through as an unscaled binary feature.
- **Strict Directional Guard:** Rejects any input containing reverse-link columns (`bwd_*`, `dload`, `dbytes`) with `PolicyViolationError`.

---

## 5. Incompatible Flow Handling Policy

If a flow violates the mathematical prerequisites of the training contract:
1. Missing or non-positive TTL ($\text{sttl} \le 0$).
2. Missing 5-tuple coordinates.
3. Negative duration or packet counts.

The flow is marked `is_compatible = False` by [`ActiveFlowState.finalize()`](file:///D:/projects/trafficshield/ingestion/flow/flow_builder.py).
In [`streaming/inference_worker.py`](file:///D:/projects/trafficshield/streaming/inference_worker.py), incompatible flows are dropped before calling the model, incrementing `incompatible_flows_rejected`.
**Zero incompatible flows are evaluated by the production model or persisted as alerts.**
