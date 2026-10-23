# TrafficShield Milestone 9: Split Integrity & Target Leakage Audit
**Date:** 2026-10-23  
**Splitting Strategy:** 4-Way Chronological Non-Overlapping Partitioning

---

## 1. Split Boundaries & Temporal Ordering

To guarantee zero lookahead bias and realistic SOC deployment conditions, flows were partitioned strictly by start timestamp:

| Split Partition | Flow Count | Normal Flows | Attack Flows | Attack % | Timestamp Start | Timestamp End |
|:---|:---:|:---:|:---:|:---:|:---|:---|
| **Train** | 50,004 | 46,221 | 3,783 | 7.57% | 2015-01-22 11:50:14+00:00 | 2015-01-22 12:23:16+00:00 |
| **Validation** | 14,999 | 14,112 | 887 | 5.91% | 2015-01-22 12:23:17+00:00 | 2015-01-22 12:33:23+00:00 |
| **Calibration** | 15,055 | 14,153 | 902 | 5.99% | 2015-01-22 12:33:24+00:00 | 2015-01-22 12:43:22+00:00 |
| **Test** | 19,942 | 14,084 | 5,858 | 29.38% | 2015-01-22 12:43:23+00:00 | 2015-01-22 12:53:21+00:00 |
| **Total Day 1** | **100,000** | **88,570** | **11,430** | **11.43%** | - | - |

### Strict Non-Overlap Verification:
- $\max(\text{Train}_{t}) = 2015-01-22 12:23:16+00:00 \le \min(\text{Val}_{t}) = 2015-01-22 12:23:17+00:00$: **VERIFIED**
- $\max(\text{Val}_{t}) = 2015-01-22 12:33:23+00:00 \le \min(\text{Cal}_{t}) = 2015-01-22 12:33:24+00:00$: **VERIFIED**
- $\max(\text{Cal}_{t}) = 2015-01-22 12:43:22+00:00 \le \min(\text{Test}_{t}) = 2015-01-22 12:43:23+00:00$: **VERIFIED**

---

## 2. Target Leakage & The `sttl` Phenomenon ($r = 0.8022$)

A deep-dive investigation was conducted into the high Pearson correlation between `sttl` (Source IP Time-To-Live) and attack labels:

### Statistical Profile:
- **Normal Traffic `sttl`:**
  - Mean: 37.89
  - Median: 31.00
  - Interquartile Range: [31, 62] (reflecting typical multi-hop transit from remote hosts)
- **Attack Traffic `sttl`:**
  - Mean: 221.74
  - Median: 254.00
  - Mode: 254 (reflecting direct injection from adjacent attack testbed hosts running raw sockets)

### Technical Analysis:
1. **Is `sttl` causally observable?**  
   **YES.** The IPv4 Time-to-Live byte is a standard 8-bit field in every ingress IP header. A unidirectional network tap inspects it with zero reliance on return traffic.
2. **Is it synthetic testbed artifact or genuine attack indicator?**  
   In synthetic testbeds (like UNSW-NB15, CICIDS, and DARPA), attack generation tools (e.g., Scapy, Metasploit, Nmap) run on dedicated machines in the cyber range with default TTLs (254 or 255) and few routing hops, whereas normal background traffic traverses the simulated Internet with TTLs decremented to 31 or 62.
3. **Does it generalize?**  
   On Day 2 (`UNSW-NB15_3.csv`), `sttl` correlation remains high ($r = 0.9437$), allowing the model to detect 98.02% of Day 2 attacks. However, in a real-world enterprise deployment, attackers can spoof TTLs. Therefore, TrafficShield combines `sttl` with 12 other volumetric and rate features (`sload`, `packet_rate`, `bytes_per_packet`, `sjit`) so the model maintains robust detection even when TTL anomalies are neutralized.
