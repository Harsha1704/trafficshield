"""
Unit Tests for Explainability Engine
====================================
Version: 1.0 (Milestone Sprint)
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from ml.explainability import FlowExplainer


def test_flow_explainer_fallback() -> None:
    """Verify flow explainer generates feature deviations."""
    feat_names = ["duration_seconds", "fwd_bytes", "sttl", "sload"]
    X = np.random.randn(50, 4)
    y = np.random.randint(0, 2, size=50)

    rf = RandomForestClassifier(n_estimators=10, random_state=42)
    rf.fit(X, y)

    explainer = FlowExplainer(model=rf, feature_names=feat_names)
    sample_flow = np.array([0.5, 5000.0, 254.0, 1000000.0])

    attributions = explainer.explain_flow(sample_flow, top_k=3)
    assert isinstance(attributions, list)
    assert len(attributions) <= 3
    for attr in attributions:
        assert "feature" in attr
        assert "shap_impact" in attr
        assert attr["feature"] in feat_names
