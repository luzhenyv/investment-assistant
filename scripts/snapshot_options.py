"""Accumulate daily option-chain snapshots from yfinance.

    uv run python scripts/snapshot_options.py            # active PROFILE's watchlist + holdings
    uv run python scripts/snapshot_options.py NVDA AVGO  # explicit tickers

yfinance only serves the CURRENT chain (no history) — which is exactly why we must capture it
ourselves, daily, to eventually edge-validate an options gamma/positioning S/R layer
(sr-roadmap item 4; see the TODO in quant/levels.py). Each run writes one parquet per symbol:

    data/options_snapshots/<SYMBOL>/<YYYY-MM-DD>.parquet

Idempotent per (symbol, date): a symbol already captured today is skipped, so re-running is
safe and a missed day just leaves a gap. Best run once daily AFTER the US close (OI is
end-of-day and published with ~1 trading-day lag).

We keep raw openInterest / volume / IV per strike (the inputs for OI walls, max pain, and a
Black-Scholes GEX), and bound file size to expiries within MAX_DTE and strikes near spot —
far/long-dated contracts are noise for near-term S/R.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import polars as pl
import yaml
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant import clock, profiles  # noqa: E402

STORE = os.path.join(ROOT, "data", "options_snapshots")
MAX_DTE = 120          # ignore expiries beyond ~4 months (sorted asc -> we can stop early)
MAX_EXPIRIES = 12      # cap option_chain calls per symbol (rate-limit friendly)
STRIKE_LO, STRIKE_HI = 0.5, 1.6   # keep strikes within this fraction of spot

_NUM = {"strike": pl.Float64, "openInterest": pl.Float64, "volume": pl.Float64,
        "impliedVolatility": pl.Float64, "lastPrice": pl.Float64, "bid": pl.Float64, "ask": pl.Float64}


def _universe() -> list[str]:
    """Default universe = active profile's watchlist + current holdings (optionable or not;
    non-optionable names are skipped gracefully)."""
    _, portfolio, watchlist, _, _ = profiles.resolve(ROOT)
    watch = (yaml.safe_load(open(watchlist)) or {}).get("symbols", [])
    port = (yaml.safe_load(open(portfolio)) or {}).get("positions", {})
    return sorted(set(watch) | set(port))


def _spot(tk: yf.Ticker) -> float | None:
    try:
        px = float(tk.fast_info["lastPrice"])
        if px > 0:
            return px
    except Exception:  # noqa: BLE001
        pass
    try:
        return float(tk.history(period="5d")["Close"].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


def _side_frame(pdf, right: str) -> pl.DataFrame:
    """One side (calls or puts) -> normalized Polars frame with a `right` column."""
    f = pl.from_pandas(pdf)
    exprs = [
        (pl.col(c).cast(t, strict=False) if c in f.columns else pl.lit(None, dtype=t)).alias(c)
        for c, t in _NUM.items()
    ]
    return f.select(exprs).with_columns(pl.lit(right).alias("right"))


def _snapshot(sym: str, today: dt.date, ts: str) -> str:
    out_dir = os.path.join(STORE, sym)
    out_path = os.path.join(out_dir, f"{today.isoformat()}.parquet")
    if os.path.exists(out_path):
        return "skip (already captured today)"
    tk = yf.Ticker(sym)
    try:
        expiries = tk.options
    except Exception:  # noqa: BLE001
        return "no option chain"
    if not expiries:
        return "no option chain"
    spot = _spot(tk)
    if not spot:
        return "no spot price"

    frames: list[pl.DataFrame] = []
    used = 0
    for e in expiries:  # ISO strings sort chronologically
        dte = (dt.date.fromisoformat(e) - today).days
        if dte < 0:
            continue
        if dte > MAX_DTE or used >= MAX_EXPIRIES:
            break
        try:
            chain = tk.option_chain(e)
        except Exception:  # noqa: BLE001
            continue
        used += 1
        for right, pdf in (("call", chain.calls), ("put", chain.puts)):
            frames.append(_side_frame(pdf, right).with_columns(
                pl.lit(e).alias("expiry"), pl.lit(dte).alias("dte")))

    if not frames:
        return "empty"
    df = (
        pl.concat(frames, how="vertical")
        .filter((pl.col("strike") >= spot * STRIKE_LO) & (pl.col("strike") <= spot * STRIKE_HI))
        .with_columns(
            pl.col("openInterest").fill_null(0),
            pl.col("volume").fill_null(0),
            pl.lit(sym).alias("symbol"),
            pl.lit(spot).alias("spot"),
            pl.lit(today.isoformat()).alias("as_of_date"),
            pl.lit(ts).alias("as_of_ts"),
        )
        .rename({"openInterest": "open_interest", "impliedVolatility": "iv", "lastPrice": "last"})
    )
    if df.height == 0:
        return "empty (after strike-band filter)"
    os.makedirs(out_dir, exist_ok=True)
    df.write_parquet(out_path)
    return f"ok — {df.height} rows, {used} expiries, spot {spot:.2f}"


def main() -> None:
    tickers = [a.upper() for a in sys.argv[1:]] or _universe()
    today = clock.today()
    ts = clock.now().isoformat(timespec="seconds")
    print(f"Snapshotting {len(tickers)} symbols for {today.isoformat()} -> {STORE}")
    ok = 0
    for sym in tickers:
        status = _snapshot(sym, today, ts)
        if status.startswith("ok"):
            ok += 1
        print(f"  {sym:6} {status}")
    print(f"Done: {ok}/{len(tickers)} captured.")


if __name__ == "__main__":
    main()
