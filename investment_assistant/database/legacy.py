"""Legacy compatibility helpers."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager


@contextmanager
def get_conn() -> sqlite3.Connection:
    """Deprecated helper retained for backward compatibility."""
    raise RuntimeError(
        "Raw SQL via get_conn() is no longer supported. "
        "Use get_session() with ORM models instead:\n"
        "  with get_session() as session:\n"
        "      zone = session.query(Zone).filter(...).first()"
    )
