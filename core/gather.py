"""The Gatherer — where `known_at` is born.

`architecture/DATA_PIPELINE.md` at seed scale: the Gatherer observes the world and records raw
**Facts**, stamping each with the instant it *first* became known. It is the only door into Memory,
and the one honest place `known_at` is assigned.

The load-bearing rule is **first-seen, not last-fetch**:
  - a genuinely new observation  → a new Fact, `known_at = now`;
  - an unchanged re-fetch        → nothing (we already knew it — `known_at` stays first-known);
  - a *changed* value (revision) → a new Fact, `known_at = now`, the old one preserved.

That last case is why this matters: yfinance fetches `auto_adjust=True`, so a split silently rewrites
history in a mutable store. Here the split arrives as an honest, dated **revision** — a new Fact — and
the past is never overwritten. The Gatherer owns this policy; the Memory just stores (separation).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import polars as pl

from core import clock
from core.memory import Memory
from core.record import Fact

# A Fetch turns a subject into a bar frame: columns date, open, high, low, close, volume.
Fetch = Callable[[str], "pl.DataFrame | None"]
FundamentalFetch = Callable[[list[str], dict], "dict[str, dict | None]"]

_METRICS = ("open", "high", "low", "close", "volume")
_FUNDAMENTAL_NUMERIC_METRICS = (
    "pe",
    "forward_pe",
    "peg",
    "pb",
    "ev_ebitda",
    "profit_margin",
    "rev_growth",
    "eps_growth",
    "analyst_target",
    "beta",
)
_FUNDAMENTALS_CACHE = Path("data/cache/fundamentals.json")
_YF_FUNDAMENTAL_MAP = {
    "sector": "sector",
    "pe": "trailingPE",
    "forward_pe": "forwardPE",
    "pb": "priceToBook",
    "ev_ebitda": "enterpriseToEbitda",
    "profit_margin": "profitMargins",
    "rev_growth": "revenueGrowth",
    "eps_growth": "earningsQuarterlyGrowth",
    "analyst_target": "targetMeanPrice",
    "beta": "beta",
}

# Two observations of the same thing are "the same" if they agree to the precision the data is quoted
# at — prices to the cent, volume to the share. This stops a panel value rounded to 2dp from reading
# as a revision of the full-precision live fetch, while a genuine cent-level move or a split still does.
# Full precision is always *stored*; the tolerance only governs the unchanged-vs-revised decision.
_TOL = {"open": 0.005, "high": 0.005, "low": 0.005, "close": 0.005, "volume": 0.5}


def _same(metric: str, a: float, b: float) -> bool:
    tol = _TOL.get(metric)
    if tol is not None:
        return abs(a - b) <= tol
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1.0)   # unknown metric: relative fallback


def _num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "None", "-", "NaN", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _event_date_from_fetched(fetched: object) -> date:
    if isinstance(fetched, str):
        try:
            return date.fromisoformat(fetched)
        except ValueError:
            pass
    return clock.today()


def _read_fundamentals_cache(cache_path: str | Path = _FUNDAMENTALS_CACHE) -> dict[str, dict]:
    path = Path(cache_path)
    if path.exists():
        try:
            return json.loads(path.read_text()) or {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _map_yf_fundamentals(info: dict) -> dict:
    out = {canonical: info.get(yf_key) for canonical, yf_key in _YF_FUNDAMENTAL_MAP.items()}
    out["peg"] = info.get("trailingPegRatio", info.get("pegRatio"))
    return out


def _download_fundamentals_yf(symbol: str) -> dict | None:
    try:
        import yfinance as yf  # local import: core remains importable without provider extras

        info = yf.Ticker(symbol).info
    except Exception:
        return None
    if not info:
        return None
    mapped = _map_yf_fundamentals(info)
    return mapped if any(value is not None for value in mapped.values()) else None


def fetch_fundamentals(
    symbols: list[str],
    cfg: dict,
    cache_path: str | Path = _FUNDAMENTALS_CACHE,
) -> dict[str, dict | None]:
    """Fetch canonical fundamentals with the original cache freshness policy.

    Fundamentals are slow-moving: use a fresh cache entry when available, refetch stale/mismatched
    entries, and serve stale cache if the live yfinance request fails.
    """
    fund_cfg = cfg.get("fundamentals", {}) if cfg else {}
    out: dict[str, dict | None] = {s: None for s in symbols}
    if not fund_cfg.get("enabled", False):
        return out
    source = fund_cfg.get("source", "yfinance")
    if source != "yfinance":
        print(f"  ! core fundamentals.source {source!r} is not supported yet — skipping")
        return out

    refresh_days = fund_cfg.get("refresh_days", 7)
    today = clock.today()
    path = Path(cache_path)
    cached = _read_fundamentals_cache(path)
    dirty = False

    def fresh(entry: dict) -> bool:
        try:
            return (today - date.fromisoformat(entry["fetched"])).days < refresh_days
        except (KeyError, ValueError):
            return False

    def serve(entry: dict, stale: bool) -> dict:
        return {
            **entry["raw"],
            "_fetched": entry["fetched"],
            "_stale": stale,
            "_source": entry.get("source", source),
        }

    for symbol in symbols:
        entry = cached.get(symbol)
        if entry and entry.get("source") != source:
            entry = None
        if entry and fresh(entry):
            out[symbol] = serve(entry, stale=False)
            continue

        raw = _download_fundamentals_yf(symbol)
        if raw is None:
            if entry:
                out[symbol] = serve(entry, stale=True)
            continue

        fetched = today.isoformat()
        cached[symbol] = {"raw": raw, "fetched": fetched, "source": source}
        dirty = True
        out[symbol] = {**raw, "_fetched": fetched, "_stale": False, "_source": source}

    if dirty:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cached, indent=2, sort_keys=True))
    return out


@dataclass(frozen=True, slots=True)
class GatherResult:
    subject: str
    new: int          # observations seen for the first time
    revised: int      # values that changed vs the current belief
    unchanged: int    # already known, identical — no record written

    @property
    def written(self) -> int:
        return self.new + self.revised


def _append_if_changed(
    memory: Memory,
    subject: str,
    event_at: date,
    known_at: datetime,
    provenance: str,
    metric: str,
    value: float,
    payload: str = "",
) -> tuple[Fact | None, str]:
    prior = memory.latest_fact(subject, metric, event_at, known_at)
    if prior is None:
        return (
            Fact(
                kind="fact", subject=subject, event_at=event_at, known_at=known_at,
                provenance=provenance, metric=metric, value=value, payload=payload,
            ),
            "new",
        )
    if _same(metric, prior.value, value) and prior.payload == payload:
        return None, "unchanged"
    return (
        Fact(
            kind="fact", subject=subject, event_at=event_at, known_at=known_at,
            provenance=provenance, metric=metric, value=value, payload=payload,
        ),
        "revised",
    )


def gather(memory: Memory, subject: str, fetch: Fetch, now: datetime | None = None) -> GatherResult:
    """Observe `subject` via `fetch` and record first-seen / revised raw Facts into Memory.

    `fetch` is injected so tests use synthetic bars and only the demo touches the network.
    """
    at = now or clock.now()
    frame = fetch(subject)
    if frame is None or frame.height == 0:
        return GatherResult(subject, 0, 0, 0)

    new = revised = unchanged = 0
    to_write: list[Fact] = []
    for row in frame.sort("date").iter_rows(named=True):
        event_at: date = row["date"]
        for metric in _METRICS:
            value = row.get(metric)
            if value is None:
                continue
            value = float(value)
            prior = memory.latest_fact(subject, metric, event_at, at)
            if prior is None:
                new += 1
            elif _same(metric, prior.value, value):
                unchanged += 1
                continue                       # already known — first-known known_at preserved
            else:
                revised += 1                   # a revision: a new record, old one kept
            to_write.append(Fact(
                kind="fact", subject=subject, event_at=event_at, known_at=at,
                provenance="gatherer@v1", metric=metric, value=value,
            ))

    memory.append(to_write)
    return GatherResult(subject, new, revised, unchanged)


def _gather_fundamental_raw(
    memory: Memory,
    subject: str,
    raw: dict | None,
    known_at: datetime,
) -> GatherResult:
    if not raw:
        return GatherResult(subject, 0, 0, 0)

    fetched = raw.get("_fetched")
    event_at = _event_date_from_fetched(fetched)
    metadata = {
        "sector": raw.get("sector"),
        "source": raw.get("_source", ""),
        "fetched": fetched,
        "stale": raw.get("_stale", False),
    }
    payload = json.dumps(metadata, sort_keys=True)

    new = revised = unchanged = 0
    to_write: list[Fact] = []
    meta_fact, state = _append_if_changed(
        memory, subject, event_at, known_at, "fundamentals_fetcher@v1",
        "fundamental.metadata", 0.0, payload,
    )
    if state == "new":
        new += 1
    elif state == "revised":
        revised += 1
    else:
        unchanged += 1
    if meta_fact is not None:
        to_write.append(meta_fact)

    for key in _FUNDAMENTAL_NUMERIC_METRICS:
        value = _num(raw.get(key))
        if value is None:
            continue
        fact, state = _append_if_changed(
            memory, subject, event_at, known_at, "fundamentals_fetcher@v1",
            f"fundamental.{key}", value, payload,
        )
        if state == "new":
            new += 1
        elif state == "revised":
            revised += 1
        else:
            unchanged += 1
        if fact is not None:
            to_write.append(fact)

    memory.append(to_write)
    return GatherResult(subject, new, revised, unchanged)


def gather_fundamentals(
    memory: Memory,
    subjects: list[str],
    cfg: dict,
    now: datetime | None = None,
    fetch: FundamentalFetch | None = None,
) -> dict[str, GatherResult]:
    """Fetch/cache fundamentals, then record the returned raw metrics as Facts."""
    at = now or clock.now()
    fetcher = fetch or fetch_fundamentals
    raw_by_subject = fetcher(subjects, cfg)
    return {
        subject: _gather_fundamental_raw(memory, subject, raw_by_subject.get(subject), at)
        for subject in subjects
    }


def yf_fetch(subject: str, period: str = "3y") -> pl.DataFrame | None:
    """Live OHLCV from yfinance → polars [date, open, high, low, close, volume].

    A lean port of `quant/providers.py`'s history path (auto_adjust=True), kept here so `core/`
    never imports `quant`. Network-touching; used by the demo, never by tests.
    """
    import yfinance as yf  # local import: keeps the module importable without a network stack

    pdf = yf.Ticker(subject).history(period=period, auto_adjust=True)
    if pdf is None or pdf.empty:
        return None
    pf = pl.from_pandas(pdf.reset_index())
    date_col = "Date" if "Date" in pf.columns else pf.columns[0]
    return (
        pf.rename({date_col: "date"})
        .with_columns(pl.col("date").cast(pl.Date))
        .select(
            pl.col("date"),
            pl.col("Open").alias("open"), pl.col("High").alias("high"),
            pl.col("Low").alias("low"), pl.col("Close").alias("close"),
            pl.col("Volume").cast(pl.Float64).alias("volume"),
        )
        .drop_nulls()
    )
