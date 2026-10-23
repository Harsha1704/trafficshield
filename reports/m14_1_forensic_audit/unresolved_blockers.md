# TrafficShield M14.1 — Unresolved Blockers & Operational Limitations

**Milestone:** M14.1 — Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **TRANSPARENTLY DOCUMENTED**  

---

## 1. Executive Summary

In adherence to TrafficShield's core safety and integrity mandate, this document records all unresolved operational blockers, hardware/driver dependencies, and mathematical limitations discovered during the Milestone 14.1 forensic audit.

No limitation is obscured or masked by synthetic simulation.

---

## 2. Active Blocker: Live Interface Promiscuous Sniffing

| Dimension | Audit Finding |
| :--- | :--- |
| **Component** | [`ingestion/capture/live_source.py:LiveCaptureSource`](file:///D:/projects/trafficshield/ingestion/capture/live_source.py) |
| **Root Cause** | Host environment (Windows 11) lacks native packet capture driver dynamic libraries (`wpcap.dll`, `Packet.dll`). |
| **Failure Mode** | [`is_capture_driver_available()`](file:///D:/projects/trafficshield/ingestion/capture/live_source.py#L18) evaluates to `False`. Calling `start_live()` raises `DriverNotFoundError` / `RuntimeError`. |
| **API Response** | `POST /api/v1/capture/start-live` fails cleanly with HTTP 400 (`DRIVER_NOT_FOUND`). |
| **UI Presentation** | React command center surfaces prominent amber warning banner and disables live capture button. |
| **Anti-Simulation Policy** | System **never** falls back to fake traffic counters or synthetic socket emulation. |
| **Resolution Path** | Requires manual installation of [Npcap](https://npcap.com/#download) with "WinPcap API-compatible Mode" enabled by an administrator. |
| **Release Gate Verdict** | **NOT RUN (DRIVER BLOCKED)** for live capture. |

---

## 3. Technical Limitation: IP Packet Fragmentation

| Dimension | Audit Finding |
| :--- | :--- |
| **Component** | [`ingestion/flow/flow_builder.py:UnidirectionalFlowBuilder`](file:///D:/projects/trafficshield/ingestion/flow/flow_builder.py) |
| **Mechanism** | IPv4 fragmentation slices large datagrams across multiple packets with `flags="MF"` or `frag_offset > 0`. |
| **Parser Behavior** | Initial fragment contains TCP/UDP headers and is keyed under the true 5-tuple. Subsequent fragments lack transport headers and are keyed under protocol `"OTHER"` with port 0. |
| **Stability Impact** | Zero crashes. Both fragments are preprocessed and scored cleanly as independent flows. |
| **Semantic Impact** | Flow byte totals are split across two flow records rather than reassembled into one large datagram. |
| **Production Recommendation** | In high-MTU enterprise environments with frequent fragmentation, a kernel-level IP defragmentation reassembly buffer should precede flow extraction. |
| **Release Gate Verdict** | **KNOWN LIMITATION (STABLE)**. |

---

## 4. Mathematical Variance: Small-Flow `sload` Convergence Bias

| Dimension | Audit Finding |
| :--- | :--- |
| **Component** | `ActiveFlowState.finalize()` in [`ingestion/flow/flow_builder.py`](file:///D:/projects/trafficshield/ingestion/flow/flow_builder.py#L76) |
| **Variance** | Argus training formula: `(sbytes - first_packet_bytes) * 8 / dur`. Live formula: `(fwd_bytes * 8) / dur`. |
| **Divergence Range** | Flows with $N=2$ packets exhibit $2\times$ difference; flows with $N \ge 20$ packets exhibit $< 5\%$ difference. |
| **Model Invariance Impact** | `RobustScaler` scales `sload` monotonically. Ordinal decision splits in `XGBClassifier` minimize sensitivity for sustained traffic. |
| **Safety Mandate** | Production model and preprocessor are strictly frozen and **never** retrained. |
| **Release Gate Verdict** | **DOCUMENTED CONVERGENCE BIAS**. |

---

## 5. Architectural Invariant: Unidirectional Observability Blindness

| Dimension | Audit Finding |
| :--- | :--- |
| **Principle** | Unidirectional monitoring links (optical TAPs, data diodes) observe one-way traffic only. |
| **Enforcement** | All reverse-link features (`bwd_packets`, `dload`, `dbytes`, `tcprtt`) are strictly prohibited and rejected by `features.policy.audit_columns` (HTTP 422). |
| **Blindness** | System cannot determine whether TCP handshakes completed, whether HTTP responses succeeded, or whether packets reached the server. |
| **Release Gate Verdict** | **ARCHITECTURAL INVARIANT (BY DESIGN)**. |

---

## 6. Persistence Boundary: SQLite Concurrency Under High Load

| Dimension | Audit Finding |
| :--- | :--- |
| **Component** | SQLite `security_alerts` table in [`app/database/models.py`](file:///D:/projects/trafficshield/app/database/models.py) |
| **Mitigations** | Write-Ahead Logging (WAL) enabled; 10-second 5-tuple deduplication window suppresses redundant writes. |
| **Upper Bound** | Sustained bursts $> 1,000$ new anomalous flows/second can induce SQLite database lock contention. |
| **Production Recommendation** | Enterprise deployments with sustained Gigabit volumetric attacks should switch `DATABASE_URL` to PostgreSQL. |
| **Release Gate Verdict** | **BOUNDED OPERATIONAL LIMITATION**. |
