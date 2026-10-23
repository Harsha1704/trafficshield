# TrafficShield Milestone 10: Dataset Inventory & Environmental Inspection
**Date:** 2026-10-23  
**Auditor:** TrafficShield Autonomous Evaluation Engine  

---

## 1. Local Environment Specification

- **Host Operating System:** Windows 11 AMD64
- **Processor:** 16 logical cores (AMD Ryzen 7 5700U with Radeon Graphics)
- **Available System Memory:** ~16.48 GB RAM
- **Python Runtime:** Python 3.14.8 (x86-64)
- **Installed Key Libraries:** `scikit-learn` 1.9+, `xgboost` 3.4.1, `lightgbm` 4.7.0, `optuna` 5.0.0, `shap` 0.54.1, `pandas`, `numpy`, `scipy`.

---

## 2. Dataset Physical Inventory

In accordance with Section 1 and Section 2 of Milestone 10 requirements, an exhaustive filesystem audit was conducted across `datasets/`:

| Dataset Family | File / Component | Local Status | Physical Size | Checksum / Hash | Notes |
|:---|:---|:---:|:---:|:---|:---|
| **UNSW-NB15** | `UNSW-NB15_1.csv` | **PRESENT** | 161.15 MB | 700,001 rows | Captured 22 Jan 2015 |
| **UNSW-NB15** | `UNSW-NB15_2.csv` | **PRESENT** | 157.57 MB | 700,001 rows | Captured 22 Jan 2015 |
| **UNSW-NB15** | `UNSW-NB15_3.csv` | **PRESENT** | 147.43 MB | 700,001 rows | Captured 15 Feb 2015 (24 days later) |
| **UNSW-NB15** | `UNSW-NB15_4.csv` | **PRESENT** | 93.07 MB | 440,044 rows | Captured 15 Feb 2015 |
| **UNSW-NB15** | `NUSW-NB15_GT.csv` | **PRESENT** | 82.42 MB | Ground-truth event list | Used for post-prediction evaluation |
| **CICIDS2017** | `TrafficLabelling / CSVs` | **ABSENT LOCALLY** | 0 MB | NOT_ACQUIRED | Not pre-downloaded; acquisition tool provided |
| **UGR'16** | `ugr16_*.csv.gz` | **ABSENT LOCALLY** | 0 MB | NOT_ACQUIRED | Academic registration required; fixture available |

### Scientific Truth in Reporting:
As mandated, TrafficShield **never fabricates dataset presence or simulates fake evaluations**. Because the 3+ GB raw CICIDS2017 CSVs have not been downloaded to `datasets/raw/cicids2017/`, Track A evaluations on real CICIDS2017 raw files are formally documented as **NOT RUN (Dataset absent locally)**.
