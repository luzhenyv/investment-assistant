"""Public database API.

This package replaces the older single-file core.database module.
"""

from investment_assistant.database.base import Base
from investment_assistant.database.init_db import init_db
from investment_assistant.database.legacy import get_conn
from investment_assistant.database.models import Alert, Journal, OHLCV, Zone
from investment_assistant.database.session import SessionLocal, engine, get_session

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_session",
    "OHLCV",
    "Zone",
    "Alert",
    "Journal",
    "init_db",
    "get_conn",
]
