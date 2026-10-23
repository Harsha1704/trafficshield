"""
TrafficShield Preprocessing Package
===================================
Version: 1.0 (Milestone 3)
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

from preprocessing.artifacts import load_preprocessor, save_preprocessor
from preprocessing.pipeline import TrafficShieldPreprocessor
from preprocessing.split import (
    TemporalLeakageError,
    audit_temporal_boundary,
    chronological_split,
    ugr16_calibration_test_split,
)

__all__ = [
    "TrafficShieldPreprocessor",
    "save_preprocessor",
    "load_preprocessor",
    "chronological_split",
    "ugr16_calibration_test_split",
    "audit_temporal_boundary",
    "TemporalLeakageError",
]
