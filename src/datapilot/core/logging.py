"""Structured logging setup for Data Pilot."""

import logging
import sys
from typing import Optional
from datapilot.core.config import Settings, get_settings


def setup_logging(settings: Optional[Settings] = None) -> None:
    """Configure the root logger with the specified settings."""
    cfg = settings or get_settings()

    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Avoid duplicate handlers if setup_logging is invoked multiple times
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Silence noisy third-party loggers in debug mode
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
