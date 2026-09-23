"""Heat go/no-go for a planned start time.

Uses the National Weather Service heat index (Rothfusz regression with the
NWS adjustments) over every forecast hour the session will span. The
thresholds are this system's own conservative defaults, not a published
standard, and are stricter for long or hard sessions. They tighten further
only after a heat illness (not after an ordinary illness such as a virus).
The Sep 13, 2026 long run (10:09 start, ~85°F) is a NO-GO under these rules.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.analysis.flags import Flag, Severity

# (caution at or above, no-go at or above), heat index °F
THRESHOLDS = {
    "easy": (85.0, 95.0),
    "quality": (80.0, 88.0),
    "long": (78.0, 85.0),
}
HEAT_ILLNESS_OFFSET_F = 5.0   # thresholds drop by this much after a heat illness
EARLIEST_START_HOUR = 5


@dataclass(frozen=True)
class HourlyWeather:
    time: datetime          # start of the hour, local
    temp_f: float
    rel_humidity: float     # percent


def heat_index_f(temp_f: float, rh: float) -> float:
    simple = 0.5 * (temp_f + 61.0 + (temp_f - 68.0) * 1.2 + rh * 0.094)
    if (simple + temp_f) / 2 < 80:
        return round(simple, 1)
    t, r = temp_f, rh
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r
          - 6.83783e-3 * t * t - 5.481717e-2 * r * r + 1.22874e-3 * t * t * r
          + 8.5282e-4 * t * r * r - 1.99e-6 * t * t * r * r)
    if r < 13 and 80 <= t <= 112:
        hi -= ((13 - r) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
    elif r > 85 and 80 <= t <= 87:
        hi += ((r - 85) / 10) * ((87 - t) / 5)
    return round(hi, 1)


def _window(hours: list[HourlyWeather], start: datetime, duration_min: float) -> list[HourlyWeather]:
    end = start + timedelta(minutes=duration_min)
    return [h for h in hours
            if h.time < end and h.time + timedelta(hours=1) > start]


def _limits(kind: str, after_heat_illness: bool) -> tuple[float, float]:
    caution, nogo = THRESHOLDS[kind]
    if after_heat_illness:
        caution, nogo = caution - HEAT_ILLNESS_OFFSET_F, nogo - HEAT_ILLNESS_OFFSET_F
    return caution, nogo


def max_heat_index(hours: list[HourlyWeather], start: datetime, duration_min: float) -> float:
    window = _window(hours, start, duration_min)
    if not window:
        raise ValueError("forecast does not cover the planned session")
    return max(heat_index_f(h.temp_f, h.rel_humidity) for h in window)


def go_no_go(hours: list[HourlyWeather], start: datetime, duration_min: float,
             kind: str = "easy", after_heat_illness: bool = False) -> Flag | None:
    caution, nogo = _limits(kind, after_heat_illness)
    peak = max_heat_index(hours, start, duration_min)
    if peak < caution:
        return None
    better = best_start(hours, start, duration_min, caution)
    hint = (f" Start by {better:%-I:%M %p} to stay under {caution:.0f}°F."
            if better and better != start else
            " No start time today stays under the limit; move it indoors or to another day.")
    sev = Severity.STOP if peak >= nogo else Severity.WARN
    word = "NO-GO" if sev is Severity.STOP else "Caution"
    return Flag("heat", sev,
                f"{word}: heat index peaks at {peak:.0f}°F during this {kind} session "
                f"starting {start:%-I:%M %p}.{hint}",
                {"peak_heat_index_f": peak, "caution_f": caution, "no_go_f": nogo,
                 "suggested_start": better.isoformat() if better else None})


def best_start(hours: list[HourlyWeather], planned: datetime, duration_min: float,
               limit_f: float) -> datetime | None:
    """Latest start on the same day, no later than planned, that keeps the
    whole session under ``limit_f``. None if no such start exists."""
    t = planned.replace(minute=0, second=0, microsecond=0)
    earliest = planned.replace(hour=EARLIEST_START_HOUR, minute=0, second=0, microsecond=0)
    while t >= earliest:
        try:
            if max_heat_index(hours, t, duration_min) < limit_f:
                return t
        except ValueError:
            pass
        t -= timedelta(minutes=30)
    return None
