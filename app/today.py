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


def build(conn, today: date, next_days: int = 4, checkin_id: int | None = None) -> dict:
    phases = db.load_phases(conn)
    try:
        p = phase_for(phases, today)
        phase = {"name": p.name, "kind": p.kind, "start": p.start_date, "end": p.end_date, "note": p.note}
    except NoPhaseDefined as e:
        phase = {"error": str(e)}

    signals = evaluate.morning_signals(conn, today)
    from app.health import watch
    from app import fitness_tests
    from app.periodization import zones
    watched = watch.load(conn, today)
    zones.refresh(conn)
    zone_info = {"summary": zones.summary(),
                 "pending": [{"id": t["id"], "kind": t["kind"], "test_date": t["test_date"],
                              "text": fitness_tests.describe(t)} for t in fitness_tests.pending(conn)],
                 "invalid": [{"kind": t["kind"], "test_date": t["test_date"], "reason": t["reason"]}
                             for t in fitness_tests.recent_invalid(conn, today)],
                 "due": fitness_tests.due_notes(conn, today)}
    episode = db.open_episode(conn, today)
    g = health_gate(episode, signals, today)
    comeback = None
    if g.status.value == "return" and episode and episode.return_started_on:
        paused = episode.return_paused
        total = (episode.return_ends_on - episode.return_started_on).days + 1 - len(paused)
        day = (today - episode.return_started_on).days + 1 - sum(1 for d in paused if d < today)
        comeback = {"day": max(1, day), "days": total, "ends": episode.return_ends_on,
                    "volume_pct": int(round(g.volume_multiplier * 100))}

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

    # Every one of the next days is listed. A day the health gate closes shows a
    # single "health hold" entry; a day after the expected clearance shows its
    # sessions marked provisional ("if cleared").
    from app.planning import generator
    day_gate = generator.day_gate(conn, today, today)
    today_sessions = []
    upcoming: dict[date, list] = {today + timedelta(days=i): [] for i in range(1, next_days + 1)}
    for r in plans:
        s = _session(r) | {"flags": [{"kind": f["kind"], "severity": f["severity"], "message": f["message"]}
                                     for f in by_plan.get(r["id"], [])]}
        if r["plan_date"] == today:
            today_sessions.append({"id": r["id"], "date": r["plan_date"], "suppressed": True}
                                  if not g.prescriptions_allowed else s)
        elif r["status"] in ("planned", "done") and r["plan_date"] in upcoming:
            upcoming[r["plan_date"]].append(s)
    for d in upcoming:
        if not day_gate(d).prescriptions_allowed:
            upcoming[d] = [{"date": d, "suppressed": True}]

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
        "where race_date >= %s and status not in ('dropped', 'deferred') order by priority", (today,)).fetchall()
    last = conn.execute("select kind, finished_at, ok from sync_runs where finished_at is not null "
                        "order by finished_at desc limit 1").fetchone()
    rec = conn.execute("select * from recovery where day <= %s order by day desc limit 1", (today,)).fetchone()
    from app import travel
    from app.planning import timing
    here = travel.place_for(travel.load(conn), today)
    days = [{"date": today, "sessions": today_sessions}] + \
           [{"date": d, "sessions": s} for d, s in sorted(upcoming.items())]
    timing_note = timing.annotate(conn, days, today) if g.prescriptions_allowed else None
    from app import strength
    strength.attach(conn, days)
    from app import checkins, nutrition
    prof = conn.execute("select rmr_kcal from profile where id = 1").fetchone() or {}
    body = conn.execute("select day, weight_lb, bf_pct, lean_lb, fat_lb, source from body_metrics "
                        "where weight_lb is not null and day <= %s order by day desc limit 1", (today,)).fetchone()
    comp = conn.execute("select day, weight_lb, bf_pct, lean_lb, fat_lb from body_metrics where fat_lb is not null "
                        "and day <= %s order by day desc limit 1", (today,)).fetchone()
    if body and comp and body.get("fat_lb") is None:
        # A plain weigh-in: show the latest scan's composition, dated, alongside today's weight.
        body = dict(body) | {"bf_pct": comp["bf_pct"], "lean_lb": comp["lean_lb"], "composition_day": comp["day"]}
    deficit_goal = bool(conn.execute("select 1 from goals where kind = 'body_comp' and status = 'active'").fetchone())
    plan = (conn.execute("select target from goals where name = 'Daily targets'").fetchone() or {}) \
        .get("target", {}) or {}
    ffm = ((comp["weight_lb"] - comp["fat_lb"]) / 2.2046) if comp and comp.get("weight_lb") else None
    fuel = nutrition.targets(prof.get("rmr_kcal"), body and body["weight_lb"], today_sessions,
                             health=g.status.value, phase_kind=phase.get("kind"), deficit_goal=deficit_goal,
                             day=today, plan=plan.get("nutrition_plan"), ffm_kg=ffm)
    who = conn.execute("select name, assistant_name from profile where id = 1").fetchone() or {}
    return {
        "today": today,
        "athlete": {"name": who.get("name"), "assistant": who.get("assistant_name")},
        "phase": phase,
        "where": {"place": here.name, "away": here.away, "sports": list(here.sports or []), "note": here.note},
        "health": {"status": g.status.value, "prescriptions_allowed": g.prescriptions_allowed,
                   "intensity_ceiling": g.intensity_ceiling, "volume_multiplier": g.volume_multiplier,
                   "reasons": list(g.reasons), "watch": list(watched.notes), "comeback": comeback,
                   "watch_learning_hrv": watched.learning_hrv},
        "readiness": rec and {"day": rec["day"], "readiness": rec["readiness"], "sleep_score": rec["sleep_score"],
                              "resting_hr": rec["resting_hr"], "hrv_ms": rec["hrv_ms"],
                              "temp_deviation_c": rec["temp_deviation_c"],
                              "resting_hr_baseline": signals.resting_hr_baseline},
        "sessions": today_sessions,
        "zones": zone_info,
        "next_days": [{"date": d, "sessions": s} for d, s in sorted(upcoming.items())],
        "long_run_gate": evaluate.upcoming_gate(conn, today),
        "recent_activities": [{
            "id": a["id"], "date": a["local_date"], "sport": a["sport"], "title": a["title"],
            "mi": round((a["distance_m"] or 0) / MI, 2), "min": round((a["duration_s"] or 0) / 60),
            "avg_hr": a["avg_hr"], "decoupling": a["decoupling"], "load": a["load_trimp"],
            "flags": act_flags.get(a["id"], [])} for a in recent],
        "races": [r | {"days_until": (r["race_date"] - today).days} for r in races],
        "timing_note": timing_note,
        "pending_checkin": checkins.pending(conn, today, checkin_id),
        "proposals": conn.execute(
            "select id, source, explanation as changes, reason, flags from plan_proposals "
            "where status = 'pending' and source = 'system' order by created_at desc limit 3").fetchall(),
        "fuel": fuel,
        "body": body,
        "last_sync": last,
    }


def plan(conn, start: date, days: int, today: date | None = None) -> dict:
    """Planned sessions day by day, with matched actuals and the best time
    for each upcoming one, for the Plan tab."""
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
    result = [{"date": d, "sessions": v} for d, v in out.items()]
    from app import strength
    strength.attach(conn, result)
    note = None
    if today is not None:
        from app.planning import timing
        note = timing.annotate(conn, result, today)
    return {"days": result, "timing_note": note}


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
    from app import checkins, strength
    goals = {label: pts for label, _, pts in strength.lift_checkpoints(conn)}
    bench_goal = max((v for _, v in goals.get("Bench", [])), default=None)
    return {
        "load": load_trend(conn, today),
        "weight": weight_trend(conn, today),
        "efficiency": efficiency_trend(conn, today),
        "bench_goal": bench_goal,
        "rpe7": checkins.rpe_trend(conn, start, today),
        "weekly_run_mi": [{"week": w, "actual": round(actual.get(w) or 0, 1),
                           "planned": round(planned[w], 1) if w in planned else None} for w in wk],
        "bench": [{"day": b["day"], "e1rm": round(b["e1rm"], 1), "top": b["top"]} for b in bench],
    }


# ── trends that change a decision (outside review, Card 11) ────────────────
LOAD_DAYS = 112                     # what the chart shows (16 weeks)
EF_HR = 140                         # pace is shown at this heart rate


def load_trend(conn, today: date) -> dict:
    """Fitness (42-day average load), fatigue (7-day) and form (fitness - fatigue),
    from each workout's heart-rate load (TRIMP) until per-sport TSS is built.
    Seeded from 12 months back so fitness starts honestly low, not at zero."""
    seed = today - timedelta(days=365)
    daily = {r["local_date"]: r["load"] for r in conn.execute(
        """select local_date, sum(load_trimp) as load from activities where local_date between %s and %s
           and load_trimp is not null group by 1""", (seed, today)).fetchall()}
    ctl = atl = 0.0
    out = []
    d = seed
    while d <= today:
        x = daily.get(d) or 0.0
        ctl += (x - ctl) / 42
        atl += (x - atl) / 7
        if d > today - timedelta(days=LOAD_DAYS):
            out.append({"day": d, "fitness": round(ctl, 1), "fatigue": round(atl, 1), "form": round(ctl - atl, 1)})
        d += timedelta(days=1)
    return {"source": "heart-rate load (TRIMP); switches to per-sport TSS when it's built", "days": out}


def weight_trend(conn, today: date) -> dict:
    rows = conn.execute("select day, weight_lb from body_metrics where weight_lb is not null and day between %s and %s "
                        "order by day", (today - timedelta(days=LOAD_DAYS + 7), today)).fetchall()
    w = {r["day"]: r["weight_lb"] for r in rows}
    out = []
    for i in range(LOAD_DAYS):
        d = today - timedelta(days=LOAD_DAYS - 1 - i)
        week = [w[x] for x in (d - timedelta(days=k) for k in range(7)) if x in w]
        if len(week) >= 3:
            out.append({"day": d, "avg7": round(sum(week) / len(week), 1), "weighed": w.get(d)})
    return {"days": out}


def efficiency_trend(conn, today: date) -> dict:
    """Pace at 140 bpm on easy runs: flat (< 15 m climbing per mile), cool (< 75°F when the
    weather is known), 20+ minutes. Each run gives speed per heartbeat (efficiency factor);
    the line is its 4-week rolling mean, shown as a pace at 140 bpm."""
    rows = conn.execute(
        """select local_date, distance_m, coalesce(moving_s, duration_s) as secs, avg_hr, elevation_gain_m, weather
           from activities where sport = 'run' and local_date between %s and %s and avg_hr > 0
             and distance_m > 1609 and coalesce(moving_s, duration_s) >= 1200 order by local_date""",
        (today - timedelta(days=LOAD_DAYS + 28), today)).fetchall()
    runs = []
    for r in rows:
        miles = r["distance_m"] / MI
        if (r["elevation_gain_m"] or 0) / miles >= 15:
            continue
        temp = (r["weather"] or {}).get("temp_f") if isinstance(r["weather"], dict) else None
        if temp is not None and temp >= 75:
            continue
        if r["avg_hr"] > 160:                                  # not an easy run
            continue
        ef = (r["distance_m"] / r["secs"]) / r["avg_hr"]       # m/s per bpm
        runs.append((r["local_date"], ef))
    out = []
    for d, ef in runs:
        if d <= today - timedelta(days=LOAD_DAYS):
            continue
        window = [e for x, e in runs if d - timedelta(days=28) < x <= d]
        roll = sum(window) / len(window)
        out.append({"day": d, "pace_s": round(MI / (ef * EF_HR)), "rolling_pace_s": round(MI / (roll * EF_HR))})
    return {"hr": EF_HR, "runs": out}


def season(conn, today: date) -> dict:
    """One page: phases, races, tests, the return, checkpoints, calorie blocks, lift checkpoints."""
    from app import checkpoints, strength
    phases = conn.execute("select name, kind, start_date, end_date from phases where end_date >= %s "
                          "order by start_date", (today - timedelta(days=14),)).fetchall()
    races = conn.execute("select name, race_date, distance, priority, status from races "
                         "where status not in ('dropped', 'deferred') and race_date >= %s order by race_date",
                         (today,)).fetchall()
    events = conn.execute("select event_date, sport, kind, title from plan_events where event_date >= %s "
                          "order by event_date", (today,)).fetchall()
    ep = db.open_episode(conn, today)
    ret = ({"start": ep.return_started_on, "end": ep.return_ends_on}
           if ep and ep.return_started_on and ep.return_ends_on and ep.return_ends_on >= today else None)
    plan = (conn.execute("select target from goals where name = 'Daily targets'").fetchone() or {}).get("target") or {}
    blocks = [b for b in (plan.get("nutrition_plan") or {}).get("deficit_blocks", []) if b["to"] >= today.isoformat()]
    cps = [{"date": c["date"], "name": c["name"]} for c in checkpoints.CHECKPOINTS if c["date"] >= today]
    lifts = [{"lift": label, "date": d, "lb": v} for label, _, pts in strength.lift_checkpoints(conn)
             for d, v in pts if d >= today]
    return {"today": today, "phases": phases, "races": races, "events": events, "return": ret,
            "deficit_blocks": blocks, "checkpoints": cps, "lift_checkpoints": lifts,
            "undecided": "Puerto Rico (Mar 14) or Texas (Apr 4): undecided; the plan builds to the earlier date"}
