"""Refactored, clean, and bitemporal Daily Review Pipeline in core.

Splits production (DATA_PIPELINE) from presentation (REVIEW_SYSTEM):
- Phase 1: Ingestion & Assessment (Gatherer -> Assessor -> Strategy -> Memory)
- Phase 2: Read-Only Report Renderer (Memory -> MD/JSON report)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# Resolve project ROOT path to locate configuration files correctly
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import clock, config, gather, assess, strategy, report, profiles
from core.memory import Memory


def execute_daily_pipeline(
    config_path: str,
    portfolio_path: str,
    watchlist_path: str,
    options_path: str,
    store_dir: str,
    now: datetime,
) -> tuple[Memory, list[str], float, dict, list[str], list[str], dict]:
    """[DATA_PIPELINE] Execute the ingestion, assessment, and policy calculations, and save to Memory."""
    print("--- Phase 1: Ingestion & Interpretation (DATA_PIPELINE) ---")
    
    # Initialize our clean, bitemporal Memory store
    memory = Memory(store_dir)
    
    # Load configuration inputs
    cfg = config.load_yaml(config_path)
    watch_symbols = config.load_watchlist(watchlist_path)
    cash, holdings, pre_positions = config.load_portfolio(portfolio_path)
    
    # Assemble the unified investment universe
    all_symbols = sorted(set(watch_symbols) | set(holdings.keys()) | set(pre_positions))
    print(f"Watchlist: {len(watch_symbols)} | Holdings: {len(holdings)} | Pre-Positions: {len(pre_positions)}")
    print(f"Total Unique Universe: {len(all_symbols)} symbols")
    
    # A. Ingest live 3-year OHLCV Facts into Memory
    print(f"Fetching and ingesting trailing daily Fact history ...")
    for sym in all_symbols:
        try:
            res = gather.gather(memory, sym, gather.yf_fetch, now)
            if res.written > 0:
                print(f"  [{sym}] Ingested {res.new} new, {res.revised} revised daily Fact(s).")
        except Exception as e:
            print(f"  ⚠ [{sym}] Fact ingestion failed ({e}) — skipping")

    print(f"Fetching/caching and ingesting fundamental Facts ...")
    fundamentals_cache_path = os.path.join(ROOT, "data", "cache", "fundamentals.json")
    try:
        fundamental_results = gather.gather_fundamentals(
            memory,
            all_symbols,
            cfg,
            now,
            lambda symbols, cfg_: gather.fetch_fundamentals(symbols, cfg_, fundamentals_cache_path),
        )
    except Exception as e:
        print(f"  ⚠ Fundamental Fact fetch/import failed ({e}) — skipping")
        fundamental_results = {}
    for sym, res in fundamental_results.items():
        try:
            if res.written > 0:
                print(f"  [{sym}] Imported {res.new} new, {res.revised} revised fundamental Fact(s).")
        except Exception as e:
            print(f"  ⚠ [{sym}] Fundamental Fact import failed ({e}) — skipping")
            
    # B. Run all bitemporal pluggable Assessors in sequence
    assessors: list[assess.Assessor] = [
        assess.FundamentalAssessor(),
        assess.TechnicalAssessor(),
        assess.BottomFishingAssessor(),
        assess.LeftSideEntryAssessor(),
    ]
    
    for assessor in assessors:
        print(f"Evaluating {assessor.perspective} Assessments ...")
        for sym in all_symbols:
            try:
                asm = assessor.run(memory, sym, now, cfg)
                if asm:
                    memory.append(asm)
            except Exception as e:
                print(f"  ⚠ [{sym}] {assessor.perspective} assessment failed ({e})")
            
    # C. Run Strategy Deciders (Holding exit/profit, Pre-Position breakout, Watchlist)
    print(f"Generating policy sizing Decisions ...")
    for sym in all_symbols:
        try:
            membership = "holding" if sym in holdings else "pre_position" if sym in pre_positions else "watchlist"
            h_info = holdings.get(sym)
            d = strategy.evaluate_daily_strategy(memory, sym, membership, h_info, cfg, now)
            if d:
                memory.append(d)
        except Exception as e:
            print(f"  ⚠ [{sym}] Strategy decision failed ({e})")
            
    print("Bitemporal Memory commit complete.")
    return memory, all_symbols, cash, holdings, pre_positions, watch_symbols, cfg


def generate_daily_review_reports(
    memory: Memory,
    all_symbols: list[str],
    cash: float,
    holdings: dict,
    pre_positions: list[str],
    watch_symbols: list[str],
    cfg: dict,
    out_dir: str,
    now: datetime,
) -> None:
    """[REVIEW_SYSTEM] Read the Memory bitemporally as of now, arrange records, and write reports."""
    print("--- Phase 2: Generating Daily Review Views (REVIEW_SYSTEM) ---")
    md_path, json_path = report.generate_review_views(
        memory, all_symbols, cash, holdings, pre_positions, watch_symbols, cfg, out_dir, now
    )
    print(f"Daily Review Markdown written to: {md_path}")
    print(f"Daily Review JSON payload written to: {json_path}")


def main() -> None:
    # Resolve profile-specific directories using profiles module
    config_path, portfolio_path, watchlist_path, options_path, out_dir = profiles.resolve(ROOT)
    profile = os.environ.get("PROFILE", "demo")
    
    # Store core bitemporal Parquet memory under data/memory/<profile>
    store_dir = os.path.join(ROOT, "data", "memory", profile)
    
    # Single unified vantage instant t for the entire run
    now = clock.now()
    
    print(f"==================================================")
    print(f"Starting Core Daily Review Workflow (Profile: {profile})")
    print(f"Vantage Time (t): {clock.timestamp(now)}")
    print(f"==================================================")
    
    # 1. Execute Production (Data Pipeline Ingestion & Interpretation)
    memory, all_symbols, cash, holdings, pre_positions, watch_symbols, cfg = execute_daily_pipeline(
        config_path, portfolio_path, watchlist_path, options_path, store_dir, now
    )
    
    # 2. Execute Presentation (Read-Only Review System View rendering)
    generate_daily_review_reports(
        memory, all_symbols, cash, holdings, pre_positions, watch_symbols, cfg, out_dir, now
    )
    print(f"==================================================")
    print("Daily Review Workflow complete.")


if __name__ == "__main__":
    main()
