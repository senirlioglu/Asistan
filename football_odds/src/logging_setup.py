"""Project-wide logging configuration."""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging(level: str | None = None) -> logging.Logger:
    global _CONFIGURED
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
        root.addHandler(handler)
        _CONFIGURED = True
    root.setLevel(getattr(logging, level_name, logging.INFO))
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger("fo")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"fo.{name}")
