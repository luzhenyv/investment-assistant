# 规格说明：基于双时态 Memory 的全新 Daily Review 系统 (Specifications / PRD)

> **设计核心理念**：语言优先于行为，行为优先于实现 (Language → Behavior → Implementation)。

本说明书是对全新 `core/` 架构下 Daily Review 系统的需求、设计、多数据源拓展性、以及多 Actor 决策融合的完整规格定义，代表了最新的决策智能 (Decision Intelligence) 设计理念。

---

## 1. 系统愿景 (Vision)
现有的 `daily_review.py` 在执行中存在三个重大设计瓶颈（见 `IMPLEMENTATION_STATUS.md`）：
1. **职责混淆 (Conflation)**：它既抓取并处理数据、计算指标、得出买卖建议并写入文件（属于 `DATA_PIPELINE` 生产），又在同一流程中渲染 HTML/Markdown 供人类阅读（属于 `REVIEW_SYSTEM` 视图）。
2. **就地修改 (In-place Overwrite)**：每次重新运行某日 review 都会使用最新调整后的复权价格覆盖历史 Parquet 文件，从而破坏了“历史数据的绝对诚实性”（无 Revision 留存）。
3. **内联判断 (In-line Judgment)**：异常交易量（RVOL z-score）、超买超卖、状态翻转等“指标判断（Assessment）”直接在 Review 渲染层中生成并输出，缺乏独立的、可追溯的主体归属，无法被后续的回测和评估系统度量（Evaluation）。

**升级目标**：
在 `core/` 文件夹下，实现一套**完全独立于 `quant/`**、**严格符合双时态（Bitemporal）事实/判断/决策隔离规范**的全新 Daily Review 系统，作为项目走向“高可用自治代理（Autonomy）”的第一个真实生产骨干。

---

## 2. 核心架构与 7 概念映射
完全继承并实现 `10-ONTOLOGY.md` 和 `11-DECISION_LOOP.md` 规范。

```
       KNOW (客观事实)               ACT (主观决策政策)                 LEARN (闭环反馈)
Fact ──────▶ Assessment ──────▶ Strategy ──────▶ Decision ──────▶ Outcome ──────▶ Evaluation
(OHLCV       (超买超卖, 支撑位,    (波段止损/       (Engine提案,       (30d后实际     (ROI, 胜率,
 事实)        左侧/抄底机遇)         止盈, 突破)       Agent/Human抉择)   收益Fact)      主观可靠性)
```

### A. 客观事实 (Fact) — `core/record.py:Fact`
- 存放环境的纯粹客观观测。目前仅包含日线 OHLCV 数据（`metric` 分别为 `"open"`, `"high"`, `"low"`, `"close"`, `"volume"`）。
- 自带双时态标记：`event_at` 代表 K线发生的市场交易日；`known_at` 代表系统抓取并存储该事实的时间戳。
- 历史数据永远不覆盖，价格复权或数据修正作为一条带有新 `known_at` 的新 `Fact` 记录追加到系统，保证回测在任何时刻都能重建 `t` 时刻的真实系统信念。

### B. 判断/评估 (Assessment) — `core/record.py:Assessment`
- 由各种专门的 **Assessor (评估器)** 基于特定视角（`Perspective`）分析事实生成。
- **全新升级的评估器包含**：
  1. `momentum`：通过 RSI、布林带 `%B` 综合研判当前走势的超买 (overbought)、超卖 (oversold) 或中性 (neutral) 状态。
  2. `macd` / `kdj`：检测最新的 MACD 金叉/死叉、MACD 顶/底背离、KDJ 金叉/死叉。
  3. `levels`：检测最近的支撑位（Support）与阻力位（Resistance）区间及强度。
  4. `left_side_entry` (左侧建仓机遇)：下行趋势/回调 (Trend < 50) + 估值合理 (PEG <= 2.0 或 cheap/fair) + 处于支撑位（1.5x ATR以内）时触发。
  5. `bottom_fishing` (抄底机会)：深度超卖 (RSI <= 35) + 处于 Strong / Super-Strong 强支撑位时触发。

### C. 决策 (Decision) — `core/record.py:Decision`
- 由 **Strategy (决策政策模块)** 读取 `Memory` 中的 Assessments 生成，输出具有 `actor` 和 `status` 的动作提议：
  - **Position (持仓管理策略)**：
    - 波段投机型（`swing`, `momentum`）依据成本价（`avg_cost`）监控实时 P&L。当浮盈超过 `take_profit` 触发止盈，浮亏低于 `stop_loss` 触发止损。
    - 中长期持有型（`core`）当浮亏达到 `-15%` 且趋势未坏时触发“分批加仓 / 滚动持仓”提醒；接近阻力位/超买提示“滚动套利 (Covered Call)”。
  - **Pre-Position (随时建仓监控策略)**：
    - 处于确定买入但等待良机的阶段。监控是否“突破 (Breakout)”或“止跌反弹 (Support Reversal)”，并生成对应的买入动作。
  - **Watchlist (候选观察策略)**：
    - 根据 RS 相对强度与金叉/超卖指标生成“Increase Exposure”或“Hold”。

---

## 3. 多数据镜头的存储设计与极简无缝扩容 (Multi-Lens Scaling)

### 3.1 弹性的 `payload` 存储设计
为了能在将来轻松整合 **期权链 (Options)**、**宏观 FRED 曲线 (Macro)**、**新闻舆情 (News)** 等极其复杂或结构多变的数据镜头，而无需不断修改物理 Parquet 数据库的 schema，我们在基础 `Record` Dataclass 中引入了泛型字段 `payload: str = ""`。

- **多镜头 Fact/Assessment 存入规范**：
  - 选项分析（Option Positioning）：`Assessment(perspective="options", result="put_wall:150;call_wall:180", payload="{'max_pain': 165, 'net_gex': 15000}")`。
  - 舆情信息（Social Sentiment）：`Assessment(perspective="sentiment", result="bullish", payload="{'st_net': 0.65, 'chatter_z': 2.5}")`。
- **优点**：任何新增的数据镜头只需通过序列化 JSON 存入 `payload`，物理底层和检索工具（`Memory.as_of`）均能完美保持不变。

### 3.2 自治代理的阶梯架构：Multi-Actor Decision
这是决策隔离防火墙中最重要的一环。在全新 Daily Review 流程中，我们允许不同参与者（Actor）在不相互干预的前提下提出/做出 `Decision`，并能追溯其上下游依赖：

```
Decision(actor="engine", status="proposed")
   │
   ├──▶ Decision(actor="agent", status="proposed", refs=(<engine_id>,))  # AI 代理（如 Claude Skill）评估并审查 Engine
          │
          └──▶ Decision(actor="human", status="accepted", refs=(<agent_id>,))  # 人类做出最终执行
```

- **Engine** 仅通过客观的 Assessment 进行纯数字化、确定性规则的 `Decision` 提案。
- **AI Agent (如 `.claude/skills/daily-review`)** 会基于 Engine 的决策、再加上宏观/期权/舆情 payload 进行全视角审查，在 `Memory` 中追加其专属的决策，详细过程写入 `payload` 文本。
- **Human (人类主宰)** 查看两方的独立决策，输入接受、忽略、拒绝并写入最终的 `accepted` 决策。
- **评估系统（Evaluation）** 在 30 天后（$t+30d$）能够针对相同的 Facts，完全平等、不偏不倚地测量 **Engine 的纯量化决策** 和 **Agent 的综合智能决策** 以及 **Human 的最终修改决策** 谁的表现最好，驱动整个系统不断迭代进化（PDCA）。

---

## 4. 模块划分与重构文件职责

```
core/
├── __init__.py
├── clock.py               # UTC 统一时区与时间转换工具（绝对 UTC）
├── record.py              # (修改) 基础双时态 Data Model，Fact, Assessment, Decision (支持 payload)
├── memory.py              # (修改) 泛型、幂等、双时态 append-only Parquet 存取器 (data/memory/<profile>/)
├── config.py              # (新) 解析 portfolio.yaml (提取 cash, holdings, pre_positions), watchlist 
├── gather.py              # (修改) 数据抓取：从 yfinance 抓取 3 年数据(3y) 并转化为 Fact 存入 Memory
├── indicators.py          # (修改) 经典技术指标（MA, RSI, MACD, BB, KDJ等）
├── assess.py              # (新) 多维度技术 Assessor：产出 Technical Assessments 并存入 Memory
├── strategy.py            # (新) 持仓盈亏追踪 / 随时建仓监控 / 观察区扫描 Strategy：产出 Decision 提案并存入 Memory
├── report.py              # (新) 纯读、零内联判断的 Review 报告渲染器 (输出 MD/JSON 视图)
└── daily_review.py        # (新) 重构后的主流程：Phase 1: Ingestion & Assessment -> Phase 2: Render Report
```

---

## 5. 开发顺序与里程碑
1. **[Data Model]**：升级 `core/record.py` 的字段，使其完全向下兼容并支持 `payload`。
2. **[Ingestion]**：编写 `core/config.py` 解析 Pre-Positions 及 portfolio，并在 `core/gather.py` 中更新为 3 年的抓取窗口。
3. **[Assessment]**：在 `core/indicators.py` 中实现 `kdj_cross` 的向量化 Polars 快速计算，在 `core/assess.py` 中构建多视角的客观技术 Assessor。
4. **[Strategy]**：在 `core/strategy.py` 中编码波段止盈止损政策与 Pre-Position 的“止跌/突破”条件。
5. **[Review System]**：在 `core/report.py` 和 `core/daily_review.py` 中实现纯读、模块化的 Markdown 呈现，保证所有的 Flag 均来源于 Stored Assessments。
6. **[Testing]**：维护原有测试套件使其 100% 绿灯，并为新 pipeline 编写鲁棒的覆盖测试。
