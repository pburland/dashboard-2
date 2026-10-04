"""Where the athlete is on a given day: home, or a stop on a trip.

The itinerary lives in the ``travel`` table. Weather, the best-time
suggestion and the server's idea of "today" follow it, so a morning run in
Tokyo is dated and forecast in Tokyo.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import load_settings


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lng: float
    tz_name: str
    sports: tuple[str, ...] | None = None   # None = home, anything goes
    note: str = ""

    @property
    def away(self) -> bool:
        return self.sports is not None


def home() -> Place:
    s = load_settings()
    return Place("Home", s.home_lat, s.home_lng, s.tz_name)


def place_for(stops: list[dict], d: date) -> Place:
    for r in stops:
        if r["start_date"] <= d <= r["end_date"]:
            return Place(r["place"], r["lat"], r["lng"], r["tz_name"], tuple(r["sports"]), r["note"])
    return home()


def tz_for_now(stops: list[dict], now_utc: datetime) -> str:
    """The time zone the athlete is in right now. Tries tomorrow's stop
    first (flying east, the local date runs ahead of home), then today's."""
    home_tz = load_settings().tz_name
    d = now_utc.astimezone(ZoneInfo(home_tz)).date()
    for c in (d + timedelta(days=1), d):
        p = place_for(stops, c)
        if p.away and now_utc.astimezone(ZoneInfo(p.tz_name)).date() == c:
            return p.tz_name
    return home_tz


def load(conn) -> list[dict]:
    return conn.execute("select start_date, end_date, place, lat, lng, tz_name, sports, note "
                        "from travel order by start_date").fetchall()


# In-memory copy for the clock, which must not hit the database each call.
_CACHE: dict = {"stops": [], "at": 0.0}
_LOCK = threading.Lock()
TTL_S = 600


def cached_stops() -> list[dict]:
    with _LOCK:
        if time.monotonic() - _CACHE["at"] > TTL_S:
            _CACHE["at"] = time.monotonic()      # on failure, retry after the TTL
            try:
                from app import db
                with db.connect() as conn:
                    _CACHE["stops"] = load(conn)
            except Exception:
                pass
        return _CACHE["stops"]


def current_tz() -> str:
    return tz_for_now(cached_stops(), datetime.now(ZoneInfo("UTC")))
