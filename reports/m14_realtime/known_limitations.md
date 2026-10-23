# TrafficShield M14 Real-Time — Known Limitations & Operational Boundaries

**Milestone:** M14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Status:** COMPLETE  

---

## 1. Executive Summary

This document delineates the technical limitations, hardware/driver dependencies, mathematical boundaries, and operational assumptions of TrafficShield's real-time network capture and streaming detection engine. Truthful documentation of these boundaries is essential for defensible security analytics and prevents operational misuse.

---

## 2. Capture Driver & Kernel Dependencies

### 2.1 OS-Level Packet Driver Availability
- **Windows Dependency:** Real-time live interface capture requires Npcap (in WinPcap compatibility mode) or legacy WinPcap, which installs kernel drivers (`npcap.sys`) and user-space shared libraries (`wpcap.dll`, `Packet.dll`).
- **Linux Dependency:** Requires `libpcap.so.1` or `libpcap.so.0.8`.
- **Failure Mode & Verification:** On hosts lacking these dynamic libraries (e.g., this Windows 11 evaluation environment where `wpcap.dll` is absent), live capture fails immediately and cleanly:
  ```python
  if not is_capture_driver_available():
      raise RuntimeError("Live packet capture requires Npcap or WinPcap (wpcap.dll not found).")
  ```
- **Strict Anti-Simulation Guarantee:** In adherence to TrafficShield integrity guidelines, the system **never** fabricates fake traffic counters or generates synthetic background packets when the driver is unavailable. The gate status is truthfully reported as `NOT RUN (DRIVER BLOCKED)`.
- **PCAP Replay Independence:** Offline PCAP replay does **not** require kernel drivers or raw socket privileges. It uses Scapy's native user-space binary parser `PcapReader`, providing 100% reproducible, deterministic evaluation on any environment.

### 2.2 Privilege Requirements
- Live promiscuous sniffing requires Administrator privileges on Windows or `CAP_NET_RAW` / `CAP_NET_ADMIN` capabilities on Linux.
- Offline PCAP replay operates completely in unprivileged user space.

---

## 3. Directional Blindness & Feature Policy Constraints

### 3.1 Strict Unidirectional Observability
TrafficShield is architecturally hardened for unidirectional network links (e.g., optical TAPs, diode-isolated segments, asymmetric ISP border routing):
- **Zero Reverse-Link Visibility:** The engine cannot observe server SYN-ACK responses, ACK acknowledgments, TCP window scale advertisements, or return payload data.
- **Handshake Indeterminacy:** The system cannot definitively confirm whether a TCP three-way handshake completed or failed unless subsequent forward payload packets appear.
- **Policy Enforcement:** All reverse-direction features (`bwd_packets`, `dload`, `dbytes`, `tcprtt`) and evaluation target labels (`label`, `attack_cat`) are strictly prohibited and blocked by `features.policy.audit_columns`.

### 3.2 Single-Packet & Zero-Duration Flows
- When a flow consists of only a single observed packet (e.g., a lone UDP probe or dropped SYN), `duration_seconds = 0.0`.
- **Rate Clamping:** Causal rate features (`packet_rate = pkts / duration`, `byte_rate = bytes / duration`) are mathematically undefined at zero duration. To prevent `ZeroDivisionError` or infinity values, TrafficShield clamps these rates to `0.0`.
- **Impact on Scoring:** Single-packet flows exhibit distinct feature profiles (duration=0, rate=0, jitter=0). While the tree ensemble handles these non-linearities, analysts should interpret single-packet critical alerts with contextual awareness.

---

## 4. Flow Table State Boundaries & Eviction Under Load

### 4.1 Memory Bounds & LRU Eviction
- The `UnidirectionalFlowBuilder` maintains an active flow table bounded by `max_active_flows` (default: 10,000).
- If state size exceeds 10,000 flows during high-volume traffic bursts, the oldest flow is evicted via LRU policy and finalized for inference.
- **SYN Flood Exposure:** Under severe volumetric SYN-flood attacks with random spoofed source IPs and ports, state table turnover accelerates. Flows may be evicted before reaching their natural idle timeout (2.0s), producing shorter, fragmented flow records.

### 4.2 Timeout Parameter Tuning
- **Idle Timeout (`idle_timeout = 2.0s`):** Flows without new packets for 2 seconds are finalized. For low-rate persistent C2 beaconing with jitter > 2s, each beacon is treated as an isolated single-packet flow.
- **Max Flow Lifetime (`max_flow_lifetime = 60.0s`):** Long-running persistent TCP streams are sliced into 60-second chunks to ensure timely SOC visibility rather than delaying alerting until stream termination.

---

## 5. Storage & Persistence Concurrency Boundaries

### 5.1 SQLite File Locking
- Incident alerts are persisted in SQLite (`security_alerts` table).
- SQLite utilizes file-level locking (`BEGIN IMMEDIATE`). Under extreme ingestion rates with hundreds of concurrent anomalies per second, database lock contention can arise.
- **Mitigation Applied:**
  1. **Write-Ahead Logging (WAL):** Enables concurrent readers while writing.
  2. **Alert Deduplication:** Identical 5-tuples within a 10-second sliding window are suppressed, eliminating redundant database writes during repetitive attack waves.
  3. **Circular In-Memory Buffer:** The streaming worker maintains an in-memory deque (200 records) allowing real-time dashboard polling with zero database read locks.
- **Production Recommendation:** For enterprise carrier-grade deployments exceeding 1,000 sustained alerts/second, the SQLite storage backend should be migrated to PostgreSQL or a distributed time-series engine.

---

## 6. Real-Time Replay Clock Granularity

- In `PcapReplaySource`, packet timing is paced using `time.sleep()`.
- On Windows systems, default kernel timer resolution is typically 10–15.6 ms unless high-resolution multimedia timers (`timeBeginPeriod`) are active.
- For extremely tight packet inter-arrival times (< 1 ms), packet replay may experience slight jitter.
- The `max` speed option bypasses `time.sleep()` entirely, streaming flows directly at full CPU throughput.

---

## 7. Model Invariance Notice

- The production detector (`production_detector.joblib`) and preprocessor (`production_preprocessor.joblib`) were strictly preserved and **never** modified or retrained.
- Model SHA-256: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`.
- Preprocessor SHA-256: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`.
- The real-time pipeline adheres 100% to the exact 13 features and scalers expected by these artifacts.
