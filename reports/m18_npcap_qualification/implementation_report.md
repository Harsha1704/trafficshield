# TrafficShield M18 — Native Npcap Driver Statistics Implementation Report

**Document ID:** TS-M18-NPCAP-IMPL  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M18 Memory Policy Review & Native Npcap Statistics  
**Target Architecture:** Windows 10/11 (Npcap/wpcap.dll) & Linux (libpcap.so)  
**Release Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`** (Maintained)  

---

## 1. Executive Summary

Milestone 18 resolves the longstanding operational gap where kernel driver packet drops were previously reported as `UNAVAILABLE (Native Npcap C wrapper required)`.

A small, non-intrusive, thread-safe statistics adapter ([`NativeStatsAdapter`](file:///d:/projects/trafficshield/ingestion/capture/native_stats.py)) was implemented in `ingestion/capture/native_stats.py`. It interfaces directly with native `wpcap.dll` / `libpcap.so` via `pcap_stats()`, reuses the active live capture socket handle without creating secondary capture sessions, distinguishes cumulative counters from interval deltas, and strictly prevents false zero reporting when statistics are unavailable.

---

## 2. Native C API Integration & Structure Contract

### 2.1 C Function Signature
The adapter queries the low-level libpcap / Npcap API:
```c
int pcap_stats(pcap_t *p, struct pcap_stat *ps);
```
- **Calling Convention:** `cdecl` via `ctypes`.
- **Return Value:** `0` on success; `< 0` (e.g. `PCAP_ERROR`) on native driver failure.

### 2.2 Counter Definitions & Semantic Distinctions
The C structure `struct pcap_stat` defines three primary hardware and kernel counters:

| Native Field | C Type | Exact Operational Meaning | Adapter Attribute |
| :--- | :--- | :--- | :--- |
| **`ps_recv`** | `bpf_u_int32` (`c_ulong`) | Total packets received by the kernel driver packet filter since capture start. Represents packets that made it through the driver filter into kernel memory. | `ps_recv_cumulative` & `ps_recv_delta` |
| **`ps_drop`** | `bpf_u_int32` (`c_ulong`) | Total packets dropped by the kernel driver because the kernel buffer was full (kernel drop). This is the true driver drop counter. | `ps_drop_cumulative` & `ps_drop_delta` |
| **`ps_ifdrop`** | `bpf_u_int32` (`c_ulong`) | Total packets dropped by the physical interface / network adapter before reaching the driver. (Frequently reported as 0 or unsupported by Windows network adapter drivers). | `ps_ifdrop_cumulative` & `ps_ifdrop_delta` |

---

## 3. Architecture & Handle Lifecycle

```
+-------------------------------------------------------------------------+
|                       RealTimeDetectionManager                          |
|                                                                         |
|  [get_status()]                                                         |
|       |                                                                 |
|       v                                                                 |
|  +-------------------------------------------------------------------+  |
|  |                LiveCaptureSource / PcapReplaySource               |  |
|  |                                                                   |  |
|  |  +-------------------------------------------------------------+  |  |
|  |  |                     NativeStatsAdapter                      |  |  |
|  |  |                                                             |  |  |
|  |  |  poll(handle)                                               |  |  |
|  |  |       |                                                     |  |  |
|  |  |       +---> Handle is Active:  pcap_stats() -> Stats        |  |  |
|  |  |       +---> Handle is None:    Returns UNAVAILABLE (None)   |  |  |
|  |  |       +---> Source is PCAP:    Returns UNSUPPORTED (None)   |  |  |
|  |  +-------------------------------------------------------------+  |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

### 3.1 Single-Handle Reuse Guarantee
- `LiveCaptureSource` pre-opens the layer-2 listening socket (`conf.L2listen`) on the selected interface, extracting the active `pcap_t` pointer from `sock.pcap_fd.pcap`.
- The sniffer worker executes using `opened_socket=sock`.
- No secondary capture session or duplicate interface descriptor is opened.
- Upon session stop, the socket is cleanly closed and the handle is dereferenced.

### 3.2 Tiered Drop Isolation
TrafficShield maintains strict separation across three distinct drop tiers:
1. **Tier 1 — Kernel Driver Drops (`native_kernel_drops`):** Dropped by the Npcap/WinPcap kernel filter buffer before reaching user space.
2. **Tier 2 — Ingestion Queue Drops (`packets_dropped`):** Dropped by `LiveCaptureSource` when its 5,000-envelope user-space queue saturates.
3. **Tier 3 — Pipeline Flow Queue Drops (`flows_queue_dropped`):** Dropped by `RealTimeDetectionManager` when the 10,000-flow scoring queue saturates.

Each drop tier is reported independently in telemetry and dashboard status.

---

## 4. Delta Computation & Counter Reset Protection

- **Interval Delta Calculation:**
  $$\Delta = \text{current\_cumulative} - \text{previous\_cumulative}$$
  $$\Delta t = \text{current\_timestamp} - \text{previous\_timestamp}$$
- **Driver Buffer Reset Handling:**
  If the kernel driver restarts or reallocates its ring buffer, cumulative counters can decrease ($\text{current} < \text{previous}$). The adapter flags this transition (`AVAILABLE (Counter Reset Observed)`) and sets delta to current value, preventing negative delta anomalies.
- **Unavailable Metric Safety:**
  If the handle is closed or native polling fails, metrics return strictly `None` with `is_available: False`. Zero is never substituted for missing data.
