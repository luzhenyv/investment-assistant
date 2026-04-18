"""Zone model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Index, Integer, String, Text

from investment_assistant.database.base import Base


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_zones_symbol_active", "symbol", "is_active"),
        CheckConstraint("strength IN ('strong', 'medium', 'weak')", name="chk_strength"),
        CheckConstraint("low < high", name="chk_low_high"),
    )
