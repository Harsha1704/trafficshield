# TrafficShield M15.3 — Model Integrity & TTL Decision Boundary Audit

**Document ID:** TS-M15.3-MODEL-INTEGRITY  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Cryptographic verification of frozen production artifacts and architectural analysis of ensemble tree decision boundaries vs individual split thresholds.

---

## 1. Cryptographic Hash Verification

Cryptographic SHA-256 hashes were calculated before and after Milestone 15.3 verification:

| Model Artifact File | Authoritative Baseline SHA-256 | Measured SHA-256 | Status |
|:---|:---|:---|:---:|
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **BIT-IDENTICAL MATCH** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **BIT-IDENTICAL MATCH** |

### Preserved Invariants:
1. **Zero Retraining:** The frozen XGBoost model (`XGBClassifier`) was not refit, serialized, or modified.
2. **Zero Preprocessor Alteration:** `TrafficShieldPreprocessor` retains its exact fitted RobustScaler center and scale parameters.
3. **Zero Threshold Tampering:** The operational classification threshold remains strictly $\tau = 0.50$. It was not adjusted or relaxed to artificially lower anomaly counts.

---

## 2. Distinction: Tree Split Thresholds vs Universal Decision Boundary

A critical distinction must be drawn between an **individual tree split threshold** and the **universal model decision boundary**:

### A. Individual Tree Split Thresholds ($sttl \approx 62.0$)
- In XGBoost, individual decision trees make local branching decisions based on feature thresholds:
  $$\text{If } x_j \le \theta_j \implies \text{traverse left leaf; Else } \implies \text{traverse right leaf}$$
- Inspection of the 3,446 tree nodes in `production_detector.joblib` shows that `sttl` is evaluated in **254 decision nodes**.
- In raw (unscaled) feature space, these splits cluster tightly between $62.0$ and $64.0$ ($\mu = 62.94$).
- When $sttl > 64$, those 254 nodes route to leaves with positive log-odds contributions ($w_t > 0$).

### B. The Universal Ensemble Decision Boundary ($\tau = 0.50$)
- An individual split does **not** unilaterally dictate the final classification.
- In XGBoost binary classification, the final score is the logistic sigmoid of the sum of leaf weights across all 50 trees in the ensemble, plus the base score:
  $$P(\text{anomaly}) = \frac{1}{1 + \exp\left(-\left(f_0 + \sum_{t=1}^{50} f_t(\mathbf{x})\right)\right)}$$
- A flow is classified as anomalous if and only if:
  $$\sum_{t=1}^{50} f_t(\mathbf{x}) \ge 0.0 \iff P(\text{anomaly}) \ge 0.50$$
- Therefore, `sttl > 62` acts as a strong positive accumulator, but the final outcome depends on the entire 13-feature vector $\mathbf{x}$.

---

## 3. Quantification of Sensitivity Across Scored Flows

To evaluate whether `sttl` alone governs predictions across diverse traffic shapes, parametric sweeps were executed on representative flows holding the other 12 features constant:

### Summary of Controlled Sensitivity Results:
1. **Single-Packet UDP Discovery (mDNS / SSDP):**
   - At $\text{TTL} = 60$: $P = 0.0010$ (Benign).
   - At $\text{TTL} = 64$: $P = 0.7460$ (Anomalous).
   - **Attribution:** In single-packet flows, all rate and duration features are zero (`duration=0`, `sload=0`, `sjit=0`, `sintpkt=0`, `swin=0`). In the absence of multi-packet TCP indicators, `sttl` is the primary differentiating feature.
2. **Interactive TCP Web Handshake:**
   - At $\text{TTL} = 60$: $P = 0.0069$ (Benign).
   - At $\text{TTL} = 64$: $P = 0.9873$ (Anomalous).
   - **Attribution:** When $sttl > 62$, positive weights from `sttl` combined with small packet counts elevate the score above $\tau = 0.50$.
3. **High-Volume TCP Data Transfer:**
   - For long-running, multi-megabyte TCP flows with large packet counts, high `fwd_bytes`, and high `smeansz`, the model evaluates multiple features simultaneously. In such flows, high byte rates and packet sizes contribute significantly alongside TTL.

---

## 4. Ground-Truth Malice & Payload Integrity

1. **Ambient Wi-Fi Traffic Is Not Attack Traffic:**
   - Packets captured on the authorized Wi-Fi adapter (mDNS port 5353, SSDP port 1900, Windows Delivery Optimization port 7680, HTTPS port 443) represent **standard, legitimate local network activity**.
   - They trigger anomaly alerts solely because their operating-system initial TTL values ($128$ and $255$) mismatch the UNSW-NB15 synthetic enterprise testbed training baseline ($sttl \le 62$).
   - **TrafficShield strictly avoids labeling ambient anomaly detections as confirmed attacks without independent ground-truth corroboration.**
2. **Zero Payload Retention:**
   - TrafficShield discards all packet payloads immediately upon protocol header validation.
   - No raw wire bytes, TLS session secrets, or packet application payloads are stored in memory or on disk.
