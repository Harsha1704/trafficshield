# TrafficShield Milestone 9: Authoritative Feature Policy Audit
**Date:** 2026-10-23  
**Domain:** Unidirectional Network Traffic Observation  
**Enforcement Engine:** `features.policy.audit_columns` and `ml.production_service`

---

## 1. Feature Eligibility Principles

TrafficShield is strictly designed for **single-direction network monitoring** where only the ingress/forward packet stream is observable. Asymmetric routing and tap placement prevent observing return traffic, acknowledgments, or bidirectional state.

The feature policy partitions all possible flow fields into four mutually exclusive categories:
1. **ELIGIBLE (Forward-Observable):** Measurable solely from ingress packets.
2. **CONDITIONALLY ELIGIBLE:** Unidirectional fields requiring derivation or validation.
3. **PROHIBITED (Reverse-Dependent):** Any metric requiring return traffic observation.
4. **ALWAYS EXCLUDED (Ground-Truth Labels):** Attack category and label columns.

---

## 2. Specific Feature Resolution & Clarifications

### A. `is_sm_ips_ports` (Verdict: ELIGIBLE)
- **Operational Definition:** A binary flag indicating whether `src_ip == dst_ip` AND `src_port == dst_port` in the packet header.
- **Observability Proof:** This field is derived entirely from the IP and TCP/UDP header fields of an **individual ingress packet**. It requires zero acknowledgment or return packet observation. It is a classic signature for LAND attacks and spoofing.
- **Resolution:** Formally codified as **ELIGIBLE** in `docs/unsw_nb15_feature_policy.json` and `ingestion/adapters/unsw_nb15_policy.py`.

### B. `tcprtt` (Verdict: STRICTLY PROHIBITED)
- **Operational Definition:** Round-trip time between SYN-ACK and ACK packets.
- **Observability Proof:** Computing RTT requires observing the server's SYN-ACK (return direction) and the client's subsequent ACK. On a unidirectional monitoring tap, return packets do not pass through the sensor.
- **Resolution:** Formally codified as **PROHIBITED**; any request presenting `tcprtt`, `synack`, or `ackdat` is rejected with HTTP 422.

### C. Connection Aggregates: `ct_ftp_cmd`, `ct_srv_src`, etc. (Verdict: BATCH EXCLUDED)
- **Operational Definition:** ARGUS connection aggregate counts over a 100-connection sliding window.
- **Observability Analysis:** In real-time stream processing, future flows within the window cannot be known. Precomputed batch aggregates from UNSW-NB15 contain lookahead leakage into subsequent flows.
- **Resolution:** All `ct_*` fields are **EXCLUDED** from real-time scoring. Only streaming temporal features computed causally from past flows (`features/temporal.py`) are permitted.

---

## 3. Production Model Feature Inventory

The frozen production model uses exactly **13 causally verified forward features**:

| # | Feature Name | Observability Vector | Type | Physical Meaning |
|:---|:---|:---|:---|:---|
| 1 | `duration_seconds` | Forward timestamp delta | Continuous | Time elapsed between first and last observed forward packet |
| 2 | `fwd_bytes` | Ingress IP header | Continuous | Total payload + header bytes in forward direction |
| 3 | `sttl` | Ingress IP header | Discrete | Time-To-Live byte in forward IP header |
| 4 | `sload` | Forward packet stream | Continuous | Source bits per second |
| 5 | `fwd_packets` | Packet counter | Discrete | Count of observed ingress packets |
| 6 | `swin` | TCP header | Discrete | Source TCP advertised window size |
| 7 | `smeansz` | Derived | Continuous | Mean forward packet size (`fwd_bytes / fwd_packets`) |
| 8 | `sjit` | Timestamp deltas | Continuous | Source packet inter-arrival jitter |
| 9 | `sintpkt` | Timestamp deltas | Continuous | Mean inter-packet arrival time |
| 10 | `packet_rate` | Derived | Continuous | Forward packets per second |
| 11 | `byte_rate` | Derived | Continuous | Forward bytes per second |
| 12 | `bytes_per_packet` | Derived | Continuous | Ratio of bytes to packets |
| 13 | `is_sm_ips_ports` | Ingress IP/port header | Binary | Flag indicating identical source/dest IP and port |

---

## 4. Policy Enforcement Verification

Automated regression test `tests/unit/test_predict_api.py::test_predict_policy_violation_reverse_feature` asserts that injecting any prohibited field (`dbytes`, `tcprtt`, `dload`, etc.) immediately triggers an HTTP 422 rejection.
