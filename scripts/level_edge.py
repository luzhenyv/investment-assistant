"""Measure whether detected S/R zones have REAL predictive edge — not whether they match
a human's labels.

    uv run python scripts/level_edge.py            # all tickers, pooled
    uv run python scripts/level_edge.py MSFT NVDA  # subset

Out-of-sample, walk-forward event study. At each step date T (using only data <= T, so no
look-ahead), we detect zones, then watch the next H bars: when price ENTERS a zone, does it
HOLD (support bounces / resistance rejects) or BREAK? We compare the hold rate at detected
zones against the hold rate at RANDOM price levels tested the same way (controls for drift —
in an uptrend everything "holds", but random levels enjoy the same drift). Significance is a
label-permutation test on the difference in proportions.

This is the honest question the 21-label validation could not answer: a zone is only "real" if
price reverses there more often than at a random level. Aligns with the repo's backtest-review
discipline (out-of-sample, permutation test, drift-controlled baseline).
"""
from __future__ import annotations

import os
import random
import sys
from statistics import median

import polars as pl
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import indicators, levels, providers  # noqa: E402

# Calibration universe (SPX -> ^GSPC). Liquid names with long history.
TICKERS = {
    "AAPL": "AAPL", "AMZN": "AMZN", "META": "META", "GOOG": "GOOG", "NVDA": "NVDA",
    "TSLA": "TSLA", "TSM": "TSM", "NFLX": "NFLX", "ORCL": "ORCL", "IBM": "IBM",
    "LLY": "LLY", "ISRG": "ISRG", "MRVL": "MRVL", "MSFT": "MSFT", "AVGO": "AVGO",
    "SOXX": "SOXX", "SMH": "SMH", "IGV": "IGV", "SPX": "^GSPC", "PLTR": "PLTR", "HOOD": "HOOD",
}
WARMUP = 300        # bars before evaluation begins (let MA200 / lookback fill)
STEP = 5            # eval every 5 bars (weekly cadence)
H = 20              # forward window (~1 trading month)
M_ATR = 1.0         # resolution threshold: move this many ATRs to confirm hold/break
RAND_PER_T = 6      # random control levels generated per eval date (per side)
N_PERM = 1000       # label-permutation iterations
random.seed(7)      # reproducible


def _resolve(kind, lo, hi, fhigh, flow, atr, m):
    """1 = hold (support bounced / resistance rejected), 0 = break, None = untested/unresolved."""
    tol = m * atr
    entered = False
    for hh, ll in zip(fhigh, flow):
        if kind == "support":
            entered = entered or ll <= hi
            if entered:
                up, dn = hh >= hi + tol, ll <= lo - tol
                if up and not dn:
                    return 1
                if dn and not up:
                    return 0
                if up and dn:
                    return None  # ambiguous single-bar whipsaw
        else:  # resistance
            entered = entered or hh >= lo
            if entered:
                dn, up = ll <= lo - tol, hh >= hi + tol
                if dn and not up:
                    return 1
                if up and not dn:
                    return 0
                if up and dn:
                    return None
    return None


def _collect(ticker, sym, cfg):
    """Return (detected_events, random_events) as lists of (outcome, frozenset(methods), kind)."""
    period, min_rows = cfg["data"]["period"], cfg["data"]["min_rows"]
    frames = providers.fetch_history([sym], period, min_rows)
    if sym not in frames:
        return [], []
    df = frames[sym].sort("date")
    high = df["High"].to_list()
    low = df["Low"].to_list()
    n = len(high)
    det, rnd = [], []
    for ti in range(WARMUP, n - H, STEP):
        sub = df.head(ti + 1)
        price = float(sub["Close"][-1])
        atr = indicators.atr(sub["High"], sub["Low"], sub["Close"])
        if not atr or atr <= 0:
            continue
        fhigh = high[ti + 1 : ti + 1 + H]
        flow = low[ti + 1 : ti + 1 + H]
        zones = levels.detect_zones(sub, cfg, current_price=price)
        if not zones:
            continue
        widths = [z.high - z.low for z in zones]
        med_w = median(widths) if widths else price * 0.015
        for z in zones:
            o = _resolve(z.kind, z.low, z.high, fhigh, flow, atr, M_ATR)
            if o is not None:
                det.append((o, frozenset(z.methods), z.kind))
        # drift-matched random controls, generated per SIDE so each kind has its own baseline
        # (uptrend drift makes support and resistance base rates very different).
        for _ in range(RAND_PER_T):
            for kind, span in (("support", (0.55, 1.0)), ("resistance", (1.0, 1.45))):
                lv = random.uniform(price * span[0], price * span[1])
                klo, khi = lv - med_w / 2, lv + med_w / 2
                o = _resolve(kind, klo, khi, fhigh, flow, atr, M_ATR)
                if o is not None:
                    rnd.append((o, frozenset(), kind))
    return det, rnd


def _rate(events):
    return (sum(e[0] for e in events) / len(events)) if events else float("nan")


def _perm_p(a_hits, a_n, b_hits, b_n):
    """Two-sided permutation test on difference in hold rate between groups A and B."""
    if a_n == 0 or b_n == 0:
        return float("nan")
    obs = a_hits / a_n - b_hits / b_n
    pool = [1] * (a_hits + b_hits) + [0] * ((a_n - a_hits) + (b_n - b_hits))
    ge = 0
    for _ in range(N_PERM):
        random.shuffle(pool)
        diff = sum(pool[:a_n]) / a_n - sum(pool[a_n:]) / b_n
        if abs(diff) >= abs(obs) - 1e-12:
            ge += 1
    return ge / N_PERM


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "demo", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    wanted = [a.upper() for a in sys.argv[1:]]
    tickers = {k: v for k, v in TICKERS.items() if not wanted or k in wanted}

    det, rnd = [], []
    for tk, sym in tickers.items():
        d, r = _collect(tk, sym, cfg)
        det += d
        rnd += r
        print(f"  {tk:5} detected events {len(d):5}  random {len(r):5}")

    def report(kind):
        d = [e for e in det if e[2] == kind]
        r = [e for e in rnd if e[2] == kind]
        base, bh, bn = _rate(r), sum(e[0] for e in r), len(r)
        print(f"\n{'=' * 72}\n{kind.upper()}  (hold = "
              f"{'bounced up off the zone' if kind == 'support' else 'rejected down at the zone'})"
              f"\n{'=' * 72}")
        print(f"  random {kind} baseline   n={bn:6}  hold={base:5.1%}  (reference)\n")

        def line(label, evs):
            n = len(evs)
            if not n:
                print(f"  {label:22} n=0")
                return
            hits = sum(e[0] for e in evs)
            rate = hits / n
            p = _perm_p(hits, n, bh, bn)
            star = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            print(f"  {label:22} n={n:6}  hold={rate:5.1%}  edge={(rate - base) * 100:+5.1f}pp  p={p:.3f} {star}")

        line("ALL detected", d)
        print("  by method in zone:")
        for mth in ("vwap", "volume", "fib", "box", "ma", "round", "swing"):
            line("  " + mth, [e for e in d if mth in e[1]])
        print("  by confluence:")
        line("  1 method", [e for e in d if len(e[1]) == 1])
        line("  2 methods", [e for e in d if len(e[1]) == 2])
        line("  >=3 methods", [e for e in d if len(e[1]) >= 3])

    print(f"\n{'#' * 72}\nEDGE vs KIND-MATCHED RANDOM BASELINE (out-of-sample walk-forward)\n{'#' * 72}")
    report("support")
    report("resistance")
    print(f"\n  (H={H} bars, resolution={M_ATR} ATR, step={STEP}, warmup={WARMUP}; "
          f"* p<.10 ** p<.05 *** p<.01)")


if __name__ == "__main__":
    main()
