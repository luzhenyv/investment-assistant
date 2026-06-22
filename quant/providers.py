"""Market-data access. Thin wrapper over yfinance backed by a Parquet cache, so a
run survives a flaky download by reusing local data. Network I/O lives only here.

yfinance returns pandas; we convert to Polars at this boundary and everything
downstream is Polars. Canonical frame schema: date (Date) + OHLCV columns."""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request

import polars as pl
import yfinance as yf

from quant import cache

_SECTOR_CACHE = cache.CACHE_DIR / "sectors.json"
_FUNDAMENTALS_CACHE = cache.CACHE_DIR / "fundamentals.json"
_AV_URL = "https://www.alphavantage.co/query?function=OVERVIEW&symbol={sym}&apikey={key}"
# AV OVERVIEW fields we keep (everything else is dropped to keep the cache small).
_AV_FIELDS = (
    "Sector", "PERatio", "ForwardPE", "PEGRatio", "PriceToBookRatio", "EVToEBITDA",
    "ProfitMargin", "QuarterlyRevenueGrowthYOY", "QuarterlyEarningsGrowthYOY",
    "AnalystTargetPrice", "Beta",
)


def _to_polars(pdf, columns: list[str]) -> pl.DataFrame:
    """yfinance pandas frame -> Polars frame with a tz-free `date` column."""
    pf = pl.from_pandas(pdf.reset_index())
    date_col = "Date" if "Date" in pf.columns else pf.columns[0]
    return (
        pf.rename({date_col: "date"})
        .with_columns(pl.col("date").cast(pl.Date))
        .select(["date", *columns])
        .drop_nulls()
    )


def _download_history(symbol: str, period: str) -> pl.DataFrame | None:
    pdf = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if pdf.empty:
        return None
    return _to_polars(pdf, ["Open", "High", "Low", "Close", "Volume"])


def _download_vix(period: str) -> pl.DataFrame | None:
    pdf = yf.Ticker("^VIX").history(period=period)
    if pdf.empty:
        return None
    return _to_polars(pdf, ["Close"])


def fetch_history(
    symbols: list[str], period: str, min_rows: int
) -> dict[str, pl.DataFrame]:
    """Return {symbol: OHLC Polars frame}. Symbols with no usable data are skipped.

    `period` and `min_rows` come from the `data` section of config.yaml."""
    out: dict[str, pl.DataFrame] = {}
    for sym in symbols:
        df = cache.load_or_fetch(
            sym, lambda s=sym: _download_history(s, period), min_rows=min_rows
        )
        if df is None:
            print(f"  ! skipping {sym}: insufficient data")
            continue
        out[sym] = df
    return out


def fetch_option_chain(symbol: str, expiry: str) -> dict[tuple[str, float], float] | None:
    """Live implied volatility per contract for one expiry: {(right, strike): iv}.

    `expiry` is an ISO date string. Returns None when the expiry isn't listed or the
    download fails (caller degrades to no-Greeks). Deep-ITM / illiquid strikes report
    garbage IV from yfinance, so anything NaN or outside (0.01, 3.0) is dropped."""
    try:
        tk = yf.Ticker(symbol)
        if expiry not in tk.options:
            return None
        chain = tk.option_chain(expiry)
    except Exception:
        return None

    ivs: dict[tuple[str, float], float] = {}
    for right, frame in (("call", chain.calls), ("put", chain.puts)):
        for strike, iv in zip(frame["strike"], frame["impliedVolatility"]):
            iv = float(iv)
            if 0.01 < iv < 3.0:
                ivs[(right, float(strike))] = iv
    return ivs


def _download_sector(symbol: str) -> str | None:
    """The symbol's GICS-style sector from yfinance, or None if unavailable."""
    try:
        return yf.Ticker(symbol).info.get("sector") or None
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None


def _read_sector_cache() -> dict[str, str]:
    if _SECTOR_CACHE.exists():
        try:
            return json.loads(_SECTOR_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_cached_sectors(symbols: list[str]) -> dict[str, str]:
    """Read sectors from the on-disk cache only — no network. Used by the backtester
    so replays are reproducible and offline. Unknown/uncached symbols => "Unknown"."""
    cached = _read_sector_cache()
    return {s: cached.get(s, "Unknown") for s in symbols}


def fetch_sectors(symbols: list[str]) -> dict[str, str]:
    """Return {symbol: sector}, backed by a persistent JSON cache at
    `data/cache/sectors.json`. Sector is effectively static, so only symbols missing
    from the cache are fetched; successful lookups are persisted while failures fall
    back to "Unknown" for this run and retry next time (a transient outage never
    poisons the cache). The on-disk file lets the backtester read sectors without any
    network I/O, keeping replays reproducible."""
    cached = _read_sector_cache()
    fetched = {s: sec for s in symbols if s not in cached if (sec := _download_sector(s))}
    if fetched:
        cached.update(fetched)
        _SECTOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _SECTOR_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True))
    return {s: cached.get(s, "Unknown") for s in symbols}


def _read_fundamentals_cache() -> dict[str, dict]:
    if _FUNDAMENTALS_CACHE.exists():
        try:
            return json.loads(_FUNDAMENTALS_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _download_overview(symbol: str, key: str) -> dict | None:
    """One Alpha Vantage OVERVIEW call. Returns the trimmed field dict, or None on
    failure / throttle / premium notice ("Information"/"Note"/"Error Message" keys)."""
    try:
        with urllib.request.urlopen(_AV_URL.format(sym=symbol, key=key), timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    if not isinstance(data, dict) or not data.get("Symbol"):
        return None  # throttle/premium/empty -> no usable fundamentals
    return {f: data.get(f) for f in _AV_FIELDS}


def fetch_fundamentals(symbols: list[str], cfg: dict) -> dict[str, dict | None]:
    """Return {symbol: OVERVIEW-field dict (+ "_fetched"/"_stale") or None}, backed by a
    persistent JSON cache at `data/cache/fundamentals.json`.

    Fundamentals move quarterly, so a symbol is refetched only when its cached copy is
    older than `fundamentals.refresh_days`. Live calls are capped at
    `fundamentals.max_api_calls_per_run` to respect the free 25/day budget; on the first
    AV failure/throttle we stop calling for the rest of the run and serve stale cache.
    Disabled (returns all-None) when `fundamentals.enabled` is false or the
    ALPHAVANTAGE_API_KEY env var is unset."""
    fund = cfg.get("fundamentals", {})
    out: dict[str, dict | None] = {s: None for s in symbols}
    if not fund.get("enabled", False):
        return out
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        print("  ! fundamentals enabled but ALPHAVANTAGE_API_KEY unset — skipping")
        return out

    refresh_days = fund.get("refresh_days", 7)
    budget = fund.get("max_api_calls_per_run", 20)
    today = dt.date.today()
    cached = _read_fundamentals_cache()
    calls = 0
    stop = False
    dirty = False

    for sym in symbols:
        entry = cached.get(sym)
        fresh_enough = False
        if entry:
            try:
                age = (today - dt.date.fromisoformat(entry["fetched"])).days
                fresh_enough = age < refresh_days
            except (KeyError, ValueError):
                fresh_enough = False
        if entry and (fresh_enough or stop or calls >= budget):
            out[sym] = {**entry["raw"], "_fetched": entry["fetched"], "_stale": not fresh_enough}
            continue
        if stop or calls >= budget:
            continue  # no cache and no budget — leave None
        calls += 1
        raw = _download_overview(sym, key)
        if raw is None:
            stop = True  # throttled/premium — don't burn the rest of the budget
            if entry:  # serve stale if we have anything
                out[sym] = {**entry["raw"], "_fetched": entry["fetched"], "_stale": True}
            continue
        fetched = today.isoformat()
        cached[sym] = {"raw": raw, "fetched": fetched}
        dirty = True
        out[sym] = {**raw, "_fetched": fetched, "_stale": False}

    if dirty:
        _FUNDAMENTALS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FUNDAMENTALS_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True))
    if calls:
        print(f"  fundamentals: {calls} Alpha Vantage call(s) this run")
    return out


def load_cached_fundamentals(symbols: list[str]) -> dict[str, dict | None]:
    """Read fundamentals from the on-disk cache only — no network (parity with
    load_cached_sectors). Unknown/uncached symbols => None."""
    cached = _read_fundamentals_cache()
    return {
        s: ({**cached[s]["raw"], "_fetched": cached[s]["fetched"], "_stale": True} if s in cached else None)
        for s in symbols
    }


def fetch_vix_history(period: str) -> pl.DataFrame | None:
    """Full VIX close history (cached) — used by the backtester for as-of lookups."""
    return cache.load_or_fetch("VIX", lambda: _download_vix(period), min_rows=1)


def fetch_vix(period: str) -> float:
    """Latest VIX close. Falls back to 20 (neutral) if unavailable."""
    df = fetch_vix_history(period)
    if df is None:
        print("  ! VIX unavailable, assuming 20")
        return 20.0
    return float(df["Close"].tail(1).item())
