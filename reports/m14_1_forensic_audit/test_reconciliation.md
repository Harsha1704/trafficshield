# TrafficShield M14.1 — Test & Operational Parameter Reconciliation

**Milestone:** M14.1 — Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED & RECONCILED**  

---

## 1. Executive Summary

This report systematically cross-examines and reconciles all numerical discrepancies, parameter thresholds, test counts, and architectural descriptions identified between earlier milestone reports and the actual production codebase.

---

## 2. Backend Test Count Reconciliation: 444 vs 457

| Milestone Stage | Test Count | Test Scope & Additions | Authoritative Evidence |
| :--- | :---: | :--- | :--- |
| **M13 Production Ready** | 418 | Application factory, RBAC auth, tamper defense, CSRF/CSP headers, monitoring baseline, alert lifecycle, and database recovery. | `pytest tests/` (418 passed) |
| **M14 Release Gate** | 444 | Added 20 end-to-end workflow tests (`tests/integration/test_m14_end_to_end_release.py`) and 6 Scapy parser tests (`tests/unit/test_pcap_real_time_features.py`). | `pytest tests/` (444 passed) |
| **M14 Real-Time Engine** | 457 | Added 13 real-time capture and flow reconstruction unit tests (`tests/unit/test_m14_realtime_detection.py`). | `pytest tests/` (457 passed in 27.44s) |

### Fresh Pytest Execution Output (2026-10-23T22:55:47Z)
```
collected 457 items
============================ 457 passed in 27.44s =============================
```

**Reconciliation Verdict:** 444 was the pre-M14 real-time test count. 457 is the current, authoritative, verified backend test count.

---

## 3. Estimator Type Reconciliation

| Document / Location | Stated Model Type | Actual Physical Artifact | Root Cause & Resolution |
| :--- | :--- | :--- | :--- |
| `reports/m14_release/final_project_summary.md` | "Frozen Random Forest detector (100 Estimators)" | `<class 'xgboost.sklearn.XGBClassifier'>` | **Errata:** Copy-paste inheritance from M4 baseline description. |
| `reports/m14_release/known_limitations.md` | "Frozen Random Forest detector" | `<class 'xgboost.sklearn.XGBClassifier'>` | **Errata:** Copy-paste inheritance from M4 baseline description. |
| `reports/m9_verification/independent_verification.md` | `OptunaTuned_XGBoost` | `<class 'xgboost.sklearn.XGBClassifier'>` | **Authoritative:** Correct champion model from 17-model tournament. |
| `artifacts/models/production_detector.json` | `OptunaTuned_XGBoost` v1.0.0 | `<class 'xgboost.sklearn.XGBClassifier'>` | **Authoritative:** Co-located metadata manifest. |
| `ml/production_service.py` | `XGBClassifier` | `<class 'xgboost.sklearn.XGBClassifier'>` | **Authoritative:** Production inference loader and scoring logic. |

**Reconciliation Verdict:** The estimator is strictly `xgboost.sklearn.XGBClassifier` with 180 estimators, learning rate 0.03, max depth 5, and objective `binary:logistic`. All Random Forest references in M14 narrative summaries are documented as superseded errata.

---

## 4. Batch Limit Reconciliation

Different endpoints enforce different batch capacity limits based on operational purpose:

| Endpoint | Max Batch Size | Enforced In | HTTP Error Code | Operational Purpose |
| :--- | :---: | :--- | :---: | :--- |
| `POST /api/v1/predict/batch` | **5,000 records** | `app/api/v1/predict.py:129` | `413 BATCH_SIZE_EXCEEDED` | Real-time vectorized ML inference. |
| `POST /api/v1/alerts/batch` | **1,000 records** | `app/api/v1/alerts.py:232` | `413 BATCH_SIZE_EXCEEDED` | SOC alert database seeding and batch resolution. |
| `M9 Benchmark Documentation` | *10,000 records* | Historical benchmark scripts | N/A | Memory throughput stress test (627,000 flows/sec). |

**Reconciliation Verdict:** The live production API enforces 5,000 records for inference (`/predict/batch`) and 1,000 records for alert ingestion (`/alerts/batch`). The 10,000 figure was an offline synthetic stress test.

---

## 5. Drift Sample-Size Guard Reconciliation

| Document / Source | Stated Minimum Sample Size | Actual Code Constant | Location |
| :--- | :---: | :---: | :--- |
| `reports/m14_release/known_limitations.md` | $\ge 500$ flows | N/A | Documentation prose |
| `reports/m14_release/end_to_end_test_report.md` | $< 500$ flows | N/A | Documentation prose |
| `monitoring/drift_engine.py:32` | **$\ge 30$ flows** | `DEFAULT_MIN_SAMPLE_SIZE = 30` | Programmatic constant |
| `monitoring/service.py:49` | **$\ge 30$ flows** | `DEFAULT_MIN_SAMPLE_SIZE = 30` | Monitoring service default |
| `tests/integration/test_m14_end_to_end_release.py:326` | **$\ge 30$ flows** | Tested with 10 records | End-to-end integration test |

**Reconciliation Verdict:** The programmatic sample size guard enforced by the drift engine is **30 flows** (`DEFAULT_MIN_SAMPLE_SIZE = 30`). Batches with $N < 30$ return `overall_status: "INSUFFICIENT_DATA"` with drift testing deferred. The 500-flow figure in earlier M14 reports was an enterprise operational recommendation, not the hardcoded threshold.

---

## 6. Audit Verdict

| Reconciliation Target | Code Reality | Status |
| :--- | :--- | :--- |
| **Backend Test Count** | 457 passed in 27.44s | **RECONCILED** |
| **Model Estimator** | `xgboost.sklearn.XGBClassifier` (`OptunaTuned_XGBoost`) | **RECONCILED** |
| **Inference Batch Limit** | 5,000 records (HTTP 413) | **RECONCILED** |
| **Alert Batch Limit** | 1,000 records (HTTP 413) | **RECONCILED** |
| **Drift Guard Threshold** | $N < 30$ returns `INSUFFICIENT_DATA` | **RECONCILED** |
