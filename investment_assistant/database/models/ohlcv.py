"""OHLCV model."""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Index, Integer, String

from investment_assistant.database.base import Base
from investment_assistant.infra.time import utc_now


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
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index("idx_ohlcv_symbol_date", "symbol", "date", unique=True),
    )
