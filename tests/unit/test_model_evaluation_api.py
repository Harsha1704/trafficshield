"""
Unit Tests for Model Performance & Evaluation REST API
======================================================
Version: 1.0 (Milestone Sprint)

Validates:
1. GET /api/v1/model/evaluation endpoint returns HTTP 200 and success envelope.
2. Production model contract, version, algorithm family, and threshold 0.50.
3. Cryptographic SHA-256 artifact integrity matches canonical baseline.
4. Mathematical consistency of confusion matrix: TN + FP + FN + TP == Total.
5. Accuracy, Precision, Recall, Specificity, F1 calculations match matrix counts.
6. Attack category breakdown accounting matches 5,858 held-out test attacks.
7. Candidate model tournament ledger presence and structure.
8. Methodological disclosures and causal policy definitions.
"""
from __future__ import annotations

import math


def test_model_evaluation_endpoint_success(client) -> None:
    """Verify GET /api/v1/model/evaluation returns 200 with complete schema."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    data = body["data"]

    # Verify top-level sections
    assert "production_model" in data
    assert "evaluation_provenance" in data
    assert "operational_metrics" in data
    assert "confusion_matrix" in data
    assert "optimal_tournament_metrics" in data
    assert "temporal_holdout_metrics" in data
    assert "category_metrics" in data
    assert "comparison_models" in data
    assert "methodology_and_limitations" in data


def test_production_model_contract_and_integrity(client) -> None:
    """Verify production model specifications and frozen SHA-256 baselines."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    prod = resp.get_json()["data"]["production_model"]

    assert prod["model_name"] == "OptunaTuned_XGBoost"
    assert prod["model_version"] == "1.0.0"
    assert prod["decision_threshold"] == 0.50
    assert prod["status"] == "ACTIVE_PRODUCTION"
    assert prod["feature_count"] == 13
    assert len(prod["required_features"]) == 10
    assert len(prod["engineered_features"]) == 3

    integrity = prod["artifact_integrity"]
    assert integrity["verified"] is True
    assert integrity["detector_sha256"] == "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
    assert integrity["preprocessor_sha256"] == "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"
    assert integrity["metadata_sha256"] == "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1"


def test_confusion_matrix_arithmetic_consistency(client) -> None:
    """Verify confusion matrix counts sum to exact total flows and metrics match."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    data = resp.get_json()["data"]

    cm = data["confusion_matrix"]
    tn = cm["tn"]
    fp = cm["fp"]
    fn = cm["fn"]
    tp = cm["tp"]
    total = cm["total"]

    assert total == 19942
    assert tn + fp + fn + tp == total
    assert tn == 13836
    assert fp == 248
    assert fn == 130
    assert tp == 5728

    # Arithmetic checks
    computed_acc = (tn + tp) / total
    assert math.isclose(computed_acc, data["operational_metrics"]["accuracy"], abs_tol=1e-4)

    computed_recall = tp / (tp + fn)
    assert math.isclose(computed_recall, data["operational_metrics"]["recall"], abs_tol=1e-4)

    computed_precision = tp / (tp + fp)
    assert math.isclose(computed_precision, data["operational_metrics"]["precision"], abs_tol=1e-4)

    computed_specificity = tn / (tn + fp)
    assert math.isclose(computed_specificity, data["operational_metrics"]["specificity"], abs_tol=1e-4)


def test_attack_category_accounting(client) -> None:
    """Verify per-category breakdown sums to exactly 5,858 test attacks."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    categories = resp.get_json()["data"]["category_metrics"]

    assert len(categories) == 9
    total_attacks = sum(c["test_flows"] for c in categories)
    total_detected = sum(c["detected_tp"] for c in categories)
    total_missed = sum(c["missed_fn"] for c in categories)

    assert total_attacks == 5858
    assert total_detected == 5728
    assert total_missed == 130
    assert total_detected + total_missed == total_attacks

    for cat in categories:
        assert cat["detected_tp"] + cat["missed_fn"] == cat["test_flows"]
        expected_recall = round(cat["detected_tp"] / cat["test_flows"], 4)
        assert math.isclose(cat["recall_rate"], expected_recall, abs_tol=1e-3)


def test_candidate_models_tournament_ledger(client) -> None:
    """Verify tournament candidates list contains both supervised and unsupervised models."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    models = resp.get_json()["data"]["comparison_models"]

    assert len(models) >= 10
    prod_candidates = [m for m in models if m["is_production"]]
    assert len(prod_candidates) == 1
    assert prod_candidates[0]["model_name"] == "OptunaTuned_XGBoost"

    unsupervised = [m for m in models if "unsupervised" in m["model_type"]]
    assert len(unsupervised) >= 4  # Autoencoder, IsolationForest, RobustStatistical, CalibratedEnsemble


def test_scientific_methodology_disclosures(client) -> None:
    """Verify causal observability and impossibility of 100% accuracy disclosures."""
    resp = client.get("/api/v1/model/evaluation")
    assert resp.status_code == 200
    methodology = resp.get_json()["data"]["methodology_and_limitations"]

    assert "unidirectional" in methodology["causal_policy"].lower()
    assert len(methodology["impossibility_of_100_percent"]) >= 4
    assert len(methodology["cross_dataset_boundaries"]) >= 2


def test_missing_artifacts_produce_explicit_integrity_failure(tmp_path) -> None:
    """Verify missing artifacts produce verified=False and FILE_NOT_FOUND instead of masked success."""
    from ml.evaluation_service import ModelEvaluationService

    service = ModelEvaluationService(model_dir=tmp_path)
    report = service.get_evaluation_report()
    integrity = report["production_model"]["artifact_integrity"]

    assert integrity["verified"] is False
    assert integrity["detector_sha256"] == "FILE_NOT_FOUND"
    assert integrity["preprocessor_sha256"] == "FILE_NOT_FOUND"
    assert integrity["metadata_sha256"] == "FILE_NOT_FOUND"

