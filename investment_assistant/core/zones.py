"""
Zone store: CRUD for support/resistance zones using SQLAlchemy ORM.
All functions return Zone ORM objects directly (no dict conversion).
"""
from __future__ import annotations
from typing import Optional

from investment_assistant.infra.time import utc_now
from investment_assistant.database import get_session, Zone


_STRENGTH_VALUES = {"strong", "medium", "weak"}


def _normalize_strength(strength: str) -> str:
    key = (strength or "").strip().lower()
    if key not in _STRENGTH_VALUES:
        raise ValueError(f"Invalid strength: {strength}")
    return key


# ── Write ─────────────────────────────────────────────────────────────────────

def add_zone(symbol: str, low: float, high: float,
             strength: str, note: str = "") -> int:
    """Insert a new zone. Returns the new zone id."""
    normalized_strength = _normalize_strength(strength)
    assert low < high, "low must be less than high"
    
    with get_session() as session:
        zone = Zone(
            symbol=symbol.upper(),
            low=low,
            high=high,
            strength=normalized_strength,
            note=note,
            is_active=1,
        )
        session.add(zone)
        session.flush()  # ensure id is assigned
        zone_id = zone.id
    
    return zone_id


def update_zone(zone_id: int, **kwargs) -> Zone:
    """
    Update one or more fields of an existing zone.
    Allowed keys: low, high, strength, note, is_active
    Returns the updated Zone ORM object.
    """
    allowed = {"low", "high", "strength", "note", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    
    with get_session() as session:
        zone = session.query(Zone).filter(Zone.id == zone_id).first()
        if not zone:
            raise ValueError(f"Zone {zone_id} not found")
        
        for key, val in updates.items():
            if key == "strength":
                val = _normalize_strength(val)
            setattr(zone, key, val)
        zone.updated_at = utc_now()
    
    return zone


def deactivate_zone(zone_id: int) -> Zone:
    """Soft-delete: mark zone inactive. Returns updated Zone object."""
    return update_zone(zone_id, is_active=0)


def flip_zone(zone_id: int, note_suffix: str = "⇄ flipped") -> Zone:
    """
    Confirm a flip suggested by the alert engine.
    Keeps the price range but appends a note so history is preserved.
    Returns the updated Zone object.
    """
    with get_session() as session:
        zone = session.query(Zone).filter(Zone.id == zone_id).first()
        if not zone:
            raise ValueError(f"Zone {zone_id} not found")
        
        existing = zone.note or ""
        new_note = f"{existing} [{note_suffix}]".strip()
        zone.note = new_note
        zone.updated_at = utc_now()
    
    return zone


# ── Read ──────────────────────────────────────────────────────────────────────

def get_zones(symbol: str, active_only: bool = True) -> list[Zone]:
    """Return all Zone ORM objects for a symbol, ordered by low price."""
    with get_session() as session:
        query = session.query(Zone).filter(Zone.symbol == symbol.upper())
        if active_only:
            query = query.filter(Zone.is_active == 1)
        zones = query.order_by(Zone.low).all()
        # Force load all attributes before exiting session
        for z in zones:
            _ = z.id, z.symbol, z.low, z.high, z.strength, z.note, z.is_active, z.created_at, z.updated_at
    
    return zones


def get_zone_by_id(zone_id: int) -> Optional[Zone]:
    """Get a single Zone ORM object by id."""
    with get_session() as session:
        zone = session.query(Zone).filter(Zone.id == zone_id).first()
        if zone:
            # Force load all attributes before exiting session
            _ = zone.id, zone.symbol, zone.low, zone.high, zone.strength, zone.note, zone.is_active, zone.created_at, zone.updated_at
    
    return zone


def get_all_active_zones() -> dict[str, list[Zone]]:
    """Return {symbol: [Zone ORM objects]} for every symbol that has active zones."""
    with get_session() as session:
        zones = (
            session.query(Zone)
            .filter(Zone.is_active == 1)
            .order_by(Zone.symbol, Zone.low)
            .all()
        )
        
        result: dict[str, list[Zone]] = {}
        for z in zones:
            # Force load all attributes before exiting session
            _ = z.id, z.symbol, z.low, z.high, z.strength, z.note, z.is_active, z.created_at, z.updated_at
            result.setdefault(z.symbol, []).append(z)
        
        return result

