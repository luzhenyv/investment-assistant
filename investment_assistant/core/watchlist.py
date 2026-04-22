"""Watchlist service with alias support and soft-delete semantics."""
from __future__ import annotations

import re
from typing import Literal

from investment_assistant.config import SETTINGS
from investment_assistant.database import WatchlistAlias, WatchlistItem, get_session
from investment_assistant.infra.time import utc_now
from investment_assistant.services.prices import probe_yfinance_symbol

DEFAULT_SOURCE = "yfinance"
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,19}$")

AddStatus = Literal["added", "exists", "reactivated"]


def normalize_symbol_input(symbol: str) -> str:
    """Normalize and validate a user-provided symbol."""
    normalized = (symbol or "").strip().upper()
    if not normalized:
        raise ValueError("Symbol cannot be empty")
    if not _SYMBOL_RE.match(normalized):
        raise ValueError("Invalid symbol format")
    return normalized


def canonicalize_symbol(symbol: str) -> str:
    """Map equivalent separators into one canonical symbol form."""
    return symbol.replace("-", ".")


def _yfinance_candidates(raw_symbol: str, canonical_symbol: str) -> list[str]:
    candidates = [
        raw_symbol,
        canonical_symbol,
        canonical_symbol.replace(".", "-"),
        canonical_symbol.replace("-", "."),
    ]
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _ensure_seeded() -> None:
    """Seed watchlist rows from settings on first run."""
    with get_session() as session:
        has_rows = session.query(WatchlistItem.id).first() is not None
        if has_rows:
            return

        for raw_symbol in SETTINGS.watchlist:
            normalized = normalize_symbol_input(raw_symbol)
            canonical = canonicalize_symbol(normalized)
            item = WatchlistItem(
                canonical_symbol=canonical,
                is_active=1,
            )
            session.add(item)
            session.flush()
            session.add(
                WatchlistAlias(
                    watchlist_id=item.id,
                    source_name=DEFAULT_SOURCE,
                    source_symbol=normalized,
                )
            )


def resolve_symbol_for_source(symbol: str, source_name: str = DEFAULT_SOURCE) -> str:
    """Resolve source-specific symbol from canonical symbol (or equivalent input)."""
    raw = normalize_symbol_input(symbol)
    canonical = canonicalize_symbol(raw)

    with get_session() as session:
        item = session.query(WatchlistItem).filter(
            WatchlistItem.canonical_symbol == canonical
        ).first()
        if not item:
            return canonical

        alias = session.query(WatchlistAlias).filter(
            WatchlistAlias.watchlist_id == item.id,
            WatchlistAlias.source_name == source_name,
        ).first()
        if alias:
            return alias.source_symbol

    return canonical


def get_watchlist_symbols(active_only: bool = True, source_name: str | None = None) -> list[str]:
    """Return watchlist symbols in canonical or source-specific format."""
    _ensure_seeded()

    with get_session() as session:
        query = session.query(WatchlistItem)
        if active_only:
            query = query.filter(WatchlistItem.is_active == 1)
        rows = query.order_by(WatchlistItem.canonical_symbol).all()
        symbols = [row.canonical_symbol for row in rows]

    if source_name:
        return [resolve_symbol_for_source(symbol, source_name) for symbol in symbols]
    return symbols


def _get_yfinance_symbol_or_raise(raw_symbol: str, canonical_symbol: str) -> str:
    for candidate in _yfinance_candidates(raw_symbol, canonical_symbol):
        if probe_yfinance_symbol(candidate):
            return candidate
    raise ValueError(f"Illegal or unsupported symbol for yfinance: {raw_symbol}")


def add_watchlist_symbol(symbol: str) -> dict[str, str]:
    """Add or reactivate a symbol after yfinance legality validation."""
    _ensure_seeded()

    raw = normalize_symbol_input(symbol)
    canonical = canonicalize_symbol(raw)
    yfinance_symbol = _get_yfinance_symbol_or_raise(raw, canonical)

    with get_session() as session:
        item = session.query(WatchlistItem).filter(
            WatchlistItem.canonical_symbol == canonical
        ).first()

        status: AddStatus
        if item:
            if item.is_active == 1:
                status = "exists"
            else:
                item.is_active = 1
                item.deactivated_at = None
                item.updated_at = utc_now()
                status = "reactivated"
        else:
            item = WatchlistItem(
                canonical_symbol=canonical,
                is_active=1,
            )
            session.add(item)
            session.flush()
            status = "added"

        alias = session.query(WatchlistAlias).filter(
            WatchlistAlias.watchlist_id == item.id,
            WatchlistAlias.source_name == DEFAULT_SOURCE,
        ).first()
        if alias:
            alias.source_symbol = yfinance_symbol
        else:
            session.add(
                WatchlistAlias(
                    watchlist_id=item.id,
                    source_name=DEFAULT_SOURCE,
                    source_symbol=yfinance_symbol,
                )
            )

    return {
        "status": status,
        "canonical_symbol": canonical,
        "source_symbol": yfinance_symbol,
    }


def remove_watchlist_symbol(symbol: str) -> bool:
    """Soft-delete watchlist membership by marking the row inactive."""
    _ensure_seeded()

    canonical = canonicalize_symbol(normalize_symbol_input(symbol))

    with get_session() as session:
        item = session.query(WatchlistItem).filter(
            WatchlistItem.canonical_symbol == canonical
        ).first()
        if not item:
            return False
        if item.is_active == 1:
            item.is_active = 0
            item.deactivated_at = utc_now()
            item.updated_at = utc_now()

    return True
