"""
Leakage-Safe Model Evaluator
============================
Version: 1.0 (Milestone 5)

Orchestrates the complete label-blind training, threshold calibration, and
held-out testing workflow for TrafficShield detectors.

Strict Guarantees:
1. Training: Preprocessor and detector fit exclusively on training partition without labels.
2. Calibration: Threshold derived exclusively from unlabelled calibration scores.
3. Testing: Predictions generated using frozen threshold before ground-truth labels are joined.
"""
from __future__ import annotations

import logging

from detection.base import BaseDetector
from detection.threshold import compute_quantile_threshold
from evaluation.metrics import (
    compute_binary_metrics,
    compute_per_category_metrics,
    compute_ranking_metrics,
    compute_temporal_alert_metrics,
)
from evaluation.partitioning import ChronologicalPartition
from evaluation.report import EvaluationReport
from evaluation.threshold_analysis import evaluate_threshold_sweep
from features.engineering import extract_features_and_labels
from features.policy import PolicyViolationError, audit_columns
from preprocessing.pipeline import TrafficShieldPreprocessor

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """
    Standardized evaluator executing the label-blind training and evaluation protocol.
    """

    def __init__(
        self,
        detector: BaseDetector,
        preprocessor: TrafficShieldPreprocessor | None = None,
    ) -> None:
        self.detector = detector
        self.preprocessor = preprocessor or TrafficShieldPreprocessor(scaler="standard")

    def evaluate_partition(
        self,
        partition: ChronologicalPartition,
        quantile: float = 0.99,
        label_col: str = "eval_label",
        benign_label: str = "background",
        dataset_name: str = "synthetic",
        manifest_ref: str | None = None,
    ) -> EvaluationReport:
        """
        Execute the leak-free evaluation lifecycle across the chronological partition.

        Parameters
        ----------
        partition : ChronologicalPartition containing train_df, calibration_df, test_df
        quantile : empirical calibration percentile for decision threshold (default: 0.99)
        label_col : column holding evaluation labels in the dataset
        benign_label : value representing normal traffic (default: 'background')
        dataset_name : dataset identifier string
        manifest_ref : optional path or identifier to provenance manifest

        Returns
        -------
        EvaluationReport detailing performance metrics and threshold audit.
        """
        # Audit: verify no forbidden reverse-dependent columns exist in any partition
        for part_name, part_df in (
            ("train", partition.train_df),
            ("calibration", partition.calibration_df),
            ("test", partition.test_df),
        ):
            if not part_df.empty:
                audit = audit_columns(list(part_df.columns))
                if audit.forbidden_violations:
                    raise PolicyViolationError(
                        f"Forbidden reverse-dependent columns detected in {part_name} partition: "
                        f"{audit.forbidden_violations}"
                    )

        # ── 1. Training Phase (Fit Preprocessor & Detector on Train Only) ────────
        train_features, train_labels, _ = extract_features_and_labels(partition.train_df)

        # Audit: verify train_features contains no label columns
        assert label_col not in train_features.columns, f"Leakage: {label_col} in training features!"

        self.preprocessor.fit(train_features)
        x_train = self.preprocessor.transform_df(train_features)

        self.detector.fit(x_train)

        # ── 2. Calibration Phase (Derive Frozen Threshold Without Labels) ────────
        cal_features, _, _ = extract_features_and_labels(partition.calibration_df)
        x_cal = self.preprocessor.transform_df(cal_features)

        if hasattr(self.detector, "calibrate_ensemble"):
            cal_scores = self.detector.calibrate_ensemble(x_cal)
        else:
            cal_scores = self.detector.score_samples(x_cal)
        frozen_thresh = compute_quantile_threshold(cal_scores, quantile=quantile)
        self.detector.set_threshold(frozen_thresh)

        # ── 3. Testing Phase (Score Test Observations with Frozen Parameters) ────
        test_features, test_labels_raw, _ = extract_features_and_labels(partition.test_df)
        x_test = self.preprocessor.transform_df(test_features)

        test_scores = self.detector.score_samples(x_test)
        test_preds = self.detector.predict(x_test)

        # ── 4. Ground-Truth Joining & Metric Evaluation (POST-PREDICTION ONLY) ──
        # Extract binary attack labels from test set
        if test_labels_raw is not None:
            raw_labels_series = test_labels_raw
        elif label_col in partition.test_df.columns:
            raw_labels_series = partition.test_df[label_col]
        else:
            raise KeyError(f"Evaluation label column '{label_col}' not found in test partition.")

        y_test = (raw_labels_series.astype(str) != benign_label).astype(int)

        # Compute metric groups
        binary_metrics = compute_binary_metrics(y_true=y_test, y_pred=test_preds)
        ranking_metrics = compute_ranking_metrics(y_true=y_test, y_scores=test_scores)
        category_metrics = compute_per_category_metrics(
            y_true_labels=raw_labels_series,
            y_pred=test_preds,
            benign_label=benign_label,
        )

        ts_col = partition.timestamp_col
        if ts_col in partition.test_df.columns:
            temporal_metrics = compute_temporal_alert_metrics(
                timestamps=partition.test_df[ts_col],
                y_pred=test_preds,
            )
        else:
            temporal_metrics = {
                "total_alerts": int(test_preds.sum()),
                "interval_freq": "N/A",
                "alerts_per_interval_mean": None,
                "alerts_per_interval_max": None,
            }

        # Threshold sweep across multiple quantiles
        sweep = evaluate_threshold_sweep(
            calibration_scores=cal_scores,
            test_scores=test_scores,
            test_labels=y_test,
        )

        warnings: list[str] = []
        if ranking_metrics.get("warning"):
            warnings.append(ranking_metrics["warning"])
        if binary_metrics["undefined_metrics"]:
            warnings.append(f"Undefined metrics due to zero denominator: {binary_metrics['undefined_metrics']}")

        # Distribution shift warning
        cal_target_fpr = round(1.0 - quantile, 6)
        obs_fpr = binary_metrics["false_positive_rate"]
        if obs_fpr is not None and abs(obs_fpr - cal_target_fpr) > 0.05:
            warnings.append(
                f"Distribution shift detected: test FPR ({obs_fpr:.4f}) diverged from "
                f"calibration target ({cal_target_fpr:.4f}) by > 5%."
            )

        report = EvaluationReport(
            detector_type=self.detector.__class__.__name__,
            detector_parameters=self.detector.get_params(),
            feature_names=self.preprocessor.feature_names_out_,
            train_count=partition.train_count,
            calibration_count=partition.calibration_count,
            test_count=partition.test_count,
            train_time_range=partition.train_time_range,
            calibration_time_range=partition.calibration_time_range,
            test_time_range=partition.test_time_range,
            threshold_method="calibration_quantile",
            threshold_value=frozen_thresh,
            target_calibration_quantile=quantile,
            binary_metrics=binary_metrics,
            ranking_metrics=ranking_metrics,
            category_metrics=category_metrics,
            temporal_metrics=temporal_metrics,
            threshold_sweep=sweep,
            dataset_name=dataset_name,
            manifest_ref=manifest_ref,
            warnings=warnings,
        )

        return report
