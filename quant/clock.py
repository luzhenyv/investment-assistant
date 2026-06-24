"""Project time convention — ALL wall-clock time is UTC.

Every value the system stores, logs, or puts in a filename is computed in UTC, so the same instant
produces the same label no matter which timezone the script is run from. Interfaces MAY convert to a
user's local zone for *display*, but must never change the stored/system format.

Use these helpers everywhere instead of `datetime.now()` / `date.today()` (which return naive LOCAL
time and would make the same instant render differently when the script is run around the world)."""
from __future__ import annotations

from datetime import date, datetime, timezone

_TS_FMT = "%Y-%m-%d %H:%M:%S UTC"   # stored/human timestamp, explicit UTC marker
_FILE_FMT = "%Y-%m-%d_%H%M%S"       # sortable filename suffix (UTC; no colons)
_DATE_FMT = "%Y-%m-%d"              # date stamp (as_of_date, per-day parquet filename)


def now() -> datetime:
    """Timezone-aware current UTC instant."""
    return datetime.now(timezone.utc)


def today() -> date:
    """Current UTC calendar date."""
    return now().date()


def timestamp(dt: datetime | None = None) -> str:
    """Stored/human UTC timestamp, e.g. '2026-06-24 10:50:16 UTC'. Pass a fixed instant to keep
    several stamps from one run consistent."""
    return (dt or now()).strftime(_TS_FMT)


def file_stamp(dt: datetime | None = None) -> str:
    """Sortable UTC filename suffix, e.g. '2026-06-24_105016'."""
    return (dt or now()).strftime(_FILE_FMT)


def datestamp(dt: datetime | None = None) -> str:
    """UTC date string 'YYYY-MM-DD' (as_of_date / per-day parquet filename)."""
    return (dt or now()).strftime(_DATE_FMT)
