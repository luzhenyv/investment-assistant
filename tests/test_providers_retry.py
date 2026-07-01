import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from quant import providers


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually back off during tests."""
    monkeypatch.setattr(providers.time, "sleep", lambda *_: None)


def _seq(results):
    """A fake yfinance call returning/raising the next item on each invocation.
    Items that are exception instances are raised; a counter tracks call count."""
    calls = {"n": 0}

    def func():
        calls["n"] += 1
        item = results[calls["n"] - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return func, calls


def test_returns_immediately_on_nonempty():
    func, calls = _seq(["ok"])
    assert providers._yf_retry(func) == "ok"
    assert calls["n"] == 1


def test_retries_rate_limit_then_succeeds():
    func, calls = _seq([YFRateLimitError(), YFRateLimitError(), "ok"])
    assert providers._yf_retry(func) == "ok"
    assert calls["n"] == 3


def test_reraises_rate_limit_after_max_retries():
    func, calls = _seq([YFRateLimitError()] * 10)
    with pytest.raises(YFRateLimitError):
        providers._yf_retry(func, max_retries=3)
    assert calls["n"] == 4  # initial + 3 retries


def test_retries_empty_then_succeeds():
    func, calls = _seq([[], [], ["data"]])
    assert providers._yf_retry(func) == ["data"]
    assert calls["n"] == 3


def test_returns_empty_after_exhausting_empty_retries():
    func, calls = _seq([[]] * 10)
    assert providers._yf_retry(func, max_retries=2) == []
    assert calls["n"] == 3  # initial + 2 retries, then hand back empty (no raise)


def test_no_retry_on_empty_when_disabled():
    func, calls = _seq([[], "should-not-reach"])
    assert providers._yf_retry(func, retry_empty=False) == []
    assert calls["n"] == 1


def test_is_empty():
    assert providers._is_empty(None)
    assert providers._is_empty(pd.DataFrame())
    assert providers._is_empty(())
    assert providers._is_empty({})
    assert providers._is_empty("")
    assert not providers._is_empty(pd.DataFrame({"a": [1]}))
    assert not providers._is_empty({"k": "v"})
    assert not providers._is_empty(("2025-01-17",))
