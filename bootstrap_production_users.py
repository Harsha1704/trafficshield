"""Opt-in bootstrap for initial production SOC operator accounts.

This script is intended to run after Alembic has initialized the production schema.
It does not create or modify accounts unless BOOTSTRAP_PRODUCTION_USERS is explicitly
set to 1/true/yes. Existing users are never overwritten.
"""
from __future__ import annotations

import os

enabled = os.getenv("BOOTSTRAP_PRODUCTION_USERS", "").strip().lower() in {
    "1", "true", "yes",
}

if not enabled:
    print("Production user bootstrap skipped; BOOTSTRAP_PRODUCTION_USERS is not enabled.")
else:
    from run import app
    from app.utils.auth import bootstrap_initial_users

    bootstrap_initial_users(app)
    print("Production user bootstrap check completed.")
