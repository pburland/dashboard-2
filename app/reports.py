"""Weekly report: what happened, what it means, and how next week changes.

Every Sunday evening (and on demand) the week Monday-Sunday is summarized
from the data, a factor for next week's volume is decided by rules, the
next three weeks are re-planned with it (week one firm, the rest preview),
and a model writes a short narrative. The model explains; it never sets the
numbers.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from statistics import mean

from app import db
from app.health.state import MorningSignals, Status, gate

MI = 1609.344


def summarize(conn, ws: date) -> dict:
    we = ws + timedelta(days=6)
    planned = conn.execute(
        """select w.plan_date, w.sport, w.title, w.distance_mi, w.duration_min, w.status, w.activity_id,
                  w.is_long, a.distance_m as act_m
           from planned_workouts w left join activities a on a.id = w.activity_id
           where w.plan_date between %s and %s and w.status <> 'superseded' order by w.plan_date""",
        (ws, we)).fetchall()
    acts = conn.execute(
        """select local_date, sport, title, distance_m, duration_s, avg_hr, decoupling, load_trimp
           from activities where local_date between %s and %s order by local_date""", (ws, we)).fetchall()
    strength = conn.execute(
        """select performed_on, workout_title, count(*) as sets from strength_sets
           where performed_on between %s and %s and not excluded and coalesce(set_type, 'normal') <> 'warmup'
           group by performed_on, workout_title order by performed_on""", (ws, we)).fetchall()
    rec = conn.execute("select * from recovery where day between %s and %s order by day", (ws, we)).fetchall()
    flags = conn.execute("select flag_date, kind, severity, message from flags where flag_date between %s and %s",
                         (ws, we)).fetchall()
    notes = conn.execute("select note_date, type, text from weekly_notes where week_start = %s or "
                         "note_date between %s and %s", (ws, ws, we)).fetchall()
    base = (db_profile(conn) or {}).get("resting_hr_baseline")

    done = [p for p in planned if p["activity_id"] or p["status"] == "done"]
    by_sport: dict[str, dict] = {}
    for a in acts:
        s = by_sport.setdefault(a["sport"], {"sessions": 0, "minutes": 0.0, "miles": 0.0})
        s["sessions"] += 1
        s["minutes"] += (a["duration_s"] or 0) / 60
        s["miles"] += (a["distance_m"] or 0) / MI
    for s in by_sport.values():
        s["minutes"], s["miles"] = round(s["minutes"]), round(s["miles"], 1)
    runs = [a for a in acts if a["sport"] == "run"]
    episode = db.open_episode(conn, we)
    g = gate(episode, MorningSignals(), we)
    rhr = [r["resting_hr"] for r in rec if r["resting_hr"]]
    return {
        "week_start": ws, "week_end": we,
        "health": {"status": g.status.value, "reasons": list(g.reasons)},
        "planned_sessions": len(planned), "completed_sessions": len(done),
        "compliance": round(len(done) / len(planned), 2) if planned else None,
        "missed": [{"date": p["plan_date"], "title": p["title"]} for p in planned
                   if not (p["activity_id"] or p["status"] == "done") and p["plan_date"] <= we],
        "planned_run_mi": round(sum(p["distance_mi"] or 0 for p in planned if p["sport"] == "run"), 1),
        "actual_run_mi": round(sum((a["distance_m"] or 0) for a in runs) / MI, 1),
        "long_run_mi": round(max(((a["distance_m"] or 0) / MI for a in runs), default=0), 1),
        "by_sport": by_sport,
        "strength_sessions": [{"date": s["performed_on"], "title": s["workout_title"], "sets": s["sets"]}
                              for s in strength],
        "load_trimp": round(sum(a["load_trimp"] or 0 for a in acts)),
        "worst_decoupling": max((a["decoupling"] for a in runs if a["decoupling"] is not None), default=None),
        "recovery": {
            "avg_readiness": round(mean(r["readiness"] for r in rec if r["readiness"])) if any(r["readiness"] for r in rec) else None,
            "avg_sleep_h": round(mean(r["total_sleep_s"] / 3600 for r in rec if r["total_sleep_s"]), 1) if any(r["total_sleep_s"] for r in rec) else None,
            "avg_resting_hr": round(mean(rhr), 1) if rhr else None,
            "resting_hr_baseline": base,
        },
        "flags": {"stop": [f["message"] for f in flags if f["severity"] == "stop"],
                  "warn": [f["message"] for f in flags if f["severity"] == "warn"]},
        "notes": [{"date": n["note_date"], "type": n["type"], "text": n["text"]} for n in notes],
    }


def db_profile(conn) -> dict | None:
    return conn.execute("select * from profile where id = 1").fetchone()


def decide(summary: dict) -> dict:
    """Next week's volume factor, from rules. Returns the factor and why."""
    h = summary["health"]["status"]
    if h in (Status.HOLD.value, Status.RETURN.value):
        return {"factor": 1.0, "why": [f"Health status {h}: the return ramp sets the volume, not the report."]}
    why, factor = [], 1.08
    c = summary["compliance"]
    rec = summary["recovery"]
    if c is not None and c < 0.6:
        factor, why = 0.9, why + [f"Only {int(c * 100)}% of sessions done: repeat the week at a little less, don't build."]
    elif c is not None and c < 0.85:
        factor, why = 1.0, why + [f"{int(c * 100)}% of sessions done: hold volume steady."]
    if summary["flags"]["stop"]:
        factor, why = min(factor, 0.9), why + ["A STOP flag this week: back off 10%."]
    if rec["avg_readiness"] is not None and rec["avg_readiness"] < 70:
        factor, why = min(factor, 0.9), why + [f"Average Oura readiness {rec['avg_readiness']} (<70): back off."]
    if (rec["avg_resting_hr"] and rec["resting_hr_baseline"]
            and rec["avg_resting_hr"] >= rec["resting_hr_baseline"] + 5):
        factor, why = min(factor, 0.9), why + ["Resting HR 5+ above baseline on average: back off."]
    if (summary["worst_decoupling"] or 0) > 0.05:
        factor, why = min(factor, 1.0), why + ["HR drift over 5% on a run: no volume increase."]
    if factor == 1.08:
        why.append("Week done as planned with normal recovery: build about 8% (the 10% rule caps it).")
    return {"factor": factor, "why": why}


SYSTEM = """You write Patrick's weekly training report. He is an amateur triathlete \
(IRONMAN 70.3 Puerto Rico on Mar 14 2027 is the main goal) and a self-described AI layman: \
write plainly, short sentences, no jargon without a one-line explanation.

Use only the numbers given. Never invent data, never change the plan, never suggest ending a \
health hold or training through one. Format (markdown, under 220 words):
**The week in one line**
**What went well** (2-3 bullets)
**What to watch** (1-3 bullets)
**Next week** (2-3 bullets: what changes and why, from the plan and the decision given)"""


def narrative(summary: dict, decision: dict, next_week: list[dict]) -> tuple[str, str | None]:
    """(text, model). Falls back to a plain summary if the model is unavailable."""
    try:
        from app import llm
        m = llm.model()
        msg = llm.client().messages.create(
            model=m, max_tokens=900, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(
                {"week": summary, "decision": decision, "next_week_plan": next_week}, default=str)}])
        return llm.text_of(msg), m
    except Exception as e:  # report still gets saved without the narrative
        lines = [f"**The week in one line**\n{summary['completed_sessions']} of {summary['planned_sessions']} "
                 f"sessions, {summary['actual_run_mi']} run miles.",
                 "**Next week**", *[f"- {w}" for w in decision["why"]],
                 f"\n_(Narrative unavailable: {type(e).__name__}.)_"]
        return "\n".join(lines), None


def build(conn, ws: date, *, replan: bool = True, today: date | None = None) -> dict:
    """Summarize the week starting ``ws``, re-plan the next 3 weeks, save."""
    from app.planning import generator
    summary = summarize(conn, ws)
    decision = decide(summary)
    nxt = ws + timedelta(days=7)
    from app import clock
    today = today or clock.today()
    # Plan from whichever is later: the week after the report, or this week.
    first = max(nxt, today - timedelta(days=today.weekday()))
    plans = generator.generate(conn, first, weeks=3, factor=decision["factor"], today=today) if replan else []
    next_week = [{"date": x.date, "title": x.title, "mi": x.distance_mi, "min": x.duration_min}
                 for x in (plans[0].drafts if plans else [])]
    text, model = narrative(summary, decision, next_week)
    summary["decision"] = decision
    summary["next_week"] = next_week
    summary["next_week_flags"] = plans[0].flags if plans else []
    conn.execute(
        """insert into weekly_summaries (week_start, summary, narrative, model) values (%s, %s::jsonb, %s, %s)
           on conflict (week_start) do update set summary = excluded.summary, narrative = excluded.narrative,
             model = excluded.model, generated_at = now()""",
        (ws, json.dumps(summary, default=str), text, model))
    conn.commit()
    return {"week_start": ws, "summary": summary, "narrative": text, "model": model}


def list_reports(conn, limit: int = 52) -> list[dict]:
    return conn.execute("select week_start, narrative, summary, model, generated_at from weekly_summaries "
                        "order by week_start desc limit %s", (limit,)).fetchall()
