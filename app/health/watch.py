"""Relapse watch for the return after the mono hold (outside review, Card 1).

Three transparent signals, each a reason to ease off, never a diagnosis:

  rhr          7-day mean resting HR >= the pre-illness baseline + 5 bpm,
               three days running
  decoupling   pace:HR decoupling > 5% on two easy runs of 30+ min within 7 days
  hrv          7-day mean of ln(nightly HRV) below the 60-day mean - 0.5 SD,
               two nights running (needs 21+ nights outside the hold; until
               then it says it is still learning)

One signal is shown on Today and changes nothing. Two different signals inside
7 days put the day and the next under CAUTION (Z2 only, no long-run growth).
Nothing here can open a hold. In the 3 days after a time-zone change of 5+
hours, the RHR and HRV signals are shown but don't count: jet lag moves both.

Thresholds are conservative coaching defaults (evidence grade C/D, no trial on
post-mono return); loosen RHR to +7 if it fires on most days in the first weeks.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

RHR_RISE = 5
RHR_DAYS = 3
DECOUPLING = 0.05
DECOUPLING_RUNS = 2
DECOUPLING_MIN_S = 30 * 60
HRV_BASELINE_DAYS = 60
HRV_MIN_NIGHTS = 21
HRV_SD = 0.5
HRV_DAYS = 2
WINDOW_DAYS = 7
CAUTION_SIGNALS = 2
CAUTION_DAYS = 2           # the trigger day and the next
TRAVEL_TZ_HOURS = 5
TRAVEL_GRACE_DAYS = 3


@dataclass(frozen=True)
class Watch:
    notes: tuple[str, ...]          # what to show (one line per signal seen in the last 7 days)
    caution: str | None             # set when two signals together call for CAUTION
    learning_hrv: bool = False


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def rhr_days(rhr: dict[date, float], baseline: int | None, days: list[date]) -> set[date]:
    """Days on which the 7-day mean had been >= baseline + 5 for 3 days running."""
    if baseline is None:
        return set()

    def high(d):
        vals = [rhr.get(d - timedelta(days=i)) for i in range(7)]
        m = _mean(vals)
        return m is not None and len([v for v in vals if v is not None]) >= 4 and m >= baseline + RHR_RISE
    return {d for d in days if all(high(d - timedelta(days=i)) for i in range(RHR_DAYS))}


def hrv_days(hrv: dict[date, float], excluded: set[date], days: list[date]) -> tuple[set[date], bool]:
    """Days on which the 7-day ln-HRV mean sat below the baseline band for 2 nights.
    Returns (days, learning) where learning means too few nights for a baseline."""
    ln = {d: math.log(v) for d, v in hrv.items() if v and v > 0}
    learning = True

    def low(d):
        nonlocal learning
        base = [ln[x] for x in (d - timedelta(days=i) for i in range(1, HRV_BASELINE_DAYS + 1))
                if x in ln and x not in excluded]
        if len(base) < HRV_MIN_NIGHTS:
            return False
        learning = False
        week = _mean([ln.get(d - timedelta(days=i)) for i in range(7)])
        return week is not None and week < statistics.fmean(base) - HRV_SD * statistics.pstdev(base)
    out = {d for d in days if all(low(d - timedelta(days=i)) for i in range(HRV_DAYS))}
    return out, learning


def decoupling_days(runs: list[tuple[date, float]], days: list[date]) -> set[date]:
    """The day of the 2nd qualifying easy run inside 7 days (runs: date, decoupling)."""
    bad = sorted(d for d, dec in runs if dec is not None and dec > DECOUPLING)
    out = set()
    for i in range(DECOUPLING_RUNS - 1, len(bad)):
        if (bad[i] - bad[i - DECOUPLING_RUNS + 1]).days < WINDOW_DAYS and bad[i] in days:
            out.add(bad[i])
    return out


def jet_lag_days(stops: list[dict], home_tz: str, days: list[date]) -> set[date]:
    """Days within 3 days after arriving somewhere 5+ hours away from the day before."""
    from app import travel

    def offset(d):
        p = travel.place_for(stops, d)
        tz = p.tz_name if p.away else home_tz
        return datetime.combine(d, time(12), ZoneInfo(tz)).utcoffset().total_seconds() / 3600
    out = set()
    for d in days:
        for back in range(TRAVEL_GRACE_DAYS):
            day = d - timedelta(days=back)
            if abs(offset(day) - offset(day - timedelta(days=1))) >= TRAVEL_TZ_HOURS:
                out.add(d)
    return out


def assess(today: date, *, rhr: dict, hrv: dict, runs: list, baseline: int | None,
           hold: tuple[date, date] | None, jet_lag: set[date]) -> Watch:
    """Pure: the watch as of ``today`` from per-day data."""
    days = [today - timedelta(days=i) for i in range(WINDOW_DAYS)]
    excluded = set()
    if hold:
        excluded = {hold[0] + timedelta(days=i) for i in range((hold[1] - hold[0]).days + 1)}
    fired = {"rhr": rhr_days(rhr, baseline, days),
             "decoupling": decoupling_days(runs, days)}
    fired["hrv"], learning = hrv_days(hrv, excluded, days)
    labels = {"rhr": f"resting HR up {RHR_RISE}+ bpm on its 7-day average for {RHR_DAYS} days",
              "decoupling": "heart rate drifting up on easy runs (2 runs over 5% decoupling)",
              "hrv": "overnight HRV below your normal range for 2 nights"}
    notes, latest = [], {}
    for key, ds in fired.items():
        if not ds:
            continue
        counting = ds if key == "decoupling" else ds - jet_lag
        tail = "" if counting else " (right after a big time-zone change, so not counted)"
        notes.append(f"Watch: {labels[key]}{tail}.")
        if counting:
            latest[key] = max(counting)
    caution = None
    if len(latest) >= CAUTION_SIGNALS:
        trigger = sorted(latest.values())[-CAUTION_SIGNALS]
        if (today - trigger).days < CAUTION_DAYS:
            caution = ("Easing off for 2 days: " + " and ".join(labels[k] for k in sorted(latest)) + ".")
    return Watch(tuple(notes), caution, learning)


def load(conn, today: date) -> Watch:
    """The watch from the database (recovery, matched easy runs, travel, the hold)."""
    from app import db, travel
    from app.config import load_settings
    since = today - timedelta(days=HRV_BASELINE_DAYS + 20)
    rec = conn.execute("select day, resting_hr, hrv_ms from recovery where day between %s and %s",
                       (since, today)).fetchall()
    runs = conn.execute(
        """select w.plan_date, a.decoupling from planned_workouts w join activities a on a.id = w.activity_id
           where w.sport = 'run' and not w.is_long and coalesce(w.max_zone, 'Z2') in ('Z1', 'Z2')
             and coalesce(a.moving_s, a.duration_s) >= %s and w.plan_date between %s and %s""",
        (DECOUPLING_MIN_S, today - timedelta(days=2 * WINDOW_DAYS), today)).fetchall()
    prof = conn.execute("select resting_hr_baseline from profile where id = 1").fetchone() or {}
    ep = db.open_episode(conn, today)
    hold = (ep.started_on, ep.return_started_on or today) if ep else None
    days = [today - timedelta(days=i) for i in range(WINDOW_DAYS)]
    lag = jet_lag_days(travel.load(conn), load_settings().tz_name, days)
    return assess(today, rhr={r["day"]: r["resting_hr"] for r in rec},
                  hrv={r["day"]: r["hrv_ms"] for r in rec},
                  runs=[(r["plan_date"], r["decoupling"]) for r in runs],
                  baseline=prof.get("resting_hr_baseline"), hold=hold, jet_lag=lag)
