"""Semi-automatic support/resistance: a human-curated `levels.yaml` that overrides the auto-detector.

The auto-detector (`quant/levels.py`) finds *where* zones are, but its exact bands/strength aren't
precise enough to act on. So a per-profile `levels.yaml` (seeded once by `scripts/gen_levels.py`, then
hand-edited) becomes the authoritative source: when a symbol is curated in the file, the engine uses
those zones; symbols absent from the file fall back to `detect_zones`. The file carries an `as_of`
date and *expires* after `levels.manual_refresh_days` — a stale curation is still loaded (never drop
the user's hand work) but flagged so the report nudges a re-review.

Same report-only contract as the auto detector: these zones never feed scoring/decision/backtest.
File format (beside config.yaml, like options.yaml):

    as_of: '2026-07-08'                 # file-level review date (per-symbol as_of overrides it)
    symbols:
      MU:
        as_of: '2026-07-08'
        zones:
          - {low: 819, high: 880, strength: strong, note: "2024 breakout retest"}
          - {low: 950, high: 1000, strength: medium}
"""
from __future__ import annotations

import datetime as dt
import os

import yaml

from quant import clock
from quant.models import Zone

# Ordinal strength vocabulary — identical to quant/levels.py labels (_LABELS).
_RANK = {"small": 1, "medium": 2, "strong": 3, "super-strong": 4}


def path_for(config_path: str) -> str:
    """`levels.yaml` sits beside `config.yaml` in the profile dir (mirrors options.yaml)."""
    return os.path.join(os.path.dirname(config_path), "levels.yaml")


def load(path: str) -> dict:
    """Parse the curated file; {} when it's absent (→ pure auto-detection, like before)."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _stale(as_of, refresh_days: int) -> bool:
    """True when the curation is older than refresh_days (or has no/parseable as_of).

    Uses the embedded as_of date, NOT file mtime — a human editing the file must not silently
    reset its freshness. Mirrors the refresh_days idiom in quant/providers.py."""
    if not as_of:
        return True
    try:
        return (clock.today() - dt.date.fromisoformat(str(as_of))).days > refresh_days
    except ValueError:
        return True


def _zone(entry: dict, price: float | None) -> Zone | None:
    """Build one Zone from a curated `{low, high, strength[, kind, note, flipped]}` entry.

    Returns None (with a printed warning) for a malformed entry — the file is hand-edited, so a
    bad row should skip, never crash the run. `kind` is derived from price when not given, exactly
    like quant/levels.py (support if the band sits at/below price, else resistance)."""
    try:
        low, high = float(entry["low"]), float(entry["high"])
    except (KeyError, TypeError, ValueError):
        print(f"  ! levels.yaml: skipping malformed zone (need numeric low/high): {entry!r}")
        return None
    lo, hi = min(low, high), max(low, high)
    label = str(entry.get("strength", "medium"))
    if label not in _RANK:
        print(f"  ! levels.yaml: unknown strength {label!r} in {entry!r} — treating as 'medium'")
        label = "medium"
    mid = (lo + hi) / 2.0
    kind = entry.get("kind") or ("support" if price is None or mid <= price else "resistance")
    return Zone(low=lo, high=hi, score=float(_RANK[label]), label=label, kind=kind,
                touches=0, methods=["manual"], timeframes=[], members=1,
                flipped=bool(entry.get("flipped", False)))


def zones_for(sym: str, price: float | None, data: dict,
              refresh_days: int) -> tuple[list[Zone], bool] | None:
    """Curated zones for `sym` as (zones, stale), or None when the symbol isn't in the file.

    None signals the caller to fall back to auto-detection. Zones are sorted strongest-first to
    match detect_zones' contract."""
    entry = (data.get("symbols") or {}).get(sym)
    if not entry:
        return None
    raw = entry.get("zones") or []
    zones = [z for z in (_zone(r, price) for r in raw) if z is not None]
    if not zones:
        return None
    zones.sort(key=lambda z: z.score, reverse=True)
    stale = _stale(entry.get("as_of") or data.get("as_of"), refresh_days)
    return zones, stale
