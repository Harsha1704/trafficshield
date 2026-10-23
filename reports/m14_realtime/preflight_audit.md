# TrafficShield M14 Real-Time — Preflight Audit & Prediction Path Trace

**Milestone:** M14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Status:** COMPLETE  

---

## 1. Trace of Current Prediction & Alerting Path

Before implementing the real-time capture and streaming detection engine, the end-to-end detection path through the existing codebase was forensically traced:

```
[Client / Analyst]
       │
       ▼
1. HTTP Ingestion:
   - POST /api/v1/predict (Single flow dict)
   - POST /api/v1/predict/batch (List of flow dicts up to 10,000)
       │
       ▼
2. Directional Feature Policy Validation (`ml.production_service.validate_and_prepare_input`):
   - Calls `features.policy.audit_columns(cols)`
   - Blocks reverse-link columns (`bwd_packets`, `dload`, `dbytes`, `tcprtt`) with `PolicyViolationError` (HTTP 422)
   - Blocks ground-truth evaluation labels (`label`, `attack_cat`) with `PolicyViolationError` (HTTP 422)
   - Validates existence of the 10 forward-observable base features
   - Computes causal rates:
     * packet_rate = fwd_packets / duration_seconds (0.0 if dur = 0)
     * byte_rate = fwd_bytes / duration_seconds (0.0 if dur = 0)
     * bytes_per_packet = fwd_bytes / fwd_packets (0.0 if pkts = 0)
       │
       ▼
3. Preprocessing Transformation (`production_preprocessor.joblib`):
   - Cryptographically verified SHA-256 before loading:
     `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`
   - Transforms 13 features via `RobustScaler` / quantile transform
       │
       ▼
4. Model Scoring & Decision Threshold (`production_detector.joblib`):
   - Cryptographically verified SHA-256 before loading:
     `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
   - Computes continuous probability anomaly score: $S \in [0.0, 1.0]$
   - Applies decision threshold $\tau = 0.50$:
     * Anomaly: $S \ge 0.50$
     * Risk Level: CRITICAL ($\ge 0.85$), HIGH ($\ge 0.65$), MEDIUM ($\ge 0.50$), LOW ($< 0.50$)
   - Calculates tree-based feature attributions for top-contributing drivers
       │
       ▼
5. SOC Alert Persistence (`app.database.models.SecurityAlert`):
   - When an anomaly is detected, an alert record is created:
     * `timestamp`: Event UTC timestamp
     * `anomaly_score`, `decision_threshold`, `risk_level`
     * `model_name`, `model_version` ("1.0.0")
     * `status`: "NEW" (investigation lifecycle: NEW -> INVESTIGATING -> RESOLVED)
     * `source`: e.g. "batch_upload", "PCAP_REPLAY", "LIVE_CAPTURE"
     * `input_features`, `top_contributing_features`
     * `protocol`, `src_port`, `dst_port`
     * `is_demo`: False
       │
       ▼
6. SOC Dashboard Presentation (`frontend/`):
   - React 18 + TypeScript + Vite + Tailwind CSS
   - Alerts displayed in Alert Center table with search, status filters, and investigation drawer
   - Monitoring tab tracks Population Stability Index (PSI) drift across scoring windows
```

---

## 2. Gap Analysis: Real-Time vs Existing Components

| Subsystem | Existing Capability (M1–M13) | Missing for Real-Time (M14) |
|---|---|---|
| **Packet Capture** | Offline static file upload; Scapy test parser | Dedicated PacketSource abstraction for offline PCAP replay (with speed control & pause/resume) and live passive sniffing |
| **Flow Reconstruction** | Pre-computed CSV flow aggregates | Streaming stateful flow builder with timeout expiration, max concurrent flows, TCP FIN/RST termination, and memory bounds |
| **Worker Architecture** | Synchronous HTTP request-response handlers | Asynchronous decoupled capture worker + inference worker communicating via bounded thread-safe queues |
| **Alert Streaming** | REST polling of `/api/v1/alerts` | Server-Sent Events (SSE) or bounded live telemetry polling endpoint for sub-second dashboard updates |
| **Dashboard UI** | Batch upload and static inspection | Dedicated Live Detection panel with interface selector, worker state machine (`STOPPED`, `STARTING`, `RUNNING`, `DEGRADED`, `FAILED`), and live telemetry metrics |
| **Provenance Tracking** | Static `source` column | Formal provenance enforcement: `PCAP_REPLAY` vs `LIVE_CAPTURE` vs `TEST_FIXTURE`, never calling replay "live" |

---

## 3. Host Environment & Driver Inspection

- **Operating System:** Windows 11 Enterprise (64-bit)
- **Python:** Python 3.14.8 (`python.exe`)
- **Network Interface Enumeration:** Scapy `scapy.arch.windows.get_windows_if_list()` successfully enumerates all real network adapters (Wi-Fi RTL8852BE, Realtek PCIe GbE, Loopback, virtual adapters).
- **Packet Driver Provider:** Native Npcap DLL (`wpcap.dll`) is **absent** on this Windows host.
- **Consequence:** Live interface sniffing is driver-blocked on this physical machine. Offline PCAP replay is fully functional.
- **Rule Enforcement:** The application will truthfully report driver unavailability for live interface sniffing and will **never** simulate fake traffic. Replay mode is verified; live capture is verified via architecture and marked `NOT_RUN` on this host.

---

## 4. Cryptographic Artifact Integrity Verification

The production model artifacts were independently audited before making any changes:

```
Artifact: artifacts/models/production_detector.joblib
SHA-256:  c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495 (MATCH)

Artifact: artifacts/models/production_preprocessor.joblib
SHA-256:  effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653 (MATCH)
```

No changes will be made to these artifacts.
