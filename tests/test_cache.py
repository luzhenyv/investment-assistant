import datetime as dt

import polars as pl
import pytest

from quant import cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


def _frame(n, start="2024-01-01"):
    dates = pl.date_range(
        dt.date.fromisoformat(start),
        dt.date.fromisoformat(start) + dt.timedelta(days=n - 1),
        "1d",
        eager=True,
    )
    return pl.DataFrame({"date": dates, "Close": list(range(n))})


def test_write_names_file_with_symbol_and_range(cache_dir):
    path = cache.write_cache("SPY", _frame(5))
    assert path.name == "SPY_2024-01-01_2024-01-05.parquet"
    assert path.exists()


def test_reuses_todays_valid_cache_without_fetching(cache_dir):
    cache.write_cache("AAA", _frame(10))

    def fetch():
        raise AssertionError("should not download when today's cache is valid")

    out = cache.load_or_fetch("AAA", fetch, min_rows=5)
    assert out.height == 10


def test_downloads_and_caches_when_empty(cache_dir):
    out = cache.load_or_fetch("BBB", lambda: _frame(8), min_rows=5)
    assert out.height == 8
    assert list(cache_dir.glob("BBB_*.parquet"))  # persisted


def test_falls_back_to_old_cache_on_download_failure(cache_dir):
    # Seed a cache file and back-date its mtime so it is not "today".
    path = cache.write_cache("CCC", _frame(7))
    old = dt.datetime(2020, 1, 1).timestamp()
    import os

    os.utime(path, (old, old))

    def failing_fetch():
        raise RuntimeError("network down")

    out = cache.load_or_fetch("CCC", failing_fetch, min_rows=5)
    assert out.height == 7  # served from stale cache


def test_returns_none_when_nothing_usable(cache_dir):
    assert cache.load_or_fetch("DDD", lambda: None, min_rows=5) is None
