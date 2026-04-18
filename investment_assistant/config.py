"""Project configuration loaded from defaults + environment variables.

Values can be provided through a local ``.env`` file at the repository root
or via process environment variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed runtime settings for the investment assistant."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = ROOT_DIR / "data"
    log_dir: Path = ROOT_DIR / "logs"
    db_path: Path | None = None
    log_level: str = "INFO"

    price_feed_backend: str = "investment_assistant.services.prices.YahooFeed"
    ohlcv_history_years: int = 5

    watchlist: list[str] = [
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
        "AMZN",
        "META",
        "TSLA",
        "AMD",
        "NFLX",
        "PLTR",
    ]

    macro_symbols: dict[str, str] = {
        "SPX": "^GSPC",
        "VIX": "^VIX",
        "DXY": "DX-Y.NYB",
        "OIL": "CL=F",
        "GOLD": "GC=F",
    }

    flip_threshold_pct: float = 2.0
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    display_timezone: str = "America/New_York"
    market_session: str = "US"

    @field_validator("watchlist", mode="before")
    @classmethod
    def _parse_watchlist(cls, value: Any) -> Any:
        # Support WATCHLIST="AAPL,MSFT,TSLA" in .env in addition to JSON arrays.
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return value

    @field_validator("db_path", mode="before")
    @classmethod
    def _empty_db_path_to_none(cls, value: Any) -> Any:
        if value in ("", None):
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    if settings.db_path is None:
        settings.db_path = settings.data_dir / "trading.db"
    return settings


SETTINGS = get_settings()
