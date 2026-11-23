"""Demonstration and baseline data seeding utilities for TrafficShield."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
import numpy as np

from app.extensions import db
from app.database.models import SecurityAlert, MonitoringBatchMetric
from monitoring.service import MonitoringService, ModelRegistryManager, MonitoringAlertManager

logger = logging.getLogger("trafficshield.seeding")
UTC = timezone.utc

DEMO_FLOWS: list[dict[str, Any]] = [
    {
        "request_id": "demo-req-001",
        "anomaly_score": 0.9642,
        "is_anomaly": True,
        "risk_level": "CRITICAL",
        "status": "NEW",
        "protocol": "TCP",
        "src_port": 49152,
        "dst_port": 80,
        "analyst_notes": "High volume SYN flood pattern with abnormal TTL and high byte rate.",
        "input_features": {
            "duration_seconds": 0.0012,
            "fwd_bytes": 142000,
            "sttl": 254,
            "sload": 946666666.0,
            "fwd_packets": 240,
            "swin": 255,
            "smeansz": 591.6,
            "sjit": 12.4,
            "sintpkt": 0.005,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [
            {
                "feature": "sttl",
                "value": 254,
                "contribution": "high",
                "reason": "Source TTL significantly elevated above standard local hop baseline.",
            },
            {
                "feature": "sload",
                "value": 946666666.0,
                "contribution": "high",
                "reason": "Source traffic load exceeds volumetric threshold.",
            },
        ],
    },
    {
        "request_id": "demo-req-002",
        "anomaly_score": 0.8814,
        "is_anomaly": True,
        "risk_level": "CRITICAL",
        "status": "INVESTIGATING",
        "protocol": "UDP",
        "src_port": 53210,
        "dst_port": 53,
        "analyst_notes": "Amplification probe detected on DNS endpoint.",
        "input_features": {
            "duration_seconds": 0.05,
            "fwd_bytes": 85000,
            "sttl": 254,
            "sload": 13600000.0,
            "fwd_packets": 80,
            "swin": 0,
            "smeansz": 1062.5,
            "sjit": 45.1,
            "sintpkt": 0.625,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [
            {
                "feature": "sttl",
                "value": 254,
                "contribution": "high",
                "reason": "Source TTL significantly elevated above standard local hop baseline.",
            },
            {
                "feature": "sload",
                "value": 13600000.0,
                "contribution": "high",
                "reason": "Source traffic load exceeds volumetric threshold.",
            },
        ],
    },
    {
        "request_id": "demo-req-003",
        "anomaly_score": 0.7245,
        "is_anomaly": True,
        "risk_level": "HIGH",
        "status": "NEW",
        "protocol": "TCP",
        "src_port": 50123,
        "dst_port": 443,
        "analyst_notes": "Anomalous TLS handshake packet sizing.",
        "input_features": {
            "duration_seconds": 1.25,
            "fwd_bytes": 48200,
            "sttl": 64,
            "sload": 308480.0,
            "fwd_packets": 35,
            "swin": 255,
            "smeansz": 1377.1,
            "sjit": 18.2,
            "sintpkt": 35.7,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [
            {
                "feature": "bytes_per_packet",
                "value": 1377.1,
                "contribution": "medium",
                "reason": "Abnormal mean packet sizing detected.",
            },
        ],
    },
    {
        "request_id": "demo-req-004",
        "anomaly_score": 0.5420,
        "is_anomaly": True,
        "risk_level": "MEDIUM",
        "status": "RESOLVED",
        "protocol": "TCP",
        "src_port": 51442,
        "dst_port": 22,
        "analyst_notes": "Internal automated backup SSH session. Confirmed benign by sysadmin.",
        "input_features": {
            "duration_seconds": 5.4,
            "fwd_bytes": 12500,
            "sttl": 64,
            "sload": 18518.5,
            "fwd_packets": 22,
            "swin": 255,
            "smeansz": 568.1,
            "sjit": 5.1,
            "sintpkt": 245.4,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [
            {
                "feature": "byte_rate",
                "value": 2314.8,
                "contribution": "medium",
                "reason": "Forward byte transmission rate elevated.",
            },
        ],
    },
    {
        "request_id": "demo-req-005",
        "anomaly_score": 0.1240,
        "is_anomaly": False,
        "risk_level": "LOW",
        "status": "RESOLVED",
        "protocol": "TCP",
        "src_port": 42100,
        "dst_port": 443,
        "analyst_notes": "Standard HTTPS client session.",
        "input_features": {
            "duration_seconds": 0.42,
            "fwd_bytes": 1820,
            "sttl": 64,
            "sload": 34666.6,
            "fwd_packets": 12,
            "swin": 255,
            "smeansz": 151.6,
            "sjit": 2.2,
            "sintpkt": 35.0,
            "is_sm_ips_ports": 0,
        },
        "top_contributing_features": [],
    },
]


def seed_demo_alerts_data() -> list[SecurityAlert]:
    """Insert 5 realistic demonstration SOC alerts into database."""
    created = []
    for d in DEMO_FLOWS:
        alert = SecurityAlert(
            request_id=d["request_id"],
            timestamp=datetime.now(UTC),
            is_anomaly=d["is_anomaly"],
            anomaly_score=d["anomaly_score"],
            decision_threshold=0.5,
            risk_level=d["risk_level"],
            model_name="OptunaTuned_XGBoost",
            model_version="1.0.0",
            status=d["status"],
            analyst_notes=d["analyst_notes"],
            input_features=d["input_features"],
            top_contributing_features=d["top_contributing_features"],
            protocol=d["protocol"],
            src_port=d["src_port"],
            dst_port=d["dst_port"],
            is_demo=True,
            source="demo_seed",
        )
        db.session.add(alert)
        created.append(alert)
    db.session.commit()
    logger.info("Seeded %d demonstration SOC alerts into database.", len(created))
    return created


def seed_demo_monitoring_data() -> dict[str, int]:
    """Insert sample monitoring batches and drift alerts into database."""
    ModelRegistryManager.initialize_registry_if_empty()
    service = MonitoringService()

    demo_batches = [
        {"flows": 250, "anom": 35, "mean": 0.21, "lat": 18.2, "src": "network_tap_A"},
        {"flows": 400, "anom": 62, "mean": 0.24, "lat": 24.5, "src": "network_tap_A"},
        {"flows": 300, "anom": 48, "mean": 0.22, "lat": 20.1, "src": "network_tap_B"},
        {"flows": 650, "anom": 185, "mean": 0.38, "lat": 38.4, "src": "dmz_border"},
        {"flows": 500, "anom": 140, "mean": 0.32, "lat": 29.8, "src": "dmz_border"},
    ]

    for i, b in enumerate(demo_batches):
        preds = []
        anom_count = int(b["anom"])
        flow_count = int(b["flows"])
        lat_ms = float(b["lat"])
        src_name = str(b["src"])

        for _ in range(anom_count):
            preds.append({
                "anomaly_score": round(float(np.random.uniform(0.65, 0.95)), 4),
                "is_anomaly": True,
                "risk_level": "CRITICAL" if np.random.rand() > 0.5 else "HIGH",
            })
        for _ in range(flow_count - anom_count):
            preds.append({
                "anomaly_score": round(float(np.random.uniform(0.01, 0.45)), 4),
                "is_anomaly": False,
                "risk_level": "LOW",
            })

        sample_recs = [
            {
                "sttl": 64 if np.random.rand() > 0.3 else 254,
                "sload": 25000.0,
                "duration_seconds": 0.5,
                "fwd_bytes": 1200,
                "fwd_packets": 10,
                "swin": 255,
                "smeansz": 120,
                "sjit": 10,
                "sintpkt": 5,
                "is_sm_ips_ports": 0,
            }
            for _ in range(flow_count)
        ]
        service.record_batch_telemetry(
            batch_id=f"demo-batch-00{i+1}",
            records=sample_recs,
            predictions=preds,
            latency_ms=lat_ms,
            source=src_name,
            is_demo=True,
        )

    alert_mgr = MonitoringAlertManager()
    alert_mgr._record_or_debounce_alert(
        alert_type="FEATURE_DRIFT",
        severity="WARNING",
        target_feature="sttl",
        metric_name="PSI",
        metric_value=0.184,
        threshold=0.10,
        sample_size=650,
        summary="Feature 'sttl' distribution drift (WARNING): PSI=0.1840 against reference baseline.",
        details={"feature": "sttl", "metric": "PSI", "value": 0.184},
        is_demo=True,
    )
    alert_mgr._record_or_debounce_alert(
        alert_type="ANOMALY_RATE_SPIKE",
        severity="CRITICAL",
        target_feature="overall_traffic",
        metric_name="AnomalyRatePercentage",
        metric_value=58.2,
        threshold=57.4,
        sample_size=650,
        summary="Sudden anomaly rate spike: 58.2% of 650 flows flagged (baseline expected ~28.7%).",
        details={"current_rate": 58.2, "baseline_rate": 28.7},
        is_demo=True,
    )

    logger.info("Seeded 5 demo monitoring batches and 2 demo operational alerts.")
    return {"seeded_batches": 5, "seeded_alerts": 2}
