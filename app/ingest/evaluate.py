"""After each sync: match actuals to the plan, flag what went wrong, and
evaluate conditional sessions (the long-run go/no-go).

Everything reads the database and writes ``planned_workouts`` / ``flags``;
nothing here calls a provider.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

from app.analysis import heat, overreach
from app.analysis.flags import Flag, Severity
from app.health.state import MorningSignals

MI = 1609.344
EASY_HR_CAP = 140          # return-phase easy-run average HR cap
RHR_TOLERANCE = 5          # "within 5 bpm of baseline"
FEVER_TEMP_C = 0.5
DEFAULT_START = time(7, 0)


# ── flags ────────────────────────────────────────────────────────────────
def save_flag(conn, f: Flag, flag_date: date, subject_type: str | None, subject_id: int | None) -> None:
    conn.execute(
        """insert into flags (flag_date, kind, severity, message, subject_type, subject_id, data)
           values (%s, %s, %s, %s, %s, %s, %s::jsonb)
           on conflict (kind, flag_date, subject_type, subject_id) do update
           set severity = excluded.severity, message = excluded.message, data = excluded.data""",
        (flag_date, f.kind, f.severity.value, f.message, subject_type, subject_id,
         json.dumps(f.data, default=str)))


def fast_end_of(pace_range: str | None) -> int | None:
    """'10:45-11:30' or '10:45–11:30' -> 645 (seconds per mile of the fast end)."""
    if not pace_range:
        return None
    m = re.match(r"\s*(\d+):(\d{2})", pace_range)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


# ── plan <-> actual ──────────────────────────────────────────────────────
def match_planned(conn, since: date, until: date) -> int:
    """Attach each planned endurance session to the same-day activity of the
    same sport (longest first). Returns the number newly matched."""
    planned = conn.execute(
        """select id, plan_date, sport from planned_workouts
           where plan_date between %s and %s and activity_id is null
             and sport in ('run','bike','swim') order by plan_date, id""", (since, until)).fetchall()
    n = 0
    for p in planned:
        a = conn.execute(
            """select id from activities a where local_date = %s and sport = %s
               and not exists (select 1 from planned_workouts w where w.activity_id = a.id)
               order by distance_m desc nulls last limit 1""", (p["plan_date"], p["sport"])).fetchone()
        if a:
            conn.execute("update planned_workouts set activity_id = %s, status = 'done' where id = %s",
                         (a["id"], p["id"]))
            n += 1
    return n


def activity_flags(conn, since: date) -> int:
    """Flags on completed, matched sessions: easy too fast, HR over cap, decoupling."""
    rows = conn.execute(
        """select w.id as plan_id, w.plan_date, w.is_long, w.structure, a.id as act_id,
                  a.distance_m, a.duration_s, a.moving_s, a.avg_hr, a.decoupling
           from planned_workouts w join activities a on a.id = w.activity_id
           where w.plan_date >= %s and w.sport = 'run'""", (since,)).fetchall()
    n = 0
    for r in rows:
        s = r["structure"] or {}
        miles = (r["distance_m"] or 0) / MI
        secs = r["moving_s"] or r["duration_s"]
        found: list[Flag] = []
        if not r["is_long"] and miles > 0.5 and secs:
            fast = fast_end_of(s.get("pace"))
            if fast:
                f = overreach.easy_too_fast(secs / miles, fast)
                if f:
                    found.append(f)
        cap = s.get("hr_avg_max")
        if cap and r["avg_hr"] and r["avg_hr"] > cap:
            found.append(Flag("hr_over_cap", Severity.WARN,
                              f"Average HR {r['avg_hr']:.0f} vs a cap of {cap}.",
                              {"avg_hr": r["avg_hr"], "cap": cap}))
        if r["decoupling"] is not None:
            f = overreach.decoupling_flag(r["decoupling"])
            if f:
                found.append(f)
        for f in found:
            save_flag(conn, f, r["plan_date"], "activity", r["act_id"])
            n += 1
    return n


# ── morning signals & heat ───────────────────────────────────────────────
def profile(conn) -> dict:
    return conn.execute("select * from profile where id = 1").fetchone() or {}


def morning_signals(conn, today: date) -> MorningSignals:
    r = conn.execute("select * from recovery where day <= %s order by day desc limit 1", (today,)).fetchone()
    if not r or r["day"] < today - timedelta(days=1):
        return MorningSignals(resting_hr_baseline=profile(conn).get("resting_hr_baseline"))
    return MorningSignals(readiness=r["readiness"], resting_hr=r["resting_hr"],
                          resting_hr_baseline=profile(conn).get("resting_hr_baseline"),
                          temp_deviation_c=r["temp_deviation_c"])


def heat_checks(conn, today: date, hours: list[heat.HourlyWeather], tz) -> int:
    runs = conn.execute(
        """select id, title, planned_start, duration_min, is_long, max_zone from planned_workouts
           where plan_date = %s and sport = 'run' and status = 'planned'""", (today,)).fetchall()
    n = 0
    for r in runs:
        start = datetime.combine(today, r["planned_start"] or DEFAULT_START, tzinfo=tz)
        kind = "long" if r["is_long"] else ("quality" if r["max_zone"] not in (None, "Z1", "Z2") else "easy")
        try:
            f = heat.go_no_go(hours, start, r["duration_min"] or 45, kind=kind)
        except ValueError:
            continue
        if f:
            save_flag(conn, f, today, "planned_workout", r["id"])
            n += 1
    return n


# ── conditional long run ─────────────────────────────────────────────────
def long_run_gate(conn, plan: dict, today: date) -> dict:
    """Evaluate a planned long run whose structure carries ``go_if``.

    Conditions (each pass / fail / pending):
      1. every run since the return started averaged <= EASY_HR_CAP with
         decoupling <= 5% where measured
      2. resting HR within RHR_TOLERANCE of baseline on the last 3 mornings
      3. no fever signal (temperature +0.5°C) and no illness note since the return
    Verdict: go (all pass), fallback (any fail), pending (otherwise)."""
    target = plan["plan_date"]
    ep = conn.execute("select * from health_episodes order by started_on desc limit 1").fetchone()
    since = (ep and ep["return_started_on"]) or (target - timedelta(days=10))
    last_day = min(today, target - timedelta(days=1))
    conds = []

    runs = conn.execute(
        """select local_date, distance_m, avg_hr, decoupling from activities
           where sport = 'run' and local_date >= %s and local_date <= %s order by local_date""",
        (since, last_day)).fetchall()
    bad = [r for r in runs if (r["avg_hr"] or 0) > EASY_HR_CAP
           or (r["decoupling"] is not None and r["decoupling"] > overreach.DECOUPLING_WARN)]
    still_planned = conn.execute(
        """select count(*) as n from planned_workouts where sport = 'run' and status = 'planned'
           and plan_date >= %s and plan_date < %s""", (max(today, since), target)).fetchone()["n"]
    conds.append({
        "key": "return_runs_easy",
        "label": f"Every run since {since:%b %-d} at avg HR ≤ {EASY_HR_CAP}, no drift over 5%",
        "status": "fail" if bad else ("pending" if still_planned or not runs else "pass"),
        "detail": [{"date": r["local_date"], "mi": round((r["distance_m"] or 0) / MI, 2),
                    "avg_hr": r["avg_hr"], "decoupling": r["decoupling"]} for r in runs],
    })

    base = profile(conn).get("resting_hr_baseline")
    rec = conn.execute(
        """select day, resting_hr, temp_deviation_c from recovery where day <= %s
           order by day desc limit 3""", (last_day,)).fetchall()
    if base is None or len(rec) < 3 or any(r["resting_hr"] is None for r in rec):
        rhr_status = "pending"
    else:
        rhr_status = "fail" if any(r["resting_hr"] > base + RHR_TOLERANCE for r in rec) else "pass"
    if rhr_status == "pass" and last_day < target - timedelta(days=1):
        rhr_status = "pending"      # the 3 mornings that count haven't all happened yet
    conds.append({"key": "rhr_normal", "label": f"Resting HR within {RHR_TOLERANCE} of baseline ({base}) for 3 mornings",
                  "status": rhr_status, "detail": [{"day": r["day"], "rhr": r["resting_hr"]} for r in rec]})

    fever = [r for r in rec if (r["temp_deviation_c"] or 0) >= FEVER_TEMP_C]
    notes = conn.execute("select count(*) as n from weekly_notes where type = 'illness' and note_date >= %s",
                         (since,)).fetchone()["n"]
    conds.append({"key": "no_fever", "label": "No fever signal or illness note",
                  "status": "fail" if fever or notes else ("pending" if len(rec) < 3 else "pass"),
                  "detail": [{"day": r["day"], "temp_deviation_c": r["temp_deviation_c"]} for r in rec]})

    statuses = {c["status"] for c in conds}
    verdict = "fallback" if "fail" in statuses else ("go" if statuses == {"pass"} else "pending")
    s = plan["structure"] or {}
    return {"plan_id": plan["id"], "date": target, "planned_mi": plan["distance_mi"],
            "fallback_mi": s.get("fallback_mi"), "verdict": verdict, "conditions": conds}


def upcoming_gate(conn, today: date, horizon_days: int = 8) -> dict | None:
    plan = conn.execute(
        """select id, plan_date, distance_mi, structure from planned_workouts
           where plan_date between %s and %s and structure ? 'go_if' and status = 'planned'
           order by plan_date limit 1""", (today, today + timedelta(days=horizon_days))).fetchone()
    return long_run_gate(conn, plan, today) if plan else None
