# TrafficShield M17 — Sustained-Soak Qualification & Harness Report

**Document ID:** TS-M17-SOAK-QUAL-REPORT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M17 Sustained-Soak Qualification & Resource Monitoring  
**Repository Revision:** `fb1d9a4`  

---

## 1. Executive Summary & Verification Matrix

Milestone 17 built, verified, and qualified a repeatable, resource-monitored soak-test harness for TrafficShield. The harness automates long-duration stability analysis, process memory sampling (RSS and peak), CPU utilization profiling, inference latency percentile distributions, and mathematical flow-accounting reconciliation.

| Evaluation Area | Target Requirement | Measured / Verified Result | Status |
|:---|:---|:---:|:---:|
| **Soak Harness Architecture** | Configurable, non-intrusive CLI & Python engine | [`tools/soak/`](file:///d:/projects/trafficshield/tools/soak/) with CLI, harness, and monitor | **PASS** |
| **Resource Sampling** | Process RSS, peak RSS, CPU %, and thread count | Windows Native PSAPI & process time sampler | **PASS** |
| **Latency Distribution** | p50, p95, and p99 inference latency tracking | Percentile metrics exposed in worker & manager | **PASS** |
| **Offline Bounded Qualification**| Bounded PCAP replay run with 8 accounting invariants | All 8 invariants passed; 24/24 flows conserved | **PASS** |
| **Automated Harness Suite** | 10 unit tests for config, errors, and interrupts | **10 / 10 passed (100%)** in 2.36s | **PASS** |
| **Flow Accounting Invariants** | Strict mathematical conservation across stages | $\text{created} = \text{completed} = \text{queued} = \text{scored} = 24$ | **PASS** |
| **Native Kernel Drops** | Clear distinction between queue drops and kernel drops | Explicitly reported as `UNAVAILABLE` | **PASS** |
| **Model Cryptographic Integrity**| Detector `c43bb5...`, Preprocessor `effe96...` | Both SHA-256 hashes bit-identical to baselines | **PASS** |
| **Live Soak Runbook** | Controlled 2-4 hour procedure with authorization gate | [`live_soak_runbook.md`](file:///d:/projects/trafficshield/reports/m17_soak_qualification/live_soak_runbook.md) established | **PASS** |
| **Full Live Soak Status** | 2-4 hour live capture run on physical interface | **NOT RUN / PENDING EXPLICIT OPERATOR AUTHORIZATION** | **OPEN BLOCKER** |

---

## 2. Resource Measurement Definitions & Windows Semantics

Hardware resource telemetry is gathered periodically without third-party agent dependencies using Windows Native PSAPI (`psapi.dll`) via standard library `ctypes`:

1. **Process Working Set (RSS Memory):**
   - **Metric:** `rss_mb` (WorkingSetSize from `PROCESS_MEMORY_COUNTERS_EX`).
   - **Semantics:** Actual physical RAM currently allocated to the TrafficShield Python process.
2. **Peak Working Set:**
   - **Metric:** `peak_rss_mb` (PeakWorkingSetSize).
   - **Semantics:** Maximum physical RAM allocated since process startup.
3. **Private Memory Allocation:**
   - **Metric:** `private_mb` (PrivateUsage).
   - **Semantics:** Memory allocated specifically to the process that cannot be shared with other processes (pagefile-backed memory).
4. **Process CPU Utilization (%):**
   - **Metric:** `cpu_percent`.
   - **Semantics:** $\frac{\Delta \text{process\_time}}{\Delta \text{wall\_time}} \times 100\%$, measured across the sampling window. Reflects user-space and kernel-space processor consumption by the Python interpreter.
5. **Thread Count:**
   - **Metric:** `active_threads` (`threading.active_count()`).

---

## 3. Short Bounded Offline Qualification Run Results

A bounded 5.0-second qualification test was executed using `python -m tools.soak.cli` with offline PCAP replay on [`data/captures/sample_traffic.pcap`](file:///d:/projects/trafficshield/data/captures/sample_traffic.pcap):

- **Session ID:** `soak_1793002364_pcap_replay`
- **Configured Duration:** 5.0 s (Actual: 5.04 s)
- **Packets Observed:** 29 packets
- **Baseline RSS Memory:** 136.05 MB
- **Final RSS Memory:** 342.16 MB (includes model loading into memory)
- **Peak Process CPU:** 74.3%
- **Shutdown Drain Latency:** 0.25 ms
- **Final Worker State:** `STOPPED`

### Invariant Verification Table:

| Invariant Name | Expected | Measured Value | Result | Details |
|:---|:---:|:---:|:---:|:---|
| `INV_1_ACTIVE_FLOWS_CLEARED` | 0 | 0 | **PASS** | State table evacuated post-flush |
| `INV_2_CREATION_COMPLETION_CONSERVATION` | 24 | 24 | **PASS** | `flows_created == flows_completed` |
| `INV_3_COMPLETED_FLOWS_DECOMPOSITION` | 24 | 24 | **PASS** | `expired + tcp + evicted + flushed == 24` |
| `INV_4_QUEUE_INGESTION_CONSERVATION` | 24 | 24 | **PASS** | `flows_completed - drops == 24` |
| `INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION`| 24 | 24 | **PASS** | `scored + rejected + failures + unprocessed == 24` |
| `INV_6_ALERT_PERSISTENCE_BOUNDS` | $\le 0$ | 0 | **PASS** | Alert writes bounded by detected anomalies |
| `INV_7_PIPELINE_JOIN_CLEAN` | `False` | `False` | **PASS** | Ingestion pipeline joined without timeout |
| `INV_8_NATIVE_KERNEL_DROPS_HONESTY` | `UNAVAILABLE` | `UNAVAILABLE` | **PASS** | Explicitly reported as unavailable |

---

## 4. Model Cryptographic Verification

Hashes computed directly from disk using `hashlib.sha256`:

| Artifact | Expected Baseline Hash | Verified Hash on Disk | Match Status |
|:---|:---:|:---:|:---:|
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **MATCH (PASS)** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **MATCH (PASS)** |

---

## 5. Known Measurement Gaps & Outstanding Blockers

1. **Native Npcap Kernel Drop Visibility:**
   - Application queue drops (`flows_queue_dropped`) are accurately measured. However, native kernel-space buffer drops (`ps_drop` in `pcap_stats`) require a C ctypes binding that is not yet implemented. The harness honestly flags this metric as `UNAVAILABLE`.
2. **Full Multi-Hour Live Soak Execution:**
   - In accordance with the prompt's explicit authorization gate, **a multi-hour live wire capture was not run in this milestone**. The harness, unit tests, short offline replay qualification, and runbook are complete. Execution of the full 2-to-4 hour live soak remains an open blocker requiring explicit operator authorization.
3. **Routed Gateway / SPAN Tap Evaluation:**
   - Operational domain alignment remains an open blocker. Validation must occur on an enterprise routed network where multi-hop routing decrements initial TTLs to align with training distributions.

---

## 6. Final Scope Verdict

```
┌────────────────────────────────────────────────────────┐
│ FINAL SCOPE VERDICT:                                   │
│ PASS FOR THE TESTED SCOPE (LOCAL DEMONSTRATION GATE)   │
└────────────────────────────────────────────────────────┘
```

**Technical Justification:**
The soak harness, resource sampler, latency percentiles, accounting assertions, and runbook are verified and fully operational. Because the full 2-to-4 hour live capture has not yet been authorized or executed, the sustained-live-soak blocker remains open. TrafficShield remains qualified as **`READY FOR LOCAL DEMONSTRATION`** and is not promoted to Release Candidate.
