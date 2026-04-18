"""Database engine and session management."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from investment_assistant.config import SETTINGS


def _get_database_url() -> str:
    """Build SQLAlchemy database URL from settings."""
    db_path = SETTINGS.db_path
    if db_path is None:
        db_path = SETTINGS.data_dir / "trading.db"
    return f"sqlite:///{db_path}"


database_url = _get_database_url()
is_sqlite = database_url.startswith("sqlite")

if is_sqlite:
    # SQLite: use StaticPool to avoid threading issues in sync context.
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    # PostgreSQL and others: use default pool.
    engine = create_engine(database_url, echo=False)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
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
