# Investment Assistant

Personal investment assistant for zone-based alerts, daily market digest, Telegram notifications, and a lightweight web dashboard.

Chinese documentation: [README.zh-CN.md](docs/README.zh-CN.md)

## Features

- Zone alerting: detect whether watchlist symbols touch support/resistance zones.
- Flip suggestion: suggest zone flip when price breaks outside a zone by a threshold.
- Daily digest: generate and send market summary after close.
- Local OHLCV cache: store historical market data in SQLite.
- Web dashboard: manage watchlist zones with CRUD operations.

## Tech Stack

- Python 3.11+
- uv for environment and dependency management
- FastAPI + Jinja2 templates (web UI)
- python-telegram-bot (notification + bot commands)
- yfinance (market data source)
- pydantic + pydantic-settings (.env based typed configuration)

## Quick Start

### 1. Install uv

If uv is not installed yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Create environment and install dependencies

From repository root:

```bash
uv sync
```

### 3. Configure environment variables

Create local environment file:

```bash
cp .env.example .env
```

Required keys in .env:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Optional overrides:

```dotenv
WATCHLIST=AAPL,MSFT,NVDA,TSLA
PRICE_FEED_BACKEND=core.price_feed.YahooFeed
OHLCV_HISTORY_YEARS=5
FLIP_THRESHOLD_PCT=2.0
DAILY_JOB_TIME_ET=16:30
DB_PATH=data/trading.db
```

### 4. Initialize database and seed sample data

```bash
uv run python investment_assistant/setup.py
```

### 5. Run web dashboard

```bash
uv run uvicorn investment_assistant.web.app:app --reload
# open http://localhost:8000
```

### 6. Run Telegram bot

```bash
uv run python investment_assistant/notify/telegram_bot.py
```

Available commands:

| Command | Description |
|---|---|
| /price AAPL | Get latest close and nearby zones |
| /zones AAPL | List active zones |
| /flip <id> | Confirm zone flip |
| /digest | Trigger digest manually |
| /help | Show command help |

## Scheduler

The daily job entrypoint is:

```bash
uv run python investment_assistant/scheduler/daily_job.py
```

Integrate it with your system scheduler (cron, launchd, etc.) at your desired market-close time.

## Project Structure

```text
investment_assistant/
  config.py
  setup.py
  core/
    database.py
    price_feed.py
    zone_store.py
    alert_engine.py
    digest_builder.py
  notify/
    telegram_bot.py
  web/
    app.py
    templates/
      base.html
      index.html
      stock.html
  scheduler/
    daily_job.py
data/
  trading.db            # auto-created
```

## Configuration Notes

Configuration is centralized in investment_assistant/config.py.

- Settings are loaded with pydantic-settings.
- .env at repository root is loaded automatically.
- Environment variables override defaults.
- Existing module-level constants are kept for backward compatibility.

## Roadmap

- Phase 1: Manual zones + alerts + digest + web management
- Phase 2: Automatic support/resistance signal engine
- Phase 3: Downtrend scoring and strategy models
- Phase 4: LLM explanation layer and backtesting