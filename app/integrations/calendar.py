"""Work calendar (Google Calendar ICS feed) -> busy times.

Only start/end times are used; event titles never leave this module. Set
GOOGLE_CALENDAR_ICS_URL to the calendar's "Secret address in iCal format"
(or the public address, if the calendar is public).
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import MissingConfig, load_settings

_CACHE: dict = {"at": 0.0, "body": None}
_LOCK = threading.Lock()
TTL_S = 1800


def _fetch() -> bytes:
    url = load_settings().calendar_ics_url
    if not url:
        raise MissingConfig("GOOGLE_CALENDAR_ICS_URL")
    with _LOCK:
        if _CACHE["body"] is not None and time.monotonic() - _CACHE["at"] < TTL_S:
            return _CACHE["body"]
    r = httpx.get(url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    if b"BEGIN:VCALENDAR" not in r.content[:200]:
        raise RuntimeError("calendar URL did not return an iCal feed (is the calendar public, "
                           "or is this the secret iCal address?)")
    with _LOCK:
        _CACHE.update(at=time.monotonic(), body=r.content)
    return r.content


def parse_busy(ics: bytes, start: date, end: date, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """Busy intervals overlapping [start, end] (dates inclusive), recurring
    events expanded. All-day events, free ("transparent") events and
    declined invitations don't block time."""
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(ics)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end + timedelta(days=1)):
        s, e = ev.get("DTSTART").dt, (ev.get("DTEND").dt if ev.get("DTEND") else None)
        if not isinstance(s, datetime):
            continue                                   # all-day
        if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue
        if any(str(a.params.get("PARTSTAT", "")).upper() == "DECLINED"
               for a in _attendees(ev) if _is_me(a)):
            continue
        if e is None:
            e = s + (ev.get("DURATION").dt if ev.get("DURATION") else timedelta(hours=1))
        if s.tzinfo is None:
            s, e = s.replace(tzinfo=tz), e.replace(tzinfo=tz)
        out.append((s.astimezone(tz), e.astimezone(tz)))
    return sorted(out)


def _attendees(ev) -> list:
    a = ev.get("ATTENDEE")
    return [] if a is None else (a if isinstance(a, list) else [a])


def _is_me(attendee) -> bool:
    # The feed owner's own invitation carries their address; the URL holds it.
    url = load_settings().calendar_ics_url or ""
    me = url.split("/ical/")[-1].split("/")[0].replace("%40", "@").lower()
    return bool(me) and me in str(attendee).lower()


def busy(start: date, end: date, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    return parse_busy(_fetch(), start, end, tz)


def check() -> dict:
    from app import clock
    t = clock.today()
    b = busy(t, t + timedelta(days=6), clock.tz())
    return {"ok": True, "busy_blocks_next_7_days": len(b)}
