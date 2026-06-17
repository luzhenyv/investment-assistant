---
name: backtest-review
description: Review a trading-strategy backtest for trustworthiness against Ernest Chan's "Quantitative Trading" Ch. 3 — performance measures, look-ahead bias, data-snooping/overfitting, survivorship bias, transaction costs, data quality. Works on any project. Use for "review my backtest", "is this backtest realistic/trustworthy", "check for bias or overfitting", "backtest sanity check".
---

# Backtest Review

Find the reasons live results will be **worse** than the backtest, and say how much to trust the
strategy (Chan, *Quantitative Trading*, Ch. 3).

**Locate first** (search, don't assume paths): the backtest engine/runner, the strategy config/
parameters, the traded universe, and the results/equity curve. Ask the user if one can't be found.

## Checklist — grade each OK / Caution / Problem, with a one-line reason + one fix

1. **Performance measures** — needs annualized **Sharpe** + **max drawdown** + **DD duration**;
   return/CAGR alone hide risk. If Sharpe missing, estimate from returns: `r_t = eq_t/eq_{t-1}-1`,
   `Sharpe ≈ sqrt(P)·mean(r)/std(r)` (P = 252 daily / 52 weekly / 12 monthly; match the cadence).
2. **Look-ahead bias** — signals from as-of/lagged data only; fills never use a bar after the
   signal bar; no full-sample fit then trade same sample. Recommend the truncation A/B test
   (re-run on data cut by N≈10–100 days; overlapping positions must be identical).
3. **Data-snooping / overfitting** — ≤ 5 free params (hand-set weights count too); is there an
   out-of-sample / train-test split? Bailey sample size: Sharpe ≈ 1 needs ~681 pts (~2.7 yr daily);
   true Sharpe ≥ 1 needs backtest Sharpe ≥ 1.5 over ~2,739 pts (~10.9 yr). Each tweak deflates live Sharpe.
4. **Survivorship / selection bias** — universe hindsight-picked from known winners? Were
   delisted/failed names eligible at the start? Compare honestly to a passive benchmark.
5. **Transaction costs** — commissions + slippage + market impact modeled? (~5 bps large-cap; more
   if illiquid). If zero, estimate `turnover × cost`; results are a ceiling. Cost can flip Sharpe negative.
6. **Data quality** — split/dividend adjusted? Any reliance on noisy daily high/low or gappy data?
7. **Refinement discipline** — any tuning must improve **both** train and test sets and have an
   economic rationale, not curve-fit one history.

## Report (chat only — no file writes / no edits unless asked)

Per-item verdict + reason, the numbers you computed (Sharpe, DD duration), top 2–3 fixes by
priority, and a one-line bottom line on trust (and: paper-trade — the ultimate out-of-sample test).
