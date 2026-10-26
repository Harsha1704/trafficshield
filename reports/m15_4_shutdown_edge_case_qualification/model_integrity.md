# TrafficShield M15.4 — Cryptographic Model & Preprocessor Integrity Audit

**Document ID:** TS-M15.4-MODEL-INTEGRITY  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Milestone:** M15.4 Shutdown Edge-Case Verification & Concurrency Hardening  

---

## 1. Baseline Cryptographic Hashes

TrafficShield requires strict preservation of the frozen model and preprocessor artifacts. No retraining, replacement, re-export, or modification is permitted.

Expected baseline SHA-256 hashes:
- **Production Detector:** `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`
- **Production Preprocessor:** `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653`

---

## 2. Verification Records

Hashes were computed directly from disk using `hashlib.sha256` before initiating any code changes and after completing the full regression test suite.

| Artifact Path | Expected Hash | Pre-Execution Hash | Post-Execution Hash | Integrity Status |
|:---|:---:|:---:|:---:|:---:|
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **VERIFIED (MATCH)** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **VERIFIED (MATCH)** |

---

## 3. Preserved Model Parameters & Controls

1. **Decision Threshold:** Preserved exactly at $\tau = 0.50$ (no manual scaling or suppression of anomaly scores).
2. **Feature Input Contract:** Preserved strictly at 13 features:
   - `duration_seconds`, `fwd_bytes`, `sttl`, `sload`, `fwd_packets`, `swin`, `smeansz`, `sjit`, `sintpkt`, `is_sm_ips_ports`, `packet_rate`, `byte_rate`, `bytes_per_packet`.
3. **Data Integrity:** Zero alteration to raw dataset files or historical benchmark artifacts.
4. **Security Controls:** Zero credential, token, or packet payload exposure.
