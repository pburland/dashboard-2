"""Pat-GPT: the coaching chat, grounded in Patrick's own data.

Each question goes to the model with a fresh snapshot of the data:
health state, plan with briefs and best times, recent workouts, recovery,
weekly reports, weather where he is, and when his work calendar is busy.

The model explains and advises. It cannot change the plan or end a health
hold. It has two tools: log a note (illness, injury, travel, context...),
which the weekly report and the plan generator read, and start a health
hold when Patrick reports being sick or hurt (only code and the doctor's
clearance ever end one).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from app import clock, db, travel
from app.health.state import EXIT_CRITERIA, MorningSignals, gate, missing_criteria

MI = 1609.344
HISTORY_MESSAGES = 20
MAX_TOOL_ROUNDS = 4

SYSTEM = """You are Pat-GPT, Patrick's training assistant inside his training app. Patrick is an \
amateur triathlete in Arlington, VA. Main goal: IRONMAN 70.3 Puerto Rico, Mar 14 2027 (goal 6:23, \
stretch 6:00). Then IRONMAN Lake Placid, Jul 25 2027. He also lifts.

How to answer:
- Plain language. He calls himself an AI and tech layman. Short answers first, detail if asked.
- Ground every claim in the DATA block below; quote the numbers. If the data doesn't say, say so.
- The plan is made by code (Joe Friel periodization plus safety rules) and re-planned each Sunday \
from the weekly report. You explain it and can suggest adjustments, but you cannot change it. If he \
wants a change, tell him what you'd change and that the system updates the plan on Sunday (or he can \
ask Claude, the engineer, to change a rule).
- Health comes first. You can never end or shorten a health hold, or tell him to train through one. \
Only his doctor's clearance, recorded in the system, ends it. For anything medical, defer to his doctor.
- When he mentions something the system should remember (illness, injury, pain, travel, a missed or \
extra workout, how he felt, equipment), call log_note. If he reports being sick (fever, mono flare, \
etc.) or injured badly enough to stop training, call start_health_hold too.
- Times are local to where he is. Best-time suggestions already account for weather and his work calendar."""

TOOLS = [
    {"name": "log_note",
     "description": "Save a note the training system will remember and use (weekly report, plan).",
     "input_schema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": ["injury", "illness", "untracked_activity", "context",
                                             "nutrition", "travel", "mental", "equipment"]},
         "text": {"type": "string", "description": "One or two sentences, in Patrick's terms."},
         "date": {"type": "string", "description": "YYYY-MM-DD the note is about; default today."},
         "sport": {"type": "string"},
         "duration_min": {"type": "number"}},
         "required": ["type", "text"]}},
    {"name": "start_health_hold",
     "description": "Open a health hold: all workouts stop until a doctor clears him. Only when he "
                    "reports illness or injury that should stop training. Cannot be undone from chat.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["illness", "injury"]},
         "reason": {"type": "string"}}, "required": ["kind", "reason"]}},
]


# ── context ──────────────────────────────────────────────────────────────
def context(conn, today: date) -> dict:
    from app import reports, today as view
    t = view.build(conn, today, next_days=4)
    plan = view.plan(conn, today, 14, today=today)
    episode = db.open_episode(conn, today)
    g = gate(episode, MorningSignals(), today)
    acts = conn.execute(
        """select local_date, sport, title, distance_m, duration_s, avg_hr, decoupling, load_trimp
           from activities where local_date >= %s order by local_date desc""",
        (today - timedelta(days=21),)).fetchall()
    rec = conn.execute("select day, readiness, sleep_score, resting_hr, hrv_ms, temp_deviation_c, total_sleep_s "
                       "from recovery where day >= %s order by day desc", (today - timedelta(days=14),)).fetchall()
    notes = conn.execute("select note_date, type, text from weekly_notes where recorded_at > now() - interval '45 days' "
                         "order by recorded_at desc limit 30").fetchall()
    goals = conn.execute("select name, status, due_date, notes from goals").fetchall()
    body = conn.execute("select * from body_metrics order by day desc limit 1").fetchone()
    reps = reports.list_reports(conn, 2)
    return {
        "now": clock.now().isoformat(timespec="minutes"),
        "where": t.get("where"),
        "health": {"status": g.status.value, "reasons": list(g.reasons),
                   "episode": episode and {"kind": episode.kind, "since": episode.started_on,
                                           "reason": episode.reason,
                                           "expected_clear_on": episode.expected_clear_on,
                                           "missing_to_exit": [EXIT_CRITERIA[k] for k in missing_criteria(episode)]
                                           if episode.return_started_on is None else []}},
        "phase": t["phase"],
        "races": t["races"],
        "goals": goals,
        "readiness_today": t["readiness"],
        "plan_next_14_days": [{"date": d["date"], "sessions": [_brief_session(s) for s in d["sessions"]]}
                              for d in plan["days"] if d["sessions"]],
        "timing_note": plan["timing_note"],
        "long_run_gate": t["long_run_gate"],
        "recent_workouts_21d": [{"date": a["local_date"], "sport": a["sport"], "title": a["title"],
                                 "mi": round((a["distance_m"] or 0) / MI, 2),
                                 "min": round((a["duration_s"] or 0) / 60), "avg_hr": a["avg_hr"],
                                 "hr_drift": a["decoupling"]} for a in acts],
        "recovery_14d": [dict(r) | {"sleep_h": round((r["total_sleep_s"] or 0) / 3600, 1)} for r in rec],
        "weekly_reports": [{"week_start": r["week_start"], "narrative": r["narrative"],
                            "decision": (r["summary"] or {}).get("decision")} for r in reps],
        "notes_45d": notes,
        "body_latest": body,
        "fuel_today": t.get("fuel"),
        "resting_metabolic_rate": conn.execute(
            "select rmr_kcal, rmr_measured_on, rmr_note from profile where id = 1").fetchone(),
        "weather_next_3_days": _weather(conn, today),
        "work_calendar_busy_next_3_days": _busy(today),
    }


def _brief_session(s: dict) -> dict:
    st = s.get("structure") or {}
    return {k: v for k, v in {
        "title": s.get("title"), "sport": s.get("sport"), "mi": s.get("distance_mi"),
        "min": s.get("duration_min"), "zone": s.get("max_zone"), "status": s.get("status"),
        "brief": st.get("brief"), "preview": st.get("preview"), "provisional": st.get("provisional"),
        "best_time": (s.get("best_time") or {}).get("label"), "why_then": (s.get("best_time") or {}).get("why"),
        "actual": s.get("actual"), "flags": st.get("flags")}.items() if v not in (None, [], {})}


def _weather(conn, today: date) -> list[dict] | str:
    from app.analysis.heat import heat_index_f
    from app.integrations import weather
    try:
        place = travel.place_for(travel.load(conn), today)
        hours = weather.hourly_forecast(3, place if place.away else None)
    except Exception as e:
        return f"unavailable ({type(e).__name__})"
    out: dict[date, dict] = {}
    for h in hours:
        if not 5 <= h.time.hour <= 21:
            continue
        d = out.setdefault(h.time.date(), {"date": h.time.date(), "place": place.name, "feels_min_f": 999,
                                           "feels_max_f": -999, "max_heat_index_f": 0, "max_rain_pct": 0})
        f = h.feels_f if h.feels_f is not None else h.temp_f
        d["feels_min_f"], d["feels_max_f"] = round(min(d["feels_min_f"], f)), round(max(d["feels_max_f"], f))
        d["max_heat_index_f"] = max(d["max_heat_index_f"], heat_index_f(h.temp_f, h.rel_humidity))
        d["max_rain_pct"] = max(d["max_rain_pct"], h.precip_pct or 0)
    return list(out.values())


def _busy(today: date) -> list[str] | str:
    from app.integrations import calendar
    try:
        b = calendar.busy(today, today + timedelta(days=2), clock.tz())
    except Exception as e:
        return "not connected" if "GOOGLE_CALENDAR_ICS_URL" in str(e) else f"unavailable ({type(e).__name__})"
    return [f"{s:%a %b %-d %-I:%M %p}-{e:%-I:%M %p}" for s, e in b]


# ── tools ────────────────────────────────────────────────────────────────
def run_tool(conn, name: str, args: dict, today: date) -> dict:
    if name == "log_note":
        d = date.fromisoformat(args["date"]) if args.get("date") else today
        conn.execute(
            """insert into weekly_notes (week_start, note_date, type, sport, duration_min, text, source)
               values (%s, %s, %s, %s, %s, %s, 'chat')""",
            (d - timedelta(days=d.weekday()), d, args["type"], args.get("sport"),
             args.get("duration_min"), args["text"]))
        return {"saved": True, "type": args["type"], "date": d.isoformat()}
    if name == "start_health_hold":
        if db.open_episode(conn) is not None:
            return {"opened": False, "why": "a health episode is already open"}
        conn.execute("insert into health_episodes (kind, started_on, reason, notes) values (%s, %s, %s, %s)",
                     (args["kind"], today, args["reason"], "Opened from Pat-GPT chat."))
        return {"opened": True, "note": "All workouts are suppressed until clearance is recorded."}
    return {"error": f"unknown tool {name}"}


# ── a turn ───────────────────────────────────────────────────────────────
def ask(conn, message: str, conversation_id: int | None = None) -> dict:
    from app import llm
    today = clock.today()
    if conversation_id is None:
        conversation_id = conn.execute("insert into conversations (title) values (%s) returning id",
                                       (message[:60],)).fetchone()["id"]
    prior = conn.execute(
        "select role, content from messages where conversation_id = %s order by created_at desc limit %s",
        (conversation_id, HISTORY_MESSAGES)).fetchall()[::-1]
    conn.execute("insert into messages (conversation_id, role, content) values (%s, 'user', %s)",
                 (conversation_id, message))
    conn.commit()

    ctx = context(conn, today)
    system = [{"type": "text", "text": SYSTEM},
              {"type": "text", "text": "DATA (JSON, as of now):\n" + json.dumps(ctx, default=str)}]
    msgs: list[dict] = []
    for r in [*prior, {"role": "user", "content": message}]:
        if msgs and msgs[-1]["role"] == r["role"]:        # e.g. an earlier turn that failed
            msgs[-1]["content"] += "\n\n" + r["content"]
        else:
            msgs.append({"role": r["role"], "content": r["content"]})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.pop(0)
    model = llm.model()
    client = llm.client()
    actions = []
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=model, max_tokens=1500, system=system, tools=TOOLS, messages=msgs)
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if resp.stop_reason != "tool_use" or not uses:
            break
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for u in uses:
            out = run_tool(conn, u.name, u.input, today)
            actions.append({"tool": u.name, "input": u.input, "result": out})
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out)})
        conn.commit()
        msgs.append({"role": "user", "content": results})
    reply = llm.text_of(resp) or "(no answer)"
    conn.execute(
        """insert into messages (conversation_id, role, content, context_snapshot, model)
           values (%s, 'assistant', %s, %s::jsonb, %s)""",
        (conversation_id, reply, json.dumps({"actions": actions, "as_of": ctx["now"]}, default=str), model))
    conn.commit()
    return {"conversation_id": conversation_id, "reply": reply, "actions": actions}


def conversations(conn, limit: int = 30) -> list[dict]:
    return conn.execute(
        """select c.id, c.title, c.created_at, max(m.created_at) as last_at, count(m.id) as messages
           from conversations c left join messages m on m.conversation_id = c.id
           group by c.id order by last_at desc nulls last limit %s""", (limit,)).fetchall()


def messages(conn, conversation_id: int) -> list[dict]:
    return conn.execute(
        """select role, content, created_at, context_snapshot -> 'actions' as actions from messages
           where conversation_id = %s order by created_at""", (conversation_id,)).fetchall()
