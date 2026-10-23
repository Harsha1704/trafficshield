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
| M10 | PostgreSQL incident store, SOC alert correlation | ⬜ Planned |
| M11 | React SOC dashboard & real-time monitoring UI | ⬜ Planned |
| M12 | Auth, Docker, production observability | ⬜ Planned |

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

## License

MIT — see `LICENSE`.
