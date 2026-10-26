# TrafficShield Evaluator Demonstration Rehearsal & Release Candidate Check

**Document ID:** TS-REP-EVAL-REHEARSAL-01  
**Timestamp of Rehearsal:** 2026-10-26T19:17:14+05:30  
**Repository:** `D:\projects\trafficshield`  
**Base Commit:** `0cb96bc` (`test: validate offline detection and demo readiness`)  
**Target Release Gate:** `READY FOR LOCAL DEMONSTRATION` (with documented limitations)  

---

## 1. Executive Summary & Verification Scope

This rehearsal record documents the live, offline execution of TrafficShield's demonstration sequence, verifying the end-to-end integration of the Flask backend, React/Vite dashboard, frozen inference pipeline, and operational telemetry. 

Every step documented herein was executed and verified live against running processes on the host. No live network traffic was transmitted, no external dependencies were downloaded, and all frozen model artifacts remain bit-identical.

---

## 2. Release Candidate Integrity Audit

### 2.1 Git Repository State
- **Branch:** `main`
- **HEAD Commit:** `0cb96bc`
- **Remote:** `https://github.com/Harsha1704/trafficshield.git`
- **Working Tree:** Scoped documentation updates only; no untracked binaries or modified models.

### 2.2 Frozen Artifact Cryptographic Verification
Computed via Python `hashlib.sha256`:

| Artifact Path | Established Baseline SHA-256 | Observed Runtime SHA-256 | Status |
| :--- | :--- | :--- | :---: |
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **MATCH** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **MATCH** |
| `artifacts/models/production_detector.json` | `3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1` | `3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1` | **MATCH** |

### 2.3 Contract & Decision Parameters
- **Feature Policy:** Exactly 13 forward-observable features (10 base + 3 causal rate derivations). Reverse-direction metrics (`dttl`, `dload`, etc.) are strictly forbidden.
- **Decision Threshold:** $\tau = 0.50$ (frozen).

### 2.4 Software Quality Gates Summary
- **Backend Test Suite:** `pytest tests/ -q` $\to$ **579 / 579 PASSED** (72.57s).
- **Frontend Test Suite:** `vitest run` $\to$ **28 / 28 PASSED** (3.02s).
- **Frontend Production Build:** `tsc -b && vite build` $\to$ **CLEAN BUILD** (672ms).
- **Static Analysis:** `ruff check .` $\to$ **CLEAN** (0 errors); `mypy` $\to$ **CLEAN** (49 files).

---

## 3. Rehearsal Execution Log

### 3.1 Service Startup
1. **Backend Service:**
   - **Command:** `python run.py` (Port 5000)
   - **Verification:** `GET http://127.0.0.1:5000/api/v1/health`
   - **Observed Result:** HTTP 200 OK
     ```json
     {
       "data": {
         "service": "TrafficShield",
         "status": "ok",
         "uptime_seconds": 6.22,
         "version": "0.1.0"
       },
       "success": true
     }
     ```
2. **Frontend Service:**
   - **Command:** `npm.cmd run dev --prefix frontend` (Port 5173)
   - **Verification:** `GET http://localhost:5173/`
   - **Observed Result:** HTTP 200 OK (Vite v8.3.5 ready in 242ms).

### 3.2 Authentication & RBAC Bootstrap
- **Command:** `POST /api/v1/auth/login`
- **Payload:** `{"username": "admin", "password": "AdminPass123!"}`
- **Observed Result:** HTTP 200 OK; token issued for user `admin` with role `admin`.

### 3.3 Offline PCAP Replay
- **Command:** `POST /api/v1/capture/start-replay`
- **Payload:**
  ```json
  {
    "pcap_path": "data/captures/sample_traffic.pcap",
    "speed_multiplier": 2.0
  }
  ```
- **Observed Result:** HTTP 200 OK; session transitioned to `RUNNING`.
- **Execution Trajectory:**
  - $T + 0.5\,\text{s}$: `State: RUNNING` | Packets: 21 | Flows: 1
  - $T + 1.0\,\text{s}$: `State: COMPLETED` | Packets: 29 | Flows Completed: 24 | Flows Scored: 24

### 3.4 Telemetry & Ring Buffer Forensic Inspection
Queried via `GET /api/v1/capture/status`:

| Telemetry Field | Observed Value | Interpretation |
| :--- | :---: | :--- |
| **Worker State** | `COMPLETED` | Clean automated completion of PCAP |
| **Selected Target** | `sample_traffic.pcap` | Authoritative reference fixture |
| **Packets Observed** | **29** | Exact count of packets in PCAP |
| **Flows Created** | **24** | Grouped by unidirectional 5-tuple |
| **Flows Completed** | **24** | 1 TCP FIN + 23 idle-flushed flows |
| **Flows Scored** | **24** | 100.0% inference completion |
| **Anomalies Detected** | **0** | Baseline smoke-test outcome |
| **Alerts Persisted** | **0** | Zero false alarms generated |
| **Unprocessed Flows** | **0** | Zero flow leakage |
| **Tier 1 Driver Drops** | `None` (`Unavailable`) | Honest provenance for offline file replay (no active live capture handle) |
| **Tier 2 Ingestion Drops** | **0** | Zero dropped packets |
| **Tier 3 Flow Queue Drops** | **0** | Zero dropped flows |
| **Model Hash Verified** | `True` | Runtime cryptographic integrity check |

**Score Distribution Across Scored Events (Ring Buffer):**
- **Count:** 24 flows
- **Minimum Score:** `0.127300` (isolated single-packet probes)
- **Median Score:** `0.127300`
- **Mean Score:** `0.137333`
- **Maximum Score:** `0.368100` (6-packet TLS stream)
- **Sample Event Breakdown:**
  - Flow 1: `192.168.1.25:49152 -> 104.244.42.1:443 [TCP]` | Score: `0.3681` | Risk: `LOW`
  - Flow 2: `192.168.1.10:53530 -> 8.8.8.8:53 [UDP]` | Score: `0.1273` | Risk: `LOW`
  - Flow 3: `192.168.1.10:53531 -> 8.8.8.8:53 [UDP]` | Score: `0.1273` | Risk: `LOW`
  - Flow 4: `192.168.1.50:8080 -> 192.168.1.50:8080 [TCP]` | Score: `0.1273` | Risk: `LOW` (`is_sm_ips_ports = 1`)
  - Flows 5–24: `10.10.10.100:60000..60019 -> 192.168.1.1:80 [TCP]` | Score: `0.1273` | Risk: `LOW`

### 3.5 Controlled High-Load Scoring & Alert Persistence Test
- **Command:** `python -m pytest tests/unit/test_detection_validation.py -v`
- **Observed Result:** 3 passed in 5.71s.
- **Controlled Test Flow:**
  - Synthetic input: $35,000$ packets, $50\,\text{MB}$, duration $1.0\,\text{s}$, sload $400\,\text{Mbps}$.
  - **Inference Score:** `0.8588` (`CRITICAL` risk tier).
  - **Outcome:** `StreamingInferenceWorker` successfully detected anomaly, passed deduplication, incremented `anomalies_detected`, and committed a `SecurityAlert` row with status `NEW`.
- **Database Isolation & Visibility Notice:** The automated test executes against an isolated, temporary SQLite test database (via pytest's `tmp_path / "det_val_test.db"`), completely decoupled from the running application's development database (`trafficshield_dev.db`), and drops all tables on fixture teardown. Consequently, this test-generated record is not visible in the running application's development dashboard; it validates the persistence engine and deduplication logic in an isolated, idempotent test harness.
- **Labeling Notice:** This is explicitly a synthetic test input verifying scoring logic and alert persistence; it does not constitute field-validated attack detection accuracy.

### 3.6 Graceful Teardown & Residual State Check
- **Command:** `POST /api/v1/capture/stop`
- **Observed Result:** HTTP 200 OK.
- **Post-Stop Telemetry:**
  - `Worker State: STOPPED`
  - `Queue Depth: 0`
  - `Unprocessed Flows: 0`
- Zero orphaned background threads or processing leaks detected.

---

## 4. Evaluator Presentation Sequence (5-Minute Runbook)

| Elapsed | Topic | Script & Narration | Visible Action / Screen |
| :---: | :--- | :--- | :--- |
| **0:00 – 1:00** | **Operational Problem & Threat Model** | TrafficShield targets critical infrastructure and OT networks using unidirectional data diodes where return traffic is physically blocked. Explain why bidirectional flow tools (like Zeek or standard NetFlow) break on one-way taps. | **Overview Dashboard** (`localhost:5173`): Show operational badges and Model Intelligence card confirming 13 features and threshold $\tau = 0.50$. |
| **1:00 – 2:00** | **Architecture & 13-Feature Contract** | Introduce the decoupled 3-tier pipeline: packet ingestion $\to$ unidirectional flow reconstruction $\to$ background worker scoring. Detail the One-Way Feature Policy enforcing 10 forward observables and 3 causal rate derivations without future leakage. | **Model Governance Ribbon**: Display frozen detector hash `c43bb5...` and verified preprocessor hash `effe96...`. |
| **2:00 – 3:15** | **Offline Replay & Honest Baseline Scoring** | Replay `sample_traffic.pcap` at 2.0x. Walk through the 29 packets and 24 reconstructed flows. Explain why scores cluster at $0.1273$ and max at $0.3681$: low-volume single-packet probes legitimately do not trigger false alarms. Highlight Tier 1 Driver drop honesty (`Unavailable` badge). | **Live Detection Tab**: Click **Start Replay**. Watch 24 flows complete and populate the ring buffer table with sub-millisecond latencies. Click **Stop Session** to show 0 unprocessed flows. |
| **3:15 – 4:15** | **Controlled Scoring & Alert Persistence** | Demonstrate that scoring and alert persistence function when anomalous volume is present by running the automated qualification test. Explain the deduplication window preventing SOC alert flooding, noting that unit tests intentionally operate on isolated transient databases rather than polluting development storage. | **Terminal & Overview / Alerts**: Run `pytest tests/unit/test_detection_validation.py -v`. Demonstrate passing test asserting score $\ge 0.85$ and database alert creation in the isolated test harness. Note that the dashboard alerts table displays persistent development records. |
| **4:15 – 5:00** | **Honest Boundaries & Qualification Roadmap** | Conclude with scientific integrity: software quality gates (579 backend tests, 28 frontend tests) pass 100%, but field detection effectiveness on routed SPAN/TAP links remains unvalidated due to observed TTL domain shift on consumer Wi-Fi. | **Architecture / Roadblocks Summary**: Point to current gate verdict: `READY FOR LOCAL DEMONSTRATION`. |

---

## 5. Known Operational Boundaries & Items Not Tested

1. **Items Not Tested in this Rehearsal (By Safety Constraint):**
   - No multi-hour live soak test executed.
   - No live packet transmission or attack injection against an active interface.
   - No live capture session or active native Npcap kernel-drop polling: Npcap is installed and active on the host (verified via C bindings and interface discovery), but native drop polling requires an active live capture handle. During offline PCAP replay, the capture source is an offline file reader, so the dashboard truthfully displays the `Unavailable` badge.
2. **Documented Limitations:**
   - **Domain Feature Shift:** The frozen XGBoost model was trained on multi-hop routed datasets where normal TTLs cluster at 62. On unrouted local links (e.g. Wi-Fi with initial TTLs of 128 or 255), benign flows may receive elevated anomaly scores.
   - **Horizontal Port Scan Limitation:** Because TrafficShield reconstructs unidirectional 5-tuple flows without cross-flow state aggregation, single-packet SYN scans across multiple ports appear as independent 1-packet flows scoring $0.1273$.
   - **Field Effectiveness:** Field true-positive and false-positive rates on operational OT links remain unvalidated until routed SPAN/TAP trials are conducted.

---

## 6. Final Readiness Verdict

**Verdict:** **`READY FOR LOCAL DEMONSTRATION (WITH DOCUMENTED LIMITATIONS)`**

**Evidence Base:**
- 579 backend tests passing ($100\%$).
- 28 frontend tests passing ($100\%$).
- Clean frontend production compilation.
- Frozen model hashes verified bit-for-bit.
- Full end-to-end replay, telemetry, and shutdown rehearsed live on running services.
- Truthful evaluator documentation and runbooks synchronized with actual runtime outputs.
