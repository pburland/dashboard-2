from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.analysis.heat import HourlyWeather
from app.integrations.calendar import parse_busy
from app.planning import timing

ET = ZoneInfo("America/New_York")
TUE = date(2026, 10, 20)
SUN = date(2026, 10, 25)


def _dt(d, h, m=0):
    return datetime.combine(d, time(h, m), ET)


def test_windows_and_busy():
    slots = timing.free_slots(TUE, ET, [(_dt(TUE, 7), _dt(TUE, 9))])
    assert slots == [(_dt(TUE, 5, 30), _dt(TUE, 7)), (_dt(TUE, 18), _dt(TUE, 21, 30))]
    sun = timing.free_slots(SUN, ET, [])
    assert sun == [(_dt(SUN, 6), _dt(SUN, 9)), (_dt(SUN, 13), _dt(SUN, 20))]
    away = timing.free_slots(TUE, ET, [(_dt(TUE, 7), _dt(TUE, 19))], away=True)
    assert away == [(_dt(TUE, 6), _dt(TUE, 20))]      # work calendar ignored on a trip


def test_best_time_prefers_comfort_and_avoids_rain():
    hours = [HourlyWeather(_dt(SUN, h), 40 + h, 50, 40 + h, 80 if h in (14, 15, 16) else 0) for h in range(24)]
    slots = timing.free_slots(SUN, ET, [])
    s = timing.best_time(SUN, 60, "run", slots, hours)
    # 10 AM (50°F) is inside the blocked Sunday 9-1; 8 AM (48°F) beats 1 PM (53°F),
    # and the 2-5 PM rain is never picked.
    assert (s.start.hour, s.feels_f, s.precip_pct) == (8, 48, 0)
    indoor = timing.best_time(TUE, 45, "strength", timing.free_slots(TUE, ET, []))
    assert indoor.start == _dt(TUE, 6)                 # 5:30 only if clearly better


def test_heat_no_go_never_suggested():
    hot = [HourlyWeather(_dt(SUN, h), 96 if h >= 7 else 70, 60) for h in range(24)]
    s = timing.best_time(SUN, 60, "run", timing.free_slots(SUN, ET, []), hot)
    assert s.start.hour == 6


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART;TZID=America/New_York:20261019T073000
DTEND;TZID=America/New_York:20261019T083000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20261020
DTEND;VALUE=DATE:20261021
SUMMARY:Holiday
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261020T230000Z
DTEND:20261021T000000Z
TRANSP:TRANSPARENT
SUMMARY:Free
END:VEVENT
END:VCALENDAR
"""


def test_ics_recurring_expanded_all_day_and_free_skipped():
    b = parse_busy(ICS, TUE, TUE, ET)
    assert b == [(_dt(TUE, 7, 30), _dt(TUE, 8, 30))]
