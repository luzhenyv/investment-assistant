"""Pre-trade ('Monday pre-flight') layer. The weekly engine runs on daily *cached* bars, so by
the time the user acts — the open of the following week — its report is a session behind: it
can't see today's gap, today's range, or an earnings print landing tomorrow. This module overlays
a LIVE intraday quote (providers.fetch_quote) on the engine's signal/positioning/role outputs and
**re-anchors** every level (walls, max-pain, TP/SL) to the live price, so distances and reward:risk
reflect where the stock actually is now — not Friday's close.

Report-only — never feeds scoring/decision. The catalyst/news judgment lives in the pretrade-check
skill (web search); this stays deterministic. Earnings within the gate is a SOFT warning + sizing
guidance (don't deploy full size into a binary print), never a hard block."""
from __future__ import annotations

from quant.models import (
    Fundamentals, NewsView, OptionPositioning, PreTradeBrief, RoleView, SentimentView, Signal,
)


def _dist(level: float | None, last: float) -> float | None:
    """Signed distance from the live price to a level, as a fraction of the live price
    (+ above / − below). None when the level is missing."""
    return (level - last) / last if (level is not None and last) else None


def _live_reward_risk(last: float, cw: float | None, pw: float | None):
    """Reward:risk recomputed at the LIVE price — upside to the call wall vs downside to the
    put wall (mirrors option_flow.reward_risk, but anchored to `last` instead of the close)."""
    reward = (cw - last) / last if (cw is not None and last) else None
    risk = (last - pw) / last if (pw is not None and last) else None
    ratio = reward / risk if (reward is not None and risk and risk > 0) else None
    return reward, risk, ratio


def _market_read(move: float | None, mkt: dict) -> tuple[bool | None, str | None]:
    """Idiosyncratic vs macro: how far the name's day move diverges from the SPY/QQQ tape.
    Returns (idiosyncratic, note). A move ≥3pp away from the index average reads idiosyncratic
    ('check the name'); in line reads macro/beta ('it's the tape')."""
    idx = [m for m in (mkt.get("spy_change_pct"), mkt.get("qqq_change_pct")) if m is not None]
    if move is None or not idx:
        return None, None
    tape = sum(idx) / len(idx)
    excess = move - tape
    if abs(excess) >= 0.03:
        return True, (f"its own {move:+.1%} vs the tape's {tape:+.1%} ({excess:+.1%} divergence) — "
                      f"idiosyncratic, check the name first")
    return False, (f"its own {move:+.1%} ≈ the tape's {tape:+.1%} — macro/beta, not name-specific")


def build(
    symbol: str,
    cfg: dict,
    sig: Signal,
    live: dict | None,
    positioning: OptionPositioning | None,
    roleview: RoleView | None,
    fund: Fundamentals | None,
    earnings: dict | None,
    market_ctx: dict,
    portfolio_ctx: dict,
    position: dict,
    *,
    as_of: str,
    sentiment_view: SentimentView | None = None,
    news_view: NewsView | None = None,
) -> PreTradeBrief:
    """Assemble the PreTradeBrief: live quote + re-anchored levels + earnings gate + market read.

    `live` may be None (quote fetch failed) — we then fall back to the engine's daily close so the
    brief still renders, flagged as stale."""
    pt = cfg.get("pretrade", {})
    if live is None:
        live = {
            "last": sig.price, "open": None, "prev_close": None,
            "day_high": None, "day_low": None, "change": None, "change_pct": None,
            "today_session": False, "source": "signal_close",
        }
    last = live["last"]
    low = live.get("day_low")
    move = live.get("change_pct")

    notes: list[str] = []

    # --- Re-anchor option-positioning levels + role TP/SL to the live price -----------------
    levels: dict = {}
    pw = cw = mp = None
    if positioning is not None:
        pw, cw, mp = positioning.put_wall, positioning.call_wall, positioning.max_pain
        reward, risk, rr = _live_reward_risk(last, cw, pw)
        levels.update({
            "put_wall": pw, "call_wall": cw, "max_pain": mp,
            "to_put_wall": _dist(pw, last), "to_call_wall": _dist(cw, last),
            "to_max_pain": _dist(mp, last),
            "live_reward": reward, "live_risk": risk, "live_rr": rr,
            "em_pct": positioning.em_pct, "iv_skew": positioning.iv_skew,
            "gamma_flip": positioning.gamma_flip, "to_gamma_flip": _dist(positioning.gamma_flip, last),
            "net_gex": positioning.net_gex, "iv_rank": positioning.iv_rank,
        })
    tp_price = sl_price = None
    if roleview is not None:
        tp_price, sl_price = roleview.tp_price, roleview.sl_price
        levels["tp_price"], levels["sl_price"] = tp_price, sl_price
        levels["to_tp"], levels["to_sl"] = _dist(tp_price, last), _dist(sl_price, last)

    # --- Re-anchored human reads (where price sits vs structure, now) -----------------------
    buf = pt.get("entry_zone_buffer", 0.05)
    if pw is not None and last <= pw * (1 + buf):
        notes.append(f"near the ${pw:,.0f} put-wall / support entry zone (live ${last:,.0f})")
    if cw is not None and last >= cw * 0.98:
        notes.append(f"at/under the ${cw:,.0f} call-wall resistance — limited room before the cap")
    if mp is not None and low is not None and low <= mp * 1.005 and last > mp:
        notes.append(f"tagged max-pain ${mp:,.0f} at the low ${low:,.0f} and bounced")
    if sl_price is not None and low is not None and low < sl_price:
        notes.append(f"role stop ${sl_price:,.0f} breached intraday (low ${low:,.0f}) — "
                     f"a stop too tight for today's range")
    gflip = positioning.gamma_flip if positioning is not None else None
    if gflip is not None:
        if last < gflip:
            notes.append(f"live ${last:,.0f} below gamma flip ${gflip:,.0f} — dealers short-gamma, "
                         f"hedging amplifies (a dip can air-pocket; size in, don't chase)")
        else:
            notes.append(f"live ${last:,.0f} above gamma flip ${gflip:,.0f} — dealers long-gamma, "
                         f"moves dampened (mean-revert / pin bias toward the flip)")

    # --- Earnings gate (soft) --------------------------------------------------------------
    gate_days = pt.get("earnings_gate_days", 5)
    earn = None
    if earnings is not None:
        earn = dict(earnings)
        within = earnings["days_until"] <= gate_days
        earn["within_gate"] = within
        earn["expected_move_pct"] = positioning.em_pct if positioning else None
        if within:
            em = earn["expected_move_pct"]
            em_txt = f" (~±{em:.0%} priced)" if em is not None else ""
            earn["sizing_note"] = (
                f"earnings in {earnings['days_until']}d ({earnings['next_date']}){em_txt} — "
                f"don't deploy full size into the print; starter / cash-secured put only, "
                f"a stop can't protect across the gap")
            notes.append(f"⚠️ earnings in {earnings['days_until']}d ({earnings['next_date']}) — "
                         f"soft gate: don't size full into the print")

    # --- Market context: idiosyncratic vs macro --------------------------------------------
    idiosyncratic, mkt_note = _market_read(move, market_ctx)
    market = dict(market_ctx)
    market["idiosyncratic"] = idiosyncratic
    if mkt_note:
        notes.append(mkt_note)

    valuation = {}
    if fund is not None:
        valuation = {
            "pe": fund.pe, "forward_pe": fund.forward_pe, "peg": fund.peg,
            "analyst_target": fund.analyst_target, "upside_to_target": fund.upside_to_target,
            "label": fund.valuation_label,
        }

    sentiment = {}
    if sentiment_view is not None:
        sentiment = {
            "label": sentiment_view.sentiment_label, "net": sentiment_view.st_net,
            "st_bull": sentiment_view.st_bull, "st_bear": sentiment_view.st_bear,
            "st_total": sentiment_view.st_total, "reddit_posts": sentiment_view.reddit_posts,
            "sent_vol_z": sentiment_view.sent_vol_z, "notes": sentiment_view.notes,
        }
        for n in sentiment_view.notes:
            notes.append(f"sentiment: {n}")

    news = {}
    if news_view is not None:
        top = news_view.headlines[0] if news_view.headlines else None
        news = {
            "news_count": news_view.news_count, "latest_age_days": news_view.latest_age_days,
            "news_vol_z": news_view.news_vol_z,
            "top_headline": top.get("title") if top else None,
            "top_publisher": top.get("publisher") if top else None,
        }
        for n in news_view.notes:
            notes.append(f"news: {n}")

    return PreTradeBrief(
        symbol=symbol,
        as_of=as_of,
        live=live,
        scores={
            "state": sig.state, "trend": sig.trend_score, "momentum": sig.momentum_score,
            "rs": sig.rs, "rsi": sig.rsi, "price": sig.price,
        },
        valuation=valuation,
        today_move_pct=move,
        levels=levels,
        roles=({
            "role": roleview.role, "suggested_role": roleview.suggested_role,
            "horizon": roleview.horizon, "tp_price": tp_price, "sl_price": sl_price,
            "note": roleview.note,
        } if roleview is not None else {}),
        sentiment=sentiment,
        news=news,
        earnings=earn,
        market_ctx=market,
        portfolio=dict(portfolio_ctx),
        position=dict(position),
        notes=notes,
    )
