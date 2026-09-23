"""Plan validator: every planned week passes through here before it is shown.

Felipe's build let the language model write prescriptions and trusted the
prompt to respect health and load limits. Here code decides: the health
gate runs first, then each planned session is checked against the
overreach rules. The model may explain the result but cannot override it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.analysis import overreach
from app.analysis.flags import Flag, Severity
from app.analysis.load import estimate_planned_load, session_share
from app.health.state import RETURN_LONG_RUN_CAP, Gate, Status
from app.periodization.zones import at_or_below


@dataclass(frozen=True)
class PlannedSession:
    date: date
    sport: str                   # run | bike | swim | strength | ...
    title: str
    duration_min: float
    zone: str = "Z2"             # highest zone the session reaches
    distance_mi: float | None = None
    is_long: bool = False
    heavy_lower: bool = False    # strength sessions only


@dataclass(frozen=True)
class History:
    runs: list[tuple[date, float]] = field(default_factory=list)   # (date, miles)
    weekly_run_mi: list[float] = field(default_factory=list)       # completed weeks, oldest first


@dataclass(frozen=True)
class WeekVerdict:
    sessions: list[PlannedSession]
    flags: dict[int, list[Flag]]     # index into sessions -> flags
    week_flags: list[Flag]
    suppressed: bool                 # True when a health hold removed everything


def validate_week(sessions: list[PlannedSession], history: History,
                  gate: Gate) -> WeekVerdict:
    if not gate.prescriptions_allowed:
        return WeekVerdict([], {}, [Flag("health_hold", Severity.STOP, r) for r in gate.reasons], True)

    flags: dict[int, list[Flag]] = {i: [] for i in range(len(sessions))}
    week_flags: list[Flag] = []

    loads = [estimate_planned_load(s.duration_min, s.zone) for s in sessions]
    pre_hold_longest = max((mi for _, mi in history.runs), default=0.0)

    for i, s in enumerate(sessions):
        f = flags[i]
        if gate.intensity_ceiling and not at_or_below(s.zone, gate.intensity_ceiling):
            f.append(Flag("intensity_cap", Severity.STOP,
                          f"{s.title} reaches {s.zone}; today's cap is {gate.intensity_ceiling} "
                          f"({gate.status.value})."))
        if s.sport == "run" and s.distance_mi:
            if s.is_long and not gate.long_run_growth_allowed and pre_hold_longest:
                ratio = RETURN_LONG_RUN_CAP if gate.status is Status.RETURN else 1.0
                cap = round(pre_hold_longest * ratio, 1)
                if s.distance_mi > cap:
                    f.append(Flag("long_run_cap", Severity.STOP,
                                  f"{s.title}: {s.distance_mi:.1f} mi is over the {cap} mi cap "
                                  f"while {gate.status.value}."))
            jump = overreach.long_run_jump(s.distance_mi, s.date, history.runs)
            if jump and s.is_long:
                f.append(jump)
        others = loads[:i] + loads[i + 1:]
        share = session_share(loads[i], others).share
        if s.is_long or share > overreach.SESSION_SHARE_WARN:
            sf = overreach.session_share_flag(share, s.title)
            if sf:
                f.append(sf)

    # Friel concurrent rule: no heavy lower-body strength within 2 days
    # before a long run or long ride.
    longs = [s for s in sessions if s.is_long and s.sport in ("run", "bike")]
    for i, s in enumerate(sessions):
        if s.sport == "strength" and s.heavy_lower:
            for l in longs:
                gap = (l.date - s.date).days
                if 0 <= gap <= 2:
                    flags[i].append(Flag("strength_before_long", Severity.WARN,
                                         f"Heavy lower-body strength {gap} day(s) before "
                                         f"{l.title}. Move it earlier in the week."))

    planned_run_mi = sum(s.distance_mi or 0 for s in sessions if s.sport == "run")
    if planned_run_mi:
        ramp = overreach.weekly_ramp(planned_run_mi, history.weekly_run_mi)
        if ramp:
            week_flags.append(ramp)

    return WeekVerdict(sessions, flags, week_flags, False)
