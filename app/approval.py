"""Weekly plan approval (Patrick, Nov 22 2026).

On Sunday (after the weekly report) he gets one notification: next week's plan is
ready. He looks it over and approves it in the app. Approving:
  * snapshots each session's suggested time (best time: his training windows,
    work meetings, weather) so the calendar shows real time blocks;
  * lets the week go to Garmin (structured workouts) and to the Training
    calendar feed.
Changes the app makes inside an approved week (a rebase, a moved session) still
flow through by themselves; a session with no snapshot gets its time worked out
when the calendar is read.
"""
from __future__ import annotations

import json
from datetime import date, timedelta


def week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_to_approve(today: date) -> date:
    """From Sunday on, next week; otherwise this week."""
    return week_of(today) + timedelta(days=7) if today.weekday() == 6 else week_of(today)


def approved(conn, ws: date) -> dict | None:
    r = conn.execute("select * from plan_approvals where week_start = %s", (ws,)).fetchone()
    return r and dict(r)


def approved_weeks(conn, start: date, end: date) -> dict[date, dict]:
    rows = conn.execute("select * from plan_approvals where week_start between %s and %s",
                        (week_of(start), week_of(end))).fetchall()
    return {r["week_start"]: dict(r) for r in rows}


def preview(conn, ws: date, today: date) -> dict:
    """The week as it would be approved: each session with its suggested time."""
    from app import today as view
    plan = view.plan(conn, ws, 7, today=today)
    sessions = []
    for d in plan["days"]:
        for s in d["sessions"]:
            if s["status"] not in ("planned", None) or d["date"] < today:
                continue
            bt = s.get("best_time") or {}
            sessions.append({"id": s["id"], "date": d["date"], "sport": s["sport"], "title": s["title"],
                             "duration_min": s["duration_min"], "start": bt.get("start"), "end": bt.get("end"),
                             "label": bt.get("label")})
    a = approved(conn, ws)
    return {"week_start": ws, "approved_at": a and a["approved_at"], "sessions": sessions,
            "timing_note": plan.get("timing_note")}


def approve(conn, ws: date, today: date) -> dict:
    """Snapshot the times, mark the week approved, and send it to Garmin."""
    p = preview(conn, ws, today)
    snap = {str(s["id"]): {k: (v.isoformat() if isinstance(v, date) else v) for k, v in s.items() if k != "id"}
            for s in p["sessions"]}
    conn.execute("""insert into plan_approvals (week_start, sessions) values (%s, %s::jsonb)
                    on conflict (week_start) do update set approved_at = now(), sessions = excluded.sessions""",
                 (ws, json.dumps(snap)))
    conn.commit()
    garmin = None
    try:
        from app.integrations import garmin_push
        garmin = garmin_push.sync(conn, today)
    except Exception as e:                       # the approval stands; Garmin retries each morning
        garmin = {"errors": [f"{type(e).__name__}: {e}"[:200]]}
    return {"week_start": ws, "sessions": len(snap), "garmin": garmin}
