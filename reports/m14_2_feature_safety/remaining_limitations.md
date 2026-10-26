# TrafficShield M14.2 — Remaining Operational Limitations & Technical Boundaries

**Milestone:** M14.2 — Feature Fidelity and Malformed-Packet Safety Gate  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **TRANSPARENTLY DOCUMENTED**  

---

## 1. Executive Summary

In adherence to TrafficShield's defensibility guidelines, this report catalogues the operational limits, physical boundaries, and intentional architectural constraints of the hardened real-time detection pipeline following Milestone 14.2.

---

## 2. Hardware & Host Driver Dependency

| Limitation | Technical Context | Operational Behavior |
| :--- | :--- | :--- |
| **Npcap / WinPcap Dependency** | Real-time promiscuous sniffing on physical network adapters on Windows requires the Npcap kernel driver (`wpcap.dll`). | On this evaluation host where `wpcap.dll` is absent, [`is_capture_driver_available()`](file:///D:/projects/trafficshield/ingestion/capture/live_source.py#L38) evaluates to `False`. The system cleanly blocks live capture requests (HTTP 400 `DRIVER_NOT_FOUND`) and displays an amber alert banner on the dashboard. **The system never fabricates simulated packets.** |
| **Offline PCAP Replay** | Does not require kernel drivers or raw socket privileges. | Replays offline binary PCAP/PCAPNG files with microsecond pacing in user space with 100% reproducibility. |

---

## 3. Incomplete & Expired Fragment Exclusion

| Limitation | Technical Context | Operational Behavior |
| :--- | :--- | :--- |
| **Fragment Reassembly Timeout (3.0s)** | If fragments of a datagram are delayed beyond 3.0s or dropped by the network, reassembly cannot complete. | Stale fragment buffers are purged from memory, counted as `dropped_timeout`, and **excluded from model inference**. They are never evaluated as phantom port 0 flows. |
| **Buffer Capacity Bound (500 Datagrams)** | Memory bound prevents fragment buffer exhaustion attacks (e.g., Rose attack). | When capacity is reached, the oldest in-flight buffer is evicted (`dropped_capacity`) and safely discarded without model scoring. |

---

## 4. Directional Blindness (Architectural Invariant)

| Limitation | Technical Context | Operational Behavior |
| :--- | :--- | :--- |
| **Unidirectional Vantage Point** | TrafficShield monitors unidirectional ingress/egress links (optical TAPs, data diodes, asymmetric ISP routing). | The detector cannot observe return SYN-ACK packets, TCP acknowledgments, or server response bodies. All reverse-link features are strictly prohibited by feature policy. Handshake completion is inferred causally from forward data transmission. |

---

## 5. Storage Persistence Throughput

| Limitation | Technical Context | Operational Behavior |
| :--- | :--- | :--- |
| **SQLite Concurrency Limits** | The SQLite database (`trafficshield.db`) utilizes Write-Ahead Logging (WAL) and 10-second 5-tuple alert deduplication. | For sustained carrier-grade enterprise ingestion exceeding 1,000 persistent alerts per second, SQLite database file lock contention can occur. Migration to PostgreSQL via `DATABASE_URL` is recommended for high-volume production deployments. |
