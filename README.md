# Investment Assistant

A weekly **decision engine** for a long-term AI-equity portfolio that uses options to
enhance returns. Run one script every weekend; it reads your portfolio + market data and
prints an **action list** answering a single question: *"What should I do next week?"*

It is a **decision engine, not a prediction engine.** It does not forecast prices or try to
beat the market. Its value is **discipline and time saved**: the same rules applied
unemotionally every week, so buy/sell/hedge calls stop being driven by gut feeling.

> **Honest framing.** The thresholds in `config/config.yaml` are *codified judgment*, not
> statistically validated edges. v0.1 makes your process consistent and repeatable — it does
> not prove the rules make money. A backtest (future version) is what would justify trusting
> them. The design (score-based features + JSON output) is built so a backtest can be added
> without a rewrite.

## What it does (v0.1)

- Pulls free OHLCV data via `yfinance` for your holdings, watchlist, and SPY/QQQ/VIX.
- Computes a market **regime** (Panic → Strong Bull) and per-symbol **scores** (trend, momentum).
- Compares each holding's weight to its target and applies a small **rule table** to produce an
  **intent**: Add Core / Trim / Hold / Generate Income / Hedge.
- Lightly scans the rest of the watchlist for **Increase Exposure** candidates.
- Writes `output/weekly_report.md` (read this) and `output/weekly_report.json` (for future tooling).

Intents are *intentions*, not trades — the report suggests which option structure could express
each intent, but **you pick the strikes and expiries.** No options-chain data is used in v0.1.

## Setup & run

```bash
uv sync                       # install dependencies
uv run weekly_review.py       # generate this week's report
uv run pytest                 # run the test suite
```

## Configure

- `data/portfolio.yaml` — your cash + holdings (update by hand each week).
- `data/watchlist.yaml` — symbols to scan.
- `config/config.yaml` — target weights, drift band, cash band, score thresholds,
  and the intent → option-strategy hint map.

## Not in v0.1 (by design)

Options-chain / strike selection · IV Rank · AI-written analysis · backtesting ·
broker integration / auto-trading · ML parameter tuning.
