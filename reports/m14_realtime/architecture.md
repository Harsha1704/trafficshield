# TrafficShield M14 Real-Time — System Architecture & Data Flow

**Milestone:** M14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts  
**Date:** 2026-10-23  
**Status:** COMPLETE & VERIFIED  

---

## 1. Architectural Blueprint

The real-time detection pipeline operates as an asynchronous, decoupled multi-stage system:

```
                                  [Packet Ingress Layer]
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
          +───────────────────────+                     +───────────────────────+
          |   PcapReplaySource    |                     |   LiveCaptureSource   |
          |  (Offline .pcap /     |                     |  (Passive Promiscuous |
          |   speed pacing)       |                     |   Sniffing via Driver)|
          +───────────────────────+                     +───────────────────────+
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            ▼
                           +─────────────────────────────────+
                           |     PacketEnvelope Stream       |
                           |   (Zero Raw Payload Retention)  |
                           +─────────────────────────────────+
                                            │
                                            ▼
                           +─────────────────────────────────+
                           |    UnidirectionalFlowBuilder    |
                           |   - Key: (src,dst,sport,dport,p)|
                           |   - Idle Timeout Expiration     |
                           |   - Max Lifetime & Size Bounds  |
                           |   - TCP FIN/RST Closure         |
                           |   - RFC 3550 Jitter Calculation |
                           +─────────────────────────────────+
                                            │
                                            ▼
                           +─────────────────────────────────+
                           |  Bounded Flow Queue (Max 10,000)|
                           +─────────────────────────────────+
                                            │
                                            ▼
                           +─────────────────────────────────+
                           |    StreamingInferenceWorker     |
                           |   - ProductionInferenceService  |
                           |   - Decision Threshold (0.50)   |
                           |   - Tree Feature Attributions   |
                           +─────────────────────────────────+
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
          +───────────────────────+                     +───────────────────────+
          |  Deduplicated Alert   |                     | In-Memory Ring Buffer |
          |  Persistence          |                     | (Latest 200 Scored    |
          |  (SecurityAlert SQL)  |                     |  Events for Web UI)   |
          +───────────────────────+                     +───────────────────────+
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            ▼
                           +─────────────────────────────────+
                           |   React Dark SOC Command Center |
                           |   (Live Detection Panel & Stream|
                           |    Auto-refresh 1000ms polling) |
                           +─────────────────────────────────+
```

---

## 2. Key Subsystem Responsibilities

### 1. Packet Source Abstraction (`ingestion/capture/`)
- **`PacketSource` Interface:** Base contract providing `start()`, `stop()`, `pause()`, `resume()`, `packets()`, and `get_metrics()`.
- **`PcapReplaySource`:** Reads `.pcap` / `.pcapng` files with rate pacing ($1\times, 2\times, 5\times, 10\times, \text{max}$). Validates magic bytes and file integrity.
- **`LiveCaptureSource`:** Interfaces directly with physical network interfaces. Enforces native driver verification (`wpcap.dll` on Windows, `libpcap.so` on Linux). Rejects unprivileged or driver-missing execution without silent simulation.
- **`PacketEnvelope`:** Sanitized header tuple. Raw packet payloads are never stored.

### 2. Unidirectional Flow Builder (`ingestion/flow/`)
- **Directional Key:** `(src_ip, dst_ip, src_port, dst_port, protocol)`. Forward-direction traffic is never merged with return packets.
- **RFC 3550 Jitter:** Implements the standard moving average jitter:
  $$D(i, j) = |(R_j - R_i) - (S_j - S_i)|, \quad J \leftarrow J + \frac{|D| - J}{16}$$
- **Lifecycle Management:**
  - `idle_timeout_seconds` (default: 2.0s): Flushes inactive flows.
  - `max_flow_lifetime_seconds` (default: 60.0s): Limits long-lived flow age.
  - `max_active_flows` (default: 10,000): Enforces bounded memory by evicting the least recently updated flow if capacity is reached.
  - `TCP FIN / RST`: Immediately finalizes the flow without timeout delay.

### 3. Streaming Inference Worker (`streaming/inference_worker.py`)
- Reads finalized flow records from bounded thread-safe queue.
- Executes inference through the frozen `ProductionInferenceService`.
- Verifies model SHA-256 (`c43bb5cabd84...`) and preprocessor SHA-256 (`effe96e1977c...`).
- Persists anomalies ($S \ge 0.50$) into `SecurityAlert` database table with deduplication window (10.0s) to prevent alert fatigue.
- Maintains in-memory circular buffer of the latest 200 events for non-blocking UI streaming.

### 4. Lifecycle Supervisor (`streaming/manager.py`)
- Singleton `RealTimeDetectionManager` managing single active session state: `STOPPED`, `STARTING`, `RUNNING`, `PAUSED`, `DEGRADED`, `FAILED`.
- Protects against duplicate concurrent session starts.
- Provides unified telemetry snapshot to REST API.
