"""
Machine-Readable Evaluation Reports
====================================
Version: 1.0 (Milestone 5)

Generates structured JSON reports and CSV summaries of anomaly detector evaluation
without including sensitive packet contents or source IPs.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from features.policy import FEATURE_POLICY_VERSION

logger = logging.getLogger(__name__)


@dataclass
class EvaluationReport:
    """Structured, reproducible evaluation report for TrafficShield detectors."""
    detector_type: str
    detector_parameters: dict[str, Any]
    feature_names: list[str]

    # Partition statistics
    train_count: int
    calibration_count: int
    test_count: int
    train_time_range: tuple[str | None, str | None]
    calibration_time_range: tuple[str | None, str | None]
    test_time_range: tuple[str | None, str | None]

    # Threshold configuration
    threshold_method: str
    threshold_value: float
    target_calibration_quantile: float | None

    # Performance metrics
    binary_metrics: dict[str, Any]
    ranking_metrics: dict[str, Any]
    category_metrics: dict[str, dict[str, Any]]
    temporal_metrics: dict[str, Any]
    threshold_sweep: list[dict[str, Any]]

    # Metadata & environment
    dataset_name: str = "synthetic"
    manifest_ref: str | None = None
    feature_policy_version: str = FEATURE_POLICY_VERSION
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return asdict(self)

    def to_json(self, filepath: str | Path, indent: int = 2) -> Path:
        """Write machine-readable JSON report."""
        out_path = Path(filepath).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.to_dict(), indent=indent, default=str), encoding="utf-8")
        logger.info("Evaluation JSON report saved to %s", out_path)
        return out_path

    def to_csv_summary(self, filepath: str | Path) -> Path:
        """Write key summary metrics to a flat CSV file."""
        out_path = Path(filepath).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        rows = [
            ("Metric / Attribute", "Value"),
            ("Detector Type", self.detector_type),
            ("Feature Policy Version", self.feature_policy_version),
            ("Dataset Name", self.dataset_name),
            ("Train Samples", str(self.train_count)),
            ("Calibration Samples", str(self.calibration_count)),
            ("Test Samples", str(self.test_count)),
            ("Threshold Value", str(self.threshold_value)),
            ("Threshold Method", self.threshold_method),
            ("Target Calibration Quantile", str(self.target_calibration_quantile or "N/A")),
            ("True Positives (TP)", str(self.binary_metrics.get("true_positives"))),
            ("False Positives (FP)", str(self.binary_metrics.get("false_positives"))),
            ("True Negatives (TN)", str(self.binary_metrics.get("true_negatives"))),
            ("False Negatives (FN)", str(self.binary_metrics.get("false_negatives"))),
            ("Precision", str(self.binary_metrics.get("precision"))),
            ("Recall", str(self.binary_metrics.get("recall"))),
            ("Specificity", str(self.binary_metrics.get("specificity"))),
            ("False Positive Rate (FPR)", str(self.binary_metrics.get("false_positive_rate"))),
            ("F1 Score", str(self.binary_metrics.get("f1_score"))),
            ("Balanced Accuracy", str(self.binary_metrics.get("balanced_accuracy"))),
            ("ROC-AUC", str(self.ranking_metrics.get("roc_auc"))),
            ("Average Precision (PR-AUC)", str(self.ranking_metrics.get("average_precision"))),
            ("Flagged Percentage (%)", str(self.binary_metrics.get("flagged_percentage"))),
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        logger.info("Evaluation CSV summary saved to %s", out_path)
        return out_path
