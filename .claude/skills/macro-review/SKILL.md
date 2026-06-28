---
name: macro-review
description: Read the Macro backdrop block in a review report (output/<profile>/weekly_report_*.md or daily_review_*.md and its .json, produced by `uv run weekly_review.py` / `daily_review.py`) and turn the FRED numbers into a tailwind/headwind/neutral verdict FOR a long-duration AI-supercycle equity book. The engine gives the levels (10y, real yield, 2s10s, HY spread, NFCI) and their direction; your job is the missing piece — the near-term calendar (FOMC/CPI/PCE/NFP) and what the last print did (via web search) — plus what would flip the read. Use whenever the user asks "what's the macro backdrop", "is macro a headwind for tech", "what does the rates/credit picture mean for my book", "what's on the calendar this week", points at the Macro block of a report, or questions the macro read — even if they don't say "skill".
---

# Macro Review

The review engines (`weekly_review.py`, `daily_review.py`) emit a **Macro backdrop** block from FRED:
nominal/real yields, the 2s10s curve, breakeven inflation, the HY credit spread, and financial
conditions (NFCI) — each with a coarse, labelled read (`quant/macro.py`). It is deliberately
**report-only**: macro never feeds `scoring`/`decision`/`market.detect_market`, so the engine stays
backtestable. The block is also **blind to the calendar**: it can see real yields rose 8bps, not that
a hot CPI print drove it or that FOMC lands Wednesday. Your job is that last mile — overlay the
calendar and the catalyst, then say whether macro is a **tailwind / headwind / neutral** to the user's
long-duration AI/tech book, and what would change it.

**Locate first** (newest wins): the `## Macro backdrop` block in `output/<profile>/weekly_report_*.md`
or `daily_review_*.md`, and the `macro` object in its sibling `.json` (carries `series`
{level/prev/change per id}, `backdrop`, and the derived reads `rates_direction`, `curve`,
`real_yield_regime`, `credit`, `fin_conditions`). If no report exists, tell the user to run
`uv run weekly_review.py` (or `daily_review.py`) first. Ground the reads in `quant/macro.py` (the
thresholds + what each label means) so explanations are accurate, not remembered.

## What the block gives you (and what it can't)
- **Rates** — `DGS10` level + `rates_direction`. The discount rate on long-duration cash flows.
- **Real yield** — `DFII10` + `real_yield_regime` (the headline for tech): rising real yields =
  **duration headwind** (multiple compression risk for unprofitable/long-duration names); falling =
  **tailwind**. This is the single most important line for an AI-supercycle book.
- **Curve** — 2s10s (`DGS2` vs `DGS10`): inverted/flat/normal — recession-signal context.
- **Breakeven** — `T10YIE`: inflation expectations (context for what the Fed does next).
- **Credit** — `BAMLH0A0HYM2` HY OAS + `credit` (risk-on/off): widening spreads = stress bid, the
  early warning that equity dips won't be cushioned. Tight + stable = risk appetite intact.
- **Financial conditions** — `NFCI` + `fin_conditions` (loose/tight): the aggregate liquidity read.
- **What it CAN'T**: *why* a number moved, and *what's next*. The change is over a ~21-day window — it
  won't know FOMC is Wednesday or that today's CPI ran hot. Go find it; never invent it.

## Required enrichment — the calendar + the driver (do this every time)
Run **WebSearch** before judging. Establish two things, with linked sources:
1. **The near-term calendar** — the next FOMC meeting, CPI/PCE/NFP/Jobs dates within ~2 weeks, and any
   major Treasury auction or Fed-speak. A benign backdrop with a binary event in 2 days is *not* benign.
2. **What the last print / move did** — was the real-yield move a hot inflation print, a hawkish Fed
   repricing, a growth scare (yields down for the *wrong* reason), or a flight-to-quality? The same
   "10y falling" is a tailwind if it's disinflation and a warning if it's a growth/credit scare —
   cross-check against `credit`: falling yields + widening HY = risk-off, not a green light.

Surface **only what a source confirms — link it.** If the numbers and the news disagree (e.g. NFCI
reads loose but HY is gapping wider intraday), say so — the FRED series lag (NFCI weekly, some series
1 day), and that lag is itself the finding.

## Judgment → a backdrop verdict for THIS book
The user is a long-term AI-supercycle PM (~25% maxDD tolerance, momentum + mean-reversion, options-aware).
Translate the macro state into what it means for *that* posture, not in the abstract:

- **Tailwind** — real yields falling on disinflation, credit calm, conditions loose: the backdrop
  supports adding duration/beta; dips are likely buyable. Say what would have to break it.
- **Headwind** — real yields rising, curve re-steepening bear-ishly, HY widening, conditions tightening:
  multiple-compression risk for the longest-duration names; favor quality/profitable compounders over
  speculative long-duration, consider trimming beta or hedging. Be specific about which names in the
  book are most rate-sensitive.
- **Neutral / mixed** — call it mixed and name the swing factor (usually the next print or FOMC).
  Don't manufacture a signal from noise: a +4bps HY move over 21 days is not "risk-off."

Tie it to the book when a report is open: if the market regime is `Strong Bull` but macro is a building
headwind (real yields grinding up), that divergence is the actionable insight — flag it.

## Output
Lead with a one-line **bottom line**: *tailwind / headwind / neutral for a long-duration AI book*, and
the one swing factor. Then: the calendar (next FOMC/CPI/PCE/NFP, linked), the driver behind the key
move (real yields / credit, classified), the read for the book (which posture, which names most
exposed), and the **trip-wire** — the specific level or event that flips the verdict (e.g. "10y real
above 2.4% or HY through 3.5%"). The user thinks like a PM — give the tradeoff and the trip-wire, not a
data dump. End with a **Sources:** list of the links you used.
