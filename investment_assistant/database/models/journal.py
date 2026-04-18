"""Journal model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Integer, String, Text

from investment_assistant.database.base import Base


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        CheckConstraint("action IN ('buy', 'sell', 'shadow')", name="chk_action"),
    )
