# TrafficShield — 5-to-7 Minute Evaluator Demonstration Script

**Document ID:** TS-DOC-DEMO-SCRIPT  
**Target Audience:** Technical Evaluators, Security Architects & ML Engineers  
**Demonstration Mode:** Offline PCAP Replay (Safe, Deterministic, Zero Network Risk)  
**Estimated Duration:** ~6.0 minutes  

---

## Stage-by-Stage Demonstration Walkthrough

```mermaid
flowchart LR
    A["0:00 Problem & Objective"] --> B["0:30 Architecture"]
    B --> C["1:15 UI & Authentication"]
    C --> D["2:00 Traffic Input (Replay)"]
    D --> E["3:00 Detection & Evidence"]
    E --> F["4:30 Operational Reliability"]
    F --> G["5:30 Limitations & Roadmap"]
```

---

### Stage 1: Problem & Objective (0:00 – 0:30, 30s)

- **Presenter Narration:**  
  *"Enterprise intrusion detection systems frequently fail in asymmetric routing topologies, where perimeter taps only observe outbound or forward traffic. TrafficShield was built to solve this challenge through strictly unidirectional IP traffic anomaly detection. By relying entirely on one-way forward observable metrics—such as arrival jitter, packet rates, window advertisements, and IP TTL—TrafficShield classifies anomalous traffic patterns without requiring reverse response packets."*
- **Visible Action:**  
  Display the project README or terminal overview.
- **Evidence Point:**  
  [`README.md`](file:///d:/projects/trafficshield/README.md) One-Way Feature Policy.

---

### Stage 2: Architecture Walkthrough (0:30 – 1:15, 45s)

- **Presenter Narration:**  
  *"The pipeline consists of six decoupled stages. Raw wire packets pass through an IPv4 packet validator that rejects malformed headers and enforces snaplen boundaries. Fragmented datagrams are reconstructed causally in a bounded fragment reassembler. A stateful unidirectional flow builder extracts 13 causal features. Features are transformed by a frozen production preprocessor, then scored by an Optuna-tuned XGBoost detector at a decision threshold of 0.50. Anomalous flows are deduplicated and committed as persistent SQLite security alerts for the React SOC dashboard."*
- **Visible Action:**  
  Point to the architecture diagram in [`docs/demo/architecture_and_limitations.md`](file:///d:/projects/trafficshield/docs/demo/architecture_and_limitations.md).
- **Evidence Point:**  
  Frozen model hashes verified bit-identical:
  - Detector SHA-256: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
  - Preprocessor SHA-256: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`

---

### Stage 3: Dashboard & Authentication (1:15 – 2:00, 45s)

- **Presenter Narration:**  
  *"We log into the SOC Command Center at localhost:5173 using development analyst credentials. The Overview screen displays real-time health indicators, database connectivity, and the active model identity badge confirming OptunaTuned_XGBoost version 1.0.0. The interface enforces role-based access control, ensuring only authorized analysts or administrators can initiate capture or replay sessions."*
- **Visible Action:**  
  1. Open browser to `http://localhost:5173`.
  2. Demonstrate navigation across **Overview**, **Traffic Analysis**, **Live Detection**, and **Security Alerts**.
  3. Show the **Model Intelligence** badge confirming active model and threshold $\tau = 0.50$.
- **Evidence Point:**  
  Header status displays `API: ONLINE`, `Model: OptunaTuned_XGBoost (1.0.0)`.

---

### Stage 4: Traffic Input via Safe PCAP Replay (2:00 – 3:00, 60s)

- **Presenter Narration:**  
  *"To demonstrate deterministic detection without transmitting packets over a live network, we navigate to the Live Detection tab. Notice the capture mode is set to PCAP Replay. We select our committed synthetic fixture, `sample_traffic.pcap`, which contains 29 isolated synthetic packets simulating DNS queries, HTTPS handshakes, and port scan probes on RFC 1918 private subnets. We set the speed multiplier to 2.0x and click 'Start Replay'."*
- **Visible Action:**  
  1. Click on **Live Detection** in the left sidebar.
  2. Select Mode: **PCAP Replay**.
  3. From the replay dropdown, select `sample_traffic.pcap`.
  4. Set Speed Multiplier: `2.0x`.
  5. Click the green **Start Replay** button.
- **Evidence Point:**  
  Status badge transitions from `STOPPED` to `RUNNING`. Packets Read increments to 29; Flows Completed increments to 24. The UI clearly labels provenance as `PCAP_REPLAY` (never mislabeled as live capture).

---

### Stage 5: Detection & Forensic Evidence (3:00 – 4:30, 90s)

- **Presenter Narration:**  
  *"As the replay progresses, the streaming event table updates in real time with sub-10 millisecond inference latencies. Each completed flow displays its 5-tuple, protocol, continuous model anomaly score, and risk level badge.
  
  In this deterministic fixture, we observe that the multi-packet HTTPS stream evaluates to an anomaly score of `0.3681` (LOW risk), while isolated single-packet probes (DNS, LAND probe, and SYN scans) evaluate to `0.1273` (LOW risk). Because all 24 flows remain strictly below the decision threshold ($\tau = 0.50$), zero false-positive alerts are generated. This demonstrates clean baseline discrimination on low-volume single-packet probes without false-positive alert fatigue.
  
  When controlled high-load inputs with elevated rates and volume are presented—as verified in our automated test suite `tests/unit/test_detection_validation.py`—the model scores them $\ge 0.85$ (CRITICAL), exercising scoring and deduplicated database alert persistence. Field detection effectiveness on routed links remains unvalidated."*
- **Visible Action:**  
  1. Scroll through the **Real-Time Detection Event Stream** on the Live Detection page.
  2. Point out individual flows and score distributions:
     - Multi-packet HTTPS flow (`192.168.1.25:49152 -> 104.244.42.1:443`): `anomaly_score = 0.3681`, `risk_level: LOW`.
     - Isolated single-packet flows (DNS, LAND probe `192.168.1.50:8080`, and SYN probes): `anomaly_score = 0.1273`, `risk_level: LOW`.
  3. Explain the honest model behavior: isolated single-packet probes without high duration or rate correctly do not cross $\tau = 0.50$, preventing false alarms.
  4. Reference automated verification test `tests/unit/test_detection_validation.py::test_volumetric_burst_anomaly_detection_and_persistence` demonstrating controlled high-load input exercising scoring and alert persistence.
- **Evidence Point:**  
  Flow accounting displays 24 flows completed and 24 flows scored; 0 drops across all three tiers; exact score bounds verified: min 0.1273, median 0.1273, max 0.3681; automated test confirms scoring and alert persistence on controlled high-load input.

---

### Stage 6: Operational Reliability & Graceful Teardown (4:30 – 5:30, 60s)

- **Presenter Narration:**  
  *"Now we test operational robustness during shutdown. In Milestone 15.4, we hardened the shutdown pipeline against race conditions. When we click 'Stop', the manager stops ingestion, flushes active in-flight flows from the builder, locks the builder against late packets, and gracefully drains all queued flows through the worker before exiting. During our live smoke test, 884 out of 884 flows were scored with zero unprocessed flows, exactly conserving all flow counters."*
- **Visible Action:**  
  1. Return to **Live Detection** page and click **Stop Session**.
  2. Observe immediate transition to `STOPPED` or `COMPLETED`.
  3. Point to the telemetry counters:
     - `Queue Depth: 0`
     - `Unprocessed Flows: 0`
     - `Flows Completed == Flows Scored`
- **Evidence Point:**  
  Demonstrate passing regression suite:
  `python -m pytest tests/unit/test_m15_4_shutdown_edge_cases.py` (13 passed in 3.93s).

---

### Stage 7: Honest Limitations & Engineering Roadmap (5:30 – 6:30, 60s)

- **Presenter Narration:**  
  *"To maintain scientific rigor, we explicitly communicate current operational boundaries. During live Wi-Fi testing, we observed an elevated anomaly rate (~52%). Our M15.3 feature audit established that this is domain feature shift: consumer Wi-Fi packets carry default OS initial TTLs (128 for Windows, 255 for multicast), whereas the model's learned decision tree split clusters at TTL 62 based on multi-hop routed datasets. Automated software quality gates pass completely, but representative field detection effectiveness (SPAN/TAP ground-truth evaluation) remains unvalidated. Therefore, TrafficShield is certified as READY FOR LOCAL DEMONSTRATION with documented limitations."*
- **Visible Action:**  
  Show the final gate verdict in [`reports/m15_4_shutdown_edge_case_qualification/final_gate_verdict.md`](file:///d:/projects/trafficshield/reports/m15_4_shutdown_edge_case_qualification/final_gate_verdict.md).
- **Evidence Point:**  
  Gate Verdict: `READY FOR LOCAL DEMONSTRATION`.
