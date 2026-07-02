"""Daily review entry point: run AFTER the close to capture the day and accumulate a database.

Same engine as weekly_review.py (quant.pipeline.run) but on a daily cadence, with two additions:
(1) an abnormal-volume overlay (RVOL + z-score) and an outliers section the `daily-review` skill
explains; (2) it APPENDS one row per symbol to a growing parquet store at
data/daily_observations/<profile>/<YYYY-MM-DD>.parquet — so the day's indicators, scores, and the
engine's per-symbol judgment (state + next-day intent) accumulate as a labelled time series to mine
and grade later. The judgment is a label; the store is the database.

    uv run daily_review.py
"""
from __future__ import annotations

import os

from quant import clock, daily_report, observations, pipeline, profiles

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, WATCHLIST, OPTIONS, OUT_DIR = profiles.resolve(ROOT)
PROFILE = os.environ.get("PROFILE", "demo")
STORE = os.path.join(ROOT, "data", "daily_observations", PROFILE)


def main() -> None:
    # force_refresh: the daily review runs after the close and must capture TODAY's bar even if an
    # earlier same-day run cached a file holding only the prior session. breadth="full": the DB needs
    # walls/max-pain/IV for every portfolio + watchlist name, not just the actionable set.
    ctx = pipeline.run(
        CONFIG, PORTFOLIO, WATCHLIST, OPTIONS,
        force_refresh=True, breadth="full", iv_hist_store=STORE,
    )

    now = clock.now()
    as_of_date = clock.datestamp(now)
    generated_at = clock.timestamp(now)

    # Raw daily bar per symbol, and a freshness check: the close is only "today's" if the latest bar
    # IS today. Warn loudly otherwise (market open / weekend / holiday / vendor lag). as_of_bar (the
    # session) keys the file/sidecar, so it must be resolved before they are written.
    ohlcv = {sym: observations.last_bar(ctx.history[sym]) for sym in ctx.signals}
    as_of_bar = max((b["bar_date"] for b in ohlcv.values()), default=as_of_date)
    stale = as_of_bar < as_of_date
    if stale:
        print(f"  ⚠ latest daily bar is {as_of_bar}, not today {as_of_date} — close is the PRIOR "
              f"session (market still open, weekend/holiday, or vendor lag). Run after the close.")

    # Provenance: stamp every row with the code + hyperparameter set that produced it, and snapshot
    # the resolved config to a sidecar so a historical decision can be replayed / re-optimized later.
    git_sha = observations.git_sha(ROOT)
    config_hash = observations.record_run_meta(STORE, as_of_bar, ctx.cfg, git_sha, generated_at)
    rows, outliers = observations.build_rows(
        ctx, cadence="daily", prior_states=observations.prior_states(STORE, as_of_bar),
        prior_macd_hist=observations.prior_macd_hist(STORE, as_of_bar),
        git_sha=git_sha, config_hash=config_hash, generated_at=generated_at, ohlcv=ohlcv,
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = clock.file_stamp(now)
    md_path = os.path.join(OUT_DIR, f"daily_review_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"daily_review_{stamp}.json")
    # Report shows positioning for the actionable set only (keeps the .md focused); the full-universe
    # positioning still lands in the observation store above.
    actionable = {r.symbol for r in ctx.holding_recs} | {r.symbol for r in ctx.watchlist_recs}
    report_positioning = {k: v for k, v in ctx.positioning.items() if k in actionable}
    daily_report.generate(
        md_path, json_path, generated_at, ctx.mkt, ctx.holding_recs, ctx.watchlist_recs,
        ctx.option_analyses, ctx.summary, ctx.fundamentals, report_positioning, ctx.roleviews,
        outliers, ohlcv=ohlcv, as_of_bar=as_of_bar, stale=stale, macro=ctx.macro_state,
        sector=ctx.sector_state,
    )
    print(f"Report written to {md_path}")
    print(f"  {len(outliers)} outlier(s) flagged")
    print("  " + observations.record(STORE, as_of_bar, rows, cadence="daily"))


if __name__ == "__main__":
    main()
