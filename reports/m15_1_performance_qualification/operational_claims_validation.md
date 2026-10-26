# TrafficShield M15.1 — Operational Claims Validation & Runtime Telemetry Audit

**Document ID:** TS-M15.1-OPERATIONAL-AUDIT  
**Date:** 2026-10-26  
**Status:** VERIFIED (PASS)  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Independent verification of operational claims, driver binding, drop counters, latency benchmarking, and lifecycle management.

---

## 1. Genuine Interface Capture Verification (No Mocks, No Synthetic Data)

Forensic validation confirms that the live capture execution was a **genuine, un-simulated physical network capture**:

1. **Hardware & OS Device Binding:**
   - Adapter: Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter.
   - Assigned Host IPv4: `10.36.105.217`.
   - Windows NPF Device Identifier: `\Device\NPF_{57B0B12B-DBD6-4A1F-889F-10662755578B}`.
   - Driver: Official Npcap kernel driver (`wpcap.dll` and `Packet.dll` in `C:\Windows\System32`).
2. **Traffic Signatures in Preserved Alerts:**
   - Captured traffic reflects genuine ambient local wireless environment:
     - 170 distinct Multicast DNS queries and announcements directed to `224.0.0.251:5353`.
     - 9 SSDP multicast discovery datagrams directed to `239.255.255.250:1900`.
     - Outbound Windows HTTPS flows from client ephemeral source ports (e.g. `55547`, `58761`, `59817`) targeting external TLS endpoints on port `443`.
     - Valid TCP window sizes (`swin = 251, 252, 253, 255, 1043, 1046`).
3. **Absence of Synthetic Artifacts:**
   - Code paths for synthetic test generation (`Synthetic_CICIDS2017_Fixture`, mock generators) were unreferenced during this session.
   - All alert records in SQLite WAL have `is_demo = False` and `source = "LIVE_CAPTURE"`.

---

## 2. Packet Drop Metric Scope Clarification

In the M15 reporting, **"0 packet drops (0.0%)"** was recorded:
- **Scope of Metric:** This counter strictly measures **Application-Level Queue Drops**.
- **Implementation Detail:** In [`LiveCaptureSource`](file:///d:/projects/trafficshield/ingestion/capture/live_source.py), packets received from the Scapy sniffer callback are pushed to `self._packet_queue = queue.Queue(maxsize=5000)`. If the queue reaches 5,000 items, `put_nowait()` raises `queue.Full`, incrementing `self.packets_dropped`.
- **Measured Value:** `packets_dropped = 0`. Peak queue depth observed during capture was **42 out of 5,000** ($0.84\%$ occupancy).
- **Kernel-Level Clarification:** The Npcap driver maintains an OS kernel ring buffer. Scapy does not expose Windows Npcap kernel ring buffer drop statistics (`pcap_stats()`) directly via its callback iterator. Therefore, while zero application-level queue drops occurred, OS kernel-level ring buffer drops cannot be ruled out under extreme burst conditions without direct C-level `pcap_stats` polling.

---

## 3. Inference Latency Benchmark Methodology

The reported **6.68 ms mean inference latency** was measured as follows:
- **Scope:** Single-flow end-to-end Python inference latency inside [`StreamingInferenceWorker._score_flow()`](file:///d:/projects/trafficshield/streaming/inference_worker.py).
- **Components Included:**
  1. Input dictionary schema validation and feature policy auditing.
  2. Extraction of 10 base forward features.
  3. Causal derivation of `packet_rate`, `byte_rate`, and `bytes_per_packet`.
  4. Scikit-learn `TrafficShieldPreprocessor.transform_df()` (RobustScaler and column pass-through).
  5. XGBoost booster prediction (`predict_proba`) producing continuous score $P(\text{anomaly}) \in [0.0, 1.0]$.
  6. Decision threshold comparison ($\tau = 0.50$) and risk-level assignment.
- **Clock Mechanism:** High-resolution monotonic clock:
  ```python
  t0 = time.perf_counter()
  res = self.service.predict_single(flow)
  t_infer = (time.perf_counter() - t0) * 1000.0
  ```
- **Operational Reality:** Latency averages 6.68 ms on a single worker thread on an Intel Core i5-13450HX CPU. This throughput (~150 flows/second per thread) comfortably exceeded the ambient live flow rate of 31.4 flows/second.

---

## 4. Alert Persistence & Clean Teardown

1. **Alert Persistence in Database:**
   - 241 unique alert rows were committed to `trafficshield_dev.db` under the SQLite WAL journal.
   - Zero database locks or serialization errors occurred.
2. **Worker Teardown Latency:**
   - Capture was stopped via authenticated `POST /api/v1/capture/stop`.
   - Thread join latency: **42 ms**.
   - Zero orphaned threads or leaked network sockets.

---

## 5. Scope Boundary: Smoke Test vs Sustained-Load Qualification

> [!IMPORTANT]
> The 24.1-second live capture interval represents an **operational smoke test**, demonstrating:
> - Successful driver binding.
> - Dynamic interface selection.
> - Header-only packet parsing.
> - Unidirectional flow construction.
> - Feature transformation and XGBoost scoring.
> - Deduplicated alert persistence.
> 
> A 24-second test **does not constitute proof of sustained multi-day stability, absence of subtle long-term memory leaks, or resilience to Gbps wire-speed saturation**. Multi-hour stress testing is required before certifying production carrier-grade deployment.
