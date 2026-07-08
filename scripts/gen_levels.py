"""Seed the semi-automatic support/resistance file `levels.yaml` from the auto-detector.

    uv run python scripts/gen_levels.py                 # seed missing names (watchlist + holdings)
    uv run python scripts/gen_levels.py MU NVDA         # seed only these (if not already curated)
    uv run python scripts/gen_levels.py MU --force       # RE-seed MU, discarding its hand edits

This writes auto-detected zones as a *first draft* the user then hand-corrects (the detector finds
where zones are, but its exact bands/strength need a human eye). Merge is NON-DESTRUCTIVE: a symbol
already in the file is preserved untouched unless --force names it, so re-running never clobbers hand
edits. The engine loads the result via quant/manual_levels.py; see the levels.yaml format there.

Run against the active PROFILE (env var; default demo → config/demo/levels.yaml, else
private/<profile>/levels.yaml). Report-only, like the detector — never touches scoring/decision.
"""
from __future__ import annotations

import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant import clock, levels, manual_levels, profiles, providers  # noqa: E402

# The detector's `small` zones are the noisiest/least reliable — omit them from the draft so the
# user prunes a clean list. (Kept if a name has nothing stronger, so an entry is never empty.)
_SEED_MIN = {"medium", "strong", "super-strong"}

_HEADER = """\
# Support/resistance zones — the engine's authoritative S/R when a symbol is listed here.
#
# Seeded by scripts/gen_levels.py from the auto-detector, then HAND-EDIT for precision.
#   strength : small | medium | strong | super-strong
#   kind     : optional (support/resistance); inferred from current price when omitted
#   note     : optional free text for your own reference
# A symbol absent from this file falls back to auto-detection. Bump a symbol's as_of when you
# re-review it; the file goes "stale" (still loaded, flagged in the report) after
# levels.manual_refresh_days. Re-seed one name with: gen_levels.py <SYM> --force
"""


def _universe() -> list[str]:
    _, portfolio, watchlist, _, _ = profiles.resolve(ROOT)
    watch = (yaml.safe_load(open(watchlist)) or {}).get("symbols", [])
    port = (yaml.safe_load(open(portfolio)) or {}).get("positions", {})
    return sorted(set(watch) | set(port))


def _seed_zones(df, cfg, price: float) -> list[dict]:
    """Auto-detect, drop `small` (unless nothing stronger), emit `{low, high, strength}` drafts."""
    zones = levels.detect_zones(df, cfg, current_price=price)
    strong = [z for z in zones if z.label in _SEED_MIN] or zones
    return [{"low": round(z.low, 2), "high": round(z.high, 2), "strength": z.label} for z in strong]


def main(argv: list[str]) -> None:
    force = "--force" in argv
    targets = [a for a in argv if not a.startswith("--")]

    config, _, _, _, _ = profiles.resolve(ROOT)
    path = manual_levels.path_for(config)
    cfg = yaml.safe_load(open(config)) or {}
    existing = manual_levels.load(path)
    symbols = dict(existing.get("symbols") or {})   # copy so we merge non-destructively

    wanted = targets or _universe()
    today = clock.datestamp()

    to_seed = [s for s in wanted if force or s not in symbols]
    preserved = [s for s in wanted if not force and s in symbols]
    if not to_seed:
        print(f"Nothing to seed — {len(preserved)} already curated (use --force to re-seed).")
        return

    data_cfg = cfg.get("data", {})
    history = providers.fetch_history(to_seed, period=data_cfg.get("period", "2y"),
                                      min_rows=data_cfg.get("min_rows", 60))
    seeded, skipped = [], []
    for sym in to_seed:
        df = history.get(sym)
        if df is None:
            skipped.append(sym)
            continue
        price = float(df.sort("date")["Close"].tail(1).item())
        zones = _seed_zones(df, cfg, price)
        if not zones:
            skipped.append(sym)
            continue
        symbols[sym] = {"as_of": today, "zones": zones}
        seeded.append(sym)

    body = {"as_of": today, "symbols": symbols}
    with open(path, "w") as f:
        f.write(_HEADER)
        yaml.safe_dump(body, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    print(f"Wrote {path}")
    print(f"  seeded: {', '.join(seeded) or '—'}")
    if preserved:
        print(f"  preserved (hand edits kept): {', '.join(preserved)}")
    if skipped:
        print(f"  skipped (no data / no zones): {', '.join(skipped)}")


if __name__ == "__main__":
    main(sys.argv[1:])
