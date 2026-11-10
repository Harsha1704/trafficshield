# TrafficShield — Technical Presentation

**Hybrid ML Anomaly Detection Platform for Unidirectional IP Traffic**  
*Architecture, Empirical Benchmarks, SOC Operations, and Security Review*

---

## Slide 1: Title & Overview
- **Title:** TrafficShield: Unidirectional IP Traffic Anomaly Detection
- **Subtitle:** An Enterprise Hybrid ML Architecture for Critical Infrastructure Network Defense
- **Presenter:** TrafficShield Engineering & Security Team
- **Core Technology:** Frozen Supervised XGBoost + Calibrated Unsupervised Isolation Forest
- **Key Tenet:** High-assurance threat detection across unidirectional optical taps and hardware data diodes without reverse packet context.

---

## Slide 2: The Critical Infrastructure Problem
- **The Physical Constraint:** Industrial control systems (ICS/SCADA), power grids, and defense networks use **unidirectional optical taps and hardware data diodes** to physically isolate protected enclaves.
- **The Observability Barrier:** Traditional intrusion detection systems (IDS) rely on bidirectional flows (TCP SYN-ACK-ACK handshakes, round-trip times, server payload size). In unidirectional links, **only forward packets exist**.
- **The Data Dilemma:** Labelled attack data in operational environments is virtually non-existent, while attack signatures drift rapidly.
- **The Solution:** A hybrid detection architecture that couples signature-based precision for known attack templates with unsupervised anomaly detection for novel, unlabelled deviations.

---

## Slide 3: 13-Feature Unidirectional Engineering
- **Strict Directionality Policy:** Total ban on reverse-direction features (`dbytes`, `dpkts`, `dload`, `dttl`, `ackdat`, `synack`, etc.).
- **10 Forward Causal Base Features:**
  - `duration_seconds` ($L_{\text{time}} - S_{\text{time}}$)
  - `fwd_bytes`, `fwd_packets`, `smeansz`
  - `sttl` (Source TTL header)
  - `sload` (Source bits per second)
  - `swin` (Source TCP advertised window)
  - `sjit` (Source inter-arrival jitter via RFC 3550 EMA)
  - `sintpkt` (Mean inter-packet arrival time)
  - `is_sm_ips_ports` (Source/destination loopback indicator)
- **3 Derived Causal Rate Features:**
  - `packet_rate` ($\text{pkts} / \text{duration}$)
  - `byte_rate` ($\text{bytes} / \text{duration}$)
  - `bytes_per_packet` ($\text{bytes} / \text{pkts}$)
- **Guaranteed Causality:** Zero future-window lookahead (`ct_*` aggregate counts excluded).

---

## Slide 4: Hybrid ML Detection Architecture
- **Dual-Model Coupling:**
  1. **Supervised XGBoost Detector:** Frozen classifier trained on UNSW-NB15 unidirectional features. Threshold calibrated at $\tau = 0.5000$. Focus: Known attack signatures (Fuzzers, Exploits, DoS, Generic).
  2. **Unsupervised Isolation Forest:** Independent anomaly detector trained strictly on normal/benign flow distributions ($N=100,000$). Threshold calibrated at $\tau = 0.727896$. Focus: Structural anomalies, volumetric shifts, zero-days.
- **Cryptographic Anti-Tamper:** Every artifact is hashed with SHA-256 and validated prior to deserialization in `ProductionInferenceService`.
- **Fail-Closed Design:** Any discrepancy in artifact hash or schema size terminates execution immediately.

---

## Slide 5: The 4-Tier Hybrid Decision Matrix
- **Transparent Fusion:** Eliminates black-box ambiguity by presenting explicit decisions from both detectors:

| Classification | Supervised ($P \ge 0.50$) | Unsupervised ($S \ge 0.728$) | Severity | Actionable SOC Triage |
|---|:---:|:---:|:---:|---|
| **`DUAL_CONFIRMED`** | **YES** | **YES** | **CRITICAL** | Both algorithms flag anomalous pattern. 100.0% precision on benchmark test split. Immediate containment. |
| **`SUPERVISED_ONLY`** | **YES** | **NO** | **HIGH** | Matches known attack signature, but overall volumetric/timing profile mimics normal baseline. |
| **`UNSUPERVISED_NOVELTY`** | **NO** | **YES** | **MEDIUM** | Novel structural anomaly or unknown zero-day behavior. Flagged for threat hunting. |
| **`NORMAL_TRAFFIC`** | **NO** | **NO** | **INFO** | Benign baseline flow. Passed without alert escalation. |

---

## Slide 6: Empirical Benchmark Evaluation (UNSW-NB15)
- **Rigorous Test Split:** Evaluated on independent UNSW-NB15 test partition ($N=19,951$ flows, 2,213 attacks):
  - **Supervised XGBoost:** Accuracy 94.75%, Precision 72.82%, Recall 85.58%, F1 78.68%, ROC-AUC 0.9634.
  - **Unsupervised Isolation Forest:** Accuracy 90.62%, Precision 56.41%, Recall 82.20%, F1 66.90%, ROC-AUC 0.9255.
- **The Hybrid Advantage:**
  - Dual-confirmed detections achieved **100.0% precision** (83 out of 83 dual alerts were true malicious attacks).
  - Unsupervised detector captured novel anomalies missed by the supervised model.
- **Inference Latency:** Mean single-flow inference time $\approx 4.8\text{ ms}$, batch inference $> 12,000\text{ flows/sec}$.

---

## Slide 7: Live Capture & Operational Stress Qualification
- **Live Passive Sniffing Validation (M15.2):**
  - Captured 572 real packets (123,321 bytes) via Npcap on active Wi-Fi adapter (`10.36.107.148`).
  - Reconstructed 331 unidirectional flows using strict 5-tuple tracking (10,000 LRU capacity, 15s timeout).
  - 100% of flows evaluated through the hybrid pipeline with zero dropped frames.
- **Operational Findings & TTL Distribution Shift:**
  - 131 flows classified as `SUPERVISED_ONLY_ALERT`, 200 as `NORMAL_TRAFFIC`.
  - Root cause: Windows local multicast/broadcast (mDNS port 5353, SSDP, LLMNR) transmits with $TTL=255$.
  - In training data, $TTL=255$ correlated with attack traffic; Isolation Forest correctly recognized normal structural behavior ($S \approx 0.55 < \tau$).
  - Proves the resilience of the hybrid architecture: avoids false `DUAL_CONFIRMED` escalation!

---

## Slide 8: Enterprise SOC Command Center
- **Tactical UI Architecture:** Built with React 19, TypeScript, Vite, and Tailwind CSS v4 in deep obsidian palette (`#07090e`, `#0d121d`).
- **Real-Time Modules:**
  - **Live Detection (`/live`):** Continuous packet stream, real-time flow reconstruction, dual score gauges.
  - **Alerts & Triage (`/alerts`):** 4-tier filtering, full feature attribution modal, lifecycle state tracking (`NEW`, `INVESTIGATING`, `RESOLVED`).
  - **Traffic Inspector (`/traffic`):** Drag-and-drop CSV batch evaluation with client/server feature policy enforcement.
  - **Statistical Monitoring (`/monitoring`):** Population Stability Index (PSI), Kolmogorov-Smirnov, Wasserstein distance drift tracking.

---

## Slide 9: Security Review & Anti-Tamper Hardening
- **13-Dimension Security Review:**
  1. *Secret Management:* Hardened Pydantic validator rejects default secrets and keys $< 32$ chars in production.
  2. *RBAC:* Role-gated server endpoints (`analyst` for scoring/alerts, `admin` for promotions/settings).
  3. *CORS:* Strict explicit origin whitelisting; wildcard `*` forbidden.
  4. *Input Validation:* Pydantic schemas enforce ranges and reject prohibited reverse features.
  5. *Safe Deserialization:* Pre-execution SHA-256 hashing blocks malicious pickle/joblib injection.
  6. *SQL Injection Defense:* 100% parameterized SQLAlchemy ORM queries; raw string interpolation prohibited.
  7. *Zero Payload Logging:* Network driver interface discards raw packet payloads; only flow metadata retained.
  8. *Queue Bounding:* Fixed-size packet and flow queues prevent memory exhaustion under line-rate spikes.
  9. *Error Shielding:* Generic JSON errors prevent stack trace and file path disclosure.
  10. *Formula Injection Defense:* Strips CSV command prefixes (`=`, `+`, `-`, `@`, `|`) on data export.

---

## Slide 10: Operational Guidance & Future Roadmap
- **Readiness Verdict:** **PASS WITH LIMITATIONS**
- **Operational Recommendations for SOC Teams:**
  1. Whitelist or apply domain-specific thresholds for local subnet broadcast/multicast (mDNS, SSDP, LLMNR).
  2. Treat `DUAL_CONFIRMED` alerts as high-priority incidents requiring immediate defensive response.
  3. Treat `SUPERVISED_ONLY` alerts with $TTL=255$ as candidate broadcast shifts subject to secondary verification.
  4. Maintain human-in-the-loop governance: **Zero automated model retraining on unlabelled link traffic**.
- **Future Roadmap:**
  - Self-supervised contrastive learning on purely benign unidirectional baseline data.
  - Hardware acceleration for 10Gbps+ optical data diodes via DPDK or eBPF.
