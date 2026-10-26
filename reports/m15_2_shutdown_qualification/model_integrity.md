# TrafficShield M15.2 — Model Integrity & TTL Sensitivity Analysis

**Document ID:** TS-M15.2-MODEL-INTEGRITY  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Cryptographic verification of frozen model artifacts, immutable contract compliance, and empirical sensitivity analysis of `sttl` parameter response.

---

## 1. Cryptographic Artifact Integrity Verification

The production detector and preprocessor artifacts were verified before and after Milestone 15.2 implementation:

| Artifact Path | Expected Baseline SHA-256 | Measured Post-M15.2 SHA-256 | Verification Status |
|:---|:---|:---|:---:|
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **BIT-IDENTICAL MATCH** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **BIT-IDENTICAL MATCH** |

### Absolute Invariants Preserved:
- **Zero Retraining:** The underlying XGBoost estimator was not refit, retrained, or fine-tuned.
- **Zero Parameter Modification:** No trees, splits, weights, or hyperparameters were adjusted.
- **Zero Threshold Modification:** The operational decision threshold remains strictly $\tau = 0.50$.
- **Zero Preprocessor Alteration:** RobustScaler center and scale parameters remain unchanged.

---

## 2. Empirical Sensitivity Analysis: `sttl` Sweep

To definitively establish whether model predictions are driven by `sttl` alone (holding all other 12 features constant), a controlled parametric sweep was conducted using [`ProductionInferenceService`](file:///d:/projects/trafficshield/ml/production_service.py) across three representative flow templates:

1. **Template A (mDNS Single-Packet):** `fwd_packets=1`, `fwd_bytes=105`, `duration=0.0s`, `sload=0`, `swin=0`, `sjit=0`, `sintpkt=0`.
2. **Template B (Unicast DNS Query):** `fwd_packets=2`, `fwd_bytes=160`, `duration=0.04s`, `sload=32000`, `swin=0`, `sjit=1.0`, `sintpkt=40.0`.
3. **Template C (Web TCP Stream):** `fwd_packets=10`, `fwd_bytes=1200`, `duration=0.25s`, `sload=38400`, `swin=255`, `sjit=2.0`, `sintpkt=25.0`.

### Measured Anomaly Score $P(\text{anomaly})$ Across `sttl` Range $[1, 255]$:

| Raw `sttl` Input | Normalized `sttl` | Template A (mDNS) Score | Template B (DNS) Score | Template C (TCP Web) Score | Classification ($\tau = 0.50$) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| `1` | $-30.0$ | **$0.0010$** | **$0.0006$** | **$0.0069$** | **BENIGN** |
| `16` | $-15.0$ | **$0.0010$** | **$0.0006$** | **$0.0069$** | **BENIGN** |
| `31` (UNSW Center) | $0.0$ | **$0.0010$** | **$0.0006$** | **$0.0069$** | **BENIGN** |
| `48` | $+17.0$ | **$0.0010$** | **$0.0006$** | **$0.0069$** | **BENIGN** |
| `60` | $+29.0$ | **$0.0010$** | **$0.0006$** | **$0.0069$** | **BENIGN** |
| `62` (XGBoost Split) | $+31.0$ | **$0.9183$** | **$0.8866$** | **$0.9918$** | **ANOMALY** |
| `63` | $+32.0$ | **$0.9183$** | **$0.8866$** | **$0.9918$** | **ANOMALY** |
| `64` (Linux Default) | $+33.0$ | **$0.7460$** | **$0.6496$** | **$0.9873$** | **ANOMALY** |
| `118` (CDN / Edge) | $+87.0$ | **$0.7460$** | **$0.6496$** | **$0.9873$** | **ANOMALY** |
| `127` / `128` (Windows) | $+97.0$ | **$0.7460$** | **$0.6496$** | **$0.9873$** | **ANOMALY** |
| `255` (RFC 6762 mDNS) | $+224.0$ | **$0.7460$** | **$0.6496$** | **$0.9873$** | **ANOMALY** |

---

## 3. Analysis & Separation of Facts from Hypotheses

### A. Measured Facts
1. **Discontinuous Step Function:** For all three templates, the model output exhibits a sharp, discontinuous transition between $sttl = 60$ ($P \le 0.007$) and $sttl = 62$ ($P \ge 0.88$).
2. **Local Wi-Fi Reality:** On modern unrouted local networks, operating systems and protocols emit:
   - Linux / macOS / Android / iOS: Default initial $\text{TTL} = 64$.
   - Windows 10 / 11: Default initial $\text{TTL} = 128$.
   - mDNS (RFC 6762) & SSDP (RFC UPnP): Protocol-mandated $\text{TTL} = 255$.
3. **Mathematical Implication:** Because $64 > 62$, $128 > 62$, and $255 > 62$, **100% of unrouted local subnet packets fall on the high-anomaly side of the XGBoost split boundary**.

### B. Hypotheses
1. **Multi-Hop Routed Traffic Hypothesis:** In an enterprise routed network (such as the UNSW-NB15 testbed topology), packets cross multiple core routers. A packet starting at TTL 64 that traverses 2 to 3 hops arrives at the monitoring tap with $\text{TTL} \le 61$, placing normal traffic back into the benign zone ($P \le 0.007$).
2. **Ground-Truth Malice:** Ambient packets observed on the local Wi-Fi interface (such as mDNS queries to `224.0.0.251:5353`) are **NOT confirmed attacks**. They are standard, benign service discovery frames that trigger false-positive alerts exclusively due to domain feature distribution shift.
