"""Market-data access. Thin wrapper over yfinance backed by a Parquet cache, so a
run survives a flaky download by reusing local data. Network I/O lives only here.

yfinance returns pandas; we convert to Polars at this boundary and everything
downstream is Polars. Canonical frame schema: date (Date) + OHLCV columns."""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

import polars as pl
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from quant import cache, clock

_SECTOR_CACHE = cache.CACHE_DIR / "sectors.json"
_FUNDAMENTALS_CACHE = cache.CACHE_DIR / "fundamentals.json"
_MACRO_CACHE = cache.CACHE_DIR / "macro.json"
_AV_URL = "https://www.alphavantage.co/query?function=OVERVIEW&symbol={sym}&apikey={key}"
_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
# Default FRED series for the macro lens (quant/macro.py) — tight, long-duration-equity-relevant.
_DEFAULT_MACRO_SERIES = ("DGS10", "DGS2", "DFII10", "T10YIE", "BAMLH0A0HYM2", "NFCI")


# --- Shared helpers ------------------------------------------------------------------- #
_YF_MAX_RETRIES = 3
_YF_BASE_DELAY = 2.0


def _is_empty(result) -> bool:
    """A yfinance return carrying no usable data (retryable soft failure)."""
    if result is None:
        return True
    empty = getattr(result, "empty", None)  # pandas DataFrame/Series
    if isinstance(empty, bool):
        return empty
    if isinstance(result, (list, tuple, dict, str)):
        return len(result) == 0
    return False


def _yf_retry(func, *, retry_empty: bool = True,
              max_retries: int = _YF_MAX_RETRIES, base_delay: float = _YF_BASE_DELAY):
    """Call a yfinance function with exponential backoff. Retries on YFRateLimitError always, and
    on an empty return when `retry_empty` (yfinance often surfaces a soft rate-limit as an empty
    frame / 'no price data' rather than raising). Non-rate-limit exceptions propagate. After the
    last attempt the empty result is returned (not raised) so the caller's existing None/cache
    degrade path still runs. Pass `retry_empty=False` where empty is a legitimate state
    (after-hours intraday, no listed options, no scheduled earnings)."""
    last = None
    for attempt in range(max_retries + 1):
        try:
            last = func()
            if not (retry_empty and _is_empty(last)):
                return last
            reason = "empty result"
        except YFRateLimitError:
            if attempt >= max_retries:
                raise
            reason = "rate limited"
        if attempt >= max_retries:
            return last  # exhausted empty-retries — hand back so the caller degrades
        delay = base_delay * (2 ** attempt)
        print(f"  ~ yfinance {reason}, retry in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
        time.sleep(delay)
    return last


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


def _parse_iso(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _is_monthly(d: dt.date) -> bool:
    """Standard monthly expiry = the 3rd Friday (weekday 4, day 15-21)."""
    return d.weekday() == 4 and 15 <= d.day <= 21


# --- History -------------------------------------------------------------------------- #
def _download_history(symbol: str, period: str) -> pl.DataFrame | None:
    pdf = _yf_retry(lambda: yf.Ticker(symbol).history(period=period, auto_adjust=True))
    if pdf is None or pdf.empty:
        return None
    return _to_polars(pdf, ["Open", "High", "Low", "Close", "Volume"])


def fetch_history(
    symbols: list[str], period: str, min_rows: int, force_refresh: bool = False
) -> dict[str, pl.DataFrame]:
    """Return {symbol: OHLC Polars frame}. Symbols with no usable data are skipped.

    `period` and `min_rows` come from the `data` section of config.yaml. `force_refresh=True`
    bypasses the cache's reuse-if-written-today shortcut so callers that need the freshest bar
    (the daily review, run after the close) re-download instead of serving a stale same-day file."""
    out: dict[str, pl.DataFrame] = {}
    for sym in symbols:
        df = cache.load_or_fetch(
            sym, lambda s=sym: _download_history(s, period), min_rows=min_rows,
            force_refresh=force_refresh,
        )
        if df is None:
            print(f"  ! skipping {sym}: insufficient data")
            continue
        out[sym] = df
    return out


# --- VIX ------------------------------------------------------------------------------ #
def _download_vix(period: str) -> pl.DataFrame | None:
    pdf = _yf_retry(lambda: yf.Ticker("^VIX").history(period=period))
    if pdf is None or pdf.empty:
        return None
    return _to_polars(pdf, ["Close"])


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


# --- Macro (FRED) --------------------------------------------------------------------- #
def _read_macro_cache() -> dict[str, dict]:
    if _MACRO_CACHE.exists():
        try:
            return json.loads(_MACRO_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _download_fred(series_id: str, change_days: int) -> dict | None:
    """Latest level of one FRED series + its value ~`change_days` calendar days earlier, via the
    keyless CSV endpoint (no API key). Returns {level, prev, change, asof} or None on failure.
    FRED marks missing observations '.'; the CSV header is skipped and the value column parsed."""
    start = (clock.today() - dt.timedelta(days=change_days + 75)).isoformat()
    try:
        with urllib.request.urlopen(_FRED_URL.format(sid=series_id, start=start), timeout=20) as resp:
            text = resp.read().decode()
    except Exception:  # noqa: BLE001 — network/parse failures are expected; caller serves stale
        return None
    rows: list[tuple[dt.date, float]] = []
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2 or parts[1].strip() in ("", "."):
            continue
        d = _parse_iso(parts[0].strip())
        try:
            v = float(parts[1].strip())
        except ValueError:
            continue
        if d is not None:
            rows.append((d, v))
    if not rows:
        return None
    rows.sort()
    last_date, level = rows[-1]
    cutoff = last_date - dt.timedelta(days=change_days)
    prior = [v for d, v in rows if d <= cutoff]
    prev = prior[-1] if prior else None
    change = level - prev if prev is not None else None
    return {"level": level, "prev": prev, "change": change, "asof": last_date.isoformat()}


def fetch_macro(cfg: dict) -> dict[str, dict]:
    """Return {series_id: {level, prev, change}} for the configured FRED series, backed by a daily
    JSON cache at `data/cache/macro.json`. Source: FRED keyless CSV (no API key). On a failed fetch
    the last cached copy is served. Report-only context (quant/macro.py) — never feeds the engine."""
    mc = cfg.get("macro", {})
    if not mc.get("enabled", True):
        return {}
    series_ids = mc.get("series", _DEFAULT_MACRO_SERIES)
    change_days = mc.get("change_days", 21)
    today = clock.today().isoformat()
    cached = _read_macro_cache()
    out: dict[str, dict] = {}
    dirty = False
    for sid in series_ids:
        entry = cached.get(sid)
        if entry and entry.get("fetched") == today:
            out[sid] = {k: entry.get(k) for k in ("level", "prev", "change")}
            continue
        data = _download_fred(sid, change_days)
        if data is None:
            out[sid] = ({k: entry.get(k) for k in ("level", "prev", "change")} if entry
                        else {"level": None, "prev": None, "change": None})
            continue
        cached[sid] = {**data, "fetched": today}
        dirty = True
        out[sid] = {k: data[k] for k in ("level", "prev", "change")}
    if dirty:
        _MACRO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _MACRO_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True))
    return out


# --- Social sentiment (StockTwits + Reddit) ------------------------------------------- #
# Un-backfillable retail-sentiment feeds (see quant/sentiment.py). Both free / no-auth. StockTwits
# carries a machine-readable Bullish/Bearish label per message (a clean numeric signal); Reddit's
# public Atom/RSS search gives post VOLUME (the JSON endpoint is WAF-403 for non-OAuth clients, so
# RSS carries no scores). Report-only — the data is archived and never feeds scoring/decision.
_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
_REDDIT_RSS_URL = "https://www.reddit.com/r/{sub}/search.rss?{qs}"
# Reddit blocks generic UAs (bare Mozilla/curl); a descriptive, identified token is served on RSS.
_SOCIAL_UA = "investment-assistant/0.1 (sentiment lens)"
_DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
_SENTIMENT_CACHE_DIR = cache.CACHE_DIR / "sentiment"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_stocktwits(symbol: str, limit: int = 30, timeout: float = 10.0) -> list[dict]:
    """Recent StockTwits messages for `symbol` as structured records (not a prompt string). Each:
    {created_at, user, sentiment: 'Bullish'|'Bearish'|None, body}. No API key needed. Returns [] on
    any failure. NB: the stream is 'most recent N', NOT date-bounded, so it must be captured daily to
    build a series — it cannot be backfilled."""
    url = _STOCKTWITS_URL.format(sym=symbol.upper())
    req = urllib.request.Request(url, headers={"User-Agent": _SOCIAL_UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — network/parse failures are expected; caller degrades to []
        return []
    messages = data.get("messages", []) if isinstance(data, dict) else []
    out = []
    for m in messages[:limit]:
        entities = m.get("entities") or {}
        sobj = entities.get("sentiment") or {}
        sentiment = sobj.get("basic") if isinstance(sobj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        out.append({
            "created_at": m.get("created_at", ""),
            "user": (m.get("user") or {}).get("username", "?"),
            "sentiment": sentiment if sentiment in ("Bullish", "Bearish") else None,
            "body": body[:280],
        })
    return out


def _strip_reddit_html(content: str) -> str:
    """Reduce the HTML body Reddit embeds in an Atom entry to plain text (selftext lives between the
    SC_OFF / SC_ON markers)."""
    if not content:
        return ""
    if "<!-- SC_OFF -->" in content and "<!-- SC_ON -->" in content:
        content = content.split("<!-- SC_OFF -->")[1].split("<!-- SC_ON -->")[0]
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", content)).split())


def _fetch_reddit_sub(symbol: str, sub: str, limit: int, timeout: float, _retry: bool = True) -> list[dict]:
    """One subreddit via the Atom/RSS search feed (last-week, newest-first). Backs off once on a 429
    honouring Retry-After. Returns records {title, created_utc, selftext, sub}; [] on failure."""
    qs = urlencode({"q": symbol, "restrict_sr": "on", "sort": "new", "t": "week", "limit": limit})
    req = urllib.request.Request(_REDDIT_RSS_URL.format(sub=sub, qs=qs), headers={"User-Agent": _SOCIAL_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            root = ET.fromstring(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and _retry:
            try:
                wait = min(float(exc.headers.get("Retry-After") or 5.0), 30.0)
            except (ValueError, TypeError, AttributeError):
                wait = 5.0
            time.sleep(wait)
            return _fetch_reddit_sub(symbol, sub, limit, timeout, _retry=False)
        return []
    except Exception:  # noqa: BLE001 — network/parse failures are expected; caller degrades to []
        return []
    posts = []
    for entry in root.findall("atom:entry", _ATOM_NS)[:limit]:
        title_el = entry.find("atom:title", _ATOM_NS)
        pub_el = entry.find("atom:published", _ATOM_NS)
        content_el = entry.find("atom:content", _ATOM_NS)
        posts.append({
            "title": (title_el.text if title_el is not None else "") or "",
            "created_utc": (pub_el.text if pub_el is not None else "") or "",
            "selftext": _strip_reddit_html(content_el.text if content_el is not None else "")[:240],
            "sub": sub,
        })
    return posts


def fetch_reddit(symbol: str, subreddits=_DEFAULT_SUBREDDITS, limit_per_sub: int = 5,
                 timeout: float = 10.0, pacing: float = 1.0) -> list[dict]:
    """Recent Reddit posts mentioning `symbol` across finance subreddits as structured records
    {title, created_utc, selftext, sub}. RSS carries no score/comment counts, so post VOLUME is the
    signal. Paces requests `pacing`s apart to stay under Reddit's per-IP limit. Returns [] on failure."""
    posts = []
    for i, sub in enumerate(subreddits):
        if i > 0 and pacing:
            time.sleep(pacing)
        posts.extend(_fetch_reddit_sub(symbol, sub, limit_per_sub, timeout))
    return posts


def _read_sentiment_cache(symbol: str) -> dict:
    p = _SENTIMENT_CACHE_DIR / f"{symbol.upper()}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def fetch_sentiment_raw(symbol: str, cfg: dict) -> dict | None:
    """Structured raw social sentiment for `symbol`: {"stocktwits": [...], "reddit": [...]}. Gated on
    cfg["sentiment"]["enabled"] (returns None when disabled). Backed by a daily per-symbol cache at
    data/cache/sentiment/<SYM>.json keyed on a "fetched" == today field, so the pipeline lens and the
    raw-snapshot step share ONE fetch (Reddit's rate limit is hit once, and the derived metrics match
    the archived raw). On a failed fetch the last cached copy is served. Report-only, un-backfillable."""
    sc = cfg.get("sentiment", {})
    if not sc.get("enabled", False):
        return None
    sym = symbol.upper()
    today = clock.today().isoformat()
    cached = _read_sentiment_cache(sym)
    if cached.get("fetched") == today:
        return {"stocktwits": cached.get("stocktwits", []), "reddit": cached.get("reddit", [])}
    st_cfg = sc.get("stocktwits", {})
    rd_cfg = sc.get("reddit", {})
    stocktwits = fetch_stocktwits(sym, limit=st_cfg.get("limit", 30)) if st_cfg.get("enabled", True) else []
    reddit = (fetch_reddit(sym, subreddits=tuple(rd_cfg.get("subreddits", _DEFAULT_SUBREDDITS)),
                           limit_per_sub=rd_cfg.get("limit_per_sub", 5),
                           timeout=rd_cfg.get("timeout", 10.0), pacing=rd_cfg.get("pacing", 1.0))
              if rd_cfg.get("enabled", True) else [])
    # Both empty likely means a transient outage — serve the last cached copy rather than poisoning
    # today's archive with nothing (but don't stamp it as today's capture).
    if not stocktwits and not reddit and (cached.get("stocktwits") or cached.get("reddit")):
        return {"stocktwits": cached.get("stocktwits", []), "reddit": cached.get("reddit", [])}
    payload = {"fetched": today, "captured_at": clock.timestamp(),
               "stocktwits": stocktwits, "reddit": reddit}
    _SENTIMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_SENTIMENT_CACHE_DIR / f"{sym}.json").write_text(json.dumps(payload, indent=2))
    return {"stocktwits": stocktwits, "reddit": reddit}


# --- News (per-ticker + global) + prediction markets ---------------------------------- #
# Report-only context (see quant/news.py, quant/prediction_markets.py). Per-ticker + global news
# come free from yfinance (no sentiment score — the news-review skill judges the headlines); the
# genuinely-new signal is Polymarket's keyless crowd-implied event probabilities. All un-backfillable
# (yfinance serves only current news; odds move), so captured daily. Never feeds scoring/decision.
_POLYMARKET_URL = "https://gamma-api.polymarket.com/public-search?q={q}&limit_per_type=20"
_NEWS_CACHE_DIR = cache.CACHE_DIR / "news"
_GLOBAL_NEWS_CACHE = cache.CACHE_DIR / "global_news.json"
_PREDICTION_MARKETS_CACHE = cache.CACHE_DIR / "prediction_markets.json"
# yfinance Search queries for the macro/world-news block (mirrors TradingAgents get_global_news).
_DEFAULT_GLOBAL_NEWS_QUERIES = (
    "Federal Reserve interest rates inflation",
    "S&P 500 earnings GDP economic outlook",
    "geopolitical risk trade war sanctions",
    "ECB Bank of England BOJ central bank policy",
    "oil commodities supply chain energy",
)
_DEFAULT_PM_TOPICS = ("Fed rate cut 2026", "US recession 2026", "US inflation 2026", "AI 2026")


def _parse_yf_news_item(item: dict) -> dict | None:
    """Normalize one yfinance Ticker.get_news item (fields nested under `content`) to a flat record."""
    c = item.get("content") or item
    title = (c.get("title") or "").strip()
    if not title:
        return None
    prov = c.get("provider") or {}
    url = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
    return {
        "title": title,
        "summary": (c.get("summary") or c.get("description") or "").replace("\n", " ").strip()[:500],
        "publisher": prov.get("displayName") if isinstance(prov, dict) else None,
        "link": url.get("url") if isinstance(url, dict) else (url or None),
        "pub_date": c.get("pubDate") or "",
    }


def fetch_news(symbol: str, limit: int = 20) -> list[dict]:
    """Recent per-ticker news headlines from yfinance as structured records
    {title, summary, publisher, link, pub_date}. Free, no key. Returns [] on any failure. NB:
    yfinance serves only the CURRENT window, so this must be captured daily (not backfillable)."""
    try:
        items = _yf_retry(lambda: yf.Ticker(symbol).get_news(count=limit), retry_empty=False) or []
    except Exception:  # noqa: BLE001 — network/parse failures are expected; caller degrades to []
        return []
    out = []
    for it in items[:limit]:
        rec = _parse_yf_news_item(it)
        if rec:
            out.append(rec)
    return out


def fetch_global_news(queries=_DEFAULT_GLOBAL_NEWS_QUERIES, limit: int = 10) -> list[dict]:
    """Macro/world headlines via yfinance Search over the configured query strings, deduped by title
    (mirrors TradingAgents get_global_news). Records {title, publisher, link, pub_date, query}."""
    seen, out = set(), []
    for q in queries:
        if len(out) >= limit:
            break
        try:
            items = yf.Search(query=q, news_count=limit, enable_fuzzy_query=True).news or []
        except Exception:  # noqa: BLE001 — network/parse failures are expected; skip this query
            continue
        for it in items:
            title = (it.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            ts = it.get("providerPublishTime")
            pub = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""
            out.append({"title": title, "publisher": it.get("publisher"),
                        "link": it.get("link"), "pub_date": pub, "query": q})
            if len(out) >= limit:
                break
    return out


def _parse_json_list(s) -> list:
    """Polymarket returns `outcomes`/`outcomePrices` as JSON-encoded strings; decode to a list."""
    if isinstance(s, list):
        return s
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def fetch_prediction_markets(topics=_DEFAULT_PM_TOPICS, limit: int = 6) -> list[dict]:
    """Forward-looking Polymarket odds per topic via the keyless Gamma public-search API. Drops
    resolved / past-dated / unparseable markets, ranks by traded volume, keeps `limit` per topic.
    Records {topic, question, outcome, prob, volume, end_date, week_change}."""
    today = clock.today().isoformat()
    out = []
    for topic in topics:
        req = urllib.request.Request(_POLYMARKET_URL.format(q=quote(topic)),
                                     headers={"User-Agent": _SOCIAL_UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception:  # noqa: BLE001 — network/parse failures are expected; skip this topic
            continue
        cand = []
        for e in (data.get("events") or []):
            for m in (e.get("markets") or []):
                if m.get("closed"):
                    continue
                end = (m.get("endDate") or "")[:10]
                if end and end < today:
                    continue
                prices = _parse_json_list(m.get("outcomePrices"))
                outcomes = _parse_json_list(m.get("outcomes"))
                if not prices or not outcomes:
                    continue
                try:
                    prob = float(prices[0])
                except (ValueError, TypeError):
                    continue
                cand.append({
                    "topic": topic, "question": (m.get("question") or "").strip(),
                    "outcome": outcomes[0], "prob": prob,
                    "volume": float(m.get("volumeNum") or 0), "end_date": end,
                    "week_change": float(m.get("oneWeekPriceChange") or 0),
                })
        cand.sort(key=lambda x: x["volume"], reverse=True)
        out.extend(cand[:limit])
    return out


def _read_json_cache(path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def fetch_news_raw(symbol: str, cfg: dict) -> list[dict] | None:
    """Per-ticker news for `symbol`, gated on cfg["news"]["enabled"] (None when disabled). Daily
    per-symbol cache at data/cache/news/<SYM>.json (the fetched==today idiom), shared by the pipeline
    lens and the raw-snapshot step so the network is hit once/day. Serves stale on a failed fetch."""
    nc = cfg.get("news", {})
    if not nc.get("enabled", False):
        return None
    sym = symbol.upper()
    today = clock.today().isoformat()
    p = _NEWS_CACHE_DIR / f"{sym}.json"
    cached = _read_json_cache(p)
    if cached.get("fetched") == today:
        return cached.get("items", [])
    items = fetch_news(sym, limit=nc.get("per_ticker", {}).get("limit", 20))
    if not items and cached.get("items"):
        return cached.get("items", [])
    _NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fetched": today, "captured_at": clock.timestamp(), "items": items}, indent=2))
    return items


def fetch_global_news_cached(cfg: dict) -> list[dict]:
    """Global macro headlines, daily cache at data/cache/global_news.json. Gated on
    cfg["news"]["enabled"] and cfg["news"]["global"]["enabled"]. Serves stale on failure."""
    nc = cfg.get("news", {})
    g = nc.get("global", {})
    if not nc.get("enabled", False) or not g.get("enabled", True):
        return []
    today = clock.today().isoformat()
    cached = _read_json_cache(_GLOBAL_NEWS_CACHE)
    if cached.get("fetched") == today:
        return cached.get("items", [])
    items = fetch_global_news(tuple(g.get("queries", _DEFAULT_GLOBAL_NEWS_QUERIES)), limit=g.get("limit", 10))
    if not items and cached.get("items"):
        return cached.get("items", [])
    _GLOBAL_NEWS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _GLOBAL_NEWS_CACHE.write_text(json.dumps({"fetched": today, "captured_at": clock.timestamp(),
                                              "items": items}, indent=2))
    return items


def fetch_prediction_markets_cached(cfg: dict) -> list[dict]:
    """Polymarket odds, daily cache at data/cache/prediction_markets.json. Gated on
    cfg["prediction_markets"]["enabled"]. Serves stale on failure."""
    pc = cfg.get("prediction_markets", {})
    if not pc.get("enabled", False):
        return []
    today = clock.today().isoformat()
    cached = _read_json_cache(_PREDICTION_MARKETS_CACHE)
    if cached.get("fetched") == today:
        return cached.get("markets", [])
    markets = fetch_prediction_markets(tuple(pc.get("topics", _DEFAULT_PM_TOPICS)), limit=pc.get("limit", 6))
    if not markets and cached.get("markets"):
        return cached.get("markets", [])
    _PREDICTION_MARKETS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _PREDICTION_MARKETS_CACHE.write_text(json.dumps({"fetched": today, "captured_at": clock.timestamp(),
                                                     "markets": markets}, indent=2))
    return markets


# --- Options -------------------------------------------------------------------------- #
def fetch_option_chain(symbol: str, expiry: str) -> dict[tuple[str, float], float] | None:
    """Live implied volatility per contract for one expiry: {(right, strike): iv}.

    `expiry` is an ISO date string. Returns None when the expiry isn't listed or the
    download fails (caller degrades to no-Greeks). Deep-ITM / illiquid strikes report
    garbage IV from yfinance, so anything NaN or outside (0.01, 3.0) is dropped."""
    try:
        tk = yf.Ticker(symbol)
        if expiry not in (_yf_retry(lambda: tk.options, retry_empty=False) or []):
            return None
        chain = _yf_retry(lambda: tk.option_chain(expiry), retry_empty=False)
    except Exception:
        return None

    ivs: dict[tuple[str, float], float] = {}
    for right, frame in (("call", chain.calls), ("put", chain.puts)):
        for strike, iv in zip(frame["strike"], frame["impliedVolatility"]):
            iv = float(iv)
            if 0.01 < iv < 3.0:
                ivs[(right, float(strike))] = iv
    return ivs


def fetch_option_grid(symbol: str, expiry: str) -> dict | None:
    """Per-strike OI / volume / IV / mid-price for one expiry, both rights:
    `{"calls": {strike: {"oi","vol","iv","price"}}, "puts": {...}}`. Returns None on
    failure. NaNs coerced (oi/vol -> 0); IV outside (0.01, 3.0) -> None (yfinance reports
    garbage IV on illiquid/deep-ITM strikes — same guard as fetch_option_chain)."""
    try:
        tk = yf.Ticker(symbol)
        if expiry not in (_yf_retry(lambda: tk.options, retry_empty=False) or []):
            return None
        chain = _yf_retry(lambda: tk.option_chain(expiry), retry_empty=False)
    except Exception:  # noqa: BLE001
        return None

    def _f(x, default=0.0):
        try:
            v = float(x)
            return default if v != v else v  # NaN -> default
        except (TypeError, ValueError):
            return default

    out: dict[str, dict] = {"calls": {}, "puts": {}}
    for right, frame in (("calls", chain.calls), ("puts", chain.puts)):
        cols = list(frame.columns)
        for row in frame.itertuples(index=False):
            r = dict(zip(cols, row))
            strike = _f(r.get("strike"), default=None)
            if strike is None:
                continue
            iv = _f(r.get("impliedVolatility"), default=0.0)
            bid, ask = _f(r.get("bid")), _f(r.get("ask"))
            mid = (bid + ask) / 2 if bid and ask else _f(r.get("lastPrice"))
            out[right][float(strike)] = {
                "oi": _f(r.get("openInterest")),
                "vol": _f(r.get("volume")),
                "iv": iv if 0.01 < iv < 3.0 else None,
                "price": mid,
            }
    return out if (out["calls"] or out["puts"]) else None


def pick_monthly_expiry(symbol: str, dte_lo: int, dte_hi: int) -> str | None:
    """Pick the most liquid expiry for positioning: the 3rd-Friday monthly whose days-to-
    expiry is closest to the [dte_lo, dte_hi] midpoint. Falls back to the nearest listed
    expiry to that midpoint if no monthly qualifies. Returns an ISO date string or None.

    NOTE: yfinance is the free options source. Alpha Vantage options (the user's preferred
    primary) are premium-only, so this stays on yfinance until a premium key is available."""
    try:
        listed = _yf_retry(lambda: yf.Ticker(symbol).options, retry_empty=False) or []
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    today = clock.today()
    target = (dte_lo + dte_hi) / 2
    dated = [(d, (d - today).days) for e in listed if (d := _parse_iso(e)) and (d - today).days > 0]
    if not dated:
        return None
    monthlies = [(d, dte) for d, dte in dated if _is_monthly(d) and dte_lo <= dte <= dte_hi]
    pool = monthlies or dated
    best = min(pool, key=lambda x: abs(x[1] - target))
    return best[0].isoformat()


# --- Sectors -------------------------------------------------------------------------- #
def _download_sector(symbol: str) -> str | None:
    """The symbol's GICS-style sector from yfinance, or None if unavailable."""
    try:
        return (_yf_retry(lambda: yf.Ticker(symbol).info) or {}).get("sector") or None
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None


def _read_sector_cache() -> dict[str, str]:
    if _SECTOR_CACHE.exists():
        try:
            return json.loads(_SECTOR_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


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


def load_cached_sectors(symbols: list[str]) -> dict[str, str]:
    """Read sectors from the on-disk cache only — no network. Used by the backtester
    so replays are reproducible and offline. Unknown/uncached symbols => "Unknown"."""
    cached = _read_sector_cache()
    return {s: cached.get(s, "Unknown") for s in symbols}


# --- Fundamentals: pluggable sources normalised to a vendor-neutral canonical dict ----- #
# Canonical keys every source maps to (what valuation.py reads).
_FUND_KEYS = (
    "sector", "pe", "forward_pe", "peg", "pb", "ev_ebitda", "profit_margin",
    "rev_growth", "eps_growth", "analyst_target", "beta",
)
_YF_MAP = {  # canonical -> yfinance .info key (peg handled separately, has a fallback)
    "sector": "sector", "pe": "trailingPE", "forward_pe": "forwardPE",
    "pb": "priceToBook", "ev_ebitda": "enterpriseToEbitda", "profit_margin": "profitMargins",
    "rev_growth": "revenueGrowth", "eps_growth": "earningsQuarterlyGrowth",
    "analyst_target": "targetMeanPrice", "beta": "beta",
}
_AV_MAP = {  # canonical -> Alpha Vantage OVERVIEW key
    "sector": "Sector", "pe": "PERatio", "forward_pe": "ForwardPE", "peg": "PEGRatio",
    "pb": "PriceToBookRatio", "ev_ebitda": "EVToEBITDA", "profit_margin": "ProfitMargin",
    "rev_growth": "QuarterlyRevenueGrowthYOY", "eps_growth": "QuarterlyEarningsGrowthYOY",
    "analyst_target": "AnalystTargetPrice", "beta": "Beta",
}


def _map_yf(info: dict) -> dict:
    """yfinance `.info` -> canonical fundamentals dict (native floats/None preserved)."""
    out = {ck: info.get(yk) for ck, yk in _YF_MAP.items()}
    out["peg"] = info.get("trailingPegRatio", info.get("pegRatio"))
    return out


def _map_av(data: dict) -> dict:
    """Alpha Vantage OVERVIEW -> canonical fundamentals dict (values stay AV strings)."""
    return {ck: data.get(ak) for ck, ak in _AV_MAP.items()}


def _download_fundamentals_yf(symbol: str) -> dict | None:
    """Canonical fundamentals from yfinance `.info`. None on failure / empty."""
    try:
        info = _yf_retry(lambda: yf.Ticker(symbol).info)
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    if not info:
        return None
    mapped = _map_yf(info)
    return mapped if any(v is not None for v in mapped.values()) else None


def _download_fundamentals_av(symbol: str, key: str) -> dict | None:
    """Canonical fundamentals from one Alpha Vantage OVERVIEW call. None on failure /
    throttle / premium notice (response then lacks a real "Symbol")."""
    try:
        with urllib.request.urlopen(_AV_URL.format(sym=symbol, key=key), timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    if not isinstance(data, dict) or not data.get("Symbol"):
        return None
    return _map_av(data)


# Source registry — add a broker / Finviz / etc. source here with its own mapper.
# Keys match the config `fundamentals.source` value — do not rename.
_FUND_SOURCES = {
    "yfinance": {"fetch": _download_fundamentals_yf, "needs_key": False},
    "alphavantage": {"fetch": _download_fundamentals_av, "needs_key": True},
}


def _read_fundamentals_cache() -> dict[str, dict]:
    if _FUNDAMENTALS_CACHE.exists():
        try:
            return json.loads(_FUNDAMENTALS_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def fetch_fundamentals(symbols: list[str], cfg: dict) -> dict[str, dict | None]:
    """Return {symbol: canonical fundamentals dict (+ "_fetched"/"_stale"/"_source") or None},
    backed by a persistent JSON cache at `data/cache/fundamentals.json`.

    Source is `fundamentals.source` (default "yfinance"); see `_FUND_SOURCES`. Fundamentals
    move quarterly, so a symbol is refetched only when its cached copy is older than
    `fundamentals.refresh_days` OR was fetched from a different source. A keyed source (Alpha
    Vantage) requires ALPHAVANTAGE_API_KEY; on a failed fetch the last cached copy is served
    stale rather than dropped. Disabled (all-None) when `fundamentals.enabled` is false."""
    fund = cfg.get("fundamentals", {})
    out: dict[str, dict | None] = {s: None for s in symbols}
    if not fund.get("enabled", False):
        return out
    source = fund.get("source", "yfinance")
    spec = _FUND_SOURCES.get(source)
    if spec is None:
        print(f"  ! unknown fundamentals.source {source!r} — skipping")
        return out
    key = None
    if spec["needs_key"]:
        key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key:
            print(f"  ! fundamentals source '{source}' needs ALPHAVANTAGE_API_KEY (unset) — skipping")
            return out

    refresh_days = fund.get("refresh_days", 7)
    today = clock.today()
    cached = _read_fundamentals_cache()
    dirty = False

    def _serve(entry, stale):
        return {**entry["raw"], "_fetched": entry["fetched"], "_stale": stale, "_source": source}

    def _fresh(entry):
        try:
            return (today - dt.date.fromisoformat(entry["fetched"])).days < refresh_days
        except (KeyError, ValueError):
            return False

    for sym in symbols:
        entry = cached.get(sym)
        if entry and entry.get("source") != source:
            entry = None  # different source -> refetch so a source switch self-heals
        if entry and _fresh(entry):
            out[sym] = _serve(entry, stale=False)
            continue
        raw = spec["fetch"](sym, key) if spec["needs_key"] else spec["fetch"](sym)
        if raw is None:
            if entry:
                out[sym] = _serve(entry, stale=True)
            continue
        fetched = today.isoformat()
        cached[sym] = {"raw": raw, "fetched": fetched, "source": source}
        dirty = True
        out[sym] = {**raw, "_fetched": fetched, "_stale": False, "_source": source}

    if dirty:
        _FUNDAMENTALS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FUNDAMENTALS_CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True))
    return out


def load_cached_fundamentals(symbols: list[str]) -> dict[str, dict | None]:
    """Read fundamentals from the on-disk cache only — no network (parity with
    load_cached_sectors). Unknown/uncached symbols => None."""
    cached = _read_fundamentals_cache()
    return {
        s: ({**cached[s]["raw"], "_fetched": cached[s]["fetched"], "_stale": True,
             "_source": cached[s].get("source", "")} if s in cached else None)
        for s in symbols
    }


# --- Live snapshots (no cache) -------------------------------------------------------- #
def fetch_quote(symbol: str) -> dict | None:
    """Live intraday snapshot — the piece the daily-bar engine can't see (it's a session
    behind). Returns `{last, open, prev_close, day_high, day_low, change, change_pct,
    today_session, source}` or None on failure. NO cache — pre-trade needs the freshest tick.

    `today_session=True` means today's regular-session 1-minute bars were available (last is the
    live/most-recent print); otherwise it falls back to the last daily close (market closed / no
    intraday). `prev_close` is the last daily close strictly before today's session, so `change_pct`
    is the true day move."""
    try:
        tk = yf.Ticker(symbol)
        daily = _yf_retry(lambda: tk.history(period="5d"))
        intra = _yf_retry(lambda: tk.history(period="1d", interval="1m"), retry_empty=False)
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    if daily is None or daily.empty:
        return None

    d_dates = [ts.date() for ts in daily.index]
    d_close = [float(x) for x in daily["Close"]]

    today_session = intra is not None and not intra.empty
    if today_session:
        i_date = intra.index[-1].date()
        last = float(intra["Close"].iloc[-1])
        open_ = float(intra["Open"].iloc[0])
        day_high = float(intra["High"].max())
        day_low = float(intra["Low"].min())
        prior = [c for dte, c in zip(d_dates, d_close) if dte < i_date]
        prev_close = prior[-1] if prior else (d_close[-2] if len(d_close) >= 2 else None)
        source = "intraday"
    else:
        last = d_close[-1]
        open_ = float(daily["Open"].iloc[-1])
        day_high = float(daily["High"].iloc[-1])
        day_low = float(daily["Low"].iloc[-1])
        prev_close = d_close[-2] if len(d_close) >= 2 else None
        source = "daily_close"

    change = (last - prev_close) if prev_close is not None else None
    change_pct = (change / prev_close) if (change is not None and prev_close) else None
    return {
        "last": last, "open": open_, "prev_close": prev_close,
        "day_high": day_high, "day_low": day_low,
        "change": change, "change_pct": change_pct,
        "today_session": today_session, "source": source,
    }


def fetch_earnings_date(symbol: str) -> dict | None:
    """Next scheduled earnings date for the symbol: `{next_date, days_until, is_estimate}` or
    None when unknown / none upcoming. NO cache — the calendar moves. `is_estimate` is True when
    yfinance reports a date *range* (unconfirmed). Source: yfinance `Ticker.calendar`."""
    try:
        cal = _yf_retry(lambda: yf.Ticker(symbol).calendar, retry_empty=False)
    except Exception:  # noqa: BLE001 — network/parse failures are expected
        return None
    dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not dates:
        return None
    today = clock.today()
    upcoming = sorted(d for d in dates if isinstance(d, dt.date) and d >= today)
    if not upcoming:
        return None
    nxt = upcoming[0]
    return {
        "next_date": nxt.isoformat(),
        "days_until": (nxt - today).days,
        "is_estimate": len(dates) > 1,
    }
