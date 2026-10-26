# TrafficShield — End-to-End Backend Telemetry & Accounting Audit

**Milestone:** Master Completion Mission — Phase 2  
**Date:** 2026-10-26  
**Repository:** `D:\projects\trafficshield`  
**Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`**

---

## 1. Architectural Telemetry Pipeline Overview

TrafficShield tracks telemetry across six sequential architectural boundaries:
1. **Packet Ingestion (`LiveCaptureSource` / `PcapReplaySource`):** Captures raw frames, applies BPF filters, validates IPv4 structure, reconstructs IP fragments, drops corrupt frames, and queues parsed `PacketEnvelope` objects.
2. **Driver Level (`NativeStatsAdapter`):** Reads kernel driver statistics (`pcap_stats()`) via ctypes `c_int` C ABI without opening secondary capture sessions.
3. **Flow Reconstruction (`UnidirectionalFlowBuilder`):** Aggregates envelopes into unidirectional 5-tuple flows, manages active flow hash tables, expires timed-out flows, handles TCP FIN/RST closures, and flushes residual flows on teardown.
4. **Flow Queue Ingestion (`RealTimeDetectionManager`):** Safely places completed flows onto `flow_queue` with non-blocking overflow tracking (`flows_queue_dropped`).
5. **Inference Pipeline (`StreamingInferenceWorker`):** Validates the 13-feature contract, transforms features via RobustScaler, executes XGBoost scoring, and records mutually exclusive terminal outcomes.
6. **Alert Persistence & Deduplication (`StreamingInferenceWorker`):** Filters flows above threshold 0.50, manages a 60-second in-memory LRU deduplication window, attempts database persistence, and isolates persistence failures.

---

## 2. Formal Accounting Equations & Conservation Laws

Every telemetry metric satisfies strict conservation equations across all runtime states (running, paused, stopped, drained, or hung).

```mermaid
flowchart TD
    NIC["Driver Packet Filter"] -->|ps_recv| KERNEL["Kernel Capture Buffer"]
    KERNEL -->|ps_drop (Tier 1)| K_DROP["Kernel Drops (native_kernel_drops)"]
    KERNEL -->|Envelopes| INGEST["LiveCaptureSource Queue"]
    INGEST -->|Queue Full (Tier 2)| P_DROP["packets_dropped"]
    INGEST -->|Valid Envelopes| BUILDER["UnidirectionalFlowBuilder"]
    
    BUILDER -->|flows_created| ACTIVE["Active Flows"]
    ACTIVE -->|Timeout / Closed / Flush| COMP["flows_completed"]
    
    COMP -->|Queue Ingestion| Q_INGEST["flow_queue.put_nowait()"]
    Q_INGEST -->|Queue Full (Tier 3)| Q_DROP["flows_queue_dropped"]
    Q_INGEST -->|Enqueued Flows| FLOW_Q["Worker Flow Queue (flows_queued)"]
    
    FLOW_Q -->|Worker Scoring| WORKER["StreamingInferenceWorker"]
    WORKER -->|Scored Benign / Anomaly| SCORED["flows_scored"]
    WORKER -->|Incompatible Feature Schema| REJECT["incompatible_flows_rejected"]
    WORKER -->|Validation Exception| V_ERR["validation_errors"]
    WORKER -->|Inference Exception| I_FAIL["inference_failures"]
    WORKER -->|Shutdown Timeout Residue| UNPROC["unprocessed_flows"]
```

### 2.1 Flow Conservation Laws

#### Equation 1: Flow Completion Conservation
$$\text{flows\_completed} = \text{flows\_expired\_timeout} + \text{flows\_closed\_tcp} + \text{flows\_evicted\_overflow} + \text{flows\_flushed}$$
- **Verification:** Verified in [`UnidirectionalFlowBuilder`](file:///d:/projects/trafficshield/ingestion/flow/flow_builder.py). Every completed flow is categorized into exactly one expiration or closure pathway. On graceful shutdown, `flush()` evacuates all active table entries to `flows_flushed`, leaving `active_flows_count == 0`.

#### Equation 2: Flow Queue Conservation
$$\text{flows\_completed} = \text{flows\_queued} + \text{flows\_queue\_dropped}$$
- **Verification:** Handled in [`RealTimeDetectionManager._on_flow_completed()`](file:///d:/projects/trafficshield/streaming/manager.py). Completed flows are submitted via `put_nowait()`. Saturated queue capacity increments `flows_queue_dropped`; successful placements increment `flows_queued`.

#### Equation 3: Inference Worker Terminal Outcome Conservation
$$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$
- **Verification:** Verified in [`StreamingInferenceWorker`](file:///d:/projects/trafficshield/streaming/inference_worker.py). Outcomes are strictly mutually exclusive:
  - `flows_scored`: Feature schema valid, transformer succeeded, model returned score.
  - `incompatible_flows_rejected`: Missing required features or invalid sTTL.
  - `validation_errors`: Schema validation exception during extraction.
  - `inference_failures`: Runtime exception during transformer or model execution.
  - `unprocessed_flows`: Flows remaining on queue if worker loop exits prematurely or timeout expires.

### 2.2 Alert Persistence & Deduplication Conservation

For all flows where $\text{anomaly\_score} \ge 0.50$, an anomaly is registered:
$$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated} + \text{alerts\_unpersisted\_no\_app}$$
- `alerts_persisted`: Successfully committed to SQLite database within Flask application context.
- `alerts_deduplicated`: Identical 5-tuple anomaly observed within the 60.0-second sliding deduplication window.
- `persistence_failures`: Database connection failure, locking conflict, or SQL exception during commit.
- `alerts_unpersisted_no_app`: Worker running in standalone headless/test mode without an active Flask app context.

### 2.3 Tiered Drop Accounting Isolation

| Drop Tier | Counter Name | Collection Point | Hardware / Software Location |
| :--- | :--- | :--- | :--- |
| **Tier 1 (Kernel Buffer Drops)** | `native_kernel_drops` | `pcap_stats()` via ctypes | Npcap / WinPcap kernel filter driver buffer |
| **Tier 2 (Packet Queue Drops)** | `packets_dropped` | `LiveCaptureSource._queue` | Ingestion thread packet queue (capacity 5,000) |
| **Tier 3 (Flow Queue Drops)** | `flows_queue_dropped` | `RealTimeDetectionManager.flow_queue` | Inference worker flow queue (capacity 10,000) |

---

## 3. API Serialization & Null Preservation

Endpoint `/api/v1/capture/status` ([`app/api/v1/capture.py`](file:///d:/projects/trafficshield/app/api/v1/capture.py)) serializes the full operational status payload:
- **Null Safety:** Missing or unavailable metrics (`native_kernel_drops`, `native_interface_drops`, `poll_interval_seconds`) strictly serialize as JSON `null`, never converting silently to `0`.
- **Status Provenance:** Provides explicit status strings (`kernel_drop_status: "UNAVAILABLE (PCAP replay is an offline file source)"`).
- **Driver Health:** Explicitly provides `native_interface_drops_supported: false` on Windows, preventing clients from misinterpreting unsupported NIC counters as zero drops.
- **Security & Authorization:** Route protected by session/token verification where configured; administrative control endpoints (`/start-live`, `/start-replay`, `/stop`, `/pause`, `/resume`) require `analyst` or `admin` role authorization.

---

## 4. Test Evidence & Coverage Summary

Deterministic coverage across:
- `tests/unit/test_m17_1_accounting_audit.py`: 15 / 15 passed (100%)
- `tests/unit/test_m18_native_stats.py`: 10 / 10 passed (100%)
- `tests/unit/test_m19_integrity_audit.py`: 15 / 15 passed (100%)
- `tests/unit/test_m15_4_shutdown_edge_cases.py`: 13 / 13 passed (100%)
- Full Backend Suite: 576 / 576 passed (100%)
