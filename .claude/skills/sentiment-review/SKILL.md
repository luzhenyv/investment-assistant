---
name: sentiment-review
description: Read the Social sentiment block in a review report (output/<profile>/weekly_report_*.md or daily_review_*.md and its .json, produced by `uv run weekly_review.py` / `daily_review.py`) and turn the StockTwits/Reddit numbers into a retail-sentiment read FOR a long-duration AI-supercycle equity book. The engine gives the deterministic metrics (bull/bear net, message + Reddit volume, a chatter z-score, a coarse label); your job is the missing piece — the catalyst behind a chatter spike, whether an extreme is contrarian, and whether retail agrees or diverges from the tape (via web search) — plus what would flip the read. Use whenever the user asks "what's the retail sentiment on X", "is StockTwits/Reddit bullish on X", "why is chatter spiking on X", "is this crowded/contrarian", points at the Social sentiment block of a report, or questions a flagged name — even if they don't say "skill".
---

# Sentiment Review

The review engines (`weekly_review.py`, `daily_review.py`) emit a **Social sentiment (retail)** block
from two free feeds: **StockTwits** (retail messages carrying user-set Bullish/Bearish labels) and
**Reddit** (post volume across r/wallstreetbets, r/stocks, r/investing). The metrics are computed
deterministically in `quant/sentiment.py` and are deliberately **report-only**: sentiment never feeds
`scoring`/`decision`/`market.detect_market`, so the engine stays backtestable. The block is also
**blind to the catalyst**: it can see that chatter spiked +3σ or that 90% of labelled messages are
bullish, not *why*, or whether that's a bottom-tick contrarian signal or a real thesis. Your job is
that last mile — find the driver, judge whether the crowd is right or crowded, and say what it means
for the user's long-duration AI/tech book.

**Locate first** (newest wins): the `## Social sentiment (retail)` block in
`output/<profile>/weekly_report_*.md` or `daily_review_*.md`, and the `sentiment` object in its sibling
`.json` (keyed by symbol; each carries `st_bull`, `st_bear`, `st_unlabeled`, `st_total`, `st_net`,
`reddit_posts`, `sent_vol_z`, `sentiment_label`, `notes`). If no report exists, tell the user to run
`uv run daily_review.py` (or `weekly_review.py`) first. Ground the reads in `quant/sentiment.py` (the
thresholds + what each label means) so explanations are accurate, not remembered.

## What the block gives you (and what it can't)
- **Net** — `st_net` = (bull − bear) / labelled ∈ [−1, 1]. The retail lean *among people who tagged*
  their post. +0.5 or higher = Bullish; −0.5 or lower = Bearish; near zero with both sides vocal = Mixed.
- **Bull/Bear + Unlbl** — the raw counts. **Sample size is everything**: a +1.0 net off 3 labelled
  messages is noise; off 40 it's a signal. Check `st_total` and the labelled count, not just the net.
- **Msgs (`st_total`)** — StockTwits message volume, the *attention/chatter* proxy.
- **Chatter z (`sent_vol_z`)** — today's message count vs this store's accumulated history. A +2σ
  spike means attention surged — usually a catalyst. **This is the highest-value line** because volume
  leads: retail piles in *around* an event.
- **Reddit** — post count this week (RSS gives volume, not scores). Corroborates attention; a name
  lit up on both StockTwits *and* Reddit is genuinely in the retail spotlight.
- **What it CAN'T**: *why* chatter spiked, whether a 90%-bull reading is early-thesis or late-blowoff,
  and whether retail is confirming or fading the institutional tape. Go find it; never invent it.

## Required enrichment — the catalyst + the crowd read (do this every time)
Run **WebSearch** before judging. Establish, with linked sources:
1. **The driver behind a spike / extreme** — if `sent_vol_z` is high or the block flagged crowded
   bull/bear, what happened? Earnings, a product launch, an analyst call, a short squeeze, an
   influencer post, a sympathy move? A benign-looking net off a chatter spike with no news is itself a
   flag (manufactured hype / pump).
2. **Confirm vs contradict the tape** — cross-check retail against price/positioning already in the
   report: retail euphoric (`Bullish`, high volume) into a **call-wall / at resistance / short-gamma**
   name is late-chase risk; retail capitulating (`Bearish`, washed-out) at a **put-wall / support** is
   a contrarian bottom tell. The divergence is the signal, not the level alone.

Surface **only what a source confirms — link it.** StockTwits labels are self-reported and gameable;
Reddit RSS is unscored. If the numbers and the news disagree, say so — and remember StockTwits is
"most recent N", not a clean daily window, so a quiet-news day can still show stale-but-loud chatter.

## Judgment → a sentiment read for THIS book
The user is a long-term AI-supercycle PM (~25% maxDD tolerance, momentum + mean-reversion, options-aware).
Retail sentiment is a **timing/positioning overlay**, never a thesis — translate it into posture:

- **Confirming tailwind** — rising chatter + bullish net *early* in a move, backed by a real catalyst:
  momentum has retail fuel; fine to press, but mark the level where it becomes crowded.
- **Contrarian caution** — crowded-bullish extreme (≥85% bull) into resistance after a big run =
  blow-off / distribution risk; crowded-bearish extreme at support = capitulation the mean-reversion
  side of the book can lean against. Say which.
- **Noise** — low sample or no catalyst: call it noise and move on. Don't manufacture a signal from 4
  messages or a −0.3σ wiggle.

Tie it to the book when a report is open: if the engine's intent is **Add** but retail just went
vertically euphoric into a call wall, that divergence is the actionable insight — flag it (stage the
entry, wait for the chatter to cool). Note that this data is **un-backfillable and freshly accumulating**
— early on, the chatter z-score may be null (not enough history yet); say so rather than over-reading.

## Output
Lead with a one-line **bottom line**: *retail is confirming / crowded-contrarian / noise on <name>*,
and the one driver. Then: the catalyst behind the chatter (linked), the crowd read (net + sample size,
honest about quality), the tape cross-check (does retail agree with price/positioning?), the read for
the book (press / stage / fade / ignore, which names), and the **trip-wire** — what flips it (e.g.
"if bull share holds ≥85% into the call wall, treat the next green day as distribution"). The user
thinks like a PM — give the tradeoff and the trip-wire, not a data dump. End with a **Sources:** list.
