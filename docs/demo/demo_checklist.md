# TrafficShield — Pre-Demonstration Verification Checklist

**Document ID:** TS-DOC-DEMO-CHECKLIST  
**Auditor / Presenter:** TrafficShield Engineering Team  
**Evaluation Target:** M16 Local Demonstration Readiness  

---

## Pre-Demonstration Verification Matrix

Use this checklist to verify system state prior to conducting an evaluator walkthrough.

| Verification Item | Target Standard | Result / Evidence | Verification Status |
|:---|:---|:---|:---:|
| **Git Revision & Branch** | Clean working tree on `main` at expected commit | Commit `99da9e8` (`fix: harden TrafficShield shutdown...`) | [x] **VERIFIED** |
| **Python Environment** | Python ≥ 3.12 active | Python 3.14.8 AMD64 on Windows 11 | [x] **VERIFIED** |
| **Node.js Environment** | Node ≥ 18, npm ≥ 9 | Node 20+, npm 10+ | [x] **VERIFIED** |
| **Model Artifact Hashes** | Detector `c43bb5...`, Preprocessor `effe96...` | Computed SHA-256 hashes match baseline bit-for-bit | [x] **VERIFIED** |
| **Backend API Health** | `GET /api/v1/health` returns HTTP 200 `healthy` | `database: "connected"`, `model_loaded: true` | [x] **VERIFIED** |
| **Database Availability** | SQLite dev database initialized with schema | Tables created: `users`, `security_alerts`, `batch_metrics` | [x] **VERIFIED** |
| **Role-Based Auth** | Seeded development accounts function | Admin and Analyst login succeed via `/api/v1/auth/login` | [x] **VERIFIED** |
| **PCAP Fixture Provenance** | `sample_traffic.pcap` exists, safe RFC 1918 | 29 packets, 1,636 bytes, synthetic DNS/HTTPS/LAND | [x] **VERIFIED** |
| **Provenance Labeling** | Replay labeled `PCAP_REPLAY`, Live labeled `LIVE` | Provenance displayed on dashboard cards & event stream | [x] **VERIFIED** |
| **Driver / Interface Discovery**| `GET /api/v1/capture/interfaces` enumerates devices | Wi-Fi adapter (`Realtek RTL8852BE`) detected | [x] **VERIFIED** |
| **Fallback Path** | PCAP replay operates without Npcap driver | Offline replay functions 100% on standard sockets | [x] **VERIFIED** |
| **Alert Persistence** | Anomalous flows committed to `security_alerts` | Alerts persisted with deduplication window | [x] **VERIFIED** |
| **Graceful Shutdown** | Teardown drains queue; 0 unprocessed flows | Clean 5-stage shutdown; all flows scored | [x] **VERIFIED** |
| **Process Teardown** | Zero orphaned Python/Node processes | Verified cleanly terminated on `Ctrl+C` | [x] **VERIFIED** |
| **Browser Console Clean** | No unhandled runtime errors in React | 0 uncaught exceptions in browser devtools console | [x] **VERIFIED** |
| **Regression Suite Pass** | Full backend & frontend test suites 100% green | **579 / 579 backend**, **28 / 28 frontend** passing | [x] **VERIFIED** |

---

## Detailed Step-by-Step Checklist

### 1. Repository & Cryptographic Integrity Checks
- [x] Run `git status` — Ensure working directory is clean.
- [x] Run `python -c "import hashlib; print(hashlib.sha256(open('artifacts/models/production_detector.joblib','rb').read()).hexdigest())"`:
  - Expected: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
- [x] Run `python -c "import hashlib; print(hashlib.sha256(open('artifacts/models/production_preprocessor.joblib','rb').read()).hexdigest())"`:
  - Expected: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`

### 2. Service Startup & Connectivity
- [x] Start Flask API in Terminal 1: `python run.py`. Verify `http://127.0.0.1:5000` is listening.
- [x] Start Vite in Terminal 2: `cd frontend; npm run dev`. Verify `http://localhost:5173` is serving.
- [x] Query `/api/v1/health` — Verify `"status": "healthy"`.

### 3. Authentication Verification
- [x] Test login via PowerShell:
  ```powershell
  Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"admin","password":"AdminPass123!"}'
  ```
- [x] Verify HTTP 200 response containing signed bearer token and user object.

### 4. Replay Demonstration Walkthrough
- [x] Navigate to `http://localhost:5173` and click **Live Detection**.
- [x] Select **PCAP Replay** mode and choose `sample_traffic.pcap`.
- [x] Click **Start Replay**. Verify packets increment to 29 and flows populate event table.
- [x] Click **Stop Session**. Verify queue depth drains to 0 and unprocessed flows remain 0.

### 5. Fallback Contingency
- [x] If live capture fails or driver is absent, **do not attempt live capture during evaluator demo**.
- [x] Rely on the synthetic `sample_traffic.pcap` fixture, which runs deterministically in all environments without driver dependencies.
