# TrafficShield — Windows Quick Start & Evaluator Setup Guide

**Document ID:** TS-DOC-QUICKSTART-WIN  
**Target Milestone:** M16 Demo Readiness  
**Platform:** Windows 10 / 11 (PowerShell 7+ or Windows PowerShell 5.1)  
**Classification:** Evaluator Documentation  

---

## 1. System Prerequisites

Before starting, verify the host system meets these requirements:

| Component | Minimum Version | Tested Baseline | Verification Command |
|:---|:---|:---|:---|
| **Operating System** | Windows 10 64-bit | Windows 11 AMD64 | `[System.Environment]::OSVersion.Version` |
| **Python** | 3.12+ | Python 3.14.8 | `python --version` |
| **Node.js & npm** | Node 18+ / npm 9+ | Node 20+ / npm 10+ | `node --version; npm --version` |
| **Packet Capture Driver** | Optional for Replay, required for Live Capture | Npcap 1.80+ (WinPcap API compatible) | `Test-Path "$env:SystemRoot\System32\Npcap\wpcap.dll"` |

> [!NOTE]
> Packet capture driver (Npcap) is **only required for live wire sniffing**. The evaluator demonstration uses the built-in synthetic PCAP replay engine, which runs 100% out-of-the-box on standard Python without Npcap or administrative privileges.

---

## 2. Repository Navigation & Environment Setup

Open **Windows PowerShell** as a regular user (administrative privileges are not required for replay demonstration):

```powershell
# Navigate to the repository directory
cd D:\projects\trafficshield

# Verify Git working branch and latest commit
git status
git log -n 1 --oneline
```

### Python Virtual Environment Activation

If using a dedicated virtual environment:
```powershell
# If .venv exists:
.\.venv\Scripts\Activate.ps1

# Verify the active Python interpreter
Get-Command python | Select-Object -ExpandProperty Source
```

### Dependency Installation

Ensure all required backend and frontend packages are installed:

```powershell
# Install backend Python dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Install frontend Node dependencies
cd frontend
npm install
cd ..
```

---

## 3. Safe Local Configuration & Environment Variables

TrafficShield includes built-in defaults for local demonstration. Create or verify your local development environment:

```powershell
# Set safe local development environment variables in PowerShell session
$env:FLASK_ENV = "development"
$env:DATABASE_URL = "sqlite:///trafficshield_dev.db"
$env:SECRET_KEY = "trafficshield-local-demo-secret-key"
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
```

> [!IMPORTANT]
> Never put production credentials or real network API keys in development configuration. The application uses a local SQLite database (`trafficshield_dev.db`) created automatically on first startup.

---

## 4. Service Startup (Two-Terminal Workflow)

Run the backend and frontend in two separate PowerShell windows to inspect real-time logs and telemetry.

### Terminal 1: Backend Flask API Server

```powershell
cd D:\projects\trafficshield
$env:FLASK_ENV = "development"
python run.py
```

Expected Terminal 1 output:
```text
 * Serving Flask app 'app'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
TrafficShield ready: db_uri=sqlite:///trafficshield_dev.db
```

### Terminal 2: React SOC Command Center Frontend

```powershell
cd D:\projects\trafficshield\frontend
npm run dev
```

Expected Terminal 2 output:
```text
  VITE v8.3.5  ready in 240 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

---

## 5. Health Verification & Authentication

### 1. Verify API Health (Terminal or Browser)

In a third PowerShell terminal or via browser:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/v1/health" | ConvertTo-Json -Depth 3
```

Expected response:
```json
{
  "status": "success",
  "data": {
    "status": "healthy",
    "version": "1.0.0",
    "database": "connected",
    "model_loaded": true,
    "model_name": "OptunaTuned_XGBoost"
  }
}
```

### 2. User Authentication

TrafficShield enforces role-based access control (RBAC). In development mode (`FLASK_ENV=development`), default testing accounts are seeded automatically if the user database is empty:

| Username | Role | Development Seed Password | Intended Use |
|:---|:---:|:---:|:---|
| `admin` | Administrator | `AdminPass123!` | System configuration & full API access |
| `analyst` | Security Analyst | `AnalystPass123!` | Alert investigation & PCAP replay |

> [!CAUTION]
> These credentials are **strictly development/testing defaults** embedded in `app/utils/auth.py`. In production deployments, initial credentials must be supplied via secure environment variables (`ADMIN_INITIAL_PASSWORD`, `ANALYST_INITIAL_PASSWORD`).

#### Acquire Session Token via PowerShell:
```powershell
$authPayload = @{
    username = "admin"
    password = "AdminPass123!"
} | ConvertTo-Json

$authResponse = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/v1/auth/login" `
    -Method Post `
    -ContentType "application/json" `
    -Body $authPayload

$token = $authResponse.data.token
Write-Host "Authenticated as $($authResponse.data.user.username) (Role: $($authResponse.data.user.role))"
```

### 3. Access the SOC Command Center UI

Open your web browser and navigate to:
**`http://localhost:5173`**

You will see the **TrafficShield SOC Command Center** dark theme dashboard.

---

## 6. Service Teardown & Process Cleanup

When the demonstration is concluded:

1. **Stop Frontend:** Press `Ctrl + C` in Terminal 2.
2. **Stop Backend:** Press `Ctrl + C` in Terminal 1.
3. **Verify No Leftover Processes:**
```powershell
Get-Process -Name python, node -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, Path
```
If any orphaned background process remains:
```powershell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Stop-Process -Name node -Force -ErrorAction SilentlyContinue
```
