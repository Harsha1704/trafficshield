# TrafficShield M15.3 — Live Wi-Fi Smoke Test & Telemetry Audit

**Document ID:** TS-M15.3-LIVE-SMOKE  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Telemetry record of genuine passive live-capture execution on Realtek RTL8852BE WiFi 6 adapter before, during, and after orderly shutdown.

---

## 1. Test Environment & Execution Parameters

- **Interface:** `Wi-Fi` (Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter, IPv4 `10.36.105.217`)
- **Driver:** Npcap WinPcap-compatible mode (`\Device\NPF_{57B0B12B-DBD6-4A1F-889F-10662755578B}`)
- **Capture Window:** **35.0 seconds** (Ambient local wireless network traffic)
- **BPF Filter:** `ip`
- **Application Context:** Flask development application (`app/`) with SQLite WAL database (`trafficshield_dev.db`)
- **Safety Policy:** Strictly passive inspection. Zero packet injection, port scanning, or subnet probing. Zero raw payload retention.

---

## 2. Telemetry Comparison: Before, During, and After Shutdown

| Telemetry Parameter | Before Capture Start | Right Before Stop | After Orderly Stop | Delta / Final |
|:---|:---:|:---:|:---:|:---:|
| **Worker State** | `STOPPED` | `RUNNING` | `STOPPED` | Clean lifecycle transition |
| **Elapsed Time** | $0.0\text{ s}$ | $35.0\text{ s}$ | $35.0\text{ s}$ | $35.0\text{ s}$ active |
| **Packets Received** | 0 | 11,506 | **11,506** | **328.7 packets/sec** |
| **Application Queue Drops** | 0 | 0 | **0 (0.0%)** | Zero packet drops |
| **Queue High-Water Mark** | 0 | 0 | **8 / 5,000** | **$0.16\%$ peak queue occupancy** |
| **Malformed Packets Rejected** | 0 | 1 | **1** | Truncated wire header |
| **Truncated / Unsupported** | 0 | 0 | **0** | Standard IPv4 frames |
| **Active Flows in Builder** | 0 | 51 | **0** | **51 flushed at stop** |
| **Flows Created** | 0 | 884 | **884** | Forward 5-tuples |
| **Flows Completed** | 0 | 833 | **884** | $833 \text{ (live)} + 51 \text{ (flushed)}$ |
| **Flows Flushed at Shutdown** | 0 | 0 | **51** | All active flows finalized |
| **Flows Queued** | 0 | 833 | **884** | $833 + 51 = 884$ |
| **Flows Scored by Model** | 0 | 833 | **884** | **$100.0\%$ scored (0 unscored)** |
| **Incompatible Flows Rejected**| 0 | 0 | **0** | All positive TTL ($sttl > 0$) |
| **Validation Failures** | 0 | 0 | **0** | Zero schema errors |
| **Inference Failures** | 0 | 0 | **0** | Zero XGBoost exceptions |
| **Persistence Failures** | 0 | 0 | **0** | Zero database write errors |
| **Unprocessed Flows** | 0 | 0 | **0** | **Zero unscored gap** |
| **Anomalies Detected ($\tau=0.50$)**| 0 | 442 | **466** | $52.7\%$ anomaly rate |
| **Alerts Persisted in SQLite** | 0 | 271 | **289** | Deduplicated across 10s window |
| **Mean Inference Latency** | *N/A* | $6.38\text{ ms}$ | **$6.35\text{ ms}$** | Real-time SLA verified |
| **Orderly Teardown Latency** | *N/A* | *N/A* | **$335.28\text{ ms}$** | Thread join & queue drain |

---

## 3. Second-by-Second Queue & Processing Profile

During the 35.0-second capture run, real-time status was polled at 1.0-second intervals:

```
[Time]  Packets   Flows Built   Flows Scored   Queue Depth   Worker Status
 3.1s       164             9              9             0   RUNNING
 6.1s       565            78             78             0   RUNNING
 9.1s      2960           131            130             1   RUNNING
12.1s      3252           199            199             0   RUNNING
15.1s      3490           308            308             0   RUNNING
18.1s      3680           363            361             1   RUNNING
21.1s      4744           448            448             0   RUNNING
24.2s      6034           507            507             0   RUNNING
27.2s      7168           561            559             1   RUNNING
28.2s      7398           637            628             8   RUNNING (Transient burst)
29.2s      7647           682            682             0   RUNNING (Burst drained)
32.2s     10015           754            751             2   RUNNING
35.2s     11506           833            833             0   RUNNING
STOP       --             884 (+51)      884 (+51)       0   STOPPED (Drained in 335ms)
```

### Key Operational Observations:
1. **Queue Stability:** Ingestion averaged ~328 pkts/sec. The inference worker consumed flows concurrently with an average latency of 6.35 ms. The queue depth remained at 0 for 88% of samples, with a peak burst depth of only 8 items.
2. **Orderly Drain Execution:** Right before `stop()` was signaled, 51 flows were active in `UnidirectionalFlowBuilder`. When `manager.stop()` was invoked:
   - Pipeline thread stopped packet ingestion.
   - Flow builder flushed the 51 active flows into the queue.
   - Inference worker consumed and scored all 51 flows up to sentinel `None`.
   - The entire teardown, drain, and thread join completed in **335.28 ms**.
   - `unprocessed_flows = 0`.
