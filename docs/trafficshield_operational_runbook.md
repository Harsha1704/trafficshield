# TrafficShield — Authoritative Operational Runbook
**Production Deployment, Startup Lifecycle, Runtime Verification & Operator Procedures**

**Project:** TrafficShield — Hybrid Intrusion Detection System (Hybrid IDS)  
**Repository:** `D:\projects\trafficshield`  
**Target Platform:** Windows 10 / 11 / Windows Server (or Linux)  
**Release Baseline:** v1.1.0-RC (Hybrid Dual-Detector Architecture)  
**Governing Document:** `reports/phase4_hybrid_release_dossier.md`  
**Execution Context:** Phase 4 Remediation — Work Package WP3 & WP4  
**Date:** 2026-11-05  

---

## 1. Operational Overview & Architecture Context

TrafficShield is an enterprise-grade hybrid intrusion detection system designed for unidirectional data diode environments. The application is deployed as a single-process, multi-threaded production service using the **Waitress WSGI server** with built-in startup preflight verification, cryptographic artifact checks, fail-fast inference error handling, and graceful shutdown signal management.

### Key Operational Invariants
- **Deployment Target Hierarchy**:
  1. *Local Windows Production-Mode Baseline (VERIFIED):* Executed via `python wsgi.py` with multi-threaded Waitress (4 worker threads). This is the active, verified production runtime in this repository.
  2. *Containerized Linux Baseline (INFRASTRUCTURE-AS-CODE SPECIFICATION):* Defined via `Dockerfile` and `docker-compose.yml`. Note that Docker is not installed on the current host; containerized execution is an IaC definition, not a live verified deployment.
  3. *Proposed Linux Systemd On-Premises Target (OPERATIONAL SPECIFICATION):* Documented in Section 6 specifying systemd service units (`trafficshield-web.service`, `trafficshield-capture.service`) and `CAP_NET_RAW`. Not applicable on local Windows host.
  4. *Cloud Staging Target (DOCUMENTED / EXTERNAL):* Documented in historical guides; remote hosting infrastructure, DNS, and uptime are unverified without external network probes.
- **Canonical Production Launcher**: **`python wsgi.py`** is the **only supported local production launcher**.
  > [!CAUTION]
  > Executing the `waitress-serve` CLI directly (e.g., `waitress-serve --port=5000 app:create_app`) is **strictly prohibited**. The raw CLI bypasses `app/lifecycle.py` preflight verification, skips database connectivity validation, and fails to register `SIGINT`/`SIGTERM` graceful shutdown hooks.
  > Running `python run.py` is reserved exclusively for local development; it launches the Flask development server with active debuggers, which must never be exposed in production.
- **Concurrency & Process Architecture**: TrafficShield is architected for **single-process multi-threading** (4 Waitress worker threads). Live capture managers maintain process-local state; running multiple forked processes (e.g. multi-worker Gunicorn) is not supported for live capture.
- **Fail-Closed Inference Contract**: Uninitialized or missing models trigger immediate HTTP `503 Service Unavailable` (`INFERENCE_ENGINE_UNAVAILABLE`). Benign default scores (`0.0`) are never emitted under failure conditions.

---

## 2. Production Environment Configuration

The production runtime is configured via environment variables or a secure `.env` file in the project root:

### Mandatory Production Settings (`.env`)

```ini
# Environment Mode
FLASK_ENV=production

# Cryptographic Secret Key (Must be at least 32 characters in production)
SECRET_KEY=MN1drZdzZ663UgOC3wjw913nLMyKJi3faEQgIgK0IMM

# Relational Database URL (Production must use PostgreSQL, never SQLite)
DATABASE_URL=postgresql+psycopg://trafficshield_user:MN1drZdzZ663UgOC3wjw913nLMyKJi3faEQgIgK0IMM@localhost:5432/trafficshield_prod

# Database Migration Setting (0 during normal serving, 1 during alembic migration runs)
ALEMBIC_MIGRATION_RUN=0

# Server Binding
SERVER_HOST=127.0.0.1
SERVER_PORT=5000
SERVER_THREADS=4

# Logging Format and Level
LOG_LEVEL=INFO
LOG_FORMAT=json

# CORS Whitelist (Comma-separated, no wildcards allowed in production)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,http://localhost:5000,http://127.0.0.1:5000

# Initial Bootstrap Credentials (Optional in prod; only seeds if database accounts are missing)
ADMIN_INITIAL_USERNAME=admin
ADMIN_INITIAL_PASSWORD=
ANALYST_INITIAL_USERNAME=analyst
ANALYST_INITIAL_PASSWORD=
```

---

## 3. Pre-Startup Verification Checklist

Before starting the service, operators must verify local system prerequisites:

### Step 1: Verify Python Runtime & Virtual Environment
```powershell
python --version
# Expected: Python 3.12+ (Tested on Python 3.14.8)
```

### Step 2: Verify Cryptographic Artifact Integrity
Verify that all 5 production artifacts match their authoritative SHA-256 digests:

```powershell
python -c "
import hashlib
from pathlib import Path
files = {
    'artifacts/models/production_detector.joblib': 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
    'artifacts/models/production_detector.json': '3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1',
    'artifacts/models/production_iforest.joblib': 'd9fe41016c51f8484b57c80bb2f0ec41186c66add9bae71f822d0a85c13a350e',
    'artifacts/models/production_iforest.json': '5daf8b0dab1c4c3a66e4cb2c38b10c406f6c1861572d27a08155c8541bf4cb94',
    'artifacts/models/production_preprocessor.joblib': 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
}
for p, exp in files.items():
    act = hashlib.sha256(Path(p).read_bytes()).hexdigest()
    assert act == exp, f'HASH MISMATCH on {p}'
print('All 5 artifacts verified bit-for-bit.')
"
```

### Step 3: Verify PostgreSQL Production Service
Ensure PostgreSQL service is running and accessible:
```powershell
Get-Service postgresql*
```

---

## 4. Starting the Production Application

### Canonical Startup Command
Execute the production launcher from the repository root:

```powershell
cd D:\projects\trafficshield
python wsgi.py
```

### Startup Preflight Behavior (`app/lifecycle.py`)
Upon executing `python wsgi.py`, the following sequence executes automatically prior to opening the TCP port:
1. **Configuration Preflight**: Validates Pydantic v2 settings (checks `SECRET_KEY` length $\ge 32$, validates that `FLASK_DEBUG` is false, and confirms database is not SQLite).
2. **Database Connectivity Preflight**: Tests connection pool and executes `SELECT 1` on PostgreSQL.
3. **Model & Manifest Preflight**: Loads `production_detector.joblib`, validates 13-feature input vector, and confirms decision threshold is `0.50`.
4. **Isolation Forest Verification**: Checks `production_iforest.joblib` and confirms threshold `0.7278956397776036`.
   - *Optional Isolation Forest Behavior*: If the Isolation Forest file is intentionally omitted, the server logs a warning and proceeds in degraded supervised-only mode. If present but tampered or corrupted, startup aborts immediately.
5. **Waitress Serving Initialization**: Binds to `127.0.0.1:5000` with 4 worker threads.

### Expected Console Output
```
19:30:00 [INFO] app - TrafficShield starting
19:30:01 [INFO] auth - Bootstrapped default dev users if missing: 'admin' and 'analyst'
19:30:01 [INFO] app - TrafficShield ready
19:30:01 [INFO] waitress - Serving on http://127.0.0.1:5000
```

---

## 5. Post-Startup Operational Health Probes

Verify service responsiveness using standard HTTP probes:

### 1. Health Diagnostic Probe
```bash
curl -i http://127.0.0.1:5000/api/v1/health
```
**Expected Response (`200 OK`)**:
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "version": "1.0.0",
    "database": "connected",
    "model_loaded": true,
    "iforest_loaded": true
  }
}
```

### 2. Authentication & Login Verification
Authenticate an analyst session:
```bash
curl -i -X POST http://127.0.0.1:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "analyst", "password": "AnalystPass123!"}'
```
**Expected Response (`200 OK`)**:
```json
{
  "success": true,
  "data": {
    "token": "<SIGNED_BEARER_TOKEN>",
    "user": {"username": "analyst", "role": "analyst"}
  }
}
```

### 3. Inference Pipeline Verification Probe
Send a sample 13-feature flow vector:
```bash
curl -i -X POST http://127.0.0.1:5000/api/v1/predict \
  -H "Authorization: Bearer <SIGNED_BEARER_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "duration_seconds": 0.05,
    "fwd_bytes": 1200,
    "sttl": 64,
    "sload": 192000.0,
    "fwd_packets": 10,
    "swin": 255,
    "smeansz": 120.0,
    "sjit": 2.5,
    "sintpkt": 5.5,
    "packet_rate": 200.0,
    "byte_rate": 24000.0,
    "bytes_per_packet": 120.0,
    "is_sm_ips_ports": 0
  }'
```
**Expected Response (`200 OK`)**:
```json
{
  "success": true,
  "data": {
    "anomaly_score": 0.0412,
    "is_anomaly": false,
    "decision_tier": "NORMAL_TRAFFIC",
    "confidence": 0.9588
  }
}
```

---

## 6. Telemetry & Retention Management Procedures

### Monitoring Telemetry Invariants
- Feature drift calculations (PSI) require $\ge 500$ flows per batch. If fewer flows exist, the drift engine returns `INSUFFICIENT_DATA` rather than generating false alerts.
- Operational alerts are debounced within configured time windows to prevent alert fatigue.

### Executing Database Retention Pruning
To prevent disk exhaustion from historical flow telemetry and operational metrics, execute the retention CLI:

```powershell
# 1. Execute Dry-Run First (Safe Inspection)
flask retention prune --days 30 --dry-run

# 2. Execute Real Pruning (Cleanses historical records older than 30 days)
flask retention prune --days 30
```
*Safety Note*: Retention pruning strictly targets expired flow records and transient metrics; it **never deletes security alerts** (`SecurityAlert` table).

---

## 7. Graceful Shutdown & Process Termination

To terminate the production server safely:

### Standard Graceful Shutdown
Send `SIGINT` (Ctrl+C in terminal) or `SIGTERM` to the python process:
1. Signal handler traps the interrupt.
2. Ingestion worker transitions to `DRAINING` state.
3. In-flight flow queues drain for up to 5 seconds.
4. Active database connection pool is disposed cleanly (`db.engine.dispose()`).
5. Waitress listener socket closes.

> [!WARNING]
> **Hard Termination Risk**: Abrupt termination via `taskkill /F /PID <pid>` or power loss bypasses the drain handler. Any packets currently buffered in capture queues before persistence will be lost.

---

## 8. Troubleshooting & Common Operational Errors

### Issue 1: CORS Error / `net::ERR_FAILED` in Browser Console
- **Symptom**: Browser console displays `Response to preflight request doesn't pass access control check: No Access-Control-Allow-Origin header`.
- **Cause**: User accessed the frontend on `http://127.0.0.1:5000` while the frontend is configured to call `http://localhost:5000/api/v1`. On Windows, `localhost` resolves to IPv6 `::1`, but Flask is bound to IPv4 `127.0.0.1`.
- **Resolution**:
  - *Option A*: Access dashboard via `http://localhost:5000`.
  - *Option B*: Open browser DevTools console and execute:
    ```javascript
    localStorage.setItem('trafficshield_api_url', 'http://127.0.0.1:5000/api/v1');
    location.reload();
    ```

### Issue 2: Startup Aborts with `RuntimeError: Production database must not use SQLite`
- **Symptom**: `python wsgi.py` fails with validation error during preflight.
- **Cause**: `DATABASE_URL` in `.env` is set to an `sqlite:///` path while `FLASK_ENV=production`.
- **Resolution**: Set `DATABASE_URL` to a valid PostgreSQL URI (`postgresql+psycopg://...`).

### Issue 3: HTTP 503 `INFERENCE_ENGINE_UNAVAILABLE`
- **Symptom**: API returns status 503 on `/api/v1/predict`.
- **Cause**: Model file missing or corrupted during runtime.
- **Resolution**: Check `artifacts/models/` and verify all 5 SHA-256 hashes match Section 3 Step 2.

---
*Authoritative Operational Runbook established under Phase 4 Remediation WP3.*
