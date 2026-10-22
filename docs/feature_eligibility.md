# TrafficShield — One-Way Feature Eligibility Policy

Version: 1.0  
Date: 2026-10-22  
Milestone: M3 (Feature Engineering, Preprocessing, Train-Only Fitting & Leakage Prevention)

## Premise

TrafficShield is designed for critical-infrastructure monitoring links that observe traffic in **one direction only**. The detection pipeline must never depend on:

- Reverse-direction traffic (replies, acknowledgements, return packets)
- Response timing (RTT, request-response latency)
- Bidirectional session state (TCP handshake completion across both directions)
- Any information that requires observing the opposite link direction
- Ground-truth evaluation labels or post-event knowledge during training
- Future observations during training or calibration

---

## Eligibility Roles (`FieldRole`)

Every field in TrafficShield is categorized by a formal `FieldRole` in `features.policy`:

1. **`FieldRole.FEATURE`**: Explicitly allowlisted model inputs.
2. **`FieldRole.LABEL`**: Ground-truth evaluation outcomes (evaluation only; structurally barred from model input).
3. **`FieldRole.IDENTIFIER`**: High-cardinality provenance keys (UUIDs, IP addresses; not treated as numerical values).
4. **`FieldRole.TIMESTAMP`**: Chronological ordering and dataset splitting only.
5. **`FieldRole.METADATA`**: Operational audit fields (raw ports, protocols, flags) mapped into safe categories.
6. **`FieldRole.FORBIDDEN`**: Strictly prohibited features (violates unidirectional or leakage constraints).

---

## Field Classification Matrix

### ✅ ELIGIBLE Features (`FieldRole.FEATURE`)

| Feature | Role | Type | Source | Rationale |
|---------|------|------|--------|-----------|
| `fwd_packets` | Feature | Numeric | Canonical | Observable forward packet counter |
| `fwd_bytes` | Feature | Numeric | Canonical | Observable forward byte counter |
| `duration_seconds` | Feature | Numeric | Canonical | Sensor-observed duration from first to last seen packet |
| `ip_tos` | Feature | Numeric | Canonical | Type of Service / DSCP byte in IP header |
| `fwd_status` | Feature | Categorical | Canonical | NetFlow router forwarding status byte |
| `packet_rate` | Feature | Numeric | Engineered | Forward packets per second (`fwd_packets / duration`) |
| `byte_rate` | Feature | Numeric | Engineered | Forward bytes per second (`fwd_bytes / duration`) |
| `bytes_per_packet` | Feature | Numeric | Engineered | Average packet payload size in observed direction |
| `log_fwd_packets` | Feature | Numeric | Engineered | `log1p(fwd_packets)` variance stabilization |
| `log_fwd_bytes` | Feature | Numeric | Engineered | `log1p(fwd_bytes)` heavy-tail compression |
| `log_duration` | Feature | Numeric | Engineered | `log1p(duration_seconds)` |
| `log_packet_rate` | Feature | Numeric | Engineered | `log1p(packet_rate)` |
| `log_byte_rate` | Feature | Numeric | Engineered | `log1p(byte_rate)` |
| `log_bytes_per_packet`| Feature | Numeric | Engineered | `log1p(bytes_per_packet)` |
| `protocol_category` | Feature | Categorical | Engineered | Transport group: TCP, UDP, ICMP, OTHER |
| `dst_port_category` | Feature | Categorical | Engineered | Well-known (<1024), registered (1024-49151), ephemeral (49152+) |
| `src_port_category` | Feature | Categorical | Engineered | Client port category |
| `is_well_known_dst_port` | Feature | Boolean | Engineered | Binary server service indicator |
| `is_tcp`, `is_udp`, `is_icmp` | Feature | Boolean | Engineered | Direct protocol indicators |
| `has_syn`, `has_ack`, `has_fin`, `has_rst`, `has_psh`, `has_urg` | Feature | Boolean | Engineered | Observed forward TCP flags |
| `hour_of_day`, `day_of_week`, `is_weekend` | Feature | Numeric/Bool | Engineered | Diurnal and weekly calendar baselines |
| `sin_hour`, `cos_hour`, `sin_day_of_week`, `cos_day_of_week` | Feature | Numeric | Engineered | Bounded continuous cyclic trigonometric representations |

---

### ❌ PROHIBITED Features (`FieldRole.FORBIDDEN`)

These fields require observing the unmonitored reverse direction and are strictly rejected:

| Feature | Reason |
|---------|--------|
| `bwd_packets` | Requires observing return direction link |
| `bwd_bytes` | Requires observing return direction link |
| `bwd_header_length` | Requires observing return direction headers |
| `rtt_ms` | Requires SYN-ACK from return direction |
| `response_latency_ms`| Requires return direction response timestamp |
| `session_complete` | Requires bidirectional FIN/RST confirmation |
| `fwd_bwd_packet_ratio` | Requires both traffic directions |
| `fwd_bwd_byte_ratio` | Requires both traffic directions |

---

### ⛔ EVALUATION LABELS (`FieldRole.LABEL`)

Retained strictly for held-out evaluation; structurally prevented from entering training:

| Column | Description |
|--------|-------------|
| `eval_label` | Canonical evaluation label string |
| `eval_label_raw` | Source dataset raw label string |
| `is_attack` | Ground-truth binary attack indicator |
| `class` | UGR'16 source class column |
| `label` | Generic evaluation label column |
| `attack_cat` | UNSW-NB15 evaluation attack category |

---

### 🆔 IDENTIFIERS & TIMESTAMPS (`FieldRole.IDENTIFIER` / `FieldRole.TIMESTAMP`)

Excluded from numeric matrices to prevent target memorization:
- `record_id`: UUID for record provenance
- `src_ip`, `dst_ip`: IP addresses (anonymized or raw)
- `flow_end_ts`, `ingest_ts`: Ordering, temporal windowing, and chronological splitting only

---

## Programmatic Enforcement Contracts

1. **`features.policy`**: Centralized policy specifications with `audit_columns()` and `validate_feature_columns()`. Strict mode raises `PolicyViolationError` if any non-feature or unregistered column is passed.
2. **`features.engineering.FeatureEngineer`**: Derives all features using strictly forward-direction data, safely guards zero durations and negative counts, and clamps all values.
3. **`features.engineering.extract_features_and_labels()`**: Cleanly partitions data into `(features_df, labels_series, metadata_df)`.
4. **`preprocessing.pipeline.TrafficShieldPreprocessor`**:
   - Trains scalers, imputers, and encoders STRICTLY on training observations.
   - Test observations NEVER update means, variances, medians, or categories.
   - Automatically handles unseen categories via `handle_unknown='ignore'`.
   - Guarantees deterministic output column ordering (`get_feature_names_out()`).
5. **`preprocessing.split.chronological_split()`**: Partitions data chronologically without future lookahead. Validates that `train_max <= test_min`.
6. **`preprocessing.split.ugr16_calibration_test_split()`**: Official calibration (March–June 2016 background only) vs test (July–August 2016 attacks) partition.
7. **`preprocessing.artifacts.save_preprocessor()` & `load_preprocessor()`**: Cryptographically signed `.joblib` artifacts with companion `.json` manifests containing SHA-256 hashes, feature policy versions, and feature ordering.
8. **Automated Leakage Suite (`tests/unit/test_leakage_prevention.py`)**: 12 automated checks guarding against reverse-feature leakage, label leakage, temporal leakage, parameter leakage, and tampered artifacts.
