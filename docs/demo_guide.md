# TrafficShield — Evaluator Demonstration Guide

**5-to-7 Minute Interactive Walkthrough for Technical Evaluators & SOC Leads**

> **Target Platform:** Windows 11 (or Linux/macOS)  
> **Repository:** `D:\projects\trafficshield`  
> **Environment:** Localhost-only (Zero external cloud dependencies)  
> **Architecture:** Hybrid ML Anomaly Detection (Frozen XGBoost + Calibrated Isolation Forest)

---

## 1. Executive Summary & Architecture Context

TrafficShield is purpose-built to protect **critical-infrastructure networks** (substations, water treatment plants, telecommunications) where hardware **data diodes and unidirectional optical taps** physically restrict traffic visibility to one direction only.

Because reverse traffic (TCP ACKs, return payloads, server replies) is unavailable, conventional bidirectional flow classifiers fail. TrafficShield solves this by combining:
1. **Supervised XGBoost Detector:** Identifies known attack signatures across 13 forward features ($\tau = 0.50$).
2. **Unsupervised Isolation Forest:** Detects novel structural deviations and zero-day anomalies without requiring attack labels during training ($\tau = 0.727896$).
3. **Hybrid Decision Engine:** Transparently fuses both models into a 4-tier decision taxonomy:
   - `DUAL_CONFIRMED` (Highest confidence — matching signature + structural outlier)
   - `SUPERVISED_ONLY_ALERT` (Known malicious signature)
   - `UNSUPERVISED_NOVELTY` (Novel outlier / potential zero-day)
   - `NORMAL_TRAFFIC` (Benign flow)

---

## 2. Pre-Flight Checklist & Prerequisites

Ensure the following prerequisites are installed on your Windows machine:
- **Python:** $\ge 3.12$ (verified on 3.12, 3.14)
- **Node.js & npm:** $\ge 18.0$
- **Packet Capture Driver:** Npcap (installed with "WinPcap API-compatible mode" enabled) for live sniffing, or use the included offline PCAP replays.

### Pre-Flight Artifact Integrity Check
Before starting any services, verify that all model artifacts match their authoritative cryptographic digests:

```powershell
Get-FileHash artifacts/models/* | Select-Object Path, Hash
```

**Authoritative Checksums:**
| File | Algorithm | Hash | Status |
|---|---|---|---|
| `production_detector.joblib` | SHA-256 | `C43BB5CABD848F930EB7A977B730E401BD8204D6DD63170D1D2F2DF2E4D27495` | FROZEN (XGBoost) |
| `production_detector.json` | SHA-256 | `3553F1A47C1C2FD67B031CADB42400246997778F8DCF42026E2EBFB882BA73B1` | FROZEN (Metadata) |
| `production_preprocessor.joblib` | SHA-256 | `EFFE96E1977CE9687EB602A953F34F70A42EE1881BF678F59C40B99A1EECC653` | FROZEN (Scaler) |
| `production_iforest.joblib` | SHA-256 | `D9FE41016C51F8484B57C80BB2F0EC41186C66ADD9BAE71F822D0A85C13A350E` | VERIFIED (IForest) |
| `production_iforest.json` | SHA-256 | `5DAF8B0DAB1C4C3A66E4CB2C38B10C406F6C1861572D27A08155C8541BF4CB94` | VERIFIED (Metadata) |

---

## 3. Starting the Application

Open two separate PowerShell terminal windows.

### Terminal 1: Backend Flask API Service
```powershell
cd D:\projects\trafficshield
python run.py
```
*Expected log output:*
```
[INFO] Loading production models and preprocessors...
[INFO] SHA-256 verification passed for production_detector.joblib
[INFO] SHA-256 verification passed for production_iforest.joblib
[INFO] Hybrid Inference Engine initialized successfully.
 * Running on http://127.0.0.1:5000 (Press CTRL+C to quit)
```

### Terminal 2: Frontend SOC Command Center
```powershell
cd D:\projects\trafficshield\frontend
npm.cmd run dev
```
*Expected log output:*
```
  VITE v6.x.x  ready in 240 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

---

## 4. Step-by-Step Evaluator Demo Walkthrough

### Step 1: Access & Authentication (Minute 0:00 – 1:00)
1. Open your browser and navigate to `http://localhost:5173/login`.
2. Authenticate using the built-in development analyst account:
   - **Email:** `analyst@trafficshield.local`
   - **Password:** `AnalystSecure2026!`
3. Notice the seamless transition to the dark obsidian tactical command center.

### Step 2: SOC Overview Dashboard (Minute 1:00 – 2:00)
1. Navigate to **Overview** (`/`).
2. Review the top-level metric counters:
   - **Total Monitored Flows**
   - **Active Anomalies & Threats**
   - **Dual-Confirmed Ratio**
   - **Pipeline Engine Health**
3. Inspect the **24-Hour Threat Distribution** chart and the **Active Sensor Nodes** panel showing the unidirectional link status.

### Step 3: Real-Time Live Detection & Packet Ingestion (Minute 2:00 – 3:30)
1. Navigate to **Live Detection** (`/live`).
2. In the **Control Panel**:
   - To replay pre-captured traffic: Select `sample_traffic.pcap`, choose replay speed `2x`, and click **Start Replay**.
   - To capture live traffic: Select your network interface (e.g. `Wi-Fi` or `Ethernet`), enter BPF filter (optional, e.g. `ip`), and click **Start Live Capture**.
3. Observe real-time flow reconstruction:
   - Packets arrive and are aggregated into unidirectional 5-tuples.
   - The live flow table populates dynamically with source/dest IP, protocol, duration, packet count, and bytes.
   - The **Dual Score Gauge** displays simultaneous supervised probability ($P$) and unsupervised anomaly score ($S$).
   - High-severity events immediately trigger visual status badges: `DUAL_CONFIRMED` (Red), `SUPERVISED_ONLY` (Amber), or `UNSUPERVISED_NOVELTY` (Purple).

### Step 4: Alerts & Incident Investigation (Minute 3:30 – 5:00)
1. Navigate to **Alerts & Triage** (`/alerts`).
2. Notice the filter tabs at the top:
   - Click **Dual Confirmed** to isolate critical incidents where both algorithms agreed on a threat.
   - Click **Supervised Only** to view known attack signatures.
   - Click **Unsupervised Novelty** to inspect structural outliers with benign signatures.
3. Click any alert row to open the **Investigation Modal**:
   - Inspect the **Dual Model Attribution**: Supervised score vs. Unsupervised score with calibrated threshold markers.
   - Review the **13 Causal Forward Features** that produced this decision.
   - Update triage state: Change status from `NEW` to `INVESTIGATING` and append analyst notes (e.g., *"Confirmed volumetric SYN probe; notifying substation gateway firewall team"*). Click **Save Triage**.

### Step 5: Traffic Analysis & Batch Scoring (Minute 5:00 – 6:00)
1. Navigate to **Traffic Analysis** (`/traffic`).
2. Drag and drop a flow batch CSV file or click to upload a batch.
3. Observe client-side and server-side feature policy validation:
   - Notice that if any reverse features (e.g. `dbytes`, `dload`) are present, TrafficShield rejects them immediately to maintain unidirectional integrity.
   - The platform calculates vectorized batch metrics in $< 50\text{ ms}$, providing an instant breakdown of the four hybrid categories.

### Step 6: Model Intelligence & Statistical Drift (Minute 6:00 – 7:00)
1. Navigate to **Model Performance** (`/models`) to view:
   - The 13 production features ranking by SHAP importance.
   - Validation performance metrics (ROC curves, PR curves, F1-scores).
2. Navigate to **Monitoring** (`/monitoring`) to inspect:
   - Population Stability Index (PSI) tracking input feature distribution drift against the calibration baseline (`reference_baseline.json`).
   - Wasserstein distance and Kolmogorov-Smirnov test statistics.
   - Model Registry audit table confirming the active artifact hashes and promotion governance.

---

## 5. API Demonstration via PowerShell

Evaluators can also verify the hybrid detection engine directly through the REST API using PowerShell:

```powershell
# Single-flow prediction test
$payload = @{
    features = @{
        duration_seconds = 0.05
        fwd_bytes = 1024
        sttl = 64
        sload = 163840.0
        fwd_packets = 8
        swin = 65535
        smeansz = 128.0
        sjit = 12.5
        sintpkt = 7.14
        is_sm_ips_ports = 0
        packet_rate = 160.0
        byte_rate = 20480.0
        bytes_per_packet = 128.0
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/v1/predict/single" -Method Post -Body $payload -ContentType "application/json"
```

*Sample API Output:*
```json
{
  "success": true,
  "data": {
    "supervised": {
      "is_anomaly": true,
      "anomaly_score": 0.8942,
      "confidence": 0.8942,
      "threshold": 0.5
    },
    "unsupervised": {
      "is_anomaly": true,
      "anomaly_score": 0.7812,
      "confidence": 0.825,
      "threshold": 0.727896
    },
    "hybrid_classification": "DUAL_CONFIRMED",
    "is_anomaly": true,
    "severity": "CRITICAL"
  }
}
```

---

## 6. Clean Teardown & Shutdown

To terminate the running demonstration cleanly:
1. In the **Frontend Terminal**, press `Ctrl + C` and confirm termination (`Y`).
2. In the **Backend Terminal**, press `Ctrl + C` to gracefully stop the Flask development server.
3. If background tasks were launched, ensure no orphan Python or Node processes remain:
   ```powershell
   Get-Process -Name python, node -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, Path
   ```

---

## 7. Troubleshooting & FAQ

- **Q: Live capture fails with "Npcap/WinPcap driver missing"?**  
  *A:* Install [Npcap](https://npcap.com/) on Windows with the "Install Npcap in WinPcap API-compatible Mode" option checked. Alternatively, use the built-in PCAP replay feature (`POST /api/v1/capture/start-replay`) which requires no kernel drivers.
- **Q: Why are broadcast/multicast packets classified as `SUPERVISED_ONLY_ALERT`?**  
  *A:* On local subnets, Windows mDNS and SSDP broadcast frames use $TTL=255$. In the UNSW-NB15 training distribution, $TTL=255$ was heavily associated with attack traffic, leading the supervised XGBoost model to flag them, while the Isolation Forest recognizes their normal structural profile. The hybrid engine categorizes them transparently as `SUPERVISED_ONLY_ALERT` rather than escalating to `DUAL_CONFIRMED`.
