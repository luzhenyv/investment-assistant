"""Forward-return evaluator: grade the stored decisions against what the market actually did.

Reads the labelled panel (data/daily_observations/<profile>/*.parquet), joins each row's `state` read
and `intent` call to its realized +5/+20/+60 **trading-day** forward return, and writes a scorecard
(output/<profile>/eval_*.{md,json}) plus a graded per-row parquet (…/<profile>/_eval/). This is
data-flywheel Phase 2 — see docs/DATA_FLYWHEEL.md. Read-only over the panel; no engine run.

    uv run evaluate.py            # active PROFILE (default demo)
    PROFILE=stocks uv run evaluate.py
"""
from __future__ import annotations

import json
import os

import polars as pl

from quant import clock, evaluate, pipeline, profiles, providers
from quant.daily_report import _pct
from quant.report import _table

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG, PORTFOLIO, WATCHLIST, OPTIONS, OUT_DIR = profiles.resolve(ROOT)
PROFILE = os.environ.get("PROFILE", "demo")
STORE = os.path.join(ROOT, "data", "daily_observations", PROFILE)
HORIZONS = evaluate.HORIZONS


def _cell(stat: dict, kind: str) -> str:
    """One horizon cell: '—' until a return resolves, else the value tagged with its sample size."""
    if kind == "mean":
        return "—" if stat["mean"] is None else f"{_pct(stat['mean'])} (n={stat['n']})"
    if kind == "delta":
        return "—" if stat["delta_base"] is None else _pct(stat["delta_base"])
    if kind == "hit":
        return "—" if stat["hit_rate"] is None else f"{stat['hit_rate']:.0%} (n={stat['n_graded']})"
    raise ValueError(kind)


def _state_table(rows: list[dict]) -> list[str]:
    """Mean forward return by asset state (full-universe coverage) vs the universe base rate."""
    headers = ["State", "Rows"] + [f"+{h}d mean" for h in HORIZONS] + [f"+{h}d vs base" for h in HORIZONS]
    aligns = ["l", "r"] + ["r"] * (2 * len(HORIZONS))
    body = [[r["key"], r["total"]] + [_cell(r[h], "mean") for h in HORIZONS]
            + [_cell(r[h], "delta") for h in HORIZONS] for r in rows]
    return _table(headers, body, aligns)


def _intent_table(rows: list[dict]) -> list[str]:
    """Hit-rate + mean forward return by intent (actionable subset only). Ungraded intents dropped."""
    graded = [r for r in rows if any(r[h]["n_graded"] for h in HORIZONS)]
    headers = ["Intent", "Rows"] + [f"+{h}d hit" for h in HORIZONS] + [f"+{h}d mean" for h in HORIZONS]
    aligns = ["l", "r"] + ["r"] * (2 * len(HORIZONS))
    body = [[r["key"], r["total"]] + [_cell(r[h], "hit") for h in HORIZONS]
            + [_cell(r[h], "mean") for h in HORIZONS] for r in graded]
    return _table(headers, body, aligns)


def main() -> None:
    now = clock.now()
    generated_at = clock.timestamp(now)
    stamp = clock.file_stamp(now)

    panel = evaluate.load_panel(STORE)
    if panel.height == 0:
        raise SystemExit(f"No daily observations under {STORE} — run daily_review.py first.")

    data_cfg = pipeline._load_yaml(CONFIG).get("data", {})
    symbols = sorted(panel["symbol"].unique().to_list())
    history = providers.fetch_history(
        symbols, data_cfg.get("period", "10y"), data_cfg.get("min_rows", 200), force_refresh=False,
    )

    # Join every stored label to its realized forward return + a pass/fail grade.
    graded: list[dict] = []
    for row in panel.iter_rows(named=True):
        bars = history.get(row["symbol"])
        fwd = (evaluate.forward_returns(bars, row["bar_date"], HORIZONS)
               if bars is not None else {h: None for h in HORIZONS})
        hit = {h: evaluate.grade(row["intent"], fwd[h]) for h in HORIZONS}
        graded.append({
            "symbol": row["symbol"], "bar_date": row["bar_date"], "price": row["price"],
            "state": row["state"], "intent": row["intent"], "fwd": fwd, "hit": hit,
        })

    by_state, base = evaluate.summarize(graded, "state", HORIZONS)
    by_intent, _ = evaluate.summarize(graded, "intent", HORIZONS)

    sessions = sorted(panel["bar_date"].unique().to_list())
    resolved = {h: sum(1 for g in graded if g["fwd"][h] is not None) for h in HORIZONS}

    md = [f"# Forward-Return Scorecard — {generated_at}", ""]
    md += [f"Panel: **{panel.height}** rows · **{len(symbols)}** symbols · "
           f"**{len(sessions)}** sessions ({sessions[0]} → {sessions[-1]}), profile `{PROFILE}`.", ""]
    md += ["Resolved forward returns (still accumulating for longer horizons): "
           + " · ".join(f"+{h}d: {resolved[h]}" for h in HORIZONS) + ".", ""]
    md += ["_Honest framing: this is a decision engine until these numbers earn otherwise. Thin "
           "samples (small n) are noise, not edge — see docs/DATA_FLYWHEEL.md._", ""]
    md += ["## By asset state (full universe)", ""]
    md += _state_table(by_state)
    md += ["Base rate (universe mean forward return): "
           + " · ".join(f"+{h}d {_pct(base[h])}" for h in HORIZONS) + ".", ""]
    md += ["## By intent (actionable calls)", ""]
    md += ["_Grading rule: long intents (Add Core / Increase Exposure) want a gain; reduce intents "
           "(Trim / Close) want the name to fall; Hold wants ±3%. Income/Hedge/empty = ungraded._", ""]
    md += _intent_table(by_intent)

    os.makedirs(OUT_DIR, exist_ok=True)
    md_path = os.path.join(OUT_DIR, f"eval_{stamp}.md")
    json_path = os.path.join(OUT_DIR, f"eval_{stamp}.json")
    with open(md_path, "w") as f:
        f.write("\n".join(md))
    with open(json_path, "w") as f:
        json.dump({
            "generated_at": generated_at, "profile": PROFILE, "horizons": list(HORIZONS),
            "sessions": sessions, "rows": panel.height, "resolved": resolved,
            "base_rate": base, "by_state": by_state, "by_intent": by_intent,
        }, f, indent=2)

    # Accumulate the graded per-row outcomes alongside the panel (invisible to the panel glob — it
    # lives in the _eval/ subdir, like _runs/). Recomputable, but a dated audit trail of each scoring.
    eval_dir = os.path.join(STORE, "_eval")
    os.makedirs(eval_dir, exist_ok=True)
    flat = [{
        "symbol": g["symbol"], "bar_date": g["bar_date"], "price": g["price"],
        "state": g["state"], "intent": g["intent"],
        **{f"fwd_{h}d": g["fwd"][h] for h in HORIZONS},
        **{f"hit_{h}d": g["hit"][h] for h in HORIZONS},
    } for g in graded]
    pl.DataFrame(flat).write_parquet(os.path.join(eval_dir, f"eval_{stamp}.parquet"))

    print(f"Scorecard written to {md_path}")
    print("  resolved forward returns: " + ", ".join(f"+{h}d={resolved[h]}" for h in HORIZONS))


if __name__ == "__main__":
    main()
