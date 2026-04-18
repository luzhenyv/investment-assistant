"""Database initialization helpers."""
from investment_assistant.database.base import Base
from investment_assistant.database.session import engine, database_url

# Ensure all model modules are imported so metadata has all tables.
from investment_assistant.database.models import Alert, Journal, OHLCV, Zone  # noqa: F401


def init_db() -> None:
    """Create all tables and run migrations if needed."""
    Base.metadata.create_all(engine)
    print(f"[db] Initialised -> {database_url}")
