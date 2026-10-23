# TrafficShield — Development Plan & Progress Tracker

## Environment
- **OS**: Windows 11, Intel i5-13450HX (10C/16T)
- **Python**: 3.14.8 (bare, no packages pre-installed)
- **Project Root**: `d:\projects\trafficshield`
- **Start Date**: 2026-10-22

## Architecture Overview

```mermaid
flowchart TD
    subgraph Ingestion
        CSV[CSV Upload] --> Validator
        PCAP[PCAP Upload] --> Parser --> Validator
        NF[NetFlow/IPFIX] --> NFAdapter --> Validator
    end
    Validator --> CanonicalSchema[Canonical Flow Schema]
    CanonicalSchema --> FeatureEng[Feature Engineering\n1-way eligible only]
    FeatureEng --> Preprocess[Preprocessing Pipeline\nfit on train only]
    Preprocess --> Detectors
    subgraph Detectors
        StatBase[Detector A\nStatistical Baseline]
        IF[Detector B\nIsolation Forest]
        LOF[Detector C\nLOF Novelty]
        DBSCAN[Detector D\nHDBSCAN Clustering]
        AE[Detector E\nAutoencoder PyTorch]
        Temporal[Detector F\nTemporal Behaviour]
    end
    Detectors --> Ensemble[Score Normalization\n& Fusion]
    Ensemble --> Explainability[Evidence-Backed Explanation]
    Explainability --> RiskScore[Risk Scoring]
    RiskScore --> Incidents[Incident Correlation]
    Incidents --> FlaskAPI[Flask REST API v1]
    FlaskAPI --> ReactDash[React SOC Dashboard]
    FlaskAPI --> PostgreSQL[(PostgreSQL / SQLite)]
    FlaskAPI --> MLflow[(MLflow Registry)]
```

## Milestones

| # | Milestone | Status | Tests | Notes |
|---|-----------|--------|-------|-------|
| 1 | Repo setup, Flask app factory, config, health API, basic tests | ✅ **DONE** | ✅ 46/46 Pass · 0.60s | |
| 2 | UGR'16 dataset inspection, adapter, canonical schema | ✅ **DONE** | ✅ 174/174 Pass · 2.67s | Review & regression fixes complete |
| 3 | One-way feature eligibility, preprocessing, leakage checks | ✅ **DONE** | ✅ 231/231 Pass · 5.44s | Feature policy, pipeline, split, artifacts, 12 leakage checks |
| 4 | Statistical baseline + Isolation Forest, model persistence, scoring API | ✅ **DONE** | ✅ 258/258 Pass · 2.45s | RobustStatisticalDetector, IsolationForestDetector, frozen thresholds |
| 5 | Evaluation framework (label-blind train, label-based post-prediction) | ✅ **DONE** | ✅ 290/290 Pass · 7.10s | 3-way partition, metrics, sweep, CLI, 14 leakage checks |
| 6 | Behavioural/temporal features, LOF, HDBSCAN | ✅ **DONE** | ✅ 309/309 Pass · 4.31s | Causal temporal features, LOF novelty, HDBSCAN density detector |
| 7 | UNSW-NB15 real dataset adapter, audit CLI, unidirectional policy | ✅ **DONE** | ✅ 324/324 Pass · 14.51s | Full 2.54M flow audit, 49-field directional policy, real evaluation |
| 7.1 | UNSW-NB15 data integrity, boundary de-dup, causal audit, broad eval | ✅ **DONE** | ✅ 330/330 Pass · 4.94s | 3-row boundary de-dup (2,540,044 unique), Ltime monotonicity (0 drops), 49-field disjoint policy (19+4+13+6+7), causal distinction |
| 8 | Neural Autoencoder (CPU PyTorch + NumPy reference fallback) | ✅ **DONE** | ✅ 338/338 Pass · 4.41s | Symmetric MLP, MSE reconstruction scoring, CPU-first, early stopping, artifact SHA-256 persistence |
| 8.1 | Calibrated Multi-Detector Ensemble | ✅ **DONE** | ✅ 349/349 Pass · 4.68s | Empirical percentile score normalization, equal/predeclared weights, label-blind frozen thresholding |
| 8.2 | Elite Model Tournament, Scoring REST API, & Explanations | ✅ **DONE** | ✅ 359/359 Pass · 16.12s | 17-model competitive benchmark, Optuna HPO, SHAP attributions, production REST API (/predict, /batch, /info) |
| 9 | Independent Verification, Production Hardening & Deployment Readiness | ✅ **DONE** | ✅ 360/360 Pass · 6.46s | Independent tournament verification (98.10% test, 96.98% Day 2 holdout), arithmetic audit, feature policy audit, split integrity audit, category reconciliation (11,430 vs 5,858), REST API hardening (400/413/422/500), SHA-256 artifact verification, sub-4ms single-flow & 627k flow/s batch latency benchmarks |
| 10 | Cross-Dataset Generalization & Robustness Validation | ✅ **DONE** | ✅ 375/375 Pass · 6.04s | CICIDS2017 unidirectional policy & adapter, 107-feature compatibility matrix, transfer feasibility audit (sttl / is_sm_ips_ports limits), 9-feature common subspace model (91.85% within-test, 84.38% Day 2), 24-day KS/Wasserstein drift audit |
| 10.1 | Evidence Provenance & Report Consistency Audit | ✅ **DONE** | ✅ 375/375 Pass · 6.21s | Forensic trace of 10,000 synthetic flows, relabeled "CICIDS2017 Stream" to Synthetic_CICIDS2017_Fixture, reconciled 20 raw + 4 derived = 24 features, 58 policy specs, 107 matrix rows, CM metric reproduction |
| 11 | Premium SOC Analyst Dashboard & Persistent Storage | ✅ **DONE** | ✅ 377 Backend / 13 Frontend Pass | React 19 + TypeScript + Vite + Tailwind v4 dark SOC command center, 7 pages, SQLite alert persistence, triage lifecycle, batch scoring, CSV/JSON reports |
| 11.1 | Dashboard Evidence Integrity, Benchmark Reconciliation & Security Audit | ✅ **DONE** | ✅ 381 Backend / 17 Frontend Pass | Reconciled M9 benchmarks (98.10% test, 96.97% Day 2), demo KPI provenance tracking & warning banner, demo seeding 403 in prod, input boundary limits (batch <= 1k, score [0,1], notes <= 2k) |
| 12 | Intelligent Monitoring, Drift Detection and Model Lifecycle | ✅ **DONE** | ✅ 390 Backend / 22 Frontend Pass | Aggregate telemetry model, explainable statistical drift engine (PSI, KS, Wasserstein), sample-size safeguards (N<30 INSUFFICIENT_DATA), debounced operational alerts, model registry & controlled promotion governance, ground-truth feedback tracker, React dark SOC Monitoring screen |
| 13 | Production Deployment, Security Hardening & Release Readiness | ✅ **DONE** | ✅ 418 Backend / 22 Frontend Pass | Security fail-fast config, User model & PBKDF2/scrypt, token session auth & RBAC (analyst/admin), model artifact SHA-256 integrity verification & fail-closed tamper defense, CSP & defense-in-depth security headers, X-Request-ID tracing, sanitized error shielding, disposable DB online backup/restore test, multi-stage Dockerfile, docker-compose (App+Postgres+Nginx), Gunicorn & Waitress production WSGI runners, 8 comprehensive reports |
| 14 | End-to-End Release Validation, Security Integration Testing & Final Sign-Off | ✅ **DONE** | ✅ 444 Backend / 22 Frontend Pass | Critical Gate Real-Time Feature Compatibility Audit, 10 end-to-end integration workflows (20 tests), clean install validation, latency benchmark, 11 release reports |
| 14.1 | Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit | ✅ **DONE** | ✅ 457 Backend / 22 Frontend Pass | Verified actual estimator is OptunaTuned_XGBoost (XGBClassifier) resolving Random Forest errata; verified fwd_bytes = IPv4 Total Length (Argus sbytes); 13 features audited; 29-packet trace confirmed (24 flows); test counts (444->457) & drift guard (N<30) reconciled; 7 forensic reports in reports/m14_1_forensic_audit/ |

---

## Milestone 1 — Detail

### Implemented
- [x] Project directory structure (modular, milestone-scoped)
- [x] `requirements.txt` and `requirements-dev.txt` (Python 3.14 compatible)
- [x] `pyproject.toml` with project metadata
- [x] `.env.example` with all configuration keys
- [x] `.gitignore` covering secrets, datasets, model artifacts, venv
- [x] `config/settings.py` — environment-aware configuration classes
- [x] `app/__init__.py` — Flask application factory
- [x] `app/extensions.py` — SQLAlchemy, Migrate, CORS, limiter
- [x] `app/api/v1/health.py` — `GET /api/v1/health`, `GET /api/v1/ready`
- [x] `app/api/__init__.py`, `app/api/v1/__init__.py` — Blueprint registration
- [x] `app/utils/response.py` — Consistent JSON response helpers
- [x] `app/utils/logging.py` — Structured JSON logging
- [x] `app/database/models.py` — Base SQLAlchemy models (AuditMixin)
- [x] `run.py` — Development entry point
- [x] `tests/conftest.py` — Pytest fixtures (SQLite test client)
- [x] `tests/unit/test_health.py` — Health endpoint unit tests
- [x] `tests/unit/test_config.py` — Configuration tests
- [x] `tests/integration/test_app_factory.py` — App factory integration tests

### Test Results
```
pytest tests/ -v
46 passed in 0.60s

platform win32 -- Python 3.14.8, pytest-9.1.1
plugins: cov-7.1.0, flask-1.3.0, mock-3.17.0
```

### Live Server Verification
```
GET http://127.0.0.1:5000/api/v1/health → 200 OK
{"success": true, "data": {"status": "ok", "service": "TrafficShield", ...}}

GET http://127.0.0.1:5000/api/v1/ready → 200 OK  
{"success": true, "data": {"status": "ok", "checks": {"database": {"status": "ok"}}}}
```

### Known Limitations
- No packages installed yet; install step required before tests pass
- Redis/Celery not started for M1 (not needed until M4+)
- No auth on health endpoints (intentional for ops tooling)

### Git Commit
```
git add -A
git commit -m "feat(m1): Flask app factory, health API, config, base tests"
```

---

## Engineering Decisions & Assumptions

1. **Python 3.14.8** — Some packages may lag. Using conservative versions in requirements.
2. **SQLite for dev/test**, PostgreSQL for production. `DATABASE_URL` env var controls which.
3. **No Redis/Celery in M1** — Added to requirements, started in M4+ when background jobs are needed.
4. **One-way feature policy** — Documented in `docs/feature_eligibility.md` (created M3).
5. **Labels never enter training** — Enforced by code contract in feature pipeline (M3+).
6. **CUDA not assumed** — PyTorch CPU-only install unless CUDA detected (M7).
7. **Large datasets not auto-downloaded** — Acquisition scripts + checksums provided (M2).
8. **Synthetic data clearly labelled** — Used only for unit tests, never cited as real performance.

---

## Known Issues / Blockers
_None at this stage._

---

## Milestone 7.1 — UNSW-NB15 Data Integrity & Evaluation Verification

### Verified Results
1. **Row Count Discrepancy (2,540,047 vs 2,540,044)**:
   - File 1: 700,001 rows
   - File 2: 700,001 rows
   - File 3: 700,001 rows
   - File 4: 440,044 rows
   - Total raw physical rows: 2,540,047
   - Cause: Consecutive chunk files have an inclusive 1-row boundary overlap (last row of file $i$ == first row of file $i+1$).
   - Deduplicating the 3 boundary rows yields exactly **2,540,044 unique records**, matching published total.
2. **Global Chronological Ordering by Ltime**:
   - Monotonicity drops in flow end timestamp (`Ltime`): **0 across all 2,540,047 rows in sequence**.
   - Apparent overlap between `min(Stime)` and `max(Ltime)` resolved: $S_{\text{time}} = L_{\text{time}} - \text{dur}$. Flows with positive duration have $S_{\text{time}} < L_{\text{time}}$, creating the appearance of overlap when comparing start times to previous end times.
3. **Reconciled 49-Field Disjoint Partition**:
   - 19 forward-observable numeric features (10 causal + 9 batch aggregates)
   - 4 forward-observable metadata headers (`sport`, `dsport`, `proto`, `service`)
   - 13 reverse-direction prohibited metrics
   - 6 bidirectional/state-dependent prohibited metrics
   - 7 identifiers, timestamps, and evaluation labels
   - Total: exactly 49 fields ($19 + 4 + 13 + 6 + 7 = 49$).
   - Resolved prior report's "24 prohibited" count (which summed 13 reverse + 6 bidirectional + 5 identifiers/labels, omitting `Stime` and `Ltime`).
4. **Causal Observability Audit**:
   - Audited all 14 candidate features in `docs/unsw15_causal_observability.md`.
   - Proved lookahead in raw `ct_*` fields (Row 0 has `ct_srv_src = 3`, anticipating rows 27 and 37).
   - Provided `--causal-only` mode and integrated with `features/temporal.py` online streaming state tracker.
5. **Real-Data Evaluation Results**:
   - Smoke (10k flows): Precision=1.0, Recall=5.7%, FPR=N/A, ROC-AUC=0.8390.
   - Broad Causal (50k flows): Partitions Train=30,014, Cal=9,988, Test=9,998; Precision=0.3053, Recall=0.0498, FPR=0.0070, ROC-AUC=0.8518.
   - Broad Causal Multi-File (100k flows, Files 1 & 2): Partitions Train=60,015, Cal=20,043, Test=19,942; Precision=0.7351, Recall=0.0464, FPR=0.0070, ROC-AUC=0.9132, AP=0.7401.
   - Attack analysis: unsupervised thresholding flags volumetric anomalies (fuzzers 20.7% recall, exploits 2.9% recall) while low-rate reconnaissance and stealth attacks require behavioral sequence models.

### Test Results
```
pytest tests/ -q --no-cov
349 passed in 4.68s
Ruff: All checks passed!
Mypy: Success: no issues found in 53 source files
```

---

## Milestone 8 — Neural Autoencoder Anomaly Detector

### Architecture & Capabilities
- **Class**: `AutoencoderDetector(BaseDetector)` in `detection/autoencoder.py`.
- **Symmetric Architecture**: Configurable hidden layers (default `[32, 16]` $\to$ bottleneck $\to$ `[16, 32]`) with ReLU activations and linear reconstruction output.
- **Score Orientation**: Continuous anomaly score is sample-level reconstruction MSE:
  $$s(x) = \frac{1}{D} \sum_{j=1}^D (x_j - \hat{x}_j)^2$$
  Higher scores strictly indicate poorer reconstruction (greater anomalousness).
- **Dual Execution Backend**:
  - Native PyTorch (`torch.nn`, `Adam`, `DataLoader`) when `torch` is installed.
  - Fully vectorized pure-NumPy CPU reference engine (`_NumpyAEModel`) with He/Xavier initialization, mini-batch Adam optimization, and early stopping when PyTorch is unavailable.
  - Informative error when `backend='torch'` is requested on a system without PyTorch.
- **Zero Leakage**:
  - Rejects reverse-dependent columns and evaluation labels via `_validate_data()`.
  - Validation split for early stopping is derived strictly from training data.
  - Decision threshold calibrated on independent calibration partition scores.
- **Artifact Security**: Serialized with SHA-256 provenance manifest verification (`save_detector` / `load_detector`).

---

## Milestone 8.1 — Calibrated Multi-Detector Ensemble

### Architecture & Fusion Design
- **Class**: `CalibratedEnsembleDetector(BaseDetector)` in `detection/ensemble.py`.
- **Common Score Contract**: Integrates `RobustStatisticalDetector`, `IsolationForestDetector`, `LOFDetector`, and `AutoencoderDetector` under common orientation (higher = more anomalous).
- **Score Normalization**:
  - `EmpiricalPercentileNormalizer`: Maps test scores to $[0, 1]$ relative to the empirical cumulative distribution function (ECDF) fitted strictly on the unlabelled calibration partition.
  - Handles constant scores, ties, and non-finite values safely without division-by-zero.
  - Zero test leakage: test scores/labels are never used to fit normalizers.
- **Predeclared Fusion**: Combines normalized scores via fixed weights (default: equal weighting $w_i = 1/K$).
- **Label-Blind Calibration**: Decision threshold is derived via quantile cutoff (default 0.99) on the fused calibration scores.

### Empirical Multi-File Benchmark (100,000 Flows, UNSW-NB15 Files 1 & 2)
Partitions: Train=60,015 | Calibration=20,043 | Test=19,942. Causal-only features (13 forward fields), boundary deduplicated:

| Detector | Precision | Recall (TPR) | FPR | F1 Score | Balanced Acc | ROC-AUC | PR-AUC (AP) | Flagged |
|---|---|---|---|---|---|---|---|---|
| Robust Statistical | 0.2995 | 0.0111 | 0.0108 | 0.0214 | 0.5002 | 0.8912 | 0.6533 | 217 (1.09%) |
| Isolation Forest | **0.7351** | 0.0464 | **0.0070** | 0.0873 | 0.5197 | **0.9132** | **0.7401** | 370 (1.86%) |
| Autoencoder (M8) | 0.4341 | **0.1272** | 0.0689 | **0.1967** | 0.5291 | 0.8724 | 0.6350 | 1716 (8.61%) |
| **Calibrated Ensemble (M8.1)** | 0.5516 | 0.1086 | 0.0367 | 0.1814 | **0.5359** | 0.9043 | 0.6858 | 1153 (5.78%) |

**Key Empirical Insights**:
1. **Autoencoder detects subtle structural anomalies**: It achieves the highest recall (12.72%), finding 745 attacks missed by tree isolation, with higher false alarm rate (6.89%).
2. **Isolation Forest isolates volumetric outliers**: It delivers high precision (73.51%) on obvious anomalies but misses 95.36% of attacks.
3. **Ensemble achieves operational balance**: By fusing normalized percentile scores, the ensemble captures 10.86% recall (>2.3x Isolation Forest, ~10x Statistical Baseline) while reducing Autoencoder's false positive rate by almost half (3.67% vs 6.89%), yielding the highest overall Balanced Accuracy (0.5359).

---

## Milestone 14.1 — Real-Time Network Detection, Flow Reconstruction & Streaming SOC Alerts

### Architecture & Pipeline Overview
- **Class Hierarchy (`ingestion/capture/`)**:
  - `PacketEnvelope`: Zero-payload header envelope (timestamps, IPs, ports, protocol, payload length, flags, TTL).
  - `PcapReplaySource`: Paced PCAP streaming (1x, 2x, max speed), magic-byte validation, 500 MB size guard, thread-safe pause/resume/stop.
  - `LiveCaptureSource`: Promiscuous interface sniffer with `is_capture_driver_available()` guard checking `wpcap.dll` (Windows) / `libpcap.so` (Linux). Zero synthetic fake counter fallback.
- **Unidirectional Flow Reconstruction (`ingestion/flow/flow_builder.py`)**:
  - `UnidirectionalFlowBuilder`: Strict 5-tuple keying, stateful RFC 3550 exponential jitter calculation, Welford's algorithm for packet size std deviation, idle timeout (2.0s), max lifetime (60s), and 10,000 active flows LRU eviction.
  - Immediate flow termination on TCP FIN/RST flags.
- **Streaming Inference & Deduplication (`streaming/`)**:
  - `StreamingInferenceWorker`: Evaluates finalized flows using `ProductionInferenceService`, deduplicates identical 5-tuples within 10 seconds, persists anomalies to `SecurityAlert` table, and serves circular 200-event buffer.
  - `RealTimeDetectionManager`: Thread lifecycle supervisor managing single-instance capture, safe thread teardown, and mutual exclusion.
- **API & SOC Dashboard**:
  - `/api/v1/capture`: `/status`, `/interfaces`, `/sample-pcaps`, `/start-replay`, `/start-live`, `/pause`, `/resume`, `/stop`, `/upload-pcap`.
  - Frontend: `LiveDetectionPage.tsx` Bento grid with real-time counters, speed controls, sample picker, and streaming event table.

### Final Verification Metrics
- **Pytest Suite:** 457 passed (100%) in 19.82s.
- **Vitest Suite:** 22 passed (100%) in 1.25s.
- **Vite Production Build:** Success in 280ms.
- **Static Analysis:** Ruff 0 errors, Mypy 0 errors across 50 source files.
- **10 Formal Reports:** Authored in `reports/m14_realtime/`.

---

## Milestone 14.1 — Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit

### Key Forensic Findings
1. **Model Identity Established:**
   - Production detector artifact `artifacts/models/production_detector.joblib` is strictly **`xgboost.sklearn.XGBClassifier`** (`OptunaTuned_XGBoost` v1.0.0, 180 estimators, learning rate 0.03, max depth 5).
   - Checksums verified: Model `c43bb5...`, Preprocessor `effe96...`.
   - "Random Forest" references in M14 release summaries were documentation inheritance errata from M4 baseline prose and are formally superseded.
2. **Feature Semantic Equivalence:**
   - `fwd_bytes` represents cumulative IPv4 Total Length (`ip.len`), matching Argus `sbytes` in training data (excluding Ethernet framing).
   - `sload` represents bits per second with documented small-flow convergence bias.
   - All 13 features audited across single-packet, zero-duration, fragmented, and malformed traffic.
3. **Evidence Reconciliation:**
   - Test count verified: 457 backend tests passing (27.44s), 22 frontend tests passing (1.36s).
   - Drift sample size guard confirmed: programmatic threshold is $N < 30$ flows (`DEFAULT_MIN_SAMPLE_SIZE = 30`), emitting `INSUFFICIENT_DATA`.
   - 29-packet PCAP replay confirmed: 24 finalized flows, 100% evaluated by production detector.
   - Live capture status: `NOT RUN (DRIVER BLOCKED)` due to absent `wpcap.dll` on Windows host; zero synthetic simulation fallback.
4. **Audit Evidence Package:**
   - 7 formal reports in `reports/m14_1_forensic_audit/`.

---

_Last updated: Milestone 14.1 Forensic Audit Complete (Production Release Ready)_
