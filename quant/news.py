"""Derive per-ticker + global news reads from headline feeds. Pure functions — the news analogue of
quant/sentiment.py. Report-only context: never feeds market.detect_market, scoring, or decision, so
the deterministic engine stays backtestable.

Free yfinance headlines carry no vendor sentiment score, so the code computes only COVERAGE metrics
(count, freshness, a coverage-volume spike vs history); the bullish/bearish/catalyst judgment is the
news-review skill's job (web search over the archived headlines)."""
from __future__ import annotations

import datetime as dt
import statistics

from quant import clock
from quant.models import GlobalNewsState, NewsView

DEFAULTS = {
    "top_n": 5,            # headlines kept on the view (report + skill); the full set goes to the archive
    "stale_days": 5,       # latest headline older than this => "quiet coverage" note
    "vol_z_min_days": 20,  # min prior news_count obs before the coverage z-score is computed
    "vol_z_spike": 2.0,    # |coverage z| at/above this => coverage-spike note
}


def _parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _vol_z(count: int, hist: list[int] | None, min_days: int) -> float | None:
    """z-score of today's headline count vs accumulated history (a coverage spike). None until enough
    prior observations or when the series is flat."""
    if not hist or len(hist) < min_days:
        return None
    try:
        sd = statistics.stdev(hist)
    except statistics.StatisticsError:
        return None
    if sd <= 0:
        return None
    return round((count - statistics.fmean(hist)) / sd, 2)


def analyze(symbol: str, raw: list[dict] | None, cfg: dict, vol_hist: list[int] | None = None) -> NewsView | None:
    """Build a NewsView from `raw` (providers.fetch_news_raw output). Returns None when there are no
    headlines (caller stores nulls), mirroring the sentiment/positioning lenses. `vol_hist` is the
    prior daily news_count series (from the store) for the coverage z-score."""
    if not raw:
        return None
    t = {**DEFAULTS, **cfg.get("news", {}).get("thresholds", {})}
    items = sorted(raw, key=lambda h: h.get("pub_date") or "", reverse=True)  # newest first
    count = len(items)
    latest_pub = items[0].get("pub_date") or None
    latest_dt = _parse_iso(latest_pub)
    age_days = round((clock.now() - latest_dt).total_seconds() / 86400, 1) if latest_dt else None
    vz = _vol_z(count, vol_hist, t["vol_z_min_days"])
    headlines = [{"title": h.get("title"), "publisher": h.get("publisher"),
                  "pub_date": h.get("pub_date"), "link": h.get("link")} for h in items[:t["top_n"]]]
    notes: list[str] = []
    if age_days is not None and age_days > t["stale_days"]:
        notes.append(f"quiet — latest headline {age_days:.0f}d old (stale coverage)")
    if vz is not None and abs(vz) >= t["vol_z_spike"]:
        notes.append(f"coverage {'surge' if vz > 0 else 'drop'} — {count} headlines, {vz:+.1f}σ vs "
                     f"history (check the catalyst)")
    return NewsView(symbol=symbol, news_count=count, latest_pub=latest_pub,
                    latest_age_days=age_days, news_vol_z=vz, headlines=headlines, notes=notes)


def analyze_global(raw: list[dict] | None, cfg: dict) -> GlobalNewsState:
    """Build the market-wide GlobalNewsState from deduped macro headlines (already deduped in the
    provider). Keeps the top-N for the report; the full set is archived separately."""
    items = raw or []
    top = cfg.get("news", {}).get("global", {}).get("report_top_n", 8)
    headlines = [{"title": h.get("title"), "publisher": h.get("publisher"), "pub_date": h.get("pub_date"),
                  "link": h.get("link"), "query": h.get("query")} for h in items[:top]]
    notes = [] if items else ["no global macro headlines fetched"]
    return GlobalNewsState(count=len(items), headlines=headlines, notes=notes)
