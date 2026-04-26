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
PRICE_FEED_BACKEND=investment_assistant.services.prices.YahooFeed
OHLCV_HISTORY_YEARS=5
FLIP_THRESHOLD_PCT=2.0
DISPLAY_TIMEZONE=America/New_York
MARKET_SESSION=US
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_RELOAD=false
DB_PATH=data/trading.db
```

### 4. Initialize database and seed sample data

```bash
uv run python investment_assistant/setup.py
```

### 5. Run web dashboard

```bash
uv run uvicorn investment_assistant.web.app:app --host 0.0.0.0 --port 8000
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

The market-open kickoff job entrypoint is:

```bash
uv run python investment_assistant/scheduler/open_job.py
```

Integrate it with your system scheduler (cron, launchd, etc.) at your desired market-close time.

To find the next market close in UTC (handles DST automatically):

```bash
uv run python -c "from investment_assistant.scheduler.daily_job import next_run_utc; print(next_run_utc())"
```

## Server Deployment

For a Tailscale-only deployment, run the web UI on `0.0.0.0:8000` and access it through the server's Tailscale IP from another device on your tailnet.

Example components to run on the server:

- Web UI: `uv run uvicorn investment_assistant.web.app:app --host 0.0.0.0 --port 8000`
- Telegram bot: `uv run python investment_assistant/notify/telegram_bot.py`
- Market open: `uv run python investment_assistant/scheduler/open_job.py`
- Market close: `uv run python investment_assistant/scheduler/daily_job.py`

Example `systemd` units and timers are included under `deploy/systemd/`:

- `investment-assistant-web.service`
- `investment-assistant-telegram-bot.service`
- `investment-assistant-market-open.service`
- `investment-assistant-market-open.timer`
- `investment-assistant-market-close.service`
- `investment-assistant-market-close.timer`

Suggested installation flow on the server:

```bash
sudo cp deploy/systemd/investment-assistant-*.service /etc/systemd/system/
sudo cp deploy/systemd/investment-assistant-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now investment-assistant-web.service
sudo systemctl enable --now investment-assistant-telegram-bot.service
sudo systemctl enable --now investment-assistant-market-open.timer
sudo systemctl enable --now investment-assistant-market-close.timer
```

Adjust `WorkingDirectory` and `EnvironmentFile` in those unit files if your server path is not `/opt/investment-assistant`.

## Time Management

All internal timestamps are UTC. Timezone conversion happens only at the application boundary (web UI, Telegram messages).

- `infra/time.py` provides `utc_now()`, `utc_today()` — the single source of truth for the current time.
- `to_tz()` / `format_local()` convert UTC to a display timezone (controlled by `DISPLAY_TIMEZONE`).
- `MarketSession` models exchange trading hours (open/close times, trading days, IANA timezone).
- Pre-defined sessions: **US**, **CN**, **HK**, **JP**. Select the active one via `MARKET_SESSION`.
- Key queries: `is_open()`, `is_trading_day()`, `next_close_utc()`, `minutes_until_close()`.

Database columns, log timestamps, and all core logic use UTC exclusively. No `date.today()` or naive `datetime.now()` calls exist in the codebase.

## Project Structure

```text
investment_assistant/
  config.py               # pydantic-settings configuration
  setup.py                # DB init + sample data seeder
  infra/
    time.py               # UTC helpers + MarketSession
    log.py                # logging setup
  core/
    alerts.py             # alert detection logic
    zones.py              # zone CRUD (repository)
    digest.py             # daily digest assembler
  services/
    prices.py             # price feed adapter (Yahoo Finance + OHLCV cache)
  database/
    models/
      alert.py
      journal.py
      ohlcv.py
      zone.py
    base.py
    init_db.py
    session.py
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
    open_job.py
data/
  trading.db              # auto-created
```
## Roadmap

- Phase 1: Manual zones + alerts + digest + web management
- Phase 2: Automatic support/resistance signal engine
- Phase 3: Downtrend scoring and strategy models
- Phase 4: LLM explanation layer and backtesting