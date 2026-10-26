# TrafficShield M14.2.1 — Authoritative Model Input Contract

**Document ID:** TS-M14-2-1-CONTRACT  
**Date:** 2026-10-24  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Forensic verification of the exact model input contract from serialized frozen artifacts, preprocessing pipeline, and detector estimator.

---

## 1. Authoritative Frozen Artifact Verification

The frozen production detector and preprocessor artifacts stored in `artifacts/models/` are the single source of truth for TrafficShield inference. Their cryptographic SHA-256 digests remain bit-for-bit identical to the authoritative baseline established in Milestone 9:

| Artifact | Filesystem Path | Authoritative SHA-256 Digest | Status |
| :--- | :--- | :--- | :---: |
| **Production Detector** | `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **MATCH (VERIFIED)** |
| **Production Preprocessor** | `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **MATCH (VERIFIED)** |

---

## 2. Introspection of Frozen Preprocessor (`production_preprocessor.joblib`)

Direct runtime inspection of `artifacts/models/production_preprocessor.joblib` reveals:

```python
{
    'scaler': 'robust',
    'impute_strategy': 'median',
    'strict_policy': True,
    'handle_unknown_categories': 'ignore',
    'is_fitted_': True,
    'feature_names_in_': [
        'duration_seconds',
        'fwd_bytes',
        'sttl',
        'sload',
        'fwd_packets',
        'swin',
        'smeansz',
        'sjit',
        'sintpkt',
        'is_sm_ips_ports',
        'packet_rate',
        'byte_rate',
        'bytes_per_packet'
    ],
    'numeric_features_': [
        'duration_seconds',
        'fwd_bytes',
        'sttl',
        'sload',
        'fwd_packets',
        'swin',
        'smeansz',
        'sjit',
        'sintpkt',
        'packet_rate',
        'byte_rate',
        'bytes_per_packet'
    ],
    'categorical_features_': [],
    'boolean_features_': ['is_sm_ips_ports'],
    'feature_names_out_': [
        'duration_seconds',
        'fwd_bytes',
        'sttl',
        'sload',
        'fwd_packets',
        'swin',
        'smeansz',
        'sjit',
        'sintpkt',
        'packet_rate',
        'byte_rate',
        'bytes_per_packet',
        'is_sm_ips_ports'
    ],
    '_numeric_imputer': SimpleImputer(strategy='median'),
    '_scaler_transformer': RobustScaler(),
    '_categorical_imputer': None,
    '_categorical_encoder': None,
    '_boolean_imputer': SimpleImputer(fill_value=0.0, strategy='constant')
}
```

---

## 3. Introspection of Frozen Detector (`production_detector.joblib`)

Direct runtime inspection of `artifacts/models/production_detector.joblib` confirms:

- **Estimator Class:** `xgboost.sklearn.XGBClassifier` (`OptunaTuned_XGBoost` v1.0.0)
- **Input Dimension (`n_features_in_`):** `13`
- **Feature Names In (`feature_names_in_`):**
  `['duration_seconds', 'fwd_bytes', 'sttl', 'sload', 'fwd_packets', 'swin', 'smeansz', 'sjit', 'sintpkt', 'packet_rate', 'byte_rate', 'bytes_per_packet', 'is_sm_ips_ports']`
- **Booster Feature Names:** Matches `preprocessor.feature_names_out_` in exact 1-to-1 order:
  `['duration_seconds', 'fwd_bytes', 'sttl', 'sload', 'fwd_packets', 'swin', 'smeansz', 'sjit', 'sintpkt', 'packet_rate', 'byte_rate', 'bytes_per_packet', 'is_sm_ips_ports']`
- **Feature Dtypes:** 13 floating-point magnitudes (`float32` / `float64`).
- **Decision Threshold:** $\tau = 0.50$ (Calibrated probability anomaly boundary).

---

## 4. The Authoritative 13-Feature Contract

The frozen production model requires exactly **10 base forward features** and **3 causally derived rate features**:

| # | Feature Name | Preprocessor Role | Type | Units | Source / Physical Meaning |
|---|--------------|-------------------|------|-------|---------------------------|
| 1 | `duration_seconds` | Numeric (`RobustScaler`) | `float64` | seconds | Record duration from first observed packet to last packet. |
| 2 | `fwd_bytes` | Numeric (`RobustScaler`) | `float64` | bytes | Total cumulative wire bytes in the monitored forward direction. |
| 3 | `sttl` | Numeric (`RobustScaler`) | `float64` | integer | Source IP header Time-To-Live ($1 \le \text{TTL} \le 255$). |
| 4 | `sload` | Numeric (`RobustScaler`) | `float64` | bits/sec | Source bits/sec across inter-arrival intervals: $\frac{(N-1)\cdot \text{smeansz} \cdot 8}{\text{dur}}$. |
| 5 | `fwd_packets` | Numeric (`RobustScaler`) | `float64` | count | Total packets observed in the forward flow direction ($N \ge 1$). |
| 6 | `swin` | Numeric (`RobustScaler`) | `float64` | bytes | Source advertised TCP window size (0 for UDP/ICMP). |
| 7 | `smeansz` | Numeric (`RobustScaler`) | `float64` | bytes | Mean forward packet size ($\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$). |
| 8 | `sjit` | Numeric (`RobustScaler`) | `float64` | ms | Source packet inter-arrival jitter in milliseconds (RFC 3550 EMA filter). |
| 9 | `sintpkt` | Numeric (`RobustScaler`) | `float64` | ms | Mean inter-packet arrival time: $\frac{\text{dur} \times 1000}{N - 1}$ for $N > 1$, else 0. |
| 10 | `is_sm_ips_ports` | Boolean (Binary pass-through) | `float64` | {0, 1} | Land attack indicator: 1 if $\text{src\_ip} == \text{dst\_ip}$ and $\text{src\_port} == \text{dst\_port}$, else 0. |
| 11 | `packet_rate` | Numeric (`RobustScaler`) | `float64` | pkts/sec | Causal forward packet rate: $\frac{\text{fwd\_packets}}{\text{duration\_seconds}}$ if $\text{dur} > 0$, else 0. |
| 12 | `byte_rate` | Numeric (`RobustScaler`) | `float64` | bytes/sec | Causal forward byte rate: $\frac{\text{fwd\_bytes}}{\text{duration\_seconds}}$ if $\text{dur} > 0$, else 0. |
| 13 | `bytes_per_packet` | Numeric (`RobustScaler`) | `float64` | bytes/pkt | Causal bytes per packet: $\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$, identical to `smeansz`. |

---

## 5. Ingestion & Scoring Service Interface

[`ProductionInferenceService`](file:///d:/projects/trafficshield/ml/production_service.py) serves as the gatekeeper:
1. Validates that incoming flows supply all 10 `REQUIRED_BASE_FEATURES`.
2. Evaluates incoming feature names against [`features.policy.audit_columns`](file:///d:/projects/trafficshield/features/policy.py) to reject any reverse-dependent or target label fields.
3. Automatically computes the 3 causal rates (`packet_rate`, `byte_rate`, `bytes_per_packet`).
4. Supplies the resulting 13-feature DataFrame to `preprocessor.transform_df()`.
5. Passes the scaled and imputed array to `production_detector.joblib` for inference.
