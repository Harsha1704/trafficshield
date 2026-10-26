# TrafficShield — Evaluator Quick Start Guide

**Document ID:** TS-DOC-QUICKSTART  
**Target Gate:** `READY FOR LOCAL DEMONSTRATION`  
**Platform:** Windows 10 / 11 · Linux · macOS  
**Recommended Browser:** Chrome · Edge · Firefox  

---

## 1. System Requirements & Preparation

TrafficShield is designed for local, evaluator-friendly execution without requiring specialized hardware, external network connectivity, or kernel driver privileges for demonstration.

| Requirement | Minimum | Tested Baseline | Notes |
| :--- | :--- | :--- | :--- |
| **Python** | 3.12+ | Python 3.14.8 AMD64 | Required for Flask backend & ML pipeline |
| **Node.js & npm** | Node 18+, npm 9+ | Node 20+, npm 10+ | Required for React SOC dashboard |
| **Packet Capture Driver** | Optional | Npcap 1.80+ (Windows) | **Not required for offline demonstration** |
| **Database** | SQLite | `trafficshield_dev.db` | Automatically initialized on startup |

---

## 2. Fast Step-by-Step Launch

### Terminal 1: Backend API Service

```powershell
# 1. Navigate to the project root
cd D:\projects\trafficshield

# 2. Activate virtual environment (if present)
.\.venv\Scripts\Activate.ps1

# 3. Set local environment variables (safe local defaults)
$env:FLASK_ENV = "development"
$env:DATABASE_URL = "sqlite:///trafficshield_dev.db"
$env:SECRET_KEY = "trafficshield-local-demo-secret-key"

# 4. Start the backend server
python run.py
```
*Expected Output:* Server listening on `http://127.0.0.1:5000` with database connected and XGBoost model loaded.

### Terminal 2: React Frontend Dashboard

```powershell
# 1. Open a second terminal and navigate to frontend directory
cd D:\projects\trafficshield\frontend

# 2. Start the Vite development server
npm run dev
```
*Expected Output:* Local web interface accessible at `http://localhost:5173`.

---

## 3. Authenticating to the SOC Dashboard

1. Open your browser and navigate to `http://localhost:5173`.
2. Login with configured development credentials:
   - **Username:** `admin`
   - **Password:** `AdminPass123!`
3. Verify access to the main SOC Navigation menu:
   - **Live Detection & PCAP Replay** (Primary Demo Page)
   - **Security Alerts & Ledger**
   - **Traffic & Flow Analytics**
   - **Model Intelligence & Drift Monitor**

---

## 4. Conducting the Offline PCAP Demonstration

1. In the sidebar, select **Live Detection**.
2. Ensure the mode toggle is set to **Offline PCAP Replay**.
3. Select the built-in authorized fixture `sample_traffic.pcap` (`D:/projects/trafficshield/data/captures/sample_traffic.pcap`).
4. Set the **Replay Speed Multiplier** to `2.0x` (or `Max` for instant ingestion).
5. Click **Start Replay**:
   - Packets Observed increments to **29**.
   - Completed flows increment to **24**.
   - Streaming detection events populate the real-time feed with sub-second latency.
   - Tier 1 Driver drops display `<Badge variant="slate">Unavailable</Badge>` (honest provenance for offline replay).
   - Tier 2 Ingestion drops and Tier 3 Queue drops remain **0**.
6. Click **Stop Session**:
   - Active flows cleanly flush to 0.
   - Worker queue drains completely with 0 unprocessed flows.

---

## 5. Troubleshooting & Common Issues

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| **`Connection Refused` on login** | Backend server is not running on port 5000 | Verify Terminal 1 is running `python run.py`. Check that port 5000 is not blocked. |
| **`Model Integrity Check Failed`** | Joblib file modified or truncated | Re-verify SHA-256: Detector must match `c43bb5...`, Preprocessor must match `effe96...`. |
| **`Driver Unavailable` warning** | Npcap is not installed on host machine | Expected on developer machines without Npcap. Offline PCAP replay functions 100% without drivers. |
| **Database locked error** | Concurrent SQLite processes accessing db | Restart backend process; SQLite locks release immediately upon termination. |
