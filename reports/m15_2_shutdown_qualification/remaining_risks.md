# TrafficShield M15.2 — Remaining Operational Risks & Architectural Bounds

**Document ID:** TS-M15.2-RISKS  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Transparent technical disclosure of remaining operational risks, kernel-level drop boundaries, BPF filtering policy, and deployment recommendations.

---

## 1. Packet Drop Metric Scope: Application Queue vs Kernel Drops

### A. Current Metric Boundary
In Milestone 15, **"0 packet drops (0.0%)"** was verified. It is vital to maintain precise boundary distinctions:
- **Measured Metric:** **Application-Level Queue Drops** (`packets_dropped`).
  - In [`LiveCaptureSource`](file:///d:/projects/trafficshield/ingestion/capture/live_source.py), packets returned from Scapy's capture callback are inserted into `queue.Queue(maxsize=5000)`.
  - Zero queue overflows occurred because the consumer thread drained envelopes at ~340 pkts/s with max queue depth of 42.
- **Unmeasured Metric:** **OS Kernel Driver Ring-Buffer Drops**.
  - In Windows Npcap, incoming NIC frames accumulate in a kernel-space ring buffer. If user-space packet copying is delayed by CPU preemption, the kernel driver drops frames.
  - Scapy's high-level `sniff(store=False)` iterator **does not expose kernel-level `pcap_stats`** during live streaming.
  - **Status:** Kernel-level packet drops are **NOT MEASURED** and cannot be certified as zero under high line-rate saturation.

### B. Engineering Path to Kernel Drop Telemetry
To collect native kernel capture drops in future releases without breaking Python runtime safety:
```c
// Native Npcap C API:
struct pcap_stat ps;
if (pcap_stats(pcap_handle, &ps) == 0) {
    uint32_t kernel_drops = ps.ps_drop; // Packets dropped by kernel
    uint32_t if_drops = ps.ps_ifdrop;   // Packets dropped by interface adapter
}
```
A native C-extension or ctypes wrapper around `pcap_stats()` will be required to certify wire-speed capture drops on 1 Gbps / 10 Gbps links.

---

## 2. BPF Filter Policy: Routed-Unicast Evaluation

In Milestone 15.1, it was identified that local link multicast traffic (mDNS 5353, SSDP 1900) dominated 78.3% of alerts due to RFC-mandated TTL 255.

### Objective & Scope:
- **Design Target of TrafficShield:** Unidirectional IP anomaly detection on **routed enterprise optical taps and SPAN ports**.
- **Proposed Filter:** `ip and not (multicast or broadcast) and not port 5353 and not port 1900`.
- **Policy Invariant:** **This BPF filter will NOT be silently imposed as a universal default.**
  - Silently dropping multicast traffic would mask operational realities from security teams inspecting industrial or IoT subnets.
  - The default BPF filter remains `bpf_filter = "ip"`.
  - Operators monitoring routed enterprise gateways may explicitly specify the routed-unicast filter via API:
    ```http
    POST /api/v1/capture/start-live
    {
      "interface": "Wi-Fi",
      "bpf_filter": "ip and not (multicast or broadcast) and not port 5353 and not port 1900"
    }
    ```

---

## 3. Sustained-Load & Resource Bounding Risks

1. **Short-Interval Smoke Test Limitation:**
   The 24.1-second live capture interval confirms mechanical, driver, and pipeline operability. It **does not constitute qualification for sustained multi-day continuous monitoring**.
2. **Memory Bounding Protection:**
   The system implements strict memory bounding:
   - Packet queue bounded at `maxsize = 5,000`.
   - Fragment reassembler capped at `max_in_flight = 500`.
   - Flow builder capped at `max_active_flows = 10,000` with LRU eviction.
   - Circular event buffer capped at `maxlen = 200`.
   - Alert deduplication cache capped at 2,000 keys.
3. **Queue Drain Timeout Under Saturation:**
   If the inference worker encounters an extreme backlog (e.g. 10,000 flows) and the operator halts the session with a 5.0-second drain timeout, the worker will score as many flows as possible before force-stopping and recording the remainder in `unprocessed_flows`. This bounds shutdown latency but means very large backlogs will leave unprocessed flows upon emergency stop.

---

## 4. Domain Mismatch Risk on Unrouted Networks

> [!WARNING]
> Deploying TrafficShield with the frozen UNSW-NB15 model on unrouted consumer, home, or office Wi-Fi links will generate a high false-positive rate (~60–65%) because modern local operating systems and protocols emit packets with initial TTLs (64, 128, 255) that exceed the model's learned threshold ($sttl > 62$).
> 
> TrafficShield must only be deployed in operational environments matching its training assumptions: **inter-subnet routed enterprise networks, perimeter optical taps, or with appropriate BPF filtering**.
