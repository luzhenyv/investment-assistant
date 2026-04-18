"""Backward-compatible facade for database APIs.

The implementation has been split into the `investment_assistant.database`
package with focused files (session, models, init, legacy).
"""

from investment_assistant.database import (
    Alert,
    Base,
    Journal,
    OHLCV,
    SessionLocal,
    Zone,
    engine,
    get_conn,
    get_session,
    init_db,
)

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


if __name__ == "__main__":
    init_db()

