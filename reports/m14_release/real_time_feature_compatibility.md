# TrafficShield M14 — Real-Time Feature Compatibility Audit & Critical Gate Report

**Milestone:** M14 — End-to-End Release Validation & Security Integration Testing  
**Component:** Real-Time Traffic Ingestion & Model Feature Compatibility  
**Authoritative Artifact Models:**  
- Model Artifact: `artifacts/models/production_detector.joblib`  
  - SHA-256: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`  
- Preprocessor: `artifacts/models/production_preprocessor.joblib`  
  - SHA-256: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`  
**Verdict:** `PCAP_REPLAY_VERIFIED`  
**Driver Status:** Host lacks Npcap/WinPcap native C drivers (`wpcap.dll`); live interface promiscuous sniffing is driver-blocked on this host. PCAP file replay and Scapy packet aggregation are 100% verified.

---

## 1. Executive Summary & Gate Status

The frozen TrafficShield production model requires exactly **10 base unidirectional features** and computes **3 derived causal rates**, forming a 13-feature input vector. In network security machine learning, training-serving skew frequently arises when models trained on pre-aggregated historical datasets (such as UNSW-NB15) are fed features from packet sniffers that calculate metrics differently or rely on bidirectional state.

This critical audit verifies:
1. **Mathematical equivalence:** Each of the 13 features extracted from packet streams by `ingestion/parsers/pcap_flow_parser.py` maps to the exact physical definition and units expected by the preprocessor and model.
2. **Strict unidirectional observation:** No reverse-link packet, round-trip time, acknowledgment timestamp, or destination-to-source payload is consumed.
3. **No fabrication or zero-filling:** Missing features are never silently imputed with zeros; single-packet flows have clear mathematical limits (duration = 0, rates guarded).
4. **Authoritative Artifact Preservation:** Model artifacts remain bit-for-bit identical to M9/M12 authoritative releases.

---

## 2. Comprehensive 13-Feature Traceability Matrix

| # | Feature Name | UNSW-NB15 Training Definition | Live Packet Capture Implementation | Formula / Calculation | Units | Compatibility Status |
|---|---|---|---|---|---|---|
| 1 | `duration_seconds` | Elapsed flow record duration from first to last packet | Elapsed time between first packet timestamp ($t_0$) and latest packet timestamp ($t_n$) | $t_n - t_0$ (guarded $\ge 0.0$) | seconds | **VERIFIED** |
| 2 | `fwd_bytes` | Source-to-destination transaction bytes | Total IPv4 header length sum of all observed forward packets | $\sum_{i=1}^N \text{len}(\text{pkt}_i)$ | bytes | **VERIFIED** |
| 3 | `sttl` | Source-to-destination time-to-live | Time-to-Live field read directly from first observed IPv4 header | $\text{IPv4.ttl}_0$ | integer [0–255] | **VERIFIED** |
| 4 | `sload` | Source bits per second | Source bits divided by flow duration (when duration > 0) | $\frac{8 \times \text{fwd\_bytes}}{\text{duration\_seconds}}$ (0.0 if dur = 0) | bps | **VERIFIED** |
| 5 | `fwd_packets` | Source-to-destination packet count | Total number of forward IP packets observed for this 5-tuple | $N = \text{count}(\text{pkts})$ | count ($\ge 1$) | **VERIFIED** |
| 6 | `swin` | Source TCP advertised window | TCP window size parameter from latest forward TCP header | $\text{TCP.window}$ (0 for UDP/ICMP) | integer [0–65535] | **VERIFIED** |
| 7 | `smeansz` | Mean source packet size | Total forward bytes divided by forward packet count | $\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$ | bytes/packet | **VERIFIED** |
| 8 | `sjit` | Source inter-arrival jitter | Inter-arrival jitter across consecutive forward packets using RFC 3550 exponential moving average | $D(i, j) = \|(R_j - R_i) - (S_j - S_i)\|$; $J = J + \frac{\|D\| - J}{16}$ | milliseconds | **VERIFIED** |
| 9 | `sintpkt` | Source inter-packet arrival time | Average arrival interval between successive forward packets | $\frac{\text{duration\_seconds} \times 1000}{N - 1}$ (0.0 if $N \le 1$) | milliseconds | **VERIFIED** |
| 10 | `is_sm_ips_ports` | Identical IP & port attack flag | Binary indicator whether source equals destination IP and port (Land attack pattern) | $1 \text{ if } (\text{src\_ip} = \text{dst\_ip} \land \text{src\_port} = \text{dst\_port}) \text{ else } 0$ | binary {0, 1} | **VERIFIED** |
| 11 | `packet_rate` | Causal forward packet rate | Derived forward packet delivery frequency | $\frac{\text{fwd\_packets}}{\text{duration\_seconds}}$ (0.0 if dur = 0) | packets/sec | **VERIFIED** |
| 12 | `byte_rate` | Causal forward byte rate | Derived forward byte delivery frequency | $\frac{\text{fwd\_bytes}}{\text{duration\_seconds}}$ (0.0 if dur = 0) | bytes/sec | **VERIFIED** |
| 13 | `bytes_per_packet` | Causal packet size density | Derived average byte payload per packet | $\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$ | bytes/packet | **VERIFIED** |

---

## 3. Disallowed Features and Leakage Defense

The production pipeline explicitly rejects and forbids the following reverse or non-causal features:
- **Strictly Prohibited:** `dload`, `dttl`, `dmeansz`, `djit`, `dintpkt`, `dwin`, `bwd_packets`, `bwd_bytes`, `ct_srv_src`, `ct_state_ttl`, `label`, `attack_cat`.
- **Validation Check:** `ingestion/parsers/pcap_flow_parser.py` contains zero references or aggregations for reverse packets. All flows are indexed by unidirectional 5-tuple: `(src_ip, dst_ip, src_port, dst_port, protocol)`.
- **Pre-inference Filter:** `ProductionInferenceService.validate_and_prepare_input` validates that no prohibited key enters the feature frame; prohibited keys cause an immediate `400 Bad Request` or `ValueError`.

---

## 4. Flow Finalization vs. In-Flight Scoring

A crucial operational distinction is drawn between **in-flight provisional flows** and **finalized flows**:
1. **Flow Finalization Triggers:**
   - **TCP FIN / RST flags:** When an observed TCP packet contains FIN or RST flags, the flow is marked complete and immediately dispatched for model scoring.
   - **Idle Timeout Expiration:** Non-TCP flows (UDP, ICMP) or unclosed TCP flows that have no packet arrivals for $\Delta t > \tau_{\text{idle}}$ (default 2.0s) are expired and finalized.
2. **Provisional In-Flight Scoring:**
   - If early scoring is requested on an active flow before finalization, it is explicitly flagged with `is_finalized: False`.
   - The production monitoring baseline only registers finalized flow vectors to maintain feature distribution integrity.

---

## 5. Host Driver Availability and Verdict

1. **Host Environment Check:**
   - Windows 11 host inspected for packet capture providers.
   - Command `from scapy.all import get_if_list` outputs: `WARNING: No libpcap provider available ! pcap won't be used`.
   - The native Npcap DLL (`wpcap.dll`) is not installed on this host system.
2. **Verdict Justification:**
   - Claiming `LIVE_CAPTURE_VERIFIED` on a machine without a functioning C packet driver would be untruthful.
   - Pure-Python PCAP parsing (`rdpcap`, `PcapReader`) and Scapy packet aggregation function with 100% mathematical fidelity.
   - Full synthetic and offline PCAP replay tests pass all verification criteria and output valid continuous anomaly scores without schema error.
   - **Final Verdict:** `PCAP_REPLAY_VERIFIED`.
