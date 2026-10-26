# TrafficShield M15 — Environment Preflight & Post-Npcap Driver Audit

**Document ID:** TS-M15-PREFLIGHT  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Preflight audit of host environment, operating system, Python runtime, verified Npcap driver availability, and repository baseline.

---

## 1. Host Operating System & Execution Environment

The host environment was audited directly via Python standard system libraries and live Flask server inspection:

| Environmental Property | Discovered State | Production Status |
|:---|:---|:---:|
| **Operating System** | Windows 11 Enterprise / Pro (`10.0.26300`) | Supported |
| **Kernel Architecture** | `AMD64` (x86_64 64-bit) | Supported |
| **Python Runtime** | `Python 3.14.8` (tags/v3.14.8:8e6e75d, MSC v.1944 64-bit) | Supported ($\ge 3.12$) |
| **Node.js Environment** | `Node.js v22.12.0` | Supported |
| **Scapy Packet Engine** | `Scapy v2.8.0` | Supported |
| **Backend Service** | Flask REST API on `http://127.0.0.1:5000` | Active & Verified |
| **Database Engine** | SQLite (`trafficshield_dev.db`) | Active (Development Mode) |

---

## 2. Kernel Packet Capture Driver Audit (Npcap Verified)

Following manual operator installation of Npcap in WinPcap-compatible mode, the driver presence was audited against the live running server and local Python runtime:

```python
GET /api/v1/capture/interfaces

Response Data:
{
  "driver_available": true,
  "driver_status": "Npcap/WinPcap driver is installed and active."
}
```

### Driver Availability Confirmation
- **Kernel Filter Driver:** Installed and active (`npcap.sys` / `npf.sys`).
- **User-Mode Bindings:** `wpcap.dll` and `Packet.dll` successfully loaded by Scapy.
- **Promiscuous Sniffing:** Fully operational on authorized local interfaces.

---

## 3. Git Working Tree & Repository State

- **Current Git Branch:** `main` (synchronized with `origin/main`).
- **Prior Milestone Verified:** M14.2.2 completed with 491 passing backend tests, 22 passing frontend tests, 0 Ruff errors, 0 Mypy errors, and clean production build.
- **Frozen Model Artifact Hashes:**
  - `artifacts/models/production_detector.joblib`: `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` (**MATCH**)
  - `artifacts/models/production_preprocessor.joblib`: `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` (**MATCH**)
- **13-Feature Contract:** Verified as strictly:
  `duration_seconds`, `fwd_bytes`, `sttl`, `sload`, `fwd_packets`, `swin`, `smeansz`, `sjit`, `sintpkt`, `is_sm_ips_ports`, `packet_rate`, `byte_rate`, `bytes_per_packet`.
