# TrafficShield — Production Deployment & Operations Guide

**Milestone:** M13 (Production Deployment, Security Hardening & Release Readiness)  
**Date:** 2026-10-23  
**Status:** Approved & Verified

---

## 1. Overview & Supported Topologies

TrafficShield supports three enterprise deployment models:
1. **Containerized Production (Recommended):** Multi-stage Docker container deployed alongside PostgreSQL and Nginx via Docker Compose or Kubernetes.
2. **Linux Host Deployment:** Gunicorn WSGI application managed by `systemd`, reverse-proxied by Nginx with TLS termination.
3. **Windows Host Deployment:** Multi-threaded Waitress WSGI server (`run_waitress.py`) running as a Windows Service or standalone process for Windows-based SOC networks.

---

## 2. Containerized Deployment (Docker Compose)

### 2.1. Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.20+
- Network access to pull base images (`node:22-alpine`, `python:3.12-slim`, `postgres:16-alpine`, `nginx:1.27-alpine`)

### 2.2. Configuration & Secret Injection
1. Create a secure production environment file from the template:
   ```bash
   cp .env.example .env.production
   ```
2. Generate a cryptographically strong secret key (minimum 32 characters):
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Set production parameters in `.env.production`:
   ```bash
   FLASK_ENV=production
   APP_ENV=production
   FLASK_DEBUG=0
   SECRET_KEY=e83a991f8c12a7db6854bf409549320e83a991f8c12a7db6854bf409549320e1
   POSTGRES_PASSWORD=YourStrongDatabasePassword123!
   ADMIN_INITIAL_USERNAME=soc_admin
   ADMIN_INITIAL_PASSWORD=YourStrongInitialAdminPassword123!
   ANALYST_INITIAL_USERNAME=soc_analyst
   ANALYST_INITIAL_PASSWORD=YourStrongInitialAnalystPassword123!
   CORS_ORIGINS=https://soc.trafficshield.internal
   ```

### 2.3. Build & Launch
Build the multi-stage image and start the full production stack:
```bash
docker compose --env-file .env.production up -d --build
```

### 2.4. Verify Deployment Health
Verify container healthchecks and probe endpoints:
```bash
# Check container status
docker compose ps

# Liveness probe (HTTP 200 OK)
curl -i http://localhost:5000/api/v1/health

# Readiness probe (HTTP 200 OK with DB & monitoring checks)
curl -i http://localhost:5000/api/v1/ready
```

---

## 3. Linux Host Deployment (Gunicorn + Systemd + Nginx)

### 3.1. Systemd Service Unit (`/etc/systemd/system/trafficshield.service`)
```ini
[Unit]
Description=TrafficShield Unidirectional Anomaly Detection Service
After=network.target postgresql.service

[Service]
Type=notify
User=trafficshield
Group=trafficshield
WorkingDirectory=/opt/trafficshield
Environment="PATH=/opt/trafficshield/venv/bin"
EnvironmentFile=/etc/trafficshield/production.env
ExecStart=/opt/trafficshield/venv/bin/gunicorn -c gunicorn_conf.py run:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=30
PrivateTmp=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3.2. Launching Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable trafficshield
sudo systemctl start trafficshield
sudo systemctl status trafficshield
```

---

## 4. Windows Host Deployment (Waitress WSGI)

For Windows-based enterprise monitoring stations where Docker or Linux hosts are unavailable:

### 4.1. Prerequisites
- Python 3.12+ (or 3.14 compatible)
- Waitress installed (`pip install waitress`)

### 4.2. Running the Production Server
```powershell
# Set production environment variables in session or system
$env:FLASK_ENV="development" # or production with PostgreSQL configured
$env:PORT="5000"
$env:WAITRESS_THREADS="8"

# Launch Waitress WSGI server
python run_waitress.py --host 0.0.0.0 --port 5000 --threads 8
```

---

## 5. Environment Variables Reference

| Variable | Type | Required in Prod? | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `FLASK_ENV` | string | **Yes** | `development` | Runtime environment: `development`, `testing`, `production`. |
| `APP_ENV` | string | Optional | `development` | Secondary environment flag; mirrors `FLASK_ENV`. |
| `SECRET_KEY` | string | **Yes** | None | Cryptographic secret for session signing (minimum 32 characters in prod). |
| `DATABASE_URL` | string | **Yes** | `sqlite:///...` | Database connection URI. Must be PostgreSQL in production. |
| `AUTH_ENABLED` | int/bool | Optional | `1` | Enforces authentication on all non-probe endpoints. |
| `AUTH_TOKEN_EXPIRY_HOURS` | int | Optional | `8` | Expiration lifetime for session tokens and cookies. |
| `ADMIN_INITIAL_USERNAME` | string | Optional | `admin` | Initial administrator username for empty database bootstrap. |
| `ADMIN_INITIAL_PASSWORD` | string | Optional | None | Initial administrator password (must be >= 12 chars). |
| `CORS_ORIGINS` | string | **Yes** | `localhost...` | Comma-separated list of allowed web origins. No `*` allowed in prod. |
| `SESSION_COOKIE_SECURE` | bool/int| Optional | `1` in prod | Enforces `Secure` flag on cookies (requires HTTPS). |
| `MONITORING_STALE_HOURS` | int | Optional | `24` | Threshold in hours before inactive telemetry flags degraded health. |

---

## 6. Health & Readiness Probes

### 6.1. Liveness Probe (`GET /api/v1/health`)
- **Purpose:** Used by container runtimes (Kubernetes/Docker) to verify process responsiveness.
- **Behavior:** Returns `HTTP 200 OK` instantly without querying external dependencies.
- **Example Response:**
  ```json
  {
    "data": {
      "service": "TrafficShield",
      "status": "ok",
      "uptime_seconds": 128.45,
      "version": "1.0.0"
    },
    "status": "success"
  }
  ```

### 6.2. Readiness Probe (`GET /api/v1/ready`)
- **Purpose:** Used by load balancers and reverse proxies before routing live traffic.
- **Behavior:** Executes `SELECT 1` on database and checks monitoring telemetry freshness. Returns `HTTP 200` if healthy, `HTTP 503` if degraded. Error details are strictly sanitized to prevent credential/path disclosure.
- **Example Response:**
  ```json
  {
    "data": {
      "checks": {
        "database": {"status": "ok"},
        "monitoring": {"fresh": true, "status": "ok"}
      },
      "status": "ok"
    },
    "status": "success"
  }
  ```

---

## 7. Graceful Shutdown & Rollback Procedures

### 7.1. Graceful Shutdown
Gunicorn and Waitress gracefully finish inflight requests before shutting down:
```bash
# Graceful reload (zero downtime)
kill -HUP <GUNICORN_MASTER_PID>

# Graceful termination (allows 30s for inflight predictions to complete)
kill -TERM <GUNICORN_MASTER_PID>
```

### 7.2. Release Rollback Checklist
If an issue arises after deploying a new release:
1. Revert container tag in `docker-compose.yml` to prior stable release (e.g. `v0.12.0`).
2. If database schema was upgraded, execute rollback migration:
   ```bash
   flask db downgrade -1
   ```
3. Restart containers:
   ```bash
   docker compose up -d --no-deps web
   ```
4. Verify checksum of frozen model artifacts (`c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`).
5. Confirm green status on `/api/v1/ready`.
