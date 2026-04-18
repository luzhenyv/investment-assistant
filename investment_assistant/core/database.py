"""
Database layer. All schema definitions live here.
Storage backend is SQLite via Python's stdlib — no ORM dependency.

To migrate to PostgreSQL later: replace get_conn() with a psycopg2
connection; all SQL in this codebase uses standard SQL-92 syntax.
"""
import sqlite3
from pathlib import Path
from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call repeatedly."""
    with get_conn() as conn:
        conn.executescript("""
        -- ── OHLCV cache ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol      TEXT    NOT NULL,
            date        TEXT    NOT NULL,   -- ISO-8601: YYYY-MM-DD
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol ON ohlcv (symbol);

        -- ── Support / resistance zones ────────────────────────────────
        CREATE TABLE IF NOT EXISTS zones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            low         REAL    NOT NULL,
            high        REAL    NOT NULL,
            strength    TEXT    NOT NULL CHECK (strength IN ('强','中','弱')),
            note        TEXT    DEFAULT '',
            is_active   INTEGER DEFAULT 1,  -- 1 = active, 0 = archived
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_zones_symbol ON zones (symbol, is_active);

        -- ── Alert log ─────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL,
            price           REAL    NOT NULL,
            zone_id         INTEGER REFERENCES zones(id),
            trigger_type    TEXT    NOT NULL CHECK (trigger_type IN ('open','close')),
            flip_suggested  INTEGER DEFAULT 0,
            sent_at         TEXT    NOT NULL
        );

        -- ── Trade journal ─────────────────────────────────────────────
        -- Phase 1: append-only log. Fields match the PRD Trade Unit.
        CREATE TABLE IF NOT EXISTS journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            action      TEXT    NOT NULL CHECK (action IN ('buy','sell','shadow')),
            price       REAL,
            shares      REAL,
            note        TEXT    DEFAULT '',
            is_shadow   INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL
        );
        """)
    print(f"[db] Initialised → {DB_PATH}")


if __name__ == "__main__":
    init_db()
