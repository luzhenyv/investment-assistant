"""Configuration and portfolio loading utilities for core.

Parses portfolio, watchlist, and strategy config files without importing any legacy quant packages.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    core: float
    trading: float
    avg_cost: float
    plan: str = ""

    @property
    def shares(self) -> float:
        return self.core + self.trading


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_watchlist(path: str) -> list[str]:
    """Load the flat list of watchlist symbols."""
    data = load_yaml(path)
    return data.get("symbols") or []


def load_portfolio(path: str) -> tuple[float, dict[str, Holding], list[str]]:
    """Load the portfolio cash, holdings, and pre-position symbols.
    
    Supports pre_positions configured either as a list:
      pre_positions:
        - TSM
        - AMD
    or as a dictionary:
      pre_positions:
        TSM: {plan: "wait for breakout"}
    """
    data = load_yaml(path)
    cash = float(data.get("cash", 0.0))
    
    holdings: dict[str, Holding] = {}
    for symbol, pos in (data.get("positions") or {}).items():
        holdings[symbol] = Holding(
            symbol=symbol,
            core=float(pos.get("core", 0.0)),
            trading=float(pos.get("trading", 0.0)),
            avg_cost=float(pos.get("avg_cost", 0.0)),
            plan=str(pos.get("plan", "")).strip(),
        )
        
    pre_positions_raw = data.get("pre_positions") or []
    if isinstance(pre_positions_raw, dict):
        pre_positions = list(pre_positions_raw.keys())
    else:
        pre_positions = list(pre_positions_raw)
        
    return cash, holdings, sorted(pre_positions)
