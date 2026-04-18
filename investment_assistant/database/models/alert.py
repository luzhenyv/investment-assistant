"""Alert model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String

from investment_assistant.database.base import Base


class Alert(Base):
    """Alert history for zone touches."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    price = Column(Float, nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    trigger_type = Column(String(10), nullable=False)  # "open" or "close"
    flip_suggested = Column(Integer, default=0)  # 1 = flip recommended
    sent_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("trigger_type IN ('open', 'close')", name="chk_trigger_type"),
    )
