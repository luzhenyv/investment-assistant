"""Derive a coarse retail-sentiment read from social feeds. Pure function — the sentiment analogue
of quant/macro.py. Report-only context that runs PARALLEL to the engine: it never feeds
market.detect_market, scoring, or decision, so the deterministic engine stays backtestable.

The numeric signal is StockTwits' machine-readable Bullish/Bearish labels (a bull/bear net + the
message-count "chatter" volume); Reddit's RSS search adds a post-VOLUME attention proxy (no labels).
Everything richer — cross-source divergence, the catalyst behind a chatter spike, whether an extreme
is contrarian — is the sentiment-review skill's job (web search), not this module's."""
from __future__ import annotations

import statistics

from quant.models import SentimentView

# Thresholds over the fetched sample. Override under config `sentiment.thresholds`.
DEFAULTS = {
    "bull_band": 0.50,       # st_net >= this = Bullish (<= -this = Bearish)
    "mild_band": 0.20,       # |st_net| >= this (but < bull_band) = Mildly Bull/Bear
    "low_sample": 10,        # labelled (bull+bear) messages below this => low-confidence note
    "bull_extreme": 0.85,    # bull share of labelled msgs >= this => contrarian over-extension flag
    "vol_z_min_days": 20,    # min prior st_total observations before the chatter z-score is computed
    "vol_z_spike": 2.0,      # |sent_vol_z| at/above this => chatter-spike note
}


def _volume_z(st_total: int, hist: list[int] | None, min_days: int) -> float | None:
    """z-score of today's message count vs the accumulated history (the 'chatter spike'). None until
    enough prior observations exist or when the series is flat (zero variance)."""
    if not hist or len(hist) < min_days:
        return None
    try:
        sd = statistics.stdev(hist)
    except statistics.StatisticsError:
        return None
    if sd <= 0:
        return None
    return round((st_total - statistics.fmean(hist)) / sd, 2)


def _label(st_net: float | None, bull: int, bear: int, t: dict) -> str:
    """Coarse band. Mixed = genuine disagreement (net near zero but both sides vocal); Neutral =
    genuinely quiet / no labelled messages."""
    if st_net is None:
        return "Neutral"
    if st_net >= t["bull_band"]:
        return "Bullish"
    if st_net <= -t["bull_band"]:
        return "Bearish"
    if st_net >= t["mild_band"]:
        return "Mildly Bullish"
    if st_net <= -t["mild_band"]:
        return "Mildly Bearish"
    # |net| < mild_band: disagreement if both sides are vocal, else genuinely quiet
    return "Mixed" if (bull > 0 and bear > 0 and bull + bear >= t["low_sample"]) else "Neutral"


def analyze(symbol: str, raw: dict | None, cfg: dict, vol_hist: list[int] | None = None) -> SentimentView | None:
    """Build a SentimentView from `raw` (providers.fetch_sentiment_raw output). Returns None when
    there's no data at all (both feeds empty) so the caller stores nulls, mirroring the positioning
    lens. `vol_hist` is the prior daily st_total series (from the observation store) for the z-score."""
    if not raw:
        return None
    st = raw.get("stocktwits") or []
    rd = raw.get("reddit") or []
    if not st and not rd:
        return None
    t = {**DEFAULTS, **cfg.get("sentiment", {}).get("thresholds", {})}

    bull = sum(1 for m in st if m.get("sentiment") == "Bullish")
    bear = sum(1 for m in st if m.get("sentiment") == "Bearish")
    unlabeled = len(st) - bull - bear
    st_total = len(st)
    labelled = bull + bear
    st_net = round((bull - bear) / labelled, 3) if labelled else None
    reddit_posts = len(rd)
    sent_vol_z = _volume_z(st_total, vol_hist, t["vol_z_min_days"])
    label = _label(st_net, bull, bear, t)

    notes: list[str] = []
    if labelled and labelled < t["low_sample"]:
        notes.append(f"low sample — only {labelled} labelled StockTwits msg(s); read is weak")
    if labelled >= t["low_sample"]:
        bull_share = bull / labelled
        if bull_share >= t["bull_extreme"]:
            notes.append(f"crowded bullish — {bull_share:.0%} of {labelled} labelled msgs "
                         f"(≥{t['bull_extreme']:.0%}) may be over-extended / contrarian risk")
        elif (1 - bull_share) >= t["bull_extreme"]:
            notes.append(f"crowded bearish — {1 - bull_share:.0%} of {labelled} labelled msgs "
                         f"(≥{t['bull_extreme']:.0%}) may be washed-out / contrarian risk")
    if sent_vol_z is not None and abs(sent_vol_z) >= t["vol_z_spike"]:
        direction = "surge" if sent_vol_z > 0 else "drop"
        notes.append(f"chatter {direction} — {st_total} StockTwits msgs, {sent_vol_z:+.1f}σ vs history "
                     f"(check the catalyst)")
    if reddit_posts and st_total == 0:
        notes.append(f"Reddit active ({reddit_posts} posts) but StockTwits silent — attention without "
                     f"a clear retail lean")

    return SentimentView(
        symbol=symbol, st_bull=bull, st_bear=bear, st_unlabeled=unlabeled, st_total=st_total,
        st_net=st_net, reddit_posts=reddit_posts, sent_vol_z=sent_vol_z,
        sentiment_label=label, notes=notes,
    )
