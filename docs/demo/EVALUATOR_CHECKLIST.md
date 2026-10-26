# TrafficShield — Evaluator Verification Checklist

**Document ID:** TS-DOC-EVALUATOR-CHECKLIST  
**Auditor / Presenter:** TrafficShield Engineering Team  
**Evaluation Target:** Master Milestone Qualification  
**Release Gate:** `READY FOR LOCAL DEMONSTRATION`  

---

## 1. Pre-Demonstration Verification Matrix

| # | Verification Criterion | Expected Standard | Observed Evidence | Verdict |
| :---: | :--- | :--- | :--- | :---: |
| 1 | **Git Working Tree** | Clean working tree on `main` branch | Commit `cccc5b9` / current verified commit | [x] **PASS** |
| 2 | **Detector Cryptographic Hash** | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | Matches bit-for-bit | [x] **PASS** |
| 3 | **Preprocessor Cryptographic Hash** | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | Matches bit-for-bit | [x] **PASS** |
| 4 | **Model Feature Contract** | Exactly 13 forward features | Validated via `ProductionInferenceService` | [x] **PASS** |
| 5 | **Decision Gate Threshold** | Strictly 0.50 | Frozen detection threshold | [x] **PASS** |
| 6 | **API Health Check** | `GET /api/v1/health` returns HTTP 200 | `status: "healthy"`, `database: "connected"` | [x] **PASS** |
| 7 | **Authentication & RBAC** | Seeded admin/analyst logins function | Admin token issued with role `admin` | [x] **PASS** |
| 8 | **Offline PCAP Replay** | Replays `sample_traffic.pcap` deterministically | Exactly 29 packets, 24 flows scored; scores 0.1273 - 0.3681 (< 0.50) | [x] **PASS** |
| 9 | **Tiered Drop Accounting** | Tier 1 driver, Tier 2 packet, Tier 3 flow queue | Separate metrics displayed and audited | [x] **PASS** |
| 10 | **Native Stats Honesty** | Unavailable stats rendered with badge, not 0 | Offline replay displays `Unavailable` | [x] **PASS** |
| 11 | **Graceful Shutdown** | Drains residual flows; 0 unprocessed flows | Clean 5-stage drain; 0 dropped on stop | [x] **PASS** |
| 12 | **Zero Payload Retention** | Raw application payload bytes discarded | Envelope contains only 5-tuple metadata | [x] **PASS** |
| 13 | **Backend Test Suite** | 100% passing across full regression suite | **579 / 579 backend tests passed** | [x] **PASS** |
| 14 | **Frontend Test Suite** | 100% passing across Vitest test suite | **28 / 28 frontend tests passed** | [x] **PASS** |
| 15 | **Frontend Build** | Clean production compilation | `tsc -b && vite build` clean (272ms) | [x] **PASS** |

---

## 2. Step-by-Step Evaluator Script

1. **Verify Integrity Checksums:**
   ```powershell
   Get-FileHash artifacts/models/* -Algorithm SHA256 | Format-List
   ```
2. **Start Services:**
   - Backend: `python run.py` (Port 5000)
   - Frontend: `npm run dev --prefix frontend` (Port 5173)
3. **Execute Offline Replay:**
   - Navigate to `http://localhost:5173`.
   - Log in (`admin` / `AdminPass123!`).
   - Open **Live Detection**, select `sample_traffic.pcap`, and click **Start Replay**.
   - Observe real-time flow completion (24 flows scored) and streaming event entries.
   - Note that scores appropriately stay below 0.50 (max 0.3681 on TLS, 0.1273 on single probes).
   - Click **Stop Session** and verify clean shutdown with 0 unprocessed flows.
4. **Validate True-Positive Alert Persistence:**
   - Run the automated detection qualification test:
     ```powershell
     python -m pytest tests/unit/test_detection_validation.py -v
     ```
   - Confirms true-positive anomaly detection ($\text{score} \ge 0.85$, CRITICAL) and database alert persistence.
