"""
TrafficShield Evaluation Package
================================
Version: 1.0 (Milestone 5)
"""
from evaluation.evaluator import ModelEvaluator
from evaluation.metrics import (
    compute_binary_metrics,
    compute_per_category_metrics,
    compute_ranking_metrics,
    compute_temporal_alert_metrics,
)
from evaluation.partitioning import (
    ChronologicalPartition,
    chronological_three_way_split,
    ugr16_three_way_split,
)
from evaluation.report import EvaluationReport
from evaluation.threshold_analysis import evaluate_threshold_sweep

__all__ = [
    "ChronologicalPartition",
    "chronological_three_way_split",
    "ugr16_three_way_split",
    "compute_binary_metrics",
    "compute_ranking_metrics",
    "compute_per_category_metrics",
    "compute_temporal_alert_metrics",
    "evaluate_threshold_sweep",
    "EvaluationReport",
    "ModelEvaluator",
]
