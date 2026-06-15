"""Load the portfolio YAML and compute weights / cash band. Pure given inputs."""
from __future__ import annotations

import yaml

from quant.models import Holding


def load_portfolio(path: str) -> tuple[float, dict[str, Holding]]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    cash = float(data.get("cash", 0))
    holdings: dict[str, Holding] = {}
    for symbol, pos in (data.get("positions") or {}).items():
        holdings[symbol] = Holding(
            symbol=symbol,
            core=float(pos.get("core", 0)),
            trading=float(pos.get("trading", 0)),
            avg_cost=float(pos.get("avg_cost", 0)),
        )
    return cash, holdings


def portfolio_value(cash: float, holdings: dict[str, Holding], prices: dict[str, float]) -> float:
    equity = sum(h.shares * prices.get(sym, 0.0) for sym, h in holdings.items())
    return cash + equity


def current_weights(
    holdings: dict[str, Holding], prices: dict[str, float], total_value: float
) -> dict[str, float]:
    if total_value <= 0:
        return {sym: 0.0 for sym in holdings}
    return {
        sym: (h.shares * prices.get(sym, 0.0)) / total_value
        for sym, h in holdings.items()
    }


def cash_status(cash: float, total_value: float, cash_band: dict) -> str:
    """Return 'low', 'high', or 'ok' relative to the configured band."""
    if total_value <= 0:
        return "ok"
    frac = cash / total_value
    if frac < cash_band.get("min", 0.0):
        return "low"
    if frac > cash_band.get("max", 1.0):
        return "high"
    return "ok"
