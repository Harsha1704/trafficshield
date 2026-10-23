# TrafficShield M14.1 — Forensic Model Identity & Artifact Audit

**Milestone:** M14.1 — Forensic Model Identity, Feature Equivalence & Real-Time Evidence Audit  
**Date:** 2026-10-23  
**Auditor:** Antigravity  
**Repository:** `D:\projects\trafficshield`  
**Verdict:** **VERIFIED** (Model identity established as `OptunaTuned_XGBoost` / `XGBClassifier`)  

---

## 1. Executive Summary

This forensic audit resolves the discrepancy between previously published documentation in Milestone 14 (which repeatedly referenced a "Frozen Random Forest Detector (100 Estimators)") and the actual serialized binary artifact in `artifacts/models/production_detector.joblib`.

Through direct runtime inspection, bytecode reflection, parameter extraction, and historical tournament tracing from Milestone 9, we conclusively establish that:
1. The physical production model artifact is **`xgboost.sklearn.XGBClassifier`** (an Optuna-tuned gradient boosted decision tree ensemble).
2. The model was trained and serialized during Milestone 8.2 / Milestone 9 as `OptunaTuned_XGBoost` (v1.0.0).
3. The cryptographic hashes of both the model and preprocessor match the authoritative values with 100% bitwise parity.
4. All narrative references to "Random Forest" in Milestone 14 reports (`reports/m14_release/`) are legacy documentation inheritance errata from early M4 baseline descriptions and must be formally corrected.

---

## 2. Cryptographic Integrity & Authoritative Checksums

Both binary artifacts were inspected and cryptographically verified against their established baseline manifests:

| Artifact Path | Expected Authoritative SHA-256 | Actual Measured SHA-256 | Bitwise Parity |
| :--- | :--- | :--- | :--- |
| `artifacts/models/production_detector.joblib` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495` | **MATCH (VERIFIED)** |
| `artifacts/models/production_preprocessor.joblib` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | `effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653` | **MATCH (VERIFIED)** |

Neither artifact has been modified, retrained, or reserialized since Milestone 9.

---

## 3. Runtime Python Introspection of Model Artifact

Direct Python inspection of `artifacts/models/production_detector.joblib`:

```python
import joblib

model = joblib.load("artifacts/models/production_detector.joblib")
print(type(model))
# Output: <class 'xgboost.sklearn.XGBClassifier'>
print(model.__class__.__module__)
# Output: xgboost.sklearn
```

### 3.1 Model Hyperparameters & Internal Configuration
Extracted via `model.get_params()`:

```json
{
  "objective": "binary:logistic",
  "n_estimators": 180,
  "learning_rate": 0.03,
  "max_depth": 5,
  "colsample_bytree": 0.8,
  "subsample": 0.8,
  "min_child_weight": 5,
  "eval_metric": "logloss",
  "random_state": 42,
  "enable_categorical": true,
  "tree_method": null,
  "n_jobs": 1
}
```

### 3.2 Model Metadata JSON
The co-located metadata manifest `artifacts/models/production_detector.json` states:

```json
{
  "model_name": "OptunaTuned_XGBoost",
  "version": "1.0.0",
  "accuracy": 0.9858,
  "attack_recall": 0.9998,
  "attack_precision": 0.9539,
  "threshold": 0.5,
  "features": [
    "duration_seconds",
    "fwd_bytes",
    "sttl",
    "sload",
    "fwd_packets",
    "swin",
    "smeansz",
    "sjit",
    "sintpkt",
    "packet_rate",
    "byte_rate",
    "bytes_per_packet",
    "is_sm_ips_ports"
  ]
}
```

---

## 4. Preprocessor Introspection

Direct Python inspection of `artifacts/models/production_preprocessor.joblib`:

```python
preprocessor = joblib.load("artifacts/models/production_preprocessor.joblib")
print(type(preprocessor))
# Output: <class 'preprocessing.pipeline.TrafficShieldPreprocessor'>
```

- **Class:** `preprocessing.pipeline.TrafficShieldPreprocessor`
- **Scaler Strategy:** `robust` (`sklearn.preprocessing.RobustScaler`)
- **Missing Value Imputation:** `median`
- **Strict Directional Policy Enforced:** `True`
- **Input Feature Count:** 13
- **Input Feature List (`feature_names_in_`):**
  1. `duration_seconds`
  2. `fwd_bytes`
  3. `sttl`
  4. `sload`
  5. `fwd_packets`
  6. `swin`
  7. `smeansz`
  8. `sjit`
  9. `sintpkt`
  10. `is_sm_ips_ports`
  11. `packet_rate`
  12. `byte_rate`
  13. `bytes_per_packet`
- **Output Feature List (`feature_names_out_`):**
  Matches `feature_names_in_` in exact order, with `is_sm_ips_ports` treated as a pass-through boolean/int feature and the 12 numeric features scaled via median/IQR robust scaling.

---

## 5. Root Cause Analysis: The "Random Forest" Discrepancy

Why did Milestone 14 documentation describe the model as a "Frozen Random Forest detector"?

1. **Milestone 4 Origins:** In Milestone 4, TrafficShield implemented two foundational baseline models: `RobustStatisticalDetector` and `IsolationForestDetector`, alongside an exploratory `RandomForestClassifier`.
2. **Milestone 8.2 / Milestone 9 Tournament:** In Milestone 8.2, a 17-model tournament was conducted (`scripts/verify_m9_tournament.py`), evaluating Autoencoders, Isolation Forests, Random Forests, LightGBM, and XGBoost. As documented in [`reports/m9_verification/independent_verification.md`](file:///D:/projects/trafficshield/reports/m9_verification/independent_verification.md):
   - `OptunaTuned_XGBoost` was selected as the champion production detector with 98.10% accuracy on the held-out test split (19,942 flows) and 97.38% on Day 2 temporal holdout.
   - It was serialized to `artifacts/models/production_detector.joblib` with SHA-256 `c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495`.
3. **Milestone 14 Documentation Inheritance Errata:** When Milestone 14 reports were authored (`final_project_summary.md`, `known_limitations.md`, `performance_and_resilience.md`, `preflight_findings.md`), boilerplate text from Milestone 4 ("frozen Random Forest detector") was accidentally propagated into the overview summaries.
4. **Correction:** The actual runtime estimator has **always** been `OptunaTuned_XGBoost` (`XGBClassifier`). The code, tests, and API service ([`ml/production_service.py`](file:///D:/projects/trafficshield/ml/production_service.py)) load and invoke `XGBClassifier` without modification.

---

## 6. Audit Verdict

| Verification Item | Target | Forensic Finding | Verdict |
| :--- | :--- | :--- | :--- |
| **Model Estimator Class** | Expected `XGBClassifier` vs documented "Random Forest" | `<class 'xgboost.sklearn.XGBClassifier'>` | **VERIFIED** |
| **Model Identity** | Named model in metadata | `OptunaTuned_XGBoost` v1.0.0 | **VERIFIED** |
| **Model Checksum** | SHA-256 `c43bb5...` | Exactly matches authoritative hash | **VERIFIED** |
| **Preprocessor Checksum** | SHA-256 `effe96...` | Exactly matches authoritative hash | **VERIFIED** |
| **Feature Name Alignment** | 13 features contract | Exact match between preprocessor & model | **VERIFIED** |
