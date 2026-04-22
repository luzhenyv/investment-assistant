"""Database initialization helpers."""
from investment_assistant.database.base import Base
from investment_assistant.database.session import engine, database_url
from sqlalchemy import text

# Ensure all model modules are imported so metadata has all tables.
from investment_assistant.database.models import (  # noqa: F401
    Alert,
    Journal,
    OHLCV,
    WatchlistAlias,
    WatchlistItem,
    Zone,
)


def _legacy_zones_schema_exists(conn) -> bool:
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='zones'")
    ).first()
    if not row or not row[0]:
        return False
    ddl = row[0].lower()
    # Legacy schema used VARCHAR(2) for strength and non-English check values.
    return "strength varchar(2)" in ddl or ("chk_strength" in ddl and "'strong'" not in ddl)


def _migrate_legacy_zones_schema(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE zones_new (
                id INTEGER NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                low FLOAT NOT NULL,
                high FLOAT NOT NULL,
                strength VARCHAR(10) NOT NULL,
                note TEXT,
                is_active INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT chk_strength CHECK (strength IN ('strong', 'medium', 'weak')),
                CONSTRAINT chk_low_high CHECK (low < high)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO zones_new (id, symbol, low, high, strength, note, is_active, created_at, updated_at)
            SELECT
                id,
                symbol,
                low,
                high,
                CASE
                    WHEN hex(CAST(strength AS BLOB)) = 'E5BCBA' THEN 'strong'
                    WHEN hex(CAST(strength AS BLOB)) = 'E4B8AD' THEN 'medium'
                    WHEN hex(CAST(strength AS BLOB)) = 'E5BCB1' THEN 'weak'
                    WHEN lower(strength) IN ('strong', 'medium', 'weak') THEN lower(strength)
                    ELSE 'medium'
                END,
                note,
                COALESCE(is_active, 1),
                created_at,
                updated_at
            FROM zones
            """
        )
    )
    conn.execute(text("DROP TABLE zones"))
    conn.execute(text("ALTER TABLE zones_new RENAME TO zones"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_zones_symbol ON zones (symbol)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_zones_symbol_active ON zones (symbol, is_active)"))


def _run_migrations() -> None:
    if not database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        if _legacy_zones_schema_exists(conn):
            _migrate_legacy_zones_schema(conn)


def init_db() -> None:
    """Create all tables and run migrations if needed."""
    Base.metadata.create_all(engine)
    _run_migrations()
    print(f"[db] Initialised -> {database_url}")
