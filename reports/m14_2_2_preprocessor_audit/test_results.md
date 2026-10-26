# TrafficShield M14.2.2 — Automated Verification Suite & Test Results

**Document ID:** TS-M14-2-2-TESTS  
**Date:** 2026-10-26  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Complete verification results across backend unit/integration tests, frontend tests, static analysis, and production build for Milestone 14.2.2.

---

## 1. Test Execution Summary

| Quality Gate | Engine / Command | Exit Code | Tests Passed | Duration | Status |
|:---|:---|:---:|:---:|:---:|:---:|
| **Full Backend Suite** | `pytest tests/ -q` | **0** | **491 / 491** | 123.25s | **PASS (100%)** |
| **M14.2.2 Consistency Tests** | `pytest tests/unit/test_m14_2_2_preprocessor_consistency.py -v` | **0** | **6 / 6** | 1.81s | **PASS (100%)** |
| **M14.2.1 Contract Tests** | `pytest tests/unit/test_m14_2_1_contract_reconciliation.py -v` | **0** | **8 / 8** | 1.95s | **PASS (100%)** |
| **M14.2 Feature Safety** | `pytest tests/unit/test_m14_2_feature_safety.py -v` | **0** | **20 / 20** | 2.89s | **PASS (100%)** |
| **Frontend Unit & Component** | `vitest run --run` (in `frontend/`) | **0** | **22 / 22** | 2.44s | **PASS (100%)** |
| **Code Quality & Linting** | `ruff check .` | **0** | **All files clean** | 0.82s | **PASS (100%)** |
| **Type Integrity** | `mypy ingestion streaming app` | **0** | **42 source files clean** | 7.12s | **PASS (100%)** |
| **Production Web Build** | `npm run build` (`tsc -b && vite build`) | **0** | **2524 modules** | 757ms | **PASS (100%)** |

---

## 2. Milestone 14.2.2 Targeted Test Output

```
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_artifact_hashes_unmodified PASSED [ 16%]
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_feature_order_alignment_with_detector_booster PASSED [ 33%]
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_is_sm_ips_ports_transforms_strictly_to_unscaled_binary PASSED [ 50%]
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_robust_scaler_mathematical_precision PASSED [ 66%]
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_deterministic_scoring_reproducibility PASSED [ 83%]
tests/unit/test_m14_2_2_preprocessor_consistency.py::TestPreprocessorConsistency::test_forbidden_columns_rejected_before_preprocessor PASSED [100%]
```

---

## 3. Cryptographic Artifact Checksums

```
[OK] artifacts/models/production_detector.joblib
     SHA-256: c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495
     Status:  MATCH (IMMUTABLE)

[OK] artifacts/models/production_preprocessor.joblib
     SHA-256: effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653
     Status:  MATCH (IMMUTABLE)
```
