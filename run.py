"""
TrafficShield — Development entry point.

Run with:
    python run.py

Or via Flask CLI:
    flask run
"""
from __future__ import annotations

import os

from app import create_app

app = create_app(env=os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=app.config.get("FLASK_DEBUG", True),
    )
