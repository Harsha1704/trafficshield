"""
Comprehensive Hybrid ML Detection System Tests
==============================================
Validates Milestone Phase 2:
1. ProductionInferenceService dual-model loading and cryptographic hash enforcement.
2. Independent scoring: Supervised XGBoost (0.50) & Unsupervised Isolation Forest (0.727896).
3. All four transparent hybrid classifications:
   - DUAL_CONFIRMED
   - SUPERVISED_ONLY_ALERT
   - UNSUPERVISED_NOVELTY
   - NORMAL_TRAFFIC
4. Top-level backward compatibility of predict APIs.
5. REST API single (/predict, /predict/single), batch (/predict/batch), info (/model/info, /predict/info).
6. Streaming worker integration and alert persistence with _hybrid_evidence.
7. Graceful degradation on missing hybrid fields for historical alerts.
8. Tampered artifact fail-closed security.
9. Frozen production artifact byte-for-byte SHA-256 preservation.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.database.models import SecurityAlert
from detection.artifacts import compute_sha256
from ml.production_service import (
    EXPECTED_DETECTOR_SHA256,
    EXPECTED_IFOREST_SHA256,
    EXPECTED_PREPROCESSOR_SHA256,
    ProductionInferenceService,
)
from streaming.inference_worker import StreamingInferenceWorker


@pytest.fixture
def benign_flow() -> dict:
    return {
        "duration_seconds": 0.5,
        "fwd_bytes": 800.0,
        "sttl": 31.0,
        "sload": 12800.0,
        "fwd_packets": 10.0,
        "swin": 255.0,
        "smeansz": 80.0,
        "sjit": 5.0,
        "sintpkt": 50.0,
        "is_sm_ips_ports": 0.0,
    }


@pytest.fixture
def attack_flow() -> dict:
    return {
        "duration_seconds": 0.001,
        "fwd_bytes": 1_200_000.0,
        "sttl": 254.0,
        "sload": 9_600_000_000.0,
        "fwd_packets": 1200.0,
        "swin": 255.0,
        "smeansz": 1000.0,
        "sjit": 0.0,
        "sintpkt": 0.001,
        "is_sm_ips_ports": 0.0,
    }


class TestHybridInferenceService:
    """Core ML hybrid inference service testing."""

    def test_production_artifacts_exist_and_match_hashes(self):
        """Verify all production artifacts exist and match authoritative SHA-256 hashes."""
        det_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")
        iforest_path = Path("artifacts/models/production_iforest.joblib")

        assert det_path.exists(), "production_detector.joblib missing"
        assert prep_path.exists(), "production_preprocessor.joblib missing"
        assert iforest_path.exists(), "production_iforest.joblib missing"

        assert compute_sha256(det_path) == EXPECTED_DETECTOR_SHA256
        assert compute_sha256(prep_path) == EXPECTED_PREPROCESSOR_SHA256
        assert compute_sha256(iforest_path) == EXPECTED_IFOREST_SHA256

    def test_service_initialization_loads_both_detectors(self):
        """Verify service loads both models and enables hybrid detection."""
        service = ProductionInferenceService(verify_checksums=True)
        assert service.model is not None
        assert service.preprocessor is not None
        assert service.iforest is not None
        assert service.hybrid_enabled is True
        assert service.threshold == 0.50
        assert round(service.iforest_threshold, 6) == 0.727896

    def test_predict_single_returns_backward_compatible_and_hybrid_fields(self, benign_flow):
        """Verify single prediction contains all required top-level and nested hybrid fields."""
        service = ProductionInferenceService(verify_checksums=True)
        res = service.predict_single(benign_flow)

        # Backward compatibility checks
        assert "request_id" in res
        assert "is_anomaly" in res
        assert isinstance(res["is_anomaly"], bool)
        assert "anomaly_score" in res
        assert isinstance(res["anomaly_score"], float)
        assert "decision_threshold" in res
        assert res["decision_threshold"] == 0.50
        assert "risk_level" in res
        assert res["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert "model_name" in res
        assert "top_contributing_features" in res

        # Nested hybrid structure
        assert "supervised" in res
        assert res["supervised"]["threshold"] == 0.50
        assert "probability" in res["supervised"]
        assert res["supervised"]["decision"] in ("ANOMALY", "NORMAL")

        assert "unsupervised" in res
        assert round(res["unsupervised"]["threshold"], 6) == 0.727896
        assert "anomaly_score" in res["unsupervised"]
        assert res["unsupervised"]["decision"] in ("ANOMALY", "NORMAL")
        assert res["unsupervised"]["available"] is True

        assert "hybrid_classification" in res
        assert res["hybrid_classification"] in (
            "DUAL_CONFIRMED",
            "SUPERVISED_ONLY_ALERT",
            "UNSUPERVISED_NOVELTY",
            "NORMAL_TRAFFIC",
        )

    def test_all_four_hybrid_classifications(self):
        """Explicitly verify all 4 classification rules using controlled mock scores."""
        service = ProductionInferenceService(verify_checksums=True)
        dummy_flow = {
            "duration_seconds": 1.0,
            "fwd_bytes": 500.0,
            "sttl": 64.0,
            "sload": 4000.0,
            "fwd_packets": 5.0,
            "swin": 255.0,
            "smeansz": 100.0,
            "sjit": 1.0,
            "sintpkt": 10.0,
            "is_sm_ips_ports": 0.0,
        }

        # Case 1: DUAL_CONFIRMED (XGBoost Anomaly >= 0.5, IForest Anomaly >= 0.727896)
        service.model.predict_proba = MagicMock(return_value=np.array([[0.1, 0.85]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.75]))
        r1 = service.predict_single(dummy_flow)
        assert r1["hybrid_classification"] == "DUAL_CONFIRMED"
        assert r1["supervised"]["decision"] == "ANOMALY"
        assert r1["unsupervised"]["decision"] == "ANOMALY"

        # Case 2: SUPERVISED_ONLY_ALERT (XGBoost Anomaly >= 0.5, IForest Normal < 0.727896)
        service.model.predict_proba = MagicMock(return_value=np.array([[0.1, 0.90]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.45]))
        r2 = service.predict_single(dummy_flow)
        assert r2["hybrid_classification"] == "SUPERVISED_ONLY_ALERT"
        assert r2["supervised"]["decision"] == "ANOMALY"
        assert r2["unsupervised"]["decision"] == "NORMAL"

        # Case 3: UNSUPERVISED_NOVELTY (XGBoost Normal < 0.5, IForest Anomaly >= 0.727896)
        service.model.predict_proba = MagicMock(return_value=np.array([[0.9, 0.10]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.78]))
        r3 = service.predict_single(dummy_flow)
        assert r3["hybrid_classification"] == "UNSUPERVISED_NOVELTY"
        assert r3["supervised"]["decision"] == "NORMAL"
        assert r3["unsupervised"]["decision"] == "ANOMALY"

        # Case 4: NORMAL_TRAFFIC (XGBoost Normal < 0.5, IForest Normal < 0.727896)
        service.model.predict_proba = MagicMock(return_value=np.array([[0.95, 0.05]]))
        service.iforest.score_samples = MagicMock(return_value=np.array([0.38]))
        r4 = service.predict_single(dummy_flow)
        assert r4["hybrid_classification"] == "NORMAL_TRAFFIC"
        assert r4["supervised"]["decision"] == "NORMAL"
        assert r4["unsupervised"]["decision"] == "NORMAL"

    def test_tampered_isolation_forest_fails_closed(self):
        """Verify tampering with Isolation Forest fails closed with RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tampered_if = Path(tmp_dir) / "production_iforest.joblib"
            tampered_if.write_bytes(b"corrupted-tampered-content")

            with pytest.raises(RuntimeError, match="Isolation Forest artifact SHA-256 integrity verification failed"):
                ProductionInferenceService(
                    iforest_path=tampered_if,
                    verify_checksums=True,
                )

    def test_predict_batch_summary_includes_hybrid_counts(self, benign_flow, attack_flow):
        """Verify batch inference returns predictions and aggregate hybrid counts."""
        service = ProductionInferenceService(verify_checksums=True)
        res = service.predict_batch([benign_flow, attack_flow])

        assert res["total_records"] == 2
        assert "anomalies_detected" in res
        assert "hybrid_classification_counts" in res
        counts = res["hybrid_classification_counts"]
        assert sum(counts.values()) == 2
        assert "DUAL_CONFIRMED" in counts
        assert "SUPERVISED_ONLY_ALERT" in counts
        assert "UNSUPERVISED_NOVELTY" in counts
        assert "NORMAL_TRAFFIC" in counts


class TestPredictAPIAndEndpoints:
    """REST API endpoint tests for hybrid detection."""

    def test_predict_single_endpoint_aliases(self, client, benign_flow):
        """Verify both /predict and /predict/single respond with identical hybrid payload."""
        resp1 = client.post("/api/v1/predict", json=benign_flow)
        resp2 = client.post("/api/v1/predict/single", json=benign_flow)

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1 = resp1.get_json()["data"]
        data2 = resp2.get_json()["data"]

        assert "supervised" in data1 and "supervised" in data2
        assert "unsupervised" in data1 and "unsupervised" in data2
        assert "hybrid_classification" in data1 and "hybrid_classification" in data2
        assert data1["hybrid_classification"] == data2["hybrid_classification"]

    def test_predict_batch_endpoint_exposes_hybrid_counts(self, client, benign_flow, attack_flow):
        """Verify /predict/batch endpoint includes hybrid classification counts."""
        resp = client.post("/api/v1/predict/batch", json={"records": [benign_flow, attack_flow]})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        data = body["data"]
        assert "hybrid_classification_counts" in data
        assert data["total_records"] == 2

    def test_model_info_endpoint_aliases_and_hybrid_metadata(self, client):
        """Verify /model/info and /predict/info return both models and hybrid rules."""
        resp1 = client.get("/api/v1/model/info")
        resp2 = client.get("/api/v1/predict/info")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data = resp1.get_json()["data"]
        assert data["hybrid_enabled"] is True
        assert "supervised_model" in data
        assert "unsupervised_model" in data
        assert data["supervised_model"]["decision_threshold"] == 0.50
        assert round(data["unsupervised_model"]["decision_threshold"], 6) == 0.727896
        assert "hybrid_classification_classes" in data
        assert "DUAL_CONFIRMED" in data["hybrid_classification_classes"]


class TestStreamingAndAlertPersistence:
    """Streaming detection and alert persistence tests."""

    def test_streaming_event_record_contains_hybrid_scores(self, benign_flow):
        """Verify streaming worker includes dual scores and hybrid classification in events."""
        import queue
        q = queue.Queue()
        service = ProductionInferenceService(verify_checksums=True)
        worker = StreamingInferenceWorker(
            flow_queue=q,
            inference_service=service,
            source_provenance="PCAP_REPLAY",
        )

        flow = benign_flow.copy()
        flow["flow_id"] = "test-flow-1"
        worker._score_flow(flow)

        assert len(worker.recent_events) == 1
        ev = worker.recent_events[0]
        assert "supervised_score" in ev
        assert "supervised_decision" in ev
        assert "unsupervised_score" in ev
        assert "unsupervised_threshold" in ev
        assert "unsupervised_decision" in ev
        assert "hybrid_classification" in ev

    def test_security_alert_to_dict_unpacks_hybrid_evidence(self):
        """Verify SecurityAlert.to_dict() unpacks _hybrid_evidence from input_features."""
        alert = SecurityAlert(
            id=str(uuid.uuid4()),
            request_id="req-123",
            is_anomaly=True,
            anomaly_score=0.92,
            decision_threshold=0.50,
            risk_level="CRITICAL",
            model_name="OptunaTuned_XGBoost",
            model_version="1.0.0",
            status="NEW",
            input_features={
                "sttl": 254.0,
                "_hybrid_evidence": {
                    "hybrid_classification": "DUAL_CONFIRMED",
                    "supervised": {"probability": 0.92, "threshold": 0.50, "is_anomaly": True, "decision": "ANOMALY"},
                    "unsupervised": {"anomaly_score": 0.75, "threshold": 0.727896, "is_anomaly": True, "decision": "ANOMALY"},
                },
            },
        )

        d = alert.to_dict()
        assert d["hybrid_classification"] == "DUAL_CONFIRMED"
        assert d["supervised"]["probability"] == 0.92
        assert d["unsupervised"]["anomaly_score"] == 0.75

    def test_historical_alert_without_hybrid_evidence_handles_gracefully(self):
        """Verify historical alerts without _hybrid_evidence return None cleanly."""
        legacy_alert = SecurityAlert(
            id=str(uuid.uuid4()),
            request_id="legacy-req",
            is_anomaly=True,
            anomaly_score=0.88,
            decision_threshold=0.50,
            risk_level="HIGH",
            model_name="OptunaTuned_XGBoost",
            model_version="1.0.0",
            status="RESOLVED",
            input_features={"sttl": 64.0, "fwd_bytes": 1000.0},
        )

        d = legacy_alert.to_dict()
        assert d["hybrid_classification"] is None
        assert d["supervised"] is None
        assert d["unsupervised"] is None
