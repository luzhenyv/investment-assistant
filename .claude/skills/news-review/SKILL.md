---
name: news-review
description: Read the News flow + Global macro news + Prediction markets blocks in a review report (output/<profile>/weekly_report_*.md or daily_review_*.md and its .json, produced by `uv run weekly_review.py` / `daily_review.py`) and turn the headlines + Polymarket odds into a catalyst read FOR a long-duration AI-supercycle equity book. The engine gives coverage metrics (headline count, freshness, a coverage z-score) and crowd-implied event probabilities but CANNOT read the story; your job is the missing piece — classify each headline as catalyst vs noise and bullish vs bearish (confirm via web search), read the prediction-market odds as the forward macro prior, and cross-check against the sentiment + macro lenses. Use whenever the user asks "what's the news on X", "any catalysts today", "why is coverage spiking on X", "what are the Fed-cut / recession odds", "what do prediction markets say", points at the News or Prediction-markets block of a report, or questions a headline-driven move — even if they don't say "skill".
---

# News Review

The review engines (`weekly_review.py`, `daily_review.py`) emit three report-only news/context blocks:
a per-ticker **News flow** table (`quant/news.py`), a **Global macro news** list, and a **Prediction
markets** odds table (`quant/prediction_markets.py`). All are deliberately **report-only**: none feed
`scoring`/`decision`/`market.detect_market`, so the engine stays backtestable. They are also **blind to
the story**: the engine can count that NVDA has 12 headlines and coverage spiked +3σ, or that Polymarket
prices a Fed cut at 68%, but not *what* the headlines say or *why* the odds moved. Your job is that last
mile — read the catalyst, classify it, and translate the forward odds into what they mean for the user's
long-duration AI/tech book.

**Locate first** (newest wins): the `## News flow (per-ticker)`, `## Global macro news`, and
`## Prediction markets` blocks in `output/<profile>/weekly_report_*.md` or `daily_review_*.md`, and the
`news` / `global_news` / `prediction_markets` objects in the sibling `.json` (the `news` object per
symbol carries `news_count`, `latest_age_days`, `news_vol_z`, and the top-N `headlines` with titles +
links; `prediction_markets` carries `backdrop` + the `markets` list with `prob`/`volume`/`week_change`).
If no report exists, tell the user to run `uv run daily_review.py` first. Ground the metric definitions
in `quant/news.py` / `quant/prediction_markets.py` so explanations are accurate, not remembered.

## What the blocks give you (and what they can't)
- **News flow (per-ticker)** — `news_count` (coverage volume, an attention proxy), `latest_age_days`
  (freshness), `news_vol_z` (**coverage spike vs this store's history — the highest-value line**; a
  +2σ jump means the news machine just turned on, usually a catalyst), and the top headlines. **No
  vendor sentiment** — free yfinance gives you the text, not a score. You supply the direction.
- **Global macro news** — deduped macro/world headlines (Fed, inflation, earnings, geopolitics, oil).
  Context for the macro backdrop; overlaps the macro-review skill's territory — cross-reference it.
- **Prediction markets** — Polymarket crowd-implied probabilities + traded volume + resolution date +
  the **1-week probability move**. Higher volume = deeper/more reliable. This is the forward prior the
  FRED macro lens can't give (odds of a Fed cut, a recession, an S&P level).
- **What they CAN'T**: read the story, tell catalyst from noise, or know *why* odds moved. Go find it;
  never invent a headline or a number.

## Required enrichment — read the catalyst + confirm the odds (do this every time)
Run **WebSearch** before judging. Establish, with linked sources:
1. **The driver behind a coverage spike / a flagged name** — open the actual story (the headlines carry
   `link`s). Is it earnings, a product/AI announcement, an analyst action, a downgrade, a lawsuit, a
   sympathy move? Classify: **catalyst vs noise**, and **bullish vs bearish vs ambiguous** for the thesis.
2. **What moved a prediction market** — if a probability jumped ≥10pp this week, find the print/event
   behind it (a CPI report, an FOMC repricing, a jobs number). The odds are only as useful as the story.

Surface **only what a source confirms — link it.** yfinance headlines can be stale, syndicated, or
mislabeled, and Polymarket odds on thin markets are noisy (weight by volume). If the coverage says one
thing and price/sentiment say another, that divergence is itself the finding.

## Judgment → a catalyst read for THIS book
The user is a long-term AI-supercycle PM (~25% maxDD tolerance, momentum + mean-reversion, options-aware).
News is a **timing/catalyst overlay**, never the thesis — translate it into posture:

- **Confirming catalyst** — a real, thesis-positive story (AI demand, a beat, a design win) behind a
  coverage spike: momentum has fuel; note the level where it's priced in.
- **Thesis-breaking catalyst** — a downgrade cycle, guidance cut, regulatory/competitive threat: flag it
  loudly against the engine's intent (an Add into deteriorating news is the actionable conflict).
- **Noise** — syndicated / low-relevance coverage with no price follow-through: say so and move on. Don't
  manufacture a catalyst from a +0.5σ wiggle or a single reprinted headline.
- **Forward odds** — read the prediction-market backdrop as the macro prior: rising Fed-cut odds =
  duration tailwind for long-duration tech (tie to the macro-review real-yield read); rising recession
  odds = risk-off, favor quality. Name the swing event and its date.

Cross-check the other lenses when the report is open: news + **sentiment** both euphoric into resistance =
crowded; a bullish catalyst the **macro** backdrop contradicts (great story, rising real yields) is a
tension worth naming. Note the archive is **freshly accumulating** — early on `news_vol_z` may be null
(not enough history); say so rather than over-reading a raw count.

## Output
Lead with a one-line **bottom line**: *catalyst / thesis-risk / noise on <name>*, or *the forward macro
prior is X*, and the one swing factor. Then: the catalyst behind each flagged name (classified + linked),
the prediction-market read (odds + what moved them), the read for the book (press / stage / trim / hedge,
which names), and the **trip-wire** — the event or level that flips it (e.g. "a guidance cut on the print
Thursday", "recession odds through 40%"). The user thinks like a PM — give the tradeoff and the trip-wire,
not a headline dump. End with a **Sources:** list of the links you used.
