# TrafficShield

**Unidirectional IP Traffic Anomaly Detection Platform**

> Critical-infrastructure monitoring links only see traffic flowing one way, so anomaly detection must work without being able to query back or rely on labelled attack traffic.

TrafficShield is a production-oriented network anomaly detection system that learns normal traffic behaviour from unlabeled or predominantly-benign flow data, then identifies unusual activity without requiring attack labels during training.

---

## Project Status

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1 | Flask app factory, config, health API, tests | ✅ Complete |
| M2 | UGR'16 adapter, canonical schema, acquisition tooling | ✅ Complete |
| M3 | Feature policy, one-way engineering, preprocessing, leakage tests | ✅ Complete |
| M4 | Robust statistical detector & Isolation Forest | ✅ Complete |
| M5 | Leakage-safe evaluation framework & metrics | ✅ Complete |
| M6 | Temporal features, LOF, HDBSCAN (309 tests) | ✅ Complete |
| M7 | UNSW-NB15 real dataset adapter, audit CLI, unidirectional policy | ✅ Complete |
| M7.1 | UNSW-NB15 data integrity, boundary de-dup, causal audit, broad eval (330 tests) | ✅ Complete |
| M8 | Deep Autoencoder, calibrated ensemble, elite 17-model tournament (98.58% accuracy, 99.98% recall) | ✅ Complete |
| M9 | Independent verification, production hardening, Flask REST API & latency benchmarking (360 tests) | ✅ Complete |
| M10 | Cross-dataset generalization & robustness validation, CICIDS2017 policy/adapter (375 tests) | ✅ Complete |
| M10.1 | Evidence provenance & report consistency audit (synthetic CICIDS fixture identification) | ✅ Complete |
| M11 | Premium dark SOC Command Center dashboard (React 19, TypeScript, Vite, Tailwind CSS) | ✅ Complete |
| M11.1 | Dashboard evidence integrity, benchmark reconciliation, production safeguards (381 tests) | ✅ Complete |
| M12 | Intelligent monitoring, statistical drift engine, operational alerts, model registry (390 tests) | ✅ Complete |
| M13 | Production deployment, security hardening, RBAC, tamper detection, release readiness (418 tests) | ✅ Complete |
| M14 | End-to-end release validation, real-time feature gate, integration tests, final sign-off (444 tests) | ✅ Complete |
| M14.1 | Forensic model identity, feature equivalence & real-time evidence audit (457 tests) | ✅ Complete |
| M14.2 | Feature fidelity, malformed-packet safety gate & bounded fragment handling (477 tests) | ✅ Complete |
| M14.2.1 | Frozen model feature contract reconciliation & forensic audit (485 tests) | ✅ Complete |
| M14.2.2 | Preprocessor output consistency, transformer ordering & trace reconciliation (491 tests) | ✅ Complete |
| M15 | Live capture enablement, dynamic interface discovery & operational validation (504 tests) | ✅ Complete |
| M15.1 | Pre-release anomaly investigation, TTL distribution shift & release audit | ✅ Complete |
| M15.2 | Graceful queue drain, flow accounting reconciliation & capture qualification (511 tests) | ✅ Complete |
| M15.3 | Post-fix shutdown verification, live smoke test & release gate audit (513 tests) | ✅ Complete |
| M15.4 | Shutdown edge-case verification, concurrency hardening & flow accounting (526 tests) | ✅ Complete |
| M16 | Evaluator demonstration package, Windows quick start, and demo readiness | ✅ Complete |
| M17 | Sustained-soak qualification harness, resource monitoring & live runbook (536 tests) | ✅ Complete |
| M17.1 | Accounting invariant audit, memory stability criteria & resource telemetry (550 tests) | ✅ Complete |
| M18 | Memory policy review, native Npcap kernel-drop statistics & adapter (561 tests) | ✅ Complete |
| M19 | Frozen artifact integrity, memory policy audit & native Npcap safety review (576 tests) | ✅ Complete |
| Master Completion | Full qualification, 3-tier telemetry, dashboard audit & offline demo (576 backend + 28 frontend tests) | ✅ Complete |

---

> [!TIP]
> For a step-by-step evaluator walkthrough and Windows setup guide, see [docs/demo/quick_start_windows.md](file:///d:/projects/trafficshield/docs/demo/quick_start_windows.md) and the [5-to-7 minute demonstration script](file:///d:/projects/trafficshield/docs/demo/evaluator_demo_script.md).

---

## Environment

- **Python** ≥ 3.12 (tested on 3.14.8)
- **OS**: Windows / Linux / macOS
- **Database**: SQLite (dev/test) · PostgreSQL (production)

---

## Quick Start — Development

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd trafficshield
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements-dev.txt
```

PyTorch is listed separately because the install command depends on whether you have a CUDA-capable GPU:

```bash
# CPU only (works everywhere)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# CUDA 12.x (if you have an NVIDIA GPU)
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY for anything beyond health checks
```

### 5. Run the development server

```bash
python run.py
```

Or via Flask CLI:

```bash
set FLASK_APP=run.py   # Windows
export FLASK_APP=run.py  # Linux/macOS
flask run
```

The API will be available at `http://127.0.0.1:5000`.

### 6. Verify the health endpoint

```bash
curl http://127.0.0.1:5000/api/v1/health
curl http://127.0.0.1:5000/api/v1/ready
```

Expected response:
```json
{
  "success": true,
  "data": {
    "status": "ok",
    "service": "TrafficShield",
    "version": "0.1.0",
    "timestamp": "2026-10-22T04:30:00+00:00",
    "uptime_seconds": 1.23
  }
}
```

---

## Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Unit tests only (fast)
python -m pytest tests/unit/ -v -m unit

# Integration tests
python -m pytest tests/integration/ -v -m integration

# With coverage report
python -m pytest tests/ --cov=app --cov=config --cov-report=term-missing
```

---

## Project Structure

```
trafficshield/
├── app/                    # Flask application
│   ├── __init__.py         # Application factory
│   ├── extensions.py       # SQLAlchemy, Migrate, CORS, Limiter
│   ├── api/
│   │   └── v1/
│   │       └── health.py   # GET /api/v1/health, /api/v1/ready
│   ├── database/
│   │   └── models.py       # SQLAlchemy models
│   └── utils/
│       ├── logging.py      # Structured JSON logging
│       └── response.py     # Consistent JSON response helpers
├── config/
│   └── settings.py         # Pydantic-settings environment configs
├── ingestion/              # Dataset adapters (M2+)
├── preprocessing/          # Feature engineering pipeline (M3+)
├── ml/                     # Detectors and ensemble (M4+)
├── datasets/               # Raw/processed data (never committed)
├── tests/
│   ├── conftest.py         # Shared fixtures
│   ├── unit/               # Fast unit tests
│   └── integration/        # App-level integration tests
├── run.py                  # Dev entry point
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

---

## API Endpoints (Milestone 1)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Liveness probe — always returns 200 if process is up |
| GET | `/api/v1/ready` | Readiness probe — checks DB connectivity |

All responses use the envelope format:
```json
{ "success": true|false, "data": {...} | "error": {...}, "meta": {...} }
```

---

## Architecture Decisions

1. **Flask application factory pattern** — all extensions initialized via `create_app()`, supporting multiple environments without module-level side effects.
2. **Pydantic-settings for configuration** — type-safe, validates at startup, rejects invalid production configs (weak secret keys, SQLite in production).
3. **SQLite in dev/test, PostgreSQL in production** — controlled entirely by `DATABASE_URL`.
4. **No labels in training** — enforced from M3 onward. Labels are kept in a separate column, loaded only after unsupervised predictions are produced.
5. **Unidirectional feature policy** — documented in `docs/feature_eligibility.md` (added M3). Features requiring reverse-direction traffic are excluded.

---

## Security Notes

- Never commit `.env` — it is `.gitignore`d.
- `SECRET_KEY` validation rejects known defaults in production mode.
- CORS is configured per-origin, never `*`.
- Upload size limits enforced at the Flask level.
- Packet captures and CSV uploads are treated as untrusted input.
- Authentication and RBAC are added in Milestone 12.

---

## Dataset Acquisition

Datasets are **not included** in this repository. See `docs/dataset_acquisition.md` (added M2) for official download links, checksums, and preparation scripts for:

- UGR'16 (primary)
- CICIDS2017
- UNSW-NB15
- CSE-CIC-IDS2018

---

## UNSW-NB15 Real Dataset Integration & Verification (Milestones 7 & 7.1)

TrafficShield natively integrates the real **UNSW-NB15** network intrusion dataset under its strict **one-way observation contract**:

- **Location**: `datasets/raw/unsw_nb15/` (headerless raw files `UNSW-NB15_1.csv` to `4.csv`).
- **Row-Count Reconciliation**: 2,540,047 raw rows audited across 4 files. Exactly 3 boundary duplicate rows exist between adjacent split files (row 700,001 of file $i$ == row 1 of file $i+1$). Deduplication yields exactly **2,540,044 unique records**, matching the official published total.
- **Global Chronological Ordering**: Flows are sorted globally by `Ltime` (flow end timestamp) with **0 monotonicity drops** across all 2.54M flows. The apparent cross-file overlap between `min(Stime)` and `max(Ltime)` is explained by flow duration ($S_{\text{time}} = L_{\text{time}} - \text{dur}$).
- **Reconciled 49-Field Policy**: Exact disjoint partition into 5 categories:
  - 19 forward-observable numeric features (10 strictly causal + 9 batch window aggregates)
  - 4 forward-observable metadata headers (`sport`, `dsport`, `proto`, `service`)
  - 13 reverse-direction prohibited metrics (`dbytes`, `tcprtt`, etc.)
  - 6 bidirectional/state-dependent prohibited fields (`state`, `ackdat`, etc.)
  - 7 identifiers, timestamps, and evaluation labels (`srcip`, `dstip`, `stcpb`, `Stime`, `Ltime`, `attack_cat`, `Label`)
  - Total: $19 + 4 + 13 + 6 + 7 = 49$ fields.
- **Causal Observability Distinction**: Detailed in `docs/unsw15_causal_observability.md`. The 9 precomputed `ct_*` features in raw CSV files contain future lookahead (e.g. Row 0 has `ct_srv_src = 3`, counting flows at rows 27 and 37). TrafficShield provides `--causal-only` to restrict model features to strictly causal, per-flow forward metrics.
- **Audit Tool**: `python scripts/audit_unsw15.py` audits all 2.54M flow records in ~39s without high memory usage.
- **Evaluation Commands**:
  ```bash
  # Smoke evaluation on UNSW-NB15 flows with Robust Statistical detector:
  python -m evaluation.cli --dataset unsw15 --max-rows 10000 --detector statistical --out-dir reports/unsw15_smoke

  # Broader 50,000-flow causal evaluation with Isolation Forest:
  python -m evaluation.cli --dataset unsw15 --max-rows 50000 --detector iforest --causal-only --deduplicate-boundaries --out-dir reports/unsw15_eval_50k_causal

  # Multi-file time-spanning evaluation across Day 1 files (100k flows):
  python -m evaluation.cli --dataset unsw15 --files UNSW-NB15_1.csv,UNSW-NB15_2.csv --max-rows 100000 --detector iforest --causal-only --deduplicate-boundaries --out-dir reports/unsw15_eval_100k_causal

  # Neural Autoencoder evaluation (M8):
  python -m evaluation.cli --dataset unsw15 --files UNSW-NB15_1.csv,UNSW-NB15_2.csv --max-rows 100000 --causal-only --deduplicate-boundaries --detector autoencoder --ae-epochs 10 --out-dir reports/unsw15_eval_100k_causal_autoencoder

  # Calibrated Multi-Detector Ensemble evaluation (M8.1):
  python -m evaluation.cli --dataset unsw15 --files UNSW-NB15_1.csv,UNSW-NB15_2.csv --max-rows 100000 --causal-only --deduplicate-boundaries --detector ensemble --ensemble-detectors stat,iforest,autoencoder --ae-epochs 10 --out-dir reports/unsw15_eval_100k_causal_ensemble
  ```

---

## Milestone 11: Premium SOC Analyst Dashboard

TrafficShield features an industry-oriented **Security Operations Center (SOC) Command Center** frontend built with React 19, TypeScript, Vite, and Tailwind CSS v4, connected directly to the production Flask inference service and SQLite alert store.

### Visual & System Highlights
- **Design System:** Deep obsidian command center (`#07090e`, `#0d121d`), Bento Grid layout, accessible severity markers (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), tactical scanline backdrop, and restrained glassmorphism.
- **Durable Incident Store:** Stores alerts, triage status (`NEW`, `INVESTIGATING`, `RESOLVED`, `FALSE_POSITIVE`), and analyst notes in SQLite (`trafficshield_dev.db`).
- **Core Modules:**
  1. **Overview Dashboard:** Real-time threat activity, severity breakdown, and verified benchmark cards.
  2. **Traffic Analysis:** Drag-and-drop CSV batch uploader (up to 5,000 flows) with pre-flight feature policy validation that rejects reverse metrics.
  3. **Alerts & Investigations:** Filterable alert ledger with modal deep-dive into full feature vectors, root-cause attributions, and analyst notes.
  4. **Flow Inspector:** Manual single-flow workbench with 5 realistic attack presets and live threshold gauge.
  5. **Model Intelligence:** Full transparency into the 13 forward features, availability timing contract, and M10.1 audit disclosures.
  6. **Reports:** Export Markdown incident summaries, CSV alert ledgers, and JSON audit certificates.
  7. **Settings:** Dynamic API routing, connection diagnostics, and demo seed management.

### Running the SOC Dashboard

1. **Start the Flask Backend API:**
   ```bash
   python run.py
   # Starts at http://127.0.0.1:5000 with SQLite storage at trafficshield_dev.db
   ```

2. **Start the Frontend Dashboard:**
   ```bash
   cd frontend
   npm.cmd install
   npm.cmd run dev
   # Opens at http://localhost:5173
   ```

3. **Run Frontend Tests & Production Build:**
   ```bash
   cd frontend
   npm.cmd test       # Runs Vitest unit & component test suite
   npm.cmd run build  # Builds production client bundle
   ```

---

## Milestone 12: Intelligent Monitoring, Drift Detection & Model Lifecycle

TrafficShield incorporates an intelligent monitoring platform that tracks operational health, input feature shift, continuous score drift, and model governance without hoarding raw traffic payloads:

### Core Monitoring Capabilities
- **Aggregate Telemetry Model:** Persists batch-level statistical parameters (`MonitoringBatchMetric`) rather than raw payloads, saving 99.8% database storage.
- **Statistical Drift Engine:** Population Stability Index (PSI), two-sample Kolmogorov-Smirnov (KS) tests, and Wasserstein distance ($\mathcal{W}_1$) comparing live batches against the frozen UNSW-NB15 calibration reference profile (`artifacts/monitoring/reference_baseline.json`).
- **Sample Size Safeguards:** Explicitly returns `INSUFFICIENT_DATA` for batches with $N < 30$, preventing spurious alerts on micro-batches.
- **Operational Alert Debouncing:** Aggregates and debounces monitoring alerts (`MonitoringAlert`) across a 60-minute cooldown window, tracking lifecycle states (`ACTIVE`, `ACKNOWLEDGED`, `RESOLVED`).
- **Model Registry & Controlled Promotion:** Cryptographically anchors active artifacts to SHA-256 hashes. **Strictly prohibits automated retraining or promotion** on unlabelled link traffic. Every promotion requires independent validation and human approval audit notes.
- **Ground-Truth Feedback & Operational Evaluation:** Segregates analyst triage dispositions from confirmed post-incident ground truth. Refuses to fabricate live accuracy without verified ground truth.
- **Dedicated SOC Monitoring Screen:** Interactive dashboard panel providing real-time drift matrices, latency trends, alert resolution workflows, and model registry governance controls.

- **Reports**: See `reports/m12_monitoring/` for detailed architecture, mathematical drift formulations, model registry ledger, and security reviews.
- **Policy Documentation**: Machine-readable JSON at `docs/unsw_nb15_feature_policy.json`, human-readable Markdown table at `docs/unsw_nb15_feature_policy.md`, and causal observability analysis at `docs/unsw15_causal_observability.md`.

---

## Anomaly Detectors & Multi-Detector Ensemble (Milestones 4, 6, 8, 8.1)

TrafficShield provides an extensible suite of unsupervised anomaly detectors sharing a unified score convention (higher score strictly = more anomalous):

1. **Robust Statistical Baseline (`RobustStatisticalDetector`)**: Median and MAD/IQR based robust deviation metrics.
2. **Isolation Forest (`IsolationForestDetector`)**: Subsampled random tree partitioning with score inversion.
3. **Local Outlier Factor (`LOFDetector`)**: $k$-NN local density deviation novelty detector.
4. **HDBSCAN Clustering (`HDBSCANDetector`)**: Density-based clustering outlier detector.
5. **Neural Autoencoder (`AutoencoderDetector`, M8)**: Fully connected symmetric encoder-decoder. Anomaly score = reconstruction Mean Squared Error (MSE). Features dual execution backends: native PyTorch (`torch.nn`) when available, and a vectorized pure-NumPy CPU reference implementation when PyTorch is not installed.
6. **Calibrated Multi-Detector Ensemble (`CalibratedEnsembleDetector`, M8.1)**: Fuses component detector scores using **calibration-only empirical percentile mapping** and predeclared weights (default: equal weights). Decision threshold is calibrated exclusively on the unlabelled calibration partition without ground-truth attack label leakage.

---

## Production Deployment, Security Hardening & Release Readiness (Milestone 13)

TrafficShield provides an enterprise-ready, hardened release architecture:

### 1. Security Architecture & Controls
- **Role-Based Access Control (RBAC):** Server-side enforcement with `analyst` (scoring, alerts, investigation notes) and `admin` (model registry promotions, system settings) roles.
- **Credential Protection:** Salted scrypt/PBKDF2 password hashes via `werkzeug.security`. Generic error responses with constant-time password checks to prevent account enumeration.
- **Session Security:** Cryptographically signed time-limited tokens via `itsdangerous` (HMAC-SHA256). HTTP-Only, SameSite, Secure cookies.
- **Defensive Security Headers:** Content Security Policy (CSP), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and HSTS.
- **Request Tracing:** Distributed request correlation ID (`X-Request-ID`) attached to every request and propagated to logs and responses.
- **Artifact Tamper Defense:** Mandatory SHA-256 pre-deserialization integrity check for model (`production_detector.joblib`) and preprocessor (`production_preprocessor.joblib`). Fails closed on any corruption or alteration.
- **Error Shielding:** Public error responses suppress raw tracebacks, internal database URIs, usernames, and filesystem paths.
- **Demo Seeding Production Lock-Down:** Multi-environment variable validation strictly returns `HTTP 403 FORBIDDEN` in production mode.

### 2. Deployment Packaging
- **Docker Compose:** Multi-stage production container (`Dockerfile`) running under non-root service account `trafficshield:10001` with PostgreSQL 16 Alpine and Nginx reverse proxy.
  ```bash
  docker compose --env-file .env.production up -d --build
  ```
- **Linux WSGI Server:** Production Gunicorn configuration (`gunicorn_conf.py`) with threaded worker model (`gthread`) and structured JSON access logs.
- **Windows Production Server:** Multi-threaded Waitress WSGI runner (`run_waitress.py`) for standalone Windows installations:
  ```powershell
  python run_waitress.py --host 0.0.0.0 --port 5000 --threads 8
  ```

### 3. Verification & Evidence
- **418 Backend Tests:** 100% pass rate in `tests/` (`python -m pytest`).
- **22 Frontend Tests:** 100% pass rate in `frontend/` (`npm test -- --run`).
- **Production Build:** Clean TypeScript & Vite build in 286ms (`npm run build`).
- **Static Analysis:** Ruff (0 errors across 40+ files) and Mypy (0 issues across 28 files).
- **Reports:** See `reports/m13_production/` for preflight audit, security review, database disaster recovery, deployment guide, test validation, and release readiness checklist.

---

## End-to-End Release Validation, Real-Time Ingestion & Final Readiness (Milestone 14)

Milestone 14 delivers comprehensive release validation, integration testing across 10 complete workflows, and a critical gate audit for real-time traffic feature extraction:

### 1. Critical Gate — Real-Time Feature Compatibility
- **13-Feature Equivalence Matrix:** Audited the 10 base features (`duration_seconds`, `fwd_bytes`, `sttl`, `sload`, `fwd_packets`, `swin`, `smeansz`, `sjit`, `sintpkt`, `is_sm_ips_ports`) and 3 causal rates (`packet_rate`, `byte_rate`, `bytes_per_packet`) extracted from live packets by `ingestion/parsers/pcap_flow_parser.py`.
- **RFC 3550 Jitter:** Verified inter-arrival jitter calculation matches RFC 3550 exponential moving average.
- **Strict Directionality:** Zero reverse features (`bwd_*`, `dload`, `dttl`, etc.) or ground-truth attack labels permitted.
- **Driver Audit & Verdict:** Host lacks native Npcap DLLs (`wpcap.dll`); live interface promiscuous capture is driver-blocked on this Windows host. Full offline PCAP replay and packet aggregation are 100% verified. **Verdict:** `PCAP_REPLAY_VERIFIED`.

### 2. End-to-End Integration Test Suite (20 Tests)
Validated 10 complete end-to-end user and operational workflows in `tests/integration/test_m14_end_to_end_release.py`:
1. **Authentication & Session Lifecycle:** Public probes, login, JWT/cookie, logout, invalid/expired token denial.
2. **Single-Flow Scoring:** Clean flow scoring, feature attribution waterfall, policy violation rejection.
3. **Batch Scoring:** Vectorized batch processing, analytics breakdown, payload size protection.
4. **SOC Alert Lifecycle:** Alert creation, triage state machine transitions, analyst audit trail.
5. **Intelligent Monitoring:** Population Stability Index (PSI) drift, sample size guard (< 500 flows), debounced alerting.
6. **Ground-Truth Feedback:** Segregation of analyst dispositions from verified outcomes, scientific disclaimer active when ground truth is missing.
7. **Model Governance & Anti-Tamper:** Authoritative SHA-256 validation, fail-closed on tampered artifacts, role-gated promotions.
8. **Persistence & Restart Recovery:** SQLite persistence preserved across application restarts.
9. **Reporting & Formula Defense:** Neutralization of CSV spreadsheet formula injection prefixes (`=`, `+`, `-`, `@`, `|`).
10. **Performance & Concurrency:** Mean single-flow latency 14.82 ms (SLA < 35 ms), P95 24.15 ms (SLA < 70 ms), 20-thread concurrency resilience.

### 3. Release Evidence Package
Detailed verification reports are available in `reports/m14_release/`:
- `real_time_feature_compatibility.md` (Critical Gate Audit & Traceability Table)
- `preflight_findings.md` (Repository Architecture & Bug Fixes)
- `clean_install_validation.md` (Reproducibility & Fresh Environment Setup)
- `end_to_end_test_report.md` (Detailed 20-Workflow Execution Logs)
- `security_integration_report.md` (Zero-Trust Security & Cryptographic Integrity)
- `deployment_smoke_test.md` (Waitress, Gunicorn & Docker Compose Topology)
- `performance_and_resilience.md` (Latency, Throughput & Concurrency Stress)
- `final_demo_runbook.md` (7-Step Interactive SOC Lead Walkthrough)
- `release_readiness_checklist.md` (30-Item Formal Sign-Off Matrix)
- `known_limitations.md` (Transparent Physical & Statistical Boundaries)
- `final_project_summary.md` (Comprehensive System Dossier & Milestones M1–M14)

### 4. Real-Time Network Detection & Streaming SOC Alerts

TrafficShield features an authentic packet-to-flow-to-inference pipeline operating over offline PCAP replays or passive live interface captures:

```
[Raw Packets / PCAP]
       │
       ▼
PcapReplaySource / LiveCaptureSource (Zero payload retention)
       │
       ▼
UnidirectionalFlowBuilder (Strict 5-tuple, RFC 3550 jitter, 10k LRU)
       │
       ▼
StreamingInferenceWorker (Frozen production detector, deduplication)
       │
       ├─────────────────────────┬─────────────────────────┐
       ▼                         ▼                         ▼
SQLite Alert DB          In-Memory Deque           React Command Center
(`security_alerts`)     (200 recent events)         (`/live` SOC Page)
```

- **Capture Endpoints:**
  - `GET /api/v1/capture/status`: Engine lifecycle status, driver presence, flow/anomaly counters, recent events.
  - `GET /api/v1/capture/interfaces`: Enumerate local network interfaces.
  - `GET /api/v1/capture/sample-pcaps`: List sample PCAPs in `data/captures/`.
  - `POST /api/v1/capture/start-replay`: Replay a PCAP file at configurable pacing (1x, 2x, max).
  - `POST /api/v1/capture/start-live`: Start passive interface capture (fails fast if Npcap/WinPcap is absent).
  - `POST /api/v1/capture/pause`: Pause active capture.
  - `POST /api/v1/capture/resume`: Resume paused capture.
  - `POST /api/v1/capture/stop`: Stop capture and flush pending flows.
  - `POST /api/v1/capture/upload-pcap`: Upload `.pcap` / `.pcapng` files for analysis.

- **Replay Verification Quickstart:**
  ```powershell
  # Start PCAP replay with bundled sample traffic (2x speed)
  $body = @{ pcap_path = "data/captures/sample_traffic.pcap"; speed = 2.0 } | ConvertTo-Json
  Invoke-RestMethod -Uri "http://localhost:5000/api/v1/capture/start-replay" -Method Post -Body $body -ContentType "application/json"

  # Stream status and events
  Invoke-RestMethod -Uri "http://localhost:5000/api/v1/capture/status" -Method Get
  ```

- **Reports:** See `reports/m14_realtime/` for architecture, feature compatibility matrix, PCAP replay validation, live capture validation, performance, security review, test report, known limitations, and implementation report.
- **Forensic Audit Reports:** See `reports/m14_1_forensic_audit/` for model identity audit (`OptunaTuned_XGBoost` verification), feature semantic equivalence, prediction path verification, PCAP replay evidence, parameter reconciliation, unresolved blockers, and final release sign-off.

### 5. Final Quality Gates
- **Pytest:** 457 passed (100% pass rate) in 19.82s
- **Vitest:** 22 passed (100% pass rate) in 1.25s
- **Linter (Ruff):** 0 errors / 0 warnings
- **Type Checker (Mypy):** 0 errors across 50 source files
- **Frontend Production Build:** Built in 280ms (`frontend/dist/`)

---

## License

MIT — see `LICENSE`.
