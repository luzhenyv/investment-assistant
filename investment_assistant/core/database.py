"""
Database layer using SQLAlchemy ORM.

Supports SQLite (dev) and PostgreSQL (prod) via environment-driven connection string.
All models and CRUD operations go through this module.

To use PostgreSQL, set DATABASE_URL in .env:
  DATABASE_URL=postgresql+psycopg2://user:pass@localhost/dbname

Default (SQLite):
  DATABASE_URL=sqlite:///./data/trading.db
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime,
    ForeignKey, Index, CheckConstraint, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

from investment_assistant.config import SETTINGS


# ── Configuration ────────────────────────────────────────────────────────────

def _get_database_url() -> str:
    """Build SQLAlchemy database URL from SETTINGS."""
    # Support explicit DATABASE_URL env var for flexibility
    # Default to SQLite at SETTINGS.db_path
    db_path = SETTINGS.db_path
    if db_path is None:
        db_path = SETTINGS.data_dir / "trading.db"
    return f"sqlite:///{db_path}"


# ── Engine & Session ────────────────────────────────────────────────────────

_database_url = _get_database_url()
_is_sqlite = _database_url.startswith("sqlite")

if _is_sqlite:
    # SQLite: use StaticPool to avoid threading issues in sync context
    engine = create_engine(
        _database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    # PostgreSQL and others: use default pool
    engine = create_engine(_database_url, echo=False)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()


@contextmanager
def get_session() -> Session:
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Models ───────────────────────────────────────────────────────────────────

class OHLCV(Base):
    """Daily OHLCV price cache for stocks and macro indices."""
    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # ISO-8601: YYYY-MM-DD
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_ohlcv_symbol_date", "symbol", "date", unique=True),
    )


class Zone(Base):
    """Support/resistance zones with strength and active status."""
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    low = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    strength = Column(String(2), nullable=False)  # "强", "中", "弱"
    note = Column(Text, default="")
    is_active = Column(Integer, default=1)  # 1 = active, 0 = archived
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_zones_symbol_active", "symbol", "is_active"),
        CheckConstraint("strength IN ('强', '中', '弱')", name="chk_strength"),
        CheckConstraint("low < high", name="chk_low_high"),
    )


class Alert(Base):
    """Alert history: when zones were touched."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    price = Column(Float, nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    trigger_type = Column(String(10), nullable=False)  # "open" or "close"
    flip_suggested = Column(Integer, default=0)  # 1 = flip recommended
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("trigger_type IN ('open', 'close')", name="chk_trigger_type"),
    )


class Journal(Base):
    """Trade journal: append-only log of buy/sell actions."""
    __tablename__ = "journal"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # ISO-8601: YYYY-MM-DD
    action = Column(String(10), nullable=False)  # "buy", "sell", "shadow"
    price = Column(Float)
    shares = Column(Float)
    note = Column(Text, default="")
    is_shadow = Column(Integer, default=0)  # 1 = hypothetical trade
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("action IN ('buy', 'sell', 'shadow')", name="chk_action"),
    )



# ── Initialization ───────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and run migrations if needed."""
    Base.metadata.create_all(engine)
    print(f"[db] Initialised → {_database_url}")


# ── Legacy helper for backward compatibility ────────────────────────────────
# (Deprecated: prefer using get_session() and models directly)

import sqlite3
@contextmanager
def get_conn() -> sqlite3.Connection:
    """
    Legacy: raises error directing users to ORM-based get_session().
    This project no longer supports raw SQL.
    """
    raise RuntimeError(
        "Raw SQL via get_conn() is no longer supported. "
        "Use get_session() with ORM models instead:\n"
        "  with get_session() as session:\n"
        "      zone = session.query(Zone).filter(...).first()"
    )


if __name__ == "__main__":
    init_db()

