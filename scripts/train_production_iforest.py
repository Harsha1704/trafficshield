"""
TrafficShield — Production Isolation Forest Training Pipeline
============================================================
Phase 1: Hybrid Architecture — Unsupervised Isolation Forest Detector

Trains an independent, auditable IsolationForestDetector for unidirectional network
traffic anomaly detection:
1. Reuses detection.isolation_forest.IsolationForestDetector without duplicating implementation.
2. Uses the frozen production preprocessor (artifacts/models/production_preprocessor.joblib)
   and the strict 13-feature unidirectional contract.
3. Trains strictly on benign samples from the designated chronological Train split of Day 1.
   Labels are used exclusively for subset selection; labels are never passed into fitting.
4. Uses the separate chronological Calibration split (benign samples) to calibrate the
   anomaly score decision threshold at a configurable quantile (default: 0.99).
5. Validates artifact integrity and writes atomically via temporary files to:
   - artifacts/models/production_iforest.joblib
   - artifacts/models/production_iforest.json
6. Verifies that existing supervised XGBoost and preprocessor artifacts remain byte-identical.
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import time
import types
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows Smart App Control / WDAC compatibility guard:
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        _mock_sag.sag64 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

if "scipy.stats._qmvnt_cy" not in sys.modules:
    try:
        import scipy.stats._qmvnt_cy  # noqa: F401
    except (ImportError, OSError):
        _mock_qmvnt = types.ModuleType("scipy.stats._qmvnt_cy")
        _mock_qmvnt._qmvn_inner = lambda *args, **kwargs: (0.0, 0.0)
        _mock_qmvnt._qmvt_inner = lambda *args, **kwargs: (0.0, 0.0)
        sys.modules["scipy.stats._qmvnt_cy"] = _mock_qmvnt

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402

from detection.artifacts import compute_sha256, load_detector, save_detector  # noqa: E402
from detection.isolation_forest import IsolationForestDetector  # noqa: E402
from evaluation.partitioning import chronological_four_way_split  # noqa: E402
from ingestion.adapters.unsw_nb15 import UNSW15Adapter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_iforest")

# Authoritative frozen hashes for existing artifacts:
EXPECTED_SUPERVISED_MODEL_SHA256 = "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
EXPECTED_SUPERVISED_META_SHA256 = "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1"
EXPECTED_PREPROCESSOR_SHA256 = "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"

DEFAULT_13_FEATURES = [
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
    "is_sm_ips_ports",
]


def verify_frozen_artifacts() -> None:
    """Ensure existing supervised model and preprocessor are untouched."""
    checks = [
        ("artifacts/models/production_detector.joblib", EXPECTED_SUPERVISED_MODEL_SHA256),
        ("artifacts/models/production_detector.json", EXPECTED_SUPERVISED_META_SHA256),
        ("artifacts/models/production_preprocessor.joblib", EXPECTED_PREPROCESSOR_SHA256),
    ]
    for path_str, exp_hash in checks:
        p = Path(path_str)
        if not p.exists():
            raise FileNotFoundError(f"Required frozen artifact missing: {path_str}")
        actual_hash = compute_sha256(p)
        if actual_hash != exp_hash:
            raise RuntimeError(
                f"Frozen artifact hash mismatch on {path_str}!\n"
                f"  Expected: {exp_hash}\n"
                f"  Actual:   {actual_hash}"
            )
    logger.info("Frozen artifact hashes verified byte-identical.")


def train_production_isolation_forest(
    raw_dir: str | Path = "datasets/raw/unsw_nb15",
    max_day1_rows: int = 100_000,
    n_estimators: int = 100,
    contamination: float | str = "auto",
    max_samples: int | float | str = "auto",
    calibration_quantile: float = 0.99,
    random_state: int = 42,
    output_model_path: str | Path = "artifacts/models/production_iforest.joblib",
    preprocessor_path: str | Path = "artifacts/models/production_preprocessor.joblib",
) -> dict[str, Any]:
    """Train, calibrate, and atomically serialize the production Isolation Forest."""
    raw_dir = Path(raw_dir)
    output_model_path = Path(output_model_path)
    output_json_path = output_model_path.with_suffix(".json")
    prep_path = Path(preprocessor_path)

    # 1. Pre-flight integrity check
    verify_frozen_artifacts()

    # 2. Load frozen preprocessor
    logger.info("Loading frozen production preprocessor from %s", prep_path)
    preprocessor = joblib.load(prep_path)
    prep_hash = compute_sha256(prep_path)

    # Verify preprocessor feature expectations
    if hasattr(preprocessor, "feature_names_out_"):
        expected_features = list(preprocessor.feature_names_out_)
    elif hasattr(preprocessor, "feature_names_in_"):
        expected_features = list(preprocessor.feature_names_in_)
    else:
        expected_features = DEFAULT_13_FEATURES

    # 3. Load Day 1 raw dataset
    day1_files = [raw_dir / fn for fn in ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv") if (raw_dir / fn).exists()]
    if not day1_files:
        raise FileNotFoundError(f"UNSW-NB15 Day 1 raw CSV files not found in {raw_dir}")

    logger.info("Loading Day 1 data from %s (max %d rows)...", [f.name for f in day1_files], max_day1_rows)
    adapter = UNSW15Adapter(chunk_size=50_000)
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(
        filepaths=day1_files,
        max_rows=max_day1_rows,
        causal_only=True,
        deduplicate_boundaries=True,
    )
    df_day1 = pd.concat([feat_df, lbl_series.rename("eval_label"), meta_df[["flow_end_ts"]]], axis=1)

    # 4. Strict chronological 4-way split (50% Train, 15% Val, 15% Cal, 20% Test)
    logger.info("Executing chronological 4-way split...")
    partition = chronological_four_way_split(
        df_day1,
        train_ratio=0.50,
        val_ratio=0.15,
        cal_ratio=0.15,
        test_ratio=0.20,
        timestamp_col="flow_end_ts",
    )

    # 5. Extract Train split and isolate benign flows
    train_df = partition.train_df
    train_total_count = len(train_df)
    train_benign_mask = train_df["eval_label"].astype(str).str.lower() == "normal"
    train_benign_df = train_df[train_benign_mask]
    train_benign_count = len(train_benign_df)

    logger.info(
        "Train split total: %d flows | Benign-only selection: %d flows (attack flows excluded: %d)",
        train_total_count,
        train_benign_count,
        train_total_count - train_benign_count,
    )

    # Transform training features through frozen preprocessor
    train_features = train_benign_df[list(feat_df.columns)]
    X_train_transformed = preprocessor.transform_df(train_features)

    # Enforce column schema
    if list(X_train_transformed.columns) != expected_features:
        X_train_transformed = X_train_transformed[expected_features]

    # 6. Fit IsolationForestDetector (strictly unsupervised, zero labels passed)
    logger.info(
        "Fitting IsolationForestDetector (n_estimators=%d, max_samples=%s, contamination=%s, seed=%d)...",
        n_estimators,
        str(max_samples),
        str(contamination),
        random_state,
    )
    t0 = time.perf_counter()
    detector = IsolationForestDetector(
        n_estimators=n_estimators,
        max_samples=max_samples,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    detector.fit(X_train_transformed)
    train_duration_sec = time.perf_counter() - t0
    logger.info("Detector fitted in %.3f seconds.", train_duration_sec)

    # 7. Threshold Calibration on separate Calibration split (benign samples)
    cal_df = partition.calibration_df
    cal_total_count = len(cal_df)
    cal_benign_mask = cal_df["eval_label"].astype(str).str.lower() == "normal"
    cal_benign_df = cal_df[cal_benign_mask]
    cal_benign_count = len(cal_benign_df)

    logger.info(
        "Calibration split total: %d flows | Benign calibration sample: %d flows",
        cal_total_count,
        cal_benign_count,
    )

    cal_features = cal_benign_df[list(feat_df.columns)]
    X_cal_transformed = preprocessor.transform_df(cal_features)
    if list(X_cal_transformed.columns) != expected_features:
        X_cal_transformed = X_cal_transformed[expected_features]

    cal_scores = detector.score_samples(X_cal_transformed)
    calibrated_threshold = detector.calibrate_threshold(cal_scores, quantile=calibration_quantile)
    logger.info(
        "Calibrated decision threshold at %.4f quantile: %.6f (score range on cal benign: [%.6f, %.6f])",
        calibration_quantile,
        calibrated_threshold,
        float(np.min(cal_scores)),
        float(np.max(cal_scores)),
    )

    # 8. Atomic save to temporary files first
    output_model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_model_path = output_model_path.with_suffix(".tmp.joblib")
    temp_json_path = output_model_path.with_suffix(".tmp.json")

    threshold_config = {
        "method": "empirical_quantile_on_benign_calibration",
        "quantile": calibration_quantile,
        "calibration_sample_count": cal_benign_count,
        "calibration_min_score": round(float(np.min(cal_scores)), 6),
        "calibration_max_score": round(float(np.max(cal_scores)), 6),
        "calibration_mean_score": round(float(np.mean(cal_scores)), 6),
        "calibrated_threshold": round(float(calibrated_threshold), 6),
    }

    extra_metadata = {
        "model_role": "unsupervised_anomaly_detector",
        "dataset": "UNSW-NB15",
        "training_split": "Day1_Chronological_Train_Benign_Only",
        "training_sample_count": train_benign_count,
        "training_total_train_partition": train_total_count,
        "training_duration_seconds": round(train_duration_sec, 3),
        "score_direction": "higher_is_more_anomalous (anomaly_score = -raw_score)",
        "preprocessor_sha256": prep_hash,
        "features": expected_features,
        "system_environment": {
            "os": platform.platform(),
            "python_version": platform.python_version(),
            "scikit_learn_version": sklearn.__version__,
        },
        "scientific_disclosures": {
            "interpretation": "Statistical novelty / out-of-distribution deviation indicator; does not represent confirmed malicious exploit.",
            "unsupervised_guarantee": "No test labels or evaluation outcomes used during training or threshold calibration.",
        },
    }

    # Save to temp
    save_detector(
        detector=detector,
        filepath=temp_model_path,
        preprocessor_artifact_ref="artifacts/models/production_preprocessor.joblib",
        threshold_config=threshold_config,
        metadata=extra_metadata,
    )

    # Correct artifact_file name in temp json manifest before rename
    if temp_json_path.exists():
        manifest_obj = json.loads(temp_json_path.read_text(encoding="utf-8"))
        manifest_obj["artifact_file"] = output_model_path.name
        temp_json_path.write_text(json.dumps(manifest_obj, indent=2), encoding="utf-8")

    # 9. Verify loaded temp artifact integrity
    loaded_detector, loaded_manifest = load_detector(temp_model_path, verify_checksum=True)
    test_score = loaded_detector.score_samples(X_cal_transformed.iloc[:5])
    if len(test_score) != 5 or not np.all(np.isfinite(test_score)):
        raise RuntimeError("Validation scoring on loaded temporary artifact failed!")

    # 10. Atomic rename into destination paths
    if temp_model_path.exists():
        temp_model_path.replace(output_model_path)
    if temp_json_path.exists():
        temp_json_path.replace(output_json_path)

    final_model_hash = compute_sha256(output_model_path)
    final_json_hash = compute_sha256(output_json_path)
    logger.info("Successfully published %s (SHA-256: %s)", output_model_path, final_model_hash)
    logger.info("Successfully published %s (SHA-256: %s)", output_json_path, final_json_hash)

    # 11. Final post-flight integrity check on frozen artifacts
    verify_frozen_artifacts()

    return {
        "model_path": str(output_model_path),
        "manifest_path": str(output_json_path),
        "model_sha256": final_model_hash,
        "manifest_sha256": final_json_hash,
        "training_samples": train_benign_count,
        "calibration_samples": cal_benign_count,
        "calibrated_threshold": calibrated_threshold,
        "features": expected_features,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train production Isolation Forest detector for TrafficShield.")
    parser.add_argument("--raw-dir", default="datasets/raw/unsw_nb15", help="Path to raw UNSW-NB15 CSV files.")
    parser.add_argument("--max-rows", type=int, default=100_000, help="Maximum Day 1 rows to process.")
    parser.add_argument("--n-estimators", type=int, default=100, help="Number of trees in forest.")
    parser.add_argument("--quantile", type=float, default=0.99, help="Calibration threshold quantile.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed.")
    args = parser.parse_args()

    results = train_production_isolation_forest(
        raw_dir=args.raw_dir,
        max_day1_rows=args.max_rows,
        n_estimators=args.n_estimators,
        calibration_quantile=args.quantile,
        random_state=args.seed,
    )
    print("\n--- Training Results Summary ---")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
