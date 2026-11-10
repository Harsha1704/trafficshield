"""
TrafficShield — Development entry point.

Run for development with:
    python run.py

Or for production WSGI serving (Waitress):
    python wsgi.py
"""
from __future__ import annotations

import logging
import os
import sys
import types

# Windows Smart App Control / WDAC compatibility guard:
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        _mock_sag.sag64 = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

if "scipy.stats._qmvnt_cy" not in sys.modules:
    try:
        import scipy.stats._qmvnt_cy  # noqa: F401
    except (ImportError, OSError):
        _mock_qmvnt = types.ModuleType("scipy.stats._qmvnt_cy")
        _mock_qmvnt._qmvn_inner = lambda *args, **kwargs: (0.0, 0.0)
        _mock_qmvnt._qmvt_inner = lambda *args, **kwargs: (0.0, 0.0)
        sys.modules["scipy.stats._qmvnt_cy"] = _mock_qmvnt

from app import create_app

app = create_app(env=os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    if os.getenv("FLASK_ENV") == "production":
        logging.getLogger("trafficshield").warning(
            "Production environment detected. For production serving, run 'python wsgi.py' (Waitress WSGI)."
        )
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=app.config.get("FLASK_DEBUG", True),
    )
