"""Centralized logging configuration for PlanPilot.

Provides a configured logger instance with RotatingFileHandler (10MB max size,
3 backups) and formatted console logging.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from planpilot.utils.config import _PROJECT_ROOT

# Log file path in project logs directory
_LOG_FILE = _PROJECT_ROOT / "logs" / "planpilot.log"


def setup_logger(name: str = "planpilot") -> logging.Logger:
    """Set up and return a configured logger with file rotation and formatting."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Ensure directory exists
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Rotating file handler (10MB max bytes, 3 backup files)
        file_handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()
