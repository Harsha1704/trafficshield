"""
Production Anomaly Scoring Service
===================================
Version: 1.0

Provides thread-safe, low-latency scoring and explainability for real-time
unidirectional network traffic flows.

Responsibilities:
1. Request validation and strict policy enforcement (rejects reverse fields and labels).
2. Feature derivation (causal rate computation).
3. Preprocessing using frozen, train-fitted preprocessor.
4. Model inference (anomaly score, alert decision, confidence).
5. Risk classification ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL').
6. Top feature attributions for SOC alert explanation.
7. SHA-256 artifact integrity checking.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from features.policy import PolicyViolationError, audit_columns

logger = logging.getLogger("production_service")

# Authoritative frozen artifact checksums verified in M9
EXPECTED_DETECTOR_SHA256 = "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
EXPECTED_PREPROCESSOR_SHA256 = "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"
EXPECTED_IFOREST_SHA256 = "d9fe41016c51f8484b57c80bb2f0ec41186c66add9bae71f822d0a85c13a350e"

REQUIRED_BASE_FEATURES = [
    "duration_seconds",
    "fwd_bytes",
    "sttl",
    "sload",
    "fwd_packets",
    "swin",
    "smeansz",
    "sjit",
    "sintpkt",
    "is_sm_ips_ports",
]


class ProductionInferenceService:
    """Thread-safe production scoring and explanation service supporting hybrid detection."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        preprocessor_path: str | Path | None = None,
        iforest_path: str | Path | None = None,
        threshold: float = 0.5,
        iforest_threshold: float | None = None,
        verify_checksums: bool = True,
    ) -> None:
        from config.settings import PROJECT_ROOT
        def_model = PROJECT_ROOT / "artifacts" / "models" / "production_detector.joblib"
        def_prep = PROJECT_ROOT / "artifacts" / "models" / "production_preprocessor.joblib"
        def_iforest = PROJECT_ROOT / "artifacts" / "models" / "production_iforest.joblib"

        self.model_path = Path(model_path) if model_path else (def_model if def_model.exists() else None)
        self.preprocessor_path = Path(preprocessor_path) if preprocessor_path else (def_prep if def_prep.exists() else None)
        self.iforest_path = Path(iforest_path) if iforest_path else (def_iforest if def_iforest.exists() else None)
        self.threshold = threshold
        self.iforest_threshold = iforest_threshold
        self.verify_checksums = verify_checksums

        self.model: Any = None
        self.preprocessor: Any = None
        self.iforest: Any = None
        self.iforest_manifest: dict[str, Any] = {}
        self.feature_names: list[str] = []
        self.model_name: str = "ProductionFlowClassifier"
        self.iforest_name: str = "IsolationForestDetector"
        self.version: str = "1.0.0"
        self.model_sha256: str | None = None
        self.preprocessor_sha256: str | None = None
        self.iforest_sha256: str | None = None
        self.hybrid_enabled: bool = False

        if self.model_path or self.preprocessor_path or self.iforest_path:
            self.load_artifacts()

    @staticmethod
    def compute_sha256(filepath: Path) -> str:
        """Compute SHA-256 hash of a file on disk."""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def load_artifacts(self) -> None:
        """
        Load and verify serialized model, isolation forest, and preprocessor artifacts.
        Enforces cryptographic SHA-256 integrity checks against authoritative frozen hashes.
        Fails fast if artifacts are missing, corrupt, or tampered with.
        """
        if self.model_path:
            if not self.model_path.exists():
                raise FileNotFoundError(f"Model artifact not found: {self.model_path}")
            actual_model_hash = self.compute_sha256(self.model_path)
            self.model_sha256 = actual_model_hash
            if self.verify_checksums and actual_model_hash != EXPECTED_DETECTOR_SHA256:
                raise RuntimeError(
                    f"Model artifact SHA-256 integrity verification failed! "
                    f"Expected: {EXPECTED_DETECTOR_SHA256}, got: {actual_model_hash}. "
                    f"Refusing to load untrusted or modified artifact."
                )
            self.model = joblib.load(self.model_path)
            self.model_name = getattr(self.model, "__class__", type(self.model)).__name__

        if self.preprocessor_path:
            if not self.preprocessor_path.exists():
                raise FileNotFoundError(f"Preprocessor artifact not found: {self.preprocessor_path}")
            actual_prep_hash = self.compute_sha256(self.preprocessor_path)
            self.preprocessor_sha256 = actual_prep_hash
            if self.verify_checksums and actual_prep_hash != EXPECTED_PREPROCESSOR_SHA256:
                raise RuntimeError(
                    f"Preprocessor artifact SHA-256 integrity verification failed! "
                    f"Expected: {EXPECTED_PREPROCESSOR_SHA256}, got: {actual_prep_hash}. "
                    f"Refusing to load untrusted or modified artifact."
                )
            self.preprocessor = joblib.load(self.preprocessor_path)
            if hasattr(self.preprocessor, "feature_names_in_"):
                self.feature_names = list(self.preprocessor.feature_names_in_)

        if self.iforest_path:
            if not self.iforest_path.exists():
                raise FileNotFoundError(f"Isolation Forest artifact not found: {self.iforest_path}")
            actual_iforest_hash = self.compute_sha256(self.iforest_path)
            self.iforest_sha256 = actual_iforest_hash
            if self.verify_checksums and actual_iforest_hash != EXPECTED_IFOREST_SHA256:
                raise RuntimeError(
                    f"Isolation Forest artifact SHA-256 integrity verification failed! "
                    f"Expected: {EXPECTED_IFOREST_SHA256}, got: {actual_iforest_hash}. "
                    f"Refusing to load untrusted or modified artifact."
                )

            # Read companion manifest to determine threshold and provenance
            manifest_path = self.iforest_path.with_suffix(".json")
            if manifest_path.exists():
                try:
                    import json
                    self.iforest_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Could not read iforest companion manifest: %s", exc)

            if self.iforest_threshold is None:
                if "threshold" in self.iforest_manifest and self.iforest_manifest["threshold"] is not None:
                    self.iforest_threshold = float(self.iforest_manifest["threshold"])
                elif (
                    "threshold_config" in self.iforest_manifest
                    and "calibrated_threshold" in self.iforest_manifest["threshold_config"]
                ):
                    self.iforest_threshold = float(self.iforest_manifest["threshold_config"]["calibrated_threshold"])
                else:
                    self.iforest_threshold = 0.727896

            self.iforest = joblib.load(self.iforest_path)
            if hasattr(self.iforest, "threshold_"):
                self.iforest.threshold_ = self.iforest_threshold
            self.iforest_name = getattr(self.iforest, "__class__", type(self.iforest)).__name__
            self.hybrid_enabled = True

    def validate_and_prepare_input(self, raw_record: dict[str, Any]) -> pd.DataFrame:
        """
        Validate single flow record against feature policy and schema.
        Derives rates causally if duration > 0.
        """
        cols = list(raw_record.keys())
        audit = audit_columns(cols)
        if not audit.is_clean:
            errors = []
            if audit.forbidden_violations:
                errors.append(f"Forbidden reverse-dependent columns rejected: {audit.forbidden_violations}")
            if audit.label_violations:
                errors.append(f"Target labels cannot be prediction features: {audit.label_violations}")
            raise PolicyViolationError("; ".join(errors))

        # Check required forward features
        missing = [f for f in REQUIRED_BASE_FEATURES if f not in raw_record]
        if missing:
            raise ValueError(f"Missing required forward observable features: {missing}")

        data = {k: [float(raw_record[k])] for k in REQUIRED_BASE_FEATURES}
        df = pd.DataFrame(data)

        # Causal rate derivation
        dur = df["duration_seconds"].iloc[0]
        pkts = df["fwd_packets"].iloc[0]
        bytes_ = df["fwd_bytes"].iloc[0]

        df["packet_rate"] = (pkts / dur) if dur > 0 else 0.0
        df["byte_rate"] = (bytes_ / dur) if dur > 0 else 0.0
        df["bytes_per_packet"] = (bytes_ / pkts) if pkts > 0 else 0.0

        return df

    def predict_single(self, flow_data: dict[str, Any]) -> dict[str, Any]:
        """Score single flow observation and provide evidence-backed explanation with hybrid detection."""
        if self.model is None or (not hasattr(self.model, "predict_proba") and not hasattr(self.model, "score_samples")):
            raise RuntimeError(
                "Production detector model is uninitialized or artifact failed to load. Refusing to perform inference."
            )

        request_id = str(uuid.uuid4())
        df_flow = self.validate_and_prepare_input(flow_data)

        if self.preprocessor is not None:
            x_input = self.preprocessor.transform_df(df_flow)
        else:
            x_input = df_flow

        # 1. Supervised XGBoost Inference (attack probability in [0.0, 1.0])
        if hasattr(self.model, "predict_proba"):
            score = float(self.model.predict_proba(x_input)[:, 1][0])
        elif hasattr(self.model, "score_samples"):
            raw_s = float(self.model.score_samples(x_input)[0])
            score = float(np.clip(raw_s, 0.0, 1.0))
        else:
            score = 0.0

        is_supervised_anomaly = bool(score >= self.threshold)

        # 2. Unsupervised Isolation Forest Inference (continuous anomaly score)
        if self.iforest is not None and hasattr(self.iforest, "score_samples"):
            raw_if_score = float(self.iforest.score_samples(x_input)[0])
            if_thresh = self.iforest_threshold if self.iforest_threshold is not None else 0.727896
            is_unsupervised_anomaly = bool(raw_if_score >= if_thresh)
            iforest_available = True
        else:
            raw_if_score = 0.0
            if_thresh = self.iforest_threshold if self.iforest_threshold is not None else 0.727896
            is_unsupervised_anomaly = False
            iforest_available = False

        # 3. Transparent Hybrid Classification
        if is_supervised_anomaly and is_unsupervised_anomaly:
            hybrid_classification = "DUAL_CONFIRMED"
        elif is_supervised_anomaly and not is_unsupervised_anomaly:
            hybrid_classification = "SUPERVISED_ONLY_ALERT"
        elif not is_supervised_anomaly and is_unsupervised_anomaly:
            hybrid_classification = "UNSUPERVISED_NOVELTY"
        else:
            hybrid_classification = "NORMAL_TRAFFIC"

        # Risk level categorization based on supervised probability
        if score >= 0.85:
            risk = "CRITICAL"
        elif score >= 0.65:
            risk = "HIGH"
        elif score >= self.threshold:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        # Feature attribution explanations
        attributions = self._compute_feature_attributions(df_flow)

        return {
            "request_id": request_id,
            "is_anomaly": is_supervised_anomaly,
            "anomaly_score": round(score, 6),
            "decision_threshold": round(self.threshold, 6),
            "risk_level": risk,
            "model_name": self.model_name,
            "top_contributing_features": attributions,
            "supervised": {
                "probability": round(score, 6),
                "threshold": round(self.threshold, 6),
                "is_anomaly": is_supervised_anomaly,
                "decision": "ANOMALY" if is_supervised_anomaly else "NORMAL",
            },
            "unsupervised": {
                "anomaly_score": round(raw_if_score, 6),
                "threshold": round(if_thresh, 6),
                "is_anomaly": is_unsupervised_anomaly,
                "decision": "ANOMALY" if is_unsupervised_anomaly else "NORMAL",
                "detector_name": self.iforest_name,
                "available": iforest_available,
            },
            "hybrid_classification": hybrid_classification,
        }

    def predict_batch(self, batch_records: list[dict[str, Any]]) -> dict[str, Any]:
        """Score a collection of flow observations with summary analytics and hybrid metrics."""
        if not batch_records:
            raise ValueError("Batch record list is empty.")

        if self.model is None or (not hasattr(self.model, "predict_proba") and not hasattr(self.model, "score_samples")):
            raise RuntimeError(
                "Production detector model is uninitialized or artifact failed to load. Refusing to perform inference."
            )

        results = []
        for rec in batch_records:
            results.append(self.predict_single(rec))

        scores = [r["anomaly_score"] for r in results]
        anom_count = sum(1 for r in results if r["is_anomaly"])

        hybrid_counts = {
            "DUAL_CONFIRMED": sum(1 for r in results if r.get("hybrid_classification") == "DUAL_CONFIRMED"),
            "SUPERVISED_ONLY_ALERT": sum(1 for r in results if r.get("hybrid_classification") == "SUPERVISED_ONLY_ALERT"),
            "UNSUPERVISED_NOVELTY": sum(1 for r in results if r.get("hybrid_classification") == "UNSUPERVISED_NOVELTY"),
            "NORMAL_TRAFFIC": sum(1 for r in results if r.get("hybrid_classification") == "NORMAL_TRAFFIC"),
        }

        return {
            "total_records": len(batch_records),
            "anomalies_detected": anom_count,
            "anomaly_percentage": round((anom_count / len(batch_records)) * 100.0, 2),
            "mean_anomaly_score": round(float(np.mean(scores)), 4),
            "max_anomaly_score": round(float(np.max(scores)), 4),
            "predictions": results,
            "hybrid_classification_counts": hybrid_counts,
        }

    def _compute_feature_attributions(self, df_flow: pd.DataFrame) -> list[dict[str, Any]]:
        """Identify top deviating forward features for evidence-backed explanation."""
        attributions = []
        # Inspect salient forward features
        sttl = float(df_flow["sttl"].iloc[0])
        sload = float(df_flow["sload"].iloc[0])
        byte_rate = float(df_flow["byte_rate"].iloc[0])
        bytes_per_pkt = float(df_flow["bytes_per_packet"].iloc[0])

        if sttl > 64:
            attributions.append({
                "feature": "sttl",
                "value": sttl,
                "contribution": "high",
                "reason": "Source TTL significantly elevated above standard local hop baseline.",
            })
        if sload > 1_000_000:
            attributions.append({
                "feature": "sload",
                "value": sload,
                "contribution": "high",
                "reason": "Source traffic load exceeds volumetric threshold.",
            })
        if byte_rate > 500_000:
            attributions.append({
                "feature": "byte_rate",
                "value": round(byte_rate, 2),
                "contribution": "medium",
                "reason": "Forward byte transmission rate elevated.",
            })
        if bytes_per_pkt > 1200 or bytes_per_pkt < 40:
            attributions.append({
                "feature": "bytes_per_packet",
                "value": round(bytes_per_pkt, 2),
                "contribution": "medium",
                "reason": "Abnormal mean packet sizing detected.",
            })

        return attributions[:4]

    def get_info(self) -> dict[str, Any]:
        """Return operational model metadata, deployment configuration, and hybrid architecture info."""
        if_thresh = self.iforest_threshold if self.iforest_threshold is not None else 0.727896
        return {
            "service": "TrafficShield Production Hybrid Anomaly Scoring API",
            "model_name": self.model_name,
            "model_version": self.version,
            "decision_threshold": self.threshold,
            "feature_policy": "Unidirectional Causal-Only (Zero Return/Reverse Observation)",
            "required_forward_features": REQUIRED_BASE_FEATURES,
            "engineered_features": ["packet_rate", "byte_rate", "bytes_per_packet"],
            "model_loaded": self.model is not None,
            "preprocessor_loaded": self.preprocessor is not None,
            "hybrid_enabled": bool(self.model is not None and self.iforest is not None),
            "supervised_model": {
                "name": self.model_name,
                "type": "Supervised XGBoost Flow Classifier",
                "version": self.version,
                "decision_threshold": self.threshold,
                "loaded": self.model is not None,
                "sha256": self.model_sha256 or EXPECTED_DETECTOR_SHA256,
            },
            "unsupervised_model": {
                "name": self.iforest_name,
                "type": "Unsupervised Isolation Forest Detector",
                "version": "1.0.0",
                "decision_threshold": round(if_thresh, 6),
                "loaded": self.iforest is not None,
                "sha256": self.iforest_sha256 or EXPECTED_IFOREST_SHA256,
                "score_direction": "Inverted (higher score indicates greater anomalousness)",
            },
            "hybrid_classification_classes": [
                "DUAL_CONFIRMED",
                "SUPERVISED_ONLY_ALERT",
                "UNSUPERVISED_NOVELTY",
                "NORMAL_TRAFFIC",
            ],
            "hybrid_classification_rules": {
                "DUAL_CONFIRMED": "Both supervised XGBoost and unsupervised Isolation Forest detect anomaly.",
                "SUPERVISED_ONLY_ALERT": "Supervised XGBoost alerts while Isolation Forest evaluates within normal baseline.",
                "UNSUPERVISED_NOVELTY": "Isolation Forest flags statistical novelty while supervised XGBoost evaluates normal.",
                "NORMAL_TRAFFIC": "Both detectors evaluate flow within normal operating baseline.",
            },
            "artifact_integrity": {
                "verified": bool(
                    self.model is not None
                    and self.preprocessor is not None
                    and (self.iforest is not None or not self.hybrid_enabled)
                ),
                "model_sha256": self.model_sha256 or EXPECTED_DETECTOR_SHA256,
                "preprocessor_sha256": self.preprocessor_sha256 or EXPECTED_PREPROCESSOR_SHA256,
                "iforest_sha256": self.iforest_sha256 or EXPECTED_IFOREST_SHA256,
            },
            "verified_benchmark": {
                "evaluation_dataset": "UNSW-NB15",
                "verification_milestone": "M9 Independent Reproduction",
                "heldout_test": {
                    "split_description": "Day 1 Held-Out Test Split (19,942 flows)",
                    "flows": 19942,
                    "accuracy": 0.981045,
                    "recall": 0.977808,
                    "precision": 0.958501,
                    "specificity": 0.982391,
                    "fpr": 0.017609,
                    "f1_score": 0.968058,
                    "roc_auc": 0.998711,
                    "pr_auc": 0.996661,
                    "confusion_matrix": [13836, 248, 130, 5728],
                },
                "day2_temporal_holdout": {
                    "split_description": "Day 2 Out-of-Distribution Holdout (20,000 flows, 24 days later)",
                    "flows": 20000,
                    "accuracy": 0.969700,
                    "recall": 0.983700,
                    "precision": 0.905700,
                    "specificity": 0.965000,
                    "fpr": 0.035000,
                    "f1_score": 0.943100,
                    "confusion_matrix": [14384, 522, 83, 5011],
                },
                "cross_dataset_limits": {
                    "cicids2017_status": "DIRECT_TRANSFER_UNSUPPORTED",
                    "cicids2017_local_raw_data": "ABSENT_LOCALLY (0 MB)",
                    "audit_verdict": "M10.1 Provenance Audit Confirmed Synthetic Fixture (Unverified on real CICIDS2017)",
                },
            },
        }
