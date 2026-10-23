"""
Central Monitoring & Drift Evaluation Service
=============================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Coordinates:
- Recording batch scoring metrics and inference latency
- On-demand and batch drift evaluation
- Model registry initialization and checks
- Purging stale metrics according to retention policy
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.database.models import MonitoringAlert, MonitoringBatchMetric
from app.extensions import db
from ml.production_service import REQUIRED_BASE_FEATURES
from monitoring.alert_manager import MonitoringAlertManager
from monitoring.baseline import load_reference_baseline
from monitoring.drift_engine import (
    DEFAULT_MIN_SAMPLE_SIZE,
    check_data_quality,
    evaluate_feature_drift,
    evaluate_score_drift,
)
from monitoring.registry import ModelRegistryManager

logger = logging.getLogger("monitoring_service")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MonitoringService:
    """Central orchestration service for operational telemetry and drift analysis."""

    def __init__(
        self,
        alert_manager: MonitoringAlertManager | None = None,
        retention_days: int = 30,
        min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    ) -> None:
        self.alert_manager = alert_manager or MonitoringAlertManager()
        self.retention_days = retention_days
        self.min_sample_size = min_sample_size
        self._reference_baseline = load_reference_baseline()

    @property
    def baseline_profile(self) -> dict[str, Any]:
        """Return the immutable reference baseline dictionary."""
        return self._reference_baseline

    def record_batch_telemetry(
        self,
        batch_id: str | None,
        records: list[dict[str, Any]],
        predictions: list[dict[str, Any]],
        latency_ms: float,
        source: str = "batch_upload",
        is_demo: bool = False,
    ) -> MonitoringBatchMetric:
        """
        Record aggregate statistical telemetry for a scoring batch.
        One batch is recorded as one summary event; flow_count records individual flows.
        """
        b_id = batch_id or f"batch-{uuid.uuid4().hex[:12]}"
        flow_count = len(records)
        scores = [p["anomaly_score"] for p in predictions]
        anomalies = [p for p in predictions if p["is_anomaly"]]
        anom_count = len(anomalies)
        anom_rate = (anom_count / flow_count * 100.0) if flow_count > 0 else 0.0
        mean_score = float(np.mean(scores)) if scores else 0.0
        p95_score = float(np.percentile(scores, 95)) if scores else 0.0

        # Severity breakdown
        sev_counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for p in predictions:
            lvl = p.get("risk_level", "LOW")
            sev_counts[lvl] = sev_counts.get(lvl, 0) + 1

        # Score histogram: 10 uniform bins over [0.0, 1.0]
        hist_counts, _ = np.histogram(scores, bins=np.linspace(0.0, 1.0, 11))
        hist_list = [int(c) for c in hist_counts]

        # Active model hash from registry or baseline
        active_model = ModelRegistryManager.get_active_model()
        model_hash = (
            active_model.model_artifact_hash
            if active_model
            else self.baseline_profile.get("model_artifact_hash", "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495")
        )

        # Feature summary metrics
        df_records = pd.DataFrame(records)
        feat_metrics: dict[str, dict[str, Any]] = {}
        target_features = REQUIRED_BASE_FEATURES + ["packet_rate", "byte_rate", "bytes_per_packet"]
        for f in target_features:
            if f in df_records.columns:
                series = pd.to_numeric(df_records[f], errors="coerce").dropna()
                feat_metrics[f] = {
                    "count": len(series),
                    "mean": round(float(np.mean(series)), 4) if len(series) > 0 else 0.0,
                    "std": round(float(np.std(series)), 4) if len(series) > 1 else 0.0,
                    "min": round(float(np.min(series)), 4) if len(series) > 0 else 0.0,
                    "max": round(float(np.max(series)), 4) if len(series) > 0 else 0.0,
                }

        # Operational alert checks
        base_rate = self.baseline_profile.get("score_baseline", {}).get("anomaly_rate", 28.7)
        self.alert_manager.process_anomaly_rate_spike(
            current_rate=anom_rate,
            baseline_rate=base_rate,
            flow_count=flow_count,
            is_demo=is_demo,
        )
        self.alert_manager.process_latency_degradation(
            latency_ms=latency_ms,
            threshold_ms=250.0,
            flow_count=flow_count,
            is_demo=is_demo,
        )

        batch_metric = MonitoringBatchMetric(
            batch_id=b_id,
            timestamp=_utcnow(),
            model_name="OptunaTuned_XGBoost",
            model_version="1.0.0",
            artifact_hash=model_hash,
            decision_threshold=0.5,
            source=source,
            flow_count=flow_count,
            anomaly_count=anom_count,
            anomaly_rate=anom_rate,
            mean_score=mean_score,
            p95_score=p95_score,
            latency_ms=latency_ms,
            validation_failure_count=0,
            severity_counts=sev_counts,
            score_histogram=hist_list,
            feature_metrics=feat_metrics,
            is_demo=is_demo,
        )
        db.session.add(batch_metric)
        db.session.commit()
        return batch_metric

    def evaluate_drift(
        self,
        df_flows: pd.DataFrame,
        scores: np.ndarray | list[float] | None = None,
        is_demo: bool = False,
    ) -> dict[str, Any]:
        """
        Evaluate full statistical drift (features, scores, data quality) for a flow batch.
        """
        target_features = REQUIRED_BASE_FEATURES + ["packet_rate", "byte_rate", "bytes_per_packet"]

        # Ensure engineered features exist if missing
        df_eval = df_flows.copy()
        if "packet_rate" not in df_eval.columns and "fwd_packets" in df_eval.columns and "duration_seconds" in df_eval.columns:
            dur = pd.to_numeric(df_eval["duration_seconds"], errors="coerce").fillna(0.0).replace(0, 1e-6)
            pkts = pd.to_numeric(df_eval["fwd_packets"], errors="coerce").fillna(1).replace(0, 1)
            bytes_col = pd.to_numeric(df_eval["fwd_bytes"], errors="coerce").fillna(0)
            df_eval["packet_rate"] = pkts / dur
            df_eval["byte_rate"] = bytes_col / dur
            df_eval["bytes_per_packet"] = bytes_col / pkts

        # 1. Feature Drift
        feature_results = evaluate_feature_drift(
            baseline_profile=self.baseline_profile,
            current_df=df_eval,
            features=target_features,
            min_sample_size=self.min_sample_size,
        )

        # 2. Score Drift
        score_res = None
        if scores is not None and len(scores) > 0:
            score_arr = np.asarray(scores, dtype=float)
            score_res = evaluate_score_drift(
                baseline_score_profile=self.baseline_profile.get("score_baseline", {}),
                current_scores=score_arr,
                min_sample_size=self.min_sample_size,
            )

        # 3. Data Quality
        quality = check_data_quality(df_eval, target_features)

        # 4. Trigger monitoring alerts for drifting features
        alerts = self.alert_manager.process_drift_results(feature_results, is_demo=is_demo)
        if score_res:
            s_alert = self.alert_manager.process_score_drift(score_res, is_demo=is_demo)
            if s_alert:
                alerts.append(s_alert)

        # Overall summary status
        statuses = [r.status for r in feature_results]
        if any(s.value == "CRITICAL" for s in statuses) or (score_res and score_res.status.value == "CRITICAL"):
            overall_status = "CRITICAL"
        elif any(s.value == "WARNING" for s in statuses) or (score_res and score_res.status.value == "WARNING"):
            overall_status = "WARNING"
        elif any(s.value == "INSUFFICIENT_DATA" for s in statuses):
            overall_status = "INSUFFICIENT_DATA"
        else:
            overall_status = "STABLE"

        return {
            "overall_status": overall_status,
            "sample_size": len(df_flows),
            "feature_drift": [r.to_dict() for r in feature_results],
            "score_drift": score_res.to_dict() if score_res else None,
            "data_quality": quality,
            "alerts_triggered_or_debounced": len(alerts),
            "disclaimer": (
                "Statistical distribution drift detects input covariate shift or concept drift relative to reference baseline. "
                "It does NOT constitute proof of an adversarial cyberattack or operational failure."
            ),
        }

    def get_monitoring_status(self) -> dict[str, Any]:
        """Aggregate summary of monitoring engine health, volume, and active alerts."""
        now = _utcnow()
        recent_cutoff = now - timedelta(hours=24)

        # Total counts
        total_batches = MonitoringBatchMetric.query.count()
        total_flows_evaluated = db.session.query(db.func.sum(MonitoringBatchMetric.flow_count)).scalar() or 0
        total_anomalies_flagged = db.session.query(db.func.sum(MonitoringBatchMetric.anomaly_count)).scalar() or 0

        # Recent 24h
        recent_batches = MonitoringBatchMetric.query.filter(MonitoringBatchMetric.timestamp >= recent_cutoff).all()
        recent_flows = sum(b.flow_count for b in recent_batches)
        avg_latency = (
            float(np.mean([b.latency_ms for b in recent_batches]))
            if recent_batches
            else 0.0
        )

        # Active monitoring alerts
        active_alerts = (
            MonitoringAlert.query.filter(MonitoringAlert.status == "ACTIVE")
            .order_by(MonitoringAlert.timestamp.desc())
            .all()
        )

        # Active model from registry
        active_model = ModelRegistryManager.get_active_model()

        # Data freshness
        latest_batch = MonitoringBatchMetric.query.order_by(MonitoringBatchMetric.timestamp.desc()).first()
        freshness_iso = latest_batch.timestamp.isoformat() if latest_batch and latest_batch.timestamp else None

        return {
            "service": "TrafficShield Intelligent Monitoring Engine",
            "version": "1.0.0",
            "monitoring_mode": "BATCH_AND_SCHEDULED",  # Discloses that continuous monitoring depends on active scoring
            "data_freshness": freshness_iso or "NO_EVENTS_RECORDED",
            "active_model": {
                "name": active_model.model_name if active_model else "OptunaTuned_XGBoost",
                "version": active_model.model_version if active_model else "1.0.0",
                "artifact_hash": active_model.model_artifact_hash if active_model else "",
                "lifecycle_status": active_model.lifecycle_status if active_model else "PRODUCTION",
            },
            "kpis": {
                "total_batches_recorded": total_batches,
                "total_flows_evaluated": total_flows_evaluated,
                "total_anomalies_flagged": total_anomalies_flagged,
                "recent_24h_flows": recent_flows,
                "average_latency_ms": round(avg_latency, 2),
                "active_monitoring_alerts": len(active_alerts),
            },
            "active_alerts": [a.to_dict() for a in active_alerts[:10]],
            "reference_baseline_meta": {
                "source": self.baseline_profile.get("dataset_source"),
                "sample_size": self.baseline_profile.get("sample_size"),
                "window": self.baseline_profile.get("time_window"),
            },
        }

    def purge_stale_metrics(self, retention_days: int | None = None) -> int:
        """Purge batch metric records older than retention period to control database size."""
        days = retention_days or self.retention_days
        cutoff = _utcnow() - timedelta(days=days)
        deleted = (
            MonitoringBatchMetric.query.filter(MonitoringBatchMetric.timestamp < cutoff).delete()
        )
        db.session.commit()
        logger.info("Purged %d stale monitoring batch records older than %d days.", deleted, days)
        return int(deleted)
