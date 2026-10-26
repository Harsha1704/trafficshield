# TrafficShield — Detection Pipeline, Model Contract & Drift Analysis Audit

**Milestone:** Master Completion Mission — Phase 5  
**Date:** 2026-10-26  
**Repository:** `D:\projects\trafficshield`  
**Model Architecture:** OptunaTuned_XGBoost + RobustScaler Preprocessor  
**Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`**

---

## 1. Frozen Model Contract & Feature Equivalence

### 1.1 Strict 13-Feature Schema Contract

The frozen production detector (`artifacts/models/production_detector.joblib`) and preprocessor (`artifacts/models/production_preprocessor.joblib`) operate on an immutable, ordered contract of exactly 13 forward features:

| Index | Feature Name | Semantic Definition | Expected Type | RobustScaler Handling |
| :---: | :--- | :--- | :---: | :--- |
| 1 | `dur` | Unidirectional flow duration in seconds | `float` | Median-centered, IQR-scaled |
| 2 | `sbytes` | Total forward bytes transmitted | `int` / `float` | Median-centered, IQR-scaled |
| 3 | `sttl` | Source-to-destination time-to-live | `int` | Scaled; key discriminant |
| 4 | `sload` | Source bits per second (flow rate) | `float` | Log-transformed / scaled |
| 5 | `Spkts` | Total forward packet count | `int` / `float` | Median-centered, IQR-scaled |
| 6 | `swin` | TCP advertised window advertisement | `int` | Scaled |
| 7 | `smeansz` | Mean forward packet size in bytes | `float` | Scaled |
| 8 | `sjit` | Source packet jitter in milliseconds | `float` | Scaled |
| 9 | `sintpkt` | Source inter-packet arrival time (ms) | `float` | Scaled |
| 10 | `is_sm_ips_ports` | Identical source/destination IP & port | `int` (0/1) | Binary indicator |
| 11 | `packet_rate` | Packets per second across flow duration | `float` | Real-time computed |
| 12 | `byte_rate` | Bytes per second across flow duration | `float` | Real-time computed |
| 13 | `bytes_per_packet` | Average payload size per packet | `float` | Real-time computed |

### 1.2 Cryptographic Integrity & Tamper Guard
- **Detector SHA-256:** `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
- **Preprocessor SHA-256:** `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`
- **Gate Decision Threshold:** `0.50` (Strictly frozen; zero tuning permitted during local qualification).
- **Integrity Enforcement:** [`ProductionInferenceService`](file:///d:/projects/trafficshield/ml/production_service.py) re-computes SHA-256 hashes during component instantiation. Any hash divergence triggers an immediate `IntegrityError`, halting model loading.

---

## 2. Investigation of High Anomaly Rates in Live Wi-Fi Testing

During initial M15 passive live Wi-Fi capture experiments, an anomaly rate of approximately 64.5% (431 of 668 scored flows flagged as anomalous at threshold 0.50) was reported.

### 2.1 Domain Shift & TTL Distribution Hypothesis
1. **Training Baseline Context (UNSW-NB15):**
   - The detector was trained and calibrated on synthetic testbed partitions of the UNSW-NB15 dataset.
   - In UNSW-NB15 benign flows, the source TTL (`sttl`) distribution clusters heavily around specific operating system default baselines (e.g. Linux 64, Windows 128, Network devices 254) with minimal hop variance.
2. **Operational Wi-Fi Environment Characteristics:**
   - In consumer or enterprise 802.11 Wi-Fi networks, observed packets arrive from heterogeneous client devices (iOS, Android, Windows, IoT) traversing complex NAT, VPN, and multiple WAN routing hops.
   - Live source TTLs frequently exhibit values like 53, 56, 114, 118, or 240, reflecting Internet transit hops.
   - Additionally, background operating system telemetry, cloud sync services, and WebRTC streaming generate bursty, single-packet flows with atypical `sload` and `sintpkt` profiles.
3. **Model Response to Out-of-Distribution Data:**
   - Because tree-based ensemble detectors (XGBoost) evaluate feature splits based on training domain distributions, unobserved combinations of `sttl`, `dur`, and `smeansz` naturally receive elevated anomaly probability scores.

### 2.2 Operational Ground-Truth Limitation (Non-Causal Disclaimer)

> [!WARNING]
> Without independently verified packet-level ground-truth labels for the live Wi-Fi capture, the observed 64.5% anomaly rate **CANNOT** be classified as proof of malicious attacks, nor can it be conclusively dismissed as pure false positives.

- Anomaly detection identifies statistical deviations from the reference baseline, not causal intent.
- Offline synthetic replay metrics (such as the 98.10% held-out test accuracy on UNSW-NB15 Day 1) cannot be cited as representative of live network attack-detection performance.
- Production deployment or promotion beyond `READY FOR LOCAL DEMONSTRATION` requires routed SPAN/TAP calibration against authorized, labeled network traffic.

---

## 3. Drift Monitoring & Population Stability Index (PSI)

TrafficShield incorporates an automated drift detection engine ([`monitoring/service.py`](file:///d:/projects/trafficshield/monitoring/service.py)):
- Computes Population Stability Index (PSI) across the 13 input features against the reference baseline (`artifacts/monitoring/reference_baseline.json`).
- Categorizes feature drift:
  - $\text{PSI} < 0.10$: Negligible shift (Green).
  - $0.10 \le \text{PSI} < 0.25$: Moderate distribution shift (Amber Warning).
  - $\text{PSI} \ge 0.25$: Significant population drift (Red Alert; triggers investigation alert).
- Computes Wasserstein-1 distance for continuous flow metrics (`dur`, `sload`, `byte_rate`).
