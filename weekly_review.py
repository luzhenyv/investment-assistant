"""Weekly review entry point: load → fetch → score → decide → report.

Recomputes a fresh strategic snapshot via quant.pipeline.run (independent of the daily store) and
also appends its own per-symbol rows to the observation store under cadence="weekly", so weekly
decisions are graded later alongside the daily labels (the file gets a `__weekly` suffix so it never
overwrites the daily session file).

    uv run weekly_review.py
"""
from __future__ import annotations

import os

from quant import clock, observations, pipeline, profiles, report

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, WATCHLIST, OPTIONS, OUT_DIR = profiles.resolve(ROOT)
PROFILE = os.environ.get("PROFILE", "demo")
STORE = os.path.join(ROOT, "data", "daily_observations", PROFILE)


def main() -> None:
    # Weekly stays on cached bars (force_refresh=False) and the actionable set (held + watchlist
    # recs). iv_hist_store anchors weekly IV-rank to the accumulated daily ATM-IV history.
    ctx = pipeline.run(
        CONFIG, PORTFOLIO, WATCHLIST, OPTIONS,
        force_refresh=False, breadth="actionable", iv_hist_store=STORE, include_unconfigured=True,
    )

    now = clock.now()
    generated_at = clock.timestamp(now)   # in-file header + JSON field (UTC)
    stamp = clock.file_stamp(now)         # filename suffix (sortable, no colons; UTC)

    # Append a weekly-cadence snapshot to the observation store (non-actionable names get null
    # option/role columns — weekly computes positioning for the actionable set only).
    git_sha = observations.git_sha(ROOT)
    ohlcv = {sym: observations.last_bar(ctx.history[sym]) for sym in ctx.signals}
    as_of_bar = max((b["bar_date"] for b in ohlcv.values()), default=clock.datestamp(now))
    config_hash = observations.record_run_meta(STORE, as_of_bar, ctx.cfg, git_sha, generated_at,
                                               cadence="weekly")
    rows, _ = observations.build_rows(
        ctx, cadence="weekly", prior_states={}, git_sha=git_sha, config_hash=config_hash,
        generated_at=generated_at, ohlcv=ohlcv,
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    md_path = os.path.join(OUT_DIR, f"weekly_report_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"weekly_report_{stamp}.json")
    report.generate(
        md_path, json_path, generated_at, ctx.mkt, ctx.holding_recs, ctx.watchlist_recs,
        ctx.option_analyses, ctx.summary, ctx.fundamentals, ctx.positioning, ctx.roleviews,
        macro=ctx.macro_state, sector=ctx.sector_state,
    )
    print(f"Report written to {md_path}")
    print("  " + observations.record(STORE, as_of_bar, rows, cadence="weekly"))


if __name__ == "__main__":
    main()
