# TrafficShield Milestone 10: Feature Compatibility Audit & Observability Contract
**Date:** 2026-10-23  
**Domain:** Cross-Dataset Unidirectional Feature Mapping  

---

## 1. Feature Eligibility & Availability Timing Contract

TrafficShield enforces strict unidirectional monitoring link constraints:
1. **Zero Return Observability:** All backward packets, backward bytes, inter-arrival times, and return TCP flags are strictly prohibited.
2. **Availability Timing Distinction:**
   - **`packet_arrival`:** Observable immediately upon receiving individual packets (e.g. `Destination Port`, `sttl`, `is_sm_ips_ports`).
   - **`flow_prefix`:** Observable during early packets (e.g. `swin` / `Init_Win_bytes_forward`, `min_seg_size_forward`).
   - **`flow_completion`:** Observable only after a flow terminates or times out (e.g. `duration_seconds`, `fwd_bytes`, `fwd_packets`, `packet_rate`, `byte_rate`).

> [!IMPORTANT]
> Flow-completion metrics must never be characterized as packet-by-packet real-time detection. They represent flow-level network monitoring.

---

## 2. Direct Transfer Feasibility Audit

### Investigation: Can the frozen UNSW-NB15 production model run on CICIDS2017?
- **Production Model Required Features (13):**  
  `duration_seconds`, `fwd_bytes`, `sttl`, `sload`, `fwd_packets`, `swin`, `smeansz`, `sjit`, `sintpkt`, `packet_rate`, `byte_rate`, `bytes_per_packet`, `is_sm_ips_ports`.

### Fatal Incompatibilities:
1. **`sttl` (Source IP TTL):**  
   CICFlowMeter captures do not extract IP Time-to-Live headers. In UNSW-NB15, `sttl` has an $r=0.8022$ correlation with attack traffic (attacks injected with TTL 254 vs local traffic 31-64). Transferring the production model without `sttl` would require zero-imputation or arbitrary substitution, invalidating the model's decision splits.
2. **`is_sm_ips_ports` (Same IP/Port Flag):**  
   Public CICIDS2017 CSV datasets omit source IP addresses to preserve testbed privacy. This prevents calculating whether source IP equals destination IP.

### Verdict:
**DIRECT TRANSFER IS UNSUPPORTED.**  
Attempting direct transfer without these fields would constitute unscientific feature fabrication.

---

## 3. The Common Forward-Observable Subspace

To enable legitimate cross-dataset investigation, TrafficShield establishes a **Common Forward-Observable Shared Feature Set (9 features)** with rigorous semantic equivalence:

| # | Common Feature | UNSW-NB15 Source | CICIDS2017 Source | Semantic Equivalence | Timing |
|:---|:---|:---|:---|:---|:---:|
| 1 | `duration_seconds` | `dur` (seconds) | `Flow Duration` ($\mu\text{s} / 10^6$) | Exact physical duration | Flow Completion |
| 2 | `fwd_bytes` | `sbytes` | `Total Length of Fwd Packets` | Total forward byte volume | Flow Completion |
| 3 | `fwd_packets` | `spkts` | `Total Fwd Packets` | Total forward packet count | Flow Completion |
| 4 | `smeansz` | `smeansz` | `Fwd Packet Length Mean` | Mean forward packet length | Flow Completion |
| 5 | `sintpkt` | `sintpkt` | `Fwd IAT Mean` | Mean forward inter-arrival time | Flow Completion |
| 6 | `packet_rate` | `fwd_packets / dur` | `Fwd Packets/s` | Forward packet rate | Flow Completion |
| 7 | `byte_rate` | `fwd_bytes / dur` | `fwd_bytes / dur` | Forward byte rate | Flow Completion |
| 8 | `bytes_per_packet` | `fwd_bytes / fwd_packets` | `fwd_bytes / fwd_packets` | Mean bytes per packet | Flow Completion |
| 9 | `swin` | `swin` | `Init_Win_bytes_forward` | Initial TCP advertised window | Flow Prefix |

The complete mapping of all 107 audited features across both datasets (49 UNSW-NB15 specifications + 58 CICIDS2017 specifications) is exported to [`feature_compatibility_matrix.csv`](./feature_compatibility_matrix.csv).
