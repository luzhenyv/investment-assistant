"""
Alert engine.

Two responsibilities:
  1. zone_checker  — did today's open/close touch any zone?
  2. flip_detector — should a zone be suggested for flipping?

Both are pure functions: given price + zones → return alerts.
No side effects. Persistence and notification happen in the caller.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from investment_assistant.infra.time import utc_now
from investment_assistant.config import SETTINGS


TriggerType = Literal["open", "close"]


@dataclass
class Alert:
    symbol: str
    price: float
    zone: dict
    trigger_type: TriggerType
    flip_suggested: bool = False
    sent_at: str = field(default_factory=lambda: utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))

    @property
    def zone_label(self) -> str:
        z = self.zone
        return f"{z['low']:.2f}-{z['high']:.2f}({z['strength']})"

    @property
    def direction_emoji(self) -> str:
        """▼ if price is near/below zone low (approaching support),
           ▲ if price is near/above zone high (approaching resistance)."""
        mid = (self.zone["low"] + self.zone["high"]) / 2
        return "📉" if self.price <= mid else "📈"


# ── Core detection logic ───────────────────────────────────────────────────────

def _price_in_zone(price: float, zone: dict) -> bool:
    return zone["low"] <= price <= zone["high"]


def _flip_suggested(price: float, zone: dict) -> bool:
    """
    Suggest a flip when price has moved decisively beyond a zone edge.
    Beyond low by FLIP_THRESHOLD_PCT  → former support may be new resistance.
    Beyond high by FLIP_THRESHOLD_PCT → former resistance may be new support.
    """
    pct = SETTINGS.flip_threshold_pct / 100
    below = price < zone["low"] * (1 - pct)
    above = price > zone["high"] * (1 + pct)
    return below or above


def check_zones(symbol: str, open_price: float, close_price: float,
                zones: list[dict]) -> list[Alert]:
    """
    Compare today's open and close against all active zones.
    Returns a list of Alert objects (may be empty).
    """
    alerts: list[Alert] = []
    prices: list[tuple[float, TriggerType]] = [
        (open_price,  "open"),
        (close_price, "close"),
    ]
    for price, trigger in prices:
        if price is None:
            continue
        for zone in zones:
            if _price_in_zone(price, zone):
                flip = _flip_suggested(close_price, zone)   # always check close for flip
                alerts.append(Alert(
                    symbol=symbol,
                    price=price,
                    zone=zone,
                    trigger_type=trigger,
                    flip_suggested=flip,
                ))
    # Deduplicate: if both open AND close hit the same zone, keep close only
    seen: set[int] = set()
    deduped: list[Alert] = []
    for a in reversed(alerts):          # close comes last → wins
        zid = a.zone["id"]
        if zid not in seen:
            seen.add(zid)
            deduped.append(a)
    return deduped


def run_alert_check(symbol: str, zones: list[dict],
                    open_price: float | None,
                    close_price: float | None) -> list[Alert]:
    """Entry point used by the scheduler. Handles None prices gracefully."""
    if not zones or (open_price is None and close_price is None):
        return []
    return check_zones(
        symbol,
        open_price  or 0.0,
        close_price or 0.0,
        zones,
    )
