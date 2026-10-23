# TrafficShield M14 Real-Time — 13-Feature Traceability & Compatibility Matrix

**Milestone:** M14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts  
**Date:** 2026-10-23  
**Status:** 100% RECONCILED & MATHEMATICALLY VERIFIED  

---

## 1. Feature Definition & Calculation Matrix

| # | Feature Name | Preprocessor & Model Order | Training Definition (UNSW-NB15) | Live Packet Replay Calculation | Units | Missing / Single-Packet Behavior | Semantic Difference Analysis |
|---|---|---|---|---|---|---|---|
| 1 | `duration_seconds` | Index 0 | Flow record duration | $t_{\text{last}} - t_{\text{first}}$ from packet arrival timestamps | Seconds | If $N=1$, duration is identically 0.0s | None. Fully equivalent. |
| 2 | `fwd_bytes` | Index 1 | Source-to-destination transaction bytes | Sum of IPv4 total length (`ip.len`) for observed forward packets | Bytes | $\ge 20$ bytes (minimum IPv4 header) | Fully equivalent. |
| 3 | `sttl` | Index 2 | Source-to-destination TTL | Time-to-Live field read from first observed packet IPv4 header | Integer [0–255] | If missing, defaults to 64 | Fully equivalent. |
| 4 | `sload` | Index 3 | Source bits per second | $\frac{8 \times \text{fwd\_bytes}}{\text{duration\_seconds}}$ when duration > 0 | Bits per second | Guarded to 0.0 if duration = 0.0s | Fully equivalent. |
| 5 | `fwd_packets` | Index 4 | Source-to-destination packet count | Count of packets observed in forward direction ($N$) | Count ($\ge 1$) | Minimum 1 | Fully equivalent. |
| 6 | `swin` | Index 5 | Source TCP window advertisement | Advertised window from latest forward TCP header | Integer [0–65535] | 0 for UDP and ICMP | Fully equivalent. |
| 7 | `smeansz` | Index 6 | Mean source packet size | $\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$ | Bytes / packet | Equal to packet length if $N=1$ | Fully equivalent. |
| 8 | `sjit` | Index 7 | Source inter-arrival jitter | RFC 3550 exponential moving average of packet arrival variance | Milliseconds | 0.0 ms if $N \le 2$ | Matches standard RFC 3550 formulation used by Argus. |
| 9 | `sintpkt` | Index 8 | Source inter-packet arrival time | $\frac{\text{duration\_seconds} \times 1000}{N - 1}$ when $N > 1$ | Milliseconds | 0.0 ms if $N \le 1$ | Fully equivalent. |
| 10 | `is_sm_ips_ports` | Index 9 | Identical IP & port attack flag | $1 \text{ if } (\text{src\_ip} = \text{dst\_ip} \land \text{src\_port} = \text{dst\_port}) \text{ else } 0$ | Binary {0, 1} | 0 for distinct endpoints | Fully equivalent. Detects Land attacks. |
| 11 | `packet_rate` | Index 10 | Causal packet delivery rate | $\frac{\text{fwd\_packets}}{\text{duration\_seconds}}$ when duration > 0 | Packets / second | Guarded to 0.0 if duration = 0.0s | Derived causally. No reverse leakage. |
| 12 | `byte_rate` | Index 11 | Causal byte delivery rate | $\frac{\text{fwd\_bytes}}{\text{duration\_seconds}}$ when duration > 0 | Bytes / second | Guarded to 0.0 if duration = 0.0s | Derived causally. No reverse leakage. |
| 13 | `bytes_per_packet` | Index 12 | Average byte payload per packet | $\frac{\text{fwd\_bytes}}{\text{fwd\_packets}}$ | Bytes / packet | Equal to `smeansz` | Derived causally. Fully equivalent. |

---

## 2. Guarding Edge Cases: Single-Packet Flows

When a flow consists of only a single observed packet ($N=1$):
- $t_{\text{last}} - t_{\text{first}} = 0.0\text{ seconds}$.
- Time-rate denominators would trigger division-by-zero errors.
- **Enforced Safety Guard:** TrafficShield explicitly evaluates:
  ```python
  if duration > 0.0:
      sload = (bytes_ * 8.0) / duration
      packet_rate = pkts / duration
      byte_rate = bytes_ / duration
  else:
      sload = 0.0
      packet_rate = 0.0
      byte_rate = 0.0
  ```
- `sintpkt` and `sjit` are mathematically 0.0 ms because no inter-packet arrival intervals exist.
- Single-packet flows are scored accurately using header metadata (`sttl`, `swin`, `smeansz`, `is_sm_ips_ports`).

---

## 3. Directional Blocklist & Anti-Leakage Verification

The following reverse-link metrics and evaluation labels are strictly blocked by `ml.production_service.validate_and_prepare_input` and `features.policy.audit_columns`:

- **Forbidden Reverse Columns:** `bwd_packets`, `bwd_bytes`, `dbytes`, `dpkts`, `dload`, `dttl`, `dmeansz`, `djit`, `dintpkt`, `dwin`, `tcprtt`, `synack`, `ackdat`.
- **Forbidden Target Labels:** `label`, `attack_cat`, `class`.
- **Result on Violation:** Immediate HTTP 422 `FEATURE_POLICY_VIOLATION`.
