"""Render a BacktestResult as one interactive HTML figure: equity-vs-SPY,
drawdown underwater, and portfolio composition over time."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from quant.backtest import BacktestResult


def _drawdown(equity: list[float]) -> list[float]:
    """Running peak-to-trough drawdown as a negative fraction."""
    out, peak = [], equity[0]
    for v in equity:
        peak = max(peak, v)
        out.append((v - peak) / peak)
    return out


def _spy_equity(result: BacktestResult) -> list[float]:
    """SPY buy-hold normalized to the same starting capital as the strategy."""
    sp = result.spy_prices
    base = sp[0]
    return [result.initial_value * p / base for p in sp]


def _composition_weights(
    composition: list[dict[str, float]],
) -> tuple[list[str], dict[str, list[float]]]:
    """Per-week dollar values → per-symbol weight series (0 where absent), each
    week normalized to sum to 1.0. Returns (symbols, {symbol: weights})."""
    symbols = sorted({s for week in composition for s in week if s != "Cash"})
    symbols.append("Cash")  # keep cash last so it sits on top of the stack
    series: dict[str, list[float]] = {s: [] for s in symbols}
    for week in composition:
        total = sum(week.values()) or 1.0
        for s in symbols:
            series[s].append(week.get(s, 0.0) / total)
    return symbols, series


def write_equity_figure(result: BacktestResult, out_path: str) -> None:
    dates = result.dates
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.5, 0.2, 0.3],
        subplot_titles=("Equity vs SPY", "Drawdown", "Composition (% of portfolio)"),
    )

    # Row 1 — strategy vs SPY buy-hold, both from the same starting capital.
    fig.add_trace(
        go.Scatter(x=dates, y=result.equity, name="Strategy", line=dict(color="#1f77b4")),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=dates, y=_spy_equity(result), name="SPY buy-hold",
                   line=dict(color="#999999", dash="dot")),
        row=1, col=1,
    )

    # Row 2 — underwater drawdown.
    dd = [d * 100 for d in _drawdown(result.equity)]
    fig.add_trace(
        go.Scatter(x=dates, y=dd, name="Drawdown", fill="tozeroy",
                   line=dict(color="#d62728"), showlegend=False),
        row=2, col=1,
    )

    # Row 3 — composition as stacked weights (sums to 100% each week).
    symbols, series = _composition_weights(result.composition)
    for s in symbols:
        color = "#cccccc" if s == "Cash" else None
        fig.add_trace(
            go.Scatter(x=dates, y=[w * 100 for w in series[s]], name=s,
                       mode="lines", line=dict(width=0.5, color=color),
                       stackgroup="comp", legendgroup="comp"),
            row=3, col=1,
        )

    fig.update_yaxes(title_text="$", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="%", row=3, col=1, range=[0, 100])

    title = (
        f"Backtest — total {result.total_return:+.0%} (SPY {result.spy_return:+.0%}), "
        f"CAGR {result.cagr:+.1%}, Sharpe {result.sharpe:.2f}, max DD {result.max_drawdown:.1%}"
    )
    fig.update_layout(title=title, hovermode="x unified", height=900,
                      legend=dict(traceorder="normal"))

    fig.write_html(out_path, include_plotlyjs=True)
