"""Opt-in bootstrap for initial production SOC operator accounts & baseline demonstration telemetry.

This script runs after Alembic has initialized the production schema.
1. Bootstraps initial operator accounts (admin, analyst) if not present.
2. If the alert database is empty, seeds baseline demonstration SOC alerts.
3. If the monitoring database is empty, seeds initial baseline operational telemetry.
"""
from __future__ import annotations

import os

enabled = os.getenv("BOOTSTRAP_PRODUCTION_USERS", "true").strip().lower() in {
    "1", "true", "yes",
}

if not enabled:
    print("Production bootstrap skipped; BOOTSTRAP_PRODUCTION_USERS is disabled.")
else:
    from run import app
    from app.utils.auth import bootstrap_initial_users
    from app.database.models import SecurityAlert, MonitoringBatchMetric
    from app.utils.seeding import seed_demo_alerts_data, seed_demo_monitoring_data

    # 1. Bootstrap operator accounts
    bootstrap_initial_users(app)

    # 2. Bootstrap baseline telemetry if tables are empty
    with app.app_context():
        alert_count = SecurityAlert.query.count()
        if alert_count == 0:
            print("Empty SecurityAlert table detected; seeding initial baseline demonstration alerts...")
            seed_demo_alerts_data()
            print("Baseline demonstration alerts seeded successfully.")
        else:
            print(f"SecurityAlert table already contains {alert_count} records; skipping alert seed.")

        monitoring_count = MonitoringBatchMetric.query.count()
        if monitoring_count == 0:
            print("Empty MonitoringBatchMetric table detected; seeding initial baseline telemetry...")
            seed_demo_monitoring_data()
            print("Baseline monitoring telemetry seeded successfully.")
        else:
            print(f"MonitoringBatchMetric table already contains {monitoring_count} records; skipping telemetry seed.")

    print("Production bootstrap completed successfully.")
