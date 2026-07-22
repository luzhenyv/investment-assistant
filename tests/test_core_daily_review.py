"""Unit tests for the clean bitemporal core Daily Review pipeline.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from core import assess, clock, config, gather, report, strategy
from core.memory import Memory
from core.record import Assessment, Decision, Fact


@pytest.fixture
def temp_dir():
    path = tempfile.mkdtemp()
    yield Path(path)
    shutil.rmtree(path)


def test_config_loader(temp_dir):
    portfolio_content = """
cash: 50000.0
positions:
  MSFT: {core: 10, trading: 5, avg_cost: 300.0, plan: "hold core"}
pre_positions:
  - TSM
  - AMD
"""
    p_path = temp_dir / "portfolio.yaml"
    with open(p_path, "w") as f:
        f.write(portfolio_content)
        
    cash, holdings, pre_positions = config.load_portfolio(str(p_path))
    
    assert cash == 50000.0
    assert "MSFT" in holdings
    assert holdings["MSFT"].shares == 15
    assert holdings["MSFT"].core == 10
    assert holdings["MSFT"].trading == 5
    assert holdings["MSFT"].avg_cost == 300.0
    assert holdings["MSFT"].plan == "hold core"
    
    assert pre_positions == ["AMD", "TSM"]


def test_gather_and_assess_and_strategy(temp_dir):
    memory = Memory(temp_dir)
    symbol = "TEST"
    at = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
    
    # Mock Fetch function returning historical daily bars (reversal & close to support)
    def mock_fetch(sub: str) -> pl.DataFrame:
        dates = [date(2026, 7, i) for i in range(1, 21)]
        # Price descends from 100 to 90, then bounces up on day 20 to 92
        closes = [100.0 - i * 0.5 for i in range(19)] + [92.0]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        volumes = [1000000.0] * 20
        return pl.DataFrame({
            "date": dates,
            "open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes
        })
        
    # Ingest Facts bitemporally
    res = gather.gather(memory, symbol, mock_fetch, at)
    assert res.new == 100  # 5 metrics x 20 dates
    
    # Run technical assessor
    assessments = assess.run_technical_assessments(memory, symbol, at)
    assert len(assessments) == 3  # technical, left_side, bottom_fishing
    memory.append(assessments)
    
    tech_asm = next(a for a in assessments if a.perspective == "technical")
    assert tech_asm.result == "neutral"
    metrics = json.loads(tech_asm.payload)
    assert metrics["price"] == 92.0
    assert metrics["rsi"] < 50.0  # fell from 100 to 90
    assert metrics["support"] is not None
    assert metrics["resistance"] is not None
    
    # Test strategy policies:
    # 1. Holding
    cfg = {
        "target_weights": {symbol: 0.10},
        "role_rules": {"swing": {"take_profit": 0.30, "stop_loss": 0.10}}
    }
    h_info_ok = config.Holding(symbol, 10.0, 0.0, 91.0) # bought at 91, currently 92 (+1.1%)
    d_hold = strategy.evaluate_daily_strategy(memory, symbol, "holding", h_info_ok, cfg, at)
    assert d_hold.action == "hold"
    
    h_info_sl = config.Holding(symbol, 10.0, 0.0, 110.0) # bought at 110, currently 92 (-16.4%)
    d_sl = strategy.evaluate_daily_strategy(memory, symbol, "holding", h_info_sl, cfg, at)
    assert d_sl.action == "sell"
    assert json.loads(d_sl.payload)["intent"] == "Close"
    
    # 2. Pre-Position (Breakout vs Support Reversal)
    d_pre = strategy.evaluate_daily_strategy(memory, symbol, "pre_position", None, cfg, at)
    # The price has bounced up from support (closes went from 90.5 to 92.0, support was around 90)
    # So a support reversal buy suggestion should be proposed!
    assert d_pre.action == "buy"
    assert json.loads(d_pre.payload)["intent"] == "Buy (Support Reversal)"


def test_report_prices_holdings_from_latest_available_bar(temp_dir):
    memory = Memory(temp_dir)
    at = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
    bar_date = date(2026, 7, 21)
    symbol = "TEST"

    memory.append(Fact(
        kind="fact",
        subject=symbol,
        event_at=bar_date,
        known_at=at,
        provenance="test@v1",
        metric="close",
        value=120.0,
    ))
    memory.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=bar_date,
        known_at=at,
        provenance="technical_assessor@v1",
        perspective="technical",
        result="neutral",
        confidence=1.0,
        payload=json.dumps({
            "price": 120.0,
            "rsi": 55.0,
            "trend_score": 75.0,
            "vol_state": "Normal",
            "vol_z": 0.0,
            "atr_move": 0.0,
        }),
    ))
    memory.append(Decision(
        kind="decision",
        subject=symbol,
        event_at=bar_date,
        known_at=at,
        provenance="sizing_strategy@v1",
        actor="engine",
        status="proposed",
        action="hold",
        payload=json.dumps({
            "membership": "holding",
            "intent": "Hold",
            "reason": "test",
            "dollar_gap": 0.0,
            "role": "core",
        }),
    ))

    holdings = {symbol: config.Holding(symbol, 10.0, 0.0, 100.0)}
    _, json_path = report.generate_review_views(
        memory, [symbol], 1000.0, holdings, [], [symbol], {}, str(temp_dir), at
    )

    payload = json.loads(Path(json_path).read_text())
    assert payload["as_of_bar"] == "2026-07-21"
    assert payload["portfolio"]["total_value"] == 2200.0
    assert payload["holdings"][0]["pnl_pct"] == 0.2
