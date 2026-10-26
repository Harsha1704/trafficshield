# TrafficShield M15.1 — Final Performance Qualification & Release Verdict

**Document ID:** TS-M15.1-VERDICT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M15.1 Pre-Release Anomaly Investigation & Operational Qualification  

---

## 1. Categorization of Findings

### A. Verified Facts (Independently Established)
1. **Physical Interface Capture:** The system bound directly to Windows NPF device `\Device\NPF_{57B0B12B-DBD6-4A1F-889F-10662755578B}` on the Realtek RTL8852BE WiFi 6 adapter using the verified Npcap kernel driver.
2. **Zero Software / Inference Defect:** Feature calculations, feature ordering, unit conversions, RobustScaler normalization, and XGBoost booster predictions match the authoritative frozen training contract with 100% precision.
3. **Artifact Immutability:** Both detector (`c43bb5...`) and preprocessor (`effe96...`) SHA-256 hashes match the frozen baselines bit-for-bit.
4. **Root Cause of High Anomaly Rate:** The 64.5% anomaly rate is mathematically attributable to **domain feature distribution shift on `sttl` and multicast UDP**:
   - In UNSW-NB15, normal internal traffic was bounded at $sttl \le 62$, and $sttl > 62$ was characteristic of external attack traffic.
   - On the live Wi-Fi interface, 74.7% of alerts were RFC 6762 Multicast DNS (mDNS) with protocol-mandated $sttl = 255$, and 16.6% were Windows host traffic with default initial $sttl = 128$.
5. **Reconciliation of Flow Counts:**
   - 757 flows built vs 668 scored: 89 in-flight/flushed flows remained in the queue when the stop signal halted the consumer loop during graceful shutdown.
   - 431 anomalies vs 241 persisted alerts: 190 duplicate alerts were suppressed by the 10-second deduplication sliding window on `(src_ip, dst_ip, dst_port, protocol)`.
6. **Codebase Health:** 504 backend tests passed (100%), 22 frontend tests passed (100%), Ruff clean, Mypy clean, Vite build clean.

### B. Reported Measurements (Operational Telemetry)
1. **Capture Duration:** 24.1 seconds.
2. **Packet Count:** 8,259 wire packets (~343 pkts/sec).
3. **Application Drops:** 0 queue drops (queue depth peak: 42 / 5,000).
4. **Latency:** Mean single-flow inference latency of 6.68 ms inside the streaming worker thread.
5. **Alerts:** 241 deduplicated alerts persisted with `source="LIVE_CAPTURE"`.

### C. Unresolved Hypotheses & Operational Boundaries
1. **Kernel Ring Buffer Drops:** While application-level queue drops were 0, Npcap kernel-level ring buffer drops were not directly measured via C `pcap_stats()`.
2. **Sustained Load Reliability:** A 24-second test confirms mechanical functionality (smoke test), but does not prove multi-day memory stability or behavior under line-rate saturation.
3. **Enterprise Gateway Anomaly Rate:** It is hypothesized that on an enterprise SPAN/tap link monitoring routed WAN or server-farm traffic (where default TTLs decrement through multiple hops and mDNS/SSDP broadcasts are filtered by routers), the anomaly false positive rate will normalize toward the training baseline (~1.9% test false positive rate). This requires empirical testing on routed enterprise traffic.

---

## 2. Recommended Release Status

> ### **RECOMMENDATION: READY FOR LOCAL DEMONSTRATION**

### Justification:
- **Mechanical & Architectural Excellence:** The pipeline reliably demonstrates real packets captured via Npcap, validated for IPv4/TCP/UDP wire syntax, assembled into causally compliant unidirectional flows, scored by the frozen model, and streamed into the React SOC dashboard.
- **Transparent Operational Disclosure:** The high anomaly rate on local Wi-Fi links is fully understood, reproducible, and documented as a domain mismatch on unrouted broadcast/multicast traffic rather than a hidden defect.
- **Not Ready for Release Candidate (RC) Without Scope Caveat:** Deploying the detector on an un-routed local Wi-Fi or consumer LAN without BPF filters would overwhelm SOC analysts with mDNS/SSDP false positives.

---

## 3. Evidence Required to Advance to `READY FOR RELEASE CANDIDATE`

To advance TrafficShield from **READY FOR LOCAL DEMONSTRATION** to **READY FOR RELEASE CANDIDATE (RC)**, the following evidence must be documented:

1. **Enterprise / SPAN Link Validation:**
   - Run live capture on an authorized SPAN port, optical tap, or WAN gateway link (the design target of unidirectional monitoring links), where inter-subnet routing decrements TTLs and multicast noise is absent.
   - Measure whether the baseline false positive rate aligns with the expected M9 benchmark ($< 3.5\%$).
2. **Domain-Appropriate BPF Filtering:**
   - Test live capture with default production BPF filters excluding link-local multicast noise (e.g. `ip and not (multicast or broadcast) and not port 5353 and not port 1900`), demonstrating clean inference on routed unicast flows.
3. **Sustained-Duration Soak Test:**
   - Execute a continuous 1-hour to 4-hour live capture run under load to certify zero memory growth in `UnidirectionalFlowBuilder`, `BoundedFragmentReassembler`, and `StreamingInferenceWorker`.
4. **Kernel Ring Buffer Drop Monitoring:**
   - Integrate native Npcap `pcap_stats` polling into `LiveCaptureSource` to verify that both user-space queue drops and kernel ring-buffer drops remain at zero under burst traffic.
