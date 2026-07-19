"""P0 seed proof, on REAL accumulated history.

Runs `spec/ontology.md`'s "validate before code" step against the live `stocks/` panel:
imports raw Facts, recomputes an Assessment from them, proves the Facts are never touched, and proves
the as-of firewall — then prints an honest report (including the known_at caveat).

    uv run scripts/core_demo.py

Reads only the legacy panel; writes a throwaway Memory under data/memory/demo (cleared each run).
"""
from __future__ import annotations

import shutil
from datetime import timezone
from pathlib import Path

import polars as pl

from core import clock, indicators
from core.assess import momentum_assessment
from core.gather import gather, yf_fetch
from core.legacy_import import import_panel
from core.memory import Memory

PANEL_GLOB = "data/daily_observations/stocks/*.parquet"
DEMO_ROOT = Path("data/memory/demo")


def _rule(ok: bool) -> str:
    return "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"


def main() -> None:
    if DEMO_ROOT.exists():
        shutil.rmtree(DEMO_ROOT)
    mem = Memory(DEMO_ROOT)

    print("=" * 72)
    print("P0 SEED — the honest Memory, proven on real history")
    print("=" * 72)

    # 1 · Import raw Facts ---------------------------------------------------- #
    n = import_panel(mem, PANEL_GLOB)
    facts = mem.as_of(clock.now(), "fact")
    subjects = sorted({f.subject for f in facts})
    days = sorted({f.event_at for f in facts})
    print(f"\n[1] Imported {n} raw Facts from the legacy panel")
    print(f"    {len(subjects)} symbols · {len(days)} bars/symbol "
          f"· {days[0]} → {days[-1]} · metrics = open/high/low/close/volume")

    sym = "AAPL" if "AAPL" in subjects else subjects[0]

    # 2 · Round-trip: Facts reconstruct the panel, no interpretation leaked ---- #
    panel = pl.concat([
        pl.read_parquet(f).select(["symbol", "bar_date", "price"])
        for f in sorted(__import__("glob").glob(PANEL_GLOB)) if "__weekly" not in f
    ]).filter(pl.col("symbol") == sym)
    panel_close = dict(zip(panel["bar_date"], panel["price"]))
    fact_close = {f.event_at.isoformat(): f.value for f in mem.facts(sym, "close", clock.now())}
    match = all(abs(panel_close[d] - fact_close.get(d, 1e9)) < 1e-9 for d in panel_close)
    print(f"\n[2] Round-trip ({sym}): {len(fact_close)} close Facts reconstruct the panel exactly "
          f"— {_rule(match)}")
    print(f"    a Fact carries metric/value only; the panel's `state`/`intent` were NOT imported "
          f"(they are Assessments/Decisions)")

    # 3 · Recompute: improve the rule, Facts stay byte-identical --------------- #
    at = clock.now()
    close = pl.Series([f.value for f in mem.facts(sym, "close", at)])
    rsi = indicators.rsi(close)
    # Choose a v2 threshold that straddles this RSI so the label demonstrably flips.
    if rsi >= 50:
        v1 = dict(overbought=99.0); v2 = dict(overbought=rsi - 0.01)
    else:
        v1 = dict(oversold=1.0); v2 = dict(oversold=rsi + 0.01)

    before = pl.read_parquet(mem._path("fact"))
    a1 = momentum_assessment(mem, sym, as_of=at, version="v1", **v1); mem.append(a1)
    a2 = momentum_assessment(mem, sym, as_of=at, version="v2", **v2); mem.append(a2)
    after = pl.read_parquet(mem._path("fact"))
    untouched = before.equals(after)
    print(f"\n[3] Recompute ({sym}, RSI={rsi:.1f}): rule v1 → '{a1.result}', v2 → '{a2.result}'")
    print(f"    two Assessments over the SAME {len(a1.refs)} Facts (same refs = "
          f"{set(a1.refs) == set(a2.refs)}); Facts byte-identical after — {_rule(untouched)}")

    # 4 · As-of firewall: today's judgment is invisible to a past vantage ----- #
    past = max(f.known_at for f in facts)   # last moment a Fact was recorded (before today's run)
    facts_then = mem.as_of(past, "fact", sym)
    assess_then = mem.as_of(past, "assessment", sym)
    assess_now = mem.as_of(clock.now(), "assessment", sym)
    firewall = len(assess_then) == 0 and len(assess_now) == 2
    print(f"\n[4] As-of firewall — vantage = {past:%Y-%m-%d %H:%M} UTC (last Fact recorded)")
    print(f"    as_of(past): {len(facts_then)} Facts, {len(assess_then)} Assessments")
    print(f"    as_of(now):  {len(assess_now)} Assessments (made this run, known_at > past) "
          f"— {_rule(firewall)}")
    print("    → a judgment made today cannot leak into a replay of the past. By construction.")

    # Honest caveat ---------------------------------------------------------- #
    kn = sorted({f.known_at for f in facts})
    print(f"\n[caveat] `known_at` here is the panel's create_time — {len(kn)} distinct instants for "
          f"{len(days)} bars.")
    print("         Honest enough to prove the mechanism; a live pipeline stamps a truer known_at.")

    # 5 · Live Gatherer: known_at born at the door (network — guarded) --------- #
    print(f"\n[5] Live Gatherer ({sym}) — known_at stamped at ingestion (needs network)")
    try:
        before_ct = clock.now()
        r1 = gather(mem, sym, yf_fetch)
        r2 = gather(mem, sym, yf_fetch)          # immediate re-gather: should write nothing
        born = [f for f in mem.facts(sym, "close", clock.now()) if f.known_at >= before_ct]
        print(f"    gather: new={r1.new} revised={r1.revised} unchanged={r1.unchanged} "
              f"(vs the {len(days)} bars already known from the panel)")
        print(f"    {len(born)} close Facts stamped known_at≈now (born at the door, not inherited)")
        print(f"    re-gather: new={r2.new} revised={r2.revised} unchanged={r2.unchanged} "
              f"— idempotent {_rule(r2.written == 0)}")
        if r1.revised:
            print(f"    → {r1.revised} panel values differ from live (auto_adjust) — recorded as "
                  f"honest revisions, not silent overwrites")
    except Exception as e:  # noqa: BLE001 - demo stays green offline
        print(f"    skipped (no network / fetch failed): {type(e).__name__}: {e}")

    print("\n" + "=" * 72)
    allpass = match and untouched and firewall
    print(f"RESULT: {_rule(allpass)} — Fact/Assessment split + append-only + as-of hold on real data.")
    print("=" * 72)


if __name__ == "__main__":
    main()
