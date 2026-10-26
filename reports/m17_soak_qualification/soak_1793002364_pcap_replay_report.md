# TrafficShield Soak Qualification Report — soak_1793002364_pcap_replay

**Mode:** `PCAP_REPLAY`  
**Target:** `data/captures/sample_traffic.pcap`  
**Configured Duration:** 5.0s  
**Actual Duration:** 5.04s  
**Samples Recorded:** 3  
**Final Worker State:** `STOPPED`  
**Shutdown Drain Latency:** 0.25 ms  
**Overall Verdict:** **PASS**  

---

## 1. Resource Consumption Summary

| Resource Metric | Baseline Value | Final Value | Peak Observed | Trend Evaluation |
|:---|:---:|:---:|:---:|:---|
| **RSS Memory (Working Set)** | 136.05 MB | 342.02 MB | 342.16 MB | Bounded growth |
| **Process CPU Utilization** | 0.0% | — | 74.3% | Within bounds |

---

## 2. Mathematical Flow Accounting Invariants

| Invariant Name | Expected | Actual Measured | Status | Details |
|:---|:---:|:---:|:---:|:---|
| `INV_1_ACTIVE_FLOWS_CLEARED` | `0` | `0` | **PASS** | Active flows in state table must be 0 after flush and shutdown. |
| `INV_2_CREATION_COMPLETION_CONSERVATION` | `24` | `24` | **PASS** | flows_created must equal flows_completed at final teardown. |
| `INV_3_COMPLETED_FLOWS_DECOMPOSITION` | `24` | `24` | **PASS** | flows_completed must equal expired + closed_tcp + evicted + flushed. |
| `INV_4_QUEUE_INGESTION_CONSERVATION` | `24` | `24` | **PASS** | flows_queued must equal flows_completed - flows_queue_dropped. |
| `INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION` | `24` | `24` | **PASS** | flows_queued must equal scored + rejected + val_errors + infer_failures + unprocessed. |
| `INV_6_ALERT_PERSISTENCE_BOUNDS` | `<= 0` | `0` | **PASS** | alerts_persisted + persistence_failures must not exceed total anomalies_detected. |
| `INV_7_PIPELINE_JOIN_CLEAN` | `False` | `False` | **PASS** | Pipeline thread must terminate cleanly without join timeout. |
| `INV_8_NATIVE_KERNEL_DROPS_HONESTY` | `UNAVAILABLE` | `UNAVAILABLE (Native Npcap C wrapper required)` | **PASS** | Native kernel drops must be reported as UNAVAILABLE, never conflated with queue drops. |

---

## 3. Telemetry Sample Timeline

| Elapsed (s) | RSS Memory (MB) | CPU % | Queue Depth | Completed Flows | Scored Flows | Anomalies |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 2.2 | 315.94 | 65.5 | 0 | 0 | 0 | 0 |
| 3.2 | 341.92 | 74.3 | 0 | 1 | 1 | 0 |
| 4.2 | 342.01 | 10.9 | 0 | 24 | 24 | 0 |