"""Zone model."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Index, Integer, String, Text

from investment_assistant.database.base import Base
from investment_assistant.infra.time import utc_now


class Zone(Base):
    """Support/resistance zones with strength and active status."""

    __tablename__ = "zones"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    low = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    strength = Column(String(10), nullable=False)  # "strong", "medium", "weak"
    note = Column(Text, default="")
    is_active = Column(Integer, default=1)  # 1 = active, 0 = archived
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_zones_symbol_active", "symbol", "is_active"),
        CheckConstraint("strength IN ('strong', 'medium', 'weak')", name="chk_strength"),
        CheckConstraint("low < high", name="chk_low_high"),
    )
