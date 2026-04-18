"""
Centralised time utilities.

Golden rule: everything inside the project runs on UTC.
Conversion to local / market timezones happens only at the
service / application boundary (web UI, Telegram messages, scheduler).

Uses stdlib ``zoneinfo`` (Python 3.9+) — no third-party deps.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


# ── UTC helpers (used everywhere) ─────────────────────────────────────────────

def utc_now() -> datetime:
    """Timezone-aware ``datetime.now()`` pinned to UTC."""
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """UTC date — independent of the server's local clock."""
    return datetime.now(timezone.utc).date()


# ── Display conversion (used only at application boundary) ────────────────────

def to_tz(dt: datetime, tz_name: str) -> datetime:
    """
    Convert a UTC-aware datetime to the given timezone.
    If *dt* is naive it is assumed to be UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name))


def format_local(dt: datetime, tz_name: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a UTC datetime as a local-time string."""
    return to_tz(dt, tz_name).strftime(fmt)


# ── Market session awareness ─────────────────────────────────────────────────

class MarketSession:
    """
    Describes one exchange's regular trading hours.

    Parameters
    ----------
    name : str          Human-readable label, e.g. "US", "CN".
    tz_name : str       IANA timezone, e.g. "America/New_York".
    open_time : str     "HH:MM" in market-local time.
    close_time : str    "HH:MM" in market-local time.
    trading_days : set  ISO weekday numbers (1=Mon … 7=Sun).
    """

    def __init__(
        self,
        name: str,
        tz_name: str,
        open_time: str,
        close_time: str,
        trading_days: set[int] | None = None,
    ):
        self.name = name
        self.tz_name = tz_name
        self.tz = ZoneInfo(tz_name)
        self.open_time = time.fromisoformat(open_time)
        self.close_time = time.fromisoformat(close_time)
        self.trading_days = trading_days or {1, 2, 3, 4, 5}  # Mon-Fri

    # ── queries ───────────────────────────────────────────────────────────

    def _local_now(self) -> datetime:
        return utc_now().astimezone(self.tz)

    def is_trading_day(self, d: date | None = None) -> bool:
        """True if *d* (or today in market-local time) is a trading day."""
        if d is None:
            d = self._local_now().date()
        return d.isoweekday() in self.trading_days

    def is_open(self, at: datetime | None = None) -> bool:
        """True if the market is currently in regular trading hours."""
        if at is None:
            local = self._local_now()
        else:
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            local = at.astimezone(self.tz)
        if not self.is_trading_day(local.date()):
            return False
        return self.open_time <= local.time() < self.close_time

    def today_open_utc(self) -> datetime | None:
        """Today's market open as a UTC datetime, or None if not a trading day."""
        local_date = self._local_now().date()
        if not self.is_trading_day(local_date):
            return None
        local_dt = datetime.combine(local_date, self.open_time, tzinfo=self.tz)
        return local_dt.astimezone(timezone.utc)

    def today_close_utc(self) -> datetime | None:
        """Today's market close as a UTC datetime, or None if not a trading day."""
        local_date = self._local_now().date()
        if not self.is_trading_day(local_date):
            return None
        local_dt = datetime.combine(local_date, self.close_time, tzinfo=self.tz)
        return local_dt.astimezone(timezone.utc)

    def next_close_utc(self) -> datetime:
        """
        The next upcoming market close in UTC.
        If the market is currently open, returns today's close.
        Otherwise advances to the next trading day.
        """
        local = self._local_now()
        d = local.date()
        # If market is open now, return today's close
        if self.is_trading_day(d) and local.time() < self.close_time:
            close_local = datetime.combine(d, self.close_time, tzinfo=self.tz)
            return close_local.astimezone(timezone.utc)
        # Otherwise find the next trading day
        for _ in range(7):
            d += timedelta(days=1)
            if self.is_trading_day(d):
                close_local = datetime.combine(d, self.close_time, tzinfo=self.tz)
                return close_local.astimezone(timezone.utc)
        # Fallback (should never happen with Mon-Fri)
        raise RuntimeError("No trading day found within 7 days")

    def minutes_until_close(self) -> int | None:
        """Minutes until market close, or None if market is not open."""
        if not self.is_open():
            return None
        close_utc = self.today_close_utc()
        if close_utc is None:
            return None
        delta = close_utc - utc_now()
        return max(0, int(delta.total_seconds() // 60))

    def __repr__(self) -> str:
        return (
            f"MarketSession({self.name!r}, tz={self.tz_name!r}, "
            f"{self.open_time.isoformat()}-{self.close_time.isoformat()})"
        )


# ── Pre-defined sessions ─────────────────────────────────────────────────────

US = MarketSession("US",  "America/New_York",  "09:30", "16:00")
CN = MarketSession("CN",  "Asia/Shanghai",     "09:30", "15:00")
HK = MarketSession("HK",  "Asia/Hong_Kong",    "09:30", "16:00")
JP = MarketSession("JP",  "Asia/Tokyo",        "09:00", "15:00")

SESSIONS: dict[str, MarketSession] = {
    "US": US,
    "CN": CN,
    "HK": HK,
    "JP": JP,
}


def get_session_by_name(name: str) -> MarketSession:
    """Lookup a pre-defined market session by name (case-insensitive)."""
    key = name.upper()
    if key not in SESSIONS:
        raise KeyError(f"Unknown market session: {name!r}. Available: {list(SESSIONS)}")
    return SESSIONS[key]
