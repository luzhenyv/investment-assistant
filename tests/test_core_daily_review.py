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

    # Append a mock fundamental assessment first so the technical assessor can read it
    memory.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=date(2026, 7, 20),
        known_at=at,
        provenance="fundamental_assessor@v1",
        perspective="fundamental",
        result="fair",
        confidence=1.0,
        payload=json.dumps({
            "pe": 25.0,
            "forward_pe": 20.0,
            "peg": 1.5,
            "valuation_label": "fair",
        })
    ))
    
    # Run technical assessor
    tech_asm = assess.run_technical_assessments(memory, symbol, at)
    assert tech_asm is not None
    assert tech_asm.perspective == "technical"
    memory.append(tech_asm)
    
    # Run bottom-fishing assessor
    bottom_asm = assess.run_bottom_fishing_assessment(memory, symbol, at)
    assert bottom_asm is not None
    assert bottom_asm.perspective == "bottom_fishing"
    memory.append(bottom_asm)
    
    # Run cross-lens left-side entry assessor
    left_asm = assess.run_left_side_assessment(memory, symbol, at)
    assert left_asm is not None
    assert left_asm.perspective == "left_side_entry"
    assert left_asm.result == "candidate"
    memory.append(left_asm)
    
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
        provenance="fundamental_assessor@v1",
        perspective="fundamental",
        result="fair",
        confidence=1.0,
        payload=json.dumps({
            "pe": 25.0,
            "forward_pe": 20.0,
            "peg": 1.5,
            "valuation_label": "fair",
        })
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
    memory.append(Assessment(
        kind="assessment",
        subject=symbol,
        event_at=bar_date,
        known_at=at,
        provenance="left_side_entry_assessor@v1",
        perspective="left_side_entry",
        result="none",
        confidence=0.0,
        payload="",
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


def test_object_oriented_assessors(temp_dir):
    """Test the OO class-based Assessor framework specifically."""
    memory = Memory(temp_dir)
    symbol = "OO_TEST"
    at = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Test TechnicalAssessor instantiates and executes
    assessor = assess.TechnicalAssessor(version="v2")
    assert assessor.perspective == "technical"
    assert assessor.provenance == "technical_assessor@v2"

    # Ingest facts
    close_facts = [
        Fact(
            kind="fact",
            subject=symbol,
            event_at=date(2026, 7, i),
            known_at=at,
            provenance="test_feed",
            metric="close",
            value=100.0 - i * 0.1,
        )
        for i in range(1, 25)
    ]
    high_facts = [
        Fact(
            kind="fact",
            subject=symbol,
            event_at=date(2026, 7, i),
            known_at=at,
            provenance="test_feed",
            metric="high",
            value=101.0 - i * 0.1,
        )
        for i in range(1, 25)
    ]
    low_facts = [
        Fact(
            kind="fact",
            subject=symbol,
            event_at=date(2026, 7, i),
            known_at=at,
            provenance="test_feed",
            metric="low",
            value=99.0 - i * 0.1,
        )
        for i in range(1, 25)
    ]
    vol_facts = [
        Fact(
            kind="fact",
            subject=symbol,
            event_at=date(2026, 7, i),
            known_at=at,
            provenance="test_feed",
            metric="volume",
            value=1000.0,
        )
        for i in range(1, 25)
    ]
    memory.append(close_facts + high_facts + low_facts + vol_facts)

    tech_asm = assessor.run(memory, symbol, at)
    assert tech_asm is not None
    assert tech_asm.perspective == "technical"
    assert tech_asm.provenance == "technical_assessor@v2"

    # 2. Test BottomFishingAssessor subclass
    bf_assessor = assess.BottomFishingAssessor(version="v2")
    assert bf_assessor.perspective == "bottom_fishing"

    # Append tech_asm to memory so BottomFishing can read it
    memory.append(tech_asm)
    bf_asm = bf_assessor.run(memory, symbol, at)
    assert bf_asm is not None
    assert bf_asm.perspective == "bottom_fishing"
    assert bf_asm.provenance == "bottom_fishing_assessor@v2"
