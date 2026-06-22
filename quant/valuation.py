"""Turn a vendor-neutral fundamentals dict (from providers.fetch_fundamentals, any source)
into a Fundamentals snapshot + a coarse valuation read. Pure logic — no network.

The label is intentionally coarse (cheap/fair/rich): a single-vendor PEG and trailing
GAAP PE can't support a precise 0-100 score, and a false-precise number would invite
mechanical use of a hint that's meant for human judgment."""
from __future__ import annotations

from quant.models import Fundamentals


def _num(s) -> float | None:
    """Coerce a field to float. Handles native floats (yfinance) and strings (Alpha Vantage),
    treating "None"/"-"/""/NaN as missing -> None."""
    if s is None:
        return None
    text = str(s).strip()
    if text in ("", "None", "-", "NaN", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def valuation_label(pe: float | None, forward_pe: float | None, peg: float | None, cfg: dict) -> str:
    """Coarse valuation tag driven by PEG (growth-adjusted), with a cyclical-ramp note.

    fwd PE much lower than trailing PE means earnings are expected to grow into the
    valuation — exactly MU's case (trailing ~53, forward ~10) — so a high trailing PE
    alone shouldn't read as 'rich'."""
    fund = cfg.get("fundamentals", {})
    peg_cheap = fund.get("peg_cheap", 1.0)
    peg_rich = fund.get("peg_rich", 2.0)

    ramping = forward_pe is not None and pe is not None and pe > 0 and forward_pe < 0.6 * pe

    if peg is not None and peg > 0:
        if peg <= peg_cheap:
            base = "cheap (growth-justified)"
        elif peg > peg_rich:
            base = "rich"
        else:
            base = "fair"
    elif ramping:
        # No usable PEG but forward earnings ramp hard — not 'unknown', lean constructive.
        base = "fair"
    else:
        return "unknown"

    return f"{base} · fwd PE ≪ trailing" if ramping else base


def build(symbol: str, raw: dict, price: float, cfg: dict, *, stale: bool = False) -> Fundamentals:
    """Construct a Fundamentals from a canonical fundamentals dict + the symbol's current price.
    `raw` keys are vendor-neutral (see providers._FUND_KEYS), so any source maps in the same way."""
    pe = _num(raw.get("pe"))
    forward_pe = _num(raw.get("forward_pe"))
    peg = _num(raw.get("peg"))
    target = _num(raw.get("analyst_target"))
    upside = (target - price) / price if (target is not None and price) else None

    return Fundamentals(
        symbol=symbol,
        sector=(raw.get("sector") or None),
        pe=pe,
        forward_pe=forward_pe,
        peg=peg,
        pb=_num(raw.get("pb")),
        ev_ebitda=_num(raw.get("ev_ebitda")),
        profit_margin=_num(raw.get("profit_margin")),
        rev_growth=_num(raw.get("rev_growth")),
        eps_growth=_num(raw.get("eps_growth")),
        analyst_target=target,
        beta=_num(raw.get("beta")),
        upside_to_target=upside,
        valuation_label=valuation_label(pe, forward_pe, peg, cfg),
        as_of=str(raw.get("_fetched", "")),
        stale=stale,
    )
