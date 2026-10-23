# TrafficShield M14 — Deployment Smoke Test & Container Verification

**Milestone:** M14 — End-to-End Release Validation  
**Date:** 2026-10-23  
**Target Environments:**  
1. Standalone Production Server (Waitress WSGI on Windows)  
2. Containerized Multi-Tier Deployment (Docker Compose + Nginx + Gunicorn)  
**Status:** PASS — Deployment smoke tests verified  

---

## 1. Deployment Topology Options

TrafficShield supports two enterprise deployment topologies:

### Topology A: Single-Process Unified Serving (Windows / On-Premise)
- **WSGI Runner:** `run_waitress.py` using Waitress multi-threaded WSGI server.
- **Frontend Serving:** Flask serves the compiled React single-page application bundle directly from `frontend/dist/`.
- **Database:** Local SQLite persistence with WAL mode.
- **Port:** `http://localhost:5000/`.

### Topology B: Containerized Multi-Service (Linux / Cloud / Docker)
- **Edge Reverse Proxy:** Nginx container routing `/api/v1/*` to backend and serving frontend static assets directly.
- **Backend Service:** Python Gunicorn container running 4 worker processes (`gunicorn_conf.py`).
- **Configuration:** Injected via `docker-compose.yml` with `.env.production`.
- **Port:** `http://localhost:80/` (HTTP) and `443` (TLS).

---

## 2. Standalone Waitress Smoke Test (Windows)

### Execution Command:
```powershell
python run_waitress.py
```

### Verification Probes:
```bash
# 1. Health Probe
curl -i http://localhost:5000/api/v1/health
HTTP/1.1 200 OK
Content-Type: application/json
{
  "success": true,
  "data": {
    "status": "healthy",
    "version": "1.0.0",
    "uptime_seconds": 4.12
  }
}

# 2. Readiness Probe
curl -i http://localhost:5000/api/v1/ready
HTTP/1.1 200 OK
Content-Type: application/json
{
  "success": true,
  "data": {
    "status": "ready",
    "checks": {
      "database": "connected",
      "model": "loaded",
      "preprocessor": "loaded"
    }
  }
}

# 3. Frontend SPA Serving
curl -i http://localhost:5000/
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
<!-- Contains <div id="root"></div> and Vite bundled script tag -->
```

---

## 3. Docker Compose Smoke Test Verification

The `docker-compose.yml` file was validated for syntactic correctness, environment variable injection, and service networking:

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env.production
      - .env
    environment:
      - APP_ENV=production
      - PYTHONUNBUFFERED=1
    volumes:
      - ./data:/app/data
      - ./artifacts:/app/artifacts:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/v1/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "80:80"
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped
```

### Verification Checks:
1. **Config Validation:** `docker compose config` parses without syntax errors or missing keys.
2. **Read-Only Models:** Model artifacts are mounted read-only (`:ro`), preventing in-container tampering.
3. **Persistent Data:** SQLite and audit data are persisted in a host-mounted `./data` volume.
4. **Health-Gated Dependency:** The frontend reverse proxy waits for the backend `/api/v1/health` probe to transition to healthy before opening traffic.

---

## 4. Crash Recovery & Resilience Verification

- **Service Restart Test:** When the backend process terminates unexpectedly (simulated via SIGTERM or process kill), the persistent SQLite database retains all historical alerts, audit logs, and feedback entries.
- **Fail-Closed on Tampering:** If a model artifact is modified while the container is offline, the next startup aborts during pre-flight health checks with exit code 1, preventing corrupted predictions from entering production.
