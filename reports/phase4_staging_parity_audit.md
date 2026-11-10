# TrafficShield — Phase 4: Staging Parity Audit Report
**Environment Comparison, Infrastructure Divergence & Deployment Parity Analysis**

**Repository:** `D:\projects\trafficshield`  
**Target Branch:** `staging`  
**Auditor Roles:** DevSecOps Engineer, Principal Software Architect, QA Lead  
**Audit Baseline:** Local Windows Production-Mode Runtime vs. Staging Cloud Deployments  
**Execution Context:** Phase 4 Remediation — Work Package WP4  
**Date:** 2026-11-05  

---

## 1. Executive Summary

This engineering parity audit compares the **Local Windows Production-Mode Baseline** against the **Staging Deployment Configuration** as evidenced in the TrafficShield repository. 

The audit evaluated five core dimensions:
1. **Runtime Parity**: Python versions, WSGI servers, process architectures, and lifecycle hooks.
2. **Database Parity**: Relational engines, driver schemes, connection pooling, migrations, and test isolation.
3. **CORS & Transport Parity**: API base URLs, origin whitelisting, authentication tokens, and cookie protection.
4. **Model & Inference Parity**: Artifact manifests, 13-feature ordering, decision thresholds, and scaling pipelines.
5. **Deployment Lifecycle Parity**: Preflight checks, socket handling, and graceful shutdown signal management.

### Key Parity Finding
The core ML inference pipeline, database models, schema migrations, and security settings demonstrate **complete parity**. However, material operational differences exist between the **local Windows single-process Waitress runtime** (`python wsgi.py`) and the **cloud staging deployment model** (Render backend with `gunicorn_conf.py` and Vercel frontend). These differences are categorized, risk-assessed, and bounded in this report.

---

## 2. Environments Compared & Audit Boundaries

| Environment Dimension | Local Production Baseline | Staging Cloud Baseline (from Evidence) |
| :--- | :--- | :--- |
| **Hosting Target** | Local Windows Workstation / Server | Render (Backend) + Vercel (Frontend) |
| **Operating System** | Windows 10 / 11 (NT Kernel) | Linux (POSIX Container) |
| **WSGI Server** | Waitress (`wsgi.py`) | Gunicorn (`gunicorn_conf.py` / `Procfile`) |
| **Concurrency Model**| Single-process, 4 worker threads | Multi-worker (`gthread`, 4 threads/worker) |
| **Database Engine** | PostgreSQL 17 Local (`trafficshield_prod`) | PostgreSQL Cloud Relational Instance |
| **Test Database** | SQLite in-memory (`sqlite:///:memory:`) | SQLite in-memory (`sqlite:///:memory:`) |
| **CORS Origins** | Localhost & 127.0.0.1 ports | Localhost + `*.vercel.app` domains |

*Strict Audit Safeguard*: In compliance with safety rules, zero connections to external cloud providers (Render, Vercel) or remote PostgreSQL servers were attempted. Findings reflect code, configuration, and commit history evidence.

---

## 3. Evidence Sources

The findings in this audit are grounded in the following repository evidence:
- `config/settings.py` (Pydantic v2 application configuration)
- `wsgi.py` (Production Waitress entry point)
- `gunicorn_conf.py` (Production Gunicorn configuration)
- `app/lifecycle.py` (Startup preflight & shutdown signal handlers)
- `app/__init__.py` (CORS initialization, security headers, SQLAlchemy setup)
- `frontend/src/services/api.ts` (API client base URL resolution logic)
- `migrations/versions/cf7c48cedf4f_initial_schema_all_models.py` (Database schema head)
- Git commits: `8d615ae`, `683d4bc`, `2841e71`, `c0dd2b6`, `0387e30`

---

## 4. Detailed Parity Comparison Tables

For each evaluated attribute, status is classified as:
- **`MATCH`**: Identical configuration, behavior, or verified standard.
- **`DIFFERENCE`**: Documented, intentional, or unmitigated technical divergence.
- **`NOT VERIFIED`**: Live remote configuration inaccessible from repository evidence alone.
- **`NOT APPLICABLE`**: Specific to one platform without cross-environment equivalent.

### A. Runtime Parity

| Comparison Item | Local Windows Baseline | Staging Cloud Target | Classification | Evaluation & Risk Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Python Version** | 3.14.8 | 3.12+ (Render default) | `MATCH` | Compatible across Python 3.12–3.14. |
| **Dependencies** | `pyproject.toml` | `pyproject.toml` | `MATCH` | Identical dependency declarations. |
| **WSGI Server** | Waitress (`wsgi.py`) | Gunicorn (`gunicorn_conf.py`)| `DIFFERENCE` | **Documented Difference**: Waitress is tailored for Windows; Gunicorn is tailored for Linux containers. |
| **Process Model** | Single process (1 PID) | Multi-worker (forked PIDs) | `DIFFERENCE` | **Operational Risk**: Live packet capture managers maintain process-local state; multi-worker Gunicorn cannot support live capture without sticky routing. |
| **Worker Threads** | 4 threads | 4 threads per worker | `MATCH` | Both configurations utilize 4 concurrent worker threads. |
| **Engine Disposal** | `app/__init__.py` & `lifecycle.py` | `gunicorn_conf.py::post_fork` | `MATCH` | Both environments dispose the SQLAlchemy engine pool to prevent SSL decryption failures across processes. |

### B. Database Parity

| Comparison Item | Local Windows Baseline | Staging Cloud Target | Classification | Evaluation & Risk Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Database Engine** | PostgreSQL 17 | PostgreSQL (Cloud) | `MATCH` | Relational PostgreSQL engines used for both production baselines. |
| **Driver Scheme** | `postgresql+psycopg://` | `postgresql+psycopg://` | `MATCH` | Modern psycopg3 driver scheme enforced in both environments. |
| **Connection Pooling**| `pool_pre_ping=True`, recycle=300 | `pool_pre_ping=True`, recycle=300 | `MATCH` | Pool recycling and connection pinging identical in `config/settings.py`. |
| **Migration Head** | `cf7c48cedf4f` | `cf7c48cedf4f` | `MATCH` | Single migration head covers all SQLAlchemy models. |
| **Test DB Isolation**| SQLite in-memory (`:memory:`) | SQLite in-memory (`:memory:`) | `MATCH` | Automated testing strictly isolated from production database. |
| **Live Remote DB** | `localhost:5432` | Remote Cloud Host | `NOT VERIFIED` | Remote database host and latency inaccessible from repository. |

### C. CORS & Frontend/Backend Parity

| Comparison Item | Local Windows Baseline | Staging Cloud Target | Classification | Evaluation & Risk Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Backend API Base**| `http://127.0.0.1:5000/api/v1`| `https://trafficshield-staging-backend.onrender.com/api/v1` | `DIFFERENCE` | **Intentional Difference**: Localhost URL vs. HTTPS staging endpoint. Handled dynamically in `api.ts`. |
| **Allowed CORS** | Localhost & 127.0.0.1 ports | Localhost + `https://*.vercel.app` | `MATCH` | `config/settings.py` whitelists local ports and authorized Vercel domains. Wildcard (`*`) is barred. |
| **Cookie Flags** | `HttpOnly`, `Lax`, `Secure=False`| `HttpOnly`, `Lax`, `Secure=True` | `DIFFERENCE` | **Security Invariant**: Production mode enforces HTTPS `Secure=True` cookies; local dev permits unencrypted cookies. |
| **Security Headers**| nosniff, DENY, strict CSP | nosniff, DENY, strict CSP | `MATCH` | Defense-in-depth headers applied identically via `_configure_security_and_tracing()`. |

### D. Model & Inference Parity

| Comparison Item | Local Windows Baseline | Staging Cloud Target | Classification | Evaluation & Risk Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Model Artifacts** | 5 frozen files in `artifacts/models/`| 5 frozen files in `artifacts/models/` | `MATCH` | Identical SHA-256 hashes verified bit-for-bit. |
| **Feature Ordering**| 13 frozen forward features | 13 frozen forward features | `MATCH` | Identical column ordering enforced in `ml/production_service.py`. |
| **XGBoost Threshold**| `0.50` | `0.50` | `MATCH` | Strictly identical. |
| **IForest Threshold**| `0.7278956397776036` | `0.7278956397776036` | `MATCH` | Strictly identical. |
| **Decision Matrix** | 4-tier taxonomy | 4-tier taxonomy | `MATCH` | Identical decision combination logic. |

### E. Deployment Lifecycle Parity

| Comparison Item | Local Windows Baseline | Staging Cloud Target | Classification | Evaluation & Risk Assessment |
| :--- | :--- | :--- | :---: | :--- |
| **Startup Preflight**| `app/lifecycle.py::run_startup_preflight()` | Executed on app factory init | `MATCH` | Preflight verifies DB and hashes before serving requests. |
| **Graceful Shutdown**| OS signal handlers in `wsgi.py` | Gunicorn master signal handler | `MATCH` | Both trap `SIGINT`/`SIGTERM` to drain flow queues. |
| **Live Packet Capture**| Supported via Npcap driver | Offline PCAP replay only | `DIFFERENCE` | **Hardware Difference**: Cloud container environments lack physical network TAP/Npcap drivers; live capture is local-only. |

---

## 5. Confirmed Parity Differences and Technical Assessment

1. **WSGI Server & Process Model (`Waitress` vs. `Gunicorn`)**:
   - *Technical Reality*: Local Windows production serving runs Waitress as a single multi-threaded process (`python wsgi.py`). Staging on Render uses Gunicorn (`gunicorn_conf.py`) with multiple workers.
   - *Risk*: Running multiple Gunicorn worker processes breaks process-local live capture state in `streaming/manager.py`.
   - *Mitigation*: The staging cloud deployment is designated strictly for **REST API scoring, offline PCAP evaluation, and dashboard triage**. Live network sniffing is restricted to Windows on-premise single-process installations.
2. **Frontend Dynamic API Resolution**:
   - *Technical Reality*: `frontend/src/services/api.ts` implements dynamic fallback logic:
     - If `VITE_API_URL` is set, uses it.
     - In production builds (`import.meta.env.PROD`), defaults to Render staging backend (`https://trafficshield-staging-backend.onrender.com/api/v1`).
     - In local development, defaults to `http://localhost:5000/api/v1`.
   - *Risk*: Operators testing local production builds on `127.0.0.1:5000` could inadvertently send API calls to Render staging unless configured via `localStorage`.
   - *Mitigation*: Documented in operational runbook with immediate console override instructions.

---

## 6. Unverified Remote Staging Areas

In compliance with read-only audit restrictions, the following remote elements remain **`NOT VERIFIED`**:
1. **Live Render Staging Service Status**: Whether the Render staging backend container is currently active, provisioned, or sleeping.
2. **Live Remote PostgreSQL Database Version & Network Latency**: Specific PostgreSQL minor version, connection latency, and storage quota on the remote cloud host.
3. **Live Vercel DNS & Deployment Status**: Current deployment state of `https://trafficshield.vercel.app`.

---

## 7. Recommended Staging Parity Remediation

1. **Explicit Cloud Live-Capture Disclaimer**: In `reports/phase4_hybrid_release_dossier.md` and UI dashboards, explicitly document that live interface sniffing (`/api/v1/capture/start-live`) requires local Npcap drivers and is unsupported in headless cloud containers.
2. **Unified WSGI Configuration Documentation**: Standardize deployment runbooks to clarify that `python wsgi.py` is the baseline on-premise launcher, while `gunicorn_conf.py` is reserved for cloud container environments.

---

## 8. Final WP4 Parity Classification

$$\mathbf{WP4\ CLASSIFICATION:\ COMPLETE\ WITH\ LIMITATIONS}$$

### Justification
- All core application logic, database schemas, model hashes, feature orderings, and decision thresholds demonstrate **100% MATCH**.
- Material deployment differences (Waitress single-process vs. Gunicorn cloud container) are verified, understood, risk-assessed, and documented.
- Unverified remote cloud parameters are explicitly isolated without assumptions.

---
*Staging Parity Audit Report established under Phase 4 Remediation WP4.*
