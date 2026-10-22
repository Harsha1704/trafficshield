"""
Structured logging configuration for TrafficShield.
Supports JSON (production) and human-readable text (development) formats.
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

try:
    from pythonjsonlogger import json as jsonlogger  # v3.x
except ImportError:
    from pythonjsonlogger import jsonlogger as jsonlogger  # type: ignore[no-redef]


class _TextFormatter(logging.Formatter):
    """Simple coloured text formatter for development."""

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def configure_logging(
    level: str = "INFO",
    fmt: Literal["json", "text"] = "json",
) -> None:
    """
    Configure root logger.

    Parameters
    ----------
    level : str
        Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    fmt : str
        'json' for structured JSON logs, 'text' for human-readable.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on hot-reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter: logging.Formatter
    if fmt == "json":
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        formatter = _TextFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("werkzeug", "sqlalchemy.engine", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
