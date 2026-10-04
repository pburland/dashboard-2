"""Best time to do a session: inside Patrick's training windows, clear of
work-calendar events, and (outdoors) in the most comfortable weather.

Windows (local time where he is):
  weekdays  before 8 AM and after 6 PM
  Saturday  free
  Sunday    free except 9 AM - 1 PM
  on a trip every day free, 6 AM - 8 PM; the work calendar is ignored
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.analysis.heat import THRESHOLDS, HourlyWeather, heat_index_f

WINDOWS: dict[int, list[tuple[time, time]]] = {
    **{d: [(time(5, 30), time(8, 0)), (time(18, 0), time(21, 30))] for d in range(5)},
    5: [(time(6, 0), time(20, 0))],
    6: [(time(6, 0), time(9, 0)), (time(13, 0), time(20, 0))],
}
AWAY_WINDOWS = [(time(6, 0), time(20, 0))]
OUTDOOR = {"run", "bike"}
IDEAL_F = 50.0          # most comfortable "feels like" for running
STEP = timedelta(minutes=30)


@dataclass(frozen=True)
class Suggestion:
    start: datetime
    end: datetime
    feels_f: float | None
    precip_pct: float | None
    why: str

    def as_dict(self) -> dict:
        a, b = _t(self.start), _t(self.end)
        if a[-2:] == b[-2:]:
            a = a[:-3]                       # "6–6:45 AM", not "6 AM–6:45 AM"
        return {"start": self.start.isoformat(), "end": self.end.isoformat(),
                "label": f"{a}–{b}", "feels_f": self.feels_f,
                "precip_pct": self.precip_pct, "why": self.why}


def _t(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").replace(":00 ", " ")


def free_slots(d: date, tz: ZoneInfo, busy: list[tuple[datetime, datetime]],
               away: bool = False) -> list[tuple[datetime, datetime]]:
    """Training windows on ``d`` minus busy time."""
    slots = []
    for a, b in (AWAY_WINDOWS if away else WINDOWS[d.weekday()]):
        slots.append((datetime.combine(d, a, tz), datetime.combine(d, b, tz)))
    return slots if away else _minus(slots, busy)


def _hours_for(hours: list[HourlyWeather], start: datetime, end: datetime) -> list[HourlyWeather]:
    return [h for h in hours if h.time < end and h.time + timedelta(hours=1) > start]


def best_time(d: date, duration_min: float, sport: str, slots: list[tuple[datetime, datetime]],
              hours: list[HourlyWeather] | None = None, kind: str = "easy") -> Suggestion | None:
    """Earliest start wins ties; outdoors, the feels-like temperature closest
    to ~50°F with the least rain wins, and a heat no-go is never suggested."""
    dur = timedelta(minutes=max(15, duration_min or 45))
    outdoor = sport in OUTDOOR
    nogo = THRESHOLDS.get(kind, THRESHOLDS["easy"])[1]
    best: tuple[float, Suggestion] | None = None
    for s, e in slots:
        t = s
        while t + dur <= e:
            w = _hours_for(hours or [], t, t + dur) if outdoor else []
            feels = rain = None
            score = 0.0
            if w:
                if max(heat_index_f(h.temp_f, h.rel_humidity) for h in w) >= nogo:
                    t += STEP
                    continue
                f = [h.feels_f if h.feels_f is not None else h.temp_f for h in w]
                feels = round(max(f) if max(f) > IDEAL_F else min(f))
                rain = max((h.precip_pct or 0) for h in w)
                score = abs(feels - IDEAL_F) + 0.4 * rain
            if t.time() < time(6, 0):
                score += 4        # a 5:30 start only when it's clearly better
            if best is None or score < best[0] - 0.01:
                best = (score, Suggestion(t, t + dur, feels, rain, ""))
            t += STEP
    if best is None:
        return None
    sug = best[1]
    if not outdoor:
        why = "first free window"
    elif sug.feels_f is None:
        why = "first free window (no forecast yet)"
    else:
        why = f"feels like {sug.feels_f:.0f}°F" + (f", {sug.precip_pct:.0f}% chance of rain" if sug.precip_pct else ", dry")
    return Suggestion(sug.start, sug.end, sug.feels_f, sug.precip_pct, why)


def annotate(conn, days: list[dict], today: date, horizon_days: int = 14) -> str | None:
    """Add ``best_time`` to each planned session from today to the horizon.
    ``days`` is [{"date", "sessions"}]. Returns a note if the calendar or
    the forecast couldn't be read (suggestions still use the windows)."""
    from app import clock, travel
    from app.integrations import calendar, weather
    stops = travel.load(conn)
    last = min(max((d["date"] for d in days), default=today), today + timedelta(days=horizon_days))
    if last < today:
        return None
    notes = []
    home_tz = ZoneInfo(travel.home().tz_name)
    try:
        busy = calendar.busy(today, last, home_tz)
    except Exception as e:
        busy = []
        notes.append("work calendar not connected" if "GOOGLE_CALENDAR_ICS_URL" in str(e)
                     else f"work calendar unavailable ({type(e).__name__})")
    forecasts: dict[str, list] = {}
    for d in days:
        if not (today <= d["date"] <= last):
            continue
        place = travel.place_for(stops, d["date"])
        tz = ZoneInfo(place.tz_name)
        if place.name not in forecasts:
            try:
                forecasts[place.name] = weather.hourly_forecast(16, place if place.away else None)
            except Exception as e:
                forecasts[place.name] = []
                notes.append(f"forecast unavailable for {place.name} ({type(e).__name__})")
        slots = free_slots(d["date"], tz, [] if place.away else busy, away=place.away)
        if d["date"] == clock.today():
            now = clock.now().astimezone(tz)
            slots = [(max(s, now), e) for s, e in slots if e > now]
        used: list[tuple[datetime, datetime]] = []
        for s in d["sessions"]:
            if s.get("suppressed") or s.get("status") not in (None, "planned") or s.get("sport") == "race":
                continue
            free = _minus(slots, used)
            kind = "long" if s.get("is_long") else ("quality" if s.get("max_zone") not in (None, "Z1", "Z2") else "easy")
            sug = best_time(d["date"], s.get("duration_min") or 45, s.get("sport", ""), free,
                            forecasts.get(place.name), kind)
            if sug:
                s["best_time"] = sug.as_dict() | ({"place": place.name} if place.away else {})
                used.append((sug.start, sug.end + timedelta(minutes=15)))
            else:
                s["best_time"] = {"label": None, "why": "no free window in your usual training times"}
    return "; ".join(dict.fromkeys(notes)) or None


def _minus(slots: list[tuple[datetime, datetime]],
           busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Slots with the busy intervals cut out."""
    out = list(slots)
    for bs, be in busy:
        nxt = []
        for s, e in out:
            if be <= s or bs >= e:
                nxt.append((s, e))
                continue
            if bs > s:
                nxt.append((s, bs))
            if be < e:
                nxt.append((be, e))
        out = nxt
    return [(s, e) for s, e in out if e > s]
