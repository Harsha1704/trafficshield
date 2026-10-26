# TrafficShield M15.4 — Remaining Operational Risks & Engineering Roadmap

**Document ID:** TS-M15.4-REMAINING-RISKS  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M15.4 Shutdown Edge-Case Verification & Concurrency Hardening  

---

## 1. Executive Summary

Milestone 15.4 successfully validated that the shutdown sequences, worker consumption loops, flow builder synchronization, and flow accounting invariants operate with zero deadlocks, zero orphaned threads, and zero untracked flows across 13 deterministic failure and concurrency scenarios.

However, advancing from a local demonstration capability to an enterprise-grade production Release Candidate (RC) requires addressing specific operational boundaries that cannot be proven by short smoke tests or deterministic unit test doubles.

---

## 2. Identified Operational Risks & Boundaries

### 2.1 Multi-Hour Soak Testing Under Live Ambient Load
- **Risk:** While unit tests confirm that circular buffers (`recent_events` maxlen 200, deduplication cache) and flow tables enforce bounds, long-term memory accumulation (e.g. fragment reassembly state, SQLite WAL file growth, Python heap fragmentation) can only be certified through multi-hour continuous capture.
- **Current Mitigation:** Bounded structures are enforced in code.
- **Path to RC:** Execute a continuous 2-to-4 hour authorized live capture soak test to measure RSS memory plateauing.

---

### 2.2 Kernel-Space Packet Drop Visibility
- **Risk:** User-space queue drops are now strictly tracked via `flows_queue_dropped` and `packets_dropped` in Scapy/Python. However, under high line-rate bursts ($> 100,000 \text{ pkts/sec}$), the underlying Npcap/WinPcap kernel ring buffer can drop packets before user-space Python receives them.
- **Current Mitigation:** Python application queue depth is monitored; max observed depth on ambient Wi-Fi was 8 / 5,000.
- **Path to RC:** Implement a lightweight ctypes wrapper around Npcap's native C function `pcap_stats()` in `LiveCaptureSource` to poll and expose kernel ring buffer drops (`ps_drop`, `ps_ifdrop`).

---

### 2.3 Local Wi-Fi Link vs Routed SPAN Gateway Domain Shift
- **Risk:** The frozen production model was trained on routed unidirectional traffic with multi-hop decremented initial TTLs. On an unrouted local 802.11 Wi-Fi interface, link-local multicast (mDNS, SSDP, LLMNR) and host-local unicast emit default OS TTLs (128 for Windows, 255 for multicast). This generates an expected domain shift resulting in elevated benign anomaly scores.
- **Current Mitigation:** Analysis in M15.3 and M15.4 proved that the model is functioning exactly as trained, but the ambient local link traffic does not represent routed perimeter network traffic.
- **Path to RC:** Certify live capture on an enterprise routed SPAN or network TAP port, where routed transit decrements TTLs into the model's normal operational zone ($< 3.5\%$ false positive rate).
