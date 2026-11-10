"""
TrafficShield Hybrid ML Evaluation Benchmark
============================================
Evaluates Supervised XGBoost, Unsupervised Isolation Forest, and Hybrid Classification
on the held-out test split of Day 1 (chronological partition) and Day 2 temporal holdout.

Metrics calculated:
- Accuracy, Precision, Recall, Specificity, False Positive Rate (FPR), F1 Score
- ROC-AUC and PR-AUC (where continuous scores are applicable)
- Hybrid classification breakdown against ground truth labels
- Inference latency benchmarks
"""
from __future__ import annotations

import json
import logging
import sys
import time
import types
from pathlib import Path

# Add project root to sys.path
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    confusion_matrix,
    roc_auc_score,
)

from evaluation.partitioning import chronological_four_way_split  # noqa: E402
from ingestion.adapters.unsw_nb15 import UNSW15Adapter  # noqa: E402
from ml.production_service import ProductionInferenceService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_hybrid")


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray | None = None) -> dict[str, float]:
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    n = tn + fp + fn + tp

    acc = float((tp + tn) / n) if n > 0 else 0.0
    prec = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    rec = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    spec = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    f1 = float(2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

    res = {
        "total_samples": int(n),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "accuracy": round(acc, 6),
        "precision": round(prec, 6),
        "recall": round(rec, 6),
        "specificity": round(spec, 6),
        "fpr": round(fpr, 6),
        "f1_score": round(f1, 6),
    }

    if y_score is not None:
        try:
            res["roc_auc"] = round(float(roc_auc_score(y_true, y_score)), 6)
        except Exception:
            res["roc_auc"] = 0.0
        try:
            res["pr_auc"] = round(float(average_precision_score(y_true, y_score)), 6)
        except Exception:
            res["pr_auc"] = 0.0

    return res


def main() -> None:
    logger.info("Initializing ProductionInferenceService...")
    service = ProductionInferenceService(verify_checksums=True)
    logger.info(
        "Models loaded: Supervised %s (tau=%.2f) | Unsupervised %s (tau=%.6f)",
        service.model_name,
        service.threshold,
        service.iforest_name,
        service.iforest_threshold,
    )

    # 1. Load Day 1 test partition
    adapter = UNSW15Adapter(chunk_size=50_000)
    raw_dir = Path("data/raw")
    day1_files = [raw_dir / fn for fn in ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv") if (raw_dir / fn).exists()]
    if not day1_files:
        raw_dir = Path("datasets/raw/unsw_nb15")
        day1_files = [raw_dir / fn for fn in ("UNSW-NB15_1.csv", "UNSW-NB15_2.csv") if (raw_dir / fn).exists()]

    logger.info("Loading Day 1 data from: %s", [str(f) for f in day1_files])
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(
        filepaths=day1_files,
        max_rows=100_009,
        causal_only=True,
        deduplicate_boundaries=True,
    )

    df_full = pd.concat([feat_df, lbl_series.rename("eval_label"), meta_df[["flow_end_ts"]]], axis=1)
    split_res = chronological_four_way_split(
        df_full,
        train_ratio=0.50,
        val_ratio=0.15,
        cal_ratio=0.15,
        test_ratio=0.20,
    )
    df_test = split_res.test_df

    logger.info("Day 1 Test split: %d flows", len(df_test))
    y_test_binary = (df_test["eval_label"].astype(str).str.lower() != "normal").astype(int).to_numpy()

    # Preprocess test features
    feat_cols = [c for c in df_test.columns if c not in ("eval_label", "flow_end_ts")]
    X_test_raw = df_test[feat_cols]
    X_test_prep = service.preprocessor.transform_df(X_test_raw)

    # 2. Supervised XGBoost Inference
    t0 = time.perf_counter()
    xgb_probs = service.model.predict_proba(X_test_prep)[:, 1]
    xgb_latency_us = ((time.perf_counter() - t0) / len(df_test)) * 1_000_000
    xgb_preds = (xgb_probs >= service.threshold).astype(int)

    # 3. Unsupervised Isolation Forest Inference
    t0 = time.perf_counter()
    if_scores = service.iforest.score_samples(X_test_prep)
    if_latency_us = ((time.perf_counter() - t0) / len(df_test)) * 1_000_000
    if_preds = (if_scores >= service.iforest_threshold).astype(int)

    # 4. Hybrid Classification
    hybrid_classifications = []
    for s_pred, u_pred in zip(xgb_preds, if_preds, strict=False):
        if s_pred == 1 and u_pred == 1:
            hybrid_classifications.append("DUAL_CONFIRMED")
        elif s_pred == 1 and u_pred == 0:
            hybrid_classifications.append("SUPERVISED_ONLY_ALERT")
        elif s_pred == 0 and u_pred == 1:
            hybrid_classifications.append("UNSUPERVISED_NOVELTY")
        else:
            hybrid_classifications.append("NORMAL_TRAFFIC")

    hybrid_series = pd.Series(hybrid_classifications)

    # 5. Compute performance metrics
    xgb_metrics = compute_metrics(y_test_binary, xgb_preds, xgb_probs)
    xgb_metrics["latency_us_per_flow"] = round(xgb_latency_us, 2)

    if_metrics = compute_metrics(y_test_binary, if_preds, if_scores)
    if_metrics["latency_us_per_flow"] = round(if_latency_us, 2)

    # Hybrid breakdown against ground truth
    breakdown = {}
    for cat in ["DUAL_CONFIRMED", "SUPERVISED_ONLY_ALERT", "UNSUPERVISED_NOVELTY", "NORMAL_TRAFFIC"]:
        mask = hybrid_series == cat
        total_in_cat = int(mask.sum())
        attacks_in_cat = int(y_test_binary[mask].sum()) if total_in_cat > 0 else 0
        benign_in_cat = total_in_cat - attacks_in_cat
        breakdown[cat] = {
            "total_count": total_in_cat,
            "pct_of_test_split": round((total_in_cat / len(df_test)) * 100, 2),
            "ground_truth_attacks": attacks_in_cat,
            "ground_truth_benign": benign_in_cat,
            "attack_precision": round(attacks_in_cat / total_in_cat, 4) if total_in_cat > 0 else 0.0,
        }

    # 6. Optional Day 2 Temporal Holdout Evaluation (UNSW-NB15_3.csv)
    d2_file = Path("datasets/raw/unsw_nb15/UNSW-NB15_3.csv")
    d2_report = None
    if d2_file.exists():
        logger.info("Evaluating Day 2 Out-of-Distribution Temporal Holdout from: %s", d2_file)
        d2_feat, d2_lbl, _ = adapter.load_unidirectional_dataframe(
            filepaths=[d2_file],
            max_rows=20_000,
            causal_only=True,
            deduplicate_boundaries=False,
        )
        d2_y = (d2_lbl.astype(str).str.lower() != "normal").astype(int).to_numpy()
        d2_prep = service.preprocessor.transform_df(d2_feat)

        d2_xgb_probs = service.model.predict_proba(d2_prep)[:, 1]
        d2_xgb_preds = (d2_xgb_probs >= service.threshold).astype(int)
        d2_xgb_metrics = compute_metrics(d2_y, d2_xgb_preds, d2_xgb_probs)

        d2_if_scores = service.iforest.score_samples(d2_prep)
        d2_if_preds = (d2_if_scores >= service.iforest_threshold).astype(int)
        d2_if_metrics = compute_metrics(d2_y, d2_if_preds, d2_if_scores)

        d2_hybrid = []
        for s_p, u_p in zip(d2_xgb_preds, d2_if_preds, strict=False):
            if s_p == 1 and u_p == 1:
                d2_hybrid.append("DUAL_CONFIRMED")
            elif s_p == 1 and u_p == 0:
                d2_hybrid.append("SUPERVISED_ONLY_ALERT")
            elif s_p == 0 and u_p == 1:
                d2_hybrid.append("UNSUPERVISED_NOVELTY")
            else:
                d2_hybrid.append("NORMAL_TRAFFIC")
        d2_h_series = pd.Series(d2_hybrid)

        d2_breakdown = {}
        for cat in ["DUAL_CONFIRMED", "SUPERVISED_ONLY_ALERT", "UNSUPERVISED_NOVELTY", "NORMAL_TRAFFIC"]:
            mask = d2_h_series == cat
            tot = int(mask.sum())
            att = int(d2_y[mask].sum()) if tot > 0 else 0
            d2_breakdown[cat] = {
                "total_count": tot,
                "pct_of_holdout": round((tot / len(d2_y)) * 100, 2),
                "ground_truth_attacks": att,
                "ground_truth_benign": tot - att,
                "attack_precision": round(att / tot, 4) if tot > 0 else 0.0,
            }

        d2_report = {
            "dataset": "UNSW-NB15 Day 2 Cross-File Temporal Holdout (20,000 flows, 24 days later)",
            "total_flows": len(d2_y),
            "ground_truth_benign": int((d2_y == 0).sum()),
            "ground_truth_attacks": int((d2_y == 1).sum()),
            "supervised_xgboost": d2_xgb_metrics,
            "unsupervised_isolation_forest": d2_if_metrics,
            "hybrid_classification_breakdown": d2_breakdown,
        }

    output_report = {
        "dataset": "UNSW-NB15 Day 1 Held-Out Test Split",
        "total_test_flows": len(df_test),
        "ground_truth_benign": int((y_test_binary == 0).sum()),
        "ground_truth_attacks": int((y_test_binary == 1).sum()),
        "supervised_xgboost": xgb_metrics,
        "unsupervised_isolation_forest": if_metrics,
        "hybrid_classification_breakdown": breakdown,
        "day2_temporal_holdout": d2_report,
    }

    print("\n" + "=" * 70)
    print("TRAFFICSHIELD HYBRID ML EVALUATION REPORT")
    print("=" * 70)
    print(f"Test Split Size: {len(df_test):,} flows (Benign: {(y_test_binary == 0).sum():,}, Attack: {(y_test_binary == 1).sum():,})")
    print("\n--- Supervised XGBoost (Threshold = 0.50) ---")
    for k, v in xgb_metrics.items():
        print(f"  {k:20s}: {v}")
    print("\n--- Unsupervised Isolation Forest (Threshold = 0.727896) ---")
    for k, v in if_metrics.items():
        print(f"  {k:20s}: {v}")
    print("\n--- Hybrid Classification Distribution & Precision ---")
    for cat, info in breakdown.items():
        print(f"  [{cat}]")
        print(f"    Count: {info['total_count']:,} ({info['pct_of_test_split']}%)")
        print(f"    Ground Truth Breakdown: {info['ground_truth_attacks']:,} Attacks | {info['ground_truth_benign']:,} Benign")
        print(f"    Empirical Precision: {info['attack_precision'] * 100:.2f}%")
    print("=" * 70)

    # Save to reports
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "hybrid_evaluation_benchmark.json"
    out_file.write_text(json.dumps(output_report, indent=2), encoding="utf-8")
    logger.info("Saved hybrid benchmark report to: %s", out_file)


if __name__ == "__main__":
    main()
