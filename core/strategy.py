"""Sizing and entry Strategy Deciders for core.

Enforces structural rule constraints:
1. Decider consumes only bitemporal Assessment records from Memory (never raw Facts).
2. Sizing and action rules are customized by asset membership (Holdings, Pre-Positions, Watchlist).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from core import clock
from core.memory import Memory
from core.record import Assessment, Decision

if TYPE_CHECKING:
    from core.config import Holding


def evaluate_daily_strategy(
    memory: Memory,
    symbol: str,
    membership: str,  # "holding" | "pre_position" | "watchlist"
    holding_info: Holding | None = None,
    cfg: dict | None = None,
    as_of: datetime | None = None,
    *,
    version: str = "v1",
) -> Decision | None:
    """Read the latest Assessments for a symbol and propose a Decision bitemporally.
    
    Reflects three distinct policies based on the symbol's membership.
    """
    at = as_of or clock.now()
    cfg = cfg or {}
    
    # 1. Fetch the latest Assessments for this symbol
    assessments = memory.as_of(at, "assessment", symbol)
    if not assessments:
        return None
        
    # Extract specific perspectives
    tech_asm = next((a for a in assessments if isinstance(a, Assessment) and a.perspective == "technical"), None)
    bottom_asm = next((a for a in assessments if isinstance(a, Assessment) and a.perspective == "bottom_fishing"), None)
    fund_asm = next((a for a in assessments if isinstance(a, Assessment) and a.perspective == "fundamental"), None)
    left_side_asm = next((a for a in assessments if isinstance(a, Assessment) and a.perspective == "left_side_entry"), None)
    
    if not tech_asm or not tech_asm.payload:
        return None
        
    # Reconstruct the valuation state
    valuation_label = "unknown"
    peg = None
    if fund_asm and fund_asm.payload:
        try:
            fund_payload = json.loads(fund_asm.payload)
            valuation_label = fund_payload.get("valuation_label") or "unknown"
            peg = fund_payload.get("peg")
        except Exception:
            pass
        
    # Reconstruct the technical state from the Assessment's payload (honest and bitemporal!)
    metrics = json.loads(tech_asm.payload)
    price = metrics["price"]
    rsi = metrics["rsi"]
    trend_score = metrics["trend_score"]
    macd_cross = metrics["macd_cross"]
    kdj_cross = metrics["kdj_cross"]
    support = metrics.get("support")
    resistance = metrics.get("resistance")
    atr = metrics["atr"]
    day_change_pct = metrics["day_change_pct"]
    bb_pct_b = metrics["bb_pct_b"]
    bb_squeeze = metrics["bb_squeeze"]
    
    # Defaults
    action = "hold"
    intent = "Hold"
    reason = "No active rule triggered."
    dollar_gap = 0.0
    
    # Target Sizing Step Setup
    # Compute default target and step from config
    target_weights = cfg.get("target_weights", {})
    target_weight = target_weights.get(symbol, cfg.get("lifecycle", {}).get("entry_default_weight", 0.06))
    total_value = 100000.0  # Normalized default reference for reviews
    max_steps = cfg.get("lifecycle", {}).get("max_steps", 3)
    step_size = (target_weight / max_steps) * total_value if max_steps else target_weight * total_value
    
    # 2. HOLIDINGS POLICY (已持仓)
    if membership == "holding" and holding_info is not None:
        role = cfg.get("roles", {}).get(symbol, "swing")
        role_cfg = cfg.get("role_rules", {}).get(role, {})
        tp_pct = role_cfg.get("take_profit")
        sl_pct = role_cfg.get("stop_loss")
        
        pnl_pct = 0.0
        if holding_info.avg_cost > 0:
            pnl_pct = (price - holding_info.avg_cost) / holding_info.avg_cost
            
        # A. Speculative / Wave Trading roles (swing, momentum)
        if role in ("swing", "momentum"):
            if sl_pct is not None and pnl_pct <= -sl_pct:
                action = "sell"
                intent = "Close"
                reason = f"投机/波段止损触发: 亏损率 {pnl_pct:+.1%} 已触及/超止损线 -{sl_pct:.0%}. 建议坚决止损离场。"
                dollar_gap = -holding_info.shares * price
            elif tp_pct is not None and pnl_pct >= tp_pct:
                action = "sell"
                intent = "Close"
                reason = f"投机/波段止盈触发: 收益率 {pnl_pct:+.1%} 已达/超目标收益 {tp_pct:.0%}. 建议分批止盈/清仓。"
                dollar_gap = -holding_info.shares * price
            else:
                action = "hold"
                intent = "Hold"
                reason = f"波段持仓观察中: 成本 ${holding_info.avg_cost:.2f}, 当前 P&L: {pnl_pct:+.1%} (止盈 {tp_pct:.0%}/ 止损 -{sl_pct:.0%})."
                
        # B. Long-term roles (core)
        elif role == "core":
            # Check for dip buying
            if pnl_pct <= -0.15 and trend_score >= 50:
                action = "buy"
                intent = "Add Core"
                reason = f"核心持仓回调加仓提醒: 股价自成本价回调 {pnl_pct:+.1%}，基本面无恶化，建议分批加仓 ~${step_size:,.0f} 并滚动持仓。"
                dollar_gap = step_size
            # Check for Covered Call selling / Income Generation
            elif rsi >= 70 or bb_pct_b >= 1.0 or (resistance is not None and price >= resistance - 1.5 * atr):
                action = "generate_income"
                intent = "Generate Income"
                reason = f"核心持仓备兑期权提醒: 股价已处于超买阻力区 (RSI {rsi:.0f}, %B {bb_pct_b:.2f}). 建议卖出 Covered Call 获取权利金滚动持仓。"
                dollar_gap = 0.0
            else:
                action = "hold"
                intent = "Hold"
                reason = f"核心资产稳健持股中: 成本 ${holding_info.avg_cost:.2f}, 当前 P&L: {pnl_pct:+.1%}。处于安全舒适区。"
                
    # 3. PRE-POSITIONS POLICY (随时准备建仓)
    elif membership == "pre_position":
        is_breakout = price >= metrics.get("high_52w", price) or (resistance is not None and price > resistance)
        
        # Check support level reversal
        is_near_support = False
        is_reversal = False
        if support is not None:
            dist_pct = (price - support) / price if price > 0 else 0.0
            if 0 <= dist_pct <= 0.05 or (price - support <= 1.5 * atr):
                is_near_support = True
                if day_change_pct > 0 or macd_cross == "golden" or kdj_cross == "golden":
                    is_reversal = True
                    
        if is_breakout:
            action = "buy"
            intent = "Buy (Breakout)"
            reason = f"确认向上突破! 股价成功穿越关键阻力区 (${price:.2f})。建议执行第1步买入建仓 (~${step_size:,.0f})。"
            dollar_gap = step_size
        elif is_near_support and is_reversal:
            action = "buy"
            intent = "Buy (Support Reversal)"
            reversal_type = "价格止跌飘红" if day_change_pct > 0 else f"{'MACD' if macd_cross == 'golden' else 'KDJ'}金叉反弹"
            reason = f"支撑位止跌反弹确认 ({reversal_type})! 股价在支撑位 ${support:.2f} 上方企稳。建议买入建仓第1步 (~${step_size:,.0f})。"
            dollar_gap = step_size
        elif is_near_support:
            action = "hold"
            intent = "Wait (Near Support)"
            reason = f"股价已回调至关键支撑位 ${support:.2f} 附近，但尚未出现明确止跌反弹信号。建议继续耐心等待形态确立。"
            dollar_gap = 0.0
        else:
            action = "hold"
            intent = "Wait"
            reason = "正处于确定建仓观察期，等待向下回调至支撑位或向上放量突破阻力位。"
            dollar_gap = 0.0
            
    # 4. WATCHLIST POLICY (候选股扫描)
    else:
        is_left_candidate = left_side_asm is not None and left_side_asm.result == "candidate"
        is_bottom_candidate = bottom_asm is not None and bottom_asm.result == "candidate"
        
        if is_bottom_candidate:
            action = "buy"
            intent = "Buy (Bottom-Fishing)"
            reason = f"黄金超卖抄底信号! 股价极度超卖 (RSI {rsi:.1f}) 且处于强支撑位 ${support:.2f} 附近。建议小仓位介入抄底 (~${step_size:,.0f})。"
            dollar_gap = step_size
        elif is_left_candidate:
            action = "buy"
            intent = "Add Core (Left-Side)"
            reason = f"左侧估值建仓信号! 估值合理偏低 ({valuation_label}) 且股价贴近支撑位 ${support:.2f} 逐渐止跌。建议按 2-3-5 / 3-3-4 分批分档左侧建仓。"
            dollar_gap = step_size
        elif trend_score >= 75 and (rsi >= 60 or macd_cross == "golden" or bb_squeeze):
            action = "buy"
            intent = "Increase Exposure"
            reason = f"趋势强势右侧信号! 趋势得分 {trend_score:.0f} 指标处于买盘加速段。可适度开仓或追加仓位 (~${step_size:,.0f})。"
            dollar_gap = step_size
        else:
            action = "hold"
            intent = "Hold"
            reason = "趋势处于震荡或调整中，没有明确的左侧建仓或右侧突破形态。暂时观望。"
            dollar_gap = 0.0
            
    # Assemble the detailed Decision record (complete with payload!)
    payload_dict = {
        "intent": intent,
        "reason": reason,
        "dollar_gap": dollar_gap,
        "role": cfg.get("roles", {}).get(symbol, "swing") if membership == "holding" else "—",
        "membership": membership,
    }
    
    return Decision(
        kind="decision",
        subject=symbol,
        event_at=tech_asm.event_at,
        known_at=at,
        provenance=f"sizing_strategy@{version}",
        refs=(tech_asm.id,),
        actor="engine",
        status="proposed",
        action=action,
        payload=json.dumps(payload_dict),
    )


_ACTION = {"oversold": "buy", "overbought": "trim", "neutral": "hold"}


def momentum_strategy(
    memory: Memory, subject: str, as_of: datetime | None = None, *, version: str = "v1",
) -> Decision | None:
    """Read `subject`'s latest momentum Assessment known by `as_of`, and propose a Decision."""
    at = as_of or clock.now()
    candidates = [
        a for a in memory.as_of(at, "assessment", subject)
        if isinstance(a, Assessment) and a.perspective == "momentum"
    ]
    if not candidates:
        return None
    assessment = max(candidates, key=lambda a: a.known_at)   # the current momentum belief
    action = _ACTION.get(assessment.result, "hold")

    return Decision(
        kind="decision",
        subject=subject,
        event_at=assessment.event_at,
        known_at=at,                            # decided at the judgment instant (= now, live; = t, replay)
        provenance=f"momentum_strategy@{version}",
        refs=(assessment.id,),          # rests on the Assessment — never the raw Facts
        actor="engine",
        status="proposed",
        action=action,
    )
