# TrafficShield M14.2.1 — Automated Test Suite & Quality Verification Results

**Document ID:** TS-M14-2-1-TESTS  
**Date:** 2026-10-24  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Complete verification results across backend unit/integration tests, frontend tests, static analysis, and production build.

---

## 1. Test Suite Execution Summary

| Test Domain | Runner / Engine | Scope | Total Tests | Passed | Failed | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Backend Integration & Unit** | `pytest 9.1.1` (Python 3.14.8) | Full application, detection, ingestion, and M14.2.1 contract tests | **485** | **485** | **0** | **PASS (100%)** |
| **Frontend Unit & Component** | `vitest 5.0.5` (Node v22.12.0) | React 19 UI, Bento grids, provenance badges, and mock telemetry | **22** | **22** | **0** | **PASS (100%)** |
| **Contract Reconciliation** | `pytest tests/unit/test_m14_2_1_contract_reconciliation.py` | Artifact contracts, forbidden field rejection, end-to-end alignment | **8** | **8** | **0** | **PASS (100%)** |
| **Feature Safety & Fragments** | `pytest tests/unit/test_m14_2_feature_safety.py` | Sload/Sjit fidelity, TTL validation, packet pre-validation, fragments | **20** | **20** | **0** | **PASS (100%)** |
| **Type Integrity** | `mypy 1.13.0` | `ingestion/`, `streaming/`, `app/` (42 source files) | **42 files** | **Clean** | **0** | **PASS (100%)** |
| **Linting & Code Quality** | `ruff 0.8.2` | Entire repository | **All files** | **Clean** | **0** | **PASS (100%)** |
| **Frontend Production Build** | `vite build` (`tsc -b && vite build`) | Production bundle in `frontend/dist/` | **2524 modules** | **Clean** | **0** | **PASS (100%)** |

---

## 2. Milestone 14.2.1 Targeted Contract Tests

```
tests/unit/test_m14_2_1_contract_reconciliation.py::TestFrozenModelFeatureContract::test_artifact_hashes_strictly_preserved PASSED [ 12%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestFrozenModelFeatureContract::test_preprocessor_authoritative_feature_names PASSED [ 25%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestFrozenModelFeatureContract::test_detector_authoritative_feature_names_and_dimension PASSED [ 37%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestForbiddenFeatureRejection::test_policy_classifies_discrepant_features_as_forbidden[res_bdy_len] PASSED [ 50%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestForbiddenFeatureRejection::test_policy_classifies_discrepant_features_as_forbidden[trans_depth] PASSED [ 62%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestForbiddenFeatureRejection::test_policy_classifies_discrepant_features_as_forbidden[ct_state_ttl] PASSED [ 75%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestForbiddenFeatureRejection::test_inference_service_rejects_forbidden_columns PASSED [ 87%]
tests/unit/test_m14_2_1_contract_reconciliation.py::TestEndToEndPipelineAlignment::test_flow_builder_output_satisfies_inference_service PASSED [100%]
```

---

## 3. Cryptographic Artifact Integrity Verification

```
Artifact 1: artifacts/models/production_detector.joblib
  Expected: c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495
  Actual:   c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495
  Result:   MATCH (VERIFIED IMMUTABLE)

Artifact 2: artifacts/models/production_preprocessor.joblib
  Expected: effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653
  Actual:   effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653
  Result:   MATCH (VERIFIED IMMUTABLE)
```
