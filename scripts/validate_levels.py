"""Validate quant/levels.py against a trader's hand-labeled support/resistance zones.

    uv run python scripts/validate_levels.py            # aggregate + per-ticker summary
    uv run python scripts/validate_levels.py MSFT SOXX  # detailed tables for named tickers

Zones were transcribed from 视野环球财经 chart screenshots (~20 tickers, captured Apr–Jun
2026). Each is validated AS-OF its screenshot date (history sliced to that date, so the
detector sees only what the trader saw). Targets are read in aggregate across all tickers —
tuning to any single ticker is the data-snooping trap the project's backtest discipline warns
against.

Strength labels: small < medium < strong < super-strong (小 < 中 < 强 < 超强; 极小 -> small).
"""
from __future__ import annotations

import os
import sys

import polars as pl
import yaml
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import levels, providers  # noqa: E402

S, M, T, U = "small", "medium", "strong", "super-strong"

# ticker -> (as_of ISO date, fetch_symbol, [(low, high, label), ...])
EXAMPLES: dict[str, tuple] = {
    "AAPL": ("2026-05-01", "AAPL", [(265, 281, T), (252, 263, T), (244, 250, M), (221, 236, T), (206, 214, T)]),
    "AMZN": ("2026-04-29", "AMZN", [(244, 251, M), (227, 240, T), (219, 226, T), (204, 213, M)]),
    "META": ("2026-05-01", "META", [(690, 730, T), (638, 680, T), (559, 611, T), (482, 540, T), (454, 471, T), (423, 441, S), (321, 396, U)]),
    "GOOG": ("2026-06-01", "GOOG", [(375, 388, M), (329, 340, S), (311, 325, T)]),
    "NVDA": ("2026-05-15", "NVDA", [(208, 211, S), (199, 203, M), (187, 196, T), (175, 185, T)]),
    "TSLA": ("2026-04-22", "TSLA", [(420, 465, T), (380, 405, S), (315, 368, T), (296, 309, S), (271, 289, M), (235, 265, U), (209, 228, T), (175, 201, T)]),
    "TSM": ("2026-04-17", "TSM", [(360, 377, M), (338, 351, T), (316, 332, M), (290, 308, T), (270, 285, S), (258, 266, M), (236, 247, T)]),
    "NFLX": ("2026-04-20", "NFLX", [(108, 112, T), (102, 107, M), (95, 100, U), (87, 92, T), (79, 84, M), (74, 77, T), (67, 72, U), (60, 65, T), (55, 57, U), (47, 50, T)]),
    "ORCL": ("2026-05-28", "ORCL", [(321, 332, M), (292, 314, T), (272, 284, T), (243, 258, M), (232, 240, T), (209, 226, M), (187, 203, T), (175, 183, T), (162, 169, M), (147, 159, T), (137, 143, T), (120, 127, T), (110, 116, T)]),
    "IBM": ("2026-05-28", "IBM", [(295, 313, M), (273, 287, M), (250, 260, T), (235, 247, T), (213, 227, M), (198, 208, M)]),
    "LLY": ("2026-04-30", "LLY", [(1000, 1090, T), (938, 963, M), (871, 928, T), (808, 840, T), (710, 778, U), (690, 701, S), (576, 650, T)]),
    "ISRG": ("2026-06-04", "ISRG", [(430, 458, T), (370, 405, T), (321, 360, T), (258, 295, U)]),
    "MRVL": ("2026-06-04", "MRVL", [(198, 210, S), (189, 195, S), (176, 182, M), (161, 172, T), (144, 150, M)]),
    "MSFT": ("2026-05-01", "MSFT", [(469, 490, M), (432, 452, M), (395, 430, U), (381, 392, M), (360, 375, T), (328, 346, T), (277, 311, T)]),
    "AVGO": ("2026-06-03", "AVGO", [(457, 465, S), (392, 433, M), (370, 385, M), (324, 365, U), (286, 307, M), (258, 277, M)]),
    "SOXX": ("2026-06-16", "SOXX", [(554, 577, T), (489, 532, M), (450, 467, M), (436, 443, M), (412, 422, S), (386, 401, S), (348, 368, T), (324, 345, U), (297, 312, M), (287, 293, T), (278, 284, T), (264, 272, M)]),
    "SMH": ("2026-06-05", "SMH", [(589, 613, M), (533, 579, M), (499, 511, M), (461, 468, S), (437, 453, S), (409, 419, T), (374, 404, U), (351, 370, T), (343, 349, T), (330, 340, T), (313, 327, M), (303, 307, S), (282, 299, M), (272, 278, S), (257, 265, T), (238, 255, T)]),
    "IGV": ("2026-06-01", "IGV", [(109, 111, T), (101, 107, T), (96.4, 99.6, S), (90.1, 94.8, M), (86.4, 89.4, T), (83.8, 85.6, T), (80.3, 83.1, U), (75.5, 79.1, M), (66.8, 72.9, T)]),
    "SPX": ("2026-05-01", "^GSPC", [(6800, 6980, T), (6550, 6765, T), (6354, 6500, M), (6210, 6303, S), (5835, 6140, U)]),
    "PLTR": ("2026-05-18", "PLTR", [(175, 192, T), (164, 172, S), (151, 161, T), (136, 144, M), (121, 130, T), (100, 118, M), (70, 76, U)]),
    "HOOD": ("2026-04-28", "HOOD", [(114, 118, T), (98, 110, T), (90.7, 95.2, M), (81.9, 87.1, S), (70.9, 79.4, T), (60.6, 67.4, T), (52.6, 56.7, S), (46.6, 51.4, T), (37.5, 43.2, T), (32.4, 35.3, M), (26.2, 28.4, S), (21.4, 24.8, T)]),
}
_RANK = {S: 1, M: 2, T: 3, U: 4}
_CN = {S: "小", M: "中", T: "强", U: "超强"}


def _iou(a, b):
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0.0, hi - lo)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def _overlaps(band, z, thr):
    mid = (band[0] + band[1]) / 2.0
    iou = _iou(band, (z.low, z.high))
    inside = z.low <= mid <= z.high
    return (iou >= thr or inside), (iou if iou > 0 else (0.01 if inside else 0.0))


def _match_one_to_one(labeled, zones, thr):
    """Greedy one-to-one: strongest labels claim their best detected zone first."""
    order = sorted(range(len(labeled)), key=lambda i: _RANK[labeled[i][2]], reverse=True)
    used, matches = set(), {}
    for li in order:
        lo, hi, _ = labeled[li]
        best, best_iou, best_zi = None, 0.0, -1
        for zi, z in enumerate(zones):
            if zi in used:
                continue
            ok, iou = _overlaps((lo, hi), z, thr)
            if ok and iou >= best_iou:
                best, best_iou, best_zi = z, iou, zi
        if best is not None:
            used.add(best_zi)
            matches[li] = (best, best_iou)
    return matches


def _spearman(xs, ys):
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = pl.Series(xs).rank(), pl.Series(ys).rank()
    c = pl.DataFrame({"x": rx, "y": ry}).select(pl.corr("x", "y")).item()
    return float(c) if c is not None else None


def _evaluate(ticker, cfg, period, min_rows, verbose):
    as_of, sym, labeled = EXAMPLES[ticker]
    frames = providers.fetch_history([sym], period, min_rows)
    if sym not in frames:
        return None
    df = frames[sym].filter(pl.col("date") <= date.fromisoformat(as_of))
    if df.height < 200:
        return None
    price = float(df["Close"].tail(1).item())
    zones = levels.detect_zones(df, cfg)
    thr = cfg["levels"].get("iou_threshold", 0.3)
    matches = _match_one_to_one(labeled, zones, thr)

    pred_rank, true_rank, rec_strong, tot_strong = [], [], 0, 0
    for li, (lo, hi, lbl) in enumerate(labeled):
        z = matches.get(li, (None,))[0]
        if lbl in (T, U):
            tot_strong += 1
            rec_strong += 1 if z is not None else 0
        if z is not None:
            true_rank.append(_RANK[lbl])
            pred_rank.append(_RANK.get(z.label, 0))

    ss_bands = [(lo, hi) for lo, hi, l in labeled if l == U]
    ss_hit = None
    if ss_bands:
        ss_hit = any(
            z.label == U and any(_overlaps(b, z, 0.3)[0] for b in ss_bands)
            for z in zones
        )
    rec = rec_strong / tot_strong if tot_strong else None
    sp = _spearman(pred_rank, true_rank)

    if verbose:
        print(f"\n{'=' * 80}\n{ticker} ({sym}) as-of {as_of}  price {price:.2f}  {len(zones)} zones")
        print(f"{'=' * 80}\n{'labeled':>14} {'lbl':>13} | {'matched':>14} {'det-lbl':>13} {'IoU':>5}")
        for li, (lo, hi, lbl) in enumerate(labeled):
            m = matches.get(li)
            z, iou = m if m else (None, 0.0)
            det = f"{z.low:.0f}-{z.high:.0f}" if z else "—"
            dl = z.label if z else "—"
            print(f"{f'{lo:g}-{hi:g}':>14} {_CN[lbl]+' '+lbl:>15} | {det:>14} {dl:>15} {iou:>5.2f}")
    return {"ticker": ticker, "price": price, "nzones": len(zones),
            "recovery": rec, "spearman": sp, "ss_hit": ss_hit}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "demo", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    period, min_rows = cfg["data"]["period"], cfg["data"]["min_rows"]
    wanted = [a.upper() for a in sys.argv[1:]]
    verbose = bool(wanted)
    tickers = wanted or list(EXAMPLES)

    rows = [r for t in tickers if (r := _evaluate(t, cfg, period, min_rows, verbose))]

    print(f"\n{'=' * 80}\nPER-TICKER SUMMARY\n{'=' * 80}")
    print(f"{'ticker':>7} {'price':>9} {'zones':>6} {'str/SS recov':>13} {'spearman':>9} {'SS hit':>7}")
    for r in rows:
        rec = f"{r['recovery']:.0%}" if r["recovery"] is not None else "n/a"
        sp = f"{r['spearman']:.2f}" if r["spearman"] is not None else "n/a"
        sh = "—" if r["ss_hit"] is None else ("YES" if r["ss_hit"] else "no")
        print(f"{r['ticker']:>7} {r['price']:>9.2f} {r['nzones']:>6} {rec:>13} {sp:>9} {sh:>7}")

    recs = [r["recovery"] for r in rows if r["recovery"] is not None]
    sps = [r["spearman"] for r in rows if r["spearman"] is not None]
    # Spearman over >=6 labeled zones only: a 3-4 point rank correlation is too quantized
    # to be meaningful, and those tickers swamp the simple mean with noise.
    sps_big = [r["spearman"] for r in rows
               if r["spearman"] is not None and len(EXAMPLES[r["ticker"]][2]) >= 6]
    sshits = [r["ss_hit"] for r in rows if r["ss_hit"] is not None]
    print(f"\n{'=' * 80}\nAGGREGATE (n={len(rows)} tickers)\n{'=' * 80}")
    print(f"  mean strong/super-strong recovery: {sum(recs) / len(recs):.0%}   (target >= 80%)")
    print(f"  mean label-rank Spearman (all):    {sum(sps) / len(sps):.2f}")
    print(f"  mean label-rank Spearman (>=6 zns): {sum(sps_big) / len(sps_big):.2f}   (n={len(sps_big)})")
    print(f"  super-strong hit rate:             {sum(sshits)}/{len(sshits)} = "
          f"{sum(sshits) / len(sshits):.0%}")


if __name__ == "__main__":
    main()
