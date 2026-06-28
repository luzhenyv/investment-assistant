---
name: daily-review
description: Explain the abnormal/outlier features in a post-close daily review (output/<profile>/daily_review_*.md and its .json, produced by `uv run daily_review.py`). The script flags names with abnormal volume (RVOL + z-score), state flips, or RSI extremes; your job is to explain WHY each one fired — the catalyst (via web search), accumulation vs distribution, and what it implies for tomorrow's plan. Also frames whether today's per-symbol label (state + intent) looks trustworthy, since the run accumulates these rows as a labelled database. Use whenever the user shares or points at a daily_review_* file, asks "what was abnormal/unusual today", "why did X spike on volume", "explain today's outliers", or questions a flagged name — even if they don't say "skill".
---

# Daily Review

The daily engine (`daily_review.py`) runs after the close: it scores every name, emits the same
mechanical per-symbol intents as the weekly engine, AND adds an abnormal-volume overlay. It then
**appends one row per symbol to `data/daily_observations/<profile>/<date>.parquet`** — the day's
indicators, scores, and the engine's judgment (`state` + next-day `intent`). That judgment is a
**label** the user is accumulating to grade against forward returns later. The engine can *flag* that
volume was abnormal or a state flipped; it is **blind to the newswire** — it can't say *why*. Your
job is that last mile: explain each outlier, and judge whether today's label is signal or noise.

**Locate first** (newest wins): `output/<profile>/daily_review_*.md` and its sibling `.json`. The
JSON carries `outliers` (the flagged names), per-symbol `scores` (now incl. `rvol`, `vol_z`,
`vol_state`), `holdings`/`watchlist` intents, and `market`. If no file exists, tell the user to run
`uv run daily_review.py` first. Ground every "why" in the engine code — `quant/indicators.py`
(`rvol`, `volume_zscore`) and `quant/scoring.py` (`volume_state`, `asset_state`) — don't trust
remembered thresholds.

## What the outliers section gives you
Each `outliers` row carries `flags` (why it fired), `day_change_pct`, `rvol`, `vol_z`, `vol_state`,
`state` (+ `prev_state` if it flipped), `rsi`, and the next-day `intent`. Flags fire on:
- **Abnormal/Elevated volume** — `vol_z ≥ abnormal_z` (default 2σ) / `≥ elevated_z` (1σ). RVOL is the
  intuitive companion (2.0 = twice the 20-day norm).
- **State change** — the `asset_state` ladder label differs from yesterday's stored row.
- **RSI extreme** — `≥ rsi_overbought` or `≤ rsi_oversold`.

## Explain each outlier (this is the whole job)
1. **Volume direction = the read.** Abnormal volume is meaningless without price:
   - **Up day + abnormal volume** → demand / accumulation / breakout confirmation. Strengthens a
     Trend-Acceleration or breakout label.
   - **Down day + abnormal volume** → distribution / capitulation. A heavy-volume break of support is
     a real warning; a heavy-volume *flush* into support can be a wash-out bottom.
   - **Abnormal volume + tiny price move** → churn / failed move / opex pin — often noise, say so.
2. **Find the catalyst — web-search it, never invent it.** Classify like `pretrade-check`:
   *macro/sector beta* (the tape, a peer, CPI/FOMC), *positioning/mechanical* (opex, triple witching
   3rd-Fri Mar/Jun/Sep/Dec, index rebalance, pre-earnings de-risk), or *thesis/company-specific*
   (earnings, guidance, downgrade, governance). Link the source; if you can't find one for an
   idiosyncratic spike, that itself is the finding — flag it for investigation, don't guess.
3. **RSI / state-flip outliers** → what the flip implies for tomorrow: a fresh Broken→Range or
   Range→Trend Acceleration flip on volume is more credible than one on quiet tape.
4. **Positioning context (when the chain has it).** The `.json` `positioning` block now carries
   `gamma_flip`, `net_gex`, and `iv_rank` per name (see `quant/option_flow.py`). Use them to qualify
   a volume outlier: a heavy-volume **down** day with spot **below the gamma flip** (dealers
   short-gamma, `net_gex < 0`) is more dangerous — hedging *amplifies* the move, so the flush can
   over-extend; **above the flip** (long-gamma) the same dip tends to get dampened / mean-revert. A
   high `iv_rank` (vol rich) around an event favors *selling* premium to express the view; a low one
   favors *owning* optionality. These lag ~1 day (EOD OI) — context, not a trigger.
5. **Is the label trustworthy?** The run stored `state` + `intent` as today's label. Say whether the
   outlier *corroborates* it (volume confirms the move → high-quality label) or *contradicts* it
   (intent says Add Core but the move is heavy-volume distribution on a thesis crack → suspect label,
   worth a manual override before it pollutes the dataset).

## Output
Chat only — no file writes unless asked. Lead with a one-line read of the day (regime + the single
most important outlier). Then one short block per flagged name: the volume read, the catalyst
(classified + linked), and the one-line implication for tomorrow's plan / label quality. Close with
the single biggest thing to watch. The user thinks like a PM building a dataset — give the tradeoff
and the label-quality call, not a data dump. End with a **Sources:** list of the links you used.
