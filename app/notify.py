"""Phone notifications: what to send, when, and how often.

Patrick's rules (2026-10-04):
  * iPhone only (the app on his Home Screen), full detail on the lock screen.
  * 8:30 PM the night before a training day: tomorrow's sessions, best time, weather.
  * 5:45 AM, only if something changed overnight: safety (readiness, resting
    HR, heat, check-in caution) and plan changes / changes awaiting OK.
  * "How was it?" 1 hour after the suggested end of each session.
  * Weekly report ready (Sunday evening).
  * During a health hold: only the report, plus "Cleared by your doctor?"
    on the expected clearance date and every 3 days after.
  * Quiet 9:30 PM - 5:30 AM (local time wherever he is), at most 4 a day;
    extras fold into one combined notification.
Each kind can be switched off in the app (profile.notification_prefs).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta

from psycopg.types.json import Jsonb

from app import clock, db

log = logging.getLogger("training.notify")

QUIET_START, QUIET_END = time(21, 30), time(5, 30)
DAILY_MAX = 4
EVENING_AT = time(20, 30)
MORNING_AT = time(5, 45)
CLEARANCE_AT = time(9, 0)
CLEARANCE_EVERY_DAYS = 3
KINDS = ("workout", "plan", "safety", "checkin", "report", "clearance")


# ── queue ────────────────────────────────────────────────────────────────
def prefs(conn) -> dict:
    r = conn.execute("select notification_prefs from profile where id = 1").fetchone()
    return {k: True for k in KINDS} | ((r or {}).get("notification_prefs") or {})


def queue(conn, kind: str, title: str, body: str, *, url: str = "/", dedupe: str | None = None,
          not_before: datetime | None = None, data: dict | None = None, pref: str | None = None) -> bool:
    """Queue one notification. False if that kind is switched off or it's a duplicate."""
    if kind != "test" and not prefs(conn).get(pref or kind, True):
        return False
    r = conn.execute(
        """insert into notifications (kind, title, body, url, dedupe_key, not_before, data)
           values (%s, %s, %s, %s, %s, coalesce(%s, now()), %s) on conflict (dedupe_key) do nothing returning id""",
        (kind, title, body, url, dedupe, not_before, Jsonb(data or {}))).fetchone()
    return r is not None


def _quiet(t: time) -> bool:
    return t >= QUIET_START or t < QUIET_END


def _still_relevant(conn, n: dict) -> bool:
    """A check-in reminder is moot once he has checked in or the session changed."""
    if n["kind"] == "checkin":
        pid = (n["data"] or {}).get("planned_workout_id")
        row = conn.execute(
            """select w.status, exists(select 1 from check_ins c where c.planned_workout_id = w.id) as done_ci
               from planned_workouts w where w.id = %s""", (pid,)).fetchone()
        return bool(row) and row["status"] in ("planned", "done") and not row["done_ci"]
    if n["kind"] == "clearance":
        ep = db.open_episode(conn)
        return bool(ep) and ep.return_started_on is None
    return True


def dispatch(conn, now: datetime | None = None, sender=None, only_tests: bool = False) -> list[dict]:
    """Send what's due, honouring quiet hours and the daily limit (a test from
    the settings button ignores both). Returns what went out."""
    now = now or clock.now()
    if _quiet(now.time()) and not only_tests:
        return []
    due = [dict(r) for r in conn.execute(
        "select * from notifications where status = 'queued' and not_before <= %s "
        + ("and kind = 'test' " if only_tests else "") + "order by not_before, id", (now,)).fetchall()]
    due_live = []
    for n in due:
        if _still_relevant(conn, n):
            due_live.append(n)
        else:
            conn.execute("update notifications set status = 'skipped' where id = %s", (n["id"],))
    if not due_live:
        conn.commit()
        return []
    day_start = datetime.combine(now.date(), time(0), now.tzinfo)
    sent_today = conn.execute(
        """select count(distinct sent_at) as n from notifications
           where status in ('sent', 'folded') and kind <> 'test' and sent_at >= %s and sent_at < %s""",
        (day_start, day_start + timedelta(days=1))).fetchone()["n"]
    slots = DAILY_MAX - sent_today
    tests = [n for n in due_live if n["kind"] == "test"]
    rest = [n for n in due_live if n["kind"] != "test"] if slots > 0 else []
    batches: list[list[dict]] = [[n] for n in tests]
    if not rest:
        pass                        # nothing, or the daily limit is reached: waits for tomorrow
    elif len(rest) <= slots:
        batches += [[n] for n in rest]
    else:                           # fold the extras into the last notification
        batches += [[n] for n in rest[:slots - 1]] + [rest[slots - 1:]]
    out = []
    for i, group in enumerate(batches):
        msg = _message(group)
        ok, err = _deliver(conn, msg, sender)
        stamp = now + timedelta(microseconds=i)          # one stamp per delivery, on the app's clock
        for n in group:
            status = ("sent" if len(group) == 1 else "folded") if ok else "failed"
            conn.execute("update notifications set status = %s, sent_at = %s, error = %s where id = %s",
                         (status, stamp, err, n["id"]))
        if ok:
            out.append(msg)
    conn.commit()
    return out


def _message(group: list[dict]) -> dict:
    if len(group) == 1:
        n = group[0]
        return {"title": n["title"], "body": n["body"], "url": n["url"], "tag": n["kind"]}
    return {"title": f"{len(group)} training updates",
            "body": " · ".join(f"{n['title']}: {n['body']}" for n in group)[:600], "url": "/", "tag": "digest"}


def _deliver(conn, msg: dict, sender=None) -> tuple[bool, str | None]:
    from app.integrations import webpush
    subs = conn.execute("select endpoint, keys from push_subscriptions").fetchall()
    if not subs:
        return False, "no phone subscribed"
    contact = (conn.execute("select extra from integrations where provider = 'vapid'").fetchone() or {}) \
        .get("extra", {}).get("contact") or "mailto:training@example.invalid"
    ok, errors = False, []
    for s in subs:
        sub = {"endpoint": s["endpoint"], "keys": s["keys"]}
        try:
            (sender or webpush.send)(conn, sub, msg, contact)
            ok = True
        except webpush.Gone:
            conn.execute("delete from push_subscriptions where endpoint = %s", (s["endpoint"],))
        except Exception as e:                      # one bad phone never blocks the rest
            errors.append(f"{type(e).__name__}: {e}"[:300])
    return ok, "; ".join(errors) or None


# ── what to say ──────────────────────────────────────────────────────────
def _fmt_session(s: dict) -> str:
    bits = [s["title"]]
    if s.get("distance_mi"):
        bits.append(f"{s['distance_mi']:g} mi")
    elif s.get("duration_min"):
        bits.append(f"{int(s['duration_min'])} min")
    bt = s.get("best_time") or {}
    if bt.get("label"):
        bits.append(f"best {bt['label']}")
    if bt.get("feels_f") is not None:
        bits.append(f"{bt['feels_f']:.0f}°F")
    return " · ".join(bits)


def evening(conn, today: date) -> int:
    """Tomorrow's workout, plus a check-in reminder per session (1 h after its suggested end)."""
    from app import today as view
    from app.planning import generator
    tomorrow = today + timedelta(days=1)
    g = generator.day_gate(conn, today, today)(tomorrow)
    if not g.prescriptions_allowed:
        return 0
    days = view.plan(conn, tomorrow, 1, today=today)["days"]
    sessions = [s for d in days for s in d["sessions"] if s.get("status") == "planned"]
    if not sessions:
        return 0                                # rest day: nothing
    n = 0
    lines = [_fmt_session(s) for s in sessions]
    caution = f" ({g.reasons[0]})" if g.status.value == "caution" and g.reasons else ""
    if queue(conn, "workout", f"Tomorrow{caution}", "\n".join(lines), url="/", dedupe=f"workout:{tomorrow}",
             data={"sessions": [s["id"] for s in sessions], "status": g.status.value}):
        n += 1
    for s in sessions:
        bt = s.get("best_time") or {}
        if not bt.get("end"):
            continue
        at = datetime.fromisoformat(bt["end"]) + timedelta(hours=1)
        if queue(conn, "checkin", "How was it?", f"{s['title']}: three taps, or tell me you skipped it.",
                 url=f"/?checkin={s['id']}", dedupe=f"checkin:{s['id']}", not_before=at,
                 data={"planned_workout_id": s["id"]}):
            n += 1
    conn.commit()
    return n


def morning(conn, today: date, since: datetime) -> int:
    """5:45 AM: only what changed overnight (safety first, then the plan)."""
    from app.ingest import evaluate
    from app.health.state import gate
    sig = evaluate.morning_signals(conn, today)
    g = gate(db.open_episode(conn, today), sig, today)
    safety, plan = [], []
    if g.status.value == "caution":
        safety += list(g.reasons)
    heat = conn.execute("""select message from flags where flag_date = %s and kind = 'heat'
                           and severity in ('warn','stop')""", (today,)).fetchall()
    safety += [h["message"] for h in heat]
    changed = conn.execute(
        """select distinct reason from plan_changes where created_at >= %s and source in ('system','generator')
           and undone_at is null and plan_date >= %s""", (since, today)).fetchall()
    plan += [f"Plan changed: {c['reason']}" for c in changed]
    waiting = conn.execute("select explanation from plan_proposals where status = 'pending' and created_at >= %s",
                           (since,)).fetchall()
    plan += [f"Needs your OK: {w['explanation']}" for w in waiting]
    n = 0
    if safety and queue(conn, "update", "Today: easy only" if g.status.value == "caution" else "Today: heads up",
                        " ".join(safety)[:400], url="/", dedupe=f"safety:{today}", pref="safety"):
        n += 1
    if plan and queue(conn, "update", "Plan update", " ".join(plan)[:400], url="/", dedupe=f"plan:{today}",
                      pref="plan"):
        n += 1
    conn.commit()
    return n


def clearance(conn, today: date) -> int:
    ep = db.open_episode(conn, today)
    if not ep or ep.return_started_on is not None or not ep.expected_clear_on or today < ep.expected_clear_on:
        return 0
    if (today - ep.expected_clear_on).days % CLEARANCE_EVERY_DAYS:
        return 0
    ok = queue(conn, "clearance", "Cleared by your doctor?", "Tap to record it and start your comeback.",
               url="/?clear=1", dedupe=f"clearance:{today}")
    conn.commit()
    return int(ok)


def report_ready(conn, week_start: date) -> None:
    queue(conn, "report", "Your weekly report is ready", "See how the week went and what changes next week.",
          url="/?tab=reports", dedupe=f"report:{week_start}")
    conn.commit()


# ── the scheduler's minute tick ──────────────────────────────────────────
def _ran(conn, key: str) -> bool:
    return bool(conn.execute("select 1 from notifications where dedupe_key = %s", (key,)).fetchone())


def tick(conn, now: datetime | None = None) -> dict:
    """Called every minute by the scheduler. Each job runs once a day in its
    window (a marker row records it), then everything due is dispatched."""
    now = now or clock.now()
    today, t = now.date(), now.time()
    done = {}
    jobs = (("evening", EVENING_AT, lambda: evening(conn, today)),
            ("morning", MORNING_AT, lambda: morning(conn, today, now - timedelta(hours=10))),
            ("clearance", CLEARANCE_AT, lambda: clearance(conn, today)))
    for name, at, fn in jobs:
        start = datetime.combine(today, at, now.tzinfo)
        marker = f"job:{name}:{today}"
        if start <= now < start + timedelta(hours=2) and not _ran(conn, marker):
            try:
                done[name] = fn()
            except Exception:
                log.exception("notification job %s failed", name)
                conn.rollback()
            conn.execute("""insert into notifications (kind, title, body, dedupe_key, status)
                            values ('test', 'job marker', %s, %s, 'skipped') on conflict do nothing""", (name, marker))
            conn.commit()
    done["sent"] = len(dispatch(conn, now))
    return done
