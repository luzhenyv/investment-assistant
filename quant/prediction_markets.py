"""Summarize forward-looking Polymarket event odds. Pure function — report-only context parallel to
the macro block (quant/macro.py); never feeds scoring/decision/backtest. The crowd-implied
probabilities are a forward prior the FRED macro lens can't give; the news-review skill reads them."""
from __future__ import annotations

from quant.models import PredictionMarketState

DEFAULTS = {
    "backdrop_n": 4,         # topics summarized in the one-line backdrop (one market each)
    "week_move_flag": 0.10,  # |1-week probability move| at/above this => a "big move" note (10pp)
    "min_prob": 0.03,        # drop near-0 uninformative buckets (a "how many Fed cuts" question splits
    "max_prob": 0.97,        # into many ~0% outcomes that dominate by volume); and near-certain markets
}


def _short(q: str, n: int = 44) -> str:
    q = (q or "").strip().rstrip("?")
    return q if len(q) <= n else q[:n].rstrip() + "…"


def analyze(raw: list[dict] | None, cfg: dict) -> PredictionMarketState:
    """Build the PredictionMarketState from provider rows (already filtered to forward-looking and
    ranked per topic). Keeps only INFORMATIVE markets (drops the near-0 / near-1 buckets that carry no
    signal but dominate by volume), composes a one-line backdrop with the highest-volume market PER
    TOPIC (one clean read per theme), and flags any market whose probability moved sharply this week."""
    t = {**DEFAULTS, **cfg.get("prediction_markets", {}).get("thresholds", {})}
    lo, hi = t["min_prob"], t["max_prob"]
    informative = [m for m in sorted(raw or [], key=lambda m: m.get("volume", 0), reverse=True)
                   if lo <= m.get("prob", 0) <= hi]
    # Backdrop: the highest-volume informative market per topic, deduped — avoids one bucketed
    # question (e.g. Fed cuts) crowding out the others.
    seen, per_topic = set(), []
    for m in informative:
        if m["topic"] in seen:
            continue
        seen.add(m["topic"])
        per_topic.append(m)
    parts = [f"{_short(m['question'])} {m['prob'] * 100:.0f}%" for m in per_topic[:t["backdrop_n"]]]
    backdrop = " · ".join(parts) if parts else "no prediction-market data"
    notes = []
    for m in informative:
        wc = m.get("week_change") or 0
        if abs(wc) >= t["week_move_flag"]:
            notes.append(f"{_short(m['question'])}: {m['prob'] * 100:.0f}% ({wc * 100:+.0f}pp this week)")
    return PredictionMarketState(backdrop=backdrop, markets=informative, notes=notes)
