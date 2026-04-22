"""Shared logging setup for terminal and daily local log files."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] [service=%(service)s] %(name)s: %(message)s"


class _ServiceFilter(logging.Filter):
    """Attach a static service tag to all log records."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        return True


def setup_logging(log_dir: Path, level: str = "INFO", service: str = "app") -> None:
    """Configure root logger once with console + daily rotating file handlers."""
    root = logging.getLogger()
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(resolved_level)

    service_filter = _ServiceFilter(service=service)

    if not any(getattr(handler, "_investment_console", False) for handler in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(resolved_level)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        console_handler.addFilter(service_filter)
        console_handler._investment_console = True  # type: ignore[attr-defined]
        root.addHandler(console_handler)

    if not any(getattr(handler, "_investment_daily_file", False) for handler in root.handlers):
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / "investment_assistant.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(resolved_level)
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        file_handler.addFilter(service_filter)
        file_handler._investment_daily_file = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return module logger."""
    return logging.getLogger(name)
