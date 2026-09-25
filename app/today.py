"""Assemble the Today view: what the phone app shows each morning."""
from __future__ import annotations

from datetime import date, timedelta

from app import db
from app.health.state import gate as health_gate
from app.ingest import evaluate
from app.periodization.phases import NoPhaseDefined, phase_for

MI = evaluate.MI


def _session(r: dict) -> dict:
    return {"id": r["id"], "date": r["plan_date"], "sport": r["sport"], "title": r["title"],
            "distance_mi": r["distance_mi"], "duration_min": r["duration_min"],
            "max_zone": r["max_zone"], "is_long": r["is_long"], "structure": r["structure"],
            "notes": r["notes"], "status": r["status"], "activity_id": r["activity_id"]}


def build(conn, today: date, next_days: int = 4) -> dict:
    phases = db.load_phases(conn)
    try:
        p = phase_for(phases, today)
        phase = {"name": p.name, "kind": p.kind, "start": p.start_date, "end": p.end_date, "note": p.note}
    except NoPhaseDefined as e:
        phase = {"error": str(e)}

    signals = evaluate.morning_signals(conn, today)
    g = health_gate(db.open_episode(conn), signals, today)

    plans = conn.execute(
        "select * from planned_workouts where plan_date between %s and %s and status <> 'superseded' "
        "order by plan_date, id", (today, today + timedelta(days=next_days))).fetchall()
    flags = conn.execute(
        """select f.* from flags f where f.flag_date between %s and %s order by f.created_at""",
        (today - timedelta(days=7), today + timedelta(days=next_days))).fetchall()
    by_plan: dict[int, list] = {}
    for f in flags:
        if f["subject_type"] == "planned_workout":
            by_plan.setdefault(f["subject_id"], []).append(f)

    today_sessions, upcoming = [], {}
    for r in plans:
        s = _session(r) | {"flags": [{"kind": f["kind"], "severity": f["severity"], "message": f["message"]}
                                     for f in by_plan.get(r["id"], [])]}
        if not g.prescriptions_allowed:
            s = {"id": r["id"], "date": r["plan_date"], "suppressed": True}
        (today_sessions if r["plan_date"] == today else upcoming.setdefault(r["plan_date"], [])).append(s)

    recent = conn.execute(
        """select a.id, a.local_date, a.sport, a.title, a.distance_m, a.duration_s, a.avg_hr,
                  a.decoupling, a.load_trimp from activities a
           where a.local_date >= %s order by a.start_local desc""", (today - timedelta(days=7),)).fetchall()
    act_flags: dict[int, list] = {}
    for f in flags:
        if f["subject_type"] == "activity":
            act_flags.setdefault(f["subject_id"], []).append(
                {"kind": f["kind"], "severity": f["severity"], "message": f["message"]})

    races = conn.execute(
        "select name, race_date, distance, priority, goal_time::text as goal_time, "
        "stretch_time::text as stretch_time, status, decision_date from races "
        "where race_date >= %s order by priority", (today,)).fetchall()
    last = conn.execute("select kind, finished_at, ok from sync_runs where finished_at is not null "
                        "order by finished_at desc limit 1").fetchone()
    rec = conn.execute("select * from recovery where day <= %s order by day desc limit 1", (today,)).fetchone()
    return {
        "today": today,
        "phase": phase,
        "health": {"status": g.status.value, "prescriptions_allowed": g.prescriptions_allowed,
                   "intensity_ceiling": g.intensity_ceiling, "volume_multiplier": g.volume_multiplier,
                   "reasons": list(g.reasons)},
        "readiness": rec and {"day": rec["day"], "readiness": rec["readiness"], "sleep_score": rec["sleep_score"],
                              "resting_hr": rec["resting_hr"], "hrv_ms": rec["hrv_ms"],
                              "temp_deviation_c": rec["temp_deviation_c"],
                              "resting_hr_baseline": signals.resting_hr_baseline},
        "sessions": today_sessions,
        "next_days": [{"date": d, "sessions": s} for d, s in sorted(upcoming.items())],
        "long_run_gate": evaluate.upcoming_gate(conn, today),
        "recent_activities": [{
            "id": a["id"], "date": a["local_date"], "sport": a["sport"], "title": a["title"],
            "mi": round((a["distance_m"] or 0) / MI, 2), "min": round((a["duration_s"] or 0) / 60),
            "avg_hr": a["avg_hr"], "decoupling": a["decoupling"], "load": a["load_trimp"],
            "flags": act_flags.get(a["id"], [])} for a in recent],
        "races": [r | {"days_until": (r["race_date"] - today).days} for r in races],
        "last_sync": last,
    }


def plan(conn, start: date, days: int) -> list[dict]:
    """Planned sessions day by day, with matched actuals, for the Plan tab."""
    rows = conn.execute(
        """select w.*, a.distance_m as act_m, a.avg_hr as act_hr, a.duration_s as act_s
           from planned_workouts w left join activities a on a.id = w.activity_id
           where w.plan_date between %s and %s and w.status <> 'superseded'
           order by w.plan_date, w.id""", (start, start + timedelta(days=days - 1))).fetchall()
    out: dict[date, list] = {start + timedelta(days=i): [] for i in range(days)}
    for r in rows:
        s = _session(r)
        if r["act_m"] is not None:
            s["actual"] = {"mi": round(r["act_m"] / MI, 2), "avg_hr": r["act_hr"],
                           "min": round((r["act_s"] or 0) / 60)}
        out[r["plan_date"]].append(s)
    return [{"date": d, "sessions": v} for d, v in out.items()]


def trends(conn, today: date, weeks: int = 10) -> dict:
    """Weekly run miles (actual vs planned) and bench estimated 1RM by session."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    actual = {r["wk"]: r["mi"] for r in conn.execute(
        """select date_trunc('week', local_date)::date as wk, sum(distance_m) / %s as mi
           from activities where sport = 'run' and local_date >= %s group by 1""", (MI, start)).fetchall()}
    planned = {r["wk"]: r["mi"] for r in conn.execute(
        """select date_trunc('week', plan_date)::date as wk, sum(distance_mi) as mi
           from planned_workouts where sport = 'run' and plan_date >= %s and status <> 'superseded'
           group by 1""", (start,)).fetchall()}
    wk = [start + timedelta(weeks=i) for i in range(weeks + 1)]
    bench = conn.execute(
        """select performed_on as day, max(weight_lb * (1 + reps / 30.0)) as e1rm, max(weight_lb) as top
           from strength_sets where exercise ilike 'bench press%%' and not excluded
             and coalesce(set_type, 'normal') not in ('warmup') and reps between 1 and 12
           group by 1 order by 1""").fetchall()
    return {
        "weekly_run_mi": [{"week": w, "actual": round(actual.get(w) or 0, 1),
                           "planned": round(planned[w], 1) if w in planned else None} for w in wk],
        "bench": [{"day": b["day"], "e1rm": round(b["e1rm"], 1), "top": b["top"]} for b in bench],
    }
