"""
TrafficShield Anomaly Detection Package
=======================================
Version: 1.0 (Milestone 4)
"""
from __future__ import annotations

import sys
import types

# Windows Smart App Control / WDAC compatibility guard:
# Safely stub unused internal C-extension solvers (_sag_fast) if blocked by host code-integrity policy
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        _mock_sag.sag64 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

from detection.artifacts import load_detector, save_detector
from detection.autoencoder import AutoencoderDetector
from detection.base import BaseDetector
from detection.ensemble import (
    BaseScoreNormalizer,
    CalibratedEnsembleDetector,
    EmpiricalPercentileNormalizer,
    RobustMinMaxNormalizer,
)
from detection.hdbscan_detector import HDBSCANDetector
from detection.isolation_forest import IsolationForestDetector
from detection.lof import LOFDetector
from detection.statistical import RobustStatisticalDetector
from detection.threshold import (
    ThresholdConfig,
    ThresholdStrategy,
    compute_quantile_threshold,
    create_threshold_config,
)

__all__ = [
    "BaseDetector",
    "RobustStatisticalDetector",
    "IsolationForestDetector",
    "LOFDetector",
    "HDBSCANDetector",
    "AutoencoderDetector",
    "CalibratedEnsembleDetector",
    "BaseScoreNormalizer",
    "EmpiricalPercentileNormalizer",
    "RobustMinMaxNormalizer",
    "ThresholdStrategy",
    "ThresholdConfig",
    "compute_quantile_threshold",
    "create_threshold_config",
    "save_detector",
    "load_detector",
]
