# TrafficShield M15 — Operational Measurements & Resource Limits

**Document ID:** TS-M15-METRICS  
**Date:** 2026-10-26  
**Status:** VERIFIED (PASS)  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Memory bounding specifications, queue high-water marks, PCAP replay performance benchmarks, and physical live capture operational measurements.

---

## 1. System Memory & Queue Bounding Architecture

To prevent memory leaks or resource exhaustion under high-throughput network streams, TrafficShield enforces strict bounds at every stage of the pipeline:

| Component | Architecture Construct | Bound Specification | Eviction / Overflow Behavior |
|:---|:---|:---:|:---|
| **Capture Queue** | `queue.Queue[PacketEnvelope]` | `maxsize = 5000` | Non-blocking drop; increments `packets_dropped`. Emits periodic log warning. |
| **Fragment Engine** | `BoundedFragmentReassembler` | `max_in_flight = 500` | LRU eviction of oldest incomplete datagram; increments `dropped_capacity`. |
| **Active Flow State** | `UnidirectionalFlowBuilder` | `max_active_flows = 10000` | LRU eviction of least recently updated flow; increments `flows_evicted_overflow`. |
| **Idle Flow State** | `ActiveFlowState` | `idle_timeout = 2.0s` | Finalized and emitted on timeout; increments `flows_expired_timeout`. |
| **Max Flow Lifetime**| `ActiveFlowState` | `max_lifetime = 60.0s` | Finalized to prevent unbounded TCP sessions. |
| **Recent Event Buffer**| `collections.deque` | `maxlen = 200` | Circular buffer; drops oldest events to maintain constant memory footprint. |
| **Alert Dedup Cache** | `dict[str, float]` | `max_keys = 2000` | Pruned when exceeding 2,000 keys; 60.0s expiration window. |

---

## 2. Live Network Operational Measurements (Wi-Fi Physical Capture)

Live network performance measurements obtained during 24.1s active monitoring on Realtek RTL8852BE WiFi 6 PCIe Adapter:

| Metric Category | Measured Parameter | Measured Value | Unit / Scale |
|:---|:---|:---:|:---:|
| **Capture Duration** | Active Sniffing Window | **24.1** | seconds |
| **Packet Throughput** | Total Packets Processed | **8,259** | packets |
| **Throughput Rate** | Ambient Packet Rate | **342.7** | packets / second |
| **Packet Loss** | Packets Dropped (Queue Full) | **0** | packets ($0.0\%$) |
| **Malformed Traffic** | Malformed Headers Detected | **0** | packets |
| **Flow Generation** | Directional Flows Completed | **757** | flows |
| **Flow Processing Rate**| Completed Flows / Sec | **31.4** | flows / second |
| **Inference Scaling** | Flows Evaluated by Detector | **668** | flows |
| **Anomalies Detected** | Anomaly Classification ($P \ge 0.50$) | **431** | flows |
| **Alerts Persisted** | Unique Alerts in SQLite WAL | **241** | alerts (`source="LIVE_CAPTURE"`) |
| **Single-Flow Latency**| Feature Prep + XGBoost Prediction | **6.68** | ms (mean) |
| **Persistence Latency**| SQLite WAL Alert Insert | **3.12** | ms (mean) |
| **Queue High-Water** | Peak Queue Occupancy | **42 / 5,000** | packets ($0.84\%$ capacity) |
| **Worker Shutdown** | Thread Teardown & Join Latency | **42** | ms |

---

## 3. Benchmark Operational Measurements (PCAP Ingestion Pipeline)

Performance measurements captured during replay of `data/captures/sample_traffic.pcap`:

| Metric Category | Measured Parameter | Measured Value | Unit / Scale |
|:---|:---|:---:|:---:|
| **Packet Throughput** | Total Packets Processed | **29** | packets |
| **Packet Loss** | Packets Dropped (Queue Full) | **0** | packets ($0.0\%$) |
| **Malformed Traffic** | Malformed Headers Detected | **0** | packets |
| **Flow Generation** | Total Flows Completed | **24** | flows |
| **Inference Scaling** | Flows Evaluated by Detector | **24** | flows ($100.0\%$) |
| **Incompatible Flows**| Flows Rejected (Missing TTL/Coords)| **0** | flows |
| **Single-Flow Latency**| Feature Prep + XGBoost Prediction | **1.84** | ms (mean) |
| **Persistence Latency**| SQLite WAL Alert Insert | **2.65** | ms (mean) |
| **Process Memory (RSS)**| Base Working Set Memory | **185.4** | MB |
| **Memory Peak (Replay)**| Peak Working Set Memory | **192.1** | MB |
| **Worker Shutdown** | Thread Teardown & Join Latency | **< 50** | ms |
