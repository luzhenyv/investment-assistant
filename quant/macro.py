"""Derive a coarse macro backdrop from FRED series. Pure function — the macro analogue of
quant/market.py. Report-only context that runs PARALLEL to MarketState: it never feeds
market.detect_market, scoring, or decision, so the deterministic engine stays backtestable.

Reads are framed for a long-duration AI/tech equity book: real-yield direction (the duration
tail/headwind), credit spreads (risk-on/off), and financial conditions (loose/tight)."""
from __future__ import annotations

from quant.models import MacroState

# Thresholds over the fetch window (providers.fetch_macro change_days, default 21 calendar days).
# Yields are in percent; a 0.10 change = 10bps. Override under config `macro.thresholds`.
DEFAULTS = {
    "rate_move": 0.10,     # 10y move to call rising/falling (else flat)
    "real_move": 0.10,     # DFII10 move to call a duration head/tailwind
    "curve_flat": 0.20,    # 2s10s below this (and >= 0) reads flat
    "hy_wide": 4.0,        # HY OAS above this = stressed
    "hy_tight": 3.0,       # HY OAS below this (and not widening) = calm
    "hy_widen": 0.30,      # HY OAS widening more than this over the window = risk-off
    "nfci_loose": -0.10,   # NFCI below this = loose conditions
    "nfci_tight": 0.10,    # NFCI above this = tight conditions
}


def _chgfmt(change: float | None, unit: str = "pp") -> str:
    return "" if change is None else f", {change:+.2f}{unit}"


def _backdrop(real: str, credit: str, fin: str) -> str:
    duration = {"tailwind": "duration tailwind", "headwind": "duration headwind",
                "neutral": "duration neutral"}[real]
    creditw = {"risk-on": "credit calm", "risk-off": "credit stress",
               "neutral": "credit neutral"}[credit]
    condw = {"loose": "conditions loose", "tight": "conditions tight",
             "neutral": "conditions neutral"}[fin]
    return f"{duration}, {creditw}, {condw}"


def detect_macro(series: dict, cfg: dict) -> MacroState:
    """series: {series_id: {level, prev, change}} from providers.fetch_macro."""
    t = {**DEFAULTS, **cfg.get("macro", {}).get("thresholds", {})}

    def lvl(sid: str) -> float | None:
        return series.get(sid, {}).get("level")

    def chg(sid: str) -> float | None:
        return series.get(sid, {}).get("change")

    notes: list[str] = []

    # 10y nominal — rate direction
    dgs10, d10c = lvl("DGS10"), chg("DGS10")
    rates_direction = "flat"
    if d10c is not None:
        rates_direction = "rising" if d10c > t["rate_move"] else "falling" if d10c < -t["rate_move"] else "flat"
    if dgs10 is not None:
        notes.append(f"10y {dgs10:.2f}% ({rates_direction}{_chgfmt(d10c)})")

    # 2s10s — curve shape
    dgs2 = lvl("DGS2")
    curve = "n/a"
    if dgs10 is not None and dgs2 is not None:
        spread = dgs10 - dgs2
        curve = "inverted" if spread < 0 else "flat" if spread < t["curve_flat"] else "normal"
        notes.append(f"2s10s {spread * 100:+.0f}bps ({curve})")

    # 10y real (DFII10) — the duration head/tailwind
    real, realc = lvl("DFII10"), chg("DFII10")
    real_yield_regime = "neutral"
    if realc is not None:
        real_yield_regime = "headwind" if realc > t["real_move"] else "tailwind" if realc < -t["real_move"] else "neutral"
    if real is not None:
        notes.append(f"10y real {real:.2f}% — duration {real_yield_regime}{_chgfmt(realc)}")

    # 10y breakeven inflation (context only)
    bei = lvl("T10YIE")
    if bei is not None:
        notes.append(f"10y breakeven {bei:.2f}%{_chgfmt(chg('T10YIE'))}")

    # HY OAS credit spread — risk-on/off
    hy, hyc = lvl("BAMLH0A0HYM2"), chg("BAMLH0A0HYM2")
    credit = "neutral"
    if hy is not None:
        widening = hyc is not None and hyc > t["hy_widen"]
        if hy > t["hy_wide"] or widening:
            credit = "risk-off"
        elif hy < t["hy_tight"] and (hyc is None or hyc <= 0):
            credit = "risk-on"
        notes.append(f"HY spread {hy:.2f}% ({credit}{_chgfmt(hyc)})")

    # NFCI — financial conditions
    nfci = lvl("NFCI")
    fin_conditions = "neutral"
    if nfci is not None:
        fin_conditions = "loose" if nfci < t["nfci_loose"] else "tight" if nfci > t["nfci_tight"] else "neutral"
        notes.append(f"NFCI {nfci:+.2f} ({fin_conditions})")

    return MacroState(
        series=series,
        backdrop=_backdrop(real_yield_regime, credit, fin_conditions),
        rates_direction=rates_direction, curve=curve, real_yield_regime=real_yield_regime,
        credit=credit, fin_conditions=fin_conditions, notes=notes,
    )
