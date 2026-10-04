"""Pat-GPT: the coaching chat, grounded in Patrick's own data.

Each question goes to the model with a fresh snapshot of the data:
health state, plan with briefs and best times, recent workouts, recovery,
weekly reports, weather where he is, and when his work calendar is busy.

The model explains and advises, and can change the plan only through
app/planning/changes.py: it proposes, the code validates (health gate,
validator, travel, calendar), Patrick confirms in a later message or with
the card's button, and only then is anything written, with an audit row.
It can never end a health hold or get past a STOP.
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
- Style: direct, plain words, no exclamation marks. One or two sentences unless he asks for more.
- The plan is made by code (Joe Friel periodization plus safety rules) and re-planned each Sunday. \
You can change it only like this: get_plan_window (and find_free_slots when timing matters) -> \
propose_change -> tell him the change and quote every warning -> wait. Only after he clearly says yes \
in a later message do you call apply_change, passing the keys of the warnings he accepted. Never \
propose and apply in the same turn. One confirmation covers one proposal, never "handle my week".
- If propose_change returns a STOP (status "refused"), refuse in one sentence quoting the reason and \
offer the nearest compliant alternative (check it with propose_change first).
- Health comes first. You can never end or shorten a health hold, or tell him to train through one. \
Only his doctor's clearance, recorded in the system, ends it. For anything medical, defer to his doctor.
- Travel he mentions goes in with add_travel. Lasting preferences ("I lift mornings") go in with \
save_preference.
- When he mentions something the system should remember (illness, injury, pain, travel, a missed or \
extra workout, how he felt, equipment), call log_note. If he reports being sick (fever, mono flare, \
etc.) or injured badly enough to stop training, call start_health_hold too.
- Times are local to where he is. Best-time suggestions already account for weather and his work calendar."""

ACTION_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["move", "swap", "remove", "add", "modify"]},
    "workout_id": {"type": "integer"}, "to": {"type": "string", "description": "YYYY-MM-DD (move)"},
    "workout_id_a": {"type": "integer"}, "workout_id_b": {"type": "integer"},
    "reason": {"type": "string"}, "plan_date": {"type": "string", "description": "YYYY-MM-DD (add)"},
    "sport": {"type": "string", "enum": ["run", "bike", "swim", "strength"]}, "title": {"type": "string"},
    "duration_min": {"type": "number"}, "distance_mi": {"type": "number"},
    "max_zone": {"type": "string", "enum": ["Z1", "Z2", "Z3", "Z4"]}, "is_long": {"type": "boolean"}},
    "required": ["action"]}

TOOLS = [
    {"name": "get_plan_window",
     "description": "Planned sessions (with ids), each day's health gate, travel and flags between two dates.",
     "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
                      "required": ["start", "end"]}},
    {"name": "find_free_slots",
     "description": "Free windows on a day inside Patrick's training windows, after work-calendar events.",
     "input_schema": {"type": "object", "properties": {"day": {"type": "string"},
                                                       "min_minutes": {"type": "integer"}},
                      "required": ["day"]}},
    {"name": "propose_change",
     "description": "Validate a plan change and hold it for Patrick's confirmation. Writes nothing. "
                    "Actions: move {workout_id, to}, swap {workout_id_a, workout_id_b}, remove {workout_id, reason}, "
                    "modify {workout_id, + fields to change}, add {plan_date, sport, title, duration_min, ...}.",
     "input_schema": {"type": "object", "properties": {
         "actions": {"type": "array", "items": ACTION_SCHEMA},
         "reason": {"type": "string", "description": "Why, in Patrick's words (e.g. 'dinner Saturday')."}},
         "required": ["actions", "reason"]}},
    {"name": "apply_change",
     "description": "Apply a proposal Patrick explicitly confirmed in a later message. Pass the keys of "
                    "every warning he accepted. Fails if the plan changed or a rule now blocks it.",
     "input_schema": {"type": "object", "properties": {
         "proposal_id": {"type": "string"},
         "accepted_warns": {"type": "array", "items": {"type": "string"}}}, "required": ["proposal_id"]}},
    {"name": "replan_week",
     "description": "Re-plan one week with the planner (same rules as the Sunday plan) and hold the result "
                    "as a proposal for Patrick to confirm. Use when he asks to rebuild or rebalance a week.",
     "input_schema": {"type": "object", "properties": {
         "week_start": {"type": "string", "description": "Monday, YYYY-MM-DD"}}, "required": ["week_start"]}},
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
    {"name": "add_travel",
     "description": "Record a trip so the plan works around it. can_train lists what he can do there "
                    "(e.g. ['run']); empty means no training (travel days).",
     "input_schema": {"type": "object", "properties": {
         "start_date": {"type": "string"}, "end_date": {"type": "string"}, "place": {"type": "string"},
         "can_train": {"type": "array", "items": {"type": "string", "enum": ["run", "bike", "swim", "strength"]}}},
         "required": ["start_date", "end_date", "place", "can_train"]}},
    {"name": "save_preference",
     "description": "Remember a lasting preference, e.g. key 'lifting_time' value 'mornings'.",
     "input_schema": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                      "required": ["key", "value"]}},
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
        "compliance_14d": _compliance(conn, today),
        "travel_next_21_days": [dict(r) for r in conn.execute(
            "select start_date, end_date, place, sports from travel where end_date >= %s and start_date <= %s "
            "order by start_date", (today, today + timedelta(days=21))).fetchall()],
        "check_ins_recent": conn.execute(
            "select check_in_on, rpe, felt, pain, pain_detail from check_ins order by check_in_on desc, id desc "
            "limit 3").fetchall(),
        "recurring_pain": conn.execute(
            "select flag_date, message from flags where kind = 'recurring_pain' and flag_date >= %s",
            (today - timedelta(days=14),)).fetchall(),
        "preferences": (conn.execute("select user_prefs from profile where id = 1").fetchone() or {}).get("user_prefs"),
        "plan_changes_7d": conn.execute(
            "select plan_date, action, reason, source, created_at::date as on from plan_changes "
            "where created_at > now() - interval '7 days' and undone_at is null order by created_at desc limit 10"
        ).fetchall(),
        "pending_proposals": conn.execute(
            "select id, explanation, flags, created_at from plan_proposals where status = 'pending' "
            "order by created_at desc limit 5").fetchall(),
    }


def _compliance(conn, today: date) -> dict:
    r = conn.execute(
        """select count(*) filter (where activity_id is not null or status = 'done') as done,
                  count(*) as planned from planned_workouts
           where plan_date between %s and %s and status in ('planned','done','skipped')""",
        (today - timedelta(days=14), today - timedelta(days=1))).fetchone()
    return {"done": r["done"], "planned": r["planned"],
            "pct": round(100 * r["done"] / r["planned"]) if r["planned"] else None}


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
def run_tool(conn, name: str, args: dict, today: date, turn_started=None,
             conversation_id: int | None = None) -> dict:
    from app.planning import changes
    try:
        if name == "get_plan_window":
            return plan_window(conn, date.fromisoformat(args["start"]), date.fromisoformat(args["end"]), today)
        if name == "find_free_slots":
            return free_slots(conn, date.fromisoformat(args["day"]), int(args.get("min_minutes") or 0))
        if name == "propose_change":
            return changes.propose(conn, args["actions"], source="chat", reason=args["reason"], today=today,
                                   conversation_id=conversation_id)
        if name == "replan_week":
            return replan(conn, date.fromisoformat(args["week_start"]), today, conversation_id)
        if name == "apply_change":
            p = conn.execute("select created_at, status, conversation_id from plan_proposals where id = %s",
                             (args["proposal_id"],)).fetchone()
            if not p:
                return {"applied": False, "error": "no such proposal"}
            # Confirmation must come in a message Patrick sent after the proposal, in this conversation.
            confirmed = p["conversation_id"] is not None and p["conversation_id"] == conversation_id and conn.execute(
                """select 1 from messages where conversation_id = %s and role = 'user' and created_at > %s""",
                (conversation_id, p["created_at"])).fetchone()
            if not confirmed:
                return {"applied": False, "error": "Patrick hasn't confirmed this proposal yet. Show it and wait "
                                                   "for his explicit yes in his next message (or the Confirm button)."}
            return changes.apply(conn, args["proposal_id"], args.get("accepted_warns") or [], today)
    except (changes.ChangeError, ValueError, KeyError) as e:
        conn.rollback()
        return {"error": str(e)}
    if name == "add_travel":
        s, e = date.fromisoformat(args["start_date"]), date.fromisoformat(args["end_date"])
        home = travel.home()
        try:
            conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note)
                            values (%s, %s, %s, %s, %s, %s, %s, 'from Pat-GPT')""",
                         (s, e, args["place"], home.lat, home.lng, home.tz_name, args.get("can_train") or []))
        except Exception as ex:
            conn.rollback()
            return {"saved": False, "error": f"overlaps an existing trip ({type(ex).__name__})"}
        conn.execute("""insert into weekly_notes (week_start, note_date, type, text, source)
                        values (%s, %s, 'travel', %s, 'chat')""",
                     (s - timedelta(days=s.weekday()), s, f"Travel {s:%b %-d}-{e:%b %-d}: {args['place']}"))
        return {"saved": True, "note": "The morning check will re-plan any key session it affects."}
    if name == "save_preference":
        conn.execute("update profile set user_prefs = user_prefs || jsonb_build_object(%s::text, %s::text) "
                     "where id = 1", (args["key"], args["value"]))
        return {"saved": True}
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


def replan(conn, ws: date, today: date, conversation_id: int | None) -> dict:
    from app.planning import generator, sync
    ws = ws - timedelta(days=ws.weekday())
    hist = generator.history(conn, ws)
    actual, planned = generator._week_run_mi(conn, ws - timedelta(days=7))
    cal = generator.Calendar(conn, ws, ws + timedelta(days=6))
    fixed, missed = sync.week_context(conn, ws, today)
    wp = generator.plan_week(conn, ws, basis_mi=actual or planned, hist=hist, today=today, cal=cal,
                             fixed=fixed, missed_keys=missed)
    r = sync.sync(conn, wp, today, preview=ws > today, trigger="chat", policy="propose",
                  conversation_id=conversation_id)
    return r.get("proposal") or {"status": "no_change", "message": "The planner would keep this week as it is."}


def plan_window(conn, start: date, end: date, today: date) -> dict:
    from app.planning import generator
    if (end - start).days > 31:
        end = start + timedelta(days=31)
    gate_for = generator.day_gate(conn, today, start)
    stops = travel.load(conn)
    rows = conn.execute(
        """select id, plan_date, sport, title, duration_min, distance_mi, max_zone, is_long, is_key, status,
                  structure -> 'flags' as flags, structure -> 'changed_by' as changed_by,
                  coalesce((structure ->> 'provisional')::boolean, false) as provisional
           from planned_workouts where plan_date between %s and %s and status in ('planned','done','skipped')
           order by plan_date, id""", (start, end)).fetchall()
    days = []
    d = start
    while d <= end:
        g = gate_for(d)
        p = travel.place_for(stops, d)
        days.append({"date": d, "health": g.status.value, "prescriptions_allowed": g.prescriptions_allowed,
                     "intensity_cap": g.intensity_ceiling, "travel": p.name if p.away else None,
                     "can_train_there": list(p.sports) if p.away else "anything",
                     "sessions": [dict(r) for r in rows if r["plan_date"] == d]})
        d += timedelta(days=1)
    return {"days": days}


def free_slots(conn, day: date, min_minutes: int) -> dict:
    from zoneinfo import ZoneInfo
    from app.integrations import calendar
    from app.planning import timing
    place = travel.place_for(travel.load(conn), day)
    tz = ZoneInfo(place.tz_name)
    note = None
    try:
        busy = [] if place.away else calendar.busy(day, day, tz)
    except Exception as e:
        busy, note = [], f"work calendar unavailable ({type(e).__name__})"
    slots = [(s, e) for s, e in timing.free_slots(day, tz, busy, place.away)
             if (e - s).total_seconds() / 60 >= min_minutes]
    return {"day": day, "place": place.name, "note": note,
            "slots": [f"{s:%-I:%M %p}-{e:%-I:%M %p}" for s, e in slots]}


# ── a turn ───────────────────────────────────────────────────────────────
def ask(conn, message: str, conversation_id: int | None = None) -> dict:
    from app import llm
    today = clock.today()
    if conversation_id is None:
        conversation_id = conn.execute("insert into conversations (title) values (%s) returning id",
                                       (message[:60],)).fetchone()["id"]
    summary = _summarize_if_long(conn, conversation_id)
    conv = conn.execute("select summary_upto_id from conversations where id = %s", (conversation_id,)).fetchone()
    prior = conn.execute(
        "select role, content from messages where conversation_id = %s and id > %s order by created_at desc limit %s",
        (conversation_id, (conv or {}).get("summary_upto_id") or 0, HISTORY_MESSAGES)).fetchall()[::-1]
    turn_started = conn.execute("insert into messages (conversation_id, role, content) values (%s, 'user', %s) "
                                "returning created_at", (conversation_id, message)).fetchone()["created_at"]
    conn.commit()

    ctx = context(conn, today)
    system = [{"type": "text", "text": SYSTEM},
              {"type": "text", "text": "DATA (JSON, as of now):\n" + json.dumps(ctx, default=str)}]
    if summary:
        system.append({"type": "text", "text": "Earlier in this conversation (summary):\n" + summary})
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
            out = run_tool(conn, u.name, u.input, today, turn_started, conversation_id)
            actions.append({"tool": u.name, "input": u.input, "result": json.loads(json.dumps(out, default=str))})
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out, default=str)})
        conn.commit()
        msgs.append({"role": "user", "content": results})
    reply = llm.text_of(resp) or "(no answer)"
    conn.execute(
        """insert into messages (conversation_id, role, content, context_snapshot, model)
           values (%s, 'assistant', %s, %s::jsonb, %s)""",
        (conversation_id, reply, json.dumps({"actions": actions, "as_of": ctx["now"]}, default=str), model))
    conn.commit()
    return {"conversation_id": conversation_id, "reply": reply, "actions": actions}


SUMMARIZE_OVER = 24


def _summarize_if_long(conn, conversation_id: int) -> str | None:
    """Past ~20 messages, fold the older ones into conversations.summary."""
    c = conn.execute("select summary, summary_upto_id from conversations where id = %s", (conversation_id,)).fetchone()
    if not c:
        return None
    rows = conn.execute("select id, role, content from messages where conversation_id = %s and id > %s order by id",
                        (conversation_id, c["summary_upto_id"] or 0)).fetchall()
    if len(rows) <= SUMMARIZE_OVER:
        return c["summary"]
    old = rows[:-HISTORY_MESSAGES]
    try:
        from app import llm
        text = "\n".join(f"{r['role']}: {r['content']}" for r in old)
        msg = llm.client().messages.create(
            model=llm.model(), max_tokens=600,
            system="Summarize this training-chat history in under 150 words: decisions made, plan changes "
                   "applied or refused, preferences, health facts. Plain sentences.",
            messages=[{"role": "user", "content": (f"Previous summary: {c['summary']}\n\n" if c["summary"] else "")
                       + text}])
        summary = llm.text_of(msg)
    except Exception:
        return c["summary"]
    conn.execute("update conversations set summary = %s, summary_upto_id = %s where id = %s",
                 (summary, old[-1]["id"], conversation_id))
    conn.commit()
    return summary


def conversations(conn, limit: int = 30) -> list[dict]:
    return conn.execute(
        """select c.id, c.title, c.created_at, max(m.created_at) as last_at, count(m.id) as messages
           from conversations c left join messages m on m.conversation_id = c.id
           group by c.id order by last_at desc nulls last limit %s""", (limit,)).fetchall()


def messages(conn, conversation_id: int) -> list[dict]:
    return conn.execute(
        """select role, content, created_at, context_snapshot -> 'actions' as actions from messages
           where conversation_id = %s order by created_at""", (conversation_id,)).fetchall()
