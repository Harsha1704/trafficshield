"""
Evaluation Command-Line Interface
=================================
Version: 1.0 (Milestone 5)

Evaluates anomaly detectors on prepared datasets and exports JSON/CSV reports.

Usage Examples:
---------------
# Synthetic evaluation demonstration:
python -m evaluation.cli --demo --detector statistical --out-dir reports/m5_demo

# Prepared CSV evaluation:
python -m evaluation.cli \\
    --data datasets/interim/ugr16/ugr16_sample.csv \\
    --detector iforest \\
    --timestamp-col flow_end_ts \\
    --label-col eval_label \\
    --benign-label background \\
    --quantile 0.99 \\
    --out-dir reports/ugr16_eval
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from detection.base import BaseDetector
from detection.isolation_forest import IsolationForestDetector
from detection.statistical import RobustStatisticalDetector
from evaluation.evaluator import ModelEvaluator
from evaluation.partitioning import chronological_three_way_split
from preprocessing.pipeline import TrafficShieldPreprocessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate")


def generate_synthetic_demo_data(n: int = 500) -> pd.DataFrame:
    """Generate synthetic flow records for fast, zero-download demonstrations."""
    np.random.seed(42)
    records = []
    base_ts = datetime(2016, 3, 1, 0, 0, tzinfo=UTC)

    for i in range(n):
        ts = datetime.fromtimestamp(base_ts.timestamp() + i * 180, tz=UTC)
        is_attack = (i >= int(n * 0.85) and i % 5 == 0)
        label = "dos" if is_attack else "background"

        # If attack, inject anomalous burst
        pkts = int(np.random.normal(500.0, 50.0)) if is_attack else int(np.random.normal(15.0, 3.0))
        pkts = max(1, pkts)
        dur = float(np.random.uniform(0.1, 0.5)) if is_attack else float(np.random.uniform(0.5, 2.0))
        bytes_ = pkts * 800 if is_attack else pkts * int(np.random.normal(80.0, 10.0))

        records.append({
            "record_id": f"flow-demo-{i:05d}",
            "flow_end_ts": ts.isoformat(),
            "src_ip": f"10.0.{i // 256}.{i % 256}",
            "dst_ip": "192.168.1.10",
            "src_port": 30000 + (i % 30000),
            "dst_port": 80 if i % 2 == 0 else 443,
            "protocol_name": "TCP",
            "fwd_packets": pkts,
            "fwd_bytes": bytes_,
            "duration_seconds": dur,
            "tcp_flags_raw": ".A..S.",
            "eval_label": label,
        })

    return pd.DataFrame(records)


def run_evaluation(args: argparse.Namespace) -> int:
    """Execute evaluation run based on parsed CLI arguments."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.demo:
        logger.info("Running synthetic evaluation demonstration (500 flows)...")
        df = generate_synthetic_demo_data(n=500)
        dataset_name = "synthetic_demo"
        manifest_ref = "in-memory-demo"
    else:
        if not args.data:
            logger.error("Must provide --data <path> or use --demo for synthetic test.")
            return 1
        data_path = Path(args.data)
        if not data_path.exists():
            logger.error("Dataset not found at: %s", data_path)
            return 1
        logger.info("Loading dataset from: %s", data_path)
        df = pd.read_csv(data_path)
        dataset_name = data_path.stem
        manifest_ref = str(data_path.resolve())

    # Validate essential columns
    if args.timestamp_col not in df.columns:
        logger.error("Timestamp column '%s' not found in dataset.", args.timestamp_col)
        return 1
    if args.label_col not in df.columns:
        logger.error("Label column '%s' not found in dataset.", args.label_col)
        return 1

    # Chronological 3-way partition
    logger.info("Partitioning dataset chronologically (train=60%%, cal=20%%, test=20%%)...")
    partition = chronological_three_way_split(
        df,
        train_ratio=args.train_ratio,
        cal_ratio=args.cal_ratio,
        test_ratio=args.test_ratio,
        timestamp_col=args.timestamp_col,
    )
    logger.info(
        "Partitions: Train=%d, Calibration=%d, Test=%d",
        partition.train_count, partition.calibration_count, partition.test_count,
    )

    # Initialize detector
    detector: BaseDetector
    if args.detector.lower() in ("stat", "statistical", "robust"):
        detector = RobustStatisticalDetector(aggregation=args.stat_agg)
    elif args.detector.lower() in ("iforest", "isolation_forest"):
        detector = IsolationForestDetector(n_estimators=args.if_estimators, random_state=args.seed)
    else:
        logger.error("Unknown detector: %s", args.detector)
        return 1

    preprocessor = TrafficShieldPreprocessor(scaler="standard")
    evaluator = ModelEvaluator(detector=detector, preprocessor=preprocessor)

    logger.info("Executing label-blind evaluation...")
    report = evaluator.evaluate_partition(
        partition=partition,
        quantile=args.quantile,
        label_col=args.label_col,
        benign_label=args.benign_label,
        dataset_name=dataset_name,
        manifest_ref=manifest_ref,
    )

    # Write reports
    json_path = out_dir / f"evaluation_report_{report.detector_type}.json"
    csv_path = out_dir / f"evaluation_summary_{report.detector_type}.csv"
    report.to_json(json_path)
    report.to_csv_summary(csv_path)

    # Print summary
    print("\n" + "=" * 65)
    print(f"TRAFFICSHIELD EVALUATION RESULTS -- {report.detector_type.upper()}")
    print("=" * 65)
    print(f"Dataset:              {report.dataset_name}")
    print(f"Partitions:           Train={report.train_count} | Cal={report.calibration_count} | Test={report.test_count}")
    print(f"Threshold (cal q={report.target_calibration_quantile}): {report.threshold_value:.4f}")
    print("-" * 65)
    bm = report.binary_metrics
    print(f"Precision:            {bm.get('precision') or 'N/A'}")
    print(f"Recall (TPR):         {bm.get('recall') or 'N/A'}")
    print(f"False Positive Rate:  {bm.get('false_positive_rate') or 'N/A'}")
    print(f"F1 Score:             {bm.get('f1_score') or 'N/A'}")
    print(f"Balanced Accuracy:    {bm.get('balanced_accuracy') or 'N/A'}")
    rm = report.ranking_metrics
    print(f"ROC-AUC:              {rm.get('roc_auc') or 'N/A'}")
    print(f"Average Precision:    {rm.get('average_precision') or 'N/A'}")
    print(f"Flagged Records:      {bm.get('flagged_count')} / {report.test_count} ({bm.get('flagged_percentage')}%)")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  [!] {w}")
    print("=" * 65)
    print(f"Full reports written to:\n  - {json_path}\n  - {csv_path}\n")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TrafficShield Leakage-Safe Evaluation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--demo", action="store_true", help="Run fast synthetic evaluation demo")
    parser.add_argument("--data", help="Path to prepared dataset CSV file")
    parser.add_argument("--detector", default="statistical", choices=["statistical", "iforest"],
                        help="Detector to evaluate: 'statistical' or 'iforest'")
    parser.add_argument("--timestamp-col", default="flow_end_ts", help="Timestamp column name")
    parser.add_argument("--label-col", default="eval_label", help="Ground-truth label column")
    parser.add_argument("--benign-label", default="background", help="Label value indicating normal traffic")
    parser.add_argument("--quantile", type=float, default=0.99, help="Empirical calibration quantile threshold (default: 0.99)")
    parser.add_argument("--train-ratio", type=float, default=0.6, help="Train ratio (default: 0.6)")
    parser.add_argument("--cal-ratio", type=float, default=0.2, help="Calibration ratio (default: 0.2)")
    parser.add_argument("--test-ratio", type=float, default=0.2, help="Test ratio (default: 0.2)")
    parser.add_argument("--stat-agg", default="max", choices=["max", "top_k", "mean", "l2"], help="Aggregation for statistical detector")
    parser.add_argument("--if-estimators", type=int, default=100, help="Number of trees for Isolation Forest")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--out-dir", default="reports/evaluation", help="Directory for output reports")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_evaluation(args))


if __name__ == "__main__":
    main()
