# TrafficShield M17 — Live Soak Qualification Runbook

**Document ID:** TS-M17-RUNBOOK-LIVE-SOAK  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Target Gate:** Post-Demonstration Sustained-Soak Qualification  
**Required Authorization:** Explicit Operator Approval Required Prior to Execution  

---

## 1. Scope, Purpose & Authorization Gate

This runbook defines the controlled operational procedure for executing a sustained 2-to-4 hour passive live network capture soak test of TrafficShield.

> [!CAUTION]
> **AUTHORIZATION GATE:**
> Do NOT initiate live packet capture without explicit operator confirmation.
> Live capture must remain strictly passive (promiscuous/non-promiscuous receive-only).
> Zero packet transmission, zero port scanning, zero attack simulation, and zero synthetic packet injection onto the physical interface.

---

## 2. Preflight Requirements & Interface Identification

### 2.1 Host Environment Prerequisites
1. **Operating System:** Windows 10/11 64-bit with Npcap kernel driver installed (`wpcap.dll` and `packet.dll` active).
2. **Permissions:** Administrative or Npcap-authorized user privilege to open the network adapter in passive capture mode.
3. **Database:** SQLite WAL mode active (`trafficshield_dev.db`) or dedicated staging PostgreSQL instance.
4. **Model Immutability:** Pre-run verification of model hashes:
   - Detector SHA-256: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
   - Preprocessor SHA-256: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`

### 2.2 Target Interface Identification & Verification
To discover authorized network interfaces and verify Npcap driver availability, run:
```powershell
python -c "
from ingestion.capture.live_source import enumerate_network_interfaces, is_capture_driver_available
driver_ok, driver_msg = is_capture_driver_available()
print(f'Driver Status: {driver_msg} (Available: {driver_ok})')
for iface in enumerate_network_interfaces():
    print(f' - Name: {iface[\"name\"]}, Desc: {iface[\"description\"]}, IPs: {iface[\"ipv4_addresses\"]}, Up: {iface[\"is_up\"]}')
"
```

**Recommended Interface:**
- Adapter: `Wi-Fi` (Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter)
- BPF Filter: `ip` (IPv4 traffic only, link-local ARP/LLDP filtered at kernel driver)

---

## 3. Execution Commands & Parameter Configurations

### 3.1 Standard 2-Hour Soak Configuration
```powershell
python -m tools.soak.cli `
    --mode LIVE_CAPTURE `
    --target "Wi-Fi" `
    --bpf "ip" `
    --duration 7200 `
    --interval 60 `
    --output-dir reports/m17_soak_qualification
```

### 3.2 Parameter Definitions:
- `--duration 7200`: 7,200 seconds (2.0 hours continuous capture).
- `--interval 60`: Samples system resources and pipeline state every 60 seconds (120 discrete samples).
- `--output-dir`: Saves structured `soak_<timestamp>_live_capture_summary.json` and human-readable `soak_<timestamp>_live_capture_report.md`.

---

## 4. Telemetry Collection & Drop Distinction

### 4.1 Monitored Dimensions
Every 60 seconds, the harness samples:
1. **Host Memory:** Process RSS working set (MB), peak working set (MB), and private bytes.
2. **Process CPU:** Average CPU % consumed by the TrafficShield Python process over the 60s interval.
3. **Queue Health:** Current queue depth (0 to 10,000 capacity) and application-level dropped flows.
4. **Flow Reconstruction:** Active flows, completed flows, closed TCP flows, expired flows, evicted flows.
5. **Inference Latency:** Mean, p50, p95, and p99 inference latencies in milliseconds.
6. **Alert Commitments:** Persisted alerts, deduplicated alerts, and persistence failures.

### 4.2 Tiered Drop Accounting (Driver vs Queue Drops)
TrafficShield strictly isolates three distinct drop tiers:
1. **Native Driver Drops (`pcap_stats`):** Packets dropped by the Npcap/WinPcap kernel filter ring buffer before reaching user-space Python.
   - Polled natively via `NativeStatsAdapter` querying `ps_recv`, `ps_drop`, and `ps_ifdrop`.
   - Reported as `native_kernel_drops` (cumulative) and `native_kernel_drops_delta` (interval delta).
   - If capture source is offline PCAP replay or the driver handle is closed, the status explicitly reports `UNSUPPORTED_SOURCE` or `UNAVAILABLE` and returns `None` (never false zeros).
2. **Ingestion Queue Drops (`packets_dropped`):** Valid packets dropped by `LiveCaptureSource` when the 5,000-envelope capture queue saturates.
3. **Pipeline Flow Queue Drops (`flows_queue_dropped`):** Flows that were finalized by the flow builder but could not be accepted into `flow_queue` because the inference worker fell behind and the queue reached capacity (10,000 items).

---

## 5. Contingency & Fault Handling

1. **Manual Interruption (`Ctrl + C` / `SIGINT`):**
   - The harness catches the interrupt signal, terminates packet acquisition, flushes active flows, drains queued flows up to 5.0s, saves the partial time-series report, and exits cleanly.
2. **Memory Growth Anomaly:**
   - If process RSS exceeds 1.5 GB or exhibits monotonic linear growth over 30 consecutive samples, abort the session using `Ctrl + C`. Inspect `active_flows_count` and `fragment_reassembler` metrics.
3. **Queue Saturation:**
   - If queue depth reaches > 8,000 items, the worker is failing to keep pace with wire line rates. Check whether CPU utilization is saturated (100% on core).
4. **Worker Hang:**
   - If the worker fails to drain within the 5.0-second shutdown timeout, `drain_timed_out` and `forced_stop` are flagged. Remaining queued flows are recorded as `unprocessed_flows`.

---

## 6. Proposed Acceptance Criteria for Review

These criteria are proposed engineering standards to evaluate whether a 2-to-4 hour live soak qualifies for Release Candidate promotion:

| Criterion | Target Metric / Proposed Threshold | Justification |
|:---|:---|:---|
| **Memory Plateau** | RSS stabilization: slope < 0.05 MB/min over final hour | Proves absence of state table or reassembler leaks |
| **Queue Depth** | Average depth < 50 items; max depth < 2,000 | Confirms worker maintains throughput above line rate |
| **Queue Drops** | 0 application queue drops (`flows_queue_dropped == 0`) | Zero user-space data loss under ambient rates |
| **Flow Accounting** | 100% conservation: $\text{flows\_created} == \text{flows\_completed} == \text{flows\_queued} == \text{flows\_scored}$ | Exact flow reconciliation |
| **Unprocessed Flows** | 0 unprocessed flows at teardown | Complete queue drain |
| **Inference Latency** | p95 latency < 25.0 ms; p99 latency < 50.0 ms | Bounded per-flow scoring budget |
| **Inference Failures** | 0 model execution crashes (`inference_failures == 0`) | Model engine stability |
| **Thread Liveness** | 0 orphaned worker or pipeline threads post-shutdown | Clean teardown |
| **Model Immutability** | SHA-256 hashes bit-identical before and after | Zero artifact tampering |

---

## 7. Post-Run Verification Checklist

Following completion of an authorized live soak run:
- [ ] Verify `summary.json` and report markdown were written to `reports/m17_soak_qualification/`.
- [ ] Confirm all 8 invariants evaluate to `PASS`.
- [ ] Confirm `model_hashes_verified` is `True`.
- [ ] Confirm `active_threads` returned to baseline.
- [ ] Inspect memory time-series plot/data to verify plateauing.
