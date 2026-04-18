# Investment Assistant（中文说明）

English documentation is the default: [README.md](../README.md)

## 项目简介

Investment Assistant 是一个个人化投资辅助系统，核心功能包括：

- 区间提醒：每日检测 Watchlist 股票是否触及手动设定支撑/压力区间
- 翻转建议：跌破支撑或突破压力超过阈值时，提醒是否翻转区间
- 每日复盘：收盘后发送大盘快照与触发记录汇总
- OHLCV 本地缓存：历史数据存入 SQLite，便于后续分析/回测
- Web 界面：管理 Watchlist 和区间（增删改查）

## 快速开始（推荐 uv）

1. 安装 uv（如未安装）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. 在仓库根目录创建环境并安装依赖

```bash
uv sync
```

3. 配置环境变量（使用 .env）

```bash
cp .env.example .env
# 编辑 .env，填入 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
```

4. 初始化数据库与样例数据

```bash
uv run python investment_assistant/setup.py
```

5. 启动 Web

```bash
uv run uvicorn investment_assistant.web.app:app --reload
# 浏览器访问 http://localhost:8000
```

6. 启动 Telegram Bot

```bash
uv run python investment_assistant/notify/telegram_bot.py
```

## 配置方式

配置文件位于 investment_assistant/config.py，已使用 pydantic + pydantic-settings：

- 默认从项目根目录 .env 读取配置
- 也支持系统环境变量覆盖
- 保持原有常量接口，现有模块无需改动即可继续运行

支持在 .env 中配置的关键项：

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- WATCHLIST（逗号分隔）
- PRICE_FEED_BACKEND（默认：`investment_assistant.services.prices.YahooFeed`）
- OHLCV_HISTORY_YEARS
- FLIP_THRESHOLD_PCT
- DISPLAY_TIMEZONE（显示时区，默认 `America/New_York`）
- MARKET_SESSION（市场交易时段，默认 `US`，可选 `CN`/`HK`/`JP`）
- DB_PATH

## 时间管理

项目内部所有时间戳统一使用 UTC，时区转换仅在展示层（Web 界面、Telegram 消息）进行。

- `infra/time.py` 提供 `utc_now()`、`utc_today()` 作为唯一时间来源
- `to_tz()` / `format_local()` 将 UTC 转为显示时区（由 `DISPLAY_TIMEZONE` 控制）
- `MarketSession` 描述交易所交易时段（开盘/收盘时间、交易日、IANA 时区）
- 内置市场：**US**、**CN**、**HK**、**JP**，通过 `MARKET_SESSION` 选择
- 常用查询：`is_open()`、`is_trading_day()`、`next_close_utc()`、`minutes_until_close()`

更多细节与完整使用说明，请查看英文版 [README.md](../README.md)。
