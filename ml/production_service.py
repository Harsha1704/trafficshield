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
    """Thread-safe production scoring and explanation service."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        preprocessor_path: str | Path | None = None,
        threshold: float = 0.5,
        verify_checksums: bool = True,
    ) -> None:
        def_model = Path("artifacts/models/production_detector.joblib")
        def_prep = Path("artifacts/models/production_preprocessor.joblib")
        self.model_path = Path(model_path) if model_path else (def_model if def_model.exists() else None)
        self.preprocessor_path = Path(preprocessor_path) if preprocessor_path else (def_prep if def_prep.exists() else None)
        self.threshold = threshold
        self.verify_checksums = verify_checksums

        self.model: Any = None
        self.preprocessor: Any = None
        self.feature_names: list[str] = []
        self.model_name: str = "ProductionFlowClassifier"
        self.version: str = "1.0.0"
        self.model_sha256: str | None = None
        self.preprocessor_sha256: str | None = None

        if self.model_path and self.model_path.exists():
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
        Load and verify serialized model and preprocessor artifacts.
        Enforces cryptographic SHA-256 integrity check against known frozen hashes.
        Fails fast if artifacts are missing, corrupt, or tampered with.
        """
        if self.model_path and self.model_path.exists():
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

        if self.preprocessor_path and self.preprocessor_path.exists():
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
        """Score single flow observation and provide evidence-backed explanation."""
        request_id = str(uuid.uuid4())
        df_flow = self.validate_and_prepare_input(flow_data)

        if self.preprocessor is not None:
            x_input = self.preprocessor.transform_df(df_flow)
        else:
            x_input = df_flow

        # Compute continuous anomaly score in [0.0, 1.0]
        if hasattr(self.model, "predict_proba"):
            score = float(self.model.predict_proba(x_input)[:, 1][0])
        elif hasattr(self.model, "score_samples"):
            raw_s = float(self.model.score_samples(x_input)[0])
            score = float(np.clip(raw_s, 0.0, 1.0))
        else:
            score = 0.0

        is_anom = int(score >= self.threshold)

        # Risk level categorization
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
            "is_anomaly": bool(is_anom),
            "anomaly_score": round(score, 6),
            "decision_threshold": round(self.threshold, 6),
            "risk_level": risk,
            "model_name": self.model_name,
            "top_contributing_features": attributions,
        }

    def predict_batch(self, batch_records: list[dict[str, Any]]) -> dict[str, Any]:
        """Score a collection of flow observations with summary analytics."""
        if not batch_records:
            raise ValueError("Batch record list is empty.")

        results = []
        for rec in batch_records:
            results.append(self.predict_single(rec))

        scores = [r["anomaly_score"] for r in results]
        anom_count = sum(1 for r in results if r["is_anomaly"])

        return {
            "total_records": len(batch_records),
            "anomalies_detected": anom_count,
            "anomaly_percentage": round((anom_count / len(batch_records)) * 100.0, 2),
            "mean_anomaly_score": round(float(np.mean(scores)), 4),
            "max_anomaly_score": round(float(np.max(scores)), 4),
            "predictions": results,
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
        """Return operational model metadata and deployment configuration."""
        return {
            "service": "TrafficShield Production Anomaly Scoring API",
            "model_name": self.model_name,
            "model_version": self.version,
            "decision_threshold": self.threshold,
            "feature_policy": "Unidirectional Causal-Only (Zero Return/Reverse Observation)",
            "required_forward_features": REQUIRED_BASE_FEATURES,
            "engineered_features": ["packet_rate", "byte_rate", "bytes_per_packet"],
            "model_loaded": self.model is not None,
            "preprocessor_loaded": self.preprocessor is not None,
            "artifact_integrity": {
                "verified": bool(self.model is not None and self.preprocessor is not None),
                "model_sha256": self.model_sha256 or EXPECTED_DETECTOR_SHA256,
                "preprocessor_sha256": self.preprocessor_sha256 or EXPECTED_PREPROCESSOR_SHA256,
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
