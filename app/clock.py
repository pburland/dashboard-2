"""The server is the only clock.

Lessons carried from the prototype:
  * Never hardcode "today". Every caller asks this module, and every
    domain function takes an explicit ``as_of: date`` so it can be tested.
  * Calendar logic uses plain ``datetime.date`` values, which carry no time
    or timezone. "Today" is the calendar date in the athlete's timezone, so
    there is no UTC-midnight rollover to work around.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from app.config import load_settings


# Set at startup to app.travel.current_tz, so "today" follows a trip. Unset
# (tests, scripts), the home timezone applies.
_resolver: Callable[[], str] | None = None


def set_resolver(fn: Callable[[], str] | None) -> None:
    global _resolver
    _resolver = fn


def tz() -> ZoneInfo:
    if _resolver is not None:
        try:
            return ZoneInfo(_resolver())
        except Exception:
            pass
    return ZoneInfo(load_settings().tz_name)


def now() -> datetime:
    """Current moment, timezone-aware, in the athlete's timezone."""
    return datetime.now(tz())


def today() -> date:
    """Current calendar date where the athlete is (home, or a trip stop)."""
    return now().date()


def week_start(d: date) -> date:
    """Monday of the week containing ``d``."""
    return d - timedelta(days=d.weekday())


def days_until(target: date, as_of: date) -> int:
    return (target - as_of).days
