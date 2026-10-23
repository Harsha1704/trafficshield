"""
Operational Monitoring Alert Manager & Deduplication Engine
============================================================
Milestone 12 — Intelligent Monitoring, Drift Detection & Model Lifecycle

Manages operational monitoring alerts:
- Evaluates feature drift, score drift, rate spikes, and latency violations
- Enforces debouncing, aggregation, and duplicate suppression
- Supports lifecycle states: ACTIVE, ACKNOWLEDGED, RESOLVED, SUPPRESSED
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.database.models import MonitoringAlert
from app.extensions import db
from monitoring.schema import (
    DriftStatus,
    FeatureDriftResult,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)

logger = logging.getLogger("alert_manager")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MonitoringAlertManager:
    """Manages creation, debouncing, deduplication, and triage of monitoring alerts."""

    def __init__(self, cooldown_minutes: int = 60) -> None:
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def process_drift_results(
        self,
        drift_results: list[FeatureDriftResult],
        is_demo: bool = False,
    ) -> list[MonitoringAlert]:
        """
        Create or update debounced monitoring alerts for features exhibiting WARNING or CRITICAL drift.
        Features with STABLE or INSUFFICIENT_DATA status do not trigger operational alerts.
        """
        alerts_generated = []

        for r in drift_results:
            if r.status not in (DriftStatus.WARNING, DriftStatus.CRITICAL):
                continue

            sev = (
                MonitoringAlertSeverity.CRITICAL.value
                if r.status == DriftStatus.CRITICAL
                else MonitoringAlertSeverity.WARNING.value
            )
            feature_name = r.feature
            summary = (
                f"Feature '{feature_name}' distribution drift ({r.status.value}): "
                f"PSI={r.metric_value:.4f} against reference baseline."
            )

            alert = self._record_or_debounce_alert(
                alert_type=MonitoringAlertType.FEATURE_DRIFT.value,
                severity=sev,
                target_feature=feature_name,
                metric_name="PSI",
                metric_value=r.metric_value,
                threshold=r.threshold_critical if r.status == DriftStatus.CRITICAL else r.threshold_warning,
                sample_size=r.sample_size,
                summary=summary,
                details=r.to_dict(),
                is_demo=is_demo,
            )
            alerts_generated.append(alert)

        return alerts_generated

    def process_score_drift(
        self,
        score_drift: FeatureDriftResult,
        is_demo: bool = False,
    ) -> MonitoringAlert | None:
        """Create or update alert if continuous anomaly score distribution drifts."""
        if score_drift.status not in (DriftStatus.WARNING, DriftStatus.CRITICAL):
            return None

        sev = (
            MonitoringAlertSeverity.CRITICAL.value
            if score_drift.status == DriftStatus.CRITICAL
            else MonitoringAlertSeverity.WARNING.value
        )
        summary = (
            f"Anomaly score distribution drift ({score_drift.status.value}): "
            f"Output score PSI={score_drift.metric_value:.4f}."
        )

        return self._record_or_debounce_alert(
            alert_type=MonitoringAlertType.SCORE_DRIFT.value,
            severity=sev,
            target_feature="anomaly_score",
            metric_name="PSI",
            metric_value=score_drift.metric_value,
            threshold=(
                score_drift.threshold_critical
                if score_drift.status == DriftStatus.CRITICAL
                else score_drift.threshold_warning
            ),
            sample_size=score_drift.sample_size,
            summary=summary,
            details=score_drift.to_dict(),
            is_demo=is_demo,
        )

    def process_anomaly_rate_spike(
        self,
        current_rate: float,
        baseline_rate: float,
        flow_count: int,
        is_demo: bool = False,
    ) -> MonitoringAlert | None:
        """Alert if the batch anomaly percentage exceeds 2x baseline rate."""
        if flow_count < 20:
            return None

        if current_rate > baseline_rate * 2.0 and current_rate >= 50.0:
            summary = (
                f"Sudden anomaly rate spike: {current_rate:.1f}% of {flow_count} flows flagged "
                f"(baseline expected ~{baseline_rate:.1f}%)."
            )
            return self._record_or_debounce_alert(
                alert_type=MonitoringAlertType.ANOMALY_RATE_SPIKE.value,
                severity=MonitoringAlertSeverity.CRITICAL.value,
                target_feature="overall_traffic",
                metric_name="AnomalyRatePercentage",
                metric_value=current_rate,
                threshold=baseline_rate * 2.0,
                sample_size=flow_count,
                summary=summary,
                details={"current_rate": current_rate, "baseline_rate": baseline_rate, "flow_count": flow_count},
                is_demo=is_demo,
            )
        return None

    def process_latency_degradation(
        self,
        latency_ms: float,
        threshold_ms: float = 250.0,
        flow_count: int = 1,
        is_demo: bool = False,
    ) -> MonitoringAlert | None:
        """Alert if inference latency breaches operational SLA."""
        if latency_ms > threshold_ms:
            summary = f"Scoring latency degradation: {latency_ms:.1f}ms exceeds operational SLA ({threshold_ms:.1f}ms)."
            return self._record_or_debounce_alert(
                alert_type=MonitoringAlertType.LATENCY_DEGRADATION.value,
                severity=MonitoringAlertSeverity.WARNING.value,
                target_feature="inference_engine",
                metric_name="LatencyMs",
                metric_value=latency_ms,
                threshold=threshold_ms,
                sample_size=flow_count,
                summary=summary,
                details={"latency_ms": latency_ms, "threshold_ms": threshold_ms},
                is_demo=is_demo,
            )
        return None

    def _record_or_debounce_alert(
        self,
        alert_type: str,
        severity: str,
        target_feature: str | None,
        metric_name: str,
        metric_value: float,
        threshold: float,
        sample_size: int,
        summary: str,
        details: dict[str, Any] | None = None,
        is_demo: bool = False,
    ) -> MonitoringAlert:
        """
        Deduplicate and debounce: If an ACTIVE or ACKNOWLEDGED alert matching
        (alert_type, target_feature) exists within cooldown, increment count instead
        of spamming new rows.
        """
        now = _utcnow()
        cutoff = now - self.cooldown

        existing = (
            MonitoringAlert.query.filter(
                MonitoringAlert.alert_type == alert_type,
                MonitoringAlert.target_feature == target_feature,
                MonitoringAlert.status.in_([MonitoringAlertStatus.ACTIVE.value, MonitoringAlertStatus.ACKNOWLEDGED.value]),
                MonitoringAlert.timestamp >= cutoff,
            )
            .order_by(MonitoringAlert.timestamp.desc())
            .first()
        )

        if existing:
            # Debounce: update existing alert
            existing.occurrence_count += 1
            existing.metric_value = metric_value
            existing.sample_size = sample_size
            existing.timestamp = now
            existing.details = details
            db.session.commit()
            return cast(MonitoringAlert, existing)

        # Create new alert
        alert = MonitoringAlert(
            timestamp=now,
            alert_type=alert_type,
            severity=severity,
            target_feature=target_feature,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
            sample_size=sample_size,
            summary=summary,
            details=details,
            status=MonitoringAlertStatus.ACTIVE.value,
            is_demo=is_demo,
        )
        db.session.add(alert)
        db.session.commit()
        return alert

    @staticmethod
    def acknowledge(alert_id: str) -> MonitoringAlert | None:
        """Acknowledge an active monitoring alert."""
        alert = db.session.get(MonitoringAlert, alert_id)
        if not alert:
            return None
        alert.status = MonitoringAlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = _utcnow()
        db.session.commit()
        return alert

    @staticmethod
    def resolve(alert_id: str) -> MonitoringAlert | None:
        """Resolve a monitoring alert."""
        alert = db.session.get(MonitoringAlert, alert_id)
        if not alert:
            return None
        alert.status = MonitoringAlertStatus.RESOLVED.value
        alert.resolved_at = _utcnow()
        db.session.commit()
        return alert
