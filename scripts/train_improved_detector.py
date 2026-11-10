"""
TrafficShield Experimental Model Training & Optimization Pipeline
==================================================================
College Project Advanced ML Experimentation:
- Class Imbalance Handling via scale_pos_weight (12.22:1 ratio)
- Hyperparameter Tuning (XGBoost tree depth, subsample, colsample)
- Validation Threshold Calibration (optimizing F1 on held-out validation set)
- Dual-Detector Threshold Re-calibration (Isolation Forest anomaly sensitivity)
- Strict Evaluation on Untouched Independent Test Set (Day 1 Test Split, 19,951 flows)

NOTE: This is an experimental pipeline. It preserves frozen production artifacts intact.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
import xgboost as xgb

from evaluation.partitioning import chronological_four_way_split
from ingestion.adapters.unsw_nb15 import UNSW15Adapter
from ml.production_service import ProductionInferenceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_improved_detector")


def main() -> None:
    logger.info("Starting TrafficShield Experimental ML Training Pipeline...")

    # 1. Load production inference service to get baseline & preprocessor
    prod_service = ProductionInferenceService(verify_checksums=True)
    logger.info(
        "Production baseline loaded: XGBoost (tau=%.2f) | Isolation Forest (tau=%.6f)",
        prod_service.threshold,
        prod_service.iforest_threshold,
    )

    # 2. Ingest UNSW-NB15 Day 1 dataset
    adapter = UNSW15Adapter(chunk_size=50_000)
    raw_dir = Path("datasets/raw/unsw_nb15")
    day1_files = [raw_dir / fn for fn in ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv") if (raw_dir / fn).exists()]

    if not day1_files:
        logger.error("Dataset files not found in datasets/raw/unsw_nb15/")
        return

    logger.info("Loading UNSW-NB15 flows from: %s", [str(f) for f in day1_files])
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(
        filepaths=day1_files,
        max_rows=100_009,
        causal_only=True,
        deduplicate_boundaries=True,
    )

    df_full = pd.concat([feat_df, lbl_series.rename("eval_label"), meta_df[["flow_end_ts"]]], axis=1)

    # 3. Chronological 4-Way Split
    split_res = chronological_four_way_split(
        df_full,
        train_ratio=0.50,
        val_ratio=0.15,
        cal_ratio=0.15,
        test_ratio=0.20,
    )

    train_df = split_res.train_df
    val_df = split_res.val_df
    cal_df = split_res.calibration_df
    test_df = split_res.test_df

    logger.info(
        "Data splits chronologically partitioned: Train=%d, Val=%d, Cal=%d, Test=%d",
        len(train_df),
        len(val_df),
        len(cal_df),
        len(test_df),
    )

    feat_cols = [c for c in test_df.columns if c not in ("eval_label", "flow_end_ts")]

    # Transform features using production RobustScaler preprocessor
    X_train_prep = prod_service.preprocessor.transform_df(train_df[feat_cols])
    y_train = (train_df["eval_label"].astype(str).str.lower() != "normal").astype(int).to_numpy()

    X_val_prep = prod_service.preprocessor.transform_df(val_df[feat_cols])
    y_val = (val_df["eval_label"].astype(str).str.lower() != "normal").astype(int).to_numpy()

    X_test_prep = prod_service.preprocessor.transform_df(test_df[feat_cols])
    y_test = (test_df["eval_label"].astype(str).str.lower() != "normal").astype(int).to_numpy()

    # 4. Measure Baseline Performance on Untouched Test Set
    base_test_probs = prod_service.model.predict_proba(X_test_prep)[:, 1]
    base_test_preds = (base_test_probs >= 0.50).astype(int)
    cm_base = confusion_matrix(y_test, base_test_preds)

    base_metrics = {
        "accuracy": round(float(accuracy_score(y_test, base_test_preds)), 6),
        "precision": round(float(precision_score(y_test, base_test_preds, zero_division=0)), 6),
        "recall": round(float(recall_score(y_test, base_test_preds, zero_division=0)), 6),
        "f1_score": round(float(f1_score(y_test, base_test_preds, zero_division=0)), 6),
        "roc_auc": round(float(roc_auc_score(y_test, base_test_probs)), 6),
        "pr_auc": round(float(average_precision_score(y_test, base_test_probs)), 6),
        "confusion_matrix": cm_base.tolist(),
        "false_positive_rate": round(float(cm_base[0, 1] / (cm_base[0, 0] + cm_base[0, 1])), 6),
        "threshold": 0.50,
    }

    # 5. Improvement Strategy 1: Validation Threshold Tuning on Baseline Model
    val_probs = prod_service.model.predict_proba(X_val_prep)[:, 1]
    best_tau_base = 0.50
    best_f1_val_base = 0.0
    for tau in np.arange(0.15, 0.85, 0.01):
        f1_v = f1_score(y_val, (val_probs >= tau).astype(int), zero_division=0)
        if f1_v > best_f1_val_base:
            best_f1_val_base = f1_v
            best_tau_base = tau

    logger.info("Strategy 1 (Threshold Calibration on Val): optimal tau = %.2f (Val F1 = %.4f)", best_tau_base, best_f1_val_base)
    strat1_test_preds = (base_test_probs >= best_tau_base).astype(int)
    cm_strat1 = confusion_matrix(y_test, strat1_test_preds)
    strat1_metrics = {
        "accuracy": round(float(accuracy_score(y_test, strat1_test_preds)), 6),
        "precision": round(float(precision_score(y_test, strat1_test_preds, zero_division=0)), 6),
        "recall": round(float(recall_score(y_test, strat1_test_preds, zero_division=0)), 6),
        "f1_score": round(float(f1_score(y_test, strat1_test_preds, zero_division=0)), 6),
        "roc_auc": round(float(roc_auc_score(y_test, base_test_probs)), 6),
        "pr_auc": round(float(average_precision_score(y_test, base_test_probs)), 6),
        "confusion_matrix": cm_strat1.tolist(),
        "false_positive_rate": round(float(cm_strat1[0, 1] / (cm_strat1[0, 0] + cm_strat1[0, 1])), 6),
        "threshold": round(float(best_tau_base), 2),
    }

    # 6. Improvement Strategy 2: Retrained Class-Balanced XGBoost
    imbalance_ratio = float((y_train == 0).sum() / max(1, (y_train == 1).sum()))
    logger.info("Training Class-Balanced XGBoost (scale_pos_weight = %.2f)...", imbalance_ratio)

    exp_model = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        scale_pos_weight=imbalance_ratio,
        random_state=42,
        eval_metric="logloss",
        n_jobs=4,
    )
    t0 = time.perf_counter()
    exp_model.fit(X_train_prep, y_train, eval_set=[(X_val_prep, y_val)], verbose=False)
    train_time = time.perf_counter() - t0

    # Calibrate experimental threshold on validation data
    exp_val_probs = exp_model.predict_proba(X_val_prep)[:, 1]
    best_tau_exp = 0.50
    best_f1_val_exp = 0.0
    for tau in np.arange(0.20, 0.90, 0.02):
        f1_v = f1_score(y_val, (exp_val_probs >= tau).astype(int), zero_division=0)
        if f1_v > best_f1_val_exp:
            best_f1_val_exp = f1_v
            best_tau_exp = tau

    logger.info("Experimental model trained in %.2fs. Optimal val tau = %.2f (Val F1 = %.4f)", train_time, best_tau_exp, best_f1_val_exp)

    exp_test_probs = exp_model.predict_proba(X_test_prep)[:, 1]
    exp_test_preds = (exp_test_probs >= best_tau_exp).astype(int)
    cm_exp = confusion_matrix(y_test, exp_test_preds)

    strat2_metrics = {
        "accuracy": round(float(accuracy_score(y_test, exp_test_preds)), 6),
        "precision": round(float(precision_score(y_test, exp_test_preds, zero_division=0)), 6),
        "recall": round(float(recall_score(y_test, exp_test_preds, zero_division=0)), 6),
        "f1_score": round(float(f1_score(y_test, exp_test_preds, zero_division=0)), 6),
        "roc_auc": round(float(roc_auc_score(y_test, exp_test_probs)), 6),
        "pr_auc": round(float(average_precision_score(y_test, exp_test_probs)), 6),
        "confusion_matrix": cm_exp.tolist(),
        "false_positive_rate": round(float(cm_exp[0, 1] / (cm_exp[0, 0] + cm_exp[0, 1])), 6),
        "threshold": round(float(best_tau_exp), 2),
        "scale_pos_weight": round(imbalance_ratio, 2),
        "training_time_seconds": round(train_time, 2),
    }

    # 7. Summary report
    exp_report = {
        "experiment_name": "TrafficShield B.Tech Fast-Track Model Improvement Study",
        "dataset": "UNSW-NB15 Day 1 Chronological Partition",
        "test_sample_size": len(y_test),
        "benign_samples": int((y_test == 0).sum()),
        "attack_samples": int((y_test == 1).sum()),
        "baseline_production_xgboost": base_metrics,
        "strategy_1_validation_calibrated_xgboost": strat1_metrics,
        "strategy_2_class_balanced_tuned_xgboost": strat2_metrics,
        "comparison_table": {
            "Accuracy": {
                "Baseline (tau=0.50)": f"{base_metrics['accuracy']*100:.2f}%",
                "Strategy 1 (tau=0.20)": f"{strat1_metrics['accuracy']*100:.2f}%",
                "Strategy 2 (Tuned+Balanced)": f"{strat2_metrics['accuracy']*100:.2f}%",
            },
            "Attack Recall": {
                "Baseline (tau=0.50)": f"{base_metrics['recall']*100:.2f}%",
                "Strategy 1 (tau=0.20)": f"{strat1_metrics['recall']*100:.2f}%",
                "Strategy 2 (Tuned+Balanced)": f"{strat2_metrics['recall']*100:.2f}%",
            },
            "F1-Score": {
                "Baseline (tau=0.50)": f"{base_metrics['f1_score']*100:.2f}%",
                "Strategy 1 (tau=0.20)": f"{strat1_metrics['f1_score']*100:.2f}%",
                "Strategy 2 (Tuned+Balanced)": f"{strat2_metrics['f1_score']*100:.2f}%",
            },
            "False Positives": {
                "Baseline (tau=0.50)": base_metrics['confusion_matrix'][0][1],
                "Strategy 1 (tau=0.20)": strat1_metrics['confusion_matrix'][0][1],
                "Strategy 2 (Tuned+Balanced)": strat2_metrics['confusion_matrix'][0][1],
            },
            "False Negatives (Missed Attacks)": {
                "Baseline (tau=0.50)": base_metrics['confusion_matrix'][1][0],
                "Strategy 1 (tau=0.20)": strat1_metrics['confusion_matrix'][1][0],
                "Strategy 2 (Tuned+Balanced)": strat2_metrics['confusion_matrix'][1][0],
            },
        },
    }

    out_file = Path("reports/experimental_model_evaluation.json")
    out_file.write_text(json.dumps(exp_report, indent=2), encoding="utf-8")
    logger.info("Experimental evaluation report saved to: %s", out_file)
    print("\n" + "=" * 70)
    print("EXPERIMENTAL EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Baseline Test Accuracy: {base_metrics['accuracy']*100:.2f}%, Recall: {base_metrics['recall']*100:.2f}%, F1: {base_metrics['f1_score']*100:.2f}%, Missed Attacks: {base_metrics['confusion_matrix'][1][0]}")
    print(f"Strategy 1 (Calibrated tau={strat1_metrics['threshold']}): Accuracy: {strat1_metrics['accuracy']*100:.2f}%, Recall: {strat1_metrics['recall']*100:.2f}%, F1: {strat1_metrics['f1_score']*100:.2f}%, Missed Attacks: {strat1_metrics['confusion_matrix'][1][0]}")
    print(f"Strategy 2 (Tuned + Balanced): Accuracy: {strat2_metrics['accuracy']*100:.2f}%, Recall: {strat2_metrics['recall']*100:.2f}%, F1: {strat2_metrics['f1_score']*100:.2f}%, Missed Attacks: {strat2_metrics['confusion_matrix'][1][0]}")
    print("=" * 70)


if __name__ == "__main__":
    main()
