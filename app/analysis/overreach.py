"""Prospective overreach checks.

Each check runs against a *planned* session before it happens, as well as
against what was actually done. The Sep 13, 2026 long run would have
tripped the first three:

  * long-run jump      12.5 mi planned vs 10.05 longest in prior 4 weeks (+24%)
  * session share      one session ~44-50% of the week's load
  * decoupling         HR 133 -> 153 at equal pace (~7% half-vs-half, limit 5%)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.analysis.flags import Flag, Severity

LONG_RUN_JUMP_WARN = 0.10
LONG_RUN_JUMP_STOP = 0.20
LONG_RUN_WINDOW_DAYS = 28
SESSION_SHARE_WARN = 0.35
SESSION_SHARE_STOP = 0.45
DECOUPLING_WARN = 0.05
DECOUPLING_STOP = 0.08
EASY_PACE_TOLERANCE_S = 10
WEEKLY_RAMP_WARN = 0.10


def long_run_jump(planned_mi: float, planned_on: date,
                  history: list[tuple[date, float]]) -> Flag | None:
    """history: (date, miles) of completed runs."""
    window_start = planned_on - timedelta(days=LONG_RUN_WINDOW_DAYS)
    prior = [mi for d, mi in history if window_start <= d < planned_on]
    if not prior:
        return Flag("long_run_jump", Severity.WARN,
                    f"No runs in the {LONG_RUN_WINDOW_DAYS} days before {planned_on}; "
                    f"a {planned_mi:.1f} mi run has no recent base to compare against.",
                    {"planned_mi": planned_mi})
    longest = max(prior)
    jump = (planned_mi - longest) / longest
    if jump <= LONG_RUN_JUMP_WARN:
        return None
    sev = Severity.STOP if jump > LONG_RUN_JUMP_STOP else Severity.WARN
    cap = round(longest * (1 + LONG_RUN_JUMP_WARN), 1)
    return Flag("long_run_jump", sev,
                f"{planned_mi:.1f} mi is +{jump:.0%} over your longest run in the last "
                f"4 weeks ({longest:.2f} mi). Cap it at {cap} mi.",
                {"planned_mi": planned_mi, "prior_longest_mi": longest,
                 "jump": round(jump, 3), "suggested_cap_mi": cap})


def session_share_flag(share: float, label: str = "this session") -> Flag | None:
    if share <= SESSION_SHARE_WARN:
        return None
    sev = Severity.STOP if share > SESSION_SHARE_STOP else Severity.WARN
    return Flag("session_load_share", sev,
                f"{label} is {share:.0%} of the week's training load "
                f"(limit {SESSION_SHARE_WARN:.0%}). Spread the load or shorten it.",
                {"share": share})


@dataclass(frozen=True)
class Lap:
    distance_m: float
    duration_s: float
    avg_hr: float


def decoupling(laps: list[Lap]) -> float:
    """Pace:HR decoupling, Friel's method: compare the efficiency factor
    (speed / HR) of the first half of the session with the second half,
    split by elapsed time. Positive = HR drifted up relative to pace.
    """
    laps = [l for l in laps if l.duration_s > 0 and l.avg_hr > 0 and l.distance_m > 0]
    if len(laps) < 2:
        raise ValueError("need at least two laps with HR and distance")
    total = sum(l.duration_s for l in laps)
    half = total / 2
    halves = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]   # distance, duration, hr*duration
    elapsed = 0.0
    for l in laps:
        # Split a lap that straddles the midpoint proportionally.
        first_part = max(0.0, min(l.duration_s, half - elapsed))
        for i, dur in ((0, first_part), (1, l.duration_s - first_part)):
            if dur <= 0:
                continue
            frac = dur / l.duration_s
            halves[i][0] += l.distance_m * frac
            halves[i][1] += dur
            halves[i][2] += l.avg_hr * dur
        elapsed += l.duration_s
    ef = []
    for dist, dur, hr_dur in halves:
        ef.append((dist / dur) / (hr_dur / dur))
    return round((ef[0] - ef[1]) / ef[0], 4)


def decoupling_flag(value: float) -> Flag | None:
    if value <= DECOUPLING_WARN:
        return None
    sev = Severity.STOP if value > DECOUPLING_STOP else Severity.WARN
    return Flag("decoupling", sev,
                f"Heart rate decoupled {value:.1%} from pace in the second half "
                f"(aerobic limit {DECOUPLING_WARN:.0%}). Don't lengthen the next long run.",
                {"decoupling": value})


def easy_too_fast(actual_pace_s: float, prescribed_fastest_s: float) -> Flag | None:
    """Paces in seconds per mile. prescribed_fastest_s is the fast end of the
    easy range (e.g. 10:15/mi = 615)."""
    if actual_pace_s >= prescribed_fastest_s - EASY_PACE_TOLERANCE_S:
        return None
    diff = prescribed_fastest_s - actual_pace_s
    return Flag("easy_too_fast", Severity.WARN,
                f"Easy run at {fmt_pace(actual_pace_s)}/mi, {int(diff)}s/mi faster than the "
                f"prescribed easy range starts ({fmt_pace(prescribed_fastest_s)}/mi).",
                {"actual_pace_s": actual_pace_s, "prescribed_fastest_s": prescribed_fastest_s})


def weekly_ramp(planned_mi: float, prior_weeks_actual_mi: list[float]) -> Flag | None:
    """Planned weekly volume vs the highest of the last 3 completed weeks."""
    recent = [m for m in prior_weeks_actual_mi[-3:] if m > 0]
    if not recent:
        return None
    base = max(recent)
    ramp = (planned_mi - base) / base
    if ramp <= WEEKLY_RAMP_WARN:
        return None
    return Flag("weekly_ramp", Severity.WARN,
                f"Planned {planned_mi:.1f} mi is +{ramp:.0%} over your biggest recent week "
                f"({base:.1f} mi).",
                {"planned_mi": planned_mi, "recent_max_mi": base, "ramp": round(ramp, 3)})


def fmt_pace(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def parse_pace(text: str) -> int:
    m, s = text.strip().split(":")
    return int(m) * 60 + int(s)
