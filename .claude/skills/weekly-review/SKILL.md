---
name: weekly-review
description: Analyze a weekly portfolio review report (output/<profile>/weekly_report_*.md and its .json) and turn the engine's mechanical intents into a prioritized, judgment-layered action list — position adjustments, opportunities, and issues. Use this whenever the user shares or points at their weekly report, asks "what should I do with my portfolio/positions this week", "evaluate/review my portfolio", or questions a specific intent / watchlist / cash line — even if they don't say "skill".
---

# Weekly Review

The weekly engine (`weekly_review.py`) emits mechanical per-symbol intents. They're correct by their
own rules but lack judgment: they don't cross-check their own signals, flag internal inconsistencies,
or explain *why*. Your job is that judgment layer — turn the report into a short, prioritized action
list, and surface the opportunities and traps the mechanical pass misses.

**Locate first** (newest wins): `output/<profile>/weekly_report_*.md` and its sibling `.json` (the
JSON carries `dollar_gap`, `weights`/`cash_frac`, per-symbol `scores`). Ground every "why" in the
engine code — `quant/scoring.py` (signal defs) and `quant/decision.py` (the rule ladder) — so
explanations are accurate, not remembered. Skim them; don't trust memory of thresholds.

## Signals — what each measures (horizon disagreement is where the insight is)
- `trend` (0–100): +25 each for price>MA20, MA20>MA50, MA50>MA200, price>MA200. Structure.
- `rsi`/`momentum`: 14-day RSI → short-term (~2wk) heat. RSI>70 ⇒ momentum 80, near overbought.
- `rs`: 126-day (~6mo) trailing **total return** (`indicators.trailing_return`). Medium-term leadership.
- `state`: first-match ladder in `asset_state()` — Broken / Mean Reversion / Trend Acceleration /
  Trend Mature / Range. Acceleration fires on `breakout OR rsi≥accel_rsi`; the RSI-only branch is a
  *short-term* trigger, not a structural new high.

The strongest findings come from **signals that disagree across horizons.** Example: a name flagged
Trend Acceleration via the RSI branch (hot, ~2wk) but with negative `rs` (a 6-month laggard) is
*chasing a bounce*, not a confirmed leader — the weakest kind of "buy". Check `avg_cost` too: adding
under water compounds it.

**Validate extremes before judging them.** An outlier RS or an implausible-looking price is *either*
a real parabola *or* a data error — don't assume bad data. Cross-check the cached series
(`data/cache/SYMBOL_*.parquet`) **and** an external source (finviz / broker) before concluding.
(Hard-won: a +300–870% RS on the memory names this session looked like garbage; finviz confirmed it
was a real AI-memory melt-up. Verify, don't assume.) The same verify-against-a-source rule
applies to any catalyst you cite in item 7 — link it or drop it.

## Checklist — verdict + one-line WHY for each
1. **Action-list integrity.** Sum the `Close` `dollar_gap`s and recompute *true* post-close cash %.
   The report's "deploy $X"/cash line is computed before the Closes — if they raise a lot, the real
   picture is far more cash, not less. State the true number.
2. **Buy-signal quality.** For every Add/Increase, check horizon agreement (trend vs rsi vs rs vs the
   state trigger). Flag bounce-chasing; rank buys by conviction, not just by what fired.
   **Parabolic entries:** if a buy is extended (report shows the "strong but parabolic" flag, or
   price ≫ MA200), treat it as strong-but-stretched — stage in (first step only), don't chase a
   spike-day candle, treat a correlated cluster (same sector) as ONE bet and cap it, and prefer
   defined-risk options. Strong RS is real *and* a parabola mean-reverts hard — both are true.
3. **Watchlist sanity.** Empty? Distinguish *false-empty* (`open_slots = max_positions − holdings`
   still counting to-be-Closed names → 0) from *genuine* (quality floor `entry_rs_min`, or weak
   regime). Name which, and what would unlock entries (execute closes / widen list).
4. **Book vs market.** Compare market regime to holdings' states/`rs`. Broken or negative-`rs` names
   in a strong tape = laggard drag worth calling out.
5. **Sizing redeployment.** For survivors under target, give gap-to-target ranked by `rs`; note the
   staged step (`target/max_steps`) and the structural cap — a few names at their ceilings can't
   absorb a big cash pile, so redeployment usually needs watchlist entries, not just topping up.
6. **Options.** Flag time-sensitive items: short calls ITM (assignment risk → roll up/out), low DTE.
7. **Catalysts & event risk (verify first, then flag only what's time-sensitive).** The mechanical
   pass is blind to the calendar and the newswire. Before endorsing any Add / Increase / Hold, scan
   for near-term catalysts — but surface **only what you can confirm from a source (link it); never
   invent news**, and keep it to material, this-week-relevant items, not a feed.
   - **Earnings / binary prints.** Flag if a buy/hold reports within ~2 weeks. Entering an extended
     or parabolic name right before a binary print is gambling, not staging (e.g. MU 6/24, ahead of
     a +305% run) — prefer waiting for the print or sizing via small defined-risk options.
     Cross-reference item 2's parabolic rule.
   - **Insider & institutional flow.** Large insider/CEO sells or buys (Form 4), block trades,
     notable 13F shifts. A cluster of insider *selling* into a parabola is a caution; sized insider
     *buying* on a beaten-down name can corroborate a Mean-Reversion add.
   - **Leadership / ownership changes.** CEO/CFO/founder/board departures or an activist stake
     change the thesis (e.g. Reed Hastings not standing for NFLX re-election as NFLX broke down).
     Call out a governance overhang on a Close/Hold.
   - **Market-structure events (one line, brief).** Triple witching (3rd Fri of Mar/Jun/Sep/Dec;
     rolls earlier if that Friday is a holiday), index rebalances, FOMC/CPI. Note elevated
     volume/volatility and option-pin effects so a single-day volume/price spike isn't over-read,
     and so option rolls (item 6) account for expiry mechanics.

## Output
Chat only — no file writes/edits unless asked. Lead with a one-line bottom line, then a priority-
ordered action list (highest-conviction / most time-sensitive first), each with a short WHY grounded
in the signals. Close with the single biggest lever or key open question. The user thinks like a PM —
give the tradeoff, not a data dump.
