# TrafficShield M14 — Final Demonstration Runbook & SOC Walkthrough Guide

**Milestone:** M14 — End-to-End Release Validation  
**Audience:** Security Operations Center (SOC) Leads, Detection Engineers, System Architects  
**Product:** TrafficShield Anomaly Detection Platform v1.0.0  

---

## 1. Demo Preparation & Quick Start

Ensure the integrated system is running:

```powershell
# In terminal 1 (TrafficShield Root):
python run_waitress.py

# In browser, navigate to:
http://localhost:5000/
```

### Credentials:
- **Analyst Role:** `analyst` / `TrafficShieldAnalyst2026!`
- **Admin Role:** `admin` / `TrafficShieldAdmin2026!`

---

## 2. Interactive Demonstration Walkthrough (7 Steps)

### Step 1: Login & SOC Command Center Overview
1. Open `http://localhost:5000/` in the browser.
2. Sign in with the **Analyst** credentials.
3. Observe the **Premium Dark SOC Command Center**:
   - Deep obsidian background with electric cyan/indigo accents.
   - Bento grid layout showing: **Evaluated Flows**, **Detected Anomalies**, **Critical Alerts**, and **Active Model Status**.
   - Notice the **Live Backend Status Pill** in the top header showing "ONLINE - Model v1.0.0".

### Step 2: Live Flow Inspection & ML Inference
1. Navigate to the **Flow Inspector** tab (`/inspector`).
2. Enter or select the default normal flow parameters:
   - Duration: `0.02s`, Forward Bytes: `800`, TTL: `64`, Load: `320000 bps`, Packets: `5`, Window: `255`, Mean Size: `160`.
3. Click **"Analyze Flow"**:
   - Observe instantaneous scoring ($< 20\text{ms}$).
   - Score: `0.0000` (Benign / LOW risk).
   - Review the **Feature Attribution Waterfall** explaining which features kept the score benign.
4. Now test an anomalous probe:
   - Packets: `120`, Forward Bytes: `84000`, Load: `8500000 bps`, Duration: `0.08s`.
5. Click **"Analyze Flow"**:
   - Score escalates immediately ($> 0.85$, CRITICAL risk).
   - High source load and packet burst rate are highlighted as top contributing drivers.

### Step 3: Demonstrate Directional Policy Enforcement (Fail-Closed)
1. Open PowerShell or a terminal to execute an explicit API policy probe:
```bash
curl -X POST http://localhost:5000/api/v1/predict \
  -H "Authorization: Bearer <ANALYST_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 0.1, "fwd_packets": 5, "fwd_bytes": 500, "bwd_packets": 2}'
```
2. Observe the API response:
   - Status: `400 Bad Request`
   - Error Code: `POLICY_VIOLATION`
   - Message: `"Reverse-direction feature 'bwd_packets' is strictly prohibited by unidirectional policy."`
3. Point out to stakeholders: *TrafficShield mathematically guarantees zero dependence on return-path packets.*

### Step 4: SOC Alert Center & Incident Triage
1. Navigate to the **Alerts** tab (`/alerts`).
2. Select a high-severity alert from the table.
3. Review the **Investigation Drawer**:
   - 5-tuple network coordinates: Source IP, Destination IP, Port, Protocol.
   - Model confidence score, decision threshold, and risk level.
4. Update the alert status from `NEW` to `INVESTIGATING` and append analyst notes:
   - *"Investigating high-load volumetric scan from external subnet."*
5. Click **"Update Status"** — note the real-time update in the table.

### Step 5: Ground-Truth Feedback & Scientific Disclaimers
1. In the investigation drawer, open the **Ground Truth Disposition** section.
2. Select disposition: `CONFIRMED_THREAT` and set verified ground truth to `Malicious (1)`.
3. Submit feedback.
4. Navigate to the **Monitoring** tab (`/monitoring`):
   - Highlight the **Operational Metrics Panel**:
   - If no verified ground truth exists, point out the prominent disclaimer: *"Unlabeled traffic cannot be assumed benign or malicious."*
   - Once confirmed labels are recorded, observe authentic precision, recall, and false-positive rates computed strictly over confirmed incidents.

### Step 6: Intelligent Monitoring & Population Drift Detection
1. While on the **Monitoring** tab, inspect the **Population Stability Index (PSI)** charts:
   - Calibration baseline computed over 200,000 flows.
   - Warning threshold at $\text{PSI} \ge 0.10$, Critical drift alert at $\text{PSI} \ge 0.20$.
   - Highlight the **Sample Size Guard**: TrafficShield refuses to emit drift warnings on batches $< 500$ flows, preventing false alarms on statistical noise.
   - Highlight **Alert Debouncing**: Repeated drift triggers increment an alert counter rather than flooding analyst inboxes.

### Step 7: Model Registry Governance & CSV Security
1. Navigate to **Model Intelligence** (`/model`):
   - Review model metadata, version tags, and cryptographic SHA-256 hashes.
   - Explain that byte-level model tampering causes immediate fail-closed termination.
2. Navigate to **Reports** (`/reports`) and click **"Export Alerts to CSV"**:
   - Open the downloaded CSV in Excel or a text editor.
   - Show that any fields starting with `=`, `+`, `-`, or `@` are safely neutralized with `'`, preventing CSV formula injection attacks.
