# TrafficShield M14 — Clean Install & Reproducibility Validation

**Milestone:** M14 — End-to-End Release Validation  
**Date:** 2026-10-23  
**Verified On:** Windows 11 64-bit / Python 3.14.8 / Node.js v22.12.0  
**Status:** PASS — 100% reproducible installation from scratch  

---

## 1. System Requirements & Prerequisites

| Subsystem | Requirement | Host Verified | Status |
|---|---|---|---|
| Operating System | Windows 10/11, Ubuntu 22.04 LTS, Debian 12 | Windows 11 Enterprise | **SUPPORTED** |
| Python Runtime | Python 3.10 to Python 3.14 | Python 3.14.8 64-bit | **VERIFIED** |
| Node.js Runtime | Node.js 18.x to 22.x with npm | Node.js v22.12.0 / npm 10.9.0 | **VERIFIED** |
| Build Tools | C++ build tools (optional, pre-built scikit-learn wheels used) | MSVC 19.x available | **VERIFIED** |
| Packet Sniffing | Npcap with WinPcap compatibility mode (for live sniffing) | Libpcap absent on host (PCAP replay verified) | **CONDITIONAL** |

---

## 2. Step-by-Step Clean Installation Procedure

### Step 1: Clone Repository
```bash
git clone https://github.com/Harsha1704/trafficshield.git
cd trafficshield
```

### Step 2: Python Virtual Environment Setup & Dependencies
```bash
# Create isolated virtual environment
python -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Upgrade pip and install core dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
```bash
# Copy template configuration
cp .env.example .env

# Generate a cryptographically secure secret key (minimum 32 characters)
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```
Ensure the following keys are set in `.env`:
```ini
APP_ENV=development
SECRET_KEY=a7d2e89f41b2c45e680193850239485720194857201938475029384750293847
DATABASE_URL=sqlite:///trafficshield.db
AUTH_ENABLED=true
ADMIN_PASSWORD=TrafficShieldAdmin2026!
ANALYST_PASSWORD=TrafficShieldAnalyst2026!
```

### Step 4: Frontend Installation & Bundle Build
```bash
cd frontend
npm install
npm run build
cd ..
```
The build completes in under 400ms and generates static assets in `frontend/dist/`:
- `frontend/dist/index.html` (~0.45 kB)
- `frontend/dist/assets/index-*.css` (~52 kB)
- `frontend/dist/assets/index-*.js` (~718 kB)

### Step 5: Database Schema & Default User Bootstrapping
When the backend starts, `app/__init__.py` automatically creates the SQLite tables and bootstraps default accounts if the database is unpopulated:
- **Admin:** `admin` / `TrafficShieldAdmin2026!`
- **Analyst:** `analyst` / `TrafficShieldAnalyst2026!`

---

## 3. Verification Test Run

Execute the automated test gates to confirm environment sanity:
```bash
# 1. Run Python test suite (444 tests)
python -m pytest

# 2. Run Frontend test suite (22 tests)
cd frontend
npm test -- --run
cd ..

# 3. Check code style and static typing
python -m ruff check app monitoring config tests ingestion
python -m mypy app monitoring config ingestion
```

**Verification Results:**
- Pytest: **444 passed in 19.08s**
- Vitest: **22 passed in 1.23s**
- Ruff: **All checks passed (0 warnings)**
- Mypy: **Success (0 issues in 40 source files)**

---

## 4. Launching the Integrated Application

### Development Mode (with hot-reload):
```bash
# Terminal 1: Backend API
python -m flask --app app:create_app run --port 5000

# Terminal 2: Frontend Vite Dev Server
cd frontend
npm run dev -- --port 5173
```

### Single-Process Production Serving:
```bash
# Production server (Waitress on Windows, Gunicorn on Linux)
# Windows:
python run_waitress.py

# Linux:
gunicorn -c gunicorn_conf.py "app:create_app('production')"
```
In single-process mode, Flask serves both the REST API on `/api/v1/*` and the compiled React dashboard directly on `http://localhost:5000/`.
