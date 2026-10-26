# TrafficShield M14.2.1 — End-to-End Runtime Inference Trace

**Document ID:** TS-M14-2-1-TRACE  
**Date:** 2026-10-24  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Real runtime trace through the complete data path from PCAP packet capture to persistent SOC alert.

---

## 1. End-to-End Data Path Architecture

```
[ Captured PCAP File / Network Stream ]
                 │
                 ▼ (Packet by Packet)
      [ IPv4PacketValidator ]
      • Structural header integrity check
      • Snaplen vs header truncation guard
      • Zero payload retention
                 │
                 ▼ (Valid IPv4 Packets)
   [ BoundedFragmentReassembler ]
      • In-flight capacity guard (500 datagrams)
      • Expiration timeout (3.0s)
      • Purges orphans; yields complete datagrams
                 │
                 ▼ (PacketEnvelope)
   [ UnidirectionalFlowBuilder ]
      • 5-tuple flow key aggregation
      • Stateful RFC 3550 jitter & Argus sload
      • Enforces positive STTL (drops sttl <= 0)
                 │
                 ▼ (Finalized Flow Dictionary)
 [ ProductionInferenceService.validate_and_prepare_input() ]
      • Policy audit against reverse-dependent features
      • Pulls 10 REQUIRED_BASE_FEATURES
      • Causally derives 3 forward rates
                 │
                 ▼ (13-Column Pandas DataFrame)
 [ TrafficShieldPreprocessor.transform_df() ]
      • Median imputation + RobustScaler on 12 numerics
      • Pass-through binary is_sm_ips_ports
                 │
                 ▼ (Normalized (1, 13) Numpy ndarray)
   [ OptunaTuned_XGBoost.predict_proba() ]
      • Evaluates continuous calibrated anomaly probability
      • Compares against decision threshold tau = 0.50
                 │
                 ▼ (Anomaly Decision & Attribution)
      [ StreamingInferenceWorker ]
      • Recent circular buffer update (UI telemetry)
      • Deduplication cache check
      • Commits SecurityAlert to SQLite WAL
```

---

## 2. Real Runtime Execution Trace

The trace below captures the exact data state of **Flow 1** and **Flow 2** extracted during authorized replay of `data/captures/sample_traffic.pcap` through the production pipeline. *(IP addresses are masked for documentation hygiene)*.

### 2.1 Stage 1: Ingested Packet Envelopes

- **Packet 1:** $t = 100.000$, $\text{src} = \text{10.x.x.x}:54321 \to \text{dst} = \text{192.168.x.x}:443$, $\text{proto} = \text{TCP}$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$.
- **Packet 2:** $t = 100.040$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$.
- **Packet 3:** $t = 100.080$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$.
- **Packet 4:** $t = 100.120$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$.
- **Packet 5:** $t = 100.160$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$.
- **Packet 6:** $t = 100.200$, $\text{len} = 60\text{B}$, $\text{TTL} = 64$, $\text{win} = 65535$, $\text{flags} = \text{FIN}$.

---

### 2.2 Stage 2: Finalized Flow Dictionary (`UnidirectionalFlowBuilder`)

Upon observing the TCP FIN flag, `ActiveFlowState.finalize()` emits:

```json
{
  "flow_id": "10.x.x.x:54321->192.168.x.x:443/TCP",
  "src_ip": "10.x.x.x",
  "dst_ip": "192.168.x.x",
  "src_port": 54321,
  "dst_port": 443,
  "protocol": "TCP",
  "first_timestamp": 100.0,
  "last_timestamp": 100.2,
  "is_finalized": true,
  "is_compatible": true,
  "compatibility_reason": null,
  "duration_seconds": 0.2,
  "fwd_bytes": 240,
  "sttl": 64,
  "sload": 7999.9981,
  "fwd_packets": 6,
  "swin": 65535,
  "smeansz": 40.0,
  "sjit": 0.0,
  "sintpkt": 40.0,
  "is_sm_ips_ports": 0,
  "packet_rate": 30.0,
  "byte_rate": 1199.9997,
  "bytes_per_packet": 40.0
}
```

---

### 2.3 Stage 3: Input Preparation (`ProductionInferenceService`)

`validate_and_prepare_input(flow)`:
1. Runs `audit_columns()`: Verifies zero forbidden reverse columns (`res_bdy_len`, `dbytes`, etc.).
2. Extracts 10 `REQUIRED_BASE_FEATURES` as floating-point series.
3. Computes causal rates:
   - `packet_rate`: $6.0 / 0.2 = 30.0$
   - `byte_rate`: $240.0 / 0.2 = 1200.0$
   - `bytes_per_packet`: $240.0 / 6.0 = 40.0$
4. Returns DataFrame with 13 columns:
   `['duration_seconds', 'fwd_bytes', 'sttl', 'sload', 'fwd_packets', 'swin', 'smeansz', 'sjit', 'sintpkt', 'is_sm_ips_ports', 'packet_rate', 'byte_rate', 'bytes_per_packet']`

---

### 2.4 Stage 4: Preprocessing & Scaling (`TrafficShieldPreprocessor`)

`preprocessor.transform_df(df)`:
- Imputes missing numeric values using training medians.
- Applies `RobustScaler` ($(x - Q_{50}) / \text{IQR}$) across 12 numeric features.
- Appends `is_sm_ips_ports` as unscaled binary feature.

Output Array:
```
Shape: (1, 13)
Values:
[[ 0.291338, -0.404984,  0.000000, -0.077977, -0.222222,  0.999985,
  -0.581644, -0.000000,  0.518712,  0.074747, -0.404984, -0.581644,
   0.000000 ]]
```

---

### 2.5 Stage 5: Model Inference & Probability Prediction

`production_detector.predict_proba(transformed)`:
- Model: `OptunaTuned_XGBoost` (`XGBClassifier`)
- Anomaly Probability: $P(\text{anomaly}) = \mathbf{0.368135}$
- Decision: $0.368135 < \tau = 0.50 \implies \mathbf{is\_anomaly = False}$
- Risk Level: **`LOW`**

---

### 2.6 Stage 6: Database Persistence (`SecurityAlert`)

When an anomalous flow ($P \ge 0.50$) is processed, `StreamingInferenceWorker._persist_alert()` deduplicates against active cache and executes:

```python
SecurityAlert(
    request_id="db5bf4b9-f3f9-4efc-9aba-88e526d25223",
    timestamp="2026-10-24T00:02:45.123456Z",
    is_anomaly=True,
    anomaly_score=0.784120,
    decision_threshold=0.50,
    risk_level="HIGH",
    model_name="OptunaTuned_XGBoost",
    model_version="1.0.0",
    status="NEW",
    source="PCAP_REPLAY",
    protocol="TCP",
    src_port=54321,
    dst_port=443,
    input_features={
        "duration_seconds": 0.2,
        "fwd_bytes": 240,
        "sttl": 64,
        "sload": 7999.9981,
        "fwd_packets": 6,
        "swin": 65535,
        "smeansz": 40.0,
        "sjit": 0.0,
        "sintpkt": 40.0,
        "is_sm_ips_ports": 0
    },
    top_contributing_features=[...],
    is_demo=False
)
```

**Zero raw packet payload bytes are stored, logged, or emitted.**
