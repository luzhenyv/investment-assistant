# Trading Assistant

一个个人化的投资辅助系统，核心功能：

- **区间提醒**：每日检测 Watchlist 股票是否触及手动设定的支撑/压力区间
- **翻转建议**：价格跌破支撑 / 突破压力超过阈值时，通过 Telegram 提示确认翻转
- **每日复盘**：收盘后自动发送大盘快照 + 触及区间汇总
- **OHLCV 本地缓存**：5 年历史数据存入 SQLite，供未来数据分析和回测使用
- **Web 界面**：管理 Watchlist 区间（增删改查）

---

## 快速开始

### 1. 安装依赖

```bash
pip install yfinance flask python-telegram-bot schedule
```

### 2. 配置

编辑 `config.py`，填入你的 Watchlist：

```python
WATCHLIST = ["AAPL", "MSFT", "TSLA", ...]
```

设置环境变量（推荐写入 `~/.zshrc` 或 `~/.bash_profile`）：

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

> **如何获取 Telegram 凭据**
> 1. 在 Telegram 搜索 `@BotFather`，发送 `/newbot` 创建 bot，获得 token
> 2. 向你的 bot 发送任意消息，然后访问：
>    `https://api.telegram.org/bot<TOKEN>/getUpdates`
>    找到 `"chat":{"id":...}` 即为 chat_id

### 3. 初始化 + 首次数据同步

```bash
python setup.py
```

这会：
- 创建 `data/trading.db`（SQLite 数据库）
- 拉取所有 Watchlist 股票 + 宏观指标的 5 年 OHLCV 历史数据
- 添加示例区间并验证核心逻辑

### 4. 启动 Web 界面

```bash
python web/app.py
# 访问 http://localhost:5000
```

### 5. 启动 Telegram Bot（持续监听指令）

```bash
python notify/telegram_bot.py
```

可用指令：

| 指令 | 说明 |
|------|------|
| `/price AAPL` | 查询最新收盘价，显示附近区间 |
| `/zones AAPL` | 列出该股所有活跃区间 |
| `/flip <id>` | 确认翻转某个区间（支撑↔压力） |
| `/digest` | 立即生成今日复盘报告 |
| `/help` | 显示帮助 |

### 6. 设置每日定时任务

**macOS LaunchAgent（推荐）**

创建 `~/Library/LaunchAgents/com.trading.daily.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>com.trading.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/trading_assistant/scheduler/daily_job.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>    <integer>16</integer>
    <key>Minute</key>  <integer>30</integer>
    <key>Weekday</key> <integer>1</integer>
  </dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key> <string>your_token</string>
    <key>TELEGRAM_CHAT_ID</key>   <string>your_chat_id</string>
  </dict>
  <key>StandardOutPath</key>  <string>/tmp/trading_daily.log</string>
  <key>StandardErrorPath</key><string>/tmp/trading_daily_err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.trading.daily.plist
```

**Linux / 远端服务器 cron**

```bash
crontab -e
# 美东时间 16:30 = UTC 20:30（夏令时）/ 21:30（冬令时）
30 20 * * 1-5 cd /path/to/trading_assistant && \
  TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python scheduler/daily_job.py \
  >> /var/log/trading_daily.log 2>&1
```

---

## 项目结构

```
trading_assistant/
  config.py              ← 所有配置入口
  setup.py               ← 首次初始化脚本
  core/
    database.py          ← SQLite schema + 连接工具
    price_feed.py        ← 数据源抽象接口 + Yahoo 实现 + 缓存读写
    zone_store.py        ← 区间 CRUD（add / edit / flip / deactivate）
    alert_engine.py      ← 触碰检测 + 翻转建议（纯函数，无副作用）
    digest_builder.py    ← 复盘报告组装
  notify/
    telegram_bot.py      ← Push 发送 + 指令监听
  web/
    app.py               ← Flask 界面（查看 + 管理区间）
    templates/
      base.html          ← 深色主题基础模板
      index.html         ← Watchlist 总览
      stock.html         ← 个股区间管理
  scheduler/
    daily_job.py         ← 每日定时任务（同步 → 检测 → 发送）
  data/
    trading.db           ← SQLite（自动生成）
```

---

## 数据库表结构

| 表 | 说明 |
|----|------|
| `ohlcv` | 所有股票 + 宏观指标的日线 OHLCV 缓存 |
| `zones` | 手动设定的支撑/压力区间，含强度和备注 |
| `alerts` | 历史触发记录 |
| `journal` | 交易日志（Phase 1 留接口，手动记录） |

---

## 扩展数据源

当前使用 Yahoo Finance（免费）。切换数据源只需两步：

1. 在 `core/price_feed.py` 新增实现类（继承 `PriceFeed`）
2. 修改 `config.py` 中的 `PRICE_FEED_BACKEND`

```python
# config.py
PRICE_FEED_BACKEND = "core.price_feed.AlphaVantageFeed"  # 改这一行
```

---

## Roadmap

| Phase | 内容 |
|-------|------|
| ✅ Phase 1 | 手动区间 + 提醒 + 复盘 + Web 管理 |
| Phase 2 | Python Signal Engine（自动识别支撑压力） |
| Phase 3 | 止跌评分 + 策略模型 |
| Phase 4 | LLM 解释层 + 回测系统 |