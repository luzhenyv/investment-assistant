"""Derive a sector-rotation backdrop from a configurable ETF map. Pure function — the sector
analogue of quant/macro.py. Report-only context that runs PARALLEL to MarketState/MacroState: it
never feeds market.detect_market, scoring, or decision, so the deterministic engine stays
backtestable.

Per equity ETF (sector / thematic / breadth groups) it measures relative strength vs SPY on two
horizons and maps them to a Relative-Rotation-Graph quadrant:
    rs_slow (medium-term level) × rs_fast (short-term momentum)
    Leading (slow≥0, fast≥0) · Weakening (slow≥0, fast<0) · Lagging (slow<0, fast<0) · Improving (slow<0, fast≥0)
So a structural leader that is fading short-term reads "Weakening" (e.g. semis pulling back after a
huge run). Cross-asset ETFs (TLT/GLD/HYG) drive a one-line risk radar that complements the (lagging)
FRED macro block."""
from __future__ import annotations

from typing import TYPE_CHECKING

from quant import indicators
from quant.models import SectorRow, SectorState

if TYPE_CHECKING:
    import polars as pl

    from quant.models import Signal

# Groups whose members get an RRG quadrant (benchmarked to SPY). `cross_asset` is the risk radar.
_EQUITY_GROUPS = ("sector", "thematic", "breadth")


def _quadrant(rs_slow: float, rs_fast: float) -> str:
    if rs_slow >= 0:
        return "Leading" if rs_fast >= 0 else "Weakening"
    return "Improving" if rs_fast >= 0 else "Lagging"


def _day_change(close: pl.Series) -> float:
    if close.len() < 2:
        return 0.0
    prev = float(close.tail(2).head(1).item())
    return float(close.tail(1).item()) / prev - 1.0 if prev else 0.0


def _return_z(close: pl.Series, lookback: int) -> float:
    """Z-score of the latest daily return vs the prior `lookback` daily returns (today excluded
    from the baseline). The 'abnormal move' measure. 0.0 when history is short or the window is flat."""
    rets = close.pct_change().drop_nulls()
    if rets.len() < lookback + 1:
        return 0.0
    today = float(rets.tail(1).item())
    prior = rets.tail(lookback + 1).head(lookback)
    mean, std = prior.mean(), prior.std()
    if not std:
        return 0.0
    return (today - float(mean)) / float(std)


def _risk_radar(history: dict, fast: int, slow: int) -> tuple[str, list[str]]:
    """A coarse risk-on/off read from cross-asset ETFs vs SPY. Each present tell casts a vote."""
    def ret(sym: str, lb: int) -> float | None:
        df = history.get(sym)
        return indicators.trailing_return(df["Close"], lb) if df is not None else None

    notes: list[str] = []
    score = 0
    spy_f, tlt_f = ret("SPY", fast), ret("TLT", fast)
    if spy_f is not None and tlt_f is not None:
        sb = spy_f - tlt_f
        score += 1 if sb > 0 else -1
        notes.append(f"stocks vs bonds (SPY−TLT {fast}d) {sb:+.1%} — "
                     f"{'stocks bid' if sb > 0 else 'bonds bid'}")
    hyg_f = ret("HYG", fast)
    if hyg_f is not None:
        score += 1 if hyg_f > 0 else -1
        notes.append(f"HY credit (HYG {fast}d) {hyg_f:+.1%} — "
                     f"{'firm' if hyg_f > 0 else 'soft'}")
    gld_s = ret("GLD", slow)
    if gld_s is not None:
        if gld_s > 0.05:
            score -= 1
        notes.append(f"gold (GLD {slow}d) {gld_s:+.1%}"
                     f"{' — strong bid (risk-off lean)' if gld_s > 0.05 else ''}")
    radar = "risk-on" if score >= 1 else "risk-off" if score <= -1 else "mixed"
    return radar, notes


def detect_rotation(
    sector_signals: dict[str, Signal], spy: Signal, history: dict, cfg: dict
) -> SectorState | None:
    """sector_signals: {etf: Signal} built by scoring.build_signal. history holds the OHLC frames
    (incl. 'SPY'). Returns None when no ETF data is available."""
    scfg = cfg.get("sectors", {})
    groups: dict[str, list[str]] = scfg.get("groups") or {}
    lb = scfg.get("lookbacks") or {}
    micro, fast, slow = int(lb.get("micro", 5)), int(lb.get("fast", 21)), int(lb.get("slow", 63))
    abn_z = float(scfg.get("abnormal_z", 2.0))

    sym_group = {s: g for g, syms in groups.items() for s in syms}
    spy_close = history["SPY"]["Close"] if "SPY" in history else None
    spy_micro = indicators.trailing_return(spy_close, micro) if spy_close is not None else 0.0
    spy_fast = indicators.trailing_return(spy_close, fast) if spy_close is not None else 0.0
    spy_slow = indicators.trailing_return(spy_close, slow) if spy_close is not None else 0.0

    rows: list[SectorRow] = []
    rotations: list[str] = []
    for sym, sig in sector_signals.items():
        df = history.get(sym)
        if df is None:
            continue
        close = df["Close"]
        group = sym_group.get(sym, "sector")
        is_equity = group in _EQUITY_GROUPS
        rs_micro = indicators.trailing_return(close, micro) - spy_micro
        rs_fast = indicators.trailing_return(close, fast) - spy_fast
        rs_slow = indicators.trailing_return(close, slow) - spy_slow
        quadrant = _quadrant(rs_slow, rs_fast) if is_equity else "—"
        day = _day_change(close)
        move_z = _return_z(close, fast)

        flags: list[str] = []
        if sig.vol_state != "Normal":
            flags.append(f"{sig.vol_state} volume")
        if abs(move_z) >= abn_z:
            flags.append(f"Abnormal move ({move_z:+.1f}σ)")
        abnormal = abs(move_z) >= abn_z or sig.vol_state != "Normal"
        if is_equity and abnormal:
            if quadrant in ("Leading", "Weakening") and day < 0:
                flags.append("Leader pullback")
            elif quadrant in ("Lagging", "Improving") and day > 0:
                flags.append("Rotation-in attempt")
        # 5-day micro-momentum: catches a multi-day fade/revival even with no single abnormal day.
        if is_equity:
            if quadrant in ("Leading", "Weakening") and rs_micro < 0:
                flags.append("Leader fading (5d)")
            elif quadrant in ("Lagging", "Improving") and rs_micro > 0:
                flags.append("Turning up (5d)")

        rows.append(SectorRow(
            symbol=sym, group=group, state=sig.state, day_change_pct=day,
            rs_micro=rs_micro, rs_fast=rs_fast, rs_slow=rs_slow, quadrant=quadrant,
            rvol=round(sig.rvol, 2), vol_z=round(sig.vol_z, 2), vol_state=sig.vol_state,
            rsi=round(sig.rsi, 1), flags=flags,
        ))
        if flags:
            q = f"{quadrant} · " if is_equity else ""
            rotations.append(f"{sym} ({q}day {day:+.1%}) — {', '.join(flags)}")

    if not rows:
        return None

    # Sort: equity ETFs by relative strength (leaders first), cross-asset trailing.
    rows.sort(key=lambda r: (r.group == "cross_asset", -r.rs_slow))

    equity = [r for r in rows if r.group in _EQUITY_GROUPS]
    leaders = [r.symbol for r in equity if r.quadrant == "Leading"][:2]
    laggards = [r.symbol for r in equity if r.quadrant == "Lagging"][-2:]
    risk_radar, radar_notes = _risk_radar(history, fast, slow)

    parts = []
    if leaders:
        parts.append(f"{'/'.join(leaders)} leading")
    if laggards:
        parts.append(f"{'/'.join(laggards)} lagging")
    parts.append(risk_radar)
    backdrop = " · ".join(parts)

    tally = {q: sum(1 for r in equity if r.quadrant == q)
             for q in ("Leading", "Weakening", "Improving", "Lagging")}
    notes = [f"quadrants: " + ", ".join(f"{k} {v}" for k, v in tally.items() if v)]
    notes += radar_notes

    return SectorState(
        backdrop=backdrop, risk_radar=risk_radar, rows=rows, rotations=rotations, notes=notes,
    )
