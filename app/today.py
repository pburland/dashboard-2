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
        "last_sync": last,
    }
