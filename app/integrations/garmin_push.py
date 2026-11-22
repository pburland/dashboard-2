"""Planned runs, rides and swims -> structured workouts on the Garmin calendar.

Each planned session from today on becomes one Garmin workout scheduled on its
day: a short warm-up, the main block, a cool-down. Easy sessions carry a
heart-rate range so the watch alerts when he drifts above easy; hard sessions
and tests carry none until his zones are set from the tests.

The app keeps a record of every workout it created (garmin_pushed). A re-plan
that changes, moves or removes a session updates or deletes exactly that
workout; workouts he made himself are never touched. Nothing is sent when
nothing changed, so it can run every morning.

Settings: profile.user_prefs.garmin_push = {"enabled": true, "from": "YYYY-MM-DD"}.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

log = logging.getLogger("training.garmin_push")

SPORTS = ("run", "bike", "swim")
EASY_ZONES = ("Z1", "Z2")
PREFIX = "TC"                          # marks workouts this app made


def settings(conn) -> dict:
    prefs = (conn.execute("select user_prefs from profile where id = 1").fetchone() or {}).get("user_prefs") or {}
    return {"enabled": False, "from": None} | (prefs.get("garmin_push") or {})


def fingerprint(s: dict) -> str:
    keys = ("plan_date", "sport", "title", "duration_min", "distance_mi", "max_zone")
    d = {k: str(s.get(k)) for k in keys}
    if (s.get("max_zone") or "Z2") in EASY_ZONES and s.get("sport") in ("run", "bike"):
        from app.periodization import zones
        lo, hi, provisional = zones.easy_hr_range(s["sport"])
        if not provisional:                 # tested zones changed -> re-send the workout
            d["hr"] = f"{lo}-{hi}"
    raw = json.dumps(d, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _test_steps(sport: str):
    """Fitness tests split so the app can read them: the run's 30 minutes as 10 + 20
    (LTHR is the last 20), the bike's 20-minute effort as its own lap."""
    from garminconnect.workout import create_cooldown_step, create_interval_step, create_recovery_step, create_warmup_step
    if sport == "run":
        plan = [(create_warmup_step, 900), (create_interval_step, 600), (create_interval_step, 1200),
                (create_cooldown_step, 300)]
    elif sport == "bike":
        plan = [(create_warmup_step, 1200), (create_interval_step, 300), (create_recovery_step, 600),
                (create_interval_step, 1200), (create_cooldown_step, 600)]
    else:
        return None
    return [f(secs, i + 1) for i, (f, secs) in enumerate(plan)]


def build(s: dict) -> dict:
    """The Garmin workout JSON for one planned session (dict with planned_workouts columns)."""
    from garminconnect.workout import (CustomHeartRateTarget, CyclingWorkout, RunningWorkout, SwimmingWorkout,
                                       WorkoutSegment, create_cooldown_step, create_interval_step,
                                       create_targeted_interval_step, create_warmup_step)
    sport, zone = s["sport"], s.get("max_zone") or "Z2"
    total = int(round((s.get("duration_min") or 30) * 60))
    warm = 300 if total >= 25 * 60 else 0
    cool = 180 if total >= 25 * 60 else 0
    main = max(300, total - warm - cool)
    test = ":test#" in str((s.get("structure") or {}).get("gen_key") or "")
    steps = _test_steps(sport) if test else None
    if steps:
        total = int(sum(st.endConditionValue for st in steps))
    else:
        steps, order = [], 1
        if warm:
            steps.append(create_warmup_step(warm, order))
            order += 1
        if zone in EASY_ZONES and sport in ("run", "bike"):
            from app.periodization import zones
            floor, cap, _ = zones.easy_hr_range(sport)
            steps.append(create_targeted_interval_step(main, order, CustomHeartRateTarget(lower_limit=floor,
                                                                                          upper_limit=cap)))
        else:
            steps.append(create_interval_step(main, order))
        order += 1
        if cool:
            steps.append(create_cooldown_step(cool, order))
    cls = {"run": RunningWorkout, "bike": CyclingWorkout, "swim": SwimmingWorkout}[sport]
    proto = cls(workoutName="x", estimatedDurationInSecs=total, workoutSegments=[])
    day = s["plan_date"]
    detail = (s.get("structure") or {}).get("brief") or ""
    notes = s.get("notes") or ""
    w = cls(workoutName=f"{PREFIX} {day:%a %b %-d} - {s['title']}"[:250], estimatedDurationInSecs=total,
            workoutSegments=[WorkoutSegment(segmentOrder=1, sportType=proto.sportType, workoutSteps=steps)],
            description=" ".join(x for x in (detail, notes, "(Sent by the training app.)") if x)[:1000])
    return w.to_dict()


def _planned(conn, start: date, end: date) -> list[dict]:
    return conn.execute(
        """select id, plan_date, sport, title, duration_min, distance_mi, max_zone, structure, notes
           from planned_workouts where plan_date between %s and %s and status = 'planned'
             and sport = any(%s) order by plan_date, id""", (start, end, list(SPORTS))).fetchall()


DAYS = 7                               # only the coming week; re-plans change anything further out


def sync(conn, today: date, days: int = DAYS, client=None) -> dict:
    """Make the Garmin calendar match the plan from ``today`` for ``days`` days."""
    cfg = settings(conn)
    out = {"created": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": []}
    if not cfg.get("enabled"):
        return out | {"skipped": "turned off"}
    start = max(today, date.fromisoformat(cfg["from"])) if cfg.get("from") else today
    end = today + timedelta(days=days - 1)
    if start > end:
        return out | {"skipped": f"starts {cfg['from']}"}
    from app.periodization import zones
    zones.refresh(conn)
    rows = _planned(conn, start, end)
    if cfg.get("approval", True):                 # only weeks Patrick approved (Sunday prompt)
        from app import approval
        ok = approval.approved_weeks(conn, start, end)
        rows = [r for r in rows if approval.week_of(r["plan_date"]) in ok]
    want = {r["id"]: r for r in rows}
    have = {r["planned_workout_id"]: r for r in conn.execute(
        "select * from garmin_pushed where plan_date between %s and %s", (start, end)).fetchall()}
    # Also anything we pushed for a session that has since moved out of the window or was superseded.
    have |= {r["planned_workout_id"]: r for r in conn.execute(
        """select g.* from garmin_pushed g left join planned_workouts w on w.id = g.planned_workout_id
           where g.plan_date >= %s and (w.id is null or w.status <> 'planned' or w.plan_date <> g.plan_date)""",
        (start,)).fetchall()}
    stale = [h for pid, h in have.items() if pid not in want or fingerprint(want[pid]) != h["fingerprint"]]
    todo = [s for pid, s in want.items() if pid not in have or fingerprint(s) != have[pid]["fingerprint"]]
    if not stale and not todo:
        return out | {"unchanged": len(want)}
    g = client
    persist = None
    if g is None:
        from app.integrations import garmin
        g, _, persist = garmin.client(conn)
    for h in stale:
        try:
            g.delete_workout(h["workout_id"])
        except Exception as e:                    # already gone on Garmin is fine
            log.info("garmin delete %s: %s", h["workout_id"], e)
        conn.execute("delete from garmin_pushed where planned_workout_id = %s", (h["planned_workout_id"],))
        if h["planned_workout_id"] not in want:
            out["removed"] += 1
    for s in todo:
        try:
            made = g.upload_workout(build(s))
            wid = int(made["workoutId"])
            g.schedule_workout(wid, s["plan_date"].isoformat())
        except Exception as e:                    # one session failing never blocks the rest
            out["errors"].append(f"{s['plan_date']} {s['title']}: {type(e).__name__}: {e}"[:200])
            continue
        conn.execute("""insert into garmin_pushed (planned_workout_id, plan_date, sport, workout_id, fingerprint)
                        values (%s, %s, %s, %s, %s)""", (s["id"], s["plan_date"], s["sport"], wid, fingerprint(s)))
        out["updated" if s["id"] in have else "created"] += 1
    out["unchanged"] = len(want) - len(todo)
    conn.commit()
    if persist:
        persist()
    return out
