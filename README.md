# TrafficShield

**Unidirectional IP Traffic Anomaly Detection Platform**

> Critical-infrastructure monitoring links only see traffic flowing one way, so anomaly detection must work without being able to query back or rely on labelled attack traffic.

TrafficShield is a production-oriented network anomaly detection system that learns normal traffic behaviour from unlabeled or predominantly-benign flow data, then identifies unusual activity without requiring attack labels during training.

---

## Project Status

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1 | Flask app factory, config, health API, tests | ✅ Complete |
| M2 | UGR'16 adapter, canonical schema | ⬜ In progress |
| M3 | Feature eligibility, preprocessing, leakage checks | ⬜ Planned |
| M4 | Statistical baseline + Isolation Forest | ⬜ Planned |
| M5 | Evaluation framework | ⬜ Planned |
| M6 | Temporal features, LOF, HDBSCAN | ⬜ Planned |
| M7 | Autoencoder, ensemble | ⬜ Planned |
| M8 | Explainability | ⬜ Planned |
| M9 | PostgreSQL, incidents, risk scoring | ⬜ Planned |
| M10 | React SOC dashboard | ⬜ Planned |
| M11 | Cross-dataset eval, drift monitoring | ⬜ Planned |
| M12 | Auth, Docker, observability | ⬜ Planned |

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

## License

MIT — see `LICENSE`.
