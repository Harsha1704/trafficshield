# TrafficShield M14.2.2 — Preprocessor Configuration & Transformer Topology

**Document ID:** TS-M14-2-2-CONFIG  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Forensic inspection of the serialized `production_preprocessor.joblib` artifact, transformer structure, scaling parameters, and block concatenation mechanics.

---

## 1. Frozen Preprocessor Identity & Integrity

The production preprocessor is loaded via [`ml.production_service.ProductionInferenceService`](file:///d:/projects/trafficshield/ml/production_service.py) from `artifacts/models/production_preprocessor.joblib`. Its cryptographic SHA-256 hash matches the authoritative M9 frozen baseline:

- **Path:** `artifacts/models/production_preprocessor.joblib`
- **Expected SHA-256:** `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`
- **Actual SHA-256:** `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`
- **Integrity Status:** **FROZEN / UNMODIFIED / BIT-IDENTICAL**

---

## 2. Transformer Topology & Hyperparameters

Direct inspection of the preprocessor attributes reveals:

```python
TrafficShieldPreprocessor(
    scaler="robust",
    impute_strategy="median",
    strict_policy=True,
    handle_unknown_categories="ignore",
    is_fitted_=True
)
```

### Internal Transformers
1. **Numeric Imputer (`_numeric_imputer`):**
   - Type: `sklearn.impute.SimpleImputer(strategy='median')`
   - Fitted on: 12 numeric features.
2. **Scaler Transformer (`_scaler_transformer`):**
   - Type: `sklearn.preprocessing.RobustScaler(with_centering=True, with_scaling=True, unit_variance=False)`
   - Computes: $z = \frac{x - Q_{50}(x)}{\text{IQR}(x)}$ where $\text{IQR} = Q_{75} - Q_{25}$.
3. **Boolean Imputer (`_boolean_imputer`):**
   - Type: `sklearn.impute.SimpleImputer(strategy='constant', fill_value=0.0)`
   - Applied to: `['is_sm_ips_ports']`
4. **Categorical Pipeline:**
   - `_categorical_imputer`: `None`
   - `_categorical_encoder`: `None` (0 categorical columns in production model).

---

## 3. Fitted Feature Collections & Block Assembly

The transformer partitions input columns into two explicit sub-collections:

### 3.1 `feature_names_in_` (Input Contract Order: 13 Features)
```python
[
    'duration_seconds',  # 0
    'fwd_bytes',         # 1
    'sttl',              # 2
    'sload',             # 3
    'fwd_packets',       # 4
    'swin',              # 5
    'smeansz',           # 6
    'sjit',              # 7
    'sintpkt',           # 8
    'is_sm_ips_ports',   # 9  <-- Notice: index 9 in feature_names_in_
    'packet_rate',       # 10
    'byte_rate',         # 11
    'bytes_per_packet'   # 12
]
```

### 3.2 Block Concatenation in `transform()`
In `preprocessing/pipeline.py`, `transform()` evaluates feature types in dedicated blocks:

```python
blocks: list[np.ndarray] = []

# Block 1: 12 Numeric Features
if self.numeric_features_:
    num_data = df[self.numeric_features_].apply(pd.to_numeric, errors="coerce")
    num_imputed = self._numeric_imputer.transform(num_data)
    num_scaled = self._scaler_transformer.transform(num_imputed)
    blocks.append(num_scaled)  # Yields (N, 12) array: columns 0 to 11

# Block 2: 1 Boolean Feature (is_sm_ips_ports)
if self.boolean_features_:
    bool_data = df[self.boolean_features_].astype(float)
    bool_imputed = self._boolean_imputer.transform(bool_data)
    blocks.append(bool_imputed)  # Yields (N, 1) array: column 12

result = np.hstack(blocks).astype(np.float64)  # Yields (N, 13) array
```

### 3.3 `feature_names_out_` (Transformed Output Order: 13 Features)
Because the 12 numeric features form Block 1 and the boolean feature forms Block 2, `feature_names_out_` is:
```python
[
    'duration_seconds',  # Index 0
    'fwd_bytes',         # Index 1
    'sttl',              # Index 2
    'sload',             # Index 3
    'fwd_packets',       # Index 4
    'swin',              # Index 5
    'smeansz',           # Index 6
    'sjit',              # Index 7
    'sintpkt',           # Index 8
    'packet_rate',       # Index 9  <-- Notice: index 9 in feature_names_out_ is packet_rate!
    'byte_rate',         # Index 10
    'bytes_per_packet',  # Index 11
    'is_sm_ips_ports'    # Index 12 <-- is_sm_ips_ports is appended as column 12!
]
```

---

## 4. Frozen RobustScaler Parameters

Fitted values from training partition (Day 1 UNSW-NB15):

| Index | Feature Name | Center ($Q_{50}$ / Median) | Scale ($\text{IQR} = Q_{75} - Q_{25}$) | Scaling Formula |
|:---:|:---|:---:|:---:|:---|
| 0 | `duration_seconds` | $0.033008$ | $0.573189$ | $\frac{x - 0.033008}{0.573189}$ |
| 1 | `fwd_bytes` | $1540.0$ | $3210.0$ | $\frac{x - 1540.0}{3210.0}$ |
| 2 | `sttl` | $31.0$ | $1.0$ | $\frac{x - 31.0}{1.0}$ |
| 3 | `sload` | $505836.5625$ | $821728.5234$ | $\frac{x - 505836.5625}{821728.5234}$ |
| 4 | `fwd_packets` | $16.0$ | $32.0$ | $\frac{x - 16.0}{32.0}$ |
| 5 | `swin` | $255.0$ | $1.0$ | $\frac{x - 255.0}{1.0}$ |
| 6 | `smeansz` | $73.0$ | $56.0$ | $\frac{x - 73.0}{56.0}$ |
| 7 | `sjit` | $61.735433$ | $1565.59807$ | $\frac{x - 61.735433}{1565.59807}$ |
| 8 | `sintpkt` | $1.219467$ | $23.842038$ | $\frac{x - 1.219467}{23.842038}$ |
| 9 | `packet_rate` | $856.026965$ | $1923.41034$ | $\frac{x - 856.026965}{1923.41034}$ |
| 10 | `byte_rate` | $81382.4446$ | $134532.2501$ | $\frac{x - 81382.4446}{134532.2501}$ |
| 11 | `bytes_per_packet` | $73.0$ | $56.7357143$ | $\frac{x - 73.0}{56.7357143}$ |
| 12 | `is_sm_ips_ports` | *None (Unscaled)* | *None (Unscaled)* | $\text{Identity: } x \to x$ (via Constant 0 Imputer) |

---

## 5. Summary Finding

`is_sm_ips_ports` is **strictly unscaled binary pass-through** ($0 \to 0.0$, $1 \to 1.0$) and occupies **column index 12** of the preprocessor output matrix. It is **never scaled by RobustScaler** and can never mathematically produce $0.074747$.
