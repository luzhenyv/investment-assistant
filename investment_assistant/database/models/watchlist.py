"""Watchlist models."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from investment_assistant.database.base import Base
from investment_assistant.infra.time import utc_now


class WatchlistItem(Base):
    """Canonical watchlist symbol with soft-delete state."""

    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True)
    canonical_symbol = Column(String(20), nullable=False, unique=True, index=True)
    is_active = Column(Integer, default=1, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    deactivated_at = Column(DateTime, nullable=True)


class WatchlistAlias(Base):
    """Data-source specific symbol aliases for a canonical symbol."""

    __tablename__ = "watchlist_aliases"

    id = Column(Integer, primary_key=True)
    watchlist_id = Column(Integer, ForeignKey("watchlist_items.id"), nullable=False, index=True)
    source_name = Column(String(30), nullable=False)
    source_symbol = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_name", "source_symbol", name="uq_watchlist_alias_source_symbol"),
        UniqueConstraint("watchlist_id", "source_name", name="uq_watchlist_alias_watchlist_source"),
        Index("idx_watchlist_alias_source_name", "source_name"),
    )
