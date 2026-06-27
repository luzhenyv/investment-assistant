---
name: pretrade-check
description: Turn a pre-trade brief (output/<profile>/pretrade_*.md and its .json, produced by `uv run pretrade.py SYM`) into a timed buy/sell decision. The brief overlays a LIVE intraday quote on the engine's signal and re-anchors levels to it; your job is to add the missing piece — today's catalyst/news (via web search) — and produce a go / stage / wait-for-print / stand-aside call with stop + sizing. Use whenever the user asks "should I buy/sell X now", "prep X before I act", "is now a good entry", "I'm about to trade X", points at a pretrade_* file, or questions today's move in a name they hold/watch — even if they don't say "skill".
---

# Pre-Trade Check

The weekly engine (`weekly_review.py`) emits mechanical intents from daily *cached* bars — a session
behind by the time the user trades. `pretrade.py` refreshes one name against LIVE data (intraday
quote, next-earnings date, option-positioning levels re-anchored to the live price). It is still
**blind to the newswire**: it can see that a stock gapped −11%, not *why*. Your job is that last
mile — find the catalyst, judge whether it's a gift or a trap, and turn the brief into a **timed**
action the user can execute. This is the MU walkthrough, productized: live tape + structure +
catalyst → go / stage / wait-for-print / stand-aside.

**Locate first** (newest wins): `output/<profile>/pretrade_*.md` and its sibling `.json` (the JSON
carries `live`, `scores`, re-anchored `levels`, `earnings`, `market_ctx`, `notes`). If no brief
exists for the name the user names, tell them to run `uv run pretrade.py SYM` first. Ground the
mechanics in the engine code — `quant/pretrade.py` (re-anchor math + gate), `quant/option_flow.py`
(walls/max-pain/expected-move), `quant/roles.py` (TP/SL) — so explanations are accurate, not remembered.

## What the brief gives you (and what it can't)
- **Live tape**: `live.last`, `prev_close`, session open/high/low, `today_move_pct`. The gap the
  engine couldn't see. `today_session=false` ⇒ market closed, `last` is a stale close — say so.
- **Re-anchored `levels`**: distances from the *live* price to put/call wall, max pain, role TP/SL,
  plus `live_rr` (reward:risk now). Yesterday's "0.0:1 at the call wall" becomes today's real odds.
- **`earnings`**: next date, `days_until`, `within_gate`, `expected_move_pct`. A soft gate (see below).
- **`market_ctx`**: SPY/QQQ day move + VIX + `idiosyncratic` flag — the engine's first guess at
  "name vs tape". Confirm or overturn it with the catalyst.
- **`portfolio`** + **`position`**: the real book — `cash`, `total_value`, `cash_status`, `deployable`
  (cash above the ceiling, i.e. what's actually spendable), and for this name `held`/`shares`,
  `current_weight` vs `target_weight`, `gap_to_target`, and `step_size` (one scale-in step, in $). This is
  what makes sizing concrete — use it.
- **`notes`**: re-anchored reads (entry zone, max-pain bounce, SL breach, gate, idiosyncratic).
- **What it CAN'T**: the reason for the move. Never invent it — go find it.

## Required enrichment — the catalyst (do this every time)
Run **WebSearch** for today's driver before judging. Classify into one of three — this is the whole call:
1. **Macro / sector beta** (the tape, a peer, a rate/CPI/FOMC move, a sector downgrade). The brief's
   `idiosyncratic=false` or a big peer move corroborates. → the dip is likely a **gift**; the thesis is intact.
2. **Profit-taking / positioning** (parabolic run unwinding, pre-earnings de-risking, an analyst
   trim, opex pin). → neutral; entry *timing* matters more than the drop itself.
3. **Thesis-breaking, company-specific** (guidance cut, demand crack, downgrade on fundamentals,
   governance/accounting, a lost customer). The brief's `idiosyncratic=true` with no macro peer move
   is the tell. → "cheap on forward PE" becomes a **value trap**; stand aside until it's clear.

Surface **only what you can confirm from a source — link it; never invent news.** If you can't find a
catalyst for an idiosyncratic move, that itself is a finding: *don't enter blind, investigate first*.
(Hard-won, MU 2026-06-23: an −11% gap looked alarming; the catalyst was a sector-wide "Black Tuesday"
selloff + pre-earnings de-risking, not an MU crack — a gift, except earnings landed in 2 days.)

## Judgment → a timed action
Combine catalyst + where the live price sits vs structure + the earnings gate into ONE call:

- **Price vs structure (re-anchored).** Buying into the call wall is buying resistance; buying near the
  put-wall / support confluence (or a max-pain bounce) is the engine's "buy near support". Use `live_rr`,
  not the stale report R:R. A breached role stop on a high-beta gap day is usually too-tight, not a sell
  signal — say which.
- **Earnings gate (SOFT — never a hard block).** Inside the gate, a binary print gaps *through* any stop,
  so **don't deploy full size**: either **wait for the print** (lower risk; let IV collapse, enter the
  reaction) or take a **small starter** (only if it's a core 1y+ hold regardless) and keep powder for the
  post-earnings reaction / the support add. A **cash-secured put at the put wall** is the IV-aware way to
  get paid to wait (rich pre-earnings premium; assigned = enter at support). Long calls into a print get
  crushed by IV collapse — flag that.
- **Role lens.** A `swing` entry is timing-sensitive (don't chase resistance); a `core` entry can accept a
  gap if sized as a long-term starter. If the brief flags a role mismatch, ask which horizon they're trading.
- **The call.** Pick one: **go now** / **stage** (starter here, add at $X) / **wait-for-print** /
  **stand-aside** — with an explicit stop / invalidation (e.g. "daily close below the put wall", not the
  too-tight role stop) and a sizing instruction. Honor the user's investor profile (long-term AI-supercycle,
  ~25% maxDD tolerance, options-aware).
- **Size in real dollars, not fractions.** Anchor every sizing call to `portfolio`/`position`: a starter is
  `≤ step_size` against `deployable` (e.g. "a ≤⅓ starter ≈ $1,000 of your $7,284 deployable"); a CSP at the
  put wall costs `100 × strike` of cash to secure — say whether `cash` covers it. If already `held`, frame
  the add as closing `gap_to_target`, and don't push past `target_weight`. If `deployable` is ~0 (cash at/below
  the ceiling), say so — the honest call may be "no room without selling something," not a clean buy.

## Output
Lead with a one-line **bottom line** (the call), then: the catalyst (classified, linked), the
re-anchored read (where price sits vs structure now), the earnings gate consequence, and the staged
plan with stop + sizing. Then **append a `## Catalyst & Timed Action` section to the brief `.md`**
(Edit the file in place — the script left a placeholder) so the report evolves from data → judgment,
exactly like the MU `.md` did. Close with the one open question (usually horizon, or "confirm the
catalyst isn't thesis-breaking"). The user thinks like a PM — give the tradeoff, not a data dump.
End with a **Sources:** list of the links you used.
