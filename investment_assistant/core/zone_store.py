"""
Zone store: CRUD for support/resistance zones.
All persistence goes through this module — callers never touch DB directly.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from core.database import get_conn


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Write ─────────────────────────────────────────────────────────────────────

def add_zone(symbol: str, low: float, high: float,
             strength: str, note: str = "") -> int:
    """Insert a new zone. Returns the new zone id."""
    assert strength in ("强", "中", "弱"), f"Invalid strength: {strength}"
    assert low < high, "low must be less than high"
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO zones (symbol, low, high, strength, note, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (symbol.upper(), low, high, strength, note, now, now),
        )
    return cur.lastrowid


def update_zone(zone_id: int, **kwargs) -> None:
    """
    Update one or more fields of an existing zone.
    Allowed keys: low, high, strength, note, is_active
    """
    allowed = {"low", "high", "strength", "note", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [zone_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE zones SET {sets} WHERE id = ?", vals)


def deactivate_zone(zone_id: int) -> None:
    """Soft-delete: mark zone inactive instead of deleting."""
    update_zone(zone_id, is_active=0)


def flip_zone(zone_id: int, note_suffix: str = "⇄ flipped") -> None:
    """
    Confirm a flip suggested by the alert engine.
    Keeps the price range but appends a note so history is preserved.
    The caller decides what 'flip' means semantically — the zone itself
    is neutral; its relationship to current price determines support vs resistance.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT note FROM zones WHERE id = ?", (zone_id,)).fetchone()
    if not row:
        return
    existing = row["note"] or ""
    new_note = f"{existing} [{note_suffix}]".strip()
    update_zone(zone_id, note=new_note)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_zones(symbol: str, active_only: bool = True) -> list[dict]:
    """Return all zones for a symbol, ordered by low price."""
    query = "SELECT * FROM zones WHERE symbol = ?"
    params: list = [symbol.upper()]
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY low"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_zone_by_id(zone_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM zones WHERE id = ?", (zone_id,)).fetchone()
    return dict(row) if row else None


def get_all_active_zones() -> dict[str, list[dict]]:
    """Return {symbol: [zones]} for every symbol that has active zones."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM zones WHERE is_active = 1 ORDER BY symbol, low"
        ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["symbol"], []).append(dict(r))
    return result
